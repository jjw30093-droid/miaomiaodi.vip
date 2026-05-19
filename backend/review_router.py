"""
review_router.py — 赛后 AI 复盘 Admin 触发接口

路由：
  POST /api/v1/admin/trigger_reviews     — 触发全量待复盘批次（BackgroundTasks）
  POST /api/v1/admin/mark_finished       — 手动将指定比赛标记为 'finished'（调试用）
  GET  /api/v1/admin/review_status       — 查询当前哪些场次有/无复盘（Admin 监控）

鉴权：请求头必须携带 X-Admin-Token，值来自环境变量 ADMIN_SECRET_TOKEN。
"""

import os
import logging
import sqlite3

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel

from review_models import fetch_pending_reviews, mark_match_finished, get_db
from review_service import generate_post_match_reviews

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["Admin · Post-Match Review"])

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(_THIS_DIR, "football_uk.db"))
ADMIN_SECRET_TOKEN = os.environ.get("ADMIN_SECRET_TOKEN", "")


# ─────────────────────────────────────────────────────────────────────────────
# 鉴权依赖（复用于所有 Admin 路由）
# ─────────────────────────────────────────────────────────────────────────────

def _verify_admin(x_admin_token: str = Header(..., alias="X-Admin-Token")) -> None:
    """
    校验 Admin 令牌。
    未配置 ADMIN_SECRET_TOKEN 时拒绝所有请求（防止裸跑）。
    """
    if not ADMIN_SECRET_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="服务端未配置 ADMIN_SECRET_TOKEN，Admin 接口暂不可用。"
        )
    if x_admin_token != ADMIN_SECRET_TOKEN:
        raise HTTPException(
            status_code=401,
            detail="X-Admin-Token 鉴权失败。"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 后台任务包装（异常在此层捕获，确保不会污染 BackgroundTasks 线程）
# ─────────────────────────────────────────────────────────────────────────────

async def _run_reviews_safely(db_path: str) -> None:
    try:
        summary = await generate_post_match_reviews(db_path)
        log.info(f"[ReviewRouter] 后台复盘批次完成: {summary}")
    except Exception as e:
        log.error(f"[ReviewRouter] 后台复盘批次异常（不影响主进程）: {e}", exc_info=True)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/admin/trigger_reviews
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/trigger_reviews")
async def trigger_reviews(
    background_tasks: BackgroundTasks,
    x_admin_token: str = Header(..., alias="X-Admin-Token"),
):
    """
    触发赛后 AI 复盘批处理。

    - 立即返回 202，不阻塞调用方。
    - 实际处理在 BackgroundTasks 中异步执行：
        查库 → 拉取真实数据 → Claude 生成复盘 → 回写 DB
    - 可以安全地重复调用（已有复盘的场次自动跳过）。
    """
    _verify_admin(x_admin_token)

    # 先做一次快速预检，避免启动无意义后台任务
    pending = fetch_pending_reviews(DB_PATH)
    pending_count = len(pending)

    if pending_count == 0:
        return {
            "status":  "skipped",
            "message": "当前无待复盘比赛（所有 finished 场次均已有复盘或尚无已结束场次）。",
            "pending": 0,
        }

    background_tasks.add_task(_run_reviews_safely, DB_PATH)

    log.info(f"[ReviewRouter] Admin 触发复盘任务，共 {pending_count} 场待处理。")
    return {
        "status":  "processing",
        "message": f"复盘任务已在后台启动，共 {pending_count} 场待处理。",
        "pending": pending_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/admin/mark_finished
# ─────────────────────────────────────────────────────────────────────────────

class MarkFinishedRequest(BaseModel):
    match_id:    str
    match_status: str = "finished"   # 也可传 'upcoming' 撤回


@router.post("/mark_finished")
async def mark_finished(
    body: MarkFinishedRequest,
    x_admin_token: str = Header(..., alias="X-Admin-Token"),
):
    """
    手动将指定比赛的 match_status 更新为 'finished' 或 'upcoming'。
    用途：
      - 比赛结束后立即标记，触发 trigger_reviews 时就能识别到。
      - 测试阶段将特定场次快速切换状态。
    """
    _verify_admin(x_admin_token)

    allowed = {"upcoming", "finished"}
    if body.match_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"match_status 必须是 {allowed} 之一。"
        )

    conn = get_db(DB_PATH)
    try:
        result = conn.execute(
            "UPDATE report_store SET match_status = ? WHERE match_id = ?",
            (body.match_status, body.match_id)
        )
        conn.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"match_id={body.match_id} 不存在。")
    finally:
        conn.close()

    log.info(f"[ReviewRouter] match_id={body.match_id} → match_status='{body.match_status}'")
    return {
        "status":       "ok",
        "match_id":     body.match_id,
        "match_status": body.match_status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/admin/review_status
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/review_status")
async def review_status(
    x_admin_token: str = Header(..., alias="X-Admin-Token"),
):
    """
    返回所有 finished 场次的复盘状态概览（已有/待处理）。
    供 Admin Dashboard 或手动运维使用。
    """
    _verify_admin(x_admin_token)

    conn = get_db(DB_PATH)
    try:
        rows = conn.execute("""
            SELECT
                match_id,
                home_team,
                away_team,
                match_time,
                match_status,
                CASE WHEN post_match_review IS NULL THEN 0 ELSE 1 END AS has_review,
                CASE WHEN post_match_shots  IS NULL THEN 0 ELSE 1 END AS has_shots
            FROM report_store
            WHERE match_status = 'finished'
            ORDER BY match_time DESC
            LIMIT 50
        """).fetchall()
    finally:
        conn.close()

    data = [dict(r) for r in rows]
    pending_count  = sum(1 for r in data if not r["has_review"])
    complete_count = sum(1 for r in data if r["has_review"])

    return {
        "total_finished": len(data),
        "pending_review": pending_count,
        "complete":       complete_count,
        "matches":        data,
    }
