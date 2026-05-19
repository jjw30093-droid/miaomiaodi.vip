#!/usr/bin/env python3
"""
build_matrix_v5.py — 构建 match-level 预测矩阵（每行一场，特征为 home-away diff）

**完全幂等**：直接读取源表，不依赖任何中间宽表，可多次重跑。

输入源表：
  dim_match                — 比赛列表、联赛、比分
  int_team_rolling_v5      — 每队每场的多窗口滚动特征（359 列）
  int_team_pi_ratings      — Pi-Rating 快照（每场赛后更新，lag-1 = 赛前）
  int_team_elo_history     — ELO pre-match 快照
  silver_match_odds        — opening / closing 赔率

输出：
  mart_prediction_matrix_v5（约 6800 行 × ~160 列，PK=match_id）

特征设计（约 140 个特征列）：
  ① roll_5_all diff   × 33 指标                              = 33 cols
  ② roll_10_all diff  × 33 指标                              = 33 cols
  ③ roll_3_all diff   × 8 核心指标（TREND_METRICS）           = 8 cols
  ④ venue diff        home.roll_5_home - away.roll_5_away × 8 = 8 cols
  ⑤ 绝对主场 form     home.roll_5_home × 8                   = 8 cols
  ⑥ 绝对客场 form     away.roll_5_away × 8                   = 8 cols
  ⑦ trend_short diff  × 8                                    = 8 cols
  ⑧ trend_medium diff × 8                                    = 8 cols
  ⑨ opp_adj diff      × 5                                    = 5 cols
  ⑩ Pi-Rating 衍生    5 列（攻防优势 + venue gap）
  ⑪ Elo diff          1 列（home_pre_elo - away_pre_elo）
  ⑫ Rest days         home / away / diff                     = 3 cols
  ⑬ Draw features     strength_parity / form_convergence
                      low_scoring_index / league_draw_rate   = 4 cols
  ⑭ Opening odds      fair + line                            = 10 cols
  ⑮ Closing odds      full set（21 cols，训练时可选排除）

标签：
  result ∈ {H, D, A}    label_enc ∈ {0, 1, 2}

CLAUDE.md §3：唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations

import argparse
import sqlite3
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)

DB_PATH = '/home/ubuntu/app/backend/football_uk.db'
OUT     = 'mart_prediction_matrix_v5'

# ── 指标集（与 build_rolling_v5.py 对齐）─────────────────────────────
RAW_METRICS = [
    'expected_goals', 'expected_goals_non_penalty', 'expected_goals_open_play',
    'Goals', 'total_shots', 'ShotsOnTarget', 'shots_inside_box', 'big_chance',
    'touches_opp_box', 'BallPossesion', 'accurate_passes', 'opposition_half_passes',
    'interceptions', 'shot_blocks', 'clearances', 'keeper_saves', 'duel_won',
    'aerials_won', 'corners',
]
RATIO_METRICS = [
    'shot_accuracy', 'box_shot_ratio', 'npxg_per_shot', 'xg_conversion',
    'big_chance_rate', 'xgot_ratio', 'open_play_xg_share', 'set_play_xg_share',
    'territorial_dominance', 'pass_accuracy', 'box_touches_per_poss',
    'block_rate', 'save_ratio', 'attack_quality',
]
ALL_METRICS   = RAW_METRICS + RATIO_METRICS   # 33
TREND_METRICS = [
    'expected_goals_non_penalty', 'xg_conversion', 'shot_accuracy',
    'territorial_dominance', 'box_shot_ratio', 'save_ratio',
    'pass_accuracy', 'attack_quality',
]  # 8
OPP_ADJ_METRICS = [
    'expected_goals_non_penalty', 'shot_accuracy', 'box_shot_ratio',
    'territorial_dominance', 'save_ratio',
]  # 5

# ── rolling 特征列名辅助 ─────────────────────────────────────────────
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


# ── rest days（每队距上一场的间隔天数）──────────────────────────────
def _compute_rest_days(dim: pd.DataFrame) -> pd.DataFrame:
    """返回 match_id / home_rest_days / away_rest_days 的 DataFrame。"""
    dim = dim.copy()
    dim['_dt'] = pd.to_datetime(dim['match_date'], errors='coerce')

    # 展开为 per-team 视角
    rows = []
    for side, tid_col in [('home', 'Home_Team_ID'), ('away', 'Away_Team_ID')]:
        sub = dim[['match_id', '_dt', tid_col]].rename(
            columns={tid_col: 'team_id', '_dt': 'dt'})
        sub['side'] = side
        rows.append(sub)
    events = pd.concat(rows, ignore_index=True)
    events = events.sort_values(['team_id', 'dt', 'match_id'])
    events['prev_dt'] = events.groupby('team_id')['dt'].shift(1)
    events['rest_days'] = (events['dt'] - events['prev_dt']).dt.days

    home_rest = (events[events['side'] == 'home']
                 [['match_id', 'rest_days']]
                 .rename(columns={'rest_days': 'home_rest_days'}))
    away_rest = (events[events['side'] == 'away']
                 [['match_id', 'rest_days']]
                 .rename(columns={'rest_days': 'away_rest_days'}))
    return home_rest.merge(away_rest, on='match_id', how='outer')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',      default=DB_PATH)
    parser.add_argument('--dry-run', action='store_true')
    # 2026-05-04: include未来场次（target=NULL），供 lambda 推理读特征
    parser.add_argument('--include-future', '--include_future', action='store_true',
                        dest='include_future',
                        help='保留未来场次行（home_score IS NULL）供 inference 使用')
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)

    # ── 1) dim_match ─────────────────────────────────────────────────
    print('📂 加载 dim_match...')
    if args.include_future:
        # 包含未完赛/未来场次（home_score 可能 NULL），用于 lambda 推理时读特征
        dm = pd.read_sql_query("""
            SELECT Match_ID AS match_id, Date AS match_date, Season, League_ID,
                   Home_Team_ID, Away_Team_ID, Home_Team_Name, Away_Team_Name,
                   home_score, away_score
            FROM dim_match
            WHERE Home_Team_ID IS NOT NULL AND Away_Team_ID IS NOT NULL
              AND Date >= '2024-01-01'
            ORDER BY Date ASC, Match_ID ASC
        """, conn)
        print(f'   {len(dm)} 场（含未来场次）')
    else:
        dm = pd.read_sql_query("""
            SELECT Match_ID AS match_id, Date AS match_date, Season, League_ID,
                   Home_Team_ID, Away_Team_ID, Home_Team_Name, Away_Team_Name,
                   home_score, away_score
            FROM dim_match
            WHERE home_score IS NOT NULL AND away_score IS NOT NULL
              AND Home_Team_ID IS NOT NULL AND Away_Team_ID IS NOT NULL
            ORDER BY Date ASC, Match_ID ASC
        """, conn)
        print(f'   {len(dm)} 场完赛')

    # ── 2) Rolling 表（int_team_rolling_v5）──────────────────────────
    print('🔄 加载 int_team_rolling_v5...')
    roll = pd.read_sql_query('SELECT * FROM int_team_rolling_v5', conn)
    feat_cols_roll = [c for c in roll.columns if c not in ID_DROP]
    print(f'   {len(roll)} 行，{len(feat_cols_roll)} 特征列')

    # home 视角：重命名特征列加 home_ 前缀，team_id → Home_Team_ID
    roll_home = roll.rename(columns={c: f'home_{c}' for c in feat_cols_roll})
    roll_home = roll_home.rename(columns={'team_id': 'Home_Team_ID'})
    roll_home = roll_home[['match_id', 'Home_Team_ID'] + [f'home_{c}' for c in feat_cols_roll]]

    # away 视角
    roll_away = roll.rename(columns={c: f'away_{c}' for c in feat_cols_roll})
    roll_away = roll_away.rename(columns={'team_id': 'Away_Team_ID'})
    roll_away = roll_away[['match_id', 'Away_Team_ID'] + [f'away_{c}' for c in feat_cols_roll]]

    # ── 3) Pi-Rating lag-1（赛前评级 = 上一场赛后评级）──────────────
    print('🥧 加载 Pi-Ratings（lag-1）...')
    pi = pd.read_sql_query("""
        SELECT match_id, team_id, match_date,
               pi_home_for, pi_home_against, pi_away_for, pi_away_against
        FROM int_team_pi_ratings
        ORDER BY team_id, match_date, match_id
    """, conn)
    pi['match_date'] = pd.to_datetime(pi['match_date'], errors='coerce')
    pi_lag = pi.copy()
    for col in ('pi_home_for', 'pi_home_against', 'pi_away_for', 'pi_away_against'):
        pi_lag[col] = pi_lag.groupby('team_id')[col].shift(1)

    pi_home = pi_lag.rename(columns={
        'team_id': 'Home_Team_ID',
        'pi_home_for':     'home_pi_home_for',
        'pi_home_against': 'home_pi_home_against',
        'pi_away_for':     'home_pi_away_for',
        'pi_away_against': 'home_pi_away_against',
    })[['match_id', 'Home_Team_ID',
        'home_pi_home_for', 'home_pi_home_against',
        'home_pi_away_for', 'home_pi_away_against']]

    pi_away = pi_lag.rename(columns={
        'team_id': 'Away_Team_ID',
        'pi_home_for':     'away_pi_home_for',
        'pi_home_against': 'away_pi_home_against',
        'pi_away_for':     'away_pi_away_for',
        'pi_away_against': 'away_pi_away_against',
    })[['match_id', 'Away_Team_ID',
        'away_pi_home_for', 'away_pi_home_against',
        'away_pi_away_for', 'away_pi_away_against']]

    # ── 4) Elo pre-match ─────────────────────────────────────────────
    print('⚡ 加载 Elo...')
    elo = pd.read_sql_query(
        'SELECT team_id, match_id, pre_match_elo FROM int_team_elo_history', conn)
    elo['match_id'] = elo['match_id'].astype(str)

    elo_home = elo.rename(columns={'team_id': 'Home_Team_ID',
                                   'pre_match_elo': 'home_pre_elo'})[
        ['match_id', 'Home_Team_ID', 'home_pre_elo']]
    elo_away = elo.rename(columns={'team_id': 'Away_Team_ID',
                                   'pre_match_elo': 'away_pre_elo'})[
        ['match_id', 'Away_Team_ID', 'away_pre_elo']]

    # ── 5) Opening 赔率 ───────────────────────────────────────────────
    print('📈 加载 opening odds...')
    raw_odds = pd.read_sql_query("""
        SELECT match_id, market, fair_home, fair_draw, fair_away, raw_line
        FROM silver_match_odds
        WHERE period = 'opening'
    """, conn)

    odds_open = None
    for mkt, pfx in [('1x2', 'open_eu'), ('ah', 'open_ah'), ('ou', 'open_ou')]:
        sub = raw_odds[raw_odds['market'] == mkt].copy()
        sub = sub.drop_duplicates(subset=['match_id'], keep='first')
        sub = sub.rename(columns={
            'fair_home': f'{pfx}_fair_home',
            'fair_draw': f'{pfx}_fair_draw',
            'fair_away': f'{pfx}_fair_away',
            'raw_line':  f'{pfx}_line',
        })[['match_id', f'{pfx}_fair_home', f'{pfx}_fair_draw',
            f'{pfx}_fair_away', f'{pfx}_line']]
        odds_open = sub if odds_open is None else odds_open.merge(
            sub, on='match_id', how='outer')

    # ── 6) Closing 赔率 ───────────────────────────────────────────────
    raw_close = pd.read_sql_query("""
        SELECT match_id, market, raw_home, raw_draw, raw_away, raw_line,
               fair_home, fair_draw, fair_away
        FROM silver_match_odds
        WHERE period = 'closing'
    """, conn)

    odds_close = None
    for mkt, pfx in [('1x2', 'closing_eu'), ('ah', 'closing_ah'), ('ou', 'closing_ou')]:
        sub = raw_close[raw_close['market'] == mkt].copy()
        sub = sub.drop_duplicates(subset=['match_id'], keep='first')
        sub = sub.rename(columns={
            'raw_home':  f'{pfx}_raw_home',
            'raw_draw':  f'{pfx}_raw_draw',
            'raw_away':  f'{pfx}_raw_away',
            'raw_line':  f'{pfx}_line',
            'fair_home': f'{pfx}_fair_home',
            'fair_draw': f'{pfx}_fair_draw',
            'fair_away': f'{pfx}_fair_away',
        })[['match_id',
            f'{pfx}_raw_home', f'{pfx}_raw_draw', f'{pfx}_raw_away', f'{pfx}_line',
            f'{pfx}_fair_home', f'{pfx}_fair_draw', f'{pfx}_fair_away']]
        odds_close = sub if odds_close is None else odds_close.merge(
            sub, on='match_id', how='outer')

    # ── 7) Merge 所有源表 ─────────────────────────────────────────────
    print('🔗 Merge...')
    dm['match_id'] = dm['match_id'].astype(str)
    roll_home['match_id'] = roll_home['match_id'].astype(str)
    roll_away['match_id'] = roll_away['match_id'].astype(str)
    pi_home['match_id']   = pi_home['match_id'].astype(str)
    pi_away['match_id']   = pi_away['match_id'].astype(str)
    elo_home['match_id']  = elo_home['match_id'].astype(str)
    elo_away['match_id']  = elo_away['match_id'].astype(str)
    if odds_open is not None:
        odds_open['match_id'] = odds_open['match_id'].astype(str)
    if odds_close is not None:
        odds_close['match_id'] = odds_close['match_id'].astype(str)

    out = dm.copy()
    out = out.merge(roll_home, on=['match_id', 'Home_Team_ID'], how='left')
    out = out.merge(roll_away, on=['match_id', 'Away_Team_ID'], how='left')
    out = out.merge(pi_home,   on=['match_id', 'Home_Team_ID'], how='left')
    out = out.merge(pi_away,   on=['match_id', 'Away_Team_ID'], how='left')
    out = out.merge(elo_home,  on=['match_id', 'Home_Team_ID'], how='left')
    out = out.merge(elo_away,  on=['match_id', 'Away_Team_ID'], how='left')
    if odds_open is not None:
        out = out.merge(odds_open,  on='match_id', how='left')
    if odds_close is not None:
        out = out.merge(odds_close, on='match_id', how='left')

    print(f'   merged: {len(out)} 行 × {len(out.columns)} 列')
    print(f'   ELO 覆盖 home={out["home_pre_elo"].notna().mean():.1%}  '
          f'away={out["away_pre_elo"].notna().mean():.1%}')

    # ── 8) Rest days + 联赛平局率 ────────────────────────────────────
    print('😴 计算 rest days...')
    rest = _compute_rest_days(
        out[['match_id', 'match_date', 'Home_Team_ID', 'Away_Team_ID']])
    rest['match_id'] = rest['match_id'].astype(str)
    out = out.merge(rest, on='match_id', how='left')

    print('🤝 计算 league draw rates...')
    out['_is_draw'] = (out['home_score'] == out['away_score']).astype(int)
    league_dr = out.groupby('League_ID')['_is_draw'].mean().rename('league_draw_rate')
    out = out.join(out['League_ID'].map(league_dr).rename('league_draw_rate'))
    out = out.drop(columns=['_is_draw'])

    # ── 9) 构建 diff 特征字典（避免 DataFrame 碎片）──────────────────
    print('🔢 构建 diff 特征...')
    feats: dict[str, pd.Series] = {}

    # ① roll_5_all diff（全 33 指标）
    for m in ALL_METRICS:
        hc, ac = f'home_roll_5_all_{m}', f'away_roll_5_all_{m}'
        if hc in out.columns and ac in out.columns:
            feats[f'diff_roll5_{m}'] = out[hc] - out[ac]

    # ② roll_10_all diff（全 33 指标）
    for m in ALL_METRICS:
        hc, ac = f'home_roll_10_all_{m}', f'away_roll_10_all_{m}'
        if hc in out.columns and ac in out.columns:
            feats[f'diff_roll10_{m}'] = out[hc] - out[ac]

    # ③ roll_3_all diff（8 TREND_METRICS）
    for m in TREND_METRICS:
        hc, ac = f'home_roll_3_all_{m}', f'away_roll_3_all_{m}'
        if hc in out.columns and ac in out.columns:
            feats[f'diff_roll3_{m}'] = out[hc] - out[ac]

    # ④ venue diff: home.roll_5_home - away.roll_5_away（8 TREND_METRICS）
    for m in TREND_METRICS:
        hc, ac = f'home_roll_5_home_{m}', f'away_roll_5_away_{m}'
        if hc in out.columns and ac in out.columns:
            feats[f'diff_venue5_{m}'] = out[hc] - out[ac]

    # ⑤ 绝对主场 form（home.roll_5_home × 8）
    for m in TREND_METRICS:
        hc = f'home_roll_5_home_{m}'
        if hc in out.columns:
            feats[f'home_venue5_{m}'] = out[hc]

    # ⑥ 绝对客场 form（away.roll_5_away × 8）
    for m in TREND_METRICS:
        ac = f'away_roll_5_away_{m}'
        if ac in out.columns:
            feats[f'away_venue5_{m}'] = out[ac]

    # ⑦ trend_short diff（8 TREND_METRICS）
    for m in TREND_METRICS:
        hc, ac = f'home_trend_short_{m}', f'away_trend_short_{m}'
        if hc in out.columns and ac in out.columns:
            feats[f'diff_trend_short_{m}'] = out[hc] - out[ac]

    # ⑧ trend_medium diff（8 TREND_METRICS）
    for m in TREND_METRICS:
        hc, ac = f'home_trend_medium_{m}', f'away_trend_medium_{m}'
        if hc in out.columns and ac in out.columns:
            feats[f'diff_trend_medium_{m}'] = out[hc] - out[ac]

    # ⑨ opp_adj diff（5 OPP_ADJ_METRICS）
    for m in OPP_ADJ_METRICS:
        hc, ac = f'home_opp_adj_{m}', f'away_opp_adj_{m}'
        if hc in out.columns and ac in out.columns:
            feats[f'diff_opp_adj_{m}'] = out[hc] - out[ac]

    n_base_feats = len(feats)

    # ⑩ Pi-Rating 衍生（5 列）
    feats['pi_home_attack_adv'] = out['home_pi_home_for']   - out['away_pi_away_against']
    feats['pi_away_attack_adv'] = out['away_pi_away_for']   - out['home_pi_home_against']
    feats['pi_net_advantage']   = feats['pi_home_attack_adv'] - feats['pi_away_attack_adv']
    feats['pi_home_venue_gap']  = out['home_pi_home_for']   - out['home_pi_away_for']
    feats['pi_away_venue_gap']  = out['away_pi_home_for']   - out['away_pi_away_for']

    # ⑪ Elo diff
    feats['elo_diff'] = out['home_pre_elo'] - out['away_pre_elo']

    # ⑫ Rest days
    feats['home_rest_days'] = out['home_rest_days']
    feats['away_rest_days'] = out['away_rest_days']
    feats['rest_diff']      = out['home_rest_days'] - out['away_rest_days']

    # ⑬ Draw features
    elo_diff_abs = feats['elo_diff'].abs()
    feats['strength_parity'] = 1.0 / (1.0 + elo_diff_abs / 400.0)
    hg = out.get(f'home_roll_5_all_Goals')
    ag = out.get(f'away_roll_5_all_Goals')
    if hg is not None and ag is not None:
        feats['form_convergence']  = 1.0 / (1.0 + (hg - ag).abs())
        feats['low_scoring_index'] = 1.0 / (1.0 + (hg + ag) / 2.0)
    else:
        feats['form_convergence']  = np.nan
        feats['low_scoring_index'] = np.nan
    feats['league_draw_rate'] = out['league_draw_rate']

    # ⑭ Opening odds
    for col in [c for c in out.columns if c.startswith('open_')]:
        feats[col] = out[col]

    # ⑮ Closing odds
    for col in [c for c in out.columns if c.startswith('closing_')]:
        feats[col] = out[col]

    print(f'   diff 特征（①～⑨）: {n_base_feats}  总特征: {len(feats)}')

    # ── 10) 标签 ─────────────────────────────────────────────────────
    result = np.where(
        out['home_score'] > out['away_score'], 'H',
        np.where(out['home_score'] == out['away_score'], 'D', 'A')
    )
    label_enc = np.where(result == 'H', 0, np.where(result == 'D', 1, 2))

    # ── 11) 组装最终 DataFrame ───────────────────────────────────────
    meta = out[['match_id', 'match_date', 'Season', 'League_ID',
                'Home_Team_ID', 'Away_Team_ID',
                'Home_Team_Name', 'Away_Team_Name',
                'home_score', 'away_score']].copy()
    meta['result']    = result
    meta['label_enc'] = label_enc
    meta['wdl_label'] = label_enc    # 同义，与 v4 pipeline 兼容

    feat_df = pd.DataFrame(feats, index=out.index)
    final   = pd.concat([meta.reset_index(drop=True),
                         feat_df.reset_index(drop=True)], axis=1)

    n_feat = len(feats)
    print(f'\n✅ Matrix shape: {final.shape}  （{n_feat} 特征列）')
    print(f'   Label dist: {pd.Series(result).value_counts().to_dict()}')

    # 覆盖率摘要
    checks = {
        'diff_roll5_expected_goals_non_penalty': 0.85,
        'diff_roll10_shot_accuracy':             0.85,
        'diff_venue5_territorial_dominance':     0.70,
        'pi_net_advantage':                      0.80,
        'elo_diff':                              0.90,
        'home_rest_days':                        0.80,
        'open_eu_fair_home':                     0.80,
        'closing_eu_fair_home':                  0.80,
    }
    for col, thr in checks.items():
        if col in final.columns:
            cov  = final[col].notna().mean()
            flag = '✓' if cov >= thr else '⚠'
            print(f'  {flag} {col:<48} {cov:.1%}  (≥{thr:.0%})')

    if args.dry_run:
        print('\n[dry-run] 不写表')
        conn.close()
        return

    # ── 12) 写表（覆盖）─────────────────────────────────────────────
    print(f'\n💾 写入 {OUT}...')
    cur = conn.cursor()
    cur.execute(f'DROP TABLE IF EXISTS {OUT}')

    int_cols  = {'match_id', 'Home_Team_ID', 'Away_Team_ID', 'League_ID',
                 'home_score', 'away_score', 'wdl_label', 'label_enc'}
    text_cols = {'match_date', 'Season', 'Home_Team_Name', 'Away_Team_Name', 'result'}

    ddl_parts = []
    for c in final.columns:
        if c in int_cols:
            ddl_parts.append(f'"{c}" INTEGER')
        elif c in text_cols:
            ddl_parts.append(f'"{c}" TEXT')
        else:
            ddl_parts.append(f'"{c}" REAL')
    cur.execute(
        f'CREATE TABLE {OUT} ({", ".join(ddl_parts)}, PRIMARY KEY (match_id))'
    )

    final_w = final.copy()
    for c in int_cols & set(final_w.columns):
        final_w[c] = pd.to_numeric(final_w[c], errors='coerce').astype('Int64')
    final_w = final_w.replace({np.nan: None})

    cols_str     = ','.join(f'"{c}"' for c in final.columns)
    placeholders = ','.join(['?'] * len(final.columns))
    cur.executemany(
        f'INSERT INTO {OUT} ({cols_str}) VALUES ({placeholders})',
        (_row_to_py(r) for r in final_w.itertuples(index=False, name=None)),
    )
    cur.execute(f'CREATE INDEX idx_matv5_season ON {OUT}(Season)')
    cur.execute(f'CREATE INDEX idx_matv5_date   ON {OUT}(match_date)')
    cur.execute(f'CREATE INDEX idx_matv5_league ON {OUT}(League_ID)')
    conn.commit()

    n = cur.execute(f'SELECT COUNT(*) FROM {OUT}').fetchone()[0]
    print(f'✅ {OUT}: {n} 行 × {final.shape[1]} 列（{n_feat} 特征列）')

    conn.close()


if __name__ == '__main__':
    main()
