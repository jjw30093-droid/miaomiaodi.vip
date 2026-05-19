"""
generate_match_report.py
========================
生产入口脚本：读取赛程 + 赔率 → 运行预测模型 → 记录预测审计 → 计算投注建议 → 生成 Markdown 研报

用法：
    python generate_match_report.py                          # 全量（所有赛程）
    python generate_match_report.py --match_id 4803342       # 单场
    python generate_match_report.py --final                  # 定稿模式（注入首发阵容）
"""

import sys, os, json, argparse, sqlite3, logging
from datetime import datetime, date
import numpy as np
import lightgbm as lgb
import pandas as pd

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from review_engine import ReviewEngine
from bankroll_simulator import BetAdvisor

DB_PATH     = os.path.join(PROJECT_ROOT, "football_uk.db")
MODEL_DIR   = os.path.join(PROJECT_ROOT, "models_v4")
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# NULL -> NaN helper (keep "missingness" signal for ML)
def _nan_or(v):
    return np.nan if v is None else v

# ─── 模型加载 ───────────────────────────────────────────────────────────────

def load_models():
    model_wdl = lgb.Booster(model_file=os.path.join(MODEL_DIR, "model_wdl.lgb"))
    model_ou  = lgb.Booster(model_file=os.path.join(MODEL_DIR, "model_ou.lgb"))
    with open(os.path.join(MODEL_DIR, "meta.json")) as f:
        meta = json.load(f)
    return model_wdl, model_ou, meta["features"]

def load_ah_predictor():
    """加载 AH 预测器（2026-05-04 切换为 V5 Lambda 双 CatBoost，纯 Lambda 不留 fallback）。

    支持联赛：47/53/54/55/87/113/223/9080（NowGoal spider 当前覆盖范围）。
    其他联赛或加载失败时 → 返回 None → run_tonight 不出 AH 推荐让 OU 单独竞争。
    """
    try:
        from lambda_ah_predictor import LambdaAHPredictor
        predictor = LambdaAHPredictor()
        predictor.load()
        log.info(f"[INFO] AH 预测器: v5_lambda 已加载（{len(predictor.SUPPORTED_LEAGUES)} 联赛覆盖）")
        return predictor
    except Exception as e:
        log.error(f"[ERR] v5_lambda AH 加载失败: {e}，AH 预测全局不可用")
        return None

def load_calibrators():
    """加载概率校准器（Isotonic Regression），不存在时返回 None"""
    import pickle
    cal_path = os.path.join(MODEL_DIR, "calibrators.pkl")
    if not os.path.exists(cal_path):
        log.warning(f"[WARN] 未找到校准器: {cal_path}，使用原始概率")
        return None
    try:
        with open(cal_path, "rb") as f:
            calibrators = pickle.load(f)
        log.info(f"[INFO] 概率校准器已加载 (n_samples={calibrators.get('n_samples', '?')})")
        return calibrators
    except Exception as e:
        log.warning(f"[WARN] 校准器加载失败: {e}，使用原始概率")
        return None

def apply_calibration(wdl_arr, ou_val, calibrators):
    """
    对原始模型输出应用 Isotonic Regression 校准
    返回: (wdl_dict, ou_dict, is_calibrated)

    注：经 Brier score 评估（验证集 1318场），新模型（52特征+Optuna+500轮）
    自身校准性已优于 IsotonicRegression，任何非零混合权重均使 Brier 变差。
    当前直接 pass-through 原始概率，保留函数签名供未来重启校准使用。
    """
    raw_wdl = {"home": float(wdl_arr[0]), "draw": float(wdl_arr[1]), "away": float(wdl_arr[2])}
    raw_ou  = {"over_25": float(ou_val), "under_25": float(1.0 - ou_val)}
    return raw_wdl, raw_ou, False

# ─── 特征构建（前瞻，取各队最近一场滚动均值）────────────────────────────────

