"""
predict_engine.py
=================
Phase 3: LightGBM + SHAP 预测引擎

核心原则："算法负责算概率，LLM 负责讲故事"

职责：
  1. 从 Intelligence Layer + Extended Features 组装特征向量
  2. LightGBM 双模型推理 (WDL 三分类 + O/U 二分类)
  3. SHAP TreeExplainer 归因 → Top-3 影响因子
  4. Confidence Gate → 置信度分级
  5. 输出标准化 JSON 供 LangGraph Agents 消费

Dependencies: lightgbm, shap, scikit-learn, pandas, numpy
  pip install lightgbm shap scikit-learn

Author: 喵弟量化研究所
"""

import sqlite3
import json
import os
import pickle
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

# ── ML imports (生产环境必须安装) ──
try:
    import lightgbm as lgb
    import shap
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.calibration import CalibratedClassifierCV
    HAS_ML = True
except ImportError:
    HAS_ML = False
    print("[WARN] lightgbm/shap not installed. Mock mode enabled.")


# ═══════════════════════════════════════════
# Section 1: Feature Vector Schema
# ═══════════════════════════════════════════

# 特征字段定义 — 同时用于训练和推理
# 分为 4 个 domain，每个 domain 的字段从不同数据源拉取

FEATURE_SCHEMA = {
    # ── Domain A: 滚动基础指标 (from int_team_rolling_extended) ──
    'rolling': [
        'home_roll_shot_pace',
        'away_roll_shot_pace',
        'home_roll_trailing_xg_ratio',
        'away_roll_trailing_xg_ratio',
        'home_roll_level_xg_ratio',
        'away_roll_level_xg_ratio',
        'home_roll_opp_adj_npxgd',
        'away_roll_opp_adj_npxgd',
        'home_roll_rest_days',
        'away_roll_rest_days',
    ],

    # ── Domain A2: dbt Rolling Features (from int_team_rolling_features) ──
    'rolling_dbt': [
        'home_roll_5_npxGD',
        'away_roll_5_npxGD',
        'home_roll_5_xGD',
        'away_roll_5_xGD',
        'home_roll_5_ppda',
        'away_roll_5_ppda',
        'home_roll_5_field_tilt',
        'away_roll_5_field_tilt',
        'home_roll_5_box_shot_ratio',
        'away_roll_5_box_shot_ratio',
        'home_roll_5_poss_diff',
        'away_roll_5_poss_diff',
        'home_roll_5_big_chances_created',
        'away_roll_5_big_chances_created',
        'home_roll_5_shot_quality_added',
        'away_roll_5_shot_quality_added',
    ],

    # ── Domain B: 扩展特征 (已移除赛后泄露项) ──
    'extended': [
        'home_pre_match_elo',
        'away_pre_match_elo',
        'home_rest_days',
        'away_rest_days',
        'rest_days_diff',
        'elo_diff',
        'ppda_diff',
        'field_tilt_diff',
        'xGD_diff',
        'is_cup',
    ],

    # ── Domain C: 盘口特征 (from raw_footballdata_odds) ──
    'odds': [
        'eu_odds_home',               # 欧赔主胜
        'eu_odds_draw',               # 欧赔平局
        'eu_odds_away',               # 欧赔客胜
        'eu_implied_home',            # 欧赔隐含主胜概率
        'eu_implied_draw',            # 欧赔隐含平局概率
        'eu_implied_away',            # 欧赔隐含客胜概率
        'odds_max_prob',
        'odds_entropy',
        'ah_line',                    # 让球数
        'ah_home_odds',               # 亚盘主队赔率
        'ah_away_odds',               # 亚盘客队赔率
        'ah_implied_home',            # 亚盘隐含主胜概率
        'ah_line_abs',                # 让球绝对值
        'ah_line_direction',          # 让球方向
    ],
}


ALL_FEATURES = []
for domain_feats in FEATURE_SCHEMA.values():
    ALL_FEATURES.extend(domain_feats)

# O/U 模型额外侧重节奏和进攻相关特征
OU_EXTRA_FEATURES = [
    'total_shot_pace',       # home + away shot_pace
    'npxGD_abs_diff',        # |home_opp_adj_npxgd - away_opp_adj_npxgd|
]


# ═══════════════════════════════════════════
# Section 2: Feature Vector Assembly
# ═══════════════════════════════════════════

