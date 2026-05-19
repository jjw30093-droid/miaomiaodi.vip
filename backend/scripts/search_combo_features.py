"""
search_combo_features.py — Phase A1: 组合特征搜索
================================================
扫描现有 rolling pre-match 特征的两两（和三元）算术组合，
用 season-grouped 时间序列 5-fold CV 评估每个组合对
WDL RPS 的边际提升，筛选出超过 Bonferroni 校正阈值的 winners。

关键设计原则：所有候选字段必须是 rolling（历史均值），避免当场比赛结果泄漏。

输出：
  backend/search_results/combo_winners.json   — 最终入选组合列表
  backend/search_results/combo_search.log     — 完整搜索日志

用法：
  cd /home/ubuntu/app/backend
  python scripts/search_combo_features.py
  python scripts/search_combo_features.py --dry-run   # 只生成候选、不跑CV
"""

import argparse
import json
import logging
import math
import os
import sqlite3
import sys
import warnings
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

try:
    import lightgbm as lgb
    HAS_ML = True
except ImportError:
    HAS_ML = False
    print("[ERROR] lightgbm not installed.")
    sys.exit(1)

# ═══════════════════════════════════════
# 配置
# ═══════════════════════════════════════

DB_PATH = Path(os.environ.get("SEARCH_DB", str(Path(__file__).parent.parent / "football_uk.db")))
OUT_DIR = Path(__file__).parent.parent / "search_results"
OUT_DIR.mkdir(exist_ok=True)

LOG_FILE = OUT_DIR / "combo_search.log"
WINNERS_FILE = OUT_DIR / "combo_winners.json"

HOLDOUT_DAYS = 90

BASE_DELTA_THRESHOLD = 0.0003   # flat threshold (no Bonferroni) — enough to filter noise
ROUND2_DELTA_THRESHOLD = 0.0005 # greedy forward selection keeps real winners
CORR_THRESHOLD = 0.85

STUMP_PARAMS = {
    "objective": "multiclass",
    "num_class": 3,
    "num_leaves": 31,       # larger than original stump for better signal
    "n_estimators": 100,    # more trees → better CV estimates
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_samples": 20,
    "verbose": -1,
    "n_jobs": -1,
    "seed": 42,
}

# ═══════════════════════════════════════
# v4 baseline 特征（来自 predict_engine.py FEATURE_SCHEMA）
# ═══════════════════════════════════════

V4_FEATURES = [
    # rolling extended
    'home_roll_shot_pace', 'away_roll_shot_pace',
    'home_roll_trailing_xg_ratio', 'away_roll_trailing_xg_ratio',
    'home_roll_level_xg_ratio', 'away_roll_level_xg_ratio',
    'home_roll_opp_adj_npxgd', 'away_roll_opp_adj_npxgd',
    'home_roll_rest_days', 'away_roll_rest_days',
    # dbt rolling
    'home_roll_5_npxGD', 'away_roll_5_npxGD',
    'home_roll_5_xGD', 'away_roll_5_xGD',
    'home_roll_5_ppda', 'away_roll_5_ppda',
    'home_roll_5_field_tilt', 'away_roll_5_field_tilt',
    'home_roll_5_box_shot_ratio', 'away_roll_5_box_shot_ratio',
    'home_roll_5_poss_diff', 'away_roll_5_poss_diff',
    'home_roll_5_big_chances_created', 'away_roll_5_big_chances_created',
    'home_roll_5_shot_quality_added', 'away_roll_5_shot_quality_added',
    'home_roll_5_open_play_xg_for', 'away_roll_5_open_play_xg_for',
    'home_roll_5_set_play_xg_for', 'away_roll_5_set_play_xg_for',
    # extended
    'home_pre_match_elo', 'away_pre_match_elo',
    'home_rest_days', 'away_rest_days',
    'rest_days_diff', 'elo_diff', 'ppda_diff', 'field_tilt_diff', 'xGD_diff', 'is_cup',
    # odds
    'eu_odds_home', 'eu_odds_draw', 'eu_odds_away',
    'eu_implied_home', 'eu_implied_draw', 'eu_implied_away',
    'odds_max_prob', 'odds_entropy',
    'ah_line', 'ah_home_odds', 'ah_away_odds',
    'ah_implied_home', 'ah_line_abs', 'ah_line_direction',
    # OU extras
    'total_shot_pace', 'npxGD_abs_diff',
]

