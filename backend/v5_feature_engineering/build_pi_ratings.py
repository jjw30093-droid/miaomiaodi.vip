#!/usr/bin/env python3
"""
build_pi_ratings.py — 从 dim_match 回溯 Pi-Ratings (Constantinou & Fenton 2013)

每支球队维护 4 个评级，全部初始 0：
  home_for     : 主场进攻强度（高=主场进球多）
  home_against : 主场失球强度（高=主场漏球多）
  away_for     : 客场进攻强度
  away_against : 客场失球强度

每场比赛：
  ghe = h.home_for - a.away_against           # 主队预期进球
  gae = a.away_for - h.home_against           # 客队预期进球
  expected_diff = ghe - gae
  margin_error  = (home_score - away_score) - expected_diff
  outcome_signal in {-1,0,+1}                 # 主队 W/D/L 转正负向

  signal = γ · outcome_signal + (1−γ) · margin_error
  Δ = λ · signal

  h.home_for     += Δ;   h.home_against -= Δ
  a.away_for     -= Δ;   a.away_against += Δ

输出：
  1. 表 int_team_pi_ratings (match_id, team_id, match_date, 4 个 pi_*, pi_delta)
  2. Grid search λ ∈ {0.04..0.08}, γ ∈ {0.3..0.7}, 用最后 1 年作 validation 最小化进球差 MSE
  3. Top 10 球队净评级排名

CLAUDE.md §3：唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd

DB_PATH      = '/home/ubuntu/app/backend/football_uk.db'
OUTPUT_TABLE = 'int_team_pi_ratings'

LAM_GRID   = [0.04, 0.05, 0.06, 0.07, 0.08]
GAMMA_GRID = [0.3, 0.4, 0.5, 0.6, 0.7]


# ── 单队评级容器 ────────────────────────────────────────────────────
def _init_team() -> dict[str, float]:
    return {'home_for': 0.0, 'home_against': 0.0,
            'away_for': 0.0, 'away_against': 0.0}


# ── 单场更新 ────────────────────────────────────────────────────────
def _update_match(ratings: dict[int, dict],
                  home_id: int, away_id: int,
                  home_score: int, away_score: int,
                  lam: float, gamma: float) -> tuple[float, float]:
    """更新评级；返回 (expected_diff, delta_home_attack)。

    进攻和防守独立更新：
      err_h = 主队实际进球 - 主队预期进球   （主队进攻误差）
      err_a = 客队实际进球 - 客队预期进球   （客队进攻误差）
    然后把"共享的胜负信号" + "各自的进球数误差"混合：
      sig_h = γ · outcome_signal     + (1−γ) · err_h     → 影响 主队进攻 / 客队防守
      sig_a = γ · (-outcome_signal)  + (1−γ) · err_a     → 影响 客队进攻 / 主队防守
    """
    h = ratings[home_id]
    a = ratings[away_id]

    ghe = h['home_for'] - a['away_against']  # 主队预期进球
    gae = a['away_for'] - h['home_against']  # 客队预期进球
    expected_diff = ghe - gae

    err_h = home_score - ghe   # 主队进攻误差（正 = 主队比预期能进）
    err_a = away_score - gae   # 客队进攻误差

    if   home_score > away_score:  outcome_h = 1.0
    elif home_score == away_score: outcome_h = 0.5
    else:                          outcome_h = 0.0
    outcome_signal = (outcome_h - 0.5) * 2.0  # ∈ {-1, 0, +1} 主队视角

    sig_h = gamma * outcome_signal      + (1.0 - gamma) * err_h
    sig_a = gamma * (-outcome_signal)   + (1.0 - gamma) * err_a
    delta_h = lam * sig_h
    delta_a = lam * sig_a

    # delta_h > 0 → 主队进攻比预期强 + 客队防守比预期弱
    h['home_for']     += delta_h
    a['away_against'] += delta_h
    # delta_a > 0 → 客队进攻比预期强 + 主队防守比预期弱
    a['away_for']     += delta_a
    h['home_against'] += delta_a

    return expected_diff, delta_h


# ── 预测（不更新评级） ─────────────────────────────────────────────
def _predict_diff(ratings: dict[int, dict], home_id: int, away_id: int) -> float:
    h = ratings.get(home_id) or _init_team()
    a = ratings.get(away_id) or _init_team()
    return (h['home_for'] - a['away_against']) - (a['away_for'] - h['home_against'])


# ── Grid search 评估：训练 → 在 validation 上算预测进球差 MSE ─────
def _evaluate_mse(matches: pd.DataFrame, lam: float, gamma: float, val_start_date: str) -> tuple[float, int]:
    train = matches[matches['Date'] < val_start_date]
    val   = matches[matches['Date'] >= val_start_date]

    ratings: dict[int, dict] = defaultdict(_init_team)
    # train pass — 只更新评级
    for r in train.itertuples(index=False):
        if r.home_score is None or r.away_score is None:
            continue
        _update_match(ratings, int(r.Home_Team_ID), int(r.Away_Team_ID),
                      int(r.home_score), int(r.away_score), lam, gamma)

    # validation pass — 先预测后更新（在线学习模式）
    sq_errs: list[float] = []
    for r in val.itertuples(index=False):
        if r.home_score is None or r.away_score is None:
            continue
        pred = _predict_diff(ratings, int(r.Home_Team_ID), int(r.Away_Team_ID))
        actual = int(r.home_score) - int(r.away_score)
        sq_errs.append((actual - pred) ** 2)
        _update_match(ratings, int(r.Home_Team_ID), int(r.Away_Team_ID),
                      int(r.home_score), int(r.away_score), lam, gamma)

    return (float(np.mean(sq_errs)) if sq_errs else float('inf'), len(sq_errs))


# ── 完整回溯，保留每场快照 ────────────────────────────────────────
def _run_full_history(matches: pd.DataFrame, lam: float, gamma: float) -> tuple[dict, list[dict]]:
    ratings: dict[int, dict] = defaultdict(_init_team)
    history: list[dict] = []

    for r in matches.itertuples(index=False):
        if r.home_score is None or r.away_score is None:
            continue
        h_id, a_id = int(r.Home_Team_ID), int(r.Away_Team_ID)
        _, delta = _update_match(ratings, h_id, a_id,
                                  int(r.home_score), int(r.away_score), lam, gamma)

        # 快照评级（更新后）
        for tid, side in ((h_id, 'home'), (a_id, 'away')):
            t = ratings[tid]
            history.append({
                'match_id':         int(r.Match_ID),
                'team_id':          tid,
                'match_date':       r.Date,
                'pi_home_for':      t['home_for'],
                'pi_home_against':  t['home_against'],
                'pi_away_for':      t['away_for'],
                'pi_away_against':  t['away_against'],
                'pi_delta':         delta if side == 'home' else -delta,
            })
    return ratings, history


# ── 主流程 ──────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',         default=DB_PATH)
    parser.add_argument('--lam',        type=float, default=0.06)
    parser.add_argument('--gamma',      type=float, default=0.6)
    parser.add_argument('--skip-grid',  action='store_true', help='跳过 grid search 用 --lam/--gamma')
    parser.add_argument('--dry-run',    action='store_true', help='不写表')
    args = parser.parse_args()

    print(f'📂 DB: {args.db}')

    conn = sqlite3.connect(args.db)
    matches = pd.read_sql_query("""
        SELECT Match_ID, Date, Home_Team_ID, Away_Team_ID, home_score, away_score
        FROM dim_match
        WHERE home_score IS NOT NULL AND away_score IS NOT NULL
          AND Home_Team_ID IS NOT NULL AND Away_Team_ID IS NOT NULL
        ORDER BY Date ASC, Match_ID ASC
    """, conn)
    print(f'📊 Matches loaded: {len(matches)}')

    # ── 1) Grid search ─────────────────────────────────────────────
    if not args.skip_grid:
        max_dt    = pd.to_datetime(matches['Date'].max())
        val_start = (max_dt - pd.DateOffset(years=1)).strftime('%Y-%m-%d')
        print(f'\n🔍 Grid search (validation from {val_start})...')

        best = None
        results = []
        for lam in LAM_GRID:
            for gamma in GAMMA_GRID:
                mse, n_val = _evaluate_mse(matches, lam, gamma, val_start)
                results.append((lam, gamma, mse, n_val))
                marker = ''
                if best is None or mse < best[2]:
                    best = (lam, gamma, mse, n_val)
                    marker = ' ★'
                print(f'  λ={lam:.2f} γ={gamma:.1f}: MSE={mse:.4f} (n={n_val}){marker}')

        best_lam, best_gamma, best_mse, _ = best
        print(f'\n🏆 Best: λ={best_lam} γ={best_gamma}, MSE={best_mse:.4f}')
    else:
        best_lam, best_gamma = args.lam, args.gamma
        print(f'\n⏭ 跳过 grid，使用 λ={best_lam} γ={best_gamma}')

    # ── 2) 完整回溯 ───────────────────────────────────────────────
    print('\n🔄 Building full history with best params...')
    ratings, history = _run_full_history(matches, best_lam, best_gamma)
    print(f'   生成 {len(history)} 行历史快照')

    # ── 3) 写表 ────────────────────────────────────────────────────
    if args.dry_run:
        print('   [dry-run] 不写表')
    else:
        print(f'\n💾 写入 {OUTPUT_TABLE} ...')
        cur = conn.cursor()
        cur.execute(f'DROP TABLE IF EXISTS {OUTPUT_TABLE}')
        cur.execute(f'''
            CREATE TABLE {OUTPUT_TABLE} (
                match_id          INTEGER NOT NULL,
                team_id           INTEGER NOT NULL,
                match_date        TEXT    NOT NULL,
                pi_home_for       REAL    NOT NULL,
                pi_home_against   REAL    NOT NULL,
                pi_away_for       REAL    NOT NULL,
                pi_away_against   REAL    NOT NULL,
                pi_delta          REAL    NOT NULL,
                PRIMARY KEY (match_id, team_id)
            )
        ''')
        cur.executemany(f'''
            INSERT INTO {OUTPUT_TABLE}
            (match_id, team_id, match_date, pi_home_for, pi_home_against,
             pi_away_for, pi_away_against, pi_delta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', [(h['match_id'], h['team_id'], h['match_date'],
               h['pi_home_for'], h['pi_home_against'],
               h['pi_away_for'], h['pi_away_against'], h['pi_delta'])
              for h in history])
        cur.execute(f'CREATE INDEX idx_pi_team_date ON {OUTPUT_TABLE}(team_id, match_date)')
        cur.execute(f'CREATE INDEX idx_pi_match ON {OUTPUT_TABLE}(match_id)')
        conn.commit()

        n = cur.execute(f'SELECT COUNT(*) FROM {OUTPUT_TABLE}').fetchone()[0]
        print(f'✅ {OUTPUT_TABLE}: {n} 行')

    # ── 4) Top 10 排名 ────────────────────────────────────────────
    name_df = pd.read_sql_query('SELECT team_id, canonical_name FROM dim_team', conn)
    name_map = dict(zip(name_df['team_id'], name_df['canonical_name']))

    final: list[dict] = []
    for tid, r in ratings.items():
        net = r['home_for'] + r['away_for'] - r['home_against'] - r['away_against']
        final.append({
            'team_id':      tid,
            'name':         name_map.get(tid, f'Team#{tid}'),
            'net':          net,
            'home_for':     r['home_for'],
            'home_against': r['home_against'],
            'away_for':     r['away_for'],
            'away_against': r['away_against'],
        })
    final.sort(key=lambda x: -x['net'])

    print('\n🏅 Top 10 Pi-Ratings:')
    print(f'{"Rk":<3} {"Team":<32} {"Net":>7} {"H_For":>7} {"H_Ag":>7} {"A_For":>7} {"A_Ag":>7}')
    print('─' * 76)
    for i, t in enumerate(final[:10], 1):
        print(f'{i:<3} {t["name"][:32]:<32} '
              f'{t["net"]:>+7.3f} {t["home_for"]:>+7.3f} {t["home_against"]:>+7.3f} '
              f'{t["away_for"]:>+7.3f} {t["away_against"]:>+7.3f}')

    conn.close()


if __name__ == '__main__':
    main()