def get_team_features(conn, team_id, today: date):
    cur = conn.cursor()

    rf = cur.execute("""
        SELECT r.*, d.Date FROM int_team_rolling_features r
        JOIN dim_match d ON r.match_id = d.Match_ID
        WHERE r.team_id = ? ORDER BY d.Date DESC LIMIT 1
    """, (team_id,)).fetchone()

    rz = cur.execute("""
        SELECT z.*, d.Date FROM int_team_rolling_zones z
        JOIN dim_match d ON z.match_id = d.Match_ID
        WHERE z.team_id = ? ORDER BY d.Date DESC LIMIT 1
    """, (team_id,)).fetchone()

    re = cur.execute("""
        SELECT r.*, d.Date FROM int_team_rolling_extended r
        JOIN dim_match d ON r.match_id = d.Match_ID
        WHERE r.team_id = ? AND r.window_size = 5
        ORDER BY d.Date DESC LIMIT 1
    """, (team_id,)).fetchone()

    elo = cur.execute("""
        SELECT post_match_elo FROM int_team_elo_history
        WHERE team_id = ? ORDER BY match_date DESC LIMIT 1
    """, (team_id,)).fetchone()

    last_match = cur.execute("""
        SELECT MAX(d.Date) FROM dim_match d
        WHERE (d.Home_Team_ID = ? OR d.Away_Team_ID = ?) AND d.status = 'Finish'
    """, (team_id, team_id)).fetchone()[0]

    rest = 0
    if last_match:
        last_date = date.fromisoformat(last_match)
        rest = (today - last_date).days

    rf_dict = dict(rf) if rf else {}
    if rz:
        rf_dict.update(dict(rz))  # merge rolling_zones features into rf

    return {
        "rf":   rf_dict,
        "re":   dict(re) if re else {},
        "elo":  elo[0] if elo else 1500.0,
        "rest": rest,
    }


