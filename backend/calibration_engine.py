"""
calibration_engine.py v2.0
==========================
概率校准器训练：用 IsotonicRegression 将原始模型概率映射到真实频率。

关键修复：
  1. MODEL_PATH 指向 models_v4（与生产一致）
  2. engine.calibrators = None 禁用内部校准，确保用原始概率训练
  3. 80/20 时间序列 split + Brier Score 评估
  4. 全量数据（不限 limit=1000）
"""

import sqlite3
import os
import pickle
import argparse
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss
from predict_engine import PredictEngine, HAS_ML

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "football_uk.db")
MODEL_PATH = os.path.join(PROJECT_ROOT, "models_v4", "calibrators.pkl")


class CalibrationEngine:
    def __init__(self, db_path=DB_PATH, model_dir=None):
        self.db_path = db_path
        _model_dir = model_dir or os.path.join(PROJECT_ROOT, "models_v4")
        self.engine = PredictEngine(db_path, model_dir=_model_dir)
        # ★ 禁用引擎内部校准器，确保 predict() 返回原始概率
        self.engine.calibrators = None
        self.calibrators = {
            'home_win': IsotonicRegression(out_of_bounds='clip'),
            'draw': IsotonicRegression(out_of_bounds='clip'),
            'away_win': IsotonicRegression(out_of_bounds='clip'),
            'over': IsotonicRegression(out_of_bounds='clip'),
            'ah_cover': IsotonicRegression(out_of_bounds='clip')
        }

    def build_calibration_dataset(self, limit=None):
        if not HAS_ML:
            print("[ERR] lightgbm/shap not installed.")
            return None

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        query = """
            SELECT m.Match_ID, m.home_score, m.away_score, o.AHh as ah_line
            FROM dim_match m
            LEFT JOIN raw_footballdata_odds o ON m.Home_Team_Name = o.HomeTeam 
                AND m.Away_Team_Name = o.AwayTeam AND m.Date = o.Date
            WHERE m.status = 'Finish' AND m.home_score IS NOT NULL
            ORDER BY m.Date
        """
        if limit:
            query += f" LIMIT {limit}"
        matches = conn.execute(query).fetchall()
        conn.close()

        if not matches:
            print("[WARN] No matches found.")
            return None

        print(f"Building calibration dataset from {len(matches)} matches (raw probs, no internal calibration)...")

        results = []
        for i, m in enumerate(matches):
            mid = m['Match_ID']
            try:
                pred = self.engine.predict(mid)
                if 'note' in pred:
                    continue
                hs, aws = m['home_score'], m['away_score']
                ah_line = m['ah_line'] if m['ah_line'] is not None else 0
                
                results.append({
                    'pred_home': pred['wdl']['home'],
                    'pred_draw': pred['wdl']['draw'],
                    'pred_away': pred['wdl']['away'],
                    'pred_over': pred['ou']['over_25'],
                    'pred_ah':   pred.get('ah_implied_home', 0.5),
                    'label_home': 1 if hs > aws else 0,
                    'label_draw': 1 if hs == aws else 0,
                    'label_away': 1 if hs < aws else 0,
                    'label_over': 1 if (hs + aws) > 2.5 else 0,
                    'label_ah':   1 if (hs - aws + ah_line) > 0 else 0,
                })
                if (i + 1) % 500 == 0:
                    print(f"  {i+1}/{len(matches)} 成功={len(results)}")
            except:
                continue

        print(f"  完成: {len(results)}/{len(matches)} 成功")
        return pd.DataFrame(results)

    def train(self, limit=None):
        df = self.build_calibration_dataset(limit)
        if df is None or len(df) < 50:
            print(f"[ERR] 数据不足: {len(df) if df is not None else 0}")
            return False

        # 80/20 时间序列 split（数据已按Date排序）
        split_idx = int(len(df) * 0.8)
        df_train = df.iloc[:split_idx]
        df_test = df.iloc[split_idx:]
        print(f"训练: {len(df_train)}, 测试: {len(df_test)}")

        # 训练
        for key, p_col, l_col in [
            ('home_win', 'pred_home', 'label_home'),
            ('draw', 'pred_draw', 'label_draw'),
            ('away_win', 'pred_away', 'label_away'),
            ('over', 'pred_over', 'label_over'),
            ('ah_cover', 'pred_ah', 'label_ah'),
        ]:
            self.calibrators[key].fit(df_train[p_col], df_train[l_col])

        # 评估
        print(f"\n{'方向':<10} | {'原始Brier':<12} | {'校准Brier':<12} | {'提升'}")
        print("-" * 55)
        for key, p_col, l_col in [
            ('home_win', 'pred_home', 'label_home'),
            ('draw', 'pred_draw', 'label_draw'),
            ('away_win', 'pred_away', 'label_away'),
            ('over', 'pred_over', 'label_over'),
            ('ah_cover', 'pred_ah', 'label_ah'),
        ]:
            test_p = df_test[p_col].values
            test_y = df_test[l_col].values
            raw_brier = brier_score_loss(test_y, test_p)
            cal_p = np.clip(self.calibrators[key].transform(test_p), 0.005, 0.995)
            cal_brier = brier_score_loss(test_y, cal_p)
            gain = (raw_brier - cal_brier) / raw_brier * 100 if raw_brier > 0 else 0
            print(f"{key:<10} | {raw_brier:.4f}       | {cal_brier:.4f}       | {gain:+.1f}%")

        # 保存
        self.calibrators['n_samples'] = len(df)
        self.calibrators['train_size'] = len(df_train)
        self.calibrators['test_size'] = len(df_test)
        self.calibrators['version'] = 'v4_raw_80_20'

        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        if os.path.exists(MODEL_PATH):
            os.rename(MODEL_PATH, MODEL_PATH + '.bak')
        with open(MODEL_PATH, 'wb') as f:
            pickle.dump(self.calibrators, f)
        print(f"\n[SUCCESS] 校准器已保存: {MODEL_PATH}")
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--db", type=str, default=DB_PATH)
    args = parser.parse_args()

    ce = CalibrationEngine(db_path=args.db)
    if args.train:
        ce.train()
    else:
        df = ce.build_calibration_dataset()
        print(f"有效样本: {len(df) if df is not None else 0}")
