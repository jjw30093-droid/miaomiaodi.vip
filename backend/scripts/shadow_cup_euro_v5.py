"""
shadow_cup_euro_v5.py
────────────────────
V5 Pure 模型对杯赛/欧战比赛的 Shadow 命中率测试。
只验证，不修改任何模型或数据库。

运行:
  cd /home/ubuntu/app/backend
  python3 scripts/shadow_cup_euro_v5.py
"""
import json
import os
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from v5_feature_engineering.inference_lambda import build_score_matrix, derive_wdl, derive_ou

# ── Config ────────────────────────────────────────────────────────────
DB_PATH     = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "football_uk.db")
MODEL_DIR   = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models_v5_lambda")
REPORT_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")
OU_LINE     = 2.5
RHO_GLOBAL  = None   # loaded from rho.json

CUP_EURO_LIDS = {
    42:    "UCL",
    73:    "UEL",
    10216: "UECL",
    132:   "FA Cup",
    133:   "EFL Cup",
    134:   "Coupe de France",
    138:   "Copa del Rey",
    141:   "Coppa Italia",
    209:   "DFB-Pokal",
}

# Known BIG5 league IDs (for team classification)
BIG5_LIDS = {47, 87, 54, 55, 53}

ENSEMBLE_FULL = 0.6
ENSEMBLE_PURE = 0.4


# ── Helpers ───────────────────────────────────────────────────────────

def load_models():
    models = {}
    for key, fname in [("H_Full","Model_H_Full.cbm"),("H_Pure","Model_H_Pure.cbm"),
                       ("A_Full","Model_A_Full.cbm"),("A_Pure","Model_A_Pure.cbm")]:
        m = CatBoostRegressor()
        m.load_model(os.path.join(MODEL_DIR, fname))
        models[key] = m
    with open(os.path.join(MODEL_DIR, "rho.json")) as f:
        rho_data = json.load(f)
    feat_full = list(models["H_Full"].feature_names_)
    feat_pure = list(models["H_Pure"].feature_names_)
    return models, rho_data, feat_full, feat_pure


def predict_row(row_df, models, feat_full, feat_pure, rho):
    """Predict lam_h, lam_a for a single feature row."""
    X_full = row_df.reindex(columns=feat_full, fill_value=0).astype(float)
    X_pure = row_df.reindex(columns=feat_pure, fill_value=0).astype(float)
    # CatBoost requires categorical features as int/str, not float
    for X in (X_full, X_pure):
        if "League_ID" in X.columns:
            X["League_ID"] = X["League_ID"].astype(int)

    lam_h = (ENSEMBLE_FULL * float(models["H_Full"].predict(X_full)[0]) +
             ENSEMBLE_PURE * float(models["H_Pure"].predict(X_pure)[0]))
    lam_a = (ENSEMBLE_FULL * float(models["A_Full"].predict(X_full)[0]) +
             ENSEMBLE_PURE * float(models["A_Pure"].predict(X_pure)[0]))
    lam_h = max(lam_h, 0.01)
    lam_a = max(lam_a, 0.01)

    matrix = build_score_matrix(lam_h, lam_a, rho=rho, max_goals=10)
    p_h, p_d, p_a = derive_wdl(matrix)
    p_over, p_under, _ = derive_ou(matrix, OU_LINE)
    return lam_h, lam_a, p_h, p_d, p_a, p_over, p_under


# ── Main ──────────────────────────────────────────────────────────────