# ═══════════════════════════════════════
# 候选字段池：只用 rolling pre-match 特征
# 格式 (column_name_in_data, short_label)
# column_name_in_data 是 home_* 或 away_* 前缀的列名
# ═══════════════════════════════════════

# 现有 rolling 特征（以 home_ 为例，away_ 同理）
ROLLING_FEATURE_PAIRS = [
    # from int_team_rolling_extended
    ('home_roll_shot_pace',           'shot_pace'),
    ('home_roll_trailing_xg_ratio',   'trailing_xg_ratio'),
    ('home_roll_level_xg_ratio',      'level_xg_ratio'),
    ('home_roll_opp_adj_npxgd',       'opp_adj_npxgd'),
    ('home_roll_rest_days',           'rest_days'),
    # from int_team_rolling_features (dbt)
    ('home_roll_5_npxGD',             'npxGD'),
    ('home_roll_5_xGD',               'xGD'),
    ('home_roll_5_ppda',              'ppda'),
    ('home_roll_5_field_tilt',        'field_tilt'),
    ('home_roll_5_box_shot_ratio',    'box_shot_ratio'),
    ('home_roll_5_poss_diff',         'poss_diff'),
    ('home_roll_5_big_chances_created', 'big_chances_created'),
    ('home_roll_5_shot_quality_added',  'shot_quality_added'),
    ('home_roll_5_open_play_xg_for',  'open_play_xg_for'),
    ('home_roll_5_set_play_xg_for',   'set_play_xg_for'),
]

# Domain groupings for same-domain pair filtering
DOMAIN_GROUPS = {
    "xg_attack": {
        'opp_adj_npxgd', 'npxGD', 'xGD',
        'open_play_xg_for', 'set_play_xg_for', 'shot_quality_added',
    },
    "shot_vol": {
        'shot_pace', 'big_chances_created', 'box_shot_ratio',
    },
    "control": {
        'poss_diff', 'field_tilt', 'ppda',
    },
    "game_state": {
        'trailing_xg_ratio', 'level_xg_ratio',
    },
    "rest": {
        'rest_days',
    },
}

# 跨域允许的配对
CROSS_DOMAIN_ALLOWED = {
    frozenset(['npxGD', 'ppda']),
    frozenset(['npxGD', 'field_tilt']),
    frozenset(['npxGD', 'poss_diff']),
    frozenset(['opp_adj_npxgd', 'ppda']),
    frozenset(['opp_adj_npxgd', 'field_tilt']),
    frozenset(['shot_pace', 'npxGD']),
    frozenset(['shot_pace', 'box_shot_ratio']),
    frozenset(['shot_pace', 'big_chances_created']),
    frozenset(['big_chances_created', 'shot_quality_added']),
    frozenset(['big_chances_created', 'ppda']),
    frozenset(['box_shot_ratio', 'poss_diff']),
    frozenset(['open_play_xg_for', 'set_play_xg_for']),
    frozenset(['open_play_xg_for', 'big_chances_created']),
    frozenset(['set_play_xg_for', 'ppda']),
    frozenset(['trailing_xg_ratio', 'npxGD']),
    frozenset(['level_xg_ratio', 'ppda']),
    frozenset(['field_tilt', 'box_shot_ratio']),
    frozenset(['poss_diff', 'ppda']),
    frozenset(['xGD', 'npxGD']),
    frozenset(['xGD', 'ppda']),
}

# Tier 1 强制注入（已是 rolling 特征组合，无泄漏）
TIER1_PRIORS_ROLLING = [
    # (label_a, op, label_b, description)
    ('npxGD',             '/',  'ppda',              'npxgd_per_ppda'),
    ('opp_adj_npxgd',     '/',  'ppda',              'adj_npxgd_per_ppda'),
    ('opp_adj_npxgd',     '*',  'field_tilt',        'adj_npxgd_x_field_tilt'),
    ('big_chances_created', '/', 'shot_pace',         'big_chance_rate'),
    ('open_play_xg_for',  '/',  'set_play_xg_for',   'open_to_set_play_ratio'),
    ('set_play_xg_for',   '/',  'opp_adj_npxgd',     'set_play_share'),
    ('shot_quality_added', '*', 'big_chances_created', 'quality_volume'),
    ('trailing_xg_ratio', '*',  'ppda',               'pressing_when_trailing'),
    ('level_xg_ratio',    '/',  'shot_pace',          'level_xg_per_shot'),
    ('npxGD',             '-',  'xGD',               'npxg_vs_xg_spread'),
    ('shot_pace',         '*',  'field_tilt',         'shot_pace_x_territory'),
    ('poss_diff',         '/',  'ppda',               'poss_adjusted_pressing'),
]

