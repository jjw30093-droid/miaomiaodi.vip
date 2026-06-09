"""
stripe_router.py — Stripe 银行卡支付接入

路由：
  POST /api/v1/payments/stripe/checkout   — 建 Stripe Checkout Session，返回 payment_url
  POST /api/v1/webhooks/stripe            — Stripe Webhook（验签 + 幂等履约）
  POST /api/v1/admin/orders/{order_no}/fulfill — 管理员手动补单履约

设计约束（CLAUDE.md）：
  - /payments/stripe/checkout 与 /orders 解耦：纯本地建单(orders)后再调 Stripe，失败可独立重试
  - webhook 读 raw bytes → 验签 → 幂等履约（状态门 + 守卫 UPDATE + INSERT OR IGNORE）
  - 付款成功后：单场 → user_unlocks；套餐 → user_entitlements（见 db_migrate.py Migration 9）
  - username 必须从 users 表取（user_unlocks.username NOT NULL 约束）
  - 所有操作写 admin_audit_log
  - 货币：currency='cny'（直接以人民币收款）
"""

import json
import logging
import os
import secrets
import sqlite3
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth_deps import get_current_user, get_optional_user, CurrentUser

log = logging.getLogger(__name__)

router = APIRouter(tags=["Stripe"])

# ── 路径 ──────────────────────────────────────────────────────────────────────
_THIS_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH      = os.environ.get("DB_PATH",    os.path.join(_THIS_DIR, "football_uk.db"))
WC_DB_PATH   = os.environ.get("WC_DB_PATH", os.path.join(os.path.dirname(_THIS_DIR), "worldcup.db"))

# ── Stripe 配置 ───────────────────────────────────────────────────────────────
STRIPE_SECRET_KEY      = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
ADMIN_SECRET_TOKEN     = os.environ.get("ADMIN_SECRET_TOKEN", "")

stripe.api_key = STRIPE_SECRET_KEY

# 套餐上/下半段 UTC 日期边界（full_half_1 = 小组赛，full_half_2 = 淘汰赛）
# 2026 WC：小组赛 06-11~06-26，淘汰赛 06-27~07-19（含 3rd/Final）
HALF1_FROM = "2026-06-11 00:00:00"
HALF1_TO   = "2026-06-27 00:00:00"
HALF2_FROM = "2026-06-27 00:00:00"
HALF2_TO   = "2026-07-20 00:00:00"
ENTITLEMENT_EXPIRES = "2026-07-26 00:00:00"   # 赛事结束 +7 天


# ─────────────────────────────────────────────────────────────────────────────
# DB 工具
# ─────────────────────────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _get_wc_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(WC_DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Admin 鉴权（timing-safe，同 cdk_router）
# ─────────────────────────────────────────────────────────────────────────────

