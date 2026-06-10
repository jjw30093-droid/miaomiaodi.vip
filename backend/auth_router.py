"""
auth_router.py — 用户名/密码注册登录路由

路由：
  POST /api/v1/auth/register                    — 公开，直接注册（写入 users，无审核）
  POST /api/v1/auth/login                       — 公开，用户名+密码登录
  GET  /api/v1/admin/registrations/pending      — Admin，列待审核申请（历史兼容，当前不再使用）
  POST /api/v1/admin/registrations/{id}/approve — Admin，批准并迁移到 users（历史兼容）
  POST /api/v1/admin/registrations/{id}/reject  — Admin，拒绝申请（历史兼容）
  GET  /api/v1/admin/users                      — Admin，列全部用户

反滥用：同一 device_id + 同一 IP 只允许注册一个账号。

# 用户名注册用户：users.openid = 'USER_' || lower(username)，users.auth_source = 'username'
# 这样 openid UNIQUE 约束不冲突，且日后扫码绑定时可识别"未绑微信的用户名账号"
# 查询纯 WeChat 用户时加：WHERE openid NOT LIKE 'USER_%'
"""

import os
import re
import time
import secrets
import sqlite3
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Header, Depends
from pydantic import BaseModel

from auth_deps import issue_session_token
from rate_limit import hit_request, client_ip as _client_ip
from password_utils import validate_password, hash_password, verify_password

try:
    from notify_utils import notify as _notify
except ImportError:
    _notify = None

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Username Auth"])

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(_THIS_DIR, "football_uk.db"))
ADMIN_SECRET_TOKEN = os.environ.get("ADMIN_SECRET_TOKEN", "")

USERNAME_MIN_LEN = 2

# 注册限流：每 IP 每小时最多 5 次（窗口 3600s）
_register_rate: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    password: str
    nickname: Optional[str] = None
    device_id: Optional[str] = None   # 前端生成的设备指纹（可选）


class LoginRequest(BaseModel):
    username: str
    password: str


class RejectRequest(BaseModel):
    reason: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# 校验函数
# ─────────────────────────────────────────────────────────────────────────────

def validate_username(name: str) -> Optional[str]:
    """返回错误消息或 None"""
    if not name or len(name.strip()) < USERNAME_MIN_LEN:
        return f"用户名长度不能少于 {USERNAME_MIN_LEN} 个字符"
    if len(name) > 32:
        return "用户名长度不能超过 32 个字符"
    if name.strip() != name:
        return "用户名首尾不能有空格"
    if any(ord(c) < 0x20 for c in name):
        return "用户名包含非法字符"
    return None



def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _verify_admin(x_admin_token: str = Header(default="")) -> None:
    if not ADMIN_SECRET_TOKEN:
        raise HTTPException(status_code=503, detail="ADMIN_SECRET_TOKEN 未配置")
    if not secrets.compare_digest(x_admin_token, ADMIN_SECRET_TOKEN):
        raise HTTPException(status_code=401, detail="Admin token 无效")


