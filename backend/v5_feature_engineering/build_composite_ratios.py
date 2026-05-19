#!/usr/bin/env python3
"""
build_composite_ratios.py — 从 fact_team_match_stats self-join 计算 per-match-per-team 复合比率

Step 1  Self-join：a.Match_ID = b.Match_ID AND a.Team_ID != b.Team_ID
Step 2  计算 18 个复合比率（分母为 0 / NULL → 结果 NULL）
Step 3  写入 int_team_match_composite_v5（包含 ratios + 原始字段，方便下一步 rolling）
Step 4  打印行数、各字段 NULL 率、前 3 行样本

CLAUDE.md §3：唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations

import argparse
import sqlite3

import numpy as np
import pandas as pd

DB_PATH      = '/home/ubuntu/app/backend/football_uk.db'
OUTPUT_TABLE = 'int_team_match_composite_v5'

# 注意：matchstats.headers.tackles 列名含点，SQL 中需用方括号转义；本脚本暂不用此字段。
# Self-join：a 是当前队，b 是对手；同时 LEFT JOIN dim_match 拿日期 + is_home。
SELF_JOIN_SQL = """
SELECT
    a.Match_ID                         AS match_id,
    a.Team_ID                          AS team_id,
    b.Team_ID                          AS opponent_id,
    dm.Date                            AS match_date,
    CASE WHEN dm.Home_Team_ID = a.Team_ID THEN 1 ELSE 0 END AS is_home,

    -- 当前队原始字段（保留给后面 rolling）
    a.expected_goals                   AS expected_goals,
    a.expected_goals_non_penalty       AS expected_goals_non_penalty,
    a.expected_goals_open_play         AS expected_goals_open_play,
    a.expected_goals_set_play          AS expected_goals_set_play,
    a.expected_goals_on_target         AS expected_goals_on_target,
    a.Goals                            AS Goals,
    a.total_shots                      AS total_shots,
    a.ShotsOnTarget                    AS ShotsOnTarget,
    a.shots_inside_box                 AS shots_inside_box,
    a.big_chance                       AS big_chance,
    a.touches_opp_box                  AS touches_opp_box,
    a.BallPossesion                    AS BallPossesion,
    a.accurate_passes                  AS accurate_passes,
    a.opposition_half_passes           AS opposition_half_passes,
    a.passes                           AS passes,
    a.long_balls_accurate              AS long_balls_accurate,
    a.interceptions                    AS interceptions,
    a.shot_blocks                      AS shot_blocks,
    a.clearances                       AS clearances,
    a.keeper_saves                     AS keeper_saves,
    a.duel_won                         AS duel_won,
    a.aerials_won                      AS aerials_won,
    a.corners                          AS corners,

    -- 对手字段（防守比率分母 / 后面也可能用）
    b.total_shots                      AS opp_total_shots,
    b.ShotsOnTarget                    AS opp_ShotsOnTarget,
    b.passes                           AS opp_passes,
    b.expected_goals                   AS opp_expected_goals,
    b.shots_inside_box                 AS opp_shots_inside_box,
    b.touches_opp_box                  AS opp_touches_opp_box,
    b.BallPossesion                    AS opp_BallPossesion
FROM fact_team_match_stats a
JOIN fact_team_match_stats b
    ON a.Match_ID = b.Match_ID
   AND a.Team_ID != b.Team_ID
   AND a.Period = 'All' AND b.Period = 'All'
