"""
repair_weekend_2026_04_25.py — 一次性补救脚本（CLAUDE.md §17 事故 #5/#6）

背景：
- 4/24 04:00 UTC fotmob_scheduler 静默漏 BIG_FIVE 9 场大赛 → report_store 0 行
- 4/26 夜场 audit 漏跑（cron 顺序错乱）→ prediction_audit.actual_wdl=NULL

执行步骤（idempotent，默认 --dry-run）：
1. 扫描 4/25-4/27 BIG_FIVE 在 dim_match 但 report_store 缺失的场次 → 记入
   ingest_failure_log（step='lost_pre_match_report'），无法事后伪造 LLM 研报
2. 扫描 4/25-4/27 已完赛但 prediction_audit.actual_wdl=NULL 的场次 → 调用
   review_engine.audit_match() 补算
3. 输出统计

用法：
    python3 scripts/repair_weekend_2026_04_25.py            # dry-run（默认）
    python3 scripts/repair_weekend_2026_04_25.py --apply    # 实际写库
"""

import os
import sys
import argparse
import sqlite3
import logging

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from review_engine import ReviewEngine
from scripts.ingest_failure_helper import record_failure

DB_PATH   = os.path.join(PROJECT_ROOT, "football_uk.db")
MODEL_DIR = os.path.join(PROJECT_ROOT, "models_v4")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

WEEKEND_DATES = ("2026-04-25", "2026-04-26", "2026-04-27")
BIG_FIVE = [47, 87, 54, 55, 53]


def find_missing_reports(conn: sqlite3.Connection):
    rows = conn.execute(f"""
        SELECT d.Match_ID, d.League_ID, d.Home_Team_Name, d.Away_Team_Name,
               d.status, d.home_score, d.away_score, d.Date
        FROM dim_match d
        LEFT JOIN report_store rs ON CAST(rs.match_id AS TEXT) = CAST(d.Match_ID AS TEXT)
        WHERE d.Date IN ({','.join('?'*len(WEEKEND_DATES))})
          AND d.League_ID IN ({','.join('?'*len(BIG_FIVE))})
          AND rs.match_id IS NULL
        ORDER BY d.Date, d.League_ID
    """, (*WEEKEND_DATES, *BIG_FIVE)).fetchall()
    return rows


def find_missing_audits(conn: sqlite3.Connection):
    rows = conn.execute(f"""
        SELECT pa.match_id, pa.match_date, d.home_score, d.away_score
        FROM prediction_audit pa
        JOIN dim_match d ON CAST(d.Match_ID AS TEXT) = CAST(pa.match_id AS TEXT)
        WHERE d.status='Finish' AND d.home_score IS NOT NULL
          AND pa.actual_wdl IS NULL
          AND pa.match_date IN ({','.join('?'*len(WEEKEND_DATES))})
        ORDER BY pa.match_date
    """, WEEKEND_DATES).fetchall()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="实际写库（默认 dry-run）")
    args = ap.parse_args()
    apply_mode = args.apply
    label = "APPLY" if apply_mode else "DRY-RUN"
    log.info(f"=== repair_weekend_2026_04_25 [{label}] ===")

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row

    # ── 1. 漏报研报 ────────────────────────────────────────────────────────
    missing_reports = find_missing_reports(conn)
    log.info(f"\n📋 BIG_FIVE 漏报研报（dim_match 有 / report_store 无）：{len(missing_reports)} 场")
    for r in missing_reports:
        log.info(f"  ✗ {r['Date']} [L{r['League_ID']}] {r['Home_Team_Name']} vs {r['Away_Team_Name']}"
                 f" → {r['home_score']}:{r['away_score']} ({r['status']})")

    if apply_mode and missing_reports:
        for r in missing_reports:
            record_failure(
                script_name="repair_weekend_2026_04_25",
                match_id=str(r["Match_ID"]),
                step="lost_pre_match_report",
                error_msg=(f"BIG_FIVE 漏报：{r['Date']} L{r['League_ID']} "
                           f"{r['Home_Team_Name']} vs {r['Away_Team_Name']} | "
                           f"final={r['home_score']}:{r['away_score']} | "
                           f"根因 fotmob_scheduler 4/24 漏抓"),
            )
        log.info(f"  ✅ 已记入 ingest_failure_log（无法事后伪造研报）")

    # ── 2. 漏 audit ────────────────────────────────────────────────────────
    missing_audits = find_missing_audits(conn)
    log.info(f"\n📋 已完赛但 actual_wdl=NULL：{len(missing_audits)} 场")
    for r in missing_audits[:30]:
        log.info(f"  ✗ mid={r['match_id']} date={r['match_date']} "
                 f"score={r['home_score']}:{r['away_score']}")

    fixed_audit = 0
    if apply_mode and missing_audits:
        review = ReviewEngine(DB_PATH, model_dir=MODEL_DIR)
        for r in missing_audits:
            mid = str(r["match_id"])
            try:
                review.audit_match(mid)
                fixed_audit += 1
            except Exception as e:
                log.error(f"  ✗ audit_match({mid}) 失败：{e}")
                record_failure("repair_weekend_2026_04_25", match_id=mid,
                               step="audit_retry_failed", error_msg=str(e))

    # ── 3. 总结 ────────────────────────────────────────────────────────────
    log.info("\n" + "=" * 60)
    log.info(f"📊 SUMMARY ({label})")
    log.info(f"  漏报研报          : {len(missing_reports)} 场（已记 ingest_failure_log）")
    log.info(f"  漏 audit          : {len(missing_audits)} 场 → 补算 {fixed_audit} 场")
    log.info("=" * 60)
    if not apply_mode:
        log.info("ℹ️  这是 dry-run，未写库。如需执行：加 --apply")

    conn.close()


if __name__ == "__main__":
    main()
