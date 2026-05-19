#!/usr/bin/env python3
"""
closing_odds_watcher.py
=======================
Phase 2.5 — 常驻进程：赛前 T-10min 抓取 NowGoal 闭盘赔率并写入 silver_match_odds。

运行逻辑：
  每 60 秒扫描一次 schedule/target_matches.json，
  找出开球时间在 [now+8min, now+12min] 之间的比赛，
  调用 titan_odds_spider.fetch_single_match_odds() 抓取赔率，
  通过 silver_builder.ingest_nowgoal_odds_from_dict() 写入 silver_match_odds。

部署：
  PM2 常驻进程（autorestart: true），日志写到 logs/closing_odds_watcher.log。
"""

import os
import sys
import json
import time
import sqlite3
import logging
from datetime import datetime, timedelta

from scripts.ingest_failure_helper import record_failure

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
DB_PATH      = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))
SCHEDULE_FILE = os.path.join(PROJECT_ROOT, "schedule", "target_matches.json")
LOG_DIR       = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [closing_watcher] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "closing_odds_watcher.log")),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("closing_watcher")

# ── 扫描窗口：开球前 8~12 分钟 ────────────────────────────────────────────
WINDOW_EARLY_MIN = 8
WINDOW_LATE_MIN  = 12
SCAN_INTERVAL_S  = 60  # 每 60 秒扫描一次


def load_schedule() -> list:
    """读取 target_matches.json，失败返回空列表（不崩溃）。"""
    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.debug(f"读取赛程失败（可能今日尚未生成）: {e}")
        return []


def already_captured(conn: sqlite3.Connection, match_id: int) -> bool:
    """检查 silver_match_odds 中是否已有该比赛的 nowgoal closing 1x2 记录。"""
    row = conn.execute(
        "SELECT 1 FROM silver_match_odds "
        "WHERE match_id=? AND market='1x2' AND period='closing' AND source='nowgoal' LIMIT 1",
        (match_id,)
    ).fetchone()
    return row is not None


def scan_upcoming_matches(conn: sqlite3.Connection) -> list:
    """
    返回 kickoff_time ∈ [now+WINDOW_EARLY_MIN, now+WINDOW_LATE_MIN] 且
    尚未在 silver_match_odds 中有 nowgoal closing 记录的场次列表。
    """
    now = datetime.now()  # server is configured in UTC timezone
    window_start = now + timedelta(minutes=WINDOW_EARLY_MIN)
    window_end   = now + timedelta(minutes=WINDOW_LATE_MIN)

    matches = load_schedule()
    results = []
    for m in matches:
        ks = m.get("kickoff_time", "")
        if not ks:
            continue
        try:
            kt = datetime.strptime(ks, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if window_start <= kt <= window_end:
            mid = m.get("match_id")
            if mid and not already_captured(conn, int(mid)):
                results.append(m)
    return results


def capture_and_persist(conn: sqlite3.Connection, match: dict) -> bool:
    """
    抓取单场比赛的赔率并写入 silver_match_odds。
    返回 True=成功，False=失败（不抛异常）。
    """
    from titan_odds_spider import fetch_single_match_odds
    from silver_builder   import ingest_nowgoal_odds_from_dict, ensure_odds_tables

    mid        = match["match_id"]
    match_date = match.get("date", match.get("kickoff_time", "")[:10])
    try:
        parts = match.get("match_name", "").split(" vs ")
        home_en = parts[0].strip()
        away_en = parts[1].strip()
    except (IndexError, AttributeError):
        log.warning(f"[{mid}] match_name 格式错误: {match.get('match_name')}")
        return False

    log.info(f"[{mid}] T-10min 抓取: {home_en} vs {away_en} (开球: {match.get('kickoff_time')})")

    try:
        odds_data = fetch_single_match_odds(mid, match_date, home_en, away_en)
    except Exception as e:
        log.warning(f"[{mid}] fetch_single_match_odds 异常: {e}")
        record_failure("closing_odds_watcher", match_id=mid, step="fetch", error_msg=str(e))
        return False

    if not odds_data:
        log.warning(f"[{mid}] 未获取到赔率（NowGoal 未找到或未开盘）")
        record_failure("closing_odds_watcher", match_id=mid, step="fetch", error_msg="NowGoal empty or unmapped")
        return False

    try:
        ensure_odds_tables(conn)
        cnt = ingest_nowgoal_odds_from_dict(conn, str(mid), odds_data, match_date)
        log.info(f"[{mid}] ✅ closing 赔率写入 {cnt} 行 → silver_match_odds")
        return cnt > 0
    except Exception as e:
        log.warning(f"[{mid}] ingest_nowgoal_odds_from_dict 异常: {e}")
        record_failure("closing_odds_watcher", match_id=mid, step="insert", error_msg=str(e))
        return False


def main_loop():
    """主循环：每 SCAN_INTERVAL_S 秒扫描一次，异常不崩溃。"""
    log.info(f"🚀 closing_odds_watcher 启动 (窗口={WINDOW_EARLY_MIN}~{WINDOW_LATE_MIN}min, 间隔={SCAN_INTERVAL_S}s)")
    log.info(f"   DB={DB_PATH}  SCHEDULE={SCHEDULE_FILE}")

    while True:
        try:
            conn = sqlite3.connect(DB_PATH)
            matches = scan_upcoming_matches(conn)

            if matches:
                log.info(f"🎯 发现 {len(matches)} 场即将开球（T-10min）:")
                for m in matches:
                    log.info(f"   - [{m['match_id']}] {m.get('match_name')} @ {m.get('kickoff_time')}")
                    capture_and_persist(conn, m)
            else:
                log.debug("暂无 T-10min 比赛，等待下次扫描...")

            conn.close()
        except Exception as e:
            log.error(f"扫描异常（继续运行）: {e}", exc_info=True)
            record_failure("closing_odds_watcher", match_id=None, step="fetch", error_msg=f"scan loop: {e}")
            try:
                conn.close()
            except Exception:
                pass

        time.sleep(SCAN_INTERVAL_S)


if __name__ == "__main__":
    main_loop()
