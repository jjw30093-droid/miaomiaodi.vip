"""
cdk_router.py — CDK 卡密核销 + 后台发卡路由

路由：
  POST /api/v1/redeem               — 旧接口（已 410 Gone，保留兼容）
  POST /api/v1/cdk/redeem           — 用户核销（基于 JWT，支持 VIP 天数延期 + Token 重签）
  POST /api/v1/admin/generate-cdks  — 主理人后台批量发卡（X-Admin-Token 鉴权）
"""

import os
import time
import secrets
import string
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Header, Depends
from pydantic import BaseModel
from typing import Optional, List

from auth_deps import get_optional_user, make_jwt, issue_session_token

router = APIRouter(prefix="/api/v1", tags=["Indie Monetization"])

# 统一使用与其他路由相同的 DB_PATH 环境变量
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(_THIS_DIR, "football_uk.db"))

# 极简内存限流：单 IP 1 分钟最多尝试 5 次
_rate_limit_cache: dict[str, dict] = {}

# Admin 鉴权（与 review_router._verify_admin 同语义）
ADMIN_SECRET_TOKEN = os.environ.get("ADMIN_SECRET_TOKEN", "")

# CDK 生成字符集（剔除易混淆字符 O 0 I 1）
_CDK_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "O0I1")


# ─────────────────────────────────────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _check_rate_limit(client_ip: str) -> None:
    now = time.time()
    bucket = _rate_limit_cache.get(client_ip, {"count": 0, "reset_at": now + 60})
    if now > bucket["reset_at"]:
        bucket = {"count": 1, "reset_at": now + 60}
    else:
        bucket["count"] += 1
    _rate_limit_cache[client_ip] = bucket
    if bucket["count"] > 5:
        raise HTTPException(status_code=429, detail="尝试过于频繁，请 1 分钟后再试。")


def _validate_cdk(cursor: sqlite3.Cursor, code: str) -> sqlite3.Row:
    """查询并校验 CDK 的有效性（未使用且未过期）。"""
    cursor.execute(
        "SELECT * FROM shop_cdk WHERE code = ? AND is_used = 0",
        (code.upper().strip(),)
    )
    cdk = cursor.fetchone()
    if not cdk:
        raise HTTPException(status_code=400, detail="卡密无效或已被使用。")

    if cdk["expires_at"]:
        try:
            expire_dt = datetime.strptime(cdk["expires_at"], "%Y-%m-%d %H:%M:%S")
            if expire_dt < datetime.now():
                raise HTTPException(status_code=400, detail="卡密已过期，无法使用。")
        except ValueError:
            pass  # 格式异常时宽松处理

    return cdk


# ─────────────────────────────────────────────────────────────────────────────
# 旧接口 — 已废弃，返回 410 Gone
# 原因：username 由客户端自填，无法验证身份，存在身份冒充风险。
# 请所有客户端迁移至 POST /api/v1/cdk/redeem（基于 JWT）。
# ─────────────────────────────────────────────────────────────────────────────

from fastapi.responses import JSONResponse

