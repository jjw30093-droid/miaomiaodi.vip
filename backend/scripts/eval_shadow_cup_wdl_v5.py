#!/usr/bin/env python3
"""
scripts/eval_shadow_cup_wdl_v5.py
==================================
每周 WDL 准确率评估 — shadow_cup_wdl_recs 复盘

流程：
  1. 读 shadow_cup_wdl_recs（上周预测，match_date in [week_start, week_end]）
  2. JOIN dim_match 取 home_score / away_score → 计算实际 outcome
  3. 对比 predicted_outcome → hit / miss
  4. 写 shadow_cup_wdl_eval（per-league + aggregate）
  5. 计算滚动 4 周 acc；< 0.45 时 log WARNING

Cron: 每周一 06:00 UTC (job-eval-shadow-cup-wdl)

用法：
    python3 scripts/eval_shadow_cup_wdl_v5.py             # 上周评估
    python3 scripts/eval_shadow_cup_wdl_v5.py --dry-run   # print only, no writes
    python3 scripts/eval_shadow_cup_wdl_v5.py --weeks 2   # 评估上上周 (2=last 2 weeks ago)
    python3 scripts/eval_shadow_cup_wdl_v5.py --since 2026-04-01  # 从某日起所有历史
"""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ─── Path setup ─────────────────────────────────────────────────────────────
PROJECT_ROOT = os.environ.get(
    "PROJECT_ROOT", str(Path(__file__).resolve().parent.parent)
)
DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ─── Config ─────────────────────────────────────────────────────────────────
ROLLING_WINDOW_WEEKS = 4
ACC_WARNING_THRESHOLD = 0.45   # rolling 4w acc below this → WARNING


# ─── Table schemas ───────────────────────────────────────────────────────────

