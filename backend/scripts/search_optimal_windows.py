"""
search_optimal_windows.py — Phase A2: 滚动窗口最优化扫描
==========================================================
对每个 rolling feature，扫描窗口 {3,5,7,10,14,20,30,50,season_to_date}，
用 season-grouped 时间序列 5-fold CV 找每个特征的最优 lookback。

输出：
  backend/search_results/window_winners.json   — {feature: [best_window, second_window]}
  backend/search_results/window_search.log     — 完整搜索日志

用法：
  cd /home/ubuntu/app/backend
  python scripts/search_optimal_windows.py
  python scripts/search_optimal_windows.py --feature npxGD   # 只测单个特征
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import warnings
from datetime import datetime, timedelta
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

LOG_FILE = OUT_DIR / "window_search.log"
WINNERS_FILE = OUT_DIR / "window_winners.json"

HOLDOUT_DAYS = 90

# 窗口网格
WINDOW_GRID = [3, 5, 7, 10, 14, 20, 30, 50, 'season_to_date']

# 选择 top-2 的最小 ΔRPS 门槛（vs window=5 baseline）
MIN_IMPROVEMENT = 0.0003

# LightGBM stump（和 combo search 保持一致）
STUMP_PARAMS = {
    "objective": "multiclass",
    "num_class": 3,
    "num_leaves": 15,
    "n_estimators": 50,
    "learning_rate": 0.1,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_samples": 20,
    "verbose": -1,
    "n_jobs": -1,
    "seed": 42,
}

# 要扫描的 rolling features
# key = 特征名称（描述）
# value = 在 flat 数据中对应的 RAW 列名（per-match 当场值，供滚动计算）
ROLLING_FEATURES = {
    # 来自 int_team_match_flattened 的当场统计字段（RAW）
    'npxGD':               'npxGD',            # npxG_for - npxGA_against
    'xGD':                 'xGD',              # xG_for - xGA_against
    'ppda':                'proxy_ppda',       # pressing metric
    'field_tilt':          'field_tilt',
    'box_shot_ratio':      'box_shot_ratio',
    'poss_diff':           'possession_diff',
    'big_chances_created': 'big_chances_created',
    'shot_quality_added':  'shot_quality_added',
    'open_play_xg_for':    'xG_open_play_for',
    'set_play_xg_for':     'xG_set_play_for',
    # 来自 int_match_features_extended（已在 load_flat_data 中 merge）
    'shot_pace':           'shot_pace',
    'trailing_xg_ratio':   'trailing_xg_ratio',
    'level_xg_ratio':      'level_xg_ratio',
    'opp_adj_npxgd':       'opp_adj_npxgd',
    'rest_days':           'rest_days',
    # 新增统计（从 fact_team_match_stats 已 merge 进 flat）
    'keeper_saves':        'keeper_saves',
    'blocked_shots':       'blocked_shots',
}

# v4 baseline features（不含要测试的 rolling feature，用于对照）
V4_FEATURES_BASE = [
    'home_pre_match_elo', 'away_pre_match_elo',
    'home_rest_days', 'away_rest_days',
    'rest_days_diff', 'elo_diff', 'ppda_diff', 'field_tilt_diff', 'xGD_diff', 'is_cup',
    'eu_implied_home', 'eu_implied_draw', 'eu_implied_away',
    'odds_max_prob', 'odds_entropy',
    'ah_implied_home', 'ah_line_abs', 'ah_line_direction',
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
logger = logging.getLogger("window_search")


# ═══════════════════════════════════════
# 数据加载
# ═══════════════════════════════════════

def load_flat_data(db_path: str, holdout_days: int = 90) -> pd.DataFrame:
    """加载 per-team 扁平化统计（int_team_match_flattened）"""
    conn = sqlite3.connect(db_path)
    cutoff = (datetime.utcnow() - timedelta(days=holdout_days)).strftime("%Y-%m-%d")

    flat = pd.read_sql("""
        SELECT f.match_id, f.match_date, f.Season, f.team_id, f.is_home,
               f.xG_for, f.npxG_for, f.xGA_against, f.npxGA_against, f.npxGD,
               f.xGD, f.xG_open_play_for, f.xG_set_play_for,
               f.big_chances_created, f.big_chances_missed, f.big_chances_conceded,
               f.shot_quality_added, f.total_shots_for, f.shots_on_target_for,
               f.box_shot_ratio, f.possession_pct, f.field_tilt, f.possession_diff,
               f.proxy_ppda, f.team_goals_prevented,
               f.golden_zone_shot_ratio_for, f.outside_box_shot_ratio_for,
               f.goals_for, f.goals_conceded
        FROM int_team_match_flattened f
        JOIN dim_match d ON CAST(f.match_id AS TEXT) = CAST(d.Match_ID AS TEXT)
        WHERE d.status = 'Finish' AND d.home_score IS NOT NULL AND f.match_date < ?
        ORDER BY f.match_date, f.match_id
    """, conn, params=(cutoff,))
    flat['match_id'] = flat['match_id'].astype(str)

    # 同场同队只保留一条
    flat = flat.drop_duplicates(subset=['match_id', 'team_id'])

    # 尝试加载额外列
    try:
        extra = pd.read_sql("""
            SELECT Match_ID as match_id, Team_ID as team_id,
                   keeper_saves, blocked_shots
            FROM fact_team_match_stats WHERE Period = 'All'
        """, conn)
        extra['match_id'] = extra['match_id'].astype(str)
        flat = flat.merge(extra, on=['match_id', 'team_id'], how='left')
    except Exception:
        flat['keeper_saves'] = np.nan
        flat['blocked_shots'] = np.nan

    # ext features
    ext = pd.read_sql("""
        SELECT match_id, team_id, shot_pace, opp_adj_npxgd,
               xg_when_leading, xg_when_trailing, xg_when_level,
               trailing_xg_ratio, level_xg_ratio, rest_days
        FROM int_match_features_extended
    """, conn)
    ext['match_id'] = ext['match_id'].astype(str)
    flat = flat.merge(ext, on=['match_id', 'team_id'], how='left')

    conn.close()
    logger.info(f"Flat data loaded: {len(flat)} team-match rows (pre-holdout)")
    return flat


def load_match_labels_and_features(db_path: str, holdout_days: int = 90) -> pd.DataFrame:
    """加载比赛标签 + odds，用于 CV 评估"""
    conn = sqlite3.connect(db_path)
    cutoff = (datetime.utcnow() - timedelta(days=holdout_days)).strftime("%Y-%m-%d")

    match_df = pd.read_sql("""
        SELECT Match_ID as match_id, Home_Team_ID as home_id, Away_Team_ID as away_id,
               home_score, away_score, Date, Season,
               League_ID as league_id, Home_Team_Name, Away_Team_Name
        FROM dim_match
        WHERE status = 'Finish' AND home_score IS NOT NULL AND Date < ?
    """, conn, params=(cutoff,))
    match_df['match_id'] = match_df['match_id'].astype(str)

    # ELO 和 rest_days_diff
    ext2 = pd.read_sql("""
        SELECT match_id, team_id, pre_match_elo, opp_pre_match_elo, rest_days_diff
        FROM int_match_features_extended
    """, conn)
    ext2['match_id'] = ext2['match_id'].astype(str)

    # odds
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

    # pivot home ELO
    home_ext = ext2.rename(columns={
        'pre_match_elo': 'home_pre_match_elo',
        'opp_pre_match_elo': 'away_pre_match_elo',
    })
    match_df = match_df.merge(
        home_ext[['match_id', 'team_id', 'home_pre_match_elo', 'away_pre_match_elo', 'rest_days_diff']],
        left_on=['match_id', 'home_id'], right_on=['match_id', 'team_id'], how='left'
    ).drop(columns=['team_id'], errors='ignore')

    away_rest = ext2[['match_id', 'team_id', 'pre_match_elo']].rename(
        columns={'pre_match_elo': 'away_elo_check'})
    match_df = match_df.merge(
        away_rest, left_on=['match_id', 'away_id'],
        right_on=['match_id', 'team_id'], how='left'
    ).drop(columns=['team_id', 'away_elo_check'], errors='ignore')

    if not odds_df.empty:
        match_df = match_df.merge(odds_df,
            left_on=['Home_Team_Name', 'Away_Team_Name', 'Date'],
            right_on=['HomeTeam', 'AwayTeam', 'Date'], how='left')
        valid = (match_df['eu_odds_home'] > 1) & (match_df['eu_odds_draw'] > 1) & (match_df['eu_odds_away'] > 1)
        match_df.loc[valid, 'eu_implied_home'] = 1 / match_df.loc[valid, 'eu_odds_home']
        match_df.loc[valid, 'eu_implied_draw'] = 1 / match_df.loc[valid, 'eu_odds_draw']
        match_df.loc[valid, 'eu_implied_away'] = 1 / match_df.loc[valid, 'eu_odds_away']
        s = (match_df['eu_implied_home'] + match_df['eu_implied_draw'] + match_df['eu_implied_away']).replace(0, np.nan)
        match_df['eu_implied_home'] /= s
        match_df['eu_implied_draw'] /= s
        match_df['eu_implied_away'] /= s
        match_df['odds_max_prob'] = match_df[['eu_implied_home', 'eu_implied_draw', 'eu_implied_away']].max(axis=1)
        match_df['odds_entropy'] = -(
            match_df['eu_implied_home'].fillna(1/3) * np.log(match_df['eu_implied_home'].fillna(1/3) + 1e-9) +
            match_df['eu_implied_draw'].fillna(1/3) * np.log(match_df['eu_implied_draw'].fillna(1/3) + 1e-9) +
            match_df['eu_implied_away'].fillna(1/3) * np.log(match_df['eu_implied_away'].fillna(1/3) + 1e-9)
        )
        valid_ah = (match_df['ah_home_odds'] > 1) & (match_df['ah_away_odds'] > 1)
        match_df['ah_implied_home'] = 0.5
        match_df.loc[valid_ah, 'ah_implied_home'] = (
            (1 / match_df.loc[valid_ah, 'ah_home_odds']) /
            (1 / match_df.loc[valid_ah, 'ah_home_odds'] + 1 / match_df.loc[valid_ah, 'ah_away_odds'])
        )
        match_df['ah_line_abs'] = match_df['ah_line'].abs().fillna(0)
        match_df['ah_line_direction'] = np.sign(match_df['ah_line'].fillna(0))

    match_df['elo_diff'] = match_df.get('home_pre_match_elo', 1500) - match_df.get('away_pre_match_elo', 1500)
    match_df['is_cup'] = match_df['league_id'].apply(
        lambda x: 1 if x in {42, 73, 10216, 132, 133, 134, 138, 141, 209} else 0)
    match_df['label_wdl'] = match_df.apply(
        lambda r: 0 if r['home_score'] > r['away_score'] else (1 if r['home_score'] == r['away_score'] else 2),
        axis=1).astype(int)

    match_df = match_df.sort_values('Date').reset_index(drop=True)
    return match_df


# ═══════════════════════════════════════
# Rolling 计算（Python 层）
# ═══════════════════════════════════════

def compute_rolling_for_window(flat: pd.DataFrame, raw_col: str, W) -> pd.Series:
    """
    为特定列和窗口计算 per-team 滚动均值。
    W: int 或 'season_to_date'
    返回与 flat 对齐的 Series（pre-match，使用 shift(1)）。
    """
    flat = flat.sort_values(['team_id', 'match_date', 'match_id'])
    result = pd.Series(np.nan, index=flat.index)

    for team_id, grp in flat.groupby('team_id'):
        col = grp[raw_col].astype(float)
        if W == 'season_to_date':
            # 按赛季分组展开历史（shift(1) 防泄漏）
            rolled = []
            for season, s_grp in grp.groupby('Season', sort=True):
                s_col = s_grp[raw_col].astype(float)
                r = s_col.shift(1).expanding(min_periods=1).mean()
                rolled.append(r)
            if rolled:
                r_all = pd.concat(rolled).reindex(grp.index)
                result.loc[grp.index] = r_all
        else:
            r = col.shift(1).rolling(W, min_periods=max(1, W // 2)).mean()
            result.loc[grp.index] = r

    return result


# ═══════════════════════════════════════
# CV 评估（复用 combo 里的函数）
# ═══════════════════════════════════════

def rps_score(y_true: np.ndarray, proba: np.ndarray) -> float:
    n_classes = proba.shape[1]
    cumprob = np.cumsum(proba, axis=1)
    cumact = np.zeros_like(cumprob)
    for i, label in enumerate(y_true):
        cumact[i, label:] = 1.0
    return float(np.mean(np.sum((cumprob - cumact) ** 2, axis=1)) / (n_classes - 1))


def season_group_cv_rps(X: np.ndarray, y: np.ndarray,
                        seasons: np.ndarray,
                        n_splits: int = 5) -> tuple[float, float]:
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


# ═══════════════════════════════════════
# Main
# ═══════════════════════════════════════

def evaluate_feature_windows(feat_name: str, raw_col: str,
                              flat: pd.DataFrame, match_df: pd.DataFrame,
                              base_cols: list[str]) -> dict:
    """
    对单个 rolling feature 扫描所有窗口，返回 scored windows 列表。
    """
    if raw_col not in flat.columns:
        logger.warning(f"Column '{raw_col}' not in flat data, skipping {feat_name}")
        return {'feature': feat_name, 'raw_col': raw_col, 'windows': [], 'best': None, 'second': None}

    results_w = []
    for W in WINDOW_GRID:
        w_label = str(W)
        rolled = compute_rolling_for_window(flat, raw_col, W)

        # 把 home/away 版本 pivot 到 match_df
        home_col = f"home_roll_{w_label}_{feat_name}"
        away_col = f"away_roll_{w_label}_{feat_name}"

        home_series = flat.set_index(['match_id', 'team_id'])[raw_col].rename(raw_col)
        rolled_indexed = rolled.copy()
        rolled_indexed.index = pd.MultiIndex.from_arrays(
            [flat['match_id'].values, flat['team_id'].values])
        rolled_indexed.name = 'val'

        # Join to match_df
        tmp = match_df.copy()
        home_vals = tmp.apply(
            lambda r: rolled_indexed.get((r['match_id'], r['home_id']), np.nan), axis=1)
        away_vals = tmp.apply(
            lambda r: rolled_indexed.get((r['match_id'], r['away_id']), np.nan), axis=1)

        tmp[home_col] = home_vals
        tmp[away_col] = away_vals
        diff_col = home_vals.fillna(0) - away_vals.fillna(0)

        # Build feature matrix: base_cols + new pair
        available_base = [c for c in base_cols if c in tmp.columns]
        X_base = tmp[available_base].fillna(0).astype(float).values
        X_aug = np.column_stack([X_base, diff_col.fillna(0).values])
        y = tmp['label_wdl'].values
        seasons = tmp['Season'].values

        if len(y) < 200:
            logger.warning(f"  {feat_name} W={W}: too few samples ({len(y)}), skip")
            continue

        mean_rps, std_rps = season_group_cv_rps(X_aug, y, seasons)
        results_w.append({'window': w_label, 'rps': mean_rps, 'std': std_rps})
        logger.info(f"  {feat_name} W={w_label:>15}: rps={mean_rps:.6f} std={std_rps:.4f}")

    if not results_w:
        return {'feature': feat_name, 'raw_col': raw_col, 'windows': [], 'best': None, 'second': None}

    # Sort by RPS (lower = better)
    results_w_sorted = sorted(results_w, key=lambda x: x['rps'])
    best = results_w_sorted[0]
    second = results_w_sorted[1] if len(results_w_sorted) > 1 else best

    # 若 top-2 在 1σ 内，取较小窗口
    if abs(best['rps'] - second['rps']) <= best['std']:
        best_w   = min(int(best['window'])   if best['window']   != 'season_to_date' else 9999,
                       int(second['window']) if second['window'] != 'season_to_date' else 9999)
        second_w = max(int(best['window'])   if best['window']   != 'season_to_date' else 9999,
                       int(second['window']) if second['window'] != 'season_to_date' else 9999)
        best_out   = str(best_w)   if best_w   != 9999 else 'season_to_date'
        second_out = str(second_w) if second_w != 9999 else 'season_to_date'
    else:
        best_out   = best['window']
        second_out = second['window']

    return {
        'feature':       feat_name,
        'raw_col':       raw_col,
        'windows':       results_w_sorted,
        'best':          best_out,
        'second':        second_out,
        'best_rps':      best['rps'],
        'w5_rps':        next((r['rps'] for r in results_w if r['window'] == '5'), None),
        'delta_vs_w5':   next((r['rps'] for r in results_w if r['window'] == '5'), best['rps']) - best['rps'],
    }


def main(only_feature: str = None):
    logger.info("=" * 60)
    logger.info("Phase A2: Optimal Window Scan")
    logger.info(f"DB: {DB_PATH}")
    logger.info(f"Window grid: {WINDOW_GRID}")
    logger.info(f"Started: {datetime.utcnow().isoformat()}")
    logger.info("=" * 60)

    flat = load_flat_data(str(DB_PATH), HOLDOUT_DAYS)
    match_df = load_match_labels_and_features(str(DB_PATH), HOLDOUT_DAYS)

    base_cols = [c for c in V4_FEATURES_BASE if c in match_df.columns]

    results = {}
    features_to_scan = ROLLING_FEATURES if not only_feature else {
        k: v for k, v in ROLLING_FEATURES.items() if only_feature in k
    }

    for feat_name, raw_col in features_to_scan.items():
        logger.info(f"\n--- Scanning feature: {feat_name} (raw_col={raw_col}) ---")
        result = evaluate_feature_windows(feat_name, raw_col, flat, match_df, base_cols)
        results[feat_name] = result
        logger.info(f"  → best window: {result.get('best')} | second: {result.get('second')} | Δ vs w5: {result.get('delta_vs_w5', 0):.6f}")

    # Sanity check: % of features where best window != 5
    best_windows = [r['best'] for r in results.values() if r.get('best')]
    non_5 = [w for w in best_windows if w != '5']
    pct_non_5 = len(non_5) / max(len(best_windows), 1) * 100
    logger.info(f"\nSanity check: {pct_non_5:.1f}% features chose window ≠ 5 ({len(non_5)}/{len(best_windows)})")

    # Write output
    with open(WINNERS_FILE, 'w') as f:
        json.dump({
            'generated_at': datetime.utcnow().isoformat(),
            'window_grid': [str(w) for w in WINDOW_GRID],
            'pct_non_5_window': round(pct_non_5, 1),
            'features': results,
        }, f, indent=2)

    logger.info(f"\nResults written to: {WINNERS_FILE}")
    logger.info(f"Full log: {LOG_FILE}")
    logger.info(f"Finished: {datetime.utcnow().isoformat()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--feature', type=str, default=None,
                        help='Scan only this feature (partial match on feature name)')
    args = parser.parse_args()
    main(only_feature=args.feature)
