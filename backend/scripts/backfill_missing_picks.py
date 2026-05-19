"""
backfill_missing_picks.py
=========================
一次性回填脚本：扫描历史 prediction_audit 行，对 picked_market IS NULL 但
report_store.inference 已存在的场次，用 pick_parser 反解并写入 picks，
对已完赛的场次额外重算 picked_correct。

幂等：带 `WHERE picked_market IS NULL` 守卫，不会覆盖已正确的行。

用法：
    python3 scripts/backfill_missing_picks.py
    python3 scripts/backfill_missing_picks.py --dry-run   # 仅预览，不写库
"""

import os
import sys
import sqlite3
import argparse
import logging
from collections import defaultdict

PROJECT_ROOT = os.environ.get(
    "PROJECT_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
sys.path.insert(0, PROJECT_ROOT)

from pick_parser import parse_inference, compute_picked_correct

DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# compute_picked_correct 已抽到 pick_parser.py（CLAUDE.md §18，双形式容错）


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="仅预览，不写库")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 1) 找所有候选行：picked_market IS NULL AND inference 非空
    rows = conn.execute("""
        SELECT
            pa.match_id,
            pa.match_date,
            pa.home_name,
            pa.away_name,
            pa.pred_ah_line,
            pa.pred_ou_line,
            pa.picked_correct,
            rs.inference,
            dm.home_score,
            dm.away_score,
            dm.status
        FROM prediction_audit pa
        JOIN report_store rs ON CAST(rs.match_id AS TEXT) = CAST(pa.match_id AS TEXT)
        LEFT JOIN dim_match dm ON CAST(dm.Match_ID AS TEXT) = CAST(pa.match_id AS TEXT)
        WHERE pa.picked_market IS NULL
          AND rs.inference IS NOT NULL
          AND TRIM(rs.inference) != ''
        ORDER BY pa.match_date
    """).fetchall()

    log.info(f"发现 {len(rows)} 行 picked_market=NULL 且 inference 已存在")

    by_month = defaultdict(int)
    parse_failed = 0
    picks_written = 0
    correct_recomputed = 0

    for r in rows:
        mid = r["match_id"]
        inf = r["inference"]
        parsed = parse_inference(inf)
        if not parsed:
            parse_failed += 1
            log.warning(f"  ❌ 无法解析 mid={mid}: {inf[:60]}")
            continue

        market    = parsed["market"]
        direction = parsed["direction"]
        odds      = parsed.get("odds")
        conf      = parsed.get("confidence")

        # 已完赛 → 顺便算 picked_correct
        picked_correct = None
        if r["status"] == "Finish" and r["home_score"] is not None:
            picked_correct = compute_picked_correct(
                market, direction, r["home_score"], r["away_score"],
                r["pred_ah_line"], r["pred_ou_line"]
            )

        if not args.dry_run:
            conn.execute("""
                UPDATE prediction_audit SET
                    picked_market    = ?,
                    picked_direction = ?,
                    picked_odds      = ?,
                    picked_confidence= ?,
                    picked_correct   = COALESCE(picked_correct, ?)
                WHERE match_id = ? AND picked_market IS NULL
            """, (market, direction, odds, conf, picked_correct, mid))

        picks_written += 1
        if picked_correct is not None:
            correct_recomputed += 1
        month_key = (r["match_date"] or "?")[:7]
        by_month[month_key] += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    log.info("="*60)
    log.info(f"扫描行数:        {len(rows)}")
    log.info(f"解析失败:        {parse_failed}")
    log.info(f"已写入 picks:    {picks_written}{'  [DRY-RUN]' if args.dry_run else ''}")
    log.info(f"已算 picked_correct: {correct_recomputed}")
    log.info("按月份分布:")
    for m in sorted(by_month):
        log.info(f"  {m}: {by_month[m]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
