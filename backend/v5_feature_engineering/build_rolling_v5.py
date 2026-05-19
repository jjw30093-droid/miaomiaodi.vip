#!/usr/bin/env python3
"""
build_rolling_v5.py — 从 int_team_match_composite_v5 计算多窗口滚动 + Trend + Opp-Adjusted

内存策略：按 team_id 分批 rolling（不做全表 pivot），最后 concat。

每队 / 每场（按 match_date 升序）：
  1) 'all' rolling：shift(1).rolling(window, min_periods).mean()       窗口 3,5,10,15
  2) 'home_only'  ：仅过滤 is_home=1 的子集 rolling，再 merge_asof 回主表  窗口 3,5,10
  3) 'away_only'  ：同 home_only 镜像                                       窗口 3,5,10

最小观测数：roll_3≥2  roll_5≥3  roll_10≥5  roll_15≥8

Trend：在每行上算（rolling 完成后）
  trend_short_{m}  = roll_3_all_{m}  - roll_10_all_{m}
  trend_medium_{m} = roll_5_all_{m}  - roll_15_all_{m}
  trend_venue_{m}  = roll_5_home_{m} - roll_5_away_{m}
仅 8 个指标：expected_goals_non_penalty, xg_conversion, shot_accuracy,
            territorial_dominance, box_shot_ratio, save_ratio, pass_accuracy, attack_quality

Opp-Adjusted（最后）：找到对手的 roll_10_all 列，做：
  opp_adj_{m} = team_roll_5_all_{m} / opp_roll_10_all_{m}    （除零→NULL）
仅 5 个指标：expected_goals_non_penalty, shot_accuracy, box_shot_ratio,
            territorial_dominance, save_ratio

CLAUDE.md §3：唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations

import argparse
import sqlite3
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore', category=FutureWarning)

DB_PATH      = '/home/ubuntu/app/backend/football_uk.db'
SOURCE_TABLE = 'int_team_match_composite_v5'
OUTPUT_TABLE = 'int_team_rolling_v5'

# ── 待 rolling 的字段 ─────────────────────────────────────────────
RAW_METRICS = [
    'expected_goals', 'expected_goals_non_penalty', 'expected_goals_open_play',
    'Goals', 'total_shots', 'ShotsOnTarget', 'shots_inside_box', 'big_chance',
    'touches_opp_box', 'BallPossesion', 'accurate_passes', 'opposition_half_passes',
    'interceptions', 'shot_blocks', 'clearances', 'keeper_saves', 'duel_won',
    'aerials_won', 'corners',
]  # 19

RATIO_METRICS = [
    'shot_accuracy', 'box_shot_ratio', 'npxg_per_shot', 'xg_conversion',
    'big_chance_rate', 'xgot_ratio', 'open_play_xg_share', 'set_play_xg_share',
    'territorial_dominance', 'pass_accuracy', 'box_touches_per_poss',
    'block_rate', 'save_ratio', 'attack_quality',
]  # 14

ROLLING_METRICS = RAW_METRICS + RATIO_METRICS  # 33

# 窗口规格：(window, min_periods)
WIN_ALL  = [(3, 2), (5, 3), (10, 5), (15, 8)]
WIN_SPLIT = [(3, 2), (5, 3), (10, 5)]   # home / away（数据量小）

TREND_METRICS = [
    'expected_goals_non_penalty', 'xg_conversion', 'shot_accuracy',
    'territorial_dominance', 'box_shot_ratio', 'save_ratio',
    'pass_accuracy', 'attack_quality',
]  # 8

OPP_ADJ_METRICS = [
    'expected_goals_non_penalty', 'shot_accuracy', 'box_shot_ratio',
    'territorial_dominance', 'save_ratio',
]  # 5


# ── 单队 rolling 计算 ────────────────────────────────────────────
def _rolling_for_team(team_df: pd.DataFrame) -> pd.DataFrame:
    """对单个 team 的所有比赛做 rolling。team_df 已按 match_date 升序。"""
    team_df = team_df.sort_values('match_date').reset_index(drop=True)
    # merge_asof 要求 key 是数值或 datetime，先把 match_date 转 datetime（保留原 TEXT 列回填）
    team_df['_md_dt'] = pd.to_datetime(team_df['match_date'], errors='coerce')

    # ── 1) 'all' rolling ─────────────────────────────────────────
    for col in ROLLING_METRICS:
        shifted = team_df[col].shift(1)
        for w, min_p in WIN_ALL:
            team_df[f'roll_{w}_all_{col}'] = shifted.rolling(w, min_periods=min_p).mean()

    # ── 2) home_only rolling 子集计算 ────────────────────────────
    home_subset = team_df[team_df['is_home'] == 1][['_md_dt'] + ROLLING_METRICS].copy()
    home_cols_added: list[str] = []
    if len(home_subset) >= 2:  # 需要至少 2 场才能算最小 roll_3
        home_subset = home_subset.sort_values('_md_dt').reset_index(drop=True)
        for col in ROLLING_METRICS:
            shifted = home_subset[col].shift(1)
            for w, min_p in WIN_SPLIT:
                new_col = f'roll_{w}_home_{col}'
                home_subset[new_col] = shifted.rolling(w, min_periods=min_p).mean()
                home_cols_added.append(new_col)

        # merge_asof 回主表：方向 backward，对 home 行能命中自己，对 away 行命中最近的主场
        home_to_merge = home_subset[['_md_dt'] + home_cols_added].sort_values('_md_dt')
        team_df = pd.merge_asof(
            team_df.sort_values('_md_dt'),
            home_to_merge,
            on='_md_dt',
            direction='backward',
        )

    # 即使 home_subset 为空，也要补全列（方便后续 concat 整齐）
    for col in ROLLING_METRICS:
        for w, _ in WIN_SPLIT:
            c = f'roll_{w}_home_{col}'
            if c not in team_df.columns:
                team_df[c] = np.nan

    # ── 3) away_only rolling（镜像） ─────────────────────────────
    away_subset = team_df[team_df['is_home'] == 0][['_md_dt'] + ROLLING_METRICS].copy()
    away_cols_added: list[str] = []
    if len(away_subset) >= 2:
        away_subset = away_subset.sort_values('_md_dt').reset_index(drop=True)
        for col in ROLLING_METRICS:
            shifted = away_subset[col].shift(1)
            for w, min_p in WIN_SPLIT:
                new_col = f'roll_{w}_away_{col}'
                away_subset[new_col] = shifted.rolling(w, min_periods=min_p).mean()
                away_cols_added.append(new_col)

        away_to_merge = away_subset[['_md_dt'] + away_cols_added].sort_values('_md_dt')
        team_df = pd.merge_asof(
            team_df.sort_values('_md_dt'),
            away_to_merge,
            on='_md_dt',
            direction='backward',
        )

    for col in ROLLING_METRICS:
        for w, _ in WIN_SPLIT:
            c = f'roll_{w}_away_{col}'
            if c not in team_df.columns:
                team_df[c] = np.nan

    team_df = team_df.drop(columns=['_md_dt'])
    return team_df


# ── 主流程 ──────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',      default=DB_PATH)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    print(f'📂 DB: {args.db}')
    conn = sqlite3.connect(args.db)

    needed_cols = ['match_id', 'team_id', 'opponent_id', 'match_date', 'is_home'] + ROLLING_METRICS
    cols_csv = ','.join(f'"{c}"' for c in needed_cols)
    df = pd.read_sql_query(f'SELECT {cols_csv} FROM {SOURCE_TABLE}', conn)
    print(f'📊 加载 {len(df)} 行（{df["team_id"].nunique()} 支球队）')

    # ── 按 team_id 分批 rolling（内存高效） ──────────────────────
    print('🔄 按 team_id 分批 rolling...')
    parts: list[pd.DataFrame] = []
    teams = df['team_id'].unique()
    for i, tid in enumerate(teams, 1):
        team_df = df[df['team_id'] == tid].copy()
        team_df = _rolling_for_team(team_df)
        parts.append(team_df)
        if i % 100 == 0 or i == len(teams):
            print(f'  · {i}/{len(teams)} teams')

    out = pd.concat(parts, ignore_index=True)
    print(f'✅ rolling 计算完成：{len(out)} 行 × {len(out.columns)} 列')

    # ── Trend 特征 ──────────────────────────────────────────────
    print('🪄 Trend 特征...')
    for m in TREND_METRICS:
        # short = roll_3_all - roll_10_all
        out[f'trend_short_{m}']  = out[f'roll_3_all_{m}']  - out[f'roll_10_all_{m}']
        # medium = roll_5_all - roll_15_all
        out[f'trend_medium_{m}'] = out[f'roll_5_all_{m}']  - out[f'roll_15_all_{m}']
        # venue = roll_5_home - roll_5_away
        out[f'trend_venue_{m}']  = out[f'roll_5_home_{m}'] - out[f'roll_5_away_{m}']

    # ── Opp-Adjusted ────────────────────────────────────────────
    print('🆚 Opp-Adjusted...')
    opp_cols = [f'roll_10_all_{m}' for m in OPP_ADJ_METRICS]
    opp_view = out[['match_id', 'team_id'] + opp_cols].copy()
    opp_view = opp_view.rename(columns={
        'team_id': '_opp_team_id',
        **{c: f'_opp_{c}' for c in opp_cols},
    })

    out = out.merge(
        opp_view,
        left_on=['match_id', 'opponent_id'],
        right_on=['match_id', '_opp_team_id'],
        how='left',
    )

    for m in OPP_ADJ_METRICS:
        team_col = f'roll_5_all_{m}'
        opp_col  = f'_opp_roll_10_all_{m}'
        denom = pd.to_numeric(out[opp_col], errors='coerce')
        num   = pd.to_numeric(out[team_col], errors='coerce')
        out[f'opp_adj_{m}'] = num.where(denom > 0) / denom.where(denom > 0)

    out = out.drop(columns=[c for c in out.columns if c.startswith('_opp_')])

    # 也不需要再保留原始 metric 列（rolling 已经独立成列）
    out = out.drop(columns=ROLLING_METRICS)

    n_total = len(out)
    n_cols  = len(out.columns)
    print(f'\n📐 总行数: {n_total}   总列数: {n_cols}')

    # ── NULL 率 ────────────────────────────────────────────────
    roll_5_all_cols = [c for c in out.columns if c.startswith('roll_5_all_')]
    roll_3_home_cols = [c for c in out.columns if c.startswith('roll_3_home_')]

    def avg_cov(cols: list[str]) -> float:
        if not cols: return 0.0
        return float(np.mean([1 - out[c].isna().mean() for c in cols]))

    cov_r5_all  = avg_cov(roll_5_all_cols)
    cov_r3_home = avg_cov(roll_3_home_cols)
    flag_5  = '✓' if cov_r5_all  > 0.85 else '⚠'
    flag_3h = '✓' if cov_r3_home > 0.55 else '⚠'
    print(f'\n📊 平均覆盖率：')
    print(f'  {flag_5} roll_5_all_*  ({len(roll_5_all_cols)} 列):  {cov_r5_all:.1%}  (target > 85%)')
    print(f'  {flag_3h} roll_3_home_* ({len(roll_3_home_cols)} 列): {cov_r3_home:.1%}  (target > 55%)')

    # ── 写表 ────────────────────────────────────────────────────
    if args.dry_run:
        print('\n[dry-run] 不写表')
        conn.close()
        return

    print(f'\n💾 写入 {OUTPUT_TABLE} ...')
    cur = conn.cursor()
    cur.execute(f'DROP TABLE IF EXISTS {OUTPUT_TABLE}')

    # DDL：id 列 INTEGER/TEXT，其余 REAL
    id_int_cols = {'match_id', 'team_id', 'opponent_id', 'is_home'}
    ddl_parts = []
    for c in out.columns:
        if c in id_int_cols:
            ddl_parts.append(f'"{c}" INTEGER')
        elif c == 'match_date':
            ddl_parts.append(f'"{c}" TEXT')
        else:
            ddl_parts.append(f'"{c}" REAL')
    ddl = f'CREATE TABLE {OUTPUT_TABLE} ({", ".join(ddl_parts)}, PRIMARY KEY (match_id, team_id))'
    cur.execute(ddl)

    # 写入：NaN → None，整数列强制 cast，再用 generator 喂 executemany
    out_w = out.copy()
    for c in id_int_cols:
        out_w[c] = out_w[c].astype('Int64')
    out_w = out_w.replace({np.nan: None})

    def _row_to_py(row):
        py = []
        for v in row:
            if v is None or (isinstance(v, float) and np.isnan(v)):
                py.append(None)
            elif hasattr(v, 'item'):
                py.append(v.item())
            else:
                py.append(v)
        return tuple(py)

    cols_str = ','.join([f'"{c}"' for c in out.columns])
    placeholders = ','.join(['?'] * len(out.columns))
    cur.executemany(
        f'INSERT INTO {OUTPUT_TABLE} ({cols_str}) VALUES ({placeholders})',
        (_row_to_py(r) for r in out_w.itertuples(index=False, name=None)),
    )
    cur.execute(f'CREATE INDEX idx_rollv5_team_date ON {OUTPUT_TABLE}(team_id, match_date)')
    cur.execute(f'CREATE INDEX idx_rollv5_match ON {OUTPUT_TABLE}(match_id)')
    conn.commit()

    n = cur.execute(f'SELECT COUNT(*) FROM {OUTPUT_TABLE}').fetchone()[0]
    print(f'✅ {OUTPUT_TABLE}: {n} 行 × {n_cols} 列')

    # ── 样本（关键列） ──────────────────────────────────────────
    print('\n🔍 样本（前 3 行，关键列）:')
    sample_cols = ['match_id', 'team_id', 'is_home',
                   'roll_5_all_expected_goals_non_penalty',
                   'roll_5_home_expected_goals_non_penalty',
                   'roll_5_away_expected_goals_non_penalty',
                   'trend_short_xg_conversion',
                   'trend_venue_pass_accuracy',
                   'opp_adj_shot_accuracy']
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 220)
    print(out[sample_cols].head(3).to_string(index=False, float_format='{:,.4f}'.format))

    conn.close()


if __name__ == '__main__':
    main()
