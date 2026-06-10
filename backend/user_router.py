"""
user_router.py — 用户中心路由

接口一览：
  GET    /api/v1/user/me              — 当前用户资料
  PATCH  /api/v1/user/nickname        — 修改昵称（查重）
  POST   /api/v1/user/avatar          — 上传头像（≤2MB jpg/png/webp）
  GET    /api/v1/user/preferences     — 读取偏好设置
  PUT    /api/v1/user/preferences     — 写入偏好设置
  GET    /api/v1/user/sessions        — 当前用户的活跃设备列表
  DELETE /api/v1/user/sessions/{jti}  — 踢出指定设备
  POST   /api/v1/user/logout          — 登出当前设备（撤销 jti）
"""

import os
import json
import hashlib
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Depends
from pydantic import BaseModel

from auth_deps import get_current_user, CurrentUser
from password_utils import validate_password, hash_password, verify_password

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/user", tags=["User Center"])

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.environ.get("DB_PATH", os.path.join(_THIS_DIR, "football_uk.db"))
AVATAR_DIR = os.path.join(_THIS_DIR, "static", "avatars")
os.makedirs(AVATAR_DIR, exist_ok=True)

# 偏好字段白名单（防止客户端塞入任意字段）
_PREF_ALLOWED = {"theme", "notify_lineup", "notify_postmatch"}
_PREF_DEFAULTS = {"theme": "dark", "notify_lineup": True, "notify_postmatch": False}

# 头像大小限制
MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2 MB
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# GET /me
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/me")
async def get_me(user: CurrentUser = Depends(get_current_user)):
    # 超管 (user_id=0) 无 DB 记录，直接从 JWT claims 返回合成资料
    if user.user_id == 0:
        return {
            "user_id":        0,
            "nickname":       user.nickname or "超级管理员",
            "avatar_url":     user.avatar_url or "",
            "role":           user.role or "admin",
            "vip_expires_at": None,
            "preferences":    _PREF_DEFAULTS.copy(),
            "created_at":     None,
            "openid_tail":    "ADMIN",
        }

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id, openid, nickname, avatar_url, role, vip_expires_at, preferences, created_at FROM users WHERE id=?",
            (user.user_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="用户记录不存在")

    prefs = _PREF_DEFAULTS.copy()
    try:
        prefs.update(json.loads(row["preferences"] or "{}"))
    except (json.JSONDecodeError, TypeError):
        pass

    openid = row["openid"] or ""
    return {
        "user_id":       row["id"],
        "nickname":      row["nickname"] or "足球探索者",
        "avatar_url":    row["avatar_url"] or "",
        "role":          row["role"],
        "vip_expires_at": row["vip_expires_at"],
        "preferences":   prefs,
        "created_at":    row["created_at"],
        "openid_tail":   openid[-6:] if len(openid) >= 6 else "***",
    }


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /nickname
# ─────────────────────────────────────────────────────────────────────────────

class NicknameRequest(BaseModel):
    nickname: str


@router.patch("/nickname")
async def update_nickname(body: NicknameRequest, user: CurrentUser = Depends(get_current_user)):
    name = body.nickname.strip()
    if not name:
        raise HTTPException(status_code=400, detail="昵称不能为空")
    if len(name) > 20:
        raise HTTPException(status_code=400, detail="昵称不能超过 20 个字符")

    name_lower = name.lower()
    conn = _get_conn()
    try:
        # 查重（排除自己）
        existing = conn.execute(
            "SELECT id FROM users WHERE nickname_lower=? AND id != ?",
            (name_lower, user.user_id)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="该昵称已被使用，请换一个")

        conn.execute(
            "UPDATE users SET nickname=?, nickname_lower=?, updated_at=datetime('now') WHERE id=?",
            (name, name_lower, user.user_id)
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok", "nickname": name}


# ─────────────────────────────────────────────────────────────────────────────
# POST /avatar
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    # 类型校验
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="仅支持 jpg / png / webp 格式")

    data = await file.read()
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="图片大小不能超过 2MB")

    # 文件名：user_{id}_{sha8}.{ext}
    ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
    ext = ext_map[content_type]
    sha8 = hashlib.sha256(data).hexdigest()[:8]
    filename = f"user_{user.user_id}_{sha8}.{ext}"
    filepath = os.path.join(AVATAR_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(data)

    # 相对 URL（FastAPI 挂载 /static）
    avatar_url = f"/static/avatars/{filename}"

    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE users SET avatar_url=?, updated_at=datetime('now') WHERE id=?",
            (avatar_url, user.user_id)
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok", "avatar_url": avatar_url}


# ─────────────────────────────────────────────────────────────────────────────
# GET/PUT /preferences
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/preferences")
async def get_preferences(user: CurrentUser = Depends(get_current_user)):
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT preferences FROM users WHERE id=?", (user.user_id,)
        ).fetchone()
    finally:
        conn.close()

    prefs = _PREF_DEFAULTS.copy()
    if row:
        try:
            prefs.update(json.loads(row["preferences"] or "{}"))
        except (json.JSONDecodeError, TypeError):
            pass
    return prefs


