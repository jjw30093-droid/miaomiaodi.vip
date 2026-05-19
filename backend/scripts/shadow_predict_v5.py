"""
shadow_predict_v5.py — Phase D: v5 A/B shadow prediction writer
================================================================
对 prediction_audit 中尚无 v5 预测的记录，用 v5 模型补写 pred_*_v5 列。
在 MODEL_VERSION=v4 生产模式下，每天 cron 运行一次（建议 04:50 UTC，在
run_tonight 04:40 之后）。

用法：
  python scripts/shadow_predict_v5.py
  python scripts/shadow_predict_v5.py --days 3   # 补写近 3 天
"""

import argparse
import os
import sys
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", str(Path(__file__).resolve().parent.parent))
DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))
V5_MODEL_DIR = os.path.join(PROJECT_ROOT, "models_v5_combo")
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def run_shadow(days: int = 1):
    if not os.path.exists(V5_MODEL_DIR):
        log.error(f"v5 model dir not found: {V5_MODEL_DIR}")
        return

    try:
        import lightgbm as lgb
        from predict_engine import FeatureAssembler, V5_ALL_FEATURES
        import numpy as np
    except ImportError as e:
        log.error(f"Import error: {e}")
        return

    wdl_path = os.path.join(V5_MODEL_DIR, "model_wdl.lgb")
    ou_path = os.path.join(V5_MODEL_DIR, "model_ou.lgb")
    if not os.path.exists(wdl_path) or not os.path.exists(ou_path):
        log.error(f"v5 model files missing in {V5_MODEL_DIR}")
        return

    model_wdl = lgb.Booster(model_file=wdl_path)
    model_ou = lgb.Booster(model_file=ou_path)
    assembler = FeatureAssembler(DB_PATH)
    conn = sqlite3.connect(DB_PATH)

    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT match_id FROM prediction_audit
        WHERE match_date >= ? AND pred_wdl_home_v5 IS NULL
    """, (cutoff,)).fetchall()

    log.info(f"Found {len(rows)} matches needing v5 shadow predictions (since {cutoff})")

    updated = 0
    for (match_id,) in rows:
        try:
            X = assembler.assemble(match_id)
            # V5 assembler uses same raw features + combos computed via the feature schema
            # For shadow we use V5_ALL_FEATURES subset
            import pandas as pd
            # Fill missing v5 features with 0
            for col in V5_ALL_FEATURES:
                if col not in X.columns:
                    X[col] = 0.0
            Xv5 = X[V5_ALL_FEATURES].fillna(0).astype(float)

            wdl_pred = model_wdl.predict(Xv5)[0]
            ou_pred = float(model_ou.predict(Xv5)[0])

            conn.execute("""
                UPDATE prediction_audit
                SET pred_wdl_home_v5=?, pred_wdl_draw_v5=?, pred_wdl_away_v5=?,
                    pred_ou_over_v5=?, model_version_active='v4'
                WHERE match_id=? AND pred_wdl_home_v5 IS NULL
            """, (float(wdl_pred[0]), float(wdl_pred[1]), float(wdl_pred[2]),
                  ou_pred, match_id))
            updated += 1
        except Exception as e:
            log.warning(f"match_id={match_id}: {e}")

    conn.commit()
    conn.close()
    log.info(f"Shadow v5 predictions written: {updated}/{len(rows)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1)
    args = parser.parse_args()
    run_shadow(args.days)