@router.post("/redeem", tags=["Deprecated"])
async def redeem_cdk_legacy_deprecated():
    return JSONResponse(
        status_code=410,
        content={
            "detail": "此接口已废弃（身份验证漏洞）。请使用 POST /api/v1/cdk/redeem（需携带 JWT）。"
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# 新接口 POST /api/v1/cdk/redeem — 基于 JWT，支持 VIP 延期
# ─────────────────────────────────────────────────────────────────────────────

class CdkRedeemRequest(BaseModel):
    code: str


@router.post("/cdk/redeem")
async def redeem_cdk_vip(body: CdkRedeemRequest, req: Request):
    """
    VIP 卡密兑换接口。

    流程：
      1. 解析 JWT，必须已登录（GUEST → 401）
      2. 限流检查
      3. 独占事务：校验 CDK → 标记已使用
      4. 根据 cdk.vip_days 延长 wechat_users.vip_expires_at
      5. 重签 JWT（含最新 is_vip / vip_expires_at）并返回给前端
         前端调用 login(token) 即可实时刷新全局 VIP 状态

    卡密类型（vip_days）：
      vip_days = 7  → 周卡（+7 天）
      vip_days = 30 → 月卡（+30 天）
      vip_days = 0  → 纯点数卡（不影响 VIP，仅返回 quota 变化）
    """
    # ── 1. JWT 鉴权 ───────────────────────────────────────────────────────────
    user = get_optional_user(req)
    if user.is_guest:
        raise HTTPException(status_code=401, detail="请先登录后再兑换卡密。")

    # ── 2. 限流（必须用真实 IP，避免反代后全部用户共享桶）───────────────────
    from rate_limit import client_ip as _client_ip
    _check_rate_limit(_client_ip(req))

    conn = _get_db()
    cursor = conn.cursor()
    try:
        conn.execute("BEGIN EXCLUSIVE TRANSACTION")

        # ── 3. 校验 CDK ───────────────────────────────────────────────────────
        cdk = _validate_cdk(cursor, body.code)

        # 标记已使用（用 user_id 记录）
        cursor.execute(
            "UPDATE shop_cdk SET is_used = 1, used_by = ? WHERE id = ?",
            (str(user.user_id), cdk["id"])
        )

        # ── 4. 读取当前用户 VIP 状态，计算新到期时间 ─────────────────────────
        # 以 users 表为准（已废弃 wechat_users，DEPRECATED 2026-04-17）
        cursor.execute(
            "SELECT id, role, nickname, avatar_url, vip_expires_at FROM users WHERE id = ?",
            (user.user_id,)
        )
        db_user = cursor.fetchone()
        if not db_user:
            conn.rollback()
            raise HTTPException(status_code=404, detail="用户记录不存在，请重新登录。")

        vip_days: int = cdk["vip_days"] if cdk["vip_days"] else 0
        new_vip_expires_at: str | None = None
        new_role = db_user["role"] or "registered"

        if vip_days > 0:
            now_utc = datetime.now(timezone.utc)

            # 若当前 VIP 仍在有效期内，在到期时间基础上累加；否则从现在起算
            current_exp_str = db_user["vip_expires_at"]
            if current_exp_str:
                try:
                    current_exp = datetime.fromisoformat(current_exp_str)
                    if current_exp.tzinfo is None:
                        current_exp = current_exp.replace(tzinfo=timezone.utc)
                    base = max(current_exp, now_utc)
                except (ValueError, TypeError):
                    base = now_utc
            else:
                base = now_utc

            new_exp = base + timedelta(days=vip_days)
            new_vip_expires_at = new_exp.isoformat()
            new_role = "vip"  # VIP 延期后必然是 VIP

            cursor.execute(
                "UPDATE users SET role = 'vip', vip_expires_at = ?, updated_at = datetime('now') WHERE id = ?",
                (new_vip_expires_at, user.user_id)
            )

        # 如果 CDK 附带 quota，也一并处理（向后兼容）
        quota_delta = cdk["quota"] if cdk["quota"] else 0
        if quota_delta > 0:
            cursor.execute("""
                INSERT INTO user_meta (username, report_quota)
                VALUES (?, ?)
                ON CONFLICT(username) DO UPDATE SET report_quota = report_quota + ?
            """, (str(user.user_id), quota_delta, quota_delta))

        conn.commit()

        # ── 5. 重签 JWT（沿用当前 jti，避免把自己踢下线）─────────────────────
        new_token = issue_session_token(
            user_id=user.user_id,
            role=new_role,
            nickname=db_user["nickname"] or "足球探索者",
            avatar_url=db_user["avatar_url"] or "",
            vip_expires_at=new_vip_expires_at,
            ip=req.client.host if req.client else "",
            ua=req.headers.get("User-Agent", ""),
            reuse_jti=user.jti,   # 沿用当前 jti，不新增会话
        )

        # 构建友好提示
        if vip_days > 0:
            label = "周卡 (+7 天)" if vip_days == 7 else f"月卡 (+{vip_days} 天)"
            exp_display = (
                datetime.fromisoformat(new_vip_expires_at).strftime("%Y-%m-%d %H:%M UTC")
                if new_vip_expires_at else "—"
            )
            message = f"🎉 {label} 兑换成功！VIP 有效至 {exp_display}"
        else:
            message = f"兑换成功！新增 {quota_delta} 场研报额度。"

        return {
            "status":          "success",
            "message":         message,
            "token":           new_token,
            "vip_expires_at":  new_vip_expires_at,
            "vip_days_added":  vip_days,
        }

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"服务器事务异常: {e}")
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Admin 接口 POST /api/v1/admin/generate-cdks — 批量发卡
# 鉴权：X-Admin-Token（与 review_router._verify_admin 同语义）
# 前端走 Next.js Route Handler 代理注入 token，浏览器 bundle 不含密钥
# ─────────────────────────────────────────────────────────────────────────────

def _verify_admin(x_admin_token: str = Header(..., alias="X-Admin-Token")) -> None:
    """校验 X-Admin-Token；未配置时拒绝所有请求；timing-safe 比较。"""
    if not ADMIN_SECRET_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="服务端未配置 ADMIN_SECRET_TOKEN，Admin 接口暂不可用。"
        )
    if not secrets.compare_digest(x_admin_token, ADMIN_SECRET_TOKEN):
        raise HTTPException(status_code=401, detail="X-Admin-Token 鉴权失败。")


