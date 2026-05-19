#!/usr/bin/env python3
"""
backfill_recent_odds.py
=======================
一次性回补近 N 天 (默认 14 天) 已完赛但 silver_match_odds 中无记录的比赛赔率。
通过 NowGoal API (titan_odds_spider.fetch_single_match_odds) 逐场抓取。

用法:
    python3 scripts/backfill_recent_odds.py            # 回补近 14 天
    python3 scripts/backfill_recent_odds.py --days 30  # 回补近 30 天
    python3 scripts/backfill_recent_odds.py --dry-run  # 只打印不写入

注意: NowGoal 保留赛后 24-72h 历史快照，超过 3 天的比赛成功率下降。
"""

import os
import sys
import time
import sqlite3
import argparse
import logging
from datetime import datetime, timedelta

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def backfill(days: int = 14, dry_run: bool = False) -> None:
    from titan_odds_spider import fetch_single_match_odds
    from silver_builder import ingest_nowgoal_odds_from_dict

    conn = sqlite3.connect(DB_PATH)
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    rows = conn.execute("""
        SELECT d.Match_ID, d.Date, d.Home_Team_Name, d.Away_Team_Name, d.League_ID
        FROM dim_match d
        WHERE d.status = 'Finish'
          AND d.Date >= ?
          AND NOT EXISTS (
              SELECT 1 FROM silver_match_odds s WHERE s.match_id = d.Match_ID
          )
        ORDER BY d.Date DESC
    """, (since,)).fetchall()

    log.info(f"🔍 发现 {len(rows)} 场 Finish 比赛在近 {days} 天内缺少 silver_match_odds")

    success = 0
    failed = 0
    no_data = 0

    for match_id, date_str, home_en, away_en, league_id in rows:
        log.info(f"  [{date_str}] {home_en} vs {away_en} (id={match_id})")
        if dry_run:
            log.info("  [dry-run] 跳过")
            continue

        try:
            odds_data = fetch_single_match_odds(
                fotmob_id=str(match_id),
                match_date=date_str,
                home_en=home_en,
                away_en=away_en,
            )
            if not odds_data:
                log.warning(f"  ⚠️  NowGoal 无数据（可能超过保留窗口）")
                no_data += 1
            else:
                n = ingest_nowgoal_odds_from_dict(
                    conn=conn,
                    fotmob_id=str(match_id),
                    odds_data=odds_data,
                    match_date=date_str,
                )
                log.info(f"  ✅ 写入 {n} 行")
                success += 1
        except Exception as e:
            log.error(f"  ❌ 失败: {e}")
            failed += 1

        time.sleep(1.0)  # 礼貌性间隔

    conn.close()
    log.info(f"\n🏁 回补完成 → 成功 {success} / 无数据 {no_data} / 失败 {failed} (共 {len(rows)} 场)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    backfill(days=args.days, dry_run=args.dry_run)