def _verify_admin(request: Request) -> None:
    token = request.headers.get("X-Admin-Token", "")
    if not ADMIN_SECRET_TOKEN:
        raise HTTPException(status_code=503, detail="Admin token not configured")
    if not secrets.compare_digest(token.encode(), ADMIN_SECRET_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Invalid admin token")


# ─────────────────────────────────────────────────────────────────────────────
# 审计日志
# ─────────────────────────────────────────────────────────────────────────────

def _audit(conn: sqlite3.Connection, event: str, actor: str, payload: dict,
           ip: str = "", ua: str = "") -> None:
    try:
        conn.execute("""
            INSERT INTO admin_audit_log (action, actor, payload, ip, ua, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (event, actor, json.dumps(payload, ensure_ascii=False), ip, ua))
    except Exception as e:
        log.warning(f"[stripe] audit write failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 套餐 scope 推导
# ─────────────────────────────────────────────────────────────────────────────

def _derive_scope(sku: str, metadata_json: str) -> dict:
    """
    根据 SKU + metadata 推导 user_entitlements 的 scope 字段。
    返回 {scope_kind, scope_value, covers_from, covers_to}。
    """
    try:
        meta = json.loads(metadata_json or "{}")
    except Exception:
        meta = {}
    scope = meta.get("scope", "")

    if scope == "group_stage":
        return {
            "scope_kind": "stage",
            "scope_value": "group_stage",
            "covers_from": None,
            "covers_to":   None,
        }
    elif scope == "knockout":
        return {
            "scope_kind": "stage",
            "scope_value": "knockout",
            "covers_from": None,
            "covers_to":   None,
        }
    elif scope == "full_half_1":
        return {
            "scope_kind": "date_range",
            "scope_value": None,
            "covers_from": HALF1_FROM,
            "covers_to":   HALF1_TO,
        }
    elif scope == "full_half_2":
        return {
            "scope_kind": "date_range",
            "scope_value": None,
            "covers_from": HALF2_FROM,
            "covers_to":   HALF2_TO,
        }
    else:
        # fallback：当作全覆盖 date_range（不应命中）
        log.warning(f"[stripe] unknown package scope for sku={sku}: {scope}")
        return {
            "scope_kind": "date_range",
            "scope_value": None,
            "covers_from": HALF1_FROM,
            "covers_to":   HALF2_TO,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 核心履约函数（webhook + admin 共用，幂等）
# ─────────────────────────────────────────────────────────────────────────────

def fulfill_order(conn: sqlite3.Connection, order_no: str,
                  provider_session_id: str = "") -> dict:
    """
    幂等履约：
      1. 查订单 + 状态门（unknown/refunded/cancelled → 200 停止）
      2. 守卫 UPDATE status='paid'（若已 paid 则幂等重跑履约，防止崩溃遗漏）
      3. INSERT OR IGNORE 写权益（user_unlocks 或 user_entitlements）
      4. 写 admin_audit_log
    返回 {ok: True, action: 'paid'|'already_paid'|'skipped', details: str}。
    """
    order = conn.execute(
        """SELECT o.*, p.type AS product_type, p.sku, p.metadata AS product_metadata
           FROM orders o JOIN products p ON p.id = o.product_id
           WHERE o.order_no = ?""",
        (order_no,)
    ).fetchone()

    if order is None:
        log.warning(f"[fulfill] unknown order_no={order_no}")
        _audit(conn, "stripe_fulfill_unknown", "system", {"order_no": order_no})
        return {"ok": True, "action": "skipped", "details": "unknown order"}

    if order["status"] in ("refunded", "cancelled"):
        log.info(f"[fulfill] order {order_no} is {order['status']}, skipping")
        return {"ok": True, "action": "skipped", "details": order["status"]}

    # 守卫 UPDATE（如果已 paid 则 rowcount=0，继续重跑履约 INSERT OR IGNORE）
    n = conn.execute(
        """UPDATE orders
           SET status='paid', paid_at=CURRENT_TIMESTAMP,
               provider_order_id=?, payment_provider='stripe',
               currency='cny', updated_at=CURRENT_TIMESTAMP
           WHERE order_no=? AND status='pending'""",
        (provider_session_id, order_no)
    ).rowcount
    action = "paid" if n > 0 else "already_paid"

    # 取 username（user_unlocks.username NOT NULL，必须从 users 取）
    user_row = conn.execute(
        "SELECT username FROM users WHERE id=?", (order["user_id"],)
    ).fetchone()
    username = user_row["username"] if user_row else ""

    # ── 履约写权益 ──────────────────────────────────────────────────────────
    if order["product_type"] == "single_match":
        match_id = order["match_id"] or ""
        conn.execute("""
            INSERT OR IGNORE INTO user_unlocks
              (username, user_id, match_id, unlock_source, source_ref, expires_at)
            VALUES (?, ?, ?, 'stripe_order', ?, NULL)
        """, (username, order["user_id"], match_id, order_no))
        details = f"unlocked match {match_id}"
    else:
        # 套餐
        scope_info = _derive_scope(order["sku"], order["product_metadata"] or "{}")
        conn.execute("""
            INSERT OR IGNORE INTO user_entitlements
              (user_id, username, sku, scope_kind, scope_value,
               season, competition, covers_from, covers_to,
               source_order_no, expires_at)
            VALUES (?, ?, ?, ?, ?, '2026', 'wc', ?, ?, ?, ?)
        """, (
            order["user_id"], username, order["sku"],
            scope_info["scope_kind"], scope_info["scope_value"],
            scope_info["covers_from"], scope_info["covers_to"],
            order_no, ENTITLEMENT_EXPIRES,
        ))
        details = f"entitlement granted sku={order['sku']}"

    _audit(conn, f"stripe_fulfill_{action}", "stripe_webhook", {
        "order_no": order_no,
        "sku": order["sku"],
        "user_id": order["user_id"],
        "session_id": provider_session_id,
        "details": details,
    })
    conn.commit()
    log.info(f"[fulfill] {order_no} action={action} {details}")
    return {"ok": True, "action": action, "details": details}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/payments/stripe/checkout
# ─────────────────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    order_no: str


@router.post("/payments/stripe/checkout")
async def create_stripe_checkout(
    body: CheckoutRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    """
    用已存在的 pending order 创建 Stripe Checkout Session，返回 payment_url。

    幂等：若订单已有未过期 session，返回旧 URL（防重复建单/双扣）。
    """
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    conn = _get_conn()
    try:
        order = conn.execute(
            """SELECT o.*, p.name AS product_name, p.price_cents,
                      p.type AS product_type, p.sku
               FROM orders o JOIN products p ON p.id = o.product_id
               WHERE o.order_no=? AND o.user_id=?""",
            (body.order_no, user.user_id)
        ).fetchone()
    finally:
        conn.close()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order["status"] == "paid":
        raise HTTPException(status_code=409, detail="Order already paid")
    if order["status"] in ("cancelled", "refunded"):
        raise HTTPException(status_code=409, detail=f"Order is {order['status']}")

    # 幂等：若已有 session id 且未过期，返回旧链接
    existing_session_id = order["provider_order_id"]
    if existing_session_id and existing_session_id.startswith("cs_"):
        try:
            sess = stripe.checkout.Session.retrieve(existing_session_id)
            if sess.status == "open":
                return {"payment_url": sess.url, "session_id": sess.id, "reused": True}
        except stripe.StripeError:
            pass  # session 过期或无效，重建

    # 建 Stripe Checkout Session（Hosted Page，CNY）
    base_url = os.environ.get("FRONTEND_BASE_URL", "https://miaomiaodi.vip")
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            currency="cny",
            line_items=[{
                "price_data": {
                    "currency": "cny",
                    "unit_amount": order["price_cents"],
                    "product_data": {
                        "name": order["product_name"],
                        "description": f"喵弟量化研究所 · 世界杯数据研报",
                    },
                },
                "quantity": 1,
            }],
            metadata={
                "order_no":  body.order_no,
                "user_id":   str(user.user_id),
                "sku":       order["sku"],
            },
            success_url=f"{base_url}/checkout/success?order_no={body.order_no}",
            cancel_url=f"{base_url}/checkout/cancel?order_no={body.order_no}",
            expires_at=int(__import__("time").time()) + 1800,  # 30 分钟
        )
    except stripe.StripeError as e:
        log.error(f"[stripe] checkout session create failed: {e}")
        raise HTTPException(status_code=502, detail=f"Stripe error: {str(e)[:200]}")

    # 把 session_id 写回 orders
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE orders SET provider_order_id=?, payment_provider='stripe', currency='cny' WHERE order_no=?",
            (session.id, body.order_no)
        )
        conn.commit()
    finally:
        conn.close()

    log.info(f"[stripe] checkout created order={body.order_no} session={session.id}")
    return {"payment_url": session.url, "session_id": session.id, "reused": False}


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/webhooks/stripe
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """
    Stripe Webhook 接收端点。

    重要：必须读 raw bytes（不能声明 Pydantic body），否则验签失败。
    Stripe-Signature 头用于 HMAC 验证。
    幂等：重复触发安全（fulfill_order 内部处理）。
    """
    if not STRIPE_WEBHOOK_SECRET:
        log.error("[stripe webhook] STRIPE_WEBHOOK_SECRET not set — refusing all webhooks")
        raise HTTPException(status_code=503, detail="Webhook not configured")

    raw = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(raw, sig, STRIPE_WEBHOOK_SECRET)
    except stripe.SignatureVerificationError as e:
        log.warning(f"[stripe webhook] invalid signature: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        log.error(f"[stripe webhook] construct_event error: {e}")
        raise HTTPException(status_code=400, detail="Malformed webhook payload")

    # 只处理 checkout.session.completed；其他事件返回 200 忽略（不让 Stripe 重试）
    if event.type != "checkout.session.completed":
        return {"ok": True, "event": event.type, "action": "ignored"}

    session = event.data.object
    order_no = (session.metadata or {}).get("order_no", "")
    if not order_no:
        log.error(f"[stripe webhook] session {session.id} has no order_no in metadata")
        _audit_noconn({"event": "stripe_webhook_no_order_no", "session_id": session.id})
        return {"ok": True, "action": "no_order_no"}

    conn = _get_conn()
    try:
        result = fulfill_order(conn, order_no, provider_session_id=session.id)
    except Exception as e:
        conn.close()
        log.error(f"[stripe webhook] fulfill_order error order={order_no}: {e}")
        raise HTTPException(status_code=500, detail="Fulfillment error")
    finally:
        conn.close()

    return {"ok": True, **result}


def _audit_noconn(payload: dict) -> None:
    """无 conn 时的简化审计（写到日志）。"""
    log.info(f"[audit_noconn] {payload}")


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/admin/orders/{order_no}/fulfill
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/admin/orders/{order_no}/fulfill")
async def admin_fulfill_order(
    order_no: str,
    request: Request,
    _: None = Depends(_verify_admin),
):
    """
    管理员手动补单履约（webhook 漏发/争议补单用）。
    与 webhook 共用 fulfill_order()，完全幂等。
    """
    conn = _get_conn()
    try:
        result = fulfill_order(conn, order_no, provider_session_id="admin_manual")
        _audit(conn, "admin_manual_fulfill", "admin",
               {"order_no": order_no, **result},
               ip=request.headers.get("X-Real-IP", ""),
               ua=request.headers.get("User-Agent", "")[:200])
        conn.commit()
    except HTTPException:
        conn.close()
        raise
    except Exception as e:
        conn.close()
        log.error(f"[admin fulfill] error order={order_no}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

    return {"ok": True, "order_no": order_no, **result}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/orders/{order_no}/status — 前端轮询（checkout success 页用）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/orders/{order_no}/status")
async def get_order_status(
    order_no: str,
    user: CurrentUser = Depends(get_current_user),
):
    """
    查单笔订单状态（前端 /checkout/success 轮询用）。
    只返回归属于当前用户的订单。
    """
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT o.order_no, o.status, o.paid_at, o.match_id,
                      p.name AS product_name, p.sku, o.price_cents
               FROM orders o JOIN products p ON p.id = o.product_id
               WHERE o.order_no=? AND o.user_id=?""",
            (order_no, user.user_id)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        "order_no":     row["order_no"],
        "status":       row["status"],
        "paid_at":      row["paid_at"],
        "match_id":     row["match_id"],
        "product_name": row["product_name"],
        "sku":          row["sku"],
        "amount_yuan":  round(row["price_cents"] / 100, 2),
    }
