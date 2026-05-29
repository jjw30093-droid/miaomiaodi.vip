"""
wc_final_lock.py
================
T-30 闭盘快照 + 研报锁定脚本。

Phase 1：手动跑（赛前 ~30 分钟）
Phase 2：挂 pm2 */5 cron（64 场自动）

用法：
  python backend/wc_final_lock.py                     # 自动扫描 T-30 窗口内的比赛
  python backend/wc_final_lock.py --match-id wc_19609127  # 强制指定
  python backend/wc_final_lock.py --dry-run            # 仅打印，不写库

逻辑：
  1. 找到窗口内（starting_at 距 now 在 27.5–32.5 分钟）的 wc_ 研报
  2. 把当前 wc_odds 快照写入 wc_odds_snapshot（period='closing'）
  3. 用 closing 数据重算 devig_consensus → 更新 wc_reports.payload_json
  4. UPDATE wc_reports SET pipeline_status='FINAL_REPORT_READY'
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = os.environ.get(
    "PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
WC_DB_PATH = os.environ.get("WC_DB_PATH", os.path.join(PROJECT_ROOT, "worldcup.db"))

# 时间窗口常量（镜像 final_lock.py）
WINDOW_LO_MIN = 27.5   # 赛前 27.5 分钟
WINDOW_HI_MIN = 32.5   # 赛前 32.5 分钟


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _find_lock_targets(conn: sqlite3.Connection, window_lo: float, window_hi: float) -> list[dict]:
    """
    查找 starting_at 在 [now+window_lo, now+window_hi] 内且
    pipeline_status 不是 FINAL_REPORT_READY 的 wc_reports。
    """
    now = _now_utc()
    lo  = now + timedelta(minutes=window_lo)
    hi  = now + timedelta(minutes=window_hi)

    rows = conn.execute("""
        SELECT r.match_id, r.fixture_sportmonks_id, r.payload_json, f.starting_at
        FROM   wc_reports r
        JOIN   wc_fixtures f ON f.sportmonks_id = r.fixture_sportmonks_id
        WHERE  r.pipeline_status != 'FINAL_REPORT_READY'
          AND  f.starting_at >= ?
          AND  f.starting_at <= ?
    """, (lo.isoformat(), hi.isoformat())).fetchall()
    return [dict(r) for r in rows]


def _snapshot_wc_odds(
    conn: sqlite3.Connection,
    fixture_id: int,
    snapshot_ts: str,
    dry_run: bool = False,
) -> int:
    """
    把 wc_odds 中该 fixture 的所有当前赔率快照写入 wc_odds_snapshot。
    返回插入行数。
    """
    rows = conn.execute("""
        SELECT fixture_sportmonks_id, market_id, bookmaker_id, label, value, total,
               handicap, probability
        FROM   wc_odds
        WHERE  fixture_sportmonks_id = ?
    """, (fixture_id,)).fetchall()

    if not rows:
        log.warning(f"  [snapshot] no wc_odds rows for fixture={fixture_id}")
        return 0

    if dry_run:
        log.info(f"  [DRY-RUN] would snapshot {len(rows)} rows for fixture={fixture_id}")
        return len(rows)

    conn.executemany("""
        INSERT INTO wc_odds_snapshot
            (fixture_sportmonks_id, market_id, bookmaker_id, label, value, total,
             handicap, probability, period, snapshot_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'closing', ?)
    """, [
        (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], snapshot_ts)
        for r in rows
    ])
    conn.commit()
    log.info(f"  [snapshot] wrote {len(rows)} rows → wc_odds_snapshot fixture={fixture_id}")
    return len(rows)


def _refresh_payload_closing(
    conn: sqlite3.Connection,
    match_id: str,
    fixture_id: int,
    existing_payload_json: str | None,
) -> dict | None:
    """
    用 closing devig 重算 market-implied，更新 payload_json['market_implied']。
    返回更新后的 payload dict，或 None 如果失败。
    """
    try:
        from wc_devig import devig_consensus  # type: ignore
    except ImportError:
        log.warning("  [lock] wc_devig not importable, skipping payload refresh")
        return None

    try:
        devig = devig_consensus(conn, fixture_id, period="closing")
        wdl   = devig.get("wdl_consensus", {})
        ou    = devig.get("ou_consensus", {})
        ah    = devig.get("ah_implied", {})

        if not wdl:
            log.warning(f"  [lock] closing devig returned empty WDL for fixture={fixture_id}")
            return None

        # 解析现有 payload
        payload: dict = {}
        if existing_payload_json:
            try:
                payload = json.loads(existing_payload_json)
            except Exception:
                pass

        # 刷新 market_implied 段
        payload["market_implied"] = {
            "wdl":  wdl,
            "ou":   ou,
            "ah":   ah,
            "period": "closing",
        }
        log.info(f"  [lock] closing devig refreshed: h={wdl.get('home'):.3f} "
                 f"d={wdl.get('draw'):.3f} a={wdl.get('away'):.3f}")
        return payload
    except Exception as e:
        log.error(f"  [lock] closing devig failed: {e}")
        return None


def lock_match(
    conn: sqlite3.Connection,
    match_id: str,
    fixture_id: int,
    existing_payload_json: str | None,
    dry_run: bool = False,
) -> None:
    """
    执行单场锁定：快照 → 刷新 payload → UPDATE pipeline_status。
    """
    snapshot_ts = _now_utc().isoformat()
    log.info(f"[wc_final_lock] locking {match_id} fixture={fixture_id} ts={snapshot_ts}")

    # 1. 快照
    n = _snapshot_wc_odds(conn, fixture_id, snapshot_ts, dry_run=dry_run)
    if n == 0:
        log.warning(f"  [lock] 0 snapshot rows — skipping payload refresh and lock")
        return

    if dry_run:
        log.info(f"  [DRY-RUN] would UPDATE {match_id} → FINAL_REPORT_READY")
        return

    # 2. 刷新 closing payload
    new_payload = _refresh_payload_closing(conn, match_id, fixture_id, existing_payload_json)

    # 3. 锁定状态
    from wc_store import update_wc_report_status  # type: ignore
    update_wc_report_status(
        conn,
        match_id=match_id,
        pipeline_status="FINAL_REPORT_READY",
        payload_json=new_payload,   # None → 不更新 payload_json
    )
    log.info(f"  [lock] {match_id} → FINAL_REPORT_READY ✅")


def run_lock(
    db_path: str,
    match_id_override: str | None = None,
    dry_run: bool = False,
) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        if match_id_override:
            # 强制模式
            fixture_id = None
            if match_id_override.startswith("wc_"):
                try:
                    fixture_id = int(match_id_override[3:])
                except ValueError:
                    pass
            row = conn.execute(
                "SELECT fixture_sportmonks_id, payload_json FROM wc_reports WHERE match_id=?",
                (match_id_override,)
            ).fetchone()
            if not row:
                log.error(f"match_id {match_id_override} not found in wc_reports")
                sys.exit(1)
            lock_match(
                conn,
                match_id=match_id_override,
                fixture_id=row["fixture_sportmonks_id"],
                existing_payload_json=row["payload_json"],
                dry_run=dry_run,
            )
        else:
            targets = _find_lock_targets(conn, WINDOW_LO_MIN, WINDOW_HI_MIN)
            if not targets:
                log.info(f"[wc_final_lock] no matches in T-{WINDOW_LO_MIN:.0f}–{WINDOW_HI_MIN:.0f} window")
                return
            for t in targets:
                lock_match(
                    conn,
                    match_id=t["match_id"],
                    fixture_id=t["fixture_sportmonks_id"],
                    existing_payload_json=t["payload_json"],
                    dry_run=dry_run,
                )
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WC T-30 snapshot + lock")
    parser.add_argument("--db",        default=WC_DB_PATH, help="Path to worldcup.db")
    parser.add_argument("--match-id",  default=None,       help="Force a specific wc_ match_id")
    parser.add_argument("--dry-run",   action="store_true", help="Print only, no writes")
    args = parser.parse_args()

    run_lock(args.db, match_id_override=args.match_id, dry_run=args.dry_run)
