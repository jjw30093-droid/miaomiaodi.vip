#!/usr/bin/env python3
"""
build_mart_v5.py — 构造 mart_prediction_matrix_v5（Batch 4，被原计划跳过，这里补上）

Join：
  dim_match (label/Season/League/scores)
+ int_team_rolling_v5 (主队 home_*, 客队 away_*)
+ int_team_pi_ratings  lag-1（每队上一场后的评级 = 当场比赛前的评级）
+ silver_match_odds   (closing 期赔率)

输出表：mart_prediction_matrix_v5  PK=match_id
"""
from __future__ import annotations

import argparse
import sqlite3

import numpy as np
import pandas as pd

DB_PATH = '/home/ubuntu/app/backend/football_uk.db'
OUT     = 'mart_prediction_matrix_v5'

ID_DROP = {'match_id', 'team_id', 'opponent_id', 'match_date', 'is_home'}


def _row_to_py(row):
    out = []
    for v in row:
        if v is None:
            out.append(None)
        elif isinstance(v, float) and np.isnan(v):
            out.append(None)
        elif hasattr(v, 'item'):
            out.append(v.item())
        else:
            out.append(v)
    return tuple(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',      default=DB_PATH)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)

    # ── 1) dim_match：所有已完赛 ─────────────────────────────────
    dm = pd.read_sql_query("""
        SELECT Match_ID AS match_id, Date AS match_date, Season, League_ID,
               Home_Team_ID, Away_Team_ID, Home_Team_Name, Away_Team_Name,
               home_score, away_score
        FROM dim_match
        WHERE home_score IS NOT NULL AND away_score IS NOT NULL
          AND Home_Team_ID IS NOT NULL AND Away_Team_ID IS NOT NULL
        ORDER BY Date ASC, Match_ID ASC
    """, conn)
    print(f'📊 dim_match 完赛: {len(dm)}')

    # ── 2) Rolling 表 ──────────────────────────────────────────
    roll = pd.read_sql_query('SELECT * FROM int_team_rolling_v5', conn)
    feat_cols_roll = [c for c in roll.columns if c not in ID_DROP]
    print(f'📊 rolling: {len(roll)} 行, {len(feat_cols_roll)} 特征列')

    # 主队视角：roll where (match_id, team_id)=(match_id, Home_Team_ID)
    # 拼前缀 home_/away_，避免列名冲突
    roll_home = roll.rename(columns={c: f'home_{c}' for c in feat_cols_roll})
    roll_home = roll_home.rename(columns={'team_id': 'Home_Team_ID'})
    roll_away = roll.rename(columns={c: f'away_{c}' for c in feat_cols_roll})
    roll_away = roll_away.rename(columns={'team_id': 'Away_Team_ID'})

    # 只保留 join key + 重命名后的特征列
    roll_home = roll_home[['match_id', 'Home_Team_ID'] + [f'home_{c}' for c in feat_cols_roll]]
    roll_away = roll_away[['match_id', 'Away_Team_ID'] + [f'away_{c}' for c in feat_cols_roll]]

    # ── 3) Pi-ratings lag-1（每队上一场比赛后 = 当场比赛前）───────
    pi = pd.read_sql_query("""
        SELECT match_id, team_id, match_date, pi_home_for, pi_home_against,
               pi_away_for, pi_away_against
        FROM int_team_pi_ratings
        ORDER BY team_id, match_date, match_id
    """, conn)
    pi['match_date'] = pd.to_datetime(pi['match_date'], errors='coerce')
    # 按 team 分组 shift(1) 得"上一场后的评级" → 即"本场比赛前的评级"
    pi_lag = pi.copy()
    for col in ('pi_home_for', 'pi_home_against', 'pi_away_for', 'pi_away_against'):
        pi_lag[col] = pi_lag.groupby('team_id')[col].shift(1)
    print(f'📊 pi lag-1 行: {len(pi_lag)}')

    pi_home = pi_lag.rename(columns={
        'team_id':         'Home_Team_ID',
        'pi_home_for':     'home_pi_home_for',
        'pi_home_against': 'home_pi_home_against',
        'pi_away_for':     'home_pi_away_for',
        'pi_away_against': 'home_pi_away_against',
    })[['match_id', 'Home_Team_ID',
        'home_pi_home_for', 'home_pi_home_against',
        'home_pi_away_for', 'home_pi_away_against']]

    pi_away = pi_lag.rename(columns={
        'team_id':         'Away_Team_ID',
        'pi_home_for':     'away_pi_home_for',
        'pi_home_against': 'away_pi_home_against',
        'pi_away_for':     'away_pi_away_for',
        'pi_away_against': 'away_pi_away_against',
    })[['match_id', 'Away_Team_ID',
        'away_pi_home_for', 'away_pi_home_against',
        'away_pi_away_for', 'away_pi_away_against']]

    # ── 4) Closing odds（silver_match_odds 按 market pivot） ────
    raw_odds = pd.read_sql_query("""
        SELECT match_id, market, raw_home, raw_draw, raw_away, raw_line,
               fair_home, fair_draw, fair_away
        FROM silver_match_odds
        WHERE period = 'closing'
    """, conn)
    # pivot：每 (match_id) 一行，三个 market 摊平到列
    odds_pivots = []
    for mkt, prefix in [('1x2', 'closing_eu'), ('ah', 'closing_ah'), ('ou', 'closing_ou')]:
        sub = raw_odds[raw_odds['market'] == mkt].drop(columns=['market']).copy()
        sub = sub.rename(columns={
            'raw_home':  f'{prefix}_raw_home',
            'raw_draw':  f'{prefix}_raw_draw',
            'raw_away':  f'{prefix}_raw_away',
            'raw_line':  f'{prefix}_line',
            'fair_home': f'{prefix}_fair_home',
            'fair_draw': f'{prefix}_fair_draw',
            'fair_away': f'{prefix}_fair_away',
        })
        # 每场可能多个 provider，取首条（DataLake 已保证 closing 唯一性，但保险起见）
        sub = sub.drop_duplicates(subset=['match_id'], keep='first')
        odds_pivots.append(sub)

    odds = odds_pivots[0]
    for sub in odds_pivots[1:]:
        odds = odds.merge(sub, on='match_id', how='outer')
    print(f'📊 closing odds: {len(odds)} 行 × {len(odds.columns)-1} 列')

    # ── 5) Merge all ───────────────────────────────────────────
    print('🔗 Merging...')
    out = dm.merge(roll_home, on=['match_id', 'Home_Team_ID'], how='left')
    out = out.merge(roll_away, on=['match_id', 'Away_Team_ID'], how='left')
    out = out.merge(pi_home,   on=['match_id', 'Home_Team_ID'], how='left')
    out = out.merge(pi_away,   on=['match_id', 'Away_Team_ID'], how='left')
    out = out.merge(odds,      on='match_id',                    how='left')

    # ── 6) Label：wdl_label ∈ {0:H_win, 1:Draw, 2:A_win} ────────
    out['wdl_label'] = np.where(
        out['home_score'] > out['away_score'], 0,
        np.where(out['home_score'] == out['away_score'], 1, 2)
    )

    print(f'\n✅ Mart shape: {out.shape}')
    print(f'   Label dist: {out["wdl_label"].value_counts().to_dict()}')

    # ── 7) 写表 ────────────────────────────────────────────────
    if args.dry_run:
        print('[dry-run]')
        return

    print(f'\n💾 写入 {OUT}...')
    cur = conn.cursor()
    cur.execute(f'DROP TABLE IF EXISTS {OUT}')

    int_cols = {'match_id', 'Home_Team_ID', 'Away_Team_ID', 'League_ID',
                'home_score', 'away_score', 'wdl_label'}
    text_cols = {'match_date', 'Season', 'Home_Team_Name', 'Away_Team_Name'}
    ddl_parts = []
    for c in out.columns:
        if c in int_cols:
            ddl_parts.append(f'"{c}" INTEGER')
        elif c in text_cols:
            ddl_parts.append(f'"{c}" TEXT')
        else:
            ddl_parts.append(f'"{c}" REAL')
    cur.execute(f'CREATE TABLE {OUT} ({", ".join(ddl_parts)}, PRIMARY KEY (match_id))')

    # cast int 列
    out_w = out.copy()
    for c in int_cols & set(out_w.columns):
        out_w[c] = out_w[c].astype('Int64')
    out_w = out_w.replace({np.nan: None})

    cols_str = ','.join(f'"{c}"' for c in out.columns)
    placeholders = ','.join(['?'] * len(out.columns))
    cur.executemany(
        f'INSERT INTO {OUT} ({cols_str}) VALUES ({placeholders})',
        (_row_to_py(r) for r in out_w.itertuples(index=False, name=None)),
    )
    cur.execute(f'CREATE INDEX idx_mart_v5_season ON {OUT}(Season)')
    cur.execute(f'CREATE INDEX idx_mart_v5_date   ON {OUT}(match_date)')
    conn.commit()

    n = cur.execute(f'SELECT COUNT(*) FROM {OUT}').fetchone()[0]
    print(f'✅ {OUT}: {n} 行 × {out.shape[1]} 列')

    # 可选：摘要 closing odds 覆盖率
    cov_odds = out['closing_eu_raw_home'].notna().mean()
    print(f'   closing 1x2 odds 覆盖率: {cov_odds:.1%}')

    conn.close()


if __name__ == '__main__':
    main()