def main():
    os.makedirs(REPORT_DIR, exist_ok=True)

    print("Loading V5 Pure models...")
    models, rho_data, feat_full, feat_pure = load_models()
    global RHO_GLOBAL
    RHO_GLOBAL = rho_data.get("rho_global", 0.0)
    print(f"  feat_full={len(feat_full)}, feat_pure={len(feat_pure)}, ρ_global={RHO_GLOBAL:.4f}")

    # ── Load cup/euro matches from mart_prediction_matrix_v5 ──────────
    conn = sqlite3.connect(DB_PATH)

    # Get cup/euro matches with complete results + features
    lid_list = ",".join(str(x) for x in CUP_EURO_LIDS)
    # mart_prediction_matrix_v5 already has home_score/away_score/team IDs/names
    # Filter via subquery to avoid duplicate columns from JOIN
    df_mat = pd.read_sql(f"""
        SELECT m.*
        FROM mart_prediction_matrix_v5 m
        WHERE m.League_ID IN ({lid_list})
          AND m.home_score IS NOT NULL
          AND m.match_id IN (
              SELECT Match_ID FROM dim_match WHERE status='Finish' AND home_score IS NOT NULL
          )
    """, conn)

    print(f"\nTotal cup/euro rows in mart_prediction_matrix_v5: {len(df_mat)}")
    print("League breakdown:")
    for lid, grp in df_mat.groupby("League_ID"):
        name = CUP_EURO_LIDS.get(int(lid), str(lid))
        has_xg = grp["diff_roll5_expected_goals"].notna().sum()
        print(f"  League {lid:5d} ({name:<20s}): {len(grp):3d} rows, xg_coverage={has_xg}/{len(grp)}")

    # ── BIG5 team set (for cross/same league classification) ──────────
    big5_teams_raw = pd.read_sql(f"""
        SELECT DISTINCT Home_Team_ID as team_id FROM dim_match
        WHERE League_ID IN ({','.join(str(x) for x in BIG5_LIDS)})
        UNION
        SELECT DISTINCT Away_Team_ID FROM dim_match
        WHERE League_ID IN ({','.join(str(x) for x in BIG5_LIDS)})
    """, conn)
    big5_team_ids = set(big5_teams_raw["team_id"].tolist())

    # ── Baseline: domestic BIG5 2025/26 acc ──────────────────────────
    # NOTE: must SELECT m.* (all features) — not just 5 columns — so that
    # predict_row's reindex(columns=feat_full, fill_value=0) doesn't zero-fill
    # the ~159 missing feature columns and produce garbage baseline predictions.
    # mart_prediction_matrix_v5 already contains home_score/away_score; no JOIN needed.
    df_dom = pd.read_sql("""
        SELECT m.*
        FROM mart_prediction_matrix_v5 m
        WHERE m.League_ID IN (47,87,54,55,53)
          AND m.Season = '2025/2026'
          AND m.home_score IS NOT NULL
          AND m.diff_roll5_expected_goals IS NOT NULL
        LIMIT 800
    """, conn)
    conn.close()

    # ── Run predictions ───────────────────────────────────────────────
    print(f"\nRunning predictions on {len(df_mat)} cup/euro matches...")

    results = []
    skipped = 0
    for _, row in df_mat.iterrows():
        # Skip if critical rolling features all NULL (can't predict)
        xg = row.get("diff_roll5_expected_goals")
        if pd.isna(xg):
            skipped += 1
            continue

        lid = int(row["League_ID"])
        # For cup/euro: use global rho (no per-league rho for these competitions)
        rho = RHO_GLOBAL

        row_df = pd.DataFrame([row.to_dict()])
        try:
            lam_h, lam_a, p_h, p_d, p_a, p_over, p_under = predict_row(
                row_df, models, feat_full, feat_pure, rho
            )
        except Exception as e:
            skipped += 1
            continue

        hs, as_ = int(row["home_score"]), int(row["away_score"])
        if hs > as_:
            actual_wdl = "home_win"
        elif hs == as_:
            actual_wdl = "draw"
        else:
            actual_wdl = "away_win"
        actual_ou = "over" if (hs + as_) > OU_LINE else "under"

        pred_wdl = max([("home_win", p_h), ("draw", p_d), ("away_win", p_a)],
                       key=lambda x: x[1])[0]
        pred_ou  = "over" if p_over > p_under else "under"

        # Classify match
        home_id = row.get("Home_Team_ID")
        away_id = row.get("Away_Team_ID")
        home_big5 = home_id in big5_team_ids
        away_big5 = away_id in big5_team_ids
        if home_big5 and away_big5:
            match_type = "both_big5"
        elif home_big5 or away_big5:
            match_type = "one_big5"
        else:
            match_type = "neither_big5"

        league_category = "domestic_cup" if lid in (132, 133, 134, 138, 141, 209) else "european"

        results.append({
            "match_id": row["match_id"],
            "League_ID": lid,
            "league_name": CUP_EURO_LIDS.get(lid, str(lid)),
            "Date": row.get("match_date", ""),
            "home": row.get("Home_Team_Name", ""),
            "away": row.get("Away_Team_Name", ""),
            "home_score": hs,
            "away_score": as_,
            "lam_h": round(lam_h, 3),
            "lam_a": round(lam_a, 3),
            "p_h": round(p_h, 3),
            "p_d": round(p_d, 3),
            "p_a": round(p_a, 3),
            "p_over": round(p_over, 3),
            "p_under": round(p_under, 3),
            "max_p": round(max(p_h, p_d, p_a), 3),
            "pred_wdl": pred_wdl,
            "actual_wdl": actual_wdl,
            "wdl_correct": int(pred_wdl == actual_wdl),
            "pred_ou": pred_ou,
            "actual_ou": actual_ou,
            "ou_correct": int(pred_ou == actual_ou),
            "match_type": match_type,
            "league_category": league_category,
            "home_big5": home_big5,
            "away_big5": away_big5,
        })

    df_res = pd.DataFrame(results)
    print(f"Predicted: {len(df_res)} | Skipped (no features): {skipped}")

    if df_res.empty:
        print("No results to report.")
        return

    # ── Baseline domestic predictions ─────────────────────────────────
    print("\nRunning baseline on domestic BIG5 2025/26 (sample 800)...")
    dom_results = []
    for _, row in df_dom.iterrows():
        xg = row.get("diff_roll5_expected_goals")
        if pd.isna(xg):
            continue
        lid = int(row["League_ID"])
        rho = rho_data.get("rho_by_league", {}).get(str(lid), RHO_GLOBAL)
        row_df = pd.DataFrame([row.to_dict()])
        try:
            lam_h, lam_a, p_h, p_d, p_a, p_over, p_under = predict_row(
                row_df, models, feat_full, feat_pure, rho
            )
        except Exception:
            continue
        hs, as_ = int(row["home_score"]), int(row["away_score"])
        actual_wdl = "home_win" if hs > as_ else ("draw" if hs == as_ else "away_win")
        actual_ou  = "over" if (hs + as_) > OU_LINE else "under"
        pred_wdl   = max([("home_win",p_h),("draw",p_d),("away_win",p_a)],key=lambda x:x[1])[0]
        pred_ou    = "over" if p_over > p_under else "under"
        dom_results.append({"wdl":int(pred_wdl==actual_wdl), "ou":int(pred_ou==actual_ou)})
    df_dom_res = pd.DataFrame(dom_results)
    dom_wdl = df_dom_res["wdl"].mean() if len(df_dom_res) else float("nan")
    dom_ou  = df_dom_res["ou"].mean()  if len(df_dom_res) else float("nan")
    print(f"  Domestic BIG5 baseline: WDL={dom_wdl:.1%} OU={dom_ou:.1%} (n={len(df_dom_res)})")

    # ── Build report ──────────────────────────────────────────────────
    lines = []
    lines.append("# V5 Shadow Test：杯赛/欧战迁移性验证报告\n")
    lines.append(f"生成时间：2026-05-07  ")
    lines.append(f"测试模型：V5 Global Pure CatBoost (ensemble 0.6 Full + 0.4 Pure)  ")
    lines.append(f"OU 基准线：{OU_LINE}，ρ：global={RHO_GLOBAL:.4f}（无联赛级别ρ）  ")
    lines.append(f"原则：只验证，不修改\n")

    # 1. Test set stats
    lines.append("## 1. 测试集统计\n")
    lines.append(f"- 总可预测场次（有 xG rolling 特征）：**{len(df_res)}**")
    lines.append(f"- 跳过（特征缺失）：{skipped}")
    lines.append(f"- 特征覆盖率：{len(df_res)/(len(df_res)+skipped)*100:.1f}%\n")
    lines.append("| 赛事 | League_ID | 总场次 | 可预测 | 特征覆盖% |")
    lines.append("|------|-----------|--------|--------|----------|")
    for lid, name in CUP_EURO_LIDS.items():
        total_rows = len(df_mat[df_mat["League_ID"]==lid])
        pred_rows  = len(df_res[df_res["League_ID"]==lid])
        pct = pred_rows/total_rows*100 if total_rows else 0
        lines.append(f"| {name} | {lid} | {total_rows} | {pred_rows} | {pct:.0f}% |")
    lines.append("")

    # 2. Overall + per-league accuracy
    lines.append("## 2. 总体命中率 + 分赛事命中率\n")
    total_wdl = df_res["wdl_correct"].mean()
    total_ou  = df_res["ou_correct"].mean()
    lines.append(f"**整体：WDL={total_wdl:.1%}（n={len(df_res)}）｜OU={total_ou:.1%}（n={len(df_res)}）**\n")
    lines.append(f"对比基准（国内 BIG5 25/26）：WDL={dom_wdl:.1%}，OU={dom_ou:.1%}（n={len(df_dom_res)}）\n")

    lines.append("### 分赛事命中率\n")
    lines.append("| 赛事 | n | WDL_acc | OU_acc | WDL_vs_baseline | 备注 |")
    lines.append("|------|---|---------|--------|----------------|------|")
    for lid, name in CUP_EURO_LIDS.items():
        g = df_res[df_res["League_ID"]==lid]
        if len(g) == 0:
            lines.append(f"| {name} | 0 | — | — | — | 特征全缺 |")
            continue
        wdl = g["wdl_correct"].mean()
        ou  = g["ou_correct"].mean()
        delta = wdl - dom_wdl
        delta_str = f"{delta:+.1%}"
        note = ("✅" if wdl >= 0.45 else "⚠️") + (" ✅" if ou >= 0.50 else " ⚠️")
        lines.append(f"| {name} | {len(g)} | {wdl:.1%} | {ou:.1%} | {delta_str} | {note} |")
    lines.append("")

    # 3. By match type
    lines.append("## 3. 分场景命中率\n")
    lines.append("| 场景 | n | WDL_acc | OU_acc |")
    lines.append("|------|---|---------|--------|")
    for cat in ["domestic_cup", "european"]:
        g = df_res[df_res["league_category"]==cat]
        if len(g):
            lines.append(f"| {'国内杯赛' if cat=='domestic_cup' else '欧战'} | {len(g)} | {g['wdl_correct'].mean():.1%} | {g['ou_correct'].mean():.1%} |")
    for mtype, label in [("both_big5","双强（双方均来自BIG5）"),
                          ("one_big5","单强（一方BIG5）"),
                          ("neither_big5","弱队对决（无BIG5球队）")]:
        g = df_res[df_res["match_type"]==mtype]
        if len(g):
            lines.append(f"| {label} | {len(g)} | {g['wdl_correct'].mean():.1%} | {g['ou_correct'].mean():.1%} |")

    # European-specific: by competition
    euro_g = df_res[df_res["league_category"]=="european"]
    if len(euro_g):
        lines.append(f"\n**欧战内部细分：**\n")
        lines.append("| 赛事 | n | WDL_acc | OU_acc |")
        lines.append("|------|---|---------|--------|")
        for lid in [42, 73, 10216]:
            g = df_res[df_res["League_ID"]==lid]
            if len(g):
                lines.append(f"| {CUP_EURO_LIDS[lid]} | {len(g)} | {g['wdl_correct'].mean():.1%} | {g['ou_correct'].mean():.1%} |")
    lines.append("")

    # 4. Calibration
    lines.append("## 4. Calibration 检查（WDL max_p 分桶）\n")
    lines.append("| max_p 区间 | n | actual_WDL_acc | 校准差 |")
    lines.append("|-----------|---|--------------|--------|")
    buckets = [(0.33, 0.40), (0.40, 0.45), (0.45, 0.50), (0.50, 0.55), (0.55, 0.60), (0.60, 0.70), (0.70, 1.01)]
    for lo, hi in buckets:
        g = df_res[(df_res["max_p"] >= lo) & (df_res["max_p"] < hi)]
        if len(g) < 3:
            continue
        mid = (lo + hi) / 2
        acc = g["wdl_correct"].mean()
        diff = acc - mid
        lines.append(f"| {lo:.2f}–{hi:.2f} | {len(g)} | {acc:.1%} | {diff:+.1%} |")
    lines.append("")

    # 5. OU calibration
    lines.append("## 5. Calibration 检查（OU p_over 分桶）\n")
    lines.append("| p_over 区间 | n | over_rate | 校准差 |")
    lines.append("|------------|---|-----------|--------|")
    for lo, hi in [(0.3,0.4),(0.4,0.5),(0.5,0.6),(0.6,0.7),(0.7,1.0)]:
        g = df_res[(df_res["p_over"] >= lo) & (df_res["p_over"] < hi)]
        if len(g) < 3:
            continue
        mid = (lo + hi) / 2
        actual_over = (g["actual_ou"] == "over").mean()
        diff = actual_over - mid
        lines.append(f"| {lo:.1f}–{hi:.1f} | {len(g)} | {actual_over:.1%} | {diff:+.1%} |")
    lines.append("")

    # 6. Verdict
    lines.append("## 6. 判断结论\n")
    feasible = total_wdl >= 0.45 and total_ou >= 0.50
    partial  = (total_wdl >= 0.42 or total_ou >= 0.48) and not feasible
    both_big5_g = df_res[df_res["match_type"]=="both_big5"]
    bb5_wdl = both_big5_g["wdl_correct"].mean() if len(both_big5_g) else 0
    bb5_ou  = both_big5_g["ou_correct"].mean()  if len(both_big5_g) else 0

    if feasible:
        verdict = "✅ **方案可行**"
    elif partial:
        verdict = "⚠️ **部分可行**"
    else:
        verdict = "🚨 **不可行**"

    lines.append(f"### {verdict}\n")
    lines.append(f"- 整体 WDL：{total_wdl:.1%}（阈值 45%）{'✅' if total_wdl>=0.45 else '❌'}")
    lines.append(f"- 整体 OU：{total_ou:.1%}（阈值 50%）{'✅' if total_ou>=0.50 else '❌'}")
    lines.append(f"- 双强对决 WDL：{bb5_wdl:.1%}（n={len(both_big5_g)}）")
    lines.append(f"- 双强对决 OU：{bb5_ou:.1%}（n={len(both_big5_g)}）")
    lines.append("")

    # Caveats
    lines.append("### 重要注意事项\n")
    lines.append("1. **League_ID 域外问题**：V5 Pure 模型训练时 League_ID 仅含 47/53/54/55/87/113/223/9080，"
                 "杯赛/欧战 League_ID（42/73 等）对 CatBoost 是未见类别，"
                 "CatBoost 用默认映射（不一定准确）处理。")
    lines.append("2. **特征覆盖不均**：UCL/UEL 仅 ~80%/41% 场次有 xG rolling 特征（其余 hometeam 无国内历史）。")
    lines.append("3. **单赛季局限**：所有结果来自 2025/26 赛季，样本量较小，置信区间宽。")
    lines.append("4. **OU line 固定 2.5**：未使用实际盘口线（大部分场次无赔率），可能影响 OU 精度。")
    lines.append("")

    if feasible or partial:
        lines.append("### 推荐上线规则\n")
        if feasible:
            lines.append("- ✅ 可在欧战/杯赛场景上线 Shadow 推荐")
        else:
            lines.append("- ⚠️ 建议仅在**双方均来自 BIG5 联赛的欧战对决**上线，其他场景暂缓")
        lines.append("- 置信度阈值：max_p ≥ 0.50（同现有生产规则）")
        lines.append("- 建议优先推 UCL 四强对决（16场已验证有赔率）")
        lines.append("- 短期内以 OU 推荐为主（不依赖球队主客之分），WDL 谨慎")

    # 7. Failure analysis (if applicable)
    lines.append("\n## 7. 失败场次分析（WDL 错误案例）\n")
    wrong = df_res[df_res["wdl_correct"]==0].sort_values("max_p", ascending=False)
    lines.append(f"高置信度（max_p≥0.60）错误：{len(wrong[wrong['max_p']>=0.60])} 场\n")
    for _, r in wrong[wrong["max_p"]>=0.60].head(10).iterrows():
        lines.append(f"- [{r['League_ID']} {r['league_name']}] {r['home']} {r['home_score']}-{r['away_score']} {r['away']} "
                     f"| 预测={r['pred_wdl']}（max_p={r['max_p']:.2f}）| λ=({r['lam_h']},{r['lam_a']})")
    lines.append("")

    # Write report
    report_path = os.path.join(REPORT_DIR, "cup_european_shadow_validation.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nReport written: {report_path}")

    # Save CSV
    csv_path = os.path.join(REPORT_DIR, "cup_european_shadow_test_set.csv")
    df_res.to_csv(csv_path, index=False, encoding="utf-8")
    print(f"CSV written:    {csv_path}")

    # Print summary to stdout
    print("\n" + "="*60)
    print(f"  Predicted:  {len(df_res)} cup/euro matches")
    print(f"  WDL acc:    {total_wdl:.1%}  (baseline domestic: {dom_wdl:.1%})")
    print(f"  OU acc:     {total_ou:.1%}   (baseline domestic: {dom_ou:.1%})")
    print(f"  Verdict:    {verdict}")
    print("="*60)

    return df_res


if __name__ == "__main__":
    main()
