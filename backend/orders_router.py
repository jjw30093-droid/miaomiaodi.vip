"""
orders_router.py — 订单创建 + 查询接口

路由：
  POST /api/v1/orders  — 创建待支付订单（需登录）
  GET  /api/v1/orders  — 查我的订单列表（需登录）
"""

import os
import time
import secrets
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from auth_deps import get_current_user, CurrentUser

router = APIRouter(tags=["Orders"])

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(_THIS_DIR, "football_uk.db"))


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _gen_order_no() -> str:
    ts_ms = int(time.time() * 1000)
    rand6 = secrets.token_hex(3)
    return f"ord_{ts_ms}_{rand6}"


# ─────────────────────────────────────────────────────────────
# POST /orders — 创建订单
# ─────────────────────────────────────────────────────────────

class CreateOrderRequest(BaseModel):
    product_id: int
    match_id: Optional[str] = None


@router.post("/orders")
async def create_order(
    body: CreateOrderRequest,
    user: CurrentUser = Depends(get_current_user),
):
    conn = _get_conn()
    try:
        # 1. 查产品
        product = conn.execute(
            "SELECT * FROM products WHERE id=? AND is_active=1",
            (body.product_id,)
        ).fetchone()
        if not product:
            raise HTTPException(status_code=400, detail="Product not found or inactive")

        # 2. 按类型校验
        if product["type"] == "single_match":
            if not body.match_id:
                raise HTTPException(status_code=400, detail="match_id is required for single_match products")
            match_row = conn.execute(
                "SELECT match_id FROM report_store WHERE match_id=?",
                (str(body.match_id),)
            ).fetchone()
            if not match_row:
                raise HTTPException(status_code=404, detail="Match not found")
            # 防重复购买：同 user + match_id 已有 paid 或未过期 pending 订单
            dup = conn.execute(
                """SELECT id, status FROM orders
                   WHERE user_id=? AND match_id=?
                     AND status IN ('paid','pending')
                     AND (status='paid' OR datetime(expires_at) > datetime('now'))""",
                (user.user_id, str(body.match_id))
            ).fetchone()
            if dup:
                if dup["status"] == "paid":
                    raise HTTPException(status_code=409, detail="You already have a paid order for this match")
                else:
                    raise HTTPException(status_code=409, detail="You have a pending order for this match. Please complete or wait for it to expire.")
        else:
            # package 类型：match_id 必须为空
            if body.match_id:
                raise HTTPException(status_code=400, detail="match_id must be empty for package products")
            # 防重复购买：同 user + sku 已有 paid 或未过期 pending 订单
            dup = conn.execute(
                """SELECT o.id, o.status FROM orders o
                   JOIN products p ON p.id = o.product_id
                   WHERE o.user_id=? AND p.sku=?
                     AND o.status IN ('paid','pending')
                     AND (o.status='paid' OR datetime(o.expires_at) > datetime('now'))""",
                (user.user_id, product["sku"])
            ).fetchone()
            if dup:
                if dup["status"] == "paid":
                    raise HTTPException(status_code=409, detail="You already have a paid order for this package")
                else:
                    raise HTTPException(status_code=409, detail="You have a pending order for this package. Please complete or wait for it to expire.")

        # 3. 生成订单号
        order_no = _gen_order_no()

        # 4. 写入订单
        conn.execute(
            """INSERT INTO orders
               (order_no, user_id, product_id,
                sku_snapshot, name_snapshot, price_cents,
                payment_provider, status, expires_at, match_id)
               VALUES (?, ?, ?, ?, ?, ?, 'hupijiao', 'pending',
                       datetime('now', '+30 minutes'), ?)""",
            (
                order_no,
                user.user_id,
                product["id"],
                product["sku"],
                product["name"],
                product["price_cents"],
                str(body.match_id) if body.match_id else None,
            )
        )
        conn.commit()

        # 读回 expires_at
        row = conn.execute(
            "SELECT expires_at FROM orders WHERE order_no=?", (order_no,)
        ).fetchone()
        expires_at = row["expires_at"] if row else None

    finally:
        conn.close()

    return {
        "order_no":     order_no,
        "status":       "pending",
        "amount_yuan":  round(product["price_cents"] / 100, 2),
        "product_name": product["name"],
        "expires_at":   expires_at,
        "payment_url":  None,
    }


