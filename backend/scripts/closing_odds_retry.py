#!/usr/bin/env python3
"""
closing_odds_retry.py
======================
每 30 分钟运行：补抓近 6h 内赛后比赛的 closing 赔率（兜底 closing_odds_watcher T-10min 窗口的漏网）。
NowGoal 保留赛后 24-72h 历史快照，赛后 6h 内成功率接近 100%。

pm2 cron: '*/30 * * * *'
"""

import os
import sys
import time
import sqlite3
import logging
from datetime import datetime, timedelta, timezone

from ingest_failure_helper import record_failure

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def retry_closing_odds() -> None:
    from titan_odds_spider import fetch_single_match_odds
    from silver_builder import ingest_nowgoal_odds_from_dict

    conn = sqlite3.connect(DB_PATH)

    # dim_match 没有 kickoff_time 列，改用 report_store.match_time 获取开球时间。
    # 近 6h 内 kickoff 的已完赛比赛，且 silver_match_odds 无 closing 行。
    rows = conn.execute("""
        SELECT d.Match_ID, d.Date, d.Home_Team_Name, d.Away_Team_Name
        FROM dim_match d
        JOIN report_store rs ON CAST(rs.match_id AS TEXT) = CAST(d.Match_ID AS TEXT)
        WHERE d.status = 'Finish'
          AND rs.match_time IS NOT NULL
          AND rs.match_time <= datetime('now', '-15 minutes')
          AND rs.match_time >= datetime('now', '-6 hours')
          AND NOT EXISTS (
              SELECT 1 FROM silver_match_odds s
              WHERE s.match_id = d.Match_ID AND s.period = 'closing'
          )
        ORDER BY rs.match_time DESC
    """).fetchall()

    if not rows:
        log.info("✅ 无需补抓 closing 赔率（近 6h 比赛均已覆盖）")
        conn.close()
        return

    log.info(f"🔄 发现 {len(rows)} 场比赛需要补抓 closing 赔率")
    success = 0

    for match_id, date_str, home_en, away_en in rows:
        log.info(f"  [{date_str}] {home_en} vs {away_en} (id={match_id})")
        try:
            odds_data = fetch_single_match_odds(
                fotmob_id=str(match_id),
                match_date=date_str,
                home_en=home_en,
                away_en=away_en,
            )
            if odds_data:
                n = ingest_nowgoal_odds_from_dict(
                    conn=conn,
                    fotmob_id=str(match_id),
                    odds_data=odds_data,
                    match_date=date_str,
                )
                log.info(f"  ✅ {home_en} vs {away_en} → written {n} rows")
                success += 1
            else:
                log.warning(f"  ⚠️  NowGoal 返回空数据")
                record_failure("closing_odds_retry", match_id=match_id, step="fetch", error_msg="NowGoal empty")
        except Exception as e:
            log.error(f"  ❌ {home_en} vs {away_en}: {e}")
            record_failure("closing_odds_retry", match_id=match_id, step="fetch", error_msg=f"{home_en} vs {away_en}: {e}")
        time.sleep(0.8)

    conn.close()
    log.info(f"🏁 closing retry 完成: {success}/{len(rows)} 成功")


if __name__ == "__main__":
    retry_closing_odds()