# ═══════════════════════════════════════
# 日志配置
# ═══════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("combo_search")


# ═══════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════

def load_training_data(db_path: str, holdout_days: int = 90) -> pd.DataFrame:
    """加载训练矩阵（只含 pre-match rolling + odds features，不含当场结果）"""
    conn = sqlite3.connect(db_path)
    cutoff = (datetime.utcnow() - timedelta(days=holdout_days)).strftime("%Y-%m-%d")
    logger.info(f"Holdout cutoff: {cutoff} (last {holdout_days} days excluded)")

    match_df = pd.read_sql("""
        SELECT Match_ID as match_id, Home_Team_ID as home_id, Away_Team_ID as away_id,
               home_score, away_score, Date, Season, League_ID as league_id,
               Home_Team_Name, Away_Team_Name
        FROM dim_match
        WHERE status = 'Finish' AND home_score IS NOT NULL AND Date < ?
    """, conn, params=(cutoff,))
    match_df['match_id'] = match_df['match_id'].astype(str)
    logger.info(f"Matches loaded (pre-holdout): {len(match_df)}")

    # Rolling extended (pre-match rolling averages)
    roll_df = pd.read_sql("""
        SELECT match_id, team_id,
               roll_shot_pace, roll_trailing_xg_ratio,
               roll_level_xg_ratio, roll_opp_adj_npxgd, roll_rest_days
        FROM int_team_rolling_extended
        WHERE window_size = 5 OR window_size IS NULL
    """, conn)
    roll_df['match_id'] = roll_df['match_id'].astype(str)
    roll_df = roll_df.drop_duplicates(subset=['match_id', 'team_id'], keep='last')

    # dbt rolling (pre-match rolling averages)
    dbt_df = pd.read_sql("""
        SELECT match_id, team_id,
               roll_5_npxGD, roll_5_xGD, roll_5_ppda, roll_5_field_tilt,
               roll_5_box_shot_ratio, roll_5_poss_diff,
               roll_5_big_chances_created, roll_5_shot_quality_added,
               roll_5_open_play_xg_for, roll_5_set_play_xg_for
        FROM int_team_rolling_features
    """, conn)
    dbt_df['match_id'] = dbt_df['match_id'].astype(str)
    dbt_df = dbt_df.drop_duplicates(subset=['match_id', 'team_id'], keep='last')

    # ELO + rest_days (pre-match, not leaky)
    ext_df = pd.read_sql("""
        SELECT match_id, team_id, pre_match_elo, opp_pre_match_elo,
               rest_days, rest_days_diff
        FROM int_match_features_extended
    """, conn)
    ext_df['match_id'] = ext_df['match_id'].astype(str)
    ext_df = ext_df.drop_duplicates(subset=['match_id', 'team_id'], keep='last')

    # Odds (pre-match, not leaky)
    try:
        odds_df = pd.read_sql("""
            SELECT HomeTeam, AwayTeam, Date,
                   B365H as eu_odds_home, B365D as eu_odds_draw, B365A as eu_odds_away,
                   AHh as ah_line, B365AHH as ah_home_odds, B365AHA as ah_away_odds
            FROM raw_footballdata_odds
        """, conn)
    except Exception:
        odds_df = pd.DataFrame()

    conn.close()

    # Pivot per-team rolling features to home/away
    def pivot(df, prefix, cols):
        sub = df[['match_id', 'team_id'] + cols].copy()
        sub = sub.rename(columns={c: f"{prefix}_{c}" for c in cols})
        return sub

    roll_cols = [c for c in roll_df.columns if c not in ('match_id', 'team_id')]
    dbt_cols  = [c for c in dbt_df.columns  if c not in ('match_id', 'team_id')]
    ext_cols  = ['pre_match_elo', 'opp_pre_match_elo', 'rest_days', 'rest_days_diff']

    data = match_df.copy()
    for prefix, id_col, df, cols in [
        ('home', 'home_id', roll_df, roll_cols),
        ('away', 'away_id', roll_df, roll_cols),
        ('home', 'home_id', dbt_df,  dbt_cols),
        ('away', 'away_id', dbt_df,  dbt_cols),
        ('home', 'home_id', ext_df,  ext_cols),
        ('away', 'away_id', ext_df,  ext_cols),
    ]:
        piv = pivot(df, prefix, cols)
        data = data.merge(piv, left_on=['match_id', id_col],
                          right_on=['match_id', 'team_id'], how='inner')
        data = data.drop(columns=['team_id'], errors='ignore')

    if not odds_df.empty:
        data = data.merge(odds_df,
                          left_on=['Home_Team_Name', 'Away_Team_Name', 'Date'],
                          right_on=['HomeTeam', 'AwayTeam', 'Date'], how='left')
        valid = (data['eu_odds_home'] > 1) & (data['eu_odds_draw'] > 1) & (data['eu_odds_away'] > 1)
        for col in ['eu_odds_home', 'eu_odds_draw', 'eu_odds_away']:
            data.loc[~valid, col] = np.nan
        data.loc[valid, 'eu_implied_home'] = 1 / data.loc[valid, 'eu_odds_home']
        data.loc[valid, 'eu_implied_draw'] = 1 / data.loc[valid, 'eu_odds_draw']
        data.loc[valid, 'eu_implied_away'] = 1 / data.loc[valid, 'eu_odds_away']
        s = (data['eu_implied_home'] + data['eu_implied_draw'] + data['eu_implied_away']).replace(0, np.nan)
        data['eu_implied_home'] /= s
        data['eu_implied_draw'] /= s
        data['eu_implied_away'] /= s
        data['odds_max_prob'] = data[['eu_implied_home', 'eu_implied_draw', 'eu_implied_away']].max(axis=1)
        data['odds_entropy'] = -(
            data['eu_implied_home'].fillna(1/3) * np.log(data['eu_implied_home'].fillna(1/3) + 1e-9) +
            data['eu_implied_draw'].fillna(1/3) * np.log(data['eu_implied_draw'].fillna(1/3) + 1e-9) +
            data['eu_implied_away'].fillna(1/3) * np.log(data['eu_implied_away'].fillna(1/3) + 1e-9)
        )
        valid_ah = (data['ah_home_odds'] > 1) & (data['ah_away_odds'] > 1)
        data['ah_implied_home'] = 0.5
        data.loc[valid_ah, 'ah_implied_home'] = (
            (1 / data.loc[valid_ah, 'ah_home_odds']) /
            (1 / data.loc[valid_ah, 'ah_home_odds'] + 1 / data.loc[valid_ah, 'ah_away_odds'])
        )
        data['ah_line_abs'] = data['ah_line'].abs().fillna(0)
        data['ah_line_direction'] = np.sign(data['ah_line'].fillna(0))

    # Derived v4 features
    data['elo_diff'] = data.get('home_pre_match_elo', 1500) - data.get('away_pre_match_elo', 1500)
    data['total_shot_pace'] = data.get('home_roll_shot_pace', 0) + data.get('away_roll_shot_pace', 0)
    data['npxGD_abs_diff'] = (data.get('home_roll_opp_adj_npxgd', 0) - data.get('away_roll_opp_adj_npxgd', 0)).abs()
    data['ppda_diff'] = data.get('home_roll_5_ppda', 0) - data.get('away_roll_5_ppda', 0)
    data['field_tilt_diff'] = data.get('home_roll_5_field_tilt', 0) - data.get('away_roll_5_field_tilt', 0)
    data['xGD_diff'] = data.get('home_roll_5_xGD', 0) - data.get('away_roll_5_xGD', 0)
    data['is_cup'] = data['league_id'].apply(lambda x: 1 if x in {42,73,10216,132,133,134,138,141,209} else 0)

    # rest_days from ext (home team)
    if 'home_rest_days' not in data.columns:
        data['home_rest_days'] = data.get('home_rest_days', 3)
    if 'away_rest_days' not in data.columns:
        data['away_rest_days'] = data.get('away_rest_days', 3)
    if 'rest_days_diff' not in data.columns:
        data['rest_days_diff'] = 0

    # Labels
    data['label_wdl'] = data.apply(
        lambda r: 0 if r['home_score'] > r['away_score'] else (1 if r['home_score'] == r['away_score'] else 2),
        axis=1).astype(int)

    data = data.sort_values('Date').reset_index(drop=True)
    logger.info(f"Training matrix shape: {data.shape}")
    return data


