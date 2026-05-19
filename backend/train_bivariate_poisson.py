"""
train_bivariate_poisson.py
==========================
训练 Bivariate Poisson 进球模型 (Part C3)。

用法:
  python3 train_bivariate_poisson.py                    # 训练 + 验证
  python3 train_bivariate_poisson.py --xi 0.003         # 调整时间衰减
  python3 train_bivariate_poisson.py --validate-only    # 仅加载校验
  python3 train_bivariate_poisson.py --leagues 47,87,55 # 仅训练指定联赛
"""

import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from ah_model import prepare_ah_data
from models_v5.bivariate_poisson import BivariatePoissonModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    df["home_goals"] = df["home_score"].astype(int)
    df["away_goals"] = df["away_score"].astype(int)
    max_dt = df["Date"].max()
    df["days_ago"] = (max_dt - df["Date"]).dt.days
    return df


def validate(model: BivariatePoissonModel, df_val: pd.DataFrame):
    """在验证集上评估 WDL + OU + AH 三市场的 Brier/LogLoss。"""
    rows = []
    for _, r in df_val.iterrows():
        l1, l2, l3 = model.get_lambdas(r["home_team"], r["away_team"])
        if l1 is None:
            continue
        M = BivariatePoissonModel.score_matrix(l1, l2, l3, max_goals=model.max_goals)

        ah_line = float(r["ah_line"]) if pd.notna(r.get("ah_line")) else 0.0
        ou_line = 2.5
        mkts = BivariatePoissonModel.markets_from_matrix(M, ah_line=ah_line, ou_line=ou_line)

        hs, as_ = int(r["home_score"]), int(r["away_score"])
        actual_wdl = 0 if hs > as_ else (1 if hs == as_ else 2)
        actual_ou  = 1 if (hs + as_) > ou_line else 0
        margin     = hs - as_ + ah_line
        actual_ah_home = 1 if margin > 1e-9 else (0 if margin < -1e-9 else None)

        rows.append({
            "match_id":   r.get("Match_ID"),
            "home":       r["home_team"],
            "away":       r["away_team"],
            "l1": l1, "l2": l2, "l3": l3,
            "p_home":     mkts["wdl"]["home"],
            "p_draw":     mkts["wdl"]["draw"],
            "p_away":     mkts["wdl"]["away"],
            "p_over":     mkts["ou"]["over"],
            "p_ah_home":  mkts["ah"]["cover"],
            "actual_wdl": actual_wdl,
            "actual_ou":  actual_ou,
            "actual_ah":  actual_ah_home,
            "hs": hs, "as": as_,
        })
    vdf = pd.DataFrame(rows)
    if vdf.empty:
        log.error("验证集为空")
        return vdf

    # ── WDL ──
    eps = 1e-7
    wdl_pred = vdf[["p_home", "p_draw", "p_away"]].values
    wdl_pred = np.clip(wdl_pred / wdl_pred.sum(axis=1, keepdims=True), eps, 1 - eps)
    wdl_lbl  = vdf["actual_wdl"].values
    wdl_ll   = -np.mean(np.log(wdl_pred[np.arange(len(wdl_lbl)), wdl_lbl]))
    wdl_acc  = (wdl_pred.argmax(axis=1) == wdl_lbl).mean()

    # ── OU 2.5 ──
    ou_br  = brier_score_loss(vdf["actual_ou"], vdf["p_over"].clip(eps, 1 - eps))
    ou_ll  = log_loss(vdf["actual_ou"], vdf["p_over"].clip(eps, 1 - eps))
    ou_acc = ((vdf["p_over"] > 0.5).astype(int) == vdf["actual_ou"]).mean()

    # ── AH（排除 push）──
    ah_sub = vdf.dropna(subset=["actual_ah"])
    if len(ah_sub):
        ah_br  = brier_score_loss(ah_sub["actual_ah"], ah_sub["p_ah_home"].clip(eps, 1 - eps))
        ah_ll  = log_loss(ah_sub["actual_ah"], ah_sub["p_ah_home"].clip(eps, 1 - eps))
        ah_acc = ((ah_sub["p_ah_home"] > 0.5).astype(int) == ah_sub["actual_ah"]).mean()
    else:
        ah_br = ah_ll = ah_acc = float("nan")

    SEP = "=" * 60
    print(f"\n{SEP}")
    print(f"  Bivariate Poisson 验证  (n={len(vdf)})")
    print(SEP)
    print(f"  WDL   LogLoss={wdl_ll:.4f}   Acc={wdl_acc*100:.1f}%")
    print(f"  OU2.5 Brier={ou_br:.4f}  LogLoss={ou_ll:.4f}  Acc={ou_acc*100:.1f}%")
    print(f"  AH    Brier={ah_br:.4f}  LogLoss={ah_ll:.4f}  Acc={ah_acc*100:.1f}%  (n={len(ah_sub)})")
    print(f"  λ₃ 全局共同强度: {model.lambda3:.4f}")
    print(f"  λ_home 均值: {vdf['l1'].mean():.3f}  实际主队进球均值: {vdf['hs'].mean():.3f}")
    print(f"  λ_away 均值: {vdf['l2'].mean():.3f}  实际客队进球均值: {vdf['as'].mean():.3f}")
    print(SEP)

    return vdf, {"wdl_ll": wdl_ll, "wdl_acc": wdl_acc,
                 "ou_brier": ou_br, "ou_ll": ou_ll, "ou_acc": ou_acc,
                 "ah_brier": ah_br, "ah_ll": ah_ll, "ah_acc": ah_acc}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db",         default=os.path.join(PROJECT_ROOT, "football_uk.db"))
    p.add_argument("--model-dir",  default=os.path.join(PROJECT_ROOT, "models_v5"))
    p.add_argument("--xi",         type=float, default=0.003)
    p.add_argument("--max-goals",  type=int, default=10)
    p.add_argument("--leagues",    type=str, default=None,
                   help="逗号分隔的联赛 ID，仅用该集合训练")
    p.add_argument("--validate-only", action="store_true")
    args = p.parse_args()

    log.info("加载 AH 训练数据...")
    df = prepare_ah_data(args.db)
    df = _prepare_df(df)
    log.info(f"总样本: {len(df)}")

    if args.leagues:
        lids = {int(x) for x in args.leagues.split(",")}
        df = df[df["league_id"].isin(lids)].reset_index(drop=True)
        log.info(f"联赛过滤后: {len(df)}  leagues={sorted(lids)}")

    split_idx = int(len(df) * 0.8)
    df_train = df.iloc[:split_idx].copy()
    df_val   = df.iloc[split_idx:].copy()
    log.info(f"训练: {len(df_train)}  验证: {len(df_val)}")

    bp = BivariatePoissonModel(xi=args.xi, max_goals=args.max_goals)

    if args.validate_only:
        bp.load(args.model_dir)
    else:
        bp.fit(df_train[["home_team", "away_team", "home_goals", "away_goals", "days_ago"]])
        bp.meta.update({
            "n_train":     len(df_train),
            "n_val":       len(df_val),
            "xi":          args.xi,
            "leagues":     sorted(list(df["league_id"].unique())),
        })
        bp.save(args.model_dir)

    _, metrics = validate(bp, df_val)
    bp.meta["validation"] = metrics
    if not args.validate_only:
        bp.save(args.model_dir)  # 把 metrics 也存进去


if __name__ == "__main__":
    main()
