"""
review_models.py — 赛后复盘数据模型

使用 Python dataclass（而非 SQLAlchemy），与项目其他模块保持原生
sqlite3 风格一致。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Domain data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PendingReview:
    """
    从 report_store 中读取的待复盘比赛记录。
    仅包含复盘服务所需的字段，避免把整张宽表传来传去。
    """
    match_id:    str
    home_team:   str
    away_team:   str
    league:      str
    match_time:  str
    inference:   str | None        # 赛前 AI 推演结论（核心 Prompt 素材）
    home_prob:   float | None
    away_prob:   float | None
    draw_prob:   float | None


@dataclass
class ActualMatchData:
    """
    外部爬虫/数据源拉取的赛后真实数据。
    post_match_shots 存储可以直接序列化为 JSON 的 Python 对象。
    """
    match_id:          str
    home_score:        int
    away_score:        int
    home_npxg:         float
    away_npxg:         float
    home_possession:   float          # 主队控球率 %
    away_possession:   float
    home_shots_total:  int
    away_shots_total:  int
    post_match_shots:  dict[str, Any]  # {homeTeam: [...], awayTeam: [...]}


# ─────────────────────────────────────────────────────────────────────────────
# DB access helpers（保持与项目其他路由相同的裸 sqlite3 风格）
# ─────────────────────────────────────────────────────────────────────────────

def get_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_pending_reviews(db_path: str) -> list[PendingReview]:
    """
    查询所有 match_status='finished' 且 post_match_review IS NULL 的比赛。
    这些是需要触发 AI 复盘的记录。
    """
    conn = get_db(db_path)
    try:
        rows = conn.execute("""
            SELECT match_id, home_team, away_team, league, match_time,
                   inference, home_prob, away_prob, draw_prob
            FROM report_store
            WHERE match_status = 'finished'
              AND post_match_review IS NULL
              AND home_team != 'Home'
              AND away_team != 'Away'
            ORDER BY match_time DESC
        """).fetchall()

        return [
            PendingReview(
                match_id   = r["match_id"],
                home_team  = r["home_team"],
                away_team  = r["away_team"],
                league     = r["league"] or "",
                match_time = r["match_time"] or "",
                inference  = r["inference"],
                home_prob  = r["home_prob"],
                away_prob  = r["away_prob"],
                draw_prob  = r["draw_prob"],
            )
            for r in rows
        ]
    finally:
        conn.close()


def write_review_result(
    db_path:           str,
    match_id:          str,
    post_match_shots:  dict[str, Any],
    post_match_review: str,
) -> None:
    """
    将 AI 复盘结果回写到 report_store。
    使用独占事务保证原子性；失败时自动 rollback。
    """
    conn = get_db(db_path)
    try:
        conn.execute("BEGIN EXCLUSIVE TRANSACTION")
        conn.execute("""
            UPDATE report_store
            SET post_match_shots  = ?,
                post_match_review = ?
            WHERE match_id = ?
        """, (
            json.dumps(post_match_shots, ensure_ascii=False),
            post_match_review,
            match_id,
        ))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_match_finished(db_path: str, match_id: str) -> None:
    """手动将某场比赛标记为 'finished'（供 Admin 或测试脚本调用）。"""
    conn = get_db(db_path)
    try:
        conn.execute(
            "UPDATE report_store SET match_status = 'finished' WHERE match_id = ?",
            (match_id,)
        )
        conn.commit()
    finally:
        conn.close()
