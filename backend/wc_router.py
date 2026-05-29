"""
wc_router.py
============
世界杯研报 Serving 端点（VIP 后端）。

GET /api/v1/wc/match_payload/{match_id}

设计原则（已锁定，不可推翻）：
  - 读 worldcup.db.wc_reports（WC 全自包含，无 cc 内网调用）
  - [REUSE-IMPORT] 复用现有 gating 逻辑（红线：物理截断，不重写）
  - 读 football_uk.db.user_unlocks/users 判权限（gating 库不变）
  - 返回结构与联赛 sync_router.get_match_payload 形状对齐（前端 adaptCloudPayload 可直接消费）
  - GUEST → report_markdown 物理清空；推荐字段清空
  - REGISTERED + paid → report_markdown 物理清空
  - VIP / is_free / unlock → 全量数据

挂载（api_server.py）：
  from wc_router import router as wc_router
  app.include_router(wc_router)
"""

import json
import logging
import os
import re
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

# [REUSE-IMPORT] 复用现有 gating 依赖（不改 auth_deps.py / sync_router.py）
from auth_deps import get_optional_user, CurrentUser  # type: ignore

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 数据库路径
# ──────────────────────────────────────────────────────────────────────────────

_THIS_DIR    = os.path.dirname(os.path.abspath(__file__))
_PROJ_ROOT   = os.environ.get("PROJECT_ROOT", os.path.dirname(_THIS_DIR))
WC_DB_PATH   = os.environ.get("WC_DB_PATH",  os.path.join(_PROJ_ROOT, "worldcup.db"))
MAIN_DB_PATH = os.environ.get("DB_PATH",     os.path.join(_THIS_DIR,  "football_uk.db"))

router = APIRouter(prefix="/api/v1/wc", tags=["worldcup"])


# ──────────────────────────────────────────────────────────────────────────────
# 数据库连接
# ──────────────────────────────────────────────────────────────────────────────