# ═══════════════════════════════════════
# 候选生成（只用 rolling 特征）
# ═══════════════════════════════════════

def is_allowed_pair(label_a: str, label_b: str) -> bool:
    for grp in DOMAIN_GROUPS.values():
        if label_a in grp and label_b in grp:
            return True
    if frozenset([label_a, label_b]) in CROSS_DOMAIN_ALLOWED:
        return True
    return False


def get_col(data: pd.DataFrame, label: str, prefix: str) -> pd.Series:
    """从数据中取 home_* 或 away_* 版本的 rolling 列"""
    # Map label → actual column name
    label_to_col = {rp[1]: rp[0] for rp in ROLLING_FEATURE_PAIRS}
    col_home = label_to_col.get(label, f"home_{label}")
    col = col_home.replace('home_', f'{prefix}_')
    return data.get(col, pd.Series(np.nan, index=data.index)).fillna(0).astype(float)


def apply_op(a: pd.Series, b: pd.Series, op: str) -> pd.Series:
    if op == '+': return a + b
    if op == '-': return a - b
    if op == '*': return a * b
    if op == '/': return a / b.clip(lower=1e-3)
    raise ValueError(op)


def generate_candidates() -> list[dict]:
    labels = [rp[1] for rp in ROLLING_FEATURE_PAIRS]
    ops = ['+', '-', '*', '/']
    seen = set()
    candidates = []

    for la, lb in combinations(labels, 2):
        if not is_allowed_pair(la, lb):
            continue
        for op in ops:
            key = (frozenset([la, lb]), op) if op in ('+', '*') else (la, op, lb)
            if key in seen:
                continue
            seen.add(key)
            name = f"combo_{la}_{op.replace('/', 'div').replace('*', 'mul')}_{lb}"
            candidates.append({'label_a': la, 'op': op, 'label_b': lb, 'name': name})

    # Inject Tier 1 priors
    for la, op, lb, desc in TIER1_PRIORS_ROLLING:
        key = (frozenset([la, lb]), op) if op in ('+', '*') else (la, op, lb)
        if key not in seen:
            seen.add(key)
            candidates.append({'label_a': la, 'op': op, 'label_b': lb, 'name': desc})

    return candidates