LEFT JOIN dim_match dm ON dm.Match_ID = a.Match_ID
ORDER BY dm.Date ASC, a.Match_ID ASC, is_home DESC
"""


def _safe_div(num: pd.Series, den: pd.Series, cap: float | None = None) -> pd.Series:
    """安全相除：分母为 0 / NaN / 负 → NaN；可选 cap 上限。"""
    num = pd.to_numeric(num, errors='coerce')
    den = pd.to_numeric(den, errors='coerce')
    out = num.where(den > 0) / den.where(den > 0)
    if cap is not None:
        out = out.clip(upper=cap)
    return out


def _build_ratios(df: pd.DataFrame) -> pd.DataFrame:
    """计算 18 个复合比率，按用户清单分组。"""
    # 进攻效率 (6)
    df['shot_accuracy']      = _safe_div(df['ShotsOnTarget'],         df['total_shots'])
    df['box_shot_ratio']     = _safe_div(df['shots_inside_box'],      df['total_shots'])
    df['npxg_per_shot']      = _safe_div(df['expected_goals_non_penalty'], df['total_shots'])
    df['xg_conversion']      = _safe_div(df['Goals'],                 df['expected_goals'], cap=3.0)
    df['big_chance_rate']    = _safe_div(df['big_chance'],            df['total_shots'])
    df['xgot_ratio']         = _safe_div(df['expected_goals_on_target'], df['expected_goals'])

    # xG 构成 (2)
    df['open_play_xg_share'] = _safe_div(df['expected_goals_open_play'], df['expected_goals'])
    df['set_play_xg_share']  = _safe_div(df['expected_goals_set_play'],  df['expected_goals'])

    # 控制 / 渗透 (4)
    df['territorial_dominance'] = _safe_div(df['opposition_half_passes'], df['passes'])
    df['pass_accuracy']         = _safe_div(df['accurate_passes'],        df['passes'])
    df['box_touches_per_poss']  = _safe_div(df['touches_opp_box'],        df['BallPossesion'])
    df['long_ball_reliance']    = _safe_div(df['long_balls_accurate'],    df['passes'])

    # 防守（用对手字段做分母） (3)
    df['block_rate']     = _safe_div(df['shot_blocks'],   df['opp_total_shots'])
    df['save_ratio']     = _safe_div(df['keeper_saves'],  df['opp_ShotsOnTarget'])
    df['intercept_rate'] = _safe_div(df['interceptions'], df['opp_passes'])

    # 综合 (1)
    df['attack_quality'] = df['npxg_per_shot'] * df['box_shot_ratio']
    return df


# 18 个复合比率 + 1 个综合
RATIO_COLS = [
    'shot_accuracy', 'box_shot_ratio', 'npxg_per_shot', 'xg_conversion',
    'big_chance_rate', 'xgot_ratio',
    'open_play_xg_share', 'set_play_xg_share',
    'territorial_dominance', 'pass_accuracy', 'box_touches_per_poss', 'long_ball_reliance',
    'block_rate', 'save_ratio', 'intercept_rate',
    'attack_quality',
]

# 全部要写入的列（顺序固定，便于 SQL DDL）
ID_COLS = ['match_id', 'team_id', 'opponent_id', 'match_date', 'is_home']
RAW_COLS = [
    'expected_goals', 'expected_goals_non_penalty', 'expected_goals_open_play',
    'expected_goals_set_play', 'expected_goals_on_target',
    'Goals', 'total_shots', 'ShotsOnTarget', 'shots_inside_box', 'big_chance',
    'touches_opp_box', 'BallPossesion', 'accurate_passes', 'opposition_half_passes',
    'passes', 'long_balls_accurate', 'interceptions', 'shot_blocks', 'clearances',
    'keeper_saves', 'duel_won', 'aerials_won', 'corners',
    # 对手原始（防守比率分母，也保留）
    'opp_total_shots', 'opp_ShotsOnTarget', 'opp_passes', 'opp_expected_goals',
    'opp_shots_inside_box', 'opp_touches_opp_box', 'opp_BallPossesion',
]
ALL_COLS = ID_COLS + RATIO_COLS + RAW_COLS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',      default=DB_PATH)
    parser.add_argument('--dry-run', action='store_true', help='不写表')
    args = parser.parse_args()

    print(f'📂 DB: {args.db}')
    conn = sqlite3.connect(args.db)

    # ── 1. Self-join 拉数 ─────────────────────────────────────────
    df = pd.read_sql_query(SELF_JOIN_SQL, conn)
    print(f'📊 Self-join 后行数: {len(df)}')
    if df.empty:
        print('⚠️  无数据，退出')
        return

    # ── 2. 计算复合比率 ──────────────────────────────────────────
    df = _build_ratios(df)

    # 列对齐 + 顺序统一
    missing = [c for c in ALL_COLS if c not in df.columns]
    if missing:
        raise RuntimeError(f'缺列: {missing}')
    df = df[ALL_COLS].copy()

    # ── 3. NULL 率 + 范围检查 ────────────────────────────────────
    n_total = len(df)
    print(f'\n🧪 NULL 率（共 {n_total} 行）:')
    for c in RATIO_COLS:
        nn = df[c].isna().sum()
        cov = 1 - nn / n_total
        flag = '✓' if cov > 0.85 else '⚠'
        print(f'  {flag} {c:<24} NULL={nn:>5}  覆盖={cov:.1%}')

    # 范围检查（shot_accuracy 必须 ∈ [0,1]）
    sa = df['shot_accuracy'].dropna()
    print(f'\n📏 shot_accuracy 范围: min={sa.min():.4f}  max={sa.max():.4f}  '
          f'(0–1 ∈ ✓)' if (sa.min() >= 0 and sa.max() <= 1) else f'(0–1 ✗)')

    # ── 4. 写表 ──────────────────────────────────────────────────
    if args.dry_run:
        print('\n[dry-run] 不写表')
    else:
        print(f'\n💾 写入 {OUTPUT_TABLE} ...')
        cur = conn.cursor()
        cur.execute(f'DROP TABLE IF EXISTS {OUTPUT_TABLE}')

        # DDL：id 列 INTEGER/TEXT，其余比率/原始 全 REAL
        ddl_cols = []
        for c in ALL_COLS:
            if c in ('match_id', 'team_id', 'opponent_id', 'is_home'):
                ddl_cols.append(f'"{c}" INTEGER')
            elif c == 'match_date':
                ddl_cols.append(f'"{c}" TEXT')
            else:
                ddl_cols.append(f'"{c}" REAL')
        ddl = f'CREATE TABLE {OUTPUT_TABLE} ({", ".join(ddl_cols)}, PRIMARY KEY (match_id, team_id))'
        cur.execute(ddl)

        # 写入：NaN → None，整数列强制 cast 成 Python int（避免 numpy.int64 → BLOB）
        df_out = df.copy()
        for c in ('match_id', 'team_id', 'opponent_id', 'is_home'):
            df_out[c] = df_out[c].astype('Int64')   # nullable int
        df_out = df_out.replace({np.nan: None})
        cols_str     = ','.join(f'"{c}"' for c in ALL_COLS)
        placeholders = ','.join(['?'] * len(ALL_COLS))

        def _row_to_py(row):
            # 把每个值转成 SQLite 能识别的 Python 类型（int / float / str / None）
            out = []
            for v in row:
                if v is None or (isinstance(v, float) and np.isnan(v)):
                    out.append(None)
                elif hasattr(v, 'item'):  # numpy scalar
                    out.append(v.item())
                else:
                    out.append(v)
            return tuple(out)

        cur.executemany(
            f'INSERT INTO {OUTPUT_TABLE} ({cols_str}) VALUES ({placeholders})',
            (_row_to_py(r) for r in df_out.itertuples(index=False, name=None)),
        )
        cur.execute(f'CREATE INDEX idx_compv5_team_date ON {OUTPUT_TABLE}(team_id, match_date)')
        cur.execute(f'CREATE INDEX idx_compv5_match     ON {OUTPUT_TABLE}(match_id)')
        conn.commit()

        n = cur.execute(f'SELECT COUNT(*) FROM {OUTPUT_TABLE}').fetchone()[0]
        print(f'✅ {OUTPUT_TABLE}: {n} 行')

    # ── 5. 前 3 行样本 ──────────────────────────────────────────
    print('\n🔍 样本（前 3 行）:')
    sample_cols = ['match_id', 'team_id', 'opponent_id', 'is_home',
                   'shot_accuracy', 'box_shot_ratio', 'npxg_per_shot', 'xg_conversion',
                   'pass_accuracy', 'block_rate', 'save_ratio', 'attack_quality']
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    print(df[sample_cols].head(3).to_string(index=False, float_format='{:,.4f}'.format))

    conn.close()


if __name__ == '__main__':
    main()
