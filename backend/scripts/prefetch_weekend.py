#!/usr/bin/env python3
"""
scripts/prefetch_weekend.py
===========================
远期赛程预抓取 — 仅写 dim_match，不触动 target_matches.json，不触发 V1 研报。

解决问题：fotmob_scheduler 维持 48h 窗口（设计契约），但周中运行时扫描窗口
刚好卡在欧洲赛事荒漠期（周二-周四），无法覆盖下个周末大批赛事。
本脚本补扫未来 N 天（默认 7），将目标联赛的比赛预写入 dim_match，
供前端展示赛程和 run_tonight 备用。

PM2 cron: 03:00 UTC = 11:00 CST（每天，早于 batch-sync）
依赖：fotmob_client.FotMobClient（curl_cffi + ThorData 代理）

CLAUDE.md refs:
    §4  FotMob API 查询日期必须用 CST 生成，入库字段用 UTC
    §15 cron 依赖链：本脚本 03:00，不依赖其他任务
    §19 不变量：prefetch 失败时 record_failure(step='weekend_prefetch')
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

# ── Path setup ──────────────────────────────────────────────────────────────
PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# CST = UTC+8（CLAUDE.md §4：FotMob API 查询日期必须用 CST）
CST = timezone(timedelta(hours=8))

# ── 复用 scheduler 的联赛白名单和写库函数 ──────────────────────────────────
from fotmob_scheduler import (
    TARGET_LIDS_SET,
    BIG_FIVE_LIDS,
    _seed_dim_match,
)


def prefetch(days_ahead: int = 7, dry_run: bool = False) -> int:
    """
    抓取未来 days_ahead 天的目标联赛赛程，INSERT OR IGNORE 进 dim_match。
    返回新增场次数（若 dry_run=True 则只打印不写库）。
    """
    from fotmob_client import FotMobClient
    client = FotMobClient()

    # CLAUDE.md §4：查询日期用 CST
    now_cst = datetime.now(CST)
    dates = [(now_cst + timedelta(days=i)).strftime("%Y%m%d") for i in range(days_ahead)]

    log.info("=" * 60)
    log.info(f"📅 远期赛程预抓取（prefetch_weekend）days={days_ahead} dry_run={dry_run}")
    log.info(f"📆 扫描日期(CST): {dates}")
    log.info("=" * 60)

    matches: list[dict] = []
    seen_ids: set[str] = set()

    for d in dates:
        log.info(f"\n📡 正在抓取 [{d}] 赛程...")
        try:
            data = client.daily_matches(d)
        except Exception as e:
            log.error(f"❌ [{d}] 请求失败: {e}")
            continue

        leagues = data.get("leagues", [])
        log.info(f"   获取到 {len(leagues)} 个联赛")
        matched_this_date = 0

        for league in leagues:
            lid = league.get("primaryId") or league.get("id")
            if lid not in TARGET_LIDS_SET:
                continue

            league_name = league.get("name", "")
            for match in league.get("matches", []):
                status = match.get("status", {})
                if status.get("finished"):
                    continue

                match_id = str(match.get("id", ""))
                if not match_id or match_id in seen_ids:
                    continue

                # 解析 UTC 开球时间（CLAUDE.md §4：入库字段用 UTC）
                utc_time = status.get("utcTime", "")
                try:
                    t = utc_time.replace(".000Z", "Z").replace("Z", "+00:00")
                    kickoff = datetime.fromisoformat(t)
                    kickoff_str = kickoff.strftime("%Y-%m-%d %H:%M:%S")
                    kickoff_date = kickoff_str[:10]
                except Exception:
                    continue

                home = match.get("home", {})
                away = match.get("away", {})

                seen_ids.add(match_id)
                matches.append({
                    "date":         kickoff_date,
                    "match_id":     int(match_id),
                    "match_name":   f"{home.get('name', '')} vs {away.get('name', '')}",
                    "home_id":      home.get("id", 0),
                    "away_id":      away.get("id", 0),
                    "league":       league_name,
                    "league_id":    lid,
                    "kickoff_time": kickoff_str,
                })
                matched_this_date += 1

        by_big5 = {lid: sum(1 for m in matches if m["league_id"] == lid) for lid in BIG_FIVE_LIDS}
        log.info(f"   本日命中目标联赛: {matched_this_date} 场")
        time.sleep(0.5)

    matches.sort(key=lambda x: x["kickoff_time"])

    # 统计
    big5_total = sum(1 for m in matches if m["league_id"] in BIG_FIVE_LIDS)
    by_date: dict[str, int] = {}
    for m in matches:
        by_date[m["date"]] = by_date.get(m["date"], 0) + 1

    log.info(f"\n📊 共发现 {len(matches)} 场目标赛事（BIG_FIVE={big5_total}）")
    for d, cnt in sorted(by_date.items()):
        log.info(f"   {d}: {cnt} 场")

    if dry_run:
        log.info("🔍 dry-run 模式，不写库")
        return 0

    if not matches:
        log.warning("⚠️ 无可写入数据，跳过 dim_match 写入")
        try:
            from scripts.ingest_failure_helper import record_failure
            record_failure("prefetch_weekend", step="weekend_prefetch", error_msg="total_zero")
        except Exception:
            pass
        return 0

    # 写 dim_match（复用 scheduler 的 _seed_dim_match，INSERT OR IGNORE）
    _seed_dim_match(matches)
    return len(matches)


def main():
    parser = argparse.ArgumentParser(description="FotMob 远期赛程预抓取（只写 dim_match）")
    parser.add_argument("--days", type=int, default=7, help="扫描未来天数（默认 7）")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写库")
    args = parser.parse_args()

    try:
        n = prefetch(days_ahead=args.days, dry_run=args.dry_run)
        log.info(f"✅ prefetch_weekend 完成，共处理 {n} 场")
    except Exception as e:
        log.error(f"❌ prefetch_weekend 异常退出: {e}", exc_info=True)
        try:
            from scripts.ingest_failure_helper import record_failure
            record_failure("prefetch_weekend", step="weekend_prefetch", error_msg=str(e)[:500])
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