# ─────────────────────────────────────────────────────────────
# GET /orders — 查我的订单
# ─────────────────────────────────────────────────────────────

@router.get("/orders")
async def list_orders(
    status: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
):
    conn = _get_conn()
    try:
        if status is not None:
            rows = conn.execute(
                """SELECT o.order_no, p.name AS product_name,
                          o.price_cents, o.status,
                          o.match_id, o.created_at, o.paid_at
                     FROM orders o
                     JOIN products p ON p.id = o.product_id
                    WHERE o.user_id=? AND o.status=?
                    ORDER BY o.created_at DESC LIMIT 50""",
                (user.user_id, status)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT o.order_no, p.name AS product_name,
                          o.price_cents, o.status,
                          o.match_id, o.created_at, o.paid_at
                     FROM orders o
                     JOIN products p ON p.id = o.product_id
                    WHERE o.user_id=?
                    ORDER BY o.created_at DESC LIMIT 50""",
                (user.user_id,)
            ).fetchall()
    finally:
        conn.close()

    orders = [
        {
            "order_no":     r["order_no"],
            "product_name": r["product_name"],
            "amount_yuan":  round(r["price_cents"] / 100, 2),
            "status":       r["status"],
            "match_id":     r["match_id"],
            "created_at":   r["created_at"],
            "paid_at":      r["paid_at"],
        }
        for r in rows
    ]
    return {"orders": orders}


# ─────────────────────────────────────────────────────────────
# GET /orders/pending — 查当前用户的 pending 订单
#   ?match_id=xxx  → 返回 {"pending_order": {...} | null}
#   不传 match_id  → 返回 {"pending_orders": [...]}
#
# 用途：PaywallOverlay 检测到 registered 用户访问付费 match 时，
# 调本端点判断是否有未过期 pending 订单 → 渲染"我已支付，刷新状态"卡片。
# ─────────────────────────────────────────────────────────────

@router.get("/orders/pending")
async def get_pending_order(
    match_id: Optional[str] = None,
    user: CurrentUser = Depends(get_current_user),
):
    conn = _get_conn()
    try:
        if match_id:
            rows = conn.execute(
                """SELECT o.order_no, p.name AS product_name,
                          o.price_cents, o.match_id,
                          o.created_at, o.expires_at,
                          CAST((julianday(o.expires_at) - julianday('now')) * 86400 AS INTEGER) AS seconds_left
                     FROM orders o
                     JOIN products p ON p.id = o.product_id
                    WHERE o.user_id=? AND o.match_id=? AND o.status='pending'
                      AND datetime(o.expires_at) > datetime('now')
                    ORDER BY o.created_at DESC LIMIT 1""",
                (user.user_id, str(match_id))
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT o.order_no, p.name AS product_name,
                          o.price_cents, o.match_id,
                          o.created_at, o.expires_at,
                          CAST((julianday(o.expires_at) - julianday('now')) * 86400 AS INTEGER) AS seconds_left
                     FROM orders o
                     JOIN products p ON p.id = o.product_id
                    WHERE o.user_id=? AND o.status='pending'
                      AND datetime(o.expires_at) > datetime('now')
                    ORDER BY o.created_at DESC LIMIT 50""",
                (user.user_id,)
            ).fetchall()
    finally:
        conn.close()

    items = [
        {
            "order_no":     r["order_no"],
            "product_name": r["product_name"],
            "amount_yuan":  round(r["price_cents"] / 100, 2),
            "match_id":     r["match_id"],
            "created_at":   r["created_at"],
            "expires_at":   r["expires_at"],
            "seconds_left": max(0, int(r["seconds_left"] or 0)),
        }
        for r in rows
    ]

    if match_id:
        return {"pending_order": items[0] if items else None}
    return {"pending_orders": items}
