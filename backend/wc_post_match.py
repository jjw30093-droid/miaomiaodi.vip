"""
wc_post_match.py
================
世界杯赛后结算脚本。

Phase 1：手动跑（比赛结束后）
Phase 2：赛后 cron

用法：
  python backend/wc_post_match.py                        # 扫描所有 finished 但未结算的
  python backend/wc_post_match.py --match-id wc_19609127 # 指定单场
  python backend/wc_post_match.py --dry-run              # 仅打印，不写库

逻辑：
  1. 读 wc_fixtures.home_score / away_score（与 wc_prediction_audit 同库，无 ATTACH）
  2. [REUSE-IMPORT] compute_picked_correct 判命中
  3. UPDATE wc_prediction_audit: actual_home_score, actual_away_score, actual_wdl, picked_correct, audit_time
  4. UPDATE wc_reports: match_status='finished'

WC ROI（独立函数，读 wc_prediction_audit；联赛 ROI 零改动）
"""

import argparse
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = os.environ.get(
    "PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
WC_DB_PATH = os.environ.get("WC_DB_PATH", os.path.join(PROJECT_ROOT, "worldcup.db"))

# [REUSE-IMPORT] 共享结算原语（不修改 pick_parser.py）
from pick_parser import compute_picked_correct  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# 结算单场
# ──────────────────────────────────────────────────────────────────────────────

def _actual_wdl(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "home_win"
    if home_score < away_score:
        return "away_win"
    return "draw"


def settle_match(
    conn: sqlite3.Connection,
    match_id: str,
    dry_run: bool = False,
) -> Optional[dict]:
    """
    结算单场。
    返回结算结果 dict，或 None 如果数据不足。
    """
    # 读 wc_prediction_audit（推荐数据）
    audit_row = conn.execute(
        "SELECT * FROM wc_prediction_audit WHERE match_id=?", (match_id,)
    ).fetchone()
    if not audit_row:
        log.warning(f"[wc_post_match] {match_id} not in wc_prediction_audit, skipping")
        return None

    audit = dict(audit_row)
    if audit.get("picked_correct") is not None:
        log.info(f"[wc_post_match] {match_id} already settled (picked_correct={audit['picked_correct']})")
        return audit

    # 读比分（wc_fixtures 同库，无 ATTACH）
    fixture_row = conn.execute("""
        SELECT f.home_score, f.away_score
        FROM   wc_fixtures f
        JOIN   wc_reports  r ON r.fixture_sportmonks_id = f.sportmonks_id
        WHERE  r.match_id = ?
    """, (match_id,)).fetchone()

    if not fixture_row:
        log.warning(f"[wc_post_match] {match_id} — wc_fixtures row not found")
        return None

    hs = fixture_row[0]
    as_ = fixture_row[1]
    if hs is None or as_ is None:
        log.info(f"[wc_post_match] {match_id} — scores not available yet (hs={hs} as={as_})")
        return None

    actual_wdl = _actual_wdl(hs, as_)
    picked_correct = compute_picked_correct(
        picked_market    = audit.get("picked_market"),
        picked_direction = audit.get("picked_direction"),
        hs               = hs,
        as_              = as_,
        ah_line          = None,   # WC 不使用 AH 推荐
        ou_line          = None,   # WC 不使用 OU 推荐
    )
    audit_time = datetime.now(timezone.utc).isoformat()

    result = {
        "match_id":          match_id,
        "actual_home_score": hs,
        "actual_away_score": as_,
        "actual_wdl":        actual_wdl,
        "picked_correct":    picked_correct,
        "audit_time":        audit_time,
    }

    outcome_str = {1: "✅ 命中", 0: "❌ 未中", -1: "↩️ 走水", None: "⚠️ 无法结算"}
    log.info(
        f"[wc_post_match] {match_id} {hs}-{as_} ({actual_wdl}) "
        f"picked={audit.get('picked_direction')} → {outcome_str.get(picked_correct)}"
    )

    if dry_run:
        log.info(f"  [DRY-RUN] would write: {result}")
        return result

    conn.execute("""
        UPDATE wc_prediction_audit
        SET    actual_home_score=?, actual_away_score=?, actual_wdl=?,
               picked_correct=?, audit_time=?
        WHERE  match_id=?
    """, (hs, as_, actual_wdl, picked_correct, audit_time, match_id))

    # 同步更新 wc_reports.match_status
    conn.execute(
        "UPDATE wc_reports SET match_status='finished', updated_at=? WHERE match_id=?",
        (audit_time, match_id)
    )
    conn.commit()

    return result


# ──────────────────────────────────────────────────────────────────────────────
# 批量扫描
# ──────────────────────────────────────────────────────────────────────────────

def _find_unsettled(conn: sqlite3.Connection) -> list[str]:
    """
    返回 wc_prediction_audit 中 picked_correct IS NULL 且 wc_fixtures 已有比分的 match_id 列表。
    """
    rows = conn.execute("""
        SELECT a.match_id
        FROM   wc_prediction_audit a
        JOIN   wc_reports r ON r.match_id = a.match_id
        JOIN   wc_fixtures f ON f.sportmonks_id = r.fixture_sportmonks_id
        WHERE  a.picked_correct IS NULL
          AND  f.home_score IS NOT NULL
          AND  f.away_score IS NOT NULL
    """).fetchall()
    return [r[0] for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# WC ROI（独立，读 wc_prediction_audit；联赛 ROI 零改动）
# ──────────────────────────────────────────────────────────────────────────────

def compute_wc_roi(conn: sqlite3.Connection) -> dict:
    """
    计算 WC 独立 ROI（与联赛物理隔离，公式相同：sum((odds-1)|-1)/n）。
    on-the-fly 计算，不落库（与联赛 compute_single_pick_stats 一致）。

    Returns:
        {'n_total': int, 'n_won': int, 'n_lost': int, 'n_push': int,
         'roi': float|None, 'hit_rate': float|None}
    """
    rows = conn.execute("""
        SELECT picked_correct, picked_odds
        FROM   wc_prediction_audit
        WHERE  picked_correct IS NOT NULL
    """).fetchall()

    n_won, n_lost, n_push = 0, 0, 0
    total_return = 0.0

    for r in rows:
        pc   = r[0]
        odds = r[1] or 2.0  # 默认 2.0 兜底

        if pc == 1:
            n_won  += 1
            total_return += (odds - 1)
        elif pc == 0:
            n_lost += 1
            total_return -= 1.0
        elif pc == -1:
            n_push += 1
            # 走水本金返还，不计入 P/L

    n_settled = n_won + n_lost + n_push
    n_bets    = n_won + n_lost  # 走水不算投注

    roi       = round(total_return / n_bets, 4) if n_bets > 0 else None
    hit_rate  = round(n_won / n_bets * 100, 1)  if n_bets > 0 else None

    return {
        "n_total":   n_settled,
        "n_won":     n_won,
        "n_lost":    n_lost,
        "n_push":    n_push,
        "roi":       roi,
        "hit_rate":  hit_rate,
    }


# ──────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────────────────────────────────────

def run(db_path: str, match_id_override: Optional[str] = None, dry_run: bool = False) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        if match_id_override:
            settle_match(conn, match_id_override, dry_run=dry_run)
        else:
            targets = _find_unsettled(conn)
            if not targets:
                log.info("[wc_post_match] no unsettled matches with scores available")
            for mid in targets:
                settle_match(conn, mid, dry_run=dry_run)

        if not dry_run:
            roi = compute_wc_roi(conn)
            log.info(
                f"[wc_post_match] WC ROI snapshot — "
                f"n={roi['n_total']} won={roi['n_won']} lost={roi['n_lost']} "
                f"push={roi['n_push']} roi={roi['roi']} hit_rate={roi['hit_rate']}%"
            )
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WC post-match settlement")
    parser.add_argument("--db",       default=WC_DB_PATH, help="Path to worldcup.db")
    parser.add_argument("--match-id", default=None,       help="Force a specific wc_ match_id")
    parser.add_argument("--dry-run",  action="store_true", help="Print only, no writes")
    args = parser.parse_args()

    run(args.db, match_id_override=args.match_id, dry_run=args.dry_run)