def _generate_cdk_code(length: int = 10) -> str:
    return "".join(secrets.choice(_CDK_ALPHABET) for _ in range(length))


class GenerateCdksRequest(BaseModel):
    count: int                              # 1..50
    quota: int = 0                          # 0..100，点数卡额度
    vip_days: int = 0                       # 0 | 7 | 30
    expire_days: int = 30                   # 1..365，CDK 自身有效期
    admin_username: Optional[str] = None    # 仅审计用


@router.post("/admin/generate-cdks")
async def generate_cdks(
    body: GenerateCdksRequest,
    req: Request,
    _: None = Depends(_verify_admin),
):
    """
    批量生成 CDK，落入 shop_cdk 表，并写一条 admin_audit_log 审计。

    返回：{"cdks": [code, ...], "count": int}
    """
    # 1) 入参校验
    if not (1 <= body.count <= 50):
        raise HTTPException(400, "count 必须在 1..50")
    if not (0 <= body.quota <= 100):
        raise HTTPException(400, "quota 必须在 0..100")
    if body.vip_days not in (0, 7, 30):
        raise HTTPException(400, "vip_days 仅允许 0 / 7 / 30")
    if not (1 <= body.expire_days <= 365):
        raise HTTPException(400, "expire_days 必须在 1..365")

    # 2) 真实 IP 提取（CF-Connecting-IP → X-Real-IP → X-Forwarded-For）
    try:
        from rate_limit import client_ip as _client_ip
        real_ip = _client_ip(req)
    except Exception:
        real_ip = req.client.host if req.client else ""

    # 3) 批量生成 + 入库（单事务 + UNIQUE 冲突重试）
    expires_at = (datetime.utcnow() + timedelta(days=body.expire_days)).strftime("%Y-%m-%d %H:%M:%S")
    codes: List[str] = []
    conn = _get_db()
    try:
        cur = conn.cursor()
        for _i in range(body.count):
            inserted = False
            for _retry in range(5):
                code = _generate_cdk_code()
                try:
                    cur.execute(
                        "INSERT INTO shop_cdk (code, quota, vip_days, expires_at) VALUES (?, ?, ?, ?)",
                        (code, body.quota, body.vip_days, expires_at),
                    )
                    codes.append(code)
                    inserted = True
                    break
                except sqlite3.IntegrityError:
                    continue  # UNIQUE 冲突，重抽
            if not inserted:
                conn.rollback()
                raise HTTPException(500, "随机码连续 5 次冲突，请重试")

        # 4) 写审计日志（同事务）
        cur.execute(
            """INSERT INTO admin_audit_log
               (actor, action, payload, ip, ua, created_at)
               VALUES (?, 'generate_cdks', ?, ?, ?, datetime('now'))""",
            (
                (body.admin_username or "unknown")[:64],
                f"count={body.count} quota={body.quota} vip_days={body.vip_days} expire_days={body.expire_days}",
                real_ip,
                (req.headers.get("user-agent") or "")[:200],
            ),
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"批量发卡异常: {e}")
    finally:
        conn.close()

    return {"cdks": codes, "count": len(codes)}