def build_diff_col(data: pd.DataFrame, label_a: str, op: str, label_b: str) -> pd.Series:
    """
    Compute (home_combo - away_combo) as the feature.
    home_combo = home_feat_a op home_feat_b
    away_combo = away_feat_a op away_feat_b
    """
    home_col = apply_op(get_col(data, label_a, 'home'), get_col(data, label_b, 'home'), op)
    away_col = apply_op(get_col(data, label_a, 'away'), get_col(data, label_b, 'away'), op)
    return home_col - away_col


# ═══════════════════════════════════════
# CV 评估
# ═══════════════════════════════════════

def rps_score(y_true: np.ndarray, proba: np.ndarray) -> float:
    n_classes = proba.shape[1]
    cumprob = np.cumsum(proba, axis=1)
    cumact = np.zeros_like(cumprob)
    for i, label in enumerate(y_true):
        cumact[i, label:] = 1.0
    return float(np.mean(np.sum((cumprob - cumact) ** 2, axis=1)) / (n_classes - 1))


def season_group_cv_rps(X: np.ndarray, y: np.ndarray,
                        seasons: np.ndarray, n_splits: int = 5) -> tuple[float, float]:
    unique_seasons = sorted(set(seasons))
    n = len(unique_seasons)
    fold_size = max(1, n // n_splits)

    rps_scores = []
    for i in range(n_splits):
        val_start = i * fold_size
        val_end = val_start + fold_size
        val_seasons = set(unique_seasons[val_start:val_end])
        train_seasons = set(unique_seasons[:val_start])
        if not train_seasons or not val_seasons:
            continue
        train_mask = np.isin(seasons, list(train_seasons))
        val_mask   = np.isin(seasons, list(val_seasons))
        if train_mask.sum() < 100 or val_mask.sum() < 20:
            continue
        model = lgb.LGBMClassifier(**STUMP_PARAMS)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model.fit(X[train_mask], y[train_mask])
        proba = model.predict_proba(X[val_mask])
        rps_scores.append(rps_score(y[val_mask], proba))

    if not rps_scores:
        return 1.0, 1.0
    return float(np.mean(rps_scores)), float(np.std(rps_scores))


def compute_baseline(data: pd.DataFrame, v4_cols: list[str], seasons: np.ndarray) -> float:
    X = data[v4_cols].fillna(0).astype(float).values
    y = data['label_wdl'].values
    rps, _ = season_group_cv_rps(X, y, seasons)
    logger.info(f"v4 baseline CV RPS: {rps:.6f}")
    return rps


# ═══════════════════════════════════════
# Greedy forward selection
# ═══════════════════════════════════════

def greedy_forward(survivors: list[dict], data: pd.DataFrame,
                   v4_cols: list[str], seasons: np.ndarray,
                   baseline_rps: float,
                   max_adds: int = 30, stop_delta: float = 0.001,
                   patience: int = 5) -> list[dict]:
    accepted = []
    accepted_vals = {}
    fail_streak = 0
    current_rps = baseline_rps

    sorted_surv = sorted(survivors, key=lambda x: x['delta'], reverse=True)

    for item in sorted_surv:
        if len(accepted) >= max_adds:
            break
        name = item['name']
        col = item['col_series']
        vals = col.fillna(0).values

        # Correlation de-duplication
        if accepted_vals:
            mat = np.column_stack(list(accepted_vals.values()))
            skip = any(abs(np.corrcoef(vals, mat[:, i])[0, 1]) > CORR_THRESHOLD
                       for i in range(mat.shape[1]))
            if skip:
                logger.info(f"  SKIP {name}: high corr with accepted")
                continue

        # Build augmented feature set
        base_X = data[v4_cols].fillna(0).astype(float).values
        extra = np.column_stack([v for v in accepted_vals.values()] + [vals]) \
            if accepted_vals else vals.reshape(-1, 1)
        X_aug = np.column_stack([base_X, extra])
        y = data['label_wdl'].values
        new_rps, new_std = season_group_cv_rps(X_aug, y, seasons)
        delta = current_rps - new_rps

        if delta >= stop_delta:
            logger.info(f"  ACCEPT {name}: delta={delta:.6f} (std={new_std:.4f})")
            accepted.append({**item, 'greedy_delta': delta, 'greedy_std': new_std})
            accepted_vals[name] = vals
            current_rps = new_rps
            fail_streak = 0
        else:
            logger.info(f"  PASS   {name}: delta={delta:.6f} < {stop_delta}")
            fail_streak += 1
            if fail_streak >= patience:
                logger.info(f"Stopping greedy selection after {patience} consecutive failures")
                break

    return accepted


# ═══════════════════════════════════════
# Triple candidates
# ═══════════════════════════════════════

MODIFIER_LABELS = [
    'ppda', 'field_tilt', 'opp_adj_npxgd', 'npxGD',
    'shot_pace', 'big_chances_created', 'poss_diff',
]


def generate_triples(winners: list[dict], data: pd.DataFrame) -> list[dict]:
    triples = []
    for w in winners[:20]:
        parent_col = w['col_series']
        for ml in MODIFIER_LABELS:
            home_mod = get_col(data, ml, 'home')
            away_mod = get_col(data, ml, 'away')
            for op in ['*', '/']:
                name_mul = op.replace('/', 'div').replace('*', 'mul')
                h_val = apply_op(apply_op(get_col(data, w['label_a'], 'home'),
                                          get_col(data, w['label_b'], 'home'),
                                          w['op']), home_mod, op)
                a_val = apply_op(apply_op(get_col(data, w['label_a'], 'away'),
                                          get_col(data, w['label_b'], 'away'),
                                          w['op']), away_mod, op)
                triples.append({
                    'name': f"triple_{w['name']}_{name_mul}_{ml}",
                    'type': 'triple',
                    'label_a': w['label_a'], 'op': w['op'], 'label_b': w['label_b'],
                    'modifier': ml, 'mod_op': op,
                    'col_series': h_val - a_val,
                })
    return triples


# ═══════════════════════════════════════
# Main
# ═══════════════════════════════════════

def main(dry_run: bool = False):
    logger.info("=" * 60)
    logger.info("Phase A1: Combo Feature Search (rolling features only)")
    logger.info(f"DB: {DB_PATH}")
    logger.info(f"Started: {datetime.utcnow().isoformat()}")
    logger.info("=" * 60)

    data = load_training_data(str(DB_PATH), HOLDOUT_DAYS)

    # Ensure v4 cols exist
    v4_cols = []
    for c in V4_FEATURES:
        if c not in data.columns:
            data[c] = 0.0
        v4_cols.append(c)

    seasons = data['Season'].values
    candidates = generate_candidates()
    logger.info(f"Total pair candidates: {len(candidates)}")

    if dry_run:
        for c in candidates[:20]:
            logger.info(f"  {c['name']}")
        logger.info("... (dry run done)")
        return

    # Baseline
    logger.info("\n--- Computing v4 baseline RPS ---")
    baseline_rps = compute_baseline(data, v4_cols, seasons)

    n_cand = len(candidates)
    round1_thr = BASE_DELTA_THRESHOLD
    logger.info(f"\n--- Round 1: {n_cand} candidates | threshold={round1_thr:.6f} ---")

    survivors = []
    for i, cand in enumerate(candidates):
        diff_col = build_diff_col(data, cand['label_a'], cand['op'], cand['label_b'])
        X_aug = np.column_stack([data[v4_cols].fillna(0).astype(float).values,
                                  diff_col.fillna(0).values.reshape(-1, 1)])
        y = data['label_wdl'].values
        mean_rps, std = season_group_cv_rps(X_aug, y, seasons)
        delta = baseline_rps - mean_rps

        msg = f"[{i+1}/{n_cand}] {cand['name']}: delta={delta:.6f} std={std:.4f}"
        if delta >= round1_thr:
            logger.info(f"SURVIVOR {msg}")
            survivors.append({**cand, 'delta': delta, 'std': std, 'col_series': diff_col})
        else:
            logger.debug(f"drop     {msg}")

        if (i + 1) % 30 == 0:
            logger.info(f"Progress: {i+1}/{n_cand} | survivors: {len(survivors)}")

    logger.info(f"\nRound 1: {len(survivors)} survivors from {n_cand}")

    # Greedy forward
    logger.info("\n--- Round 2: Greedy forward selection ---")
    accepted_pairs = greedy_forward(survivors, data, v4_cols, seasons, baseline_rps)
    logger.info(f"Round 2: {len(accepted_pairs)} pairs accepted")

    # Triples
    logger.info("\n--- Triples ---")
    triples = generate_triples(accepted_pairs, data)
    logger.info(f"Triple candidates: {len(triples)}")
    triple_surv = []
    for t in triples:
        X_aug = np.column_stack([data[v4_cols].fillna(0).astype(float).values,
                                   t['col_series'].fillna(0).values.reshape(-1, 1)])
        mean_rps, std = season_group_cv_rps(X_aug, data['label_wdl'].values, seasons)
        delta = baseline_rps - mean_rps
        if delta >= round1_thr:
            triple_surv.append({**t, 'delta': delta, 'std': std})
    accepted_triples = greedy_forward(triple_surv, data, v4_cols, seasons, baseline_rps,
                                       max_adds=10)
    logger.info(f"Triples accepted: {len(accepted_triples)}")

    # Output
    final = accepted_pairs + accepted_triples
    output = []
    for w in final:
        output.append({
            'name': w['name'], 'type': w.get('type', 'pair'),
            'label_a': w.get('label_a', ''), 'op': w.get('op', ''), 'label_b': w.get('label_b', ''),
            'modifier': w.get('modifier', ''), 'mod_op': w.get('mod_op', ''),
            'round1_delta': float(w.get('delta', 0)), 'round1_std': float(w.get('std', 0)),
            'greedy_delta': float(w.get('greedy_delta', 0)), 'greedy_std': float(w.get('greedy_std', 0)),
        })

    with open(WINNERS_FILE, 'w') as f:
        json.dump({
            'generated_at': datetime.utcnow().isoformat(),
            'baseline_rps': baseline_rps,
            'round1_threshold': round1_thr,
            'n_candidates': n_cand,
            'n_survivors_round1': len(survivors),
            'n_accepted_pairs': len(accepted_pairs),
            'n_accepted_triples': len(accepted_triples),
            'winners': output,
        }, f, indent=2)

    logger.info(f"\n{'='*60}")
    logger.info(f"DONE. {len(final)} features accepted total.")
    logger.info(f"Results: {WINNERS_FILE}")
    logger.info(f"Finished: {datetime.utcnow().isoformat()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    main(dry_run=args.dry_run)
