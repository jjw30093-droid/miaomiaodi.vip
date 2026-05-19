#!/usr/bin/env python3
"""
scripts/pipeline_healthcheck.py
================================
每日 Pipeline 健康 watchdog — 05:30 UTC (13:30 CST)

检查项（任意失败 → Server 酱推送 + record_failure）：
  1. target_matches.json mtime 在 24h 内（scheduler 是否跑过）
  2. 当日 dim_match 有 ≥1 条新记录（batch-sync 是否写入）
  3. 当日 report_store 有 ≥1 条 version='v3' 研报（run_tonight 是否输出）
  4. ingest_failure_log 24h 内 P0 step 数为 0

PM2 cron: 30 5 * * *（05:30 UTC）
CLAUDE.md refs:
    §19 target_matches 覆盖不变量
    §23 run_tonight 二次闸门告警
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))
SCHEDULE_DIR = os.path.join(PROJECT_ROOT, "schedule")
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

P0_STEPS = frozenset({
    "sanity_check", "target_coverage_gap", "league_coverage_regression",
    "weekend_prefetch", "drift_auto_recalibrate",
})


def _check_target_matches_fresh() -> tuple[bool, str]:
    json_path = os.path.join(SCHEDULE_DIR, "target_matches.json")
    if not os.path.exists(json_path):
        return False, "target_matches.json 不存在"
    mtime = datetime.fromtimestamp(os.path.getmtime(json_path), tz=timezone.utc)
    age_h = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
    if age_h > 26:
        return False, f"target_matches.json 超过 {age_h:.1f}h 未更新（scheduler 可能未跑）"
    return True, f"target_matches.json 正常（{age_h:.1f}h 前更新）"


def _check_dim_match_today() -> tuple[bool, str]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        row = conn.execute(
            "SELECT COUNT(*) FROM dim_match WHERE Date = ?", (today,)
        ).fetchone()
        conn.close()
        cnt = row[0] if row else 0
        if cnt == 0:
            return False, f"dim_match 当日({today})无记录（batch-sync 未写入？）"
        return True, f"dim_match 当日 {cnt} 条"
    except Exception as e:
        return False, f"dim_match 查询失败: {e}"


def _check_report_store_today() -> tuple[bool, str]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        row = conn.execute(
            "SELECT COUNT(*) FROM report_store WHERE match_time LIKE ? AND version='v3'",
            (f"{today}%",)
        ).fetchone()
        conn.close()
        cnt = row[0] if row else 0
        if cnt == 0:
            return False, f"report_store 当日({today})无 v3 研报（run_tonight 未输出？）"
        return True, f"report_store 当日 {cnt} 篇 v3 研报"
    except Exception as e:
        return False, f"report_store 查询失败: {e}"


def _check_no_p0_failures_24h() -> tuple[bool, str]:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        placeholders = ",".join("?" * len(P0_STEPS))
        row = conn.execute(
            f"SELECT COUNT(*) FROM ingest_failure_log WHERE step IN ({placeholders}) AND created_at >= ?",
            (*P0_STEPS, since)
        ).fetchone()
        conn.close()
        cnt = row[0] if row else 0
        if cnt > 0:
            return False, f"过去 24h 有 {cnt} 条 P0 failure 记录"
        return True, "过去 24h 无 P0 failure"
    except Exception as e:
        return False, f"ingest_failure_log 查询失败: {e}"


def main():
    log.info("=" * 50)
    log.info("🔍 Pipeline Healthcheck 开始")
    log.info("=" * 50)

    checks = [
        ("target_matches_fresh", _check_target_matches_fresh),
        ("dim_match_today",      _check_dim_match_today),
        ("report_store_today",   _check_report_store_today),
        ("no_p0_failures_24h",   _check_no_p0_failures_24h),
    ]

    failures: list[str] = []
    for name, fn in checks:
        ok, msg = fn()
        if ok:
            log.info(f"  ✅ {name}: {msg}")
        else:
            log.error(f"  ❌ {name}: {msg}")
            failures.append(f"**{name}**: {msg}")

    if failures:
        summary = "\n".join(failures)
        log.error(f"❌ Healthcheck 发现 {len(failures)} 项异常，推送告警")
        try:
            from scripts.ingest_failure_helper import record_failure
            record_failure(
                "pipeline_healthcheck",
                step="pipeline_healthcheck",
                error_msg=f"{len(failures)} 项异常: " + " | ".join(f.replace("**", "") for f in failures),
            )
        except Exception as e:
            log.error(f"record_failure 失败: {e}")
        sys.exit(1)
    else:
        log.info("✅ 所有检查通过，Pipeline 健康")
        sys.exit(0)


if __name__ == "__main__":
    main()
