"""
wc_store.py
===========
写 worldcup.db.wc_reports（对标联赛 _sync_report_store，但完全独立）。

用法：
    from wc_store import write_wc_report, read_wc_report
    write_wc_report(conn_wc, match_id='wc_19609127', ...)
    payload = read_wc_report(conn_wc, 'wc_19609127')
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 写入
# ──────────────────────────────────────────────────────────────────────────────

def write_wc_report(
    conn: sqlite3.Connection,
    *,
    match_id: str,
    fixture_sportmonks_id: int,
    report_markdown: str,
    payload_json: dict | str,
    inference: str,
    pipeline_status: str = "DRAFT",
    home_team: str = "",
    away_team: str = "",
    match_time: str = "",
    league: str = "World Cup",
    is_free: int = 0,
    home_prob: Optional[float] = None,
    draw_prob: Optional[float] = None,
    away_prob: Optional[float] = None,
    beginner_summary: Optional[str] = None,
    key_risk: Optional[str] = None,
    key_variables: Optional[list] = None,
    chart_insights: Optional[dict] = None,
    post_match_review: Optional[str] = None,
    match_status: str = "upcoming",
    preview_content: Optional[str] = None,
) -> None:
    """
    INSERT OR REPLACE wc_reports 行。

    pipeline_status:
      'DRAFT'              — 生成完成，未锁定
      'REPORT_READY'       — 备用中间状态
      'FINAL_REPORT_READY' — T-30 锁定后（wc_final_lock.py 设置）
    """
    if not match_id.startswith("wc_"):
        raise ValueError(f"[wc_store] match_id must start with 'wc_', got: {match_id!r}")

    # 序列化复合字段
    if isinstance(payload_json, dict):
        payload_str = json.dumps(payload_json, ensure_ascii=False)
    else:
        payload_str = payload_json  # 已是字符串

    key_vars_str     = json.dumps(key_variables,  ensure_ascii=False) if key_variables  else None
    chart_ins_str    = json.dumps(chart_insights, ensure_ascii=False) if chart_insights else None
    now              = datetime.now(timezone.utc).isoformat()

    sql = """
        INSERT OR REPLACE INTO wc_reports (
            match_id, fixture_sportmonks_id,
            report_markdown, payload_json, inference, pipeline_status,
            home_team, away_team, match_time, league, is_free,
            home_prob, draw_prob, away_prob,
            beginner_summary, key_risk, key_variables, chart_insights,
            post_match_review, match_status, preview_content,
            created_at, updated_at
        ) VALUES (
            ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            COALESCE((SELECT created_at FROM wc_reports WHERE match_id=?), ?),
            ?
        )
    """
    conn.execute(sql, (
        match_id, fixture_sportmonks_id,
        report_markdown, payload_str, inference, pipeline_status,
        home_team, away_team, match_time, league, is_free,
        home_prob, draw_prob, away_prob,
        beginner_summary, key_risk, key_vars_str, chart_ins_str,
        post_match_review, match_status, preview_content,
        match_id, now,   # COALESCE 参数
        now,
    ))
    conn.commit()
    log.info(f"[wc_store] written {match_id} status={pipeline_status}")


def update_wc_report_status(
    conn: sqlite3.Connection,
    match_id: str,
    pipeline_status: str,
    payload_json: dict | str | None = None,
) -> None:
    """
    更新 pipeline_status（供 wc_final_lock.py 使用）。
    可选同时刷新 payload_json（closing devig 后重算）。
    """
    now = datetime.now(timezone.utc).isoformat()
    if payload_json is not None:
        if isinstance(payload_json, dict):
            payload_str = json.dumps(payload_json, ensure_ascii=False)
        else:
            payload_str = payload_json
        conn.execute(
            "UPDATE wc_reports SET pipeline_status=?, payload_json=?, updated_at=? WHERE match_id=?",
            (pipeline_status, payload_str, now, match_id),
        )
    else:
        conn.execute(
            "UPDATE wc_reports SET pipeline_status=?, updated_at=? WHERE match_id=?",
            (pipeline_status, now, match_id),
        )
    conn.commit()
    log.info(f"[wc_store] {match_id} pipeline_status → {pipeline_status}")


def update_wc_report_post_match(
    conn: sqlite3.Connection,
    match_id: str,
    post_match_review: str,
    match_status: str = "finished",
) -> None:
    """赛后写入复盘内容（供赛后脚本使用）。"""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE wc_reports SET post_match_review=?, match_status=?, updated_at=? WHERE match_id=?",
        (post_match_review, match_status, now, match_id),
    )
    conn.commit()
    log.info(f"[wc_store] {match_id} post_match_review written, status={match_status}")


# ──────────────────────────────────────────────────────────────────────────────
# 读取
# ──────────────────────────────────────────────────────────────────────────────

def read_wc_report(conn: sqlite3.Connection, match_id: str) -> Optional[dict]:
    """
    读 wc_reports 行，payload_json 自动反序列化。
    返回 None 如果不存在。
    """
    row = conn.execute(
        "SELECT * FROM wc_reports WHERE match_id=?", (match_id,)
    ).fetchone()
    if row is None:
        return None

    d = dict(row)
    # 反序列化 JSON 字段
    for field in ("payload_json", "key_variables", "chart_insights"):
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                pass  # 保留原始字符串
    return d


def list_wc_reports(
    conn: sqlite3.Connection,
    pipeline_status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """列出 wc_reports，可按 pipeline_status 过滤。"""
    if pipeline_status:
        rows = conn.execute(
            "SELECT match_id, home_team, away_team, match_time, pipeline_status, match_status "
            "FROM wc_reports WHERE pipeline_status=? ORDER BY match_time DESC LIMIT ?",
            (pipeline_status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT match_id, home_team, away_team, match_time, pipeline_status, match_status "
            "FROM wc_reports ORDER BY match_time DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# 审计记录（wc_prediction_audit）
# ──────────────────────────────────────────────────────────────────────────────

def write_wc_prediction_audit(
    conn: sqlite3.Connection,
    *,
    match_id: str,
    match_date: str,
    home: str,
    away: str,
    picked_market: str,
    picked_direction: str,
    picked_odds: Optional[float],
    picked_confidence: str,
) -> None:
    """
    写入 wc_prediction_audit（仅记录推荐，结算字段在 wc_post_match.py 更新）。
    INSERT OR IGNORE（不覆盖已有结算数据）。
    """
    conn.execute("""
        INSERT OR IGNORE INTO wc_prediction_audit
            (match_id, match_date, home, away,
             picked_market, picked_direction, picked_odds, picked_confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        match_id, match_date, home, away,
        picked_market, picked_direction, picked_odds, picked_confidence,
    ))
    conn.commit()
    log.info(f"[wc_store] audit written {match_id} dir={picked_direction} conf={picked_confidence}")