def _write_audit_log(conn: sqlite3.Connection, action: str, actor: str, payload: str, ip: str, ua: str) -> None:
    try:
        conn.execute(
            """INSERT INTO admin_audit_log (action, actor, payload, ip, user_agent, created_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (action, actor, payload, ip, ua)
        )
    except Exception as e:
        log.warning(f"[Auth] audit_log write failed: {e}")


def _rate_limit_register(ip: str) -> None:
    """注册限流：每 IP 每小时最多 5 次"""
    now = time.time()
    bucket = _register_rate.get(ip)
    if not bucket or now > bucket["reset_at"]:
        _register_rate[ip] = {"count": 1, "reset_at": now + 3600}
    else:
        bucket["count"] += 1
        if bucket["count"] > 5:
            raise HTTPException(status_code=429, detail="注册请求过于频繁，请 1 小时后再试")


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/auth/register
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/auth/register")
async def register(body: RegisterRequest, request: Request):
    """注册入口已关闭。账号由管理员通过后台开通。"""
    raise HTTPException(status_code=403, detail="注册已关闭，请联系管理员开通账号")
    ip = _client_ip(request)
    _rate_limit_register(ip)

    username = body.username.strip()
    password = body.password
    nickname = (body.nickname or "").strip() or username
    device_id = (body.device_id or "").strip()[:128] or None

    err = validate_username(username)
    if err:
        raise HTTPException(status_code=422, detail=err)

    err = validate_password(password)
    if err:
        raise HTTPException(status_code=422, detail=err)

    password_hash = hash_password(password)
    openid_placeholder = f"USER_{username.lower()}"

    conn = _get_db()
    try:
        # 1. 用户名唯一性检查
        existing_user = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing_user:
            raise HTTPException(status_code=409, detail="用户名已被使用，请换一个")

        # 2. 反滥用：同一 device_id + 同一 IP 只允许注册一个账号
        if device_id:
            dupe = conn.execute(
                "SELECT 1 FROM users WHERE register_device_id = ? AND register_ip = ? "
                "AND auth_source = 'username'",
                (device_id, ip)
            ).fetchone()
            if dupe:
                log.warning("[register-409-device] ip=%s device_id=%s username=%s", ip, device_id, username)
                raise HTTPException(
                    status_code=409,
                    detail="该设备已注册过账号，每台设备仅允许注册一个账号"
                )

        # 3. 直接写入 users 表（无审核流程）
        conn.execute(
            """INSERT INTO users
               (openid, username, password_hash, nickname, role, auth_source,
                register_ip, register_device_id, created_at)
               VALUES (?, ?, ?, ?, 'registered', 'username',
                       ?, ?, datetime('now'))""",
            (openid_placeholder, username, password_hash, nickname, ip, device_id)
        )
        conn.commit()

        # 获取新建用户 ID，用于签发 JWT
        new_user = conn.execute(
            "SELECT id, nickname, role, avatar_url, vip_expires_at FROM users WHERE username = ?",
            (username,)
        ).fetchone()

    except HTTPException:
        raise
    except sqlite3.IntegrityError as e:
        conn.rollback()
        log.error(f"[Auth/Register] IntegrityError: {e}")
        raise HTTPException(status_code=409, detail="用户名已被使用，请换一个")
    except Exception as e:
        conn.rollback()
        log.error(f"[Auth/Register] DB error: {e}")
        raise HTTPException(status_code=500, detail="注册失败，请稍后重试")
    finally:
        conn.close()

    if _notify:
        try:
            _notify(f"新注册用户：{username}（昵称：{nickname}，IP：{ip}）")
        except Exception:
            pass

    # 签发 JWT，注册成功直接可登录
    token = issue_session_token(
        user_id=new_user["id"],
        role=new_user["role"] or "registered",
        nickname=new_user["nickname"] or username,
        avatar_url=new_user["avatar_url"] or "",
        vip_expires_at=new_user["vip_expires_at"],
        ip=ip,
        ua=request.headers.get("user-agent", "")[:512],
    )

    return {
        "status": "registered",
        "message": "注册成功",
        "token": token,
        "user": {
            "user_id": new_user["id"],
            "nickname": new_user["nickname"] or username,
            "role": new_user["role"] or "registered",
            "avatar_url": new_user["avatar_url"] or "",
            "vip_expires_at": new_user["vip_expires_at"],
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/auth/login
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/auth/login")
async def login(body: LoginRequest, request: Request):
    """用户名+密码登录。返回 JWT token。"""
    hit_request("auth_login", request, max_per_min=20)

    username = body.username.strip()
    password = body.password

    conn = _get_db()
    try:
        # 查已审核通过的 users 表
        user_row = conn.execute(
            "SELECT id, username, password_hash, nickname, role, avatar_url, vip_expires_at, "
            "COALESCE(disabled, 0) as disabled "
            "FROM users WHERE username = ? AND auth_source = 'username'",
            (username,)
        ).fetchone()

        if user_row:
            if user_row["disabled"]:
                raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")
            if not verify_password(password, user_row["password_hash"] or ""):
                raise HTTPException(status_code=401, detail="用户名或密码错误")
            token = issue_session_token(
                user_id=user_row["id"],
                role=user_row["role"] or "registered",
                nickname=user_row["nickname"] or username,
                avatar_url=user_row["avatar_url"] or "",
                vip_expires_at=user_row["vip_expires_at"],
                ip=_client_ip(request),
                ua=request.headers.get("user-agent", "")[:512],
            )
            return {
                "token": token,
                "user": {
                    "user_id": user_row["id"],
                    "nickname": user_row["nickname"] or username,
                    "role": user_row["role"] or "registered",
                    "avatar_url": user_row["avatar_url"] or "",
                    "vip_expires_at": user_row["vip_expires_at"],
                },
            }

        # 检查是否在 pending_registrations 中
        pending = conn.execute(
            "SELECT status FROM pending_registrations WHERE username = ?", (username,)
        ).fetchone()
        if pending:
            if pending["status"] == "pending":
                raise HTTPException(status_code=403, detail="账号待管理员审核，请耐心等待")
            elif pending["status"] == "rejected":
                raise HTTPException(status_code=403, detail="注册申请已被拒绝，如有疑问请联系管理员")

        raise HTTPException(status_code=401, detail="用户名或密码错误")
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Admin endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/registrations/pending")
async def list_pending_registrations(
    _: None = Depends(_verify_admin),
):
    """列出 status='pending' 的注册申请。"""
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT id, username, nickname, created_at, ip FROM pending_registrations "
            "WHERE status = 'pending' ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("/admin/registrations/{reg_id}/approve")
async def approve_registration(
    reg_id: int,
    request: Request,
    _: None = Depends(_verify_admin),
):
    """批准注册申请，把 pending_registrations 行迁移到 users 表。"""
    ua = request.headers.get("user-agent", "")[:256]
    ip = _client_ip(request)

    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM pending_registrations WHERE id = ? AND status = 'pending'", (reg_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="申请不存在或已处理")

        username = row["username"]
        openid_placeholder = f"USER_{username.lower()}"

        conn.execute(
            """INSERT INTO users (openid, username, password_hash, nickname, role, auth_source, created_at)
               VALUES (?, ?, ?, ?, 'registered', 'username', datetime('now'))""",
            (openid_placeholder, username, row["password_hash"], row["nickname"])
        )

        conn.execute(
            """UPDATE pending_registrations
               SET status='approved', approved_at=datetime('now'), approved_by='admin'
               WHERE id=?""",
            (reg_id,)
        )

        _write_audit_log(conn, "approve_registration", "admin", f"reg_id={reg_id} username={username}", ip, ua)
        conn.commit()
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在于 users 表中")
    except Exception as e:
        conn.rollback()
        log.error(f"[Auth/Approve] error: {e}")
        raise HTTPException(status_code=500, detail="审批失败")
    finally:
        conn.close()

    return {"status": "approved", "username": username}


@router.post("/admin/registrations/{reg_id}/reject")
async def reject_registration(
    reg_id: int,
    body: RejectRequest,
    request: Request,
    _: None = Depends(_verify_admin),
):
    """拒绝注册申请。"""
    ua = request.headers.get("user-agent", "")[:256]
    ip = _client_ip(request)
    reason = (body.reason or "").strip() or "管理员拒绝"

    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT username FROM pending_registrations WHERE id = ? AND status = 'pending'", (reg_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="申请不存在或已处理")

        conn.execute(
            """UPDATE pending_registrations
               SET status='rejected', rejected_reason=?, approved_at=datetime('now'), approved_by='admin'
               WHERE id=?""",
            (reason, reg_id)
        )
        _write_audit_log(conn, "reject_registration", "admin",
                         f"reg_id={reg_id} username={row['username']} reason={reason}", ip, ua)
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        log.error(f"[Auth/Reject] error: {e}")
        raise HTTPException(status_code=500, detail="操作失败")
    finally:
        conn.close()

    return {"status": "rejected"}


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/admin/users  — 列全部已注册用户（管理后台专用）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/admin/users")
async def list_all_users(
    _: None = Depends(_verify_admin),
):
    """列出 users 表全部用户（含微信 + 用户名注册）。"""
    conn = _get_db()
    try:
        rows = conn.execute(
            """SELECT id, nickname, username, role, auth_source,
                      COALESCE(disabled, 0) as disabled,
                      register_ip, register_device_id, created_at
               FROM users
               ORDER BY id DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 新管理员端点：建号 / 重置密码 / 停用 / 删除
# ─────────────────────────────────────────────────────────────────────────────

class AdminCreateUserRequest(BaseModel):
    username: str
    password: str
    nickname: Optional[str] = None


class AdminResetPasswordRequest(BaseModel):
    new_password: str


class AdminDisableRequest(BaseModel):
    disabled: int  # 0=启用, 1=停用


def _revoke_all_sessions(conn: sqlite3.Connection, user_id: int) -> None:
    """吊销某用户全部活跃 session（踢下线）。"""
    conn.execute(
        "UPDATE user_sessions SET revoked_at=datetime('now'), revoke_reason='admin_action' "
        "WHERE user_id=? AND revoked_at IS NULL",
        (user_id,)
    )


@router.post("/admin/users")
async def admin_create_user(
    body: AdminCreateUserRequest,
    request: Request,
    _: None = Depends(_verify_admin),
):
    """管理员建号：创建 role=vip、永久有效的账号。"""
    username = body.username.strip()
    password = body.password
    nickname = (body.nickname or "").strip() or username

    err = validate_username(username)
    if err:
        raise HTTPException(status_code=422, detail=err)
    err = validate_password(password)
    if err:
        raise HTTPException(status_code=422, detail=err)

    password_hash = hash_password(password)
    openid_placeholder = f"USER_{username.lower()}"
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]

    conn = _get_db()
    try:
        existing = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="用户名已存在")

        conn.execute(
            """INSERT INTO users
               (openid, username, password_hash, nickname, role, auth_source,
                vip_expires_at, disabled, register_ip, created_at)
               VALUES (?, ?, ?, ?, 'vip', 'username', NULL, 0, ?, datetime('now'))""",
            (openid_placeholder, username, password_hash, nickname, ip)
        )
        conn.commit()

        new_user = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()

        _write_audit_log(conn, "admin_create_user", "admin",
                         f"username={username}", ip, ua)
        conn.commit()
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在")
    except Exception as e:
        conn.rollback()
        log.error(f"[AdminCreateUser] DB error: {e}")
        raise HTTPException(status_code=500, detail="建号失败，请稍后重试")
    finally:
        conn.close()

    return {"status": "ok", "user_id": new_user["id"], "username": username, "role": "vip"}