class FeatureAssembler:
    """
    从 SQLite 数据湖组装单场比赛的特征向量。
    输出一个 1-row DataFrame，列名与 FEATURE_SCHEMA 对齐。
    """

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def assemble(self, match_id: str) -> pd.DataFrame:
        """组装单场特征向量"""
        cur = self.conn.cursor()
        row = {}

        # ── 基础信息 (使用已重命名的 dim_match) ──
        match = cur.execute(
            "SELECT *, Match_ID as match_id, Home_Team_ID as home_id, Away_Team_ID as away_id, Date as match_time FROM dim_match WHERE Match_ID=?", (match_id,)
        ).fetchone()
        if not match:
            raise ValueError(f"match_id={match_id} not found")

        home_id = match['home_id']
        away_id = match['away_id']

        # ── Domain A: Rolling Features (int_team_rolling_extended) ──
        for team_id, prefix in [(home_id, 'home'), (away_id, 'away')]:
            rf = cur.execute("""
                SELECT * FROM int_team_rolling_extended
                WHERE match_id=? AND team_id=? AND (window_size=5 OR window_size IS NULL)
            """, (match_id, team_id)).fetchone()

            if rf:
                row[f'{prefix}_roll_shot_pace'] = rf['roll_shot_pace'] or 0
                row[f'{prefix}_roll_trailing_xg_ratio'] = rf['roll_trailing_xg_ratio'] or 0
                row[f'{prefix}_roll_level_xg_ratio'] = rf['roll_level_xg_ratio'] or 0
                row[f'{prefix}_roll_opp_adj_npxgd'] = rf['roll_opp_adj_npxgd'] or 0
                row[f'{prefix}_roll_rest_days'] = rf['roll_rest_days'] or 4
            else:
                row[f'{prefix}_roll_shot_pace'] = 0
                row[f'{prefix}_roll_trailing_xg_ratio'] = 0
                row[f'{prefix}_roll_level_xg_ratio'] = 0
                row[f'{prefix}_roll_opp_adj_npxgd'] = 0
                row[f'{prefix}_roll_rest_days'] = 4

        # ── Domain B: Extended Features ──
        for team_id, prefix in [(home_id, 'home'), (away_id, 'away')]:
            ef = cur.execute("""
                SELECT pre_match_elo, opp_pre_match_elo, rest_days, rest_days_diff 
                FROM int_match_features_extended
                WHERE match_id=? AND team_id=?
            """, (match_id, team_id)).fetchone()
            
            if ef:
                row[f'{prefix}_pre_match_elo'] = ef['pre_match_elo'] or 1500
                row[f'{prefix}_rest_days'] = ef['rest_days'] or 3
                if prefix == 'home':
                    row['elo_diff'] = (ef['pre_match_elo'] or 1500) - (ef['opp_pre_match_elo'] or 1500)
                    row['rest_days_diff'] = ef['rest_days_diff'] or 0
            else:
                row[f'{prefix}_pre_match_elo'] = 1500
                row[f'{prefix}_rest_days'] = 3
                if prefix == 'home':
                    row['elo_diff'] = 0
                    row['rest_days_diff'] = 0

        # ── Domain A2: dbt Rolling Features (int_team_rolling_features) ──
        for team_id, prefix in [(home_id, 'home'), (away_id, 'away')]:
            dbt_rf = cur.execute("""
                SELECT roll_5_npxGD, roll_5_xGD, roll_5_ppda, roll_5_field_tilt,
                       roll_5_box_shot_ratio, roll_5_poss_diff,
                       roll_5_big_chances_created, roll_5_shot_quality_added
                FROM int_team_rolling_features
                WHERE match_id=? AND team_id=?
            """, (match_id, team_id)).fetchone()

            if dbt_rf:
                row[f'{prefix}_roll_5_npxGD']               = dbt_rf['roll_5_npxGD'] or 0
                row[f'{prefix}_roll_5_xGD']                 = dbt_rf['roll_5_xGD'] or 0
                row[f'{prefix}_roll_5_ppda']                = dbt_rf['roll_5_ppda'] or 0
                row[f'{prefix}_roll_5_field_tilt']          = dbt_rf['roll_5_field_tilt'] or 0
                row[f'{prefix}_roll_5_box_shot_ratio']      = dbt_rf['roll_5_box_shot_ratio'] or 0
                row[f'{prefix}_roll_5_poss_diff']           = dbt_rf['roll_5_poss_diff'] or 0
                row[f'{prefix}_roll_5_big_chances_created'] = dbt_rf['roll_5_big_chances_created'] or 0
                row[f'{prefix}_roll_5_shot_quality_added']  = dbt_rf['roll_5_shot_quality_added'] or 0
            else:
                for feat in FEATURE_SCHEMA['rolling_dbt']:
                    if feat.startswith(prefix):
                        row.setdefault(feat, 0)

        # ── Domain C: Odds Features ──
        odds = cur.execute("""
            SELECT * FROM raw_footballdata_odds o
            JOIN dim_match dm ON o.HomeTeam = dm.Home_Team_Name
                AND o.AwayTeam = dm.Away_Team_Name AND o.Date = dm.Date
            WHERE dm.Match_ID = ? LIMIT 1
        """, (match_id,)).fetchone() if self._table_exists('raw_footballdata_odds') else None

        if odds:
            row['eu_odds_home'] = odds['B365H'] or 0
            row['eu_odds_draw'] = odds['B365D'] or 0
            row['eu_odds_away'] = odds['B365A'] or 0

            # --- NEW AH FEATURES ---
            row['ah_line'] = odds['AHh'] or 0
            row['ah_home_odds'] = odds['B365AHH'] or 0
            row['ah_away_odds'] = odds['B365AHA'] or 0

            h, d, a = row['eu_odds_home'], row['eu_odds_draw'], row['eu_odds_away']
            if h > 0 and d > 0 and a > 0:
                s = 1/h + 1/d + 1/a
                row['eu_implied_home'] = (1/h)/s
                row['eu_implied_draw'] = (1/d)/s
                row['eu_implied_away'] = (1/a)/s
                probs = [row['eu_implied_home'], row['eu_implied_draw'], row['eu_implied_away']]
                row['odds_max_prob'] = max(probs)
                row['odds_entropy'] = -sum(p * np.log(p + 1e-9) for p in probs)
            else:
                row['eu_implied_home'] = 0
                row['eu_implied_draw'] = 0
                row['eu_implied_away'] = 0
                row['odds_max_prob'] = 0
                row['odds_entropy'] = 0

            # AH Derivative calculation
            h_ah, a_ah = row['ah_home_odds'], row['ah_away_odds']
            if h_ah > 0 and a_ah > 0:
                row['ah_implied_home'] = (1/h_ah) / (1/h_ah + 1/a_ah)
            else:
                row['ah_implied_home'] = 0.5
            row['ah_line_abs'] = abs(row['ah_line'])
            row['ah_line_direction'] = np.sign(row['ah_line'])
        else:
            for feat in FEATURE_SCHEMA['odds']:
                if 'implied' in feat:
                    row[feat] = 0.5 if 'ah' in feat else 1/3
                else:
                    row[feat] = 0

        # ── 构造 DataFrame ──
        df = pd.DataFrame([row])

        # 衍生特征
        df['ppda_diff']       = df['home_roll_5_ppda'] - df['away_roll_5_ppda']
        df['field_tilt_diff'] = df['home_roll_5_field_tilt'] - df['away_roll_5_field_tilt']
        df['xGD_diff']        = df['home_roll_5_xGD'] - df['away_roll_5_xGD']

        # 补充 O/U 专用衍生特征
        df['total_shot_pace'] = df['home_roll_shot_pace'] + df['away_roll_shot_pace']
        df['npxGD_abs_diff'] = (df['home_roll_opp_adj_npxgd'] - df['away_roll_opp_adj_npxgd']).abs()

        # 确保列顺序一致
        all_cols = []
        for domain in FEATURE_SCHEMA.values():
            all_cols.extend(domain)
        all_cols.extend(OU_EXTRA_FEATURES)

        for c in all_cols:
            if c not in df.columns:
                df[c] = 0

        return df[all_cols]



    def _table_exists(self, table_name: str) -> bool:
        r = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        ).fetchone()
        return r is not None

    def close(self):
        self.conn.close()