def build_feature_row(home_feat, away_feat, eu_home, eu_draw, eu_away, 
                      ah_line=0, ah_home=0, ah_away=0, is_cup=0):
    r = {}
    for prefix, t in [("home", home_feat), ("away", away_feat)]:
        re = t["re"]
        r[f"{prefix}_roll_shot_pace"]         = re.get("roll_shot_pace") or 0
        r[f"{prefix}_roll_trailing_xg_ratio"] = re.get("roll_trailing_xg_ratio") or 0
        r[f"{prefix}_roll_level_xg_ratio"]    = re.get("roll_level_xg_ratio") or 0
        r[f"{prefix}_roll_opp_adj_npxgd"]     = re.get("roll_opp_adj_npxgd") or 0
        r[f"{prefix}_roll_rest_days"]         = re.get("roll_rest_days") or 4

    for prefix, t in [("home", home_feat), ("away", away_feat)]:
        rf = t["rf"]
        r[f"{prefix}_roll_5_npxGD"]               = rf.get("roll_5_npxGD") or 0
        r[f"{prefix}_roll_5_xGD"]                 = rf.get("roll_5_xGD") or 0
        r[f"{prefix}_roll_5_ppda"]                = rf.get("roll_5_ppda") or 0
        r[f"{prefix}_roll_5_field_tilt"]          = rf.get("roll_5_field_tilt") or 0
        r[f"{prefix}_roll_5_box_shot_ratio"]      = rf.get("roll_5_box_shot_ratio") or 0
        r[f"{prefix}_roll_5_poss_diff"]           = rf.get("roll_5_poss_diff") or 0
        r[f"{prefix}_roll_5_big_chances_created"] = rf.get("roll_5_big_chances_created") or 0
        r[f"{prefix}_roll_5_shot_quality_added"]  = rf.get("roll_5_shot_quality_added") or 0
        r[f"{prefix}_roll_5_open_play_xg_for"]  = _nan_or(rf.get("roll_5_open_play_xg_for"))
        r[f"{prefix}_roll_5_set_play_xg_for"]   = _nan_or(rf.get("roll_5_set_play_xg_for"))

        # rolling_zones (dbt model int_team_rolling_zones): keep source suffix to avoid conflicts
        r[f"{prefix}_roll_5_golden_zone_ratio_zones"]  = _nan_or(rf.get("roll_5_golden_zone_ratio_zones"))
        r[f"{prefix}_roll_5_outside_box_ratio_zones"]  = _nan_or(rf.get("roll_5_outside_box_ratio_zones"))
        r[f"{prefix}_roll_5_avg_xg_per_shot"]          = _nan_or(rf.get("roll_5_avg_xg_per_shot"))
        r[f"{prefix}_roll_5_high_value_shots"]         = _nan_or(rf.get("roll_5_high_value_shots"))
        r[f"{prefix}_roll_5_shot_execution_added"]     = _nan_or(rf.get("roll_5_shot_execution_added"))

    # set-play / open-play xG：只用于 OU（不进入 WDL），这里按比赛主/客语义取 split 特征
    # 主队使用 *_home，客队使用 *_away（与 is_home 拆分的 rolling 口径一致）
    _hrf = home_feat["rf"]
    _arf = away_feat["rf"]
    r["roll_5_xg_set_play_home"] = _nan_or(_hrf.get("roll_5_xg_set_play_home"))
    r["roll_5_xg_set_play_away"] = _nan_or(_arf.get("roll_5_xg_set_play_away"))
    r["roll_5_set_play_xg_ratio_home"] = _nan_or(_hrf.get("roll_5_set_play_xg_ratio_home"))
    r["roll_5_set_play_xg_ratio_away"] = _nan_or(_arf.get("roll_5_set_play_xg_ratio_away"))

    # rolling_zones: golden_zone / outside_box / execution (only for OU variance reduction)
    r["roll_5_golden_zone_ratio_home"]  = _nan_or(_hrf.get("roll_5_golden_zone_ratio_home"))
    r["roll_5_golden_zone_ratio_away"]  = _nan_or(_arf.get("roll_5_golden_zone_ratio_away"))
    r["roll_5_outside_box_ratio_home"]  = _nan_or(_hrf.get("roll_5_outside_box_ratio_home"))
    r["roll_5_outside_box_ratio_away"]  = _nan_or(_arf.get("roll_5_outside_box_ratio_away"))
    r["roll_5_avg_xg_per_shot_home"]    = _nan_or(_hrf.get("roll_5_avg_xg_per_shot_home"))
    r["roll_5_avg_xg_per_shot_away"]    = _nan_or(_arf.get("roll_5_avg_xg_per_shot_away"))
    r["roll_5_high_value_shots_home"]   = _nan_or(_hrf.get("roll_5_high_value_shots_home"))
    r["roll_5_high_value_shots_away"]   = _nan_or(_arf.get("roll_5_high_value_shots_away"))
    r["roll_5_shot_exec_added_home"]    = _nan_or(_hrf.get("roll_5_shot_exec_added_home"))
    r["roll_5_shot_exec_added_away"]    = _nan_or(_arf.get("roll_5_shot_exec_added_away"))

    # physical metrics (fatigue signal) — Rolling 3 split by match venue
    r["roll_3_distance_home"] = _nan_or(_hrf.get("roll_3_distance_home"))
    r["roll_3_distance_away"] = _nan_or(_arf.get("roll_3_distance_away"))
    r["roll_3_sprints_home"]  = _nan_or(_hrf.get("roll_3_sprints_home"))
    r["roll_3_sprints_away"]  = _nan_or(_arf.get("roll_3_sprints_away"))

    r["home_pre_match_elo"] = home_feat["elo"]
    r["away_pre_match_elo"] = away_feat["elo"]
    r["home_rest_days"]     = home_feat["rest"]
    r["away_rest_days"]     = away_feat["rest"]
    r["elo_diff"]           = home_feat["elo"] - away_feat["elo"]
    r["rest_days_diff"]     = home_feat["rest"] - away_feat["rest"]
    r["ppda_diff"]          = r["home_roll_5_ppda"] - r["away_roll_5_ppda"]
    r["field_tilt_diff"]    = r["home_roll_5_field_tilt"] - r["away_roll_5_field_tilt"]
    r["xGD_diff"]           = r["home_roll_5_xGD"] - r["away_roll_5_xGD"]
    r["is_cup"]             = is_cup

    h_o, d_o, a_o = float(eu_home or 0), float(eu_draw or 0), float(eu_away or 0)
    r["eu_odds_home"] = h_o
    r["eu_odds_draw"] = d_o
    r["eu_odds_away"] = a_o
    if h_o > 1 and d_o > 1 and a_o > 1:
        s = 1/h_o + 1/d_o + 1/a_o
        ih, id_, ia = (1/h_o)/s, (1/d_o)/s, (1/a_o)/s
        r["eu_implied_home"] = ih
        r["eu_implied_draw"] = id_
        r["eu_implied_away"] = ia
        r["odds_max_prob"]   = max(ih, id_, ia)
        r["odds_entropy"]    = -sum(p * np.log(p + 1e-9) for p in [ih, id_, ia])
    else:
        r["eu_implied_home"] = 1/3
        r["eu_implied_draw"] = 1/3
        r["eu_implied_away"] = 1/3
        r["odds_max_prob"] = 1/3
        r["odds_entropy"] = np.log(3)

    # --- NEW AH FEATURES ---
    r["ah_line"] = float(ah_line or 0)
    r["ah_home_odds"] = float(ah_home or 0)
    r["ah_away_odds"] = float(ah_away or 0)
    if r["ah_home_odds"] > 1 and r["ah_away_odds"] > 1:
        r["ah_implied_home"] = (1/r["ah_home_odds"]) / (1/r["ah_home_odds"] + 1/r["ah_away_odds"])
    else:
        r["ah_implied_home"] = 0.5
    r["ah_line_abs"] = abs(r["ah_line"])
    r["ah_line_direction"] = np.sign(r["ah_line"])

    r["total_shot_pace"]  = r["home_roll_shot_pace"] + r["away_roll_shot_pace"]
    r["npxGD_abs_diff"]   = abs(r["home_roll_opp_adj_npxgd"] - r["away_roll_opp_adj_npxgd"])
    return r


