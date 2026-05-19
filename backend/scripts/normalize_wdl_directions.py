"""
normalize_wdl_directions.py
============================
一次性数据迁移（CLAUDE.md §18）：

1) 把 prediction_audit.picked_direction 从短形式归一为长形式（仅 WDL 影响）
   - 'home' → 'home_win'
   - 'away' → 'away_win'
   - 'draw' 不变
   AH/OU 已经是 canonical 形式，不动。

2) 对所有 picked_market IS NOT NULL 且 dim_match.status='Finish' 的行，
   用 pick_parser.compute_picked_correct 重算 picked_correct，覆盖任何旧值。
   特别修复 audit 早于 picks 写入的"漏算"场次。

幂等：UPDATE WHERE 短形式 跑两次第二次匹配 0 行；picked_correct 重算用同样输入产同样结果。

用法：
    python3 scripts/normalize_wdl_directions.py
    python3 scripts/normalize_wdl_directions.py --dry-run
"""

import os
import sys
import sqlite3
import argparse
import logging
from collections import Counter

PROJECT_ROOT = os.environ.get(
    "PROJECT_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
sys.path.insert(0, PROJECT_ROOT)

from pick_parser import compute_picked_correct

DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # ── Step 1: 短形式 → 长形式（仅 WDL）──
    pre = dict(conn.execute("""
        SELECT picked_direction, COUNT(*) FROM prediction_audit
        WHERE picked_market='wdl' GROUP BY picked_direction
    """).fetchall())
    log.info(f"WDL picked_direction 分布（迁移前）: {dict(pre)}")

    n_home = conn.execute(
        "SELECT COUNT(*) FROM prediction_audit WHERE picked_market='wdl' AND picked_direction='home'"
    ).fetchone()[0]
    n_away = conn.execute(
        "SELECT COUNT(*) FROM prediction_audit WHERE picked_market='wdl' AND picked_direction='away'"
    ).fetchone()[0]

    if not args.dry_run:
        conn.execute(
            "UPDATE prediction_audit SET picked_direction='home_win' "
            "WHERE picked_market='wdl' AND picked_direction='home'"
        )
        conn.execute(
            "UPDATE prediction_audit SET picked_direction='away_win' "
            "WHERE picked_market='wdl' AND picked_direction='away'"
        )

    log.info(f"  归一: home → home_win  ({n_home} 行)")
    log.info(f"  归一: away → away_win  ({n_away} 行)")

    # ── Step 2: 全量回算 picked_correct ──
    rows = conn.execute("""
        SELECT pa.match_id, pa.picked_market, pa.picked_direction,
               pa.picked_correct AS old_correct,
               pa.pred_ah_line, pa.pred_ou_line,
               d.home_score, d.away_score, d.status
        FROM prediction_audit pa
        JOIN dim_match d ON CAST(d.Match_ID AS TEXT)=CAST(pa.match_id AS TEXT)
        WHERE pa.picked_market IS NOT NULL
          AND d.status='Finish'
          AND d.home_score IS NOT NULL
    """).fetchall()

    log.info(f"扫描已完赛+有 picks 的行: {len(rows)}")

    transitions = Counter()
    for r in rows:
        new_correct = compute_picked_correct(
            r["picked_market"], r["picked_direction"],
            r["home_score"], r["away_score"],
            r["pred_ah_line"], r["pred_ou_line"],
        )
        old = r["old_correct"]
        transitions[(old, new_correct)] += 1
        if old != new_correct and not args.dry_run:
            conn.execute(
                "UPDATE prediction_audit SET picked_correct=? WHERE match_id=?",
                (new_correct, r["match_id"]),
            )

    if not args.dry_run:
        conn.commit()
    conn.close()

    log.info("=" * 60)
    log.info("picked_correct 变化统计 (old → new):")
    for (old, new), n in sorted(transitions.items(), key=lambda x: -x[1]):
        marker = "  " if old == new else " *"
        log.info(f"{marker} {str(old):>5} → {str(new):>5} : {n}")
    log.info("=" * 60)
    if args.dry_run:
        log.info("[DRY-RUN] 未写库")
    return 0


if __name__ == "__main__":
    sys.exit(main())