def _get_wc_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(WC_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _get_main_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(MAIN_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ──────────────────────────────────────────────────────────────────────────────
# Payload 读取 + json 字段反序列化
# ──────────────────────────────────────────────────────────────────────────────

def _load_wc_report(match_id: str) -> Optional[dict]:
    try:
        conn = _get_wc_conn()
        row = conn.execute(
            "SELECT * FROM wc_reports WHERE match_id=?", (match_id,)
        ).fetchone()
        conn.close()
    except Exception as e:
        log.error(f"[wc_router] DB error reading wc_reports: {e}")
        raise HTTPException(status_code=503, detail="worldcup db temporarily unavailable")

    if row is None:
        return None

    d = dict(row)

    # 反序列化复合 JSON 字段
    for field in ("key_variables", "chart_insights"):
        v = d.get(field)
        if isinstance(v, str) and v:
            try:
                d[field] = json.loads(v)
            except Exception:
                pass

    # payload_json → market_implied_prob 等子字段
    payload_raw = d.get("payload_json")
    d["_payload"] = {}
    if payload_raw:
        try:
            d["_payload"] = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
        except Exception:
            pass

    return d


# ──────────────────────────────────────────────────────────────────────────────
# Gating（[REUSE-IMPORT] 复用逻辑，不重写）
# ──────────────────────────────────────────────────────────────────────────────

def _check_gating(match_id: str, is_free: bool, user: CurrentUser) -> tuple[bool, str, str]:
    """
    返回 (is_gated, access_level, unlock_reason)。

    复用联赛 gating 三步：
      1. is_free → 放行
      2. user.is_vip → 放行
      3. REGISTERED + user_unlocks 命中 → 放行
    """
    is_gated: bool = True
    unlock_reason: Optional[str] = None

    if user.is_guest:
        access_level = "guest"
    elif user.is_vip:
        access_level = "vip"
    else:
        access_level = "registered"

    if is_free:
        is_gated = False
        unlock_reason = "free_match"
    elif user.is_vip:
        is_gated = False
        unlock_reason = "vip"
    elif not user.is_guest and user.user_id:
        # 检查 user_unlocks（football_uk.db，与联赛相同逻辑）
        try:
            conn = _get_main_conn()
            row = conn.execute("""
                SELECT 1 FROM user_unlocks u
                JOIN users us ON us.username = u.username
                WHERE us.id = ? AND u.match_id = ?
                LIMIT 1
            """, (user.user_id, str(match_id))).fetchone()
            conn.close()
            if row:
                is_gated = False
                unlock_reason = "single_unlock"
                access_level = "unlocked"
        except Exception as e:
            log.warning(f"[wc_router] user_unlocks query failed: {e}")

    return is_gated, access_level, unlock_reason or ""


# ──────────────────────────────────────────────────────────────────────────────
# Payload 组装（对齐联赛 sync_router payload 形状，WC 字段加性）
# ──────────────────────────────────────────────────────────────────────────────

def _build_payload(
    match_id: str,
    report: dict,
    is_gated: bool,
    access_level: str,
    unlock_reason: str,
    user: CurrentUser,
) -> dict:
    """
    组装返回给前端的扁平 payload（与联赛 adaptCloudPayload 期望形状对齐）。
    """
    is_free        = bool(report.get("is_free"))
    _hide_probs    = user.is_guest
    _allow_post    = user.is_vip

    _payload_extra = report.get("_payload", {})

    # 从 payload_json 中提取 market-implied（closing devig 刷新后在此）
    market_data    = _payload_extra.get("market_implied") or {}
    wdl_mi         = market_data.get("wdl") or {}
    market_implied_prob = None
    if wdl_mi and not _hide_probs:
        home_p = wdl_mi.get("home")
        draw_p = wdl_mi.get("draw")
        away_p = wdl_mi.get("away")
        if home_p and draw_p and away_p:
            market_implied_prob = {
                "home": round(home_p * 100, 1),
                "draw": round(draw_p * 100, 1),
                "away": round(away_p * 100, 1),
            }

    # 概率字段（GUEST 清空）
    # DB 存储为小数（0-1），adaptCloudPayload 期望百分制（0-100），乘以 100 对齐联赛格式
    _hp = report.get("home_prob")
    _dp = report.get("draw_prob")
    _ap = report.get("away_prob")
    home_prob = round(_hp * 100, 1) if (_hp is not None and not _hide_probs) else None
    draw_prob = round(_dp * 100, 1) if (_dp is not None and not _hide_probs) else None
    away_prob = round(_ap * 100, 1) if (_ap is not None and not _hide_probs) else None
    inference = (report.get("inference") or "") if not _hide_probs else ""

    # 赛后复盘（仅 VIP）
    post_match_review = report.get("post_match_review") if _allow_post else None

    # chart_insights 反序列化（可能是 dict 或字符串）
    chart_raw = report.get("chart_insights")
    if isinstance(chart_raw, str):
        try:
            chart_insights = json.loads(chart_raw)
        except Exception:
            chart_insights = None
    else:
        chart_insights = chart_raw

    # key_variables 确保是 list
    key_vars = report.get("key_variables")
    if isinstance(key_vars, str):
        try:
            key_vars = json.loads(key_vars)
        except Exception:
            key_vars = None

    return {
        # ── 标识 ──
        "match_id":            match_id,
        "tournament_type":     "wc",           # 前端 tournamentType 门控用

        # ── 权限 ──
        "is_gated":            is_gated,
        "access_level":        access_level,
        "unlock_reason":       unlock_reason,
        "is_free":             is_free,

        # ── 研报内容（物理截断） ──
        "report_markdown":     report.get("report_markdown") if not is_gated else None,

        # ── 元数据 ──
        "home_team":           report.get("home_team") or "",
        "away_team":           report.get("away_team") or "",
        "home_icon":           "",    # WC 暂无 icon URL
        "away_icon":           "",
        "match_time":          report.get("match_time") or "",
        "league":              report.get("league") or "World Cup",
        "match_status":        report.get("match_status") or "upcoming",
        "pipeline_status":     report.get("pipeline_status") or "DRAFT",
        "preview_content":     report.get("preview_content"),
        "updated_at":          report.get("updated_at") or "",

        # ── 概率（GUEST 清空） ──
        "inference":           inference,
        "home_prob":           home_prob,
        "draw_prob":           draw_prob,
        "away_prob":           away_prob,
        "market_implied_prob": market_implied_prob,

        # ── WC 无此数据（前端 null → 自隐） ──
        "npxg_trend":          "{}",
        "shot_map_data":       "{}",
        "player_stats":        None,
        "team_match_stats":    None,
        "lineup_impact_data":  None,
        "lineup_status":       "unavailable",
        "lineup_confirmed_at": None,
        "lineup_brief":        None,

        # ── WC-only 字段（联赛 adaptCloudPayload 不读这些 key，安全加性） ──
        "ah_implied":    _payload_extra.get("market_implied", {}).get("ah") or None,
        "wc_team_stats": _payload_extra.get("wc_team_stats") or None,

        # ── 新手版字段 ──
        "beginner_summary":    report.get("beginner_summary"),
        "chart_insights":      chart_insights,
        "key_variables":       key_vars,
        "key_risk":            report.get("key_risk"),

        # ── 赛后（VIP only） ──
        "post_match_review":   post_match_review,
        "post_match_shots":    None,     # WC 无 shotmap

        # ── 战绩卡（WC 域首场无历史 → null，前端按 null 隐藏） ──
        "best_recent_stat":    None,

        # ── 综合判断卡（由 LLM 写入研报，服务端透传） ──
        "verdict_summary":     None,     # Phase 1 暂不解析，前端兜底隐藏
    }


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/match_payload/{match_id}")
async def get_wc_match_payload(
    match_id: str,
    request: Request,
    user: CurrentUser = Depends(get_optional_user),
):
    """
    获取 WC 研报复合 Payload。

    权限层（与联赛 sync_router 对齐）：
      - GUEST     → 200，report_markdown / inference / 概率物理清空
      - REGISTERED + paid → 200，report_markdown 物理清空
      - VIP / is_free / unlock → 200，全量数据
    """
    if not match_id.startswith("wc_"):
        raise HTTPException(status_code=400, detail="invalid match_id for wc endpoint")

    report = _load_wc_report(match_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"{match_id} not found")

    is_free = bool(report.get("is_free"))
    is_gated, access_level, unlock_reason = _check_gating(match_id, is_free, user)

    payload = _build_payload(
        match_id      = match_id,
        report        = report,
        is_gated      = is_gated,
        access_level  = access_level,
        unlock_reason = unlock_reason,
        user          = user,
    )

    log.info(
        f"[wc_router] {match_id} → access={access_level} gated={is_gated} "
        f"unlock={unlock_reason or '-'} user={user.user_id}"
    )

    return payload