CREATE_EVAL_TABLE = """
CREATE TABLE IF NOT EXISTS shadow_cup_wdl_eval (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_date           TEXT,       -- date this eval ran (UTC)
    week_start          TEXT,       -- Monday of evaluated week
    week_end            TEXT,       -- Sunday of evaluated week
    league_id           INTEGER,    -- NULL = aggregate across all leagues
    n_total             INTEGER,    -- shadow recs in this week/league
    n_correct           INTEGER,    -- correct predictions
    acc                 REAL,       -- weekly accuracy = n_correct / n_total
    rolling_4w_n        INTEGER,    -- total in rolling 4-week window
    rolling_4w_correct  INTEGER,
    rolling_4w_acc      REAL,       -- rolling 4-week accuracy
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_EVAL_IDX = """
CREATE INDEX IF NOT EXISTS idx_scwe_week
ON shadow_cup_wdl_eval(week_start, league_id);
"""


def ensure_eval_table(conn: sqlite3.Connection):
    conn.execute(CREATE_EVAL_TABLE)
    conn.execute(CREATE_EVAL_IDX)
    conn.commit()


# ─── Date helpers ────────────────────────────────────────────────────────────

def last_monday(ref: date) -> date:
    """Return the most recent Monday (UTC) before or on ref."""
    return ref - timedelta(days=ref.weekday())


def week_range(weeks_ago: int = 1) -> tuple[str, str]:
    """Return (week_start, week_end) strings for N weeks ago.

    weeks_ago=1 → last week (Mon–Sun), default for cron.
    """
    today = date.today()
    this_monday = last_monday(today)
    start = this_monday - timedelta(weeks=weeks_ago)
    end = start + timedelta(days=6)
    return start.isoformat(), end.isoformat()


# ─── Outcome computation ─────────────────────────────────────────────────────

def compute_outcome(home_score: int, away_score: int) -> str:
    """Return 'H', 'D', or 'A' from actual scores."""
    if home_score > away_score:
        return "H"
    elif home_score == away_score:
        return "D"
    else:
        return "A"


# ─── Rolling window ──────────────────────────────────────────────────────────

def fetch_rolling_acc(
    conn: sqlite3.Connection,
    league_id: Optional[int],
    up_to_date: str,
    num_weeks: int = ROLLING_WINDOW_WEEKS,
) -> tuple[int, int, Optional[float]]:
    """Fetch rolling N-week accuracy from shadow_cup_wdl_eval.

    Returns (n_total, n_correct, acc) or (0, 0, None) if no data.
    """
    start_date = (
        date.fromisoformat(up_to_date) - timedelta(weeks=num_weeks)
    ).isoformat()

    if league_id is None:
        rows = conn.execute(
            """SELECT SUM(n_total), SUM(n_correct) FROM shadow_cup_wdl_eval
               WHERE league_id IS NULL
                 AND week_start >= ? AND week_end <= ?""",
            (start_date, up_to_date),
        ).fetchone()
    else:
        rows = conn.execute(
            """SELECT SUM(n_total), SUM(n_correct) FROM shadow_cup_wdl_eval
               WHERE league_id = ?
                 AND week_start >= ? AND week_end <= ?""",
            (league_id, start_date, up_to_date),
        ).fetchone()

    n_total = int(rows[0] or 0)
    n_correct = int(rows[1] or 0)
    acc = (n_correct / n_total) if n_total > 0 else None
    return n_total, n_correct, acc


# ─── Core evaluation ─────────────────────────────────────────────────────────

def run_eval(
    week_start: str,
    week_end: str,
    dry_run: bool,
    conn: sqlite3.Connection,
) -> dict:
    """Evaluate shadow recs for a given week. Returns summary dict."""

    # --- Fetch shadow recs for the week with actual scores ---
    rows = conn.execute(
        """
        SELECT
            s.match_id,
            s.league_id,
            s.match_date,
            s.predicted_outcome,
            d.home_score,
            d.away_score
        FROM shadow_cup_wdl_recs s
        JOIN dim_match d ON CAST(d.Match_ID AS INTEGER) = s.match_id
        WHERE s.match_date BETWEEN ? AND ?
          AND d.status = 'Finish'
          AND d.home_score IS NOT NULL
          AND d.away_score IS NOT NULL
        ORDER BY s.league_id, s.match_date
        """,
        (week_start, week_end),
    ).fetchall()

    if not rows:
        log.info(f"No completed shadow recs for {week_start} → {week_end}")
        return {"week_start": week_start, "week_end": week_end, "n_total": 0}

    # --- Compute per-match correctness ---
    results = []
    for mid, lid, mdate, pred, hs, aws in rows:
        actual = compute_outcome(int(hs), int(aws))
        correct = 1 if pred == actual else 0
        results.append({
            "match_id": mid, "league_id": lid, "match_date": mdate,
            "predicted": pred, "actual": actual, "correct": correct,
        })
        log.info(
            f"  mid={mid:<10} lid={lid:<6} {mdate}  "
            f"pred={pred}  actual={actual}  {'✓' if correct else '✗'}"
        )

    # --- Aggregate stats ---
    today_str = date.today().isoformat()
    all_correct = sum(r["correct"] for r in results)
    all_n = len(results)
    all_acc = all_correct / all_n if all_n > 0 else 0.0

    # Per-league breakdown
    league_ids = sorted(set(r["league_id"] for r in results))
    per_league = {}
    for lid in league_ids:
        lg_rows = [r for r in results if r["league_id"] == lid]
        lg_n = len(lg_rows)
        lg_correct = sum(r["correct"] for r in lg_rows)
        per_league[lid] = {"n": lg_n, "correct": lg_correct,
                           "acc": lg_correct / lg_n if lg_n > 0 else 0.0}

    # Rolling 4-week
    roll_n, roll_correct, roll_acc = fetch_rolling_acc(conn, None, week_end)
    # Add current week to rolling window
    roll_n += all_n
    roll_correct += all_correct
    roll_acc = roll_correct / roll_n if roll_n > 0 else None

    # --- Print report ---
    print(f"\n{'='*60}")
    print(f"  shadow_cup_wdl eval | {week_start} → {week_end}")
    print(f"  {'DRY-RUN' if dry_run else 'WRITING TO DB'}")
    print(f"{'='*60}")
    print(f"  Matches evaluated   : {all_n}")
    print(f"  Correct             : {all_correct}")
    print(f"  Week acc            : {all_acc:.3f} ({all_correct}/{all_n})")
    print(f"  Rolling {ROLLING_WINDOW_WEEKS}w acc      : "
          f"{roll_acc:.3f} ({roll_correct}/{roll_n})" if roll_acc is not None
          else f"  Rolling {ROLLING_WINDOW_WEEKS}w acc      : N/A (no prior data)")

    if per_league:
        print(f"\n  Per-league breakdown:")
        for lid, lg in per_league.items():
            print(f"    league {lid:<6}: {lg['acc']:.3f} ({lg['correct']}/{lg['n']})")

    # WARNING check
    if roll_acc is not None and roll_acc < ACC_WARNING_THRESHOLD:
        log.warning(
            f"Rolling {ROLLING_WINDOW_WEEKS}w WDL acc = {roll_acc:.3f} "
            f"< threshold {ACC_WARNING_THRESHOLD}. "
            f"Shadow quality degraded — consider model review."
        )

    # --- Write to DB ---
    if not dry_run:
        ensure_eval_table(conn)

        # Aggregate row
        conn.execute(
            """INSERT INTO shadow_cup_wdl_eval
               (eval_date, week_start, week_end, league_id,
                n_total, n_correct, acc,
                rolling_4w_n, rolling_4w_correct, rolling_4w_acc)
               VALUES (?,?,?,NULL,?,?,?,?,?,?)""",
            (today_str, week_start, week_end,
             all_n, all_correct, round(all_acc, 4),
             roll_n, roll_correct,
             round(roll_acc, 4) if roll_acc is not None else None),
        )

        # Per-league rows
        for lid, lg in per_league.items():
            rl_n, rl_c, rl_acc = fetch_rolling_acc(conn, lid, week_end)
            rl_n += lg["n"]
            rl_c += lg["correct"]
            rl_acc_v = rl_c / rl_n if rl_n > 0 else None
            conn.execute(
                """INSERT INTO shadow_cup_wdl_eval
                   (eval_date, week_start, week_end, league_id,
                    n_total, n_correct, acc,
                    rolling_4w_n, rolling_4w_correct, rolling_4w_acc)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (today_str, week_start, week_end, lid,
                 lg["n"], lg["correct"], round(lg["acc"], 4),
                 rl_n, rl_c,
                 round(rl_acc_v, 4) if rl_acc_v is not None else None),
            )

        conn.commit()
        log.info(f"Eval written: week={week_start}→{week_end}, n={all_n}, acc={all_acc:.3f}")
    else:
        print(f"\n[DRY-RUN] Would write {1 + len(per_league)} rows to shadow_cup_wdl_eval")

    return {
        "week_start": week_start, "week_end": week_end,
        "n_total": all_n, "n_correct": all_correct, "acc": all_acc,
        "rolling_4w_acc": roll_acc,
    }


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Weekly WDL accuracy evaluation for shadow_cup_wdl_recs"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results without writing to shadow_cup_wdl_eval")
    parser.add_argument("--weeks", type=int, default=1,
                        help="Evaluate N weeks ago (default=1 = last week)")
    parser.add_argument("--since", type=str, default=None,
                        help="Evaluate all recs since YYYY-MM-DD (overrides --weeks)")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    try:
        if args.since:
            week_start = args.since
            week_end = date.today().isoformat()
            log.info(f"Evaluating all shadow recs from {week_start} to {week_end}")
            run_eval(week_start, week_end, args.dry_run, conn)
        else:
            ws, we = week_range(weeks_ago=args.weeks)
            log.info(f"Evaluating week: {ws} → {we} (weeks_ago={args.weeks})")
            run_eval(ws, we, args.dry_run, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