@router.put("/preferences")
async def update_preferences(request: Request, user: CurrentUser = Depends(get_current_user)):
    body = await request.json()
    # 白名单过滤
    filtered = {k: v for k, v in body.items() if k in _PREF_ALLOWED}
    if not filtered:
        raise HTTPException(status_code=400, detail=f"支持的字段：{list(_PREF_ALLOWED)}")

    # 读取现有并合并
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT preferences FROM users WHERE id=?", (user.user_id,)
        ).fetchone()
        current = _PREF_DEFAULTS.copy()
        if row:
            try:
                current.update(json.loads(row["preferences"] or "{}"))
            except (json.JSONDecodeError, TypeError):
                pass
        current.update(filtered)

        conn.execute(
            "UPDATE users SET preferences=?, updated_at=datetime('now') WHERE id=?",
            (json.dumps(current, ensure_ascii=False), user.user_id)
        )
        conn.commit()
    finally:
        conn.close()

    return current


# ─────────────────────────────────────────────────────────────────────────────
# GET /sessions  —  当前用户所有活跃设备
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/sessions")
async def list_sessions(user: CurrentUser = Depends(get_current_user)):
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT jti, device_label, ip, created_at, last_seen_at
                 FROM user_sessions
                WHERE user_id=? AND revoked_at IS NULL
                ORDER BY created_at DESC""",
            (user.user_id,)
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "jti":          r["jti"],
            "device_label": r["device_label"] or "未知设备",
            "ip":           r["ip"] or "",
            "created_at":   r["created_at"],
            "last_seen_at": r["last_seen_at"],
            "is_current":   r["jti"] == user.jti,
        }
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /sessions/{jti}  —  踢出指定设备
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/sessions/{target_jti}")
async def revoke_session(target_jti: str, user: CurrentUser = Depends(get_current_user)):
    if target_jti == user.jti:
        raise HTTPException(status_code=400, detail="不能踢出当前正在使用的设备，请使用退出登录")

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT jti FROM user_sessions WHERE jti=? AND user_id=? AND revoked_at IS NULL",
            (target_jti, user.user_id)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="会话不存在或已失效")

        conn.execute(
            "UPDATE user_sessions SET revoked_at=datetime('now'), revoke_reason='manual' WHERE jti=?",
            (target_jti,)
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok", "revoked_jti": target_jti}


# ─────────────────────────────────────────────────────────────────────────────
# POST /logout  —  登出当前设备
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/logout")
async def logout(user: CurrentUser = Depends(get_current_user)):
    if not user.jti:
        return {"status": "ok", "message": "旧格式 token，无需撤销"}

    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE user_sessions SET revoked_at=datetime('now'), revoke_reason='logout' WHERE jti=? AND user_id=?",
            (user.jti, user.user_id)
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# POST /password  —  自助修改密码
# ─────────────────────────────────────────────────────────────────────────────

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    """用户自助修改密码。需要提供原密码验证身份。"""
    from rate_limit import hit_request
    hit_request("user_password", request, max_per_min=5)

    if user.user_id == 0:
        raise HTTPException(status_code=400, detail="超管账号不支持此操作")

    err = validate_password(body.new_password)
    if err:
        raise HTTPException(status_code=422, detail=err)

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id=? AND auth_source='username'",
            (user.user_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="该账号不支持密码登录")
        if not verify_password(body.old_password, row["password_hash"] or ""):
            raise HTTPException(status_code=401, detail="原密码错误")
        if body.old_password == body.new_password:
            raise HTTPException(status_code=422, detail="新密码不能与原密码相同")

        new_hash = hash_password(body.new_password)
        conn.execute(
            "UPDATE users SET password_hash=?, updated_at=datetime('now') WHERE id=?",
            (new_hash, user.user_id)
        )
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        log.error(f"[ChangePassword] DB error: {e}")
        raise HTTPException(status_code=500, detail="修改失败，请稍后重试")
    finally:
        conn.close()

    return {"status": "ok"}