@router.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: int,
    body: AdminResetPasswordRequest,
    request: Request,
    _: None = Depends(_verify_admin),
):
    """管理员重置某用户密码，并踢出所有活跃 session。"""
    err = validate_password(body.new_password)
    if err:
        raise HTTPException(status_code=422, detail=err)

    new_hash = hash_password(body.new_password)
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]

    conn = _get_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")

        conn.execute(
            "UPDATE users SET password_hash=?, updated_at=datetime('now') WHERE id=?",
            (new_hash, user_id)
        )
        _revoke_all_sessions(conn, user_id)
        _write_audit_log(conn, "admin_reset_password", "admin",
                         f"user_id={user_id}", ip, ua)
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        log.error(f"[AdminResetPassword] DB error: {e}")
        raise HTTPException(status_code=500, detail="重置失败")
    finally:
        conn.close()

    return {"status": "ok"}


@router.post("/admin/users/{user_id}/disable")
async def admin_disable_user(
    user_id: int,
    body: AdminDisableRequest,
    request: Request,
    _: None = Depends(_verify_admin),
):
    """停用(disabled=1)或启用(disabled=0)某账号。停用时踢出所有 session。"""
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]

    conn = _get_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")

        conn.execute(
            "UPDATE users SET disabled=?, updated_at=datetime('now') WHERE id=?",
            (1 if body.disabled else 0, user_id)
        )
        if body.disabled:
            _revoke_all_sessions(conn, user_id)
        action = "admin_disable_user" if body.disabled else "admin_enable_user"
        _write_audit_log(conn, action, "admin", f"user_id={user_id}", ip, ua)
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        log.error(f"[AdminDisableUser] DB error: {e}")
        raise HTTPException(status_code=500, detail="操作失败")
    finally:
        conn.close()

    return {"status": "ok"}


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    request: Request,
    _: None = Depends(_verify_admin),
):
    """永久删除某账号及其所有 session。"""
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]

    conn = _get_db()
    try:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")

        _revoke_all_sessions(conn, user_id)
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        _write_audit_log(conn, "admin_delete_user", "admin",
                         f"user_id={user_id} username={row['username']}", ip, ua)
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        log.error(f"[AdminDeleteUser] DB error: {e}")
        raise HTTPException(status_code=500, detail="删除失败")
    finally:
        conn.close()

    return {"status": "ok"}