# ─── predict_engine 输出格式适配层（供 review_engine / bankroll 使用）────────

def adapt_for_review(result: dict) -> dict:
    """将 predict_engine 输出转换为 review_engine / bankroll_simulator 期望的格式"""
    wdl = result["wdl"]
    ou  = result["ou"]
    conf = result.get("confidence", "LOW")
    return {
        "wdl_prob": {
            "home_win": wdl["home"],
            "draw":     wdl["draw"],
            "away_win": wdl["away"],
        },
        "ou_prob": {
            "over":  ou["over_25"],
            "under": ou["under_25"],
        },
        "confidence": {"wdl": conf, "ou": conf},
        "shap_wdl": result.get("attribution", []),
        "shap_ou":  [],
    }


# ─── 报告生成 ────────────────────────────────────────────────────────────────

def pct(v):  return f"{v*100:.1f}%"

def build_report(match_results: list, report_date: str, is_final: bool = False) -> str:
    lines = []
    version_tag = "📌 定稿版" if is_final else "📊 预览版"
    lines.append(f"# 赛事量化研报 · {report_date}  {version_tag}")
    lines.append(f"**模型版本：** V4（45维特征，训练样本10,432场）  |  **赔率来源：** Bet365  |  **更新时间：** {datetime.now().strftime('%H:%M')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, m in enumerate(match_results, 1):
        pred   = m["prediction"]
        mkt    = m["market"]
        ts     = m["team_stats"]
        bets   = m["bet_decisions"]
        match  = m["match"]

        wdl_h = pred["wdl"]["home"]
        wdl_d = pred["wdl"]["draw"]
        wdl_a = pred["wdl"]["away"]
        ou_o  = pred["ou"]["over_25"]
        conf  = pred["confidence"]
        conf_icon = {"HIGH": "🔴 高", "MID": "🟡 中", "LOW": "⚪ 低"}.get(conf, conf)

        # 市场隐含概率
        h_o, d_o, a_o = mkt["eu_home"], mkt["eu_draw"], mkt["eu_away"]
        s = (1/h_o + 1/d_o + 1/a_o) if h_o > 1 and d_o > 1 and a_o > 1 else 1
        mk_h = (1/h_o)/s if h_o > 1 else 0
        mk_d = (1/d_o)/s if d_o > 1 else 0
        mk_a = (1/a_o)/s if a_o > 1 else 0

        edge_h = round(wdl_h - mk_h, 4)
        edge_d = round(wdl_d - mk_d, 4)
        edge_a = round(wdl_a - mk_a, 4)

        lines.append(f"## {i}. {match['match_name']}  ·  {match['league']}")
        lines.append(f"**开球时间：** {match['kickoff_time']}  |  **信心：** {conf_icon}")
        lines.append("")

        lines.append("### 📊 胜平负")
        lines.append("")
        lines.append("| | 主胜 | 平局 | 客胜 |")
        lines.append("|---|---|---|---|")
        lines.append(f"| **模型** | {pct(wdl_h)} | {pct(wdl_d)} | {pct(wdl_a)} |")
        lines.append(f"| **市场** | {pct(mk_h)} | {pct(mk_d)} | {pct(mk_a)} |")
        lines.append(f"| **Edge** | {edge_h*100:+.1f}% | {edge_d*100:+.1f}% | {edge_a*100:+.1f}% |")
        lines.append(f"| **欧赔** | {h_o} | {d_o} | {a_o} |")
        lines.append("")

        lines.append(f"### ⚽ 大小球（{mkt['ou_line']}）")
        lines.append("")
        lines.append(f"| 大球 | 小球 |")
        lines.append(f"|---|---|")
        lines.append(f"| {pct(ou_o)} | {pct(1-ou_o)} |")
        lines.append(f"| 赔率 {mkt['ou_over']} | 赔率 {mkt['ou_under']} |")
        lines.append("")

        lines.append(f"### 📐 亚盘（{mkt['ah_line']}）")
        lines.append(f"主队 {mkt['ah_home']} / 客队 {mkt['ah_away']}")
        lines.append("")

        lines.append("### 📈 近期数据（近5场）")
        lines.append("")
        lines.append("| 指标 | 主队 | 客队 |")
        lines.append("|---|---|---|")
        lines.append(f"| Elo | {ts['home_elo']} | {ts['away_elo']} |")
        lines.append(f"| Elo差 | {ts['elo_diff']:+.1f} | — |")
        lines.append(f"| npxGD | {ts['home_npxGD']:+.3f} | {ts['away_npxGD']:+.3f} |")
        lines.append(f"| PPDA | {ts['home_ppda']:.3f} | {ts['away_ppda']:.3f} |")
        lines.append(f"| Field Tilt | {ts['home_field_tilt']:.3f} | {ts['away_field_tilt']:.3f} |")
        lines.append(f"| 休息天数 | {ts['home_rest']}天 | {ts['away_rest']}天 |")
        lines.append("")

        # 投注建议
        if bets:
            lines.append("### 💰 Kelly 投注建议（参考）")
            lines.append("")
            lines.append("| 方向 | 模型概率 | 赔率 | Edge | Kelly建议 |")
            lines.append("|---|---|---|---|---|")
            for b in bets:
                if b.bet_amount > 0:
                    label_map = {"home_win": f"主胜({h_o})", "draw": f"平局({d_o})",
                                 "away_win": f"客胜({a_o})", "over": "大球", "under": "小球"}
                    lines.append(f"| {label_map.get(b.bet_pick, b.bet_pick)} | {pct(b.ml_prob)} | {b.market_odds} | {b.edge*100:+.1f}% | {b.kelly_actual*100:.1f}% |")
        lines.append("")

        # 综合结论
        lines.append("### 🎯 综合结论")
        best_edge_key = max([("home", edge_h), ("draw", edge_d), ("away", edge_a)], key=lambda x: x[1])
        best_label = {"home": f"主胜（{h_o}）", "draw": f"平局（{d_o}）", "away": f"客胜（{a_o}）"}[best_edge_key[0]]
        if best_edge_key[1] > 0.10:
            lines.append(f"- **最大价值：** {best_label}，Edge = **+{best_edge_key[1]*100:.1f}%**")
        elif best_edge_key[1] > 0.03:
            lines.append(f"- **轻微价值：** {best_label}，Edge = +{best_edge_key[1]*100:.1f}%")
        else:
            lines.append("- **无明显价值**，市场定价合理")

        if ou_o > 0.62:
            lines.append(f"- **大球倾向：** {pct(ou_o)}，赔率 {mkt['ou_over']}")
        elif ou_o < 0.38:
            lines.append(f"- **小球倾向：** {pct(1-ou_o)}，赔率 {mkt['ou_under']}")
        else:
            lines.append("- **大小球均势**，建议规避")

        # 首发阵容（仅定稿版显示）
        lineup = m.get("lineup")
        if lineup:
            lines.append("### 📋 首发阵容")
            lines.append("")
            home_players = lineup.get("home", [])
            away_players = lineup.get("away", [])
            max_len = max(len(home_players), len(away_players), 1)
            lines.append(f"| {match['match_name'].split(' vs ')[0]} | {match['match_name'].split(' vs ')[-1]} |")
            lines.append("|---|---|")
            for i in range(max_len):
                hp = home_players[i] if i < len(home_players) else ""
                ap = away_players[i] if i < len(away_players) else ""
                lines.append(f"| {hp} | {ap} |")
            lines.append("")

        lines.append("")
        lines.append("---")
        lines.append("")

    # 汇总表
    lines.append("## 📋 快速汇总")
    lines.append("")
    lines.append("| 场次 | 最优方向 | Edge | 大小球 | 信心 |")
    lines.append("|---|---|---|---|---|")
    for m in match_results:
        pred = m["prediction"]; mkt = m["market"]
        wdl_h = pred["wdl"]["home"]; wdl_d = pred["wdl"]["draw"]; wdl_a = pred["wdl"]["away"]
        h_o, d_o, a_o = mkt["eu_home"], mkt["eu_draw"], mkt["eu_away"]
        s = (1/h_o + 1/d_o + 1/a_o) if h_o > 1 and d_o > 1 and a_o > 1 else 1
        edges = {"home": wdl_h-(1/h_o)/s if h_o>1 else -1,
                 "draw": wdl_d-(1/d_o)/s if d_o>1 else -1,
                 "away": wdl_a-(1/a_o)/s if a_o>1 else -1}
        best = max(edges.items(), key=lambda x: x[1])
        label = {"home": f"主胜({h_o})", "draw": f"平局({d_o})", "away": f"客胜({a_o})"}[best[0]]
        ou_o = pred["ou"]["over_25"]
        ou_txt = f"大球{pct(ou_o)}" if ou_o > 0.55 else (f"小球{pct(1-ou_o)}" if ou_o < 0.45 else "均势")
        conf_icon = {"HIGH": "🔴", "MID": "🟡", "LOW": "⚪"}.get(pred["confidence"], "")
        lines.append(f"| {m['match']['match_name']} | {label} | {best[1]*100:+.1f}% | {ou_txt} | {conf_icon} |")

    lines.append("")
    lines.append("> ⚠️ **免责声明：** 本研报基于历史统计模型，仅供参考，不构成投注建议。")

    return "\n".join(lines)


# ─── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule",  default=os.path.join(PROJECT_ROOT, "schedule/target_matches.json"))
    parser.add_argument("--odds",      default=os.path.join(PROJECT_ROOT, "odds/match_odds_data.json"))
    parser.add_argument("--bankroll",  type=float, default=10000.0)
    parser.add_argument("--match_id",  type=str, default=None, help="只处理指定 match_id（单场模式）")
    parser.add_argument("--final",     action="store_true",    help="定稿模式：从数据库读取首发阵容注入研报")
    args = parser.parse_args()

    # 加载输入数据
    with open(args.schedule, encoding="utf-8") as f:
        matches = json.load(f)
    # 单场过滤
    if args.match_id:
        matches = [m for m in matches if str(m["match_id"]) == str(args.match_id)]
        if not matches:
            log.warning(f"target_matches.json 中未找到 match_id={args.match_id}")
            sys.exit(0)

    with open(args.odds, encoding="utf-8") as f:
        odds_raw = json.load(f)
    odds_index = {}
    for o in odds_raw:
        if "fotmob_id" not in o or "odds" not in o:
            logging.warning(f"[odds_load] 跳过损坏记录（缺 fotmob_id/odds），keys={list(o.keys())[:4]}")
            continue
        odds_index[str(o["fotmob_id"])] = o["odds"]

    model_wdl, model_ou, FEATURES = load_models()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    review = ReviewEngine(DB_PATH, model_dir=MODEL_DIR)
    calibrators = load_calibrators()
    advisor = BetAdvisor()
    today = date.today()

    match_results = []
    for m in matches:
        mid = str(m["match_id"])
        log.info(f"预测中: {m['match_name']}")

        odds_data = odds_index.get(mid, {})
        eu = odds_data.get("european_1x2", {}).get("latest", {})
        ah = odds_data.get("asian_handicap", {}).get("latest", {})
        ou_odds = odds_data.get("over_under", {}).get("latest", {})

        eu_h = float(eu.get("home", 0) or 0)
        eu_d = float(eu.get("draw", 0) or 0)
        eu_a = float(eu.get("away", 0) or 0)

        h_feat = get_team_features(conn, m["home_id"], today)
        a_feat = get_team_features(conn, m["away_id"], today)

        # 准备 AH 特征
        ah_l = 0
        try:
            val = ah.get("line")
            ah_l = float(val) if val not in [None, "N/A"] else 0
        except: pass
        ah_h = float(ah.get("over_or_home") or 0)
        ah_a = float(ah.get("under_or_away") or 0)

        row = build_feature_row(h_feat, a_feat, eu_h, eu_d, eu_a, 
                                ah_line=ah_l, ah_home=ah_h, ah_away=ah_a)
        X = pd.DataFrame([row])[FEATURES].fillna(0)

        wdl_arr = model_wdl.predict(X)[0]
        ou_val  = float(model_ou.predict(X)[0])
        
        # 应用概率校准
        cal_wdl, cal_ou, _ = apply_calibration(wdl_arr, ou_val, calibrators)
        
        conf = "HIGH" if max(wdl_arr) > 0.6 else ("MID" if max(wdl_arr) > 0.45 else "LOW")

        result = {
            "match_id":   mid,
            "wdl":        cal_wdl,
            "ou":         cal_ou,
            "confidence": conf,
            "attribution": [],
        }

        # 记录到 prediction_audit（用适配格式）
        name_parts = m["match_name"].split(" vs ")
        _home = name_parts[0].strip()
        _away = name_parts[1].strip() if len(name_parts) > 1 else ""
        # Phase 2: 提取大小球线 + 亚盘方向，写入 prediction_audit
        _ou_line_raw = ou_odds.get("line")
        try:
            _ou_line = float(_ou_line_raw) if _ou_line_raw not in (None, '', 'N/A') else 2.5
        except (ValueError, TypeError):
            _ou_line = 2.5
        _ah_line_for_audit = ah_l if ah_l != 0 else None
        _ah_pick = 'home' if ah_h > ah_a else ('away' if ah_a > ah_h else None)
        try:
            review.log_prediction(mid, adapt_for_review(result),
                                  match_date=today.isoformat(),
                                  home_name=_home, away_name=_away,
                                  ou_line=_ou_line,
                                  ah_pick=_ah_pick,
                                  ah_line=_ah_line_for_audit)
        except Exception as e:
            log.warning(f"[{mid}] review_engine.log_prediction 跳过: {e}")

        # Kelly 投注建议
        bet_odds = {
            "eu_home": eu_h, "eu_draw": eu_d, "eu_away": eu_a,
            "ou_over":  float(ou_odds.get("over_or_home", 0) or 0),
            "ou_under": float(ou_odds.get("under_or_away", 0) or 0),
        }
        bet_decisions = advisor.advise(mid, m["match_name"], adapt_for_review(result), bet_odds, args.bankroll)

        ts = {
            "home_elo":        round(h_feat["elo"], 1),
            "away_elo":        round(a_feat["elo"], 1),
            "elo_diff":        round(h_feat["elo"] - a_feat["elo"], 1),
            "home_rest":       h_feat["rest"],
            "away_rest":       a_feat["rest"],
            "home_npxGD":      round(h_feat["rf"].get("roll_5_npxGD", 0) or 0, 3),
            "away_npxGD":      round(a_feat["rf"].get("roll_5_npxGD", 0) or 0, 3),
            "home_ppda":       round(h_feat["rf"].get("roll_5_ppda", 0) or 0, 3),
            "away_ppda":       round(a_feat["rf"].get("roll_5_ppda", 0) or 0, 3),
            "home_field_tilt": round(h_feat["rf"].get("roll_5_field_tilt", 0) or 0, 3),
            "away_field_tilt": round(a_feat["rf"].get("roll_5_field_tilt", 0) or 0, 3),
        }

        # 首发阵容（定稿模式：从 DB 读取）
        lineup = None
        if args.final:
            try:
                lineup_row = conn.execute("""
                    SELECT home_lineup, away_lineup FROM match_payloads
                    WHERE match_id = ? ORDER BY created_at DESC LIMIT 1
                """, (mid,)).fetchone()
                if lineup_row:
                    lineup = {
                        "home": json.loads(lineup_row[0]) if lineup_row[0] else [],
                        "away": json.loads(lineup_row[1]) if lineup_row[1] else [],
                    }
            except Exception:
                pass  # match_payloads 不存在或无数据，跳过
        market = {
            "eu_home": eu_h, "eu_draw": eu_d, "eu_away": eu_a,
            "ah_line": ah.get("line", "N/A"),
            "ah_home": ah.get("over_or_home", "N/A"),
            "ah_away": ah.get("under_or_away", "N/A"),
            "ou_line":  ou_odds.get("line", "2.5"),
            "ou_over":  ou_odds.get("over_or_home", "N/A"),
            "ou_under": ou_odds.get("under_or_away", "N/A"),
        }

        match_results.append({
            "match":         m,
            "prediction":    result,
            "market":        market,
            "team_stats":    ts,
            "bet_decisions": bet_decisions,
            "lineup":        lineup,
        })

    conn.close()
    review.close()

    # 生成研报
    report_date = today.strftime("%Y-%m-%d")
    report_text = build_report(match_results, report_date, is_final=args.final)
    # 单场模式：文件名带 match_id；定稿模式：文件名带 _final
    if args.match_id:
        suffix = f"_final" if args.final else ""
        report_path = os.path.join(REPORTS_DIR, f"report_{report_date}_{args.match_id}{suffix}.md")
    else:
        report_path = os.path.join(REPORTS_DIR, f"report_{report_date}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    log.info(f"✅ 研报已生成: {report_path}")
    print(report_text)
    return report_path


if __name__ == "__main__":
    main()
