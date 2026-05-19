#!/usr/bin/env python3
"""
build_ou_features_v5.py — OU 专属特征矩阵

数据流：
  mart_ou_dataset_v5          ← 标签 + 赔率（4986 行）
  mart_prediction_matrix_v5   ← 比赛元数据 + WDL 特征
  int_team_rolling_v5         ← per-team 滚动统计（self-join 取 home/away）
  dim_match                   ← H2H / 联赛 / 裁判基础数据

特征组：
  A. xG 总量         B. 进球转化偏差     C. 节奏
  D. 防守强度         E. H2H + 联赛      F. 盘口偏离
  G. Poisson 衍生

输出：mart_ou_features_v5
CLAUDE.md §3：唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations
import os, sqlite3, warnings
import numpy as np
import pandas as pd
from scipy.stats import poisson as sp_poisson
warnings.filterwarnings('ignore')

DB_PATH = '/home/ubuntu/app/backend/football_uk.db'

# rolling 中需要拉取的列（is_home=1 为 home，is_home=0 为 away，后缀 _H / _A 区分）
ROLL_COLS = [
    'match_id', 'team_id', 'is_home',
    # 进攻
    'roll_5_all_expected_goals',
    'roll_5_all_expected_goals_non_penalty',
    'roll_5_all_Goals',
    'roll_5_all_total_shots',
    'roll_5_all_shots_inside_box',
    'roll_5_all_ShotsOnTarget',
    'roll_5_all_big_chance',
    # 中场/节奏
    'roll_5_all_BallPossesion',
    'roll_5_all_pass_accuracy',
    'roll_5_all_touches_opp_box',
    # 防守
    'roll_5_all_keeper_saves',
    'roll_5_all_save_ratio',
    'roll_5_all_shot_blocks',
    'roll_5_all_clearances',
    'roll_5_all_interceptions',
    # venue-specific
    'roll_5_home_expected_goals',    # home team 主场近5场 xG
    'roll_5_away_expected_goals',    # away team 客场近5场 xG
    'roll_5_home_Goals',
    'roll_5_away_Goals',
    'roll_5_home_save_ratio',
    'roll_5_away_save_ratio',
]


# ─────────────────────────────────────────────────────────────────────
# Poisson P(total >= 3) ≈ P(over 2.5)
# ─────────────────────────────────────────────────────────────────────

def poisson_p_over_25(lam: float) -> float:
    if np.isnan(lam) or lam <= 0:
        return float('nan')
    return float(1.0 - sp_poisson.cdf(2, lam))


# ─────────────────────────────────────────────────────────────────────
# H2H 特征（无数据泄漏：只用本场日期前的历史对阵）
# ─────────────────────────────────────────────────────────────────────

def build_h2h(all_matches: pd.DataFrame) -> pd.DataFrame:
    """
    all_matches：含 match_id, match_date, Home_Team_ID, Away_Team_ID,
                    home_score, away_score
    返回：match_id → h2h_avg_goals_5, h2h_over25_rate_5
    """
    df = all_matches.copy()
    df['match_date'] = pd.to_datetime(df['match_date'], format='mixed')
    df['total']      = df['home_score'] + df['away_score']
    df['over25']     = (df['total'] > 2.5).astype(float)

    # 标准化 pair key（无向）
    df['pair'] = df.apply(
        lambda r: tuple(sorted([int(r['Home_Team_ID']), int(r['Away_Team_ID'])])),
        axis=1)
    df = df.sort_values('match_date').reset_index(drop=True)

    h2h_goals = []
    h2h_over  = []

    for _, row in df.iterrows():
        pair_matches = df[
            (df['pair'] == row['pair']) &
            (df['match_date'] < row['match_date'])
        ].tail(5)
        if len(pair_matches) == 0:
            h2h_goals.append(float('nan'))
            h2h_over.append(float('nan'))
        else:
            h2h_goals.append(float(pair_matches['total'].mean()))
            h2h_over.append(float(pair_matches['over25'].mean()))

    df['h2h_avg_total_goals_5'] = h2h_goals
    df['h2h_over_2_5_rate_5']   = h2h_over
    return df[['match_id', 'h2h_avg_total_goals_5', 'h2h_over_2_5_rate_5']]


# ─────────────────────────────────────────────────────────────────────
# 联赛赛季平均（全季均值；不做 lookahead 过滤，因为 train/test 赛季不同）
# ─────────────────────────────────────────────────────────────────────

def build_league_avgs(all_matches: pd.DataFrame) -> pd.DataFrame:
    """→ match_id → league_avg_goals_season, league_over_2_5_rate_season"""
    df = all_matches.copy()
    df['total'] = df['home_score'] + df['away_score']
    df['over25'] = (df['total'] > 2.5).astype(float)
    grp = df.groupby(['League_ID', 'Season']).agg(
        league_avg_goals_season=('total', 'mean'),
        league_over_2_5_rate_season=('over25', 'mean'),
    ).reset_index()
    return df[['match_id', 'League_ID', 'Season']].merge(grp, on=['League_ID', 'Season'])


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    conn = sqlite3.connect(DB_PATH)

    # ── 1) 读取核心表 ─────────────────────────────────────────────────
    print('📂 读取源表...')

    ou = pd.read_sql_query('SELECT * FROM mart_ou_dataset_v5', conn)
    print(f'   mart_ou_dataset_v5          : {len(ou)} 行')

    pm = pd.read_sql_query('''
        SELECT match_id, match_date, Season, League_ID,
               Home_Team_ID, Away_Team_ID,
               Home_Team_Name, Away_Team_Name,
               home_score, away_score
        FROM mart_prediction_matrix_v5
    ''', conn)
    print(f'   mart_prediction_matrix_v5   : {len(pm)} 行')

    roll_raw = pd.read_sql_query(
        f'SELECT {", ".join(ROLL_COLS)} FROM int_team_rolling_v5', conn)
    print(f'   int_team_rolling_v5         : {len(roll_raw)} 行')

    dm = pd.read_sql_query('''
        SELECT Match_ID as match_id, League_ID, Season,
               Home_Team_ID, Away_Team_ID,
               Referee, home_score, away_score
        FROM dim_match
        WHERE home_score IS NOT NULL AND away_score IS NOT NULL
    ''', conn)
    print(f'   dim_match (finished)        : {len(dm)} 行')

    conn.close()

    # ── 2) 基础 JOIN：ou ← pm ─────────────────────────────────────────
    ou['match_id'] = ou['match_id'].astype(str)
    pm['match_id'] = pm['match_id'].astype(str)
    base = ou.merge(pm, on='match_id', how='inner', suffixes=('', '_pm'))
    # Season 以 ou 表为准（相同，_pm 副本丢掉）
    base = base[[c for c in base.columns if not c.endswith('_pm')]]
    print(f'\n   ou ⟕ pm                     : {len(base)} 行')

    # ── 3) rolling self-join → 每场 home 行 + away 行 ─────────────────
    print('📐 构建 rolling 特征矩阵...')
    roll_raw['match_id'] = roll_raw['match_id'].astype(str)

    home_r = roll_raw[roll_raw['is_home'] == 1].copy()
    away_r = roll_raw[roll_raw['is_home'] == 0].copy()

    # rename 列（保留 match_id，其余加 _H / _A）
    def suffix_cols(df, sfx, skip=('match_id', 'is_home')):
        return df.rename(columns={c: c + sfx for c in df.columns if c not in skip})

    home_r = suffix_cols(home_r.drop(columns='is_home'), '_H')
    away_r = suffix_cols(away_r.drop(columns='is_home'), '_A')

    roll = home_r.merge(away_r, on='match_id', how='inner')
    print(f'   rolling home✕away           : {len(roll)} 行')

    base = base.merge(roll, on='match_id', how='left')
    print(f'   base ⟕ rolling              : {len(base)} 行')

    # ── 4) 计算 xG 特征 ───────────────────────────────────────────────
    print('🔧 计算特征...')

    # A. xG 总量
    # home_xG5 = home team's offensive xG;  away_xG5 = away team's offensive xG
    # xGA proxy: home_xGA5 ≈ away team's xG (threat on home team's defense)
    base['home_xG5']         = base['roll_5_all_expected_goals_H']
    base['away_xG5']         = base['roll_5_all_expected_goals_A']
    base['home_xGA5']        = base['away_xG5']   # symmetric proxy
    base['away_xGA5']        = base['home_xG5']   # symmetric proxy

    # venue-specific
    base['home_xG_venue5']   = base['roll_5_home_expected_goals_H']  # home team in home games
    base['away_xG_venue5']   = base['roll_5_away_expected_goals_A']  # away team in away games
    base['home_xGA_venue5']  = base['away_xG_venue5']
    base['away_xGA_venue5']  = base['home_xG_venue5']

    # expected total
    base['expected_total_xG']       = base['home_xG5'] + base['away_xG5']
    base['expected_total_xG_venue'] = (
        base['home_xG_venue5'].fillna(base['home_xG5']) +
        base['away_xG_venue5'].fillna(base['away_xG5'])
    )

    # B. 进球转化偏差
    _eps = 0.01
    base['home_goals5']         = base['roll_5_all_Goals_H']
    base['away_goals5']         = base['roll_5_all_Goals_A']
    base['home_goals_vs_xG5']   = (
        (base['home_goals5'] - base['home_xG5']) /
        (base['home_xG5'] + _eps)
    )
    base['away_goals_vs_xG5']   = (
        (base['away_goals5'] - base['away_xG5']) /
        (base['away_xG5'] + _eps)
    )
    # GA_vs_xGA (goalkeeper over-performance)：(xGA - actual_GA) / xGA
    # actual_GA = away_goals5 (goals the home team conceded = goals by away team)
    base['home_GA_vs_xGA5']     = (
        (base['home_xGA5'] - base['away_goals5']) /
        (base['home_xGA5'] + _eps)
    )
    base['away_GA_vs_xGA5']     = (
        (base['away_xGA5'] - base['home_goals5']) /
        (base['away_xGA5'] + _eps)
    )

    # C. 节奏
    base['home_pace5']          = (
        base['roll_5_all_BallPossesion_H'] *
        base['roll_5_all_pass_accuracy_H'] / 100.0
    )
    base['away_pace5']          = (
        base['roll_5_all_BallPossesion_A'] *
        base['roll_5_all_pass_accuracy_A'] / 100.0
    )
    base['combined_pace']       = (base['home_pace5'] + base['away_pace5']) / 2.0
    base['combined_shots5']     = (
        base['roll_5_all_total_shots_H'] + base['roll_5_all_total_shots_A'])
    base['combined_box_shots5'] = (
        base['roll_5_all_shots_inside_box_H'] + base['roll_5_all_shots_inside_box_A'])

    # D. 防守强度
    base['home_save_ratio5']      = base['roll_5_all_save_ratio_H']
    base['away_save_ratio5']      = base['roll_5_all_save_ratio_A']
    base['defensive_match_score'] = (
        base['home_save_ratio5'] + base['away_save_ratio5']) / 2.0
    base['combined_blocks5']      = (
        base['roll_5_all_shot_blocks_H'] + base['roll_5_all_shot_blocks_A'])
    base['combined_clearances5']  = (
        base['roll_5_all_clearances_H'] + base['roll_5_all_clearances_A'])

    # ── 5) H2H 特征 ───────────────────────────────────────────────────
    print('🔧 计算 H2H 特征（逐行，需数秒）...')
    dm['match_id']      = dm['match_id'].astype(str)
    dm['home_score']    = pd.to_numeric(dm['home_score'], errors='coerce')
    dm['away_score']    = pd.to_numeric(dm['away_score'], errors='coerce')
    dm['Home_Team_ID']  = pd.to_numeric(dm['Home_Team_ID'], errors='coerce')
    dm['Away_Team_ID']  = pd.to_numeric(dm['Away_Team_ID'], errors='coerce')
    dm_clean = dm.dropna(subset=['home_score', 'away_score',
                                  'Home_Team_ID', 'Away_Team_ID'])
    pm_date = pm[['match_id', 'match_date']].copy()
    dm_h2h = dm_clean.merge(pm_date, on='match_id', how='left')
    dm_h2h = dm_h2h.dropna(subset=['match_date'])

    h2h_df = build_h2h(dm_h2h)
    base = base.merge(h2h_df, on='match_id', how='left')
    print(f'   H2H 命中率: {base["h2h_avg_total_goals_5"].notna().mean()*100:.1f}%')

    # ── 6) 联赛赛季特征 ───────────────────────────────────────────────
    print('🔧 计算联赛赛季特征...')
    # dim_match 已含 Season，直接用；不需要再 merge pm
    dm_league = dm_clean.dropna(subset=['Season']).copy()
    lg_df = build_league_avgs(dm_league)
    lg_df['match_id'] = lg_df['match_id'].astype(str)
    base = base.merge(
        lg_df[['match_id', 'league_avg_goals_season', 'league_over_2_5_rate_season']],
        on='match_id', how='left')

    # ── 7) 裁判特征 ───────────────────────────────────────────────────
    # 14% 覆盖率，做好 NULL 标记
    dm_ref = dm.copy()
    dm_ref['Referee'] = dm_ref['Referee'].replace('', float('nan'))
    dm_ref = dm_ref.dropna(subset=['Referee'])
    dm_ref['home_score'] = pd.to_numeric(dm_ref['home_score'], errors='coerce')
    dm_ref['away_score'] = pd.to_numeric(dm_ref['away_score'], errors='coerce')
    dm_ref = dm_ref.dropna(subset=['home_score', 'away_score'])
    dm_ref['total'] = dm_ref['home_score'] + dm_ref['away_score']
    ref_avg = dm_ref.groupby('Referee')['total'].mean().reset_index()
    ref_avg.columns = ['Referee', 'referee_avg_goals']
    base = base.merge(
        dm[['match_id', 'Referee']].rename(columns={'match_id': 'match_id'}),
        on='match_id', how='left')
    base['Referee'] = base['Referee'].replace('', float('nan'))
    base = base.merge(ref_avg, on='Referee', how='left')
    base['referee_avg_goals'] = base['referee_avg_goals'].where(
        base['Referee'].notna(), other=float('nan'))

    # ── 8) 盘口偏离特征 ───────────────────────────────────────────────
    base['expected_xG_vs_line']      = base['expected_total_xG'] - base['ou_line_opening']
    base['expected_xG_vs_baseline']  = base['expected_total_xG'] - 2.5
    base['form_total_goals5']        = base['home_goals5'] + base['away_goals5']
    base['form_total_goals_vs_line'] = base['form_total_goals5'] - base['ou_line_opening']

    # ── 9) Poisson 衍生 ───────────────────────────────────────────────
    base['poisson_p_over_2_5_naive'] = base['expected_total_xG'].apply(
        poisson_p_over_25)
    base['poisson_p_venue_over_2_5'] = base['expected_total_xG_venue'].apply(
        poisson_p_over_25)

    # ── 10) 整理最终列 ────────────────────────────────────────────────
    # 去掉 roll 原始中间列（保留计算后的特征）
    drop_intermediates = [c for c in base.columns if (
        c.endswith('_H') or c.endswith('_A'))]
    base = base.drop(columns=drop_intermediates)
    # 去掉重复的 team_id 列（如果有）
    for dup in ('team_id_H', 'team_id_A'):
        if dup in base.columns:
            base = base.drop(columns=[dup])
    # 去掉 Referee（只保留 referee_avg_goals）
    if 'Referee' in base.columns:
        base = base.drop(columns=['Referee'])

    print(f'\n📐 输出: {len(base)} 行 × {len(base.columns)} 列')

    # ── 11) 写入数据库 ────────────────────────────────────────────────
    conn2 = sqlite3.connect(DB_PATH)
    conn2.execute('DROP TABLE IF EXISTS mart_ou_features_v5')
    base.to_sql('mart_ou_features_v5', conn2, if_exists='replace', index=False)
    conn2.commit()
    conn2.close()
    print('✔ mart_ou_features_v5 写入完成')

    # ── 12) NULL 率报告 ───────────────────────────────────────────────
    print('\n' + '='*65)
    print('  NULL 率报告（关键特征）')
    print('='*65)

    key_features = [
        # xG
        'home_xG5', 'away_xG5',
        'home_xG_venue5', 'away_xG_venue5',
        'expected_total_xG', 'expected_total_xG_venue',
        # 转化偏差
        'home_goals_vs_xG5', 'away_goals_vs_xG5',
        'home_GA_vs_xGA5',
        # 节奏
        'combined_pace', 'combined_shots5',
        # 防守
        'defensive_match_score', 'combined_clearances5',
        # H2H / 联赛
        'h2h_avg_total_goals_5', 'h2h_over_2_5_rate_5',
        'league_avg_goals_season', 'league_over_2_5_rate_season',
        'referee_avg_goals',
        # 盘口偏离
        'expected_xG_vs_line', 'expected_xG_vs_baseline',
        'form_total_goals5', 'form_total_goals_vs_line',
        'ou_line_opening', 'ou_line_vs_baseline',
        # Poisson
        'poisson_p_over_2_5_naive',
        # 标签
        'baseline_label', 'actual_label_value',
    ]

    n = len(base)
    print(f'\n  {"特征":<40} {"NULL率":>8}  {"非NULL":>8}')
    print('  ' + '-'*60)
    for feat in key_features:
        if feat not in base.columns:
            print(f'  {feat:<40} {"❌ 不存在":>8}')
            continue
        null_n  = int(base[feat].isna().sum())
        null_r  = null_n / n * 100
        flag    = ' ⚠️' if null_r > 10 else ('  ✅' if null_r < 5 else '')
        print(f'  {feat:<40} {null_r:>7.1f}%  {n-null_n:>8}{flag}')

    # 输出列清单
    print(f'\n  全部列（{len(base.columns)} 个）:')
    for i, c in enumerate(base.columns, 1):
        print(f'    {i:>3}. {c}')


if __name__ == '__main__':
    main()