# ═══════════════════════════════════════════
# Section 3: Training Pipeline
# ═══════════════════════════════════════════

WDL_LABELS = {0: 'home_win', 1: 'draw', 2: 'away_win'}

# ── 默认优化参数 (保守优化) ──
DEFAULT_OPT_PARAMS = {
    'num_leaves': 63,
    'max_depth': 8,
    'learning_rate': 0.03,
    'min_data_in_leaf': 15,
    'feature_fraction': 0.8,
    'bagging_fraction': 0.8,
    'bagging_freq': 5,
    'lambda_l1': 0.1,
    'lambda_l2': 0.1,
}

def _load_best_params():
    """尝试加载 Optuna 调优的最佳参数"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, 'models_v4', 'best_params.json')
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                return data.get('wdl', {}).get('params'), data.get('ou', {}).get('params')
        except Exception as e:
            print(f"[WARN] Failed to load best_params.json: {e}")
    return None, None

BEST_WDL_PARAMS, BEST_OU_PARAMS = _load_best_params()

LGB_PARAMS_WDL = {
    'objective': 'multiclass',
    'num_class': 3,
    'metric': 'multi_logloss',
    'boosting_type': 'gbdt',
    'verbose': -1,
    'seed': 42,
    **(BEST_WDL_PARAMS if BEST_WDL_PARAMS else DEFAULT_OPT_PARAMS)
}

LGB_PARAMS_OU = {
    'objective': 'binary',
    'metric': 'binary_logloss',
    'boosting_type': 'gbdt',
    'verbose': -1,
    'seed': 42,
    **(BEST_OU_PARAMS if BEST_OU_PARAMS else DEFAULT_OPT_PARAMS)
}


class ModelTrainer:
    def __init__(self, db_path: str, model_dir: str = './models'):
        self.db_path = db_path
        self.model_dir = model_dir
        self.assembler = FeatureAssembler(db_path)
        
        self.model_wdl = None
        self.model_ou = None
        self.meta = {}

    def _table_exists(self, table_name):
        conn = sqlite3.connect(self.db_path)
        res = conn.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'").fetchone()
        conn.close()
        return res is not None

    def prepare_training_data(self):
        """全量数据读取 + 时间序列 80/20 split"""
        conn = sqlite3.connect(self.db_path)

        # 杯赛/欧战 League_ID 集合
        CUP_LIDS = {42, 73, 10216, 132, 133, 134, 138, 141, 209}

        # ── 1. 加载 Elo 与休息时间 ──
        print("[DATA] Loading baseline features...")
        ext_df = pd.read_sql("""
            SELECT match_id, team_id, pre_match_elo, opp_pre_match_elo,
                   rest_days, rest_days_diff
            FROM int_match_features_extended
        """, conn)

        # ── 2. 加载 Rolling Features ──
        print("[DATA] Loading rolling features...")
        roll_df = pd.read_sql("""
            SELECT match_id, team_id,
                   roll_shot_pace, roll_trailing_xg_ratio,
                   roll_level_xg_ratio, roll_opp_adj_npxgd, roll_rest_days
            FROM int_team_rolling_extended
            WHERE window_size = 5 OR window_size IS NULL
        """, conn)

        # ── 3. 加载 dbt Rolling Features ──
        print("[DATA] Loading dbt rolling features...")
        dbt_roll_df = pd.read_sql("""
            SELECT match_id, team_id,
                   roll_5_npxGD, roll_5_xGD, roll_5_ppda, roll_5_field_tilt,
                   roll_5_box_shot_ratio, roll_5_poss_diff,
                   roll_5_big_chances_created, roll_5_shot_quality_added,
                   roll_5_open_play_xg_for, roll_5_set_play_xg_for
            FROM int_team_rolling_features
        """, conn)
        dbt_roll_df['match_id'] = dbt_roll_df['match_id'].astype(str)
        dbt_roll_df = dbt_roll_df.drop_duplicates(subset=['match_id', 'team_id'], keep='last')

        # ── 3.1 加载 rolling zones features ──
        print("[DATA] Loading rolling zones features...")
        zones_df = pd.read_sql("""
            SELECT match_id, team_id,
                   roll_5_golden_zone_ratio_zones,
                   roll_5_outside_box_ratio_zones,
                   roll_5_avg_xg_per_shot,
                   roll_5_high_value_shots,
                   roll_5_shot_execution_added
            FROM int_team_rolling_zones
        """, conn)
        zones_df['match_id'] = zones_df['match_id'].astype(str)
        zones_df = zones_df.drop_duplicates(subset=['match_id', 'team_id'], keep='last')

        # ── 4. 加载比赛基础信息 + League_ID ──
        print("[DATA] Loading match labels...")
        match_df = pd.read_sql("""
            SELECT Match_ID as match_id, Home_Team_ID as home_id, Away_Team_ID as away_id,
                   home_score, away_score, Home_Team_Name, Away_Team_Name, Date,
                   League_ID as league_id
            FROM dim_match
            WHERE status = 'Finish' AND home_score IS NOT NULL
        """, conn)

        # ── 4.5 加载赔率信息 ──
        print("[DATA] Loading odds features...")
        odds_df = pd.read_sql("""
            SELECT HomeTeam, AwayTeam, Date,
                   B365H as eu_odds_home, B365D as eu_odds_draw, B365A as eu_odds_away,
                   AHh as ah_line, B365AHH as ah_home_odds, B365AHA as ah_away_odds
            FROM raw_footballdata_odds
        """, conn) if self._table_exists('raw_footballdata_odds') else pd.DataFrame()

        # 统一 match_id 类型
        match_df['match_id'] = match_df['match_id'].astype(str)
        ext_df['match_id'] = ext_df['match_id'].astype(str)
        roll_df['match_id'] = roll_df['match_id'].astype(str)
        ext_df = ext_df.drop_duplicates(subset=['match_id', 'team_id'], keep='last')
        roll_df = roll_df.drop_duplicates(subset=['match_id', 'team_id'], keep='last')

        # ── 5. 组装特征矩阵 ──
        print("[DATA] Assembling feature matrix...")

        def pivot_team_features(df, prefix):
            tmp = df.copy()
            cols = [col for col in tmp.columns if col not in ['match_id', 'team_id']]
            tmp.columns = [f"{prefix}_{col}" if col in cols else col for col in tmp.columns]
            return tmp

        data = match_df.merge(
            pivot_team_features(ext_df, 'home'), left_on=['match_id', 'home_id'], right_on=['match_id', 'team_id'], how='inner'
        ).drop('team_id', axis=1)
        data = data.merge(
            pivot_team_features(roll_df, 'home'), left_on=['match_id', 'home_id'], right_on=['match_id', 'team_id'], how='inner'
        ).drop('team_id', axis=1)
        data = data.merge(
            pivot_team_features(ext_df, 'away'), left_on=['match_id', 'away_id'], right_on=['match_id', 'team_id'], how='inner'
        ).drop('team_id', axis=1)
        data = data.merge(
            pivot_team_features(roll_df, 'away'), left_on=['match_id', 'away_id'], right_on=['match_id', 'team_id'], how='inner'
        ).drop('team_id', axis=1)
        data = data.merge(
            pivot_team_features(dbt_roll_df, 'home'),
            left_on=['match_id', 'home_id'], right_on=['match_id', 'team_id'], how='inner'
        ).drop('team_id', axis=1)
        data = data.merge(
            pivot_team_features(dbt_roll_df, 'away'),
            left_on=['match_id', 'away_id'], right_on=['match_id', 'team_id'], how='inner'
        ).drop('team_id', axis=1)
        data = data.merge(
            pivot_team_features(zones_df, 'home'),
            left_on=['match_id', 'home_id'], right_on=['match_id', 'team_id'], how='left'
        ).drop('team_id', axis=1)
        data = data.merge(
            pivot_team_features(zones_df, 'away'),
            left_on=['match_id', 'away_id'], right_on=['match_id', 'team_id'], how='left'
        ).drop('team_id', axis=1)

        # ── 5.5 合并赔率 ──
        if not odds_df.empty:
            data = data.merge(
                odds_df,
                left_on=['Home_Team_Name', 'Away_Team_Name', 'Date'],
                right_on=['HomeTeam', 'AwayTeam', 'Date'],
                how='left'
            )

        # 计算隐含概率（安全除法）
        if 'eu_odds_home' in data.columns:
            valid_odds = (data['eu_odds_home'] > 1) & (data['eu_odds_draw'] > 1) & (data['eu_odds_away'] > 1)
            data.loc[valid_odds, 'eu_implied_home'] = (1 / data.loc[valid_odds, 'eu_odds_home'])
            data.loc[valid_odds, 'eu_implied_draw'] = (1 / data.loc[valid_odds, 'eu_odds_draw'])
            data.loc[valid_odds, 'eu_implied_away'] = (1 / data.loc[valid_odds, 'eu_odds_away'])
            s = data['eu_implied_home'] + data['eu_implied_draw'] + data['eu_implied_away']
            s = s.replace(0, np.nan)
            data['eu_implied_home'] /= s
            data['eu_implied_draw'] /= s
            data['eu_implied_away'] /= s
            data['odds_max_prob'] = data[['eu_implied_home', 'eu_implied_draw', 'eu_implied_away']].max(axis=1)
            data['odds_entropy'] = -(
                data['eu_implied_home'] * np.log(data['eu_implied_home'] + 1e-9) +
                data['eu_implied_draw'] * np.log(data['eu_implied_draw'] + 1e-9) +
                data['eu_implied_away'] * np.log(data['eu_implied_away'] + 1e-9)
            )

        # ── 5.5.1 AH 特征衍生 ──
        if 'ah_line' in data.columns:
            valid_ah = (data['ah_home_odds'] > 1) & (data['ah_away_odds'] > 1)
            data['ah_implied_home'] = 0.5
            data.loc[valid_ah, 'ah_implied_home'] = (1 / data.loc[valid_ah, 'ah_home_odds']) / \
                                                  (1 / data.loc[valid_ah, 'ah_home_odds'] + 1 / data.loc[valid_ah, 'ah_away_odds'])
            data['ah_line_abs'] = data['ah_line'].abs().fillna(0)
            data['ah_line_direction'] = np.sign(data['ah_line'].fillna(0))

        # ── 5.6 is_cup 特征 ──
        data['is_cup'] = data['league_id'].apply(lambda x: 1 if x in CUP_LIDS else 0)

        # 补全缺失的特征列
        all_cols = []
        for domain in FEATURE_SCHEMA.values():
            all_cols.extend(domain)
        all_cols.extend(OU_EXTRA_FEATURES)

        for c in all_cols:
            if c not in data.columns:
                data[c] = 0.0

        if data.empty:
            print("[WARN] No matching data after joins.")
            return pd.DataFrame(), [], [], pd.DataFrame(), [], []

        # ── 6. 衍生特征 ──
        data['elo_diff'] = data['home_pre_match_elo'] - data['away_pre_match_elo']
        data['total_shot_pace'] = data['home_roll_shot_pace'] + data['away_roll_shot_pace']
        data['npxGD_abs_diff'] = (data['home_roll_opp_adj_npxgd'] - data['away_roll_opp_adj_npxgd']).abs()
        data['ppda_diff'] = data['home_roll_5_ppda'] - data['away_roll_5_ppda']
        data['field_tilt_diff'] = data['home_roll_5_field_tilt'] - data['away_roll_5_field_tilt']
        data['xGD_diff'] = data['home_roll_5_xGD'] - data['away_roll_5_xGD']

        # ── 6.5 赔率缺失：用中位数填充而非0 ──
        odds_cols = ['eu_odds_home', 'eu_odds_draw', 'eu_odds_away',
                     'eu_implied_home', 'eu_implied_draw', 'eu_implied_away',
                     'odds_max_prob', 'odds_entropy',
                     'ah_line', 'ah_home_odds', 'ah_away_odds', 'ah_implied_home',
                     'ah_line_abs', 'ah_line_direction']
        for c in odds_cols:
            if c in data.columns:
                # 针对概率类或比例类特征，缺失值填充 0.5 或均值更稳健
                if c == 'ah_implied_home': fill_val = 0.5
                elif 'eu_implied' in c: fill_val = 1/3
                elif 'direction' in c or c == 'ah_line': fill_val = 0
                else: fill_val = data[c].median()
                
                data[c] = data[c].fillna(fill_val)
                print(f"[DATA] {c}: 填充值={fill_val:.4f}, 缺失={data[c].isna().sum()}")

        # ── 7. Labels ──
        def get_wdl(row):
            if row['home_score'] > row['away_score']: return 0
            if row['home_score'] == row['away_score']: return 1
            return 2

        data['label_wdl'] = data.apply(get_wdl, axis=1).astype(int)
        data['label_ou'] = (data['home_score'] + data['away_score'] > 2.5).astype(int)

        conn.close()

        # ── 8. 时间序列 80/20 split ──
        data = data.sort_values('Date').reset_index(drop=True)
        split_idx = int(len(data) * 0.8)

        X = data[all_cols].fillna(0).astype(float)
        y_wdl = data['label_wdl'].values
        y_ou = data['label_ou'].values

        X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train_wdl, y_val_wdl = y_wdl[:split_idx], y_wdl[split_idx:]
        y_train_ou, y_val_ou = y_ou[:split_idx], y_ou[split_idx:]

        # 保存赔率隐含概率供评估用
        self._val_implied = None
        if 'eu_implied_home' in data.columns:
            implied_cols = ['eu_implied_home', 'eu_implied_draw', 'eu_implied_away']
            self._val_implied = data[implied_cols].iloc[split_idx:].fillna(1/3).values

        print(f"[DATA] Train: {X_train.shape}, Val: {X_val.shape}")
        print(f"[DATA] WDL分布(train): H={np.mean(y_train_wdl==0):.1%} D={np.mean(y_train_wdl==1):.1%} A={np.mean(y_train_wdl==2):.1%}")
        print(f"[DATA] WDL分布(val):   H={np.mean(y_val_wdl==0):.1%} D={np.mean(y_val_wdl==1):.1%} A={np.mean(y_val_wdl==2):.1%}")
        return X_train, X_val, y_train_wdl, y_val_wdl, y_train_ou, y_val_ou

    def train(self, n_rounds=500, early_stop=50):
        result = self.prepare_training_data()
        if isinstance(result[0], pd.DataFrame) and result[0].empty:
            print("[ERR] No training data found.")
            return False
        X_train, X_val, y_train_wdl, y_val_wdl, y_train_ou, y_val_ou = result

        print(f"\n[TRAIN] X_train: {X_train.shape}, X_val: {X_val.shape}")

        # ── WDL Model ──
        d_train = lgb.Dataset(X_train, label=y_train_wdl)
        d_val = lgb.Dataset(X_val, label=y_val_wdl, reference=d_train)
        self.model_wdl = lgb.train(
            LGB_PARAMS_WDL, d_train,
            num_boost_round=n_rounds,
            valid_sets=[d_val],
            callbacks=[lgb.early_stopping(early_stop), lgb.log_evaluation(50)]
        )

        # ── OU Model ──
        d_train_ou = lgb.Dataset(X_train, label=y_train_ou)
        d_val_ou = lgb.Dataset(X_val, label=y_val_ou, reference=d_train_ou)
        self.model_ou = lgb.train(
            LGB_PARAMS_OU, d_train_ou,
            num_boost_round=n_rounds,
            valid_sets=[d_val_ou],
            callbacks=[lgb.early_stopping(early_stop), lgb.log_evaluation(50)]
        )

        # ── Save Models ──
        os.makedirs(self.model_dir, exist_ok=True)
        self.model_wdl.save_model(os.path.join(self.model_dir, 'model_wdl.lgb'))
        self.model_ou.save_model(os.path.join(self.model_dir, 'model_ou.lgb'))

        # ── Feature Importance ──
        fi_wdl = dict(zip(X_train.columns, self.model_wdl.feature_importance('gain')))
        fi_ou = dict(zip(X_train.columns, self.model_ou.feature_importance('gain')))
        fi_total = sum(fi_wdl.values())
        fi_pct = {k: round(v / fi_total * 100, 2) for k, v in sorted(fi_wdl.items(), key=lambda x: -x[1])}

        print(f"\n[IMPORTANCE] WDL Top-10:")
        for i, (k, v) in enumerate(fi_pct.items()):
            if i >= 10: break
            print(f"  {k:40s} {v:.1f}%")

        odds_importance = sum(v for k, v in fi_pct.items() if 'odds' in k or 'eu_' in k or 'implied' in k)
        print(f"\n[IMPORTANCE] 赔率特征总占比: {odds_importance:.1f}%")

        # ── Evaluation on Validation Set ──
        print(f"\n{'='*60}")
        print(f"  验证集评估 (n={len(X_val)})")
        print(f"{'='*60}")

        wdl_val_pred = self.model_wdl.predict(X_val)
        ou_val_pred = self.model_ou.predict(X_val)

        # RPS (Ranked Probability Score)
        def calc_rps(pred_probs, actual_labels):
            rps_list = []
            for pred, label in zip(pred_probs, actual_labels):
                actual = [0, 0, 0]
                actual[int(label)] = 1
                cum_pred = np.cumsum(pred)
                cum_actual = np.cumsum(actual)
                rps_list.append(np.mean((cum_pred - cum_actual) ** 2))
            return np.mean(rps_list)

        model_rps = calc_rps(wdl_val_pred, y_val_wdl)
        naive_rps = calc_rps(np.full_like(wdl_val_pred, 1/3), y_val_wdl)

        print(f"  模型 RPS:  {model_rps:.4f}")
        print(f"  随机 RPS:  {naive_rps:.4f}  (1/3, 1/3, 1/3)")

        if self._val_implied is not None:
            odds_rps = calc_rps(self._val_implied, y_val_wdl)
            print(f"  赔率 RPS:  {odds_rps:.4f}  (市场隐含概率)")
            if model_rps < odds_rps:
                print(f"  → 模型优于市场 ({(odds_rps-model_rps)/odds_rps*100:.1f}% 改善)")
            else:
                print(f"  → ⚠️ 市场优于模型 ({(model_rps-odds_rps)/odds_rps*100:.1f}% 落后)")

        # Brier Score per direction
        from sklearn.metrics import brier_score_loss
        for i, name in enumerate(['home_win', 'draw', 'away_win']):
            brier = brier_score_loss((y_val_wdl == i).astype(int), wdl_val_pred[:, i])
            print(f"  Brier({name}): {brier:.4f}")
        brier_ou = brier_score_loss(y_val_ou, ou_val_pred)
        print(f"  Brier(over):     {brier_ou:.4f}")

        # 分桶校准检查
        print(f"\n  分桶校准 (WDL home_win):")
        home_probs = wdl_val_pred[:, 0]
        home_labels = (y_val_wdl == 0).astype(int)
        bins = np.arange(0, 1.05, 0.1)
        for lo, hi in zip(bins[:-1], bins[1:]):
            mask = (home_probs >= lo) & (home_probs < hi)
            n = mask.sum()
            if n > 0:
                pred_mean = home_probs[mask].mean()
                actual_freq = home_labels[mask].mean()
                print(f"    [{lo:.1f}-{hi:.1f}): n={n:4d}  pred={pred_mean:.3f}  actual={actual_freq:.3f}  gap={abs(pred_mean-actual_freq):.3f}")

        # ── Save Meta ──
        self.meta = {
            'trained_at': datetime.now().isoformat(),
            'features': list(X_train.columns),
            'n_samples': len(X_train) + len(X_val),
            'n_train': len(X_train),
            'n_val': len(X_val),
            'wdl_best_iteration': self.model_wdl.best_iteration,
            'ou_best_iteration': self.model_ou.best_iteration,
            'feature_importance_wdl': fi_pct,
            'odds_importance_pct': odds_importance,
            'rps_model': round(model_rps, 4),
            'rps_naive': round(naive_rps, 4),
        }
        with open(os.path.join(self.model_dir, 'meta.json'), 'w') as f:
            json.dump(self.meta, f, indent=2)

        print(f"\n[SUCCESS] Models saved to {self.model_dir}")
        return True


# ═══════════════════════════════════════════
# Section 4: Inference Engine
# ═══════════════════════════════════════════

class PredictEngine:
    def __init__(self, db_path: str, model_dir: str = './models'):
        self.db_path = db_path
        self.model_dir = model_dir
        self.assembler = FeatureAssembler(db_path)
        
        # Load Models
        self.model_wdl = None
        self.model_ou = None
        self.meta = {}
        
        if HAS_ML:
            wdl_path = os.path.join(model_dir, 'model_wdl.lgb')
            ou_path = os.path.join(model_dir, 'model_ou.lgb')
            meta_path = os.path.join(model_dir, 'meta.json')
            cal_path = os.path.join(model_dir, 'calibrators.pkl')
            
            if os.path.exists(wdl_path):
                self.model_wdl = lgb.Booster(model_file=wdl_path)
            if os.path.exists(ou_path):
                self.model_ou = lgb.Booster(model_file=ou_path)
                
            if os.path.exists(meta_path):
                with open(meta_path, 'r') as f:
                    self.meta = json.load(f)
            
            # 加载校准器
            self.calibrators = None
            if os.path.exists(cal_path):
                try:
                    with open(cal_path, 'rb') as f:
                        self.calibrators = pickle.load(f)
                    print("[INFO] Probability calibrators loaded successfully.")
                except Exception as e:
                    print(f"[WARN] Failed to load calibrators: {e}")

            self.has_models = (self.model_wdl is not None) or (self.model_ou is not None)
            self.explainer_wdl = shap.TreeExplainer(self.model_wdl) if self.model_wdl else None
            self.explainer_ou  = shap.TreeExplainer(self.model_ou)  if self.model_ou  else None

    def predict(self, match_id: str):
        if not self.has_models:
            return self._mock_predict(match_id)
            
        try:
            X = self.assembler.assemble(match_id)
            
            # WDL Probs
            wdl_res = self.model_wdl.predict(X)
            wdl_probs = wdl_res[0]
            
            # OU Probs
            ou_res = self.model_ou.predict(X)
            ou_prob = ou_res[0]

            # ── 概率校准 (Calibration Layer) ──
            raw_wdl = {'home': float(wdl_probs[0]), 'draw': float(wdl_probs[1]), 'away': float(wdl_probs[2])}
            raw_ou = {'over_25': float(ou_prob), 'under_25': 1.0 - float(ou_prob)}
            
            cal_wdl = raw_wdl.copy()
            cal_ou = raw_ou.copy()
            is_calibrated = False

            if self.calibrators:
                try:
                    cal_wdl['home'] = float(self.calibrators['home_win'].transform([raw_wdl['home']])[0])
                    cal_wdl['draw'] = float(self.calibrators['draw'].transform([raw_wdl['draw']])[0])
                    cal_wdl['away'] = float(self.calibrators['away_win'].transform([raw_wdl['away']])[0])
                    # 重新归一化 WDL（由于独立校准可能导致和不为 1）
                    s = cal_wdl['home'] + cal_wdl['draw'] + cal_wdl['away']
                    if s > 0:
                        for k in cal_wdl: cal_wdl[k] /= s
                    
                    cal_ou['over_25'] = float(self.calibrators['over'].transform([raw_ou['over_25']])[0])
                    cal_ou['under_25'] = 1.0 - cal_ou['over_25']
                    is_calibrated = True
                except Exception as e:
                    print(f"[WARN] Calibration transform failed: {e}")

            # SHAP 归因（Top-3）
            feature_names = self.meta.get('features', list(X.columns))
            shap_wdl_top3 = self._shap_top3_wdl(X, wdl_probs, feature_names)
            shap_ou_top3  = self._shap_top3_ou(X, ou_prob, feature_names)

            return {
                'match_id': match_id,
                'wdl': cal_wdl,
                'ou': cal_ou,
                'raw_wdl': raw_wdl,
                'raw_ou': raw_ou,
                'is_calibrated': is_calibrated,
                'shap_wdl_top3': shap_wdl_top3,
                'shap_ou_top3':  shap_ou_top3,
                'attribution':   shap_wdl_top3,
                'confidence': self._calc_confidence(wdl_probs, ou_prob),
                'ah_implied_home': float(X['ah_implied_home'].iloc[0]) if 'ah_implied_home' in X.columns else 0.5,
                'model_meta': self.meta
            }
            
        except Exception as e:
            print(f"[ERR] Prediction failed for {match_id}: {e}")
            return self._mock_predict(match_id)

    def _calc_confidence(self, wdl, ou):
        max_p = max(wdl)
        if max_p > 0.6: return "HIGH"
        if max_p > 0.45: return "MEDIUM"
        return "LOW"

    def _shap_top3_wdl(self, X, wdl_probs, feature_names):
        """返回 WDL 最大概率方向的 Top-3 SHAP 因子"""
        if self.explainer_wdl is None:
            return []
        try:
            # shap_values: list of [n_samples, n_features] per class, or [n_samples, n_features, n_classes]
            sv = self.explainer_wdl.shap_values(X)
            best_class = int(wdl_probs.argmax())
            # 兼容两种 shap 输出格式
            if isinstance(sv, list):
                vals = sv[best_class][0]
            else:
                vals = sv[0, :, best_class]
            top_idx = sorted(range(len(vals)), key=lambda i: abs(vals[i]), reverse=True)[:3]
            label_map = {0: '主胜', 1: '平局', 2: '客胜'}
            direction = label_map.get(best_class, str(best_class))
            return [
                {
                    'feature': feature_names[i] if i < len(feature_names) else f'f{i}',
                    'shap_value': round(float(vals[i]), 4),
                    'direction': direction
                }
                for i in top_idx
            ]
        except Exception as e:
            print(f"[WARN] SHAP WDL 计算失败: {e}")
            return []

    def _shap_top3_ou(self, X, ou_prob, feature_names):
        """返回 OU 大球/小球方向的 Top-3 SHAP 因子"""
        if self.explainer_ou is None:
            return []
        try:
            sv = self.explainer_ou.shap_values(X)
            # OU 是二分类或回归，sv 可能是 list[2] 或单个 array
            if isinstance(sv, list):
                vals = sv[1][0] if ou_prob >= 0.5 else sv[0][0]
            else:
                vals = sv[0]
            top_idx = sorted(range(len(vals)), key=lambda i: abs(vals[i]), reverse=True)[:3]
            direction = '大球' if ou_prob >= 0.5 else '小球'
            return [
                {
                    'feature': feature_names[i] if i < len(feature_names) else f'f{i}',
                    'shap_value': round(float(vals[i]), 4),
                    'direction': direction
                }
                for i in top_idx
            ]
        except Exception as e:
            print(f"[WARN] SHAP OU 计算失败: {e}")
            return []

    def _mock_predict(self, match_id):
        return {
            'match_id': match_id,
            'wdl': {'home': 0.4, 'draw': 0.3, 'away': 0.3},
            'ou': {'over_25': 0.5, 'under_25': 0.5},
            'confidence': "LOW",
            'attribution': [{'feature': 'mock', 'impact': 0}],
            'note': "Using Mock Predictions"
        }
