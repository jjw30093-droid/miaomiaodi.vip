"""
auth_deps.py — FastAPI JWT 依赖注入层 + 签发工具

职责：
  1. 解析 Authorization: Bearer <token>，返回用户层级枚举。
  2. 提供 make_jwt() 给所有路由统一签发 Token（避免各自重复实现）。
  3. 提供 issue_session_token() 统一处理设备会话限制与 jti 白名单写入。

三级层级：
  GUEST      (0) — 无 JWT 或 JWT 无效
  REGISTERED (1) — 有效 JWT，role='registered' 或 'admin' 但非 VIP
  VIP        (2) — 有效 JWT，role='vip' 且 vip_expires_at 未到期
"""

import os
import uuid
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from dataclasses import dataclass
from typing import Optional
from fastapi import Request, HTTPException, Response, status
from jose import jwt, JWTError

log = logging.getLogger(__name__)

_jwt_secret_raw = os.environ.get("JWT_SECRET", "")
if not _jwt_secret_raw:
    raise RuntimeError(
        "[FATAL] 环境变量 JWT_SECRET 未配置。"
        "请在 .env 或 PM2 ecosystem 中设置一个足够长的随机字符串后再启动服务。"
    )
JWT_SECRET      = _jwt_secret_raw
JWT_ALGORITHM   = "HS256"
# 默认 14 天：平衡"不频繁打扰用户"与"长期暴露密钥风险"。
# 被 kicked_by_limit 的旧 jti 仍会被 user_sessions 白名单立刻拦截。
JWT_EXPIRE_DAYS = int(os.environ.get("JWT_EXPIRE_DAYS", "30"))

# 超管专用 JWT Secret（2026-04-30 新增）
# user_id=0 的 token 必须用此 secret 验签，与普通用户路径隔离。
# 未配置时：user_id=0 请求一律拒绝（防止裸跑使用 JWT_SECRET 代替）。
SUPER_ADMIN_JWT_SECRET = os.environ.get("SUPER_ADMIN_JWT_SECRET", "")

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(_THIS_DIR, "football_uk.db"))

# 最多允许同时在线的设备数，超出后踢出最早登录的设备
MAX_DEVICES = int(os.environ.get("MAX_DEVICES_PER_USER", "2"))


# ─────────────────────────────────────────────────────────────────────────────
# 枚举 & 数据类
# ─────────────────────────────────────────────────────────────────────────────

class UserTier(IntEnum):
    GUEST      = 0
    REGISTERED = 1
    VIP        = 2


@dataclass
class CurrentUser:
    tier:       UserTier
    user_id:    int | None = None
    role:       str | None = None
    nickname:   str | None = None
    avatar_url: str | None = None
    jti:        str | None = None

    @property
    def is_guest(self) -> bool:
        return self.tier == UserTier.GUEST

    @property
    def is_vip(self) -> bool:
        if os.environ.get("ENABLE_VIP_GATING", "0") == "1":
            return self.tier == UserTier.VIP
        return self.tier >= UserTier.REGISTERED

    @property
    def is_registered(self) -> bool:
        return self.tier >= UserTier.REGISTERED


# ─────────────────────────────────────────────────────────────────────────────
# JWT 签发（全项目统一入口）
# ─────────────────────────────────────────────────────────────────────────────

def make_jwt(
    user_id: int,
    role: str,
    nickname: str = "足球探索者",
    avatar_url: str = "",
    vip_expires_at: str | None = None,
    jti: str | None = None,
) -> str:
    """
    签发 JWT。

    参数：
      user_id        — users.id
      role           — 角色标识: 'registered', 'vip', 'admin'
      nickname       — 用户昵称
      avatar_url     — 用户头像
      vip_expires_at — VIP 到期时间（ISO-8601 字符串，UTC），None 表示无 VIP
      jti            — 会话唯一 ID（写入 user_sessions 后传入），None 则不写
    """
    now = datetime.now(timezone.utc)
    is_vip_flag = (role == "vip")
    # 再次检查 vip_expires_at 是否真的未到期
    if is_vip_flag and vip_expires_at:
        try:
            exp_dt = datetime.fromisoformat(vip_expires_at)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp_dt:
                is_vip_flag = False
        except (ValueError, TypeError):
            is_vip_flag = False

    payload: dict = {
        "user_id":    user_id,
        "role":       role,
        "nickname":   nickname,
        "avatar_url": avatar_url,
        "is_vip":     is_vip_flag,   # 修复 bug：frontend parseApiJwt 依赖此字段
        "exp":        now + timedelta(days=JWT_EXPIRE_DAYS),
    }
    if vip_expires_at:
        payload["vip_expires_at"] = vip_expires_at
    if jti:
        payload["jti"] = jti

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


# ─────────────────────────────────────────────────────────────────────────────
# 会话签发（设备限制 + jti 白名单写入）
# ─────────────────────────────────────────────────────────────────────────────

def issue_session_token(
    user_id: int,
    role: str,
    nickname: str = "足球探索者",
    avatar_url: str = "",
    vip_expires_at: str | None = None,
    ip: str = "",
    ua: str = "",
    device_label: str | None = None,
    reuse_jti: str | None = None,
) -> str:
    """
    签发带会话的 JWT，并管理设备并发限制。

    - reuse_jti: 若非 None，沿用已有的 jti（CDK 兑换续签时用，避免踢出自己）。
    - 若当前活跃会话数 >= MAX_DEVICES，踢出创建时间最早的那条（revoke_reason='kicked_by_limit'）。
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        if reuse_jti:
            jti = reuse_jti
            # 续签：更新 last_seen_at 即可，不新增行
            conn.execute(
                "UPDATE user_sessions SET last_seen_at=datetime('now') WHERE jti=?",
                (jti,)
            )
        else:
            # 检查活跃会话数
            cur = conn.execute(
                "SELECT COUNT(*) FROM user_sessions WHERE user_id=? AND revoked_at IS NULL",
                (user_id,)
            )
            active_count = cur.fetchone()[0]

            if active_count >= MAX_DEVICES:
                # 踢出最早登录的那条
                old = conn.execute(
                    "SELECT jti FROM user_sessions WHERE user_id=? AND revoked_at IS NULL ORDER BY created_at ASC LIMIT 1",
                    (user_id,)
                ).fetchone()
                if old:
                    conn.execute(
                        "UPDATE user_sessions SET revoked_at=datetime('now'), revoke_reason='kicked_by_limit' WHERE jti=?",
                        (old["jti"],)
                    )
                    log.info(f"[Auth] 踢出设备 jti={old['jti']} (user_id={user_id}, 超出 {MAX_DEVICES} 台限制)")

            # 生成新 jti 并写入白名单
            jti = str(uuid.uuid4())
            if not device_label:
                device_label = _build_device_label(ua, ip)
            conn.execute(
                """INSERT INTO user_sessions (jti, user_id, device_label, user_agent, ip)
                   VALUES (?, ?, ?, ?, ?)""",
                (jti, user_id, device_label, ua[:512] if ua else None, ip)
            )

        conn.commit()
    finally:
        conn.close()

    return make_jwt(
        user_id=user_id,
        role=role,
        nickname=nickname,
        avatar_url=avatar_url,
        vip_expires_at=vip_expires_at,
        jti=jti,
    )


def _build_device_label(ua: str, ip: str) -> str:
    """从 User-Agent 构建可读的设备标签。"""
    if not ua:
        return f"未知设备 · {ip[:16]}"
    ua_lower = ua.lower()
    if "iphone" in ua_lower:
        device = "iPhone"
    elif "ipad" in ua_lower:
        device = "iPad"
    elif "android" in ua_lower:
        device = "Android"
    elif "macintosh" in ua_lower or "mac os" in ua_lower:
        device = "Mac"
    elif "windows" in ua_lower:
        device = "Windows"
    else:
        device = "设备"

    if "chrome" in ua_lower and "edg" not in ua_lower:
        browser = "Chrome"
    elif "safari" in ua_lower and "chrome" not in ua_lower:
        browser = "Safari"
    elif "firefox" in ua_lower:
        browser = "Firefox"
    elif "edg" in ua_lower:
        browser = "Edge"
    else:
        browser = "浏览器"

    return f"{device} · {browser}"


# ─────────────────────────────────────────────────────────────────────────────
# 请求级鉴权（软鉴权）
# ─────────────────────────────────────────────────────────────────────────────

def get_optional_user(request: Request) -> CurrentUser:
    """
    软鉴权依赖：无 token 时返回 GUEST，不抛异常。
    需要强制登录的接口自行检查 user.is_guest 后抛 401。

    jti 白名单校验：
      - 若 payload 含 jti，检查 user_sessions 是否已被 revoke。
      - 若已 revoke，在响应头写入 X-Session-Revoked: 1，并返回 GUEST。
      - 旧 token（无 jti）不强制校验，仅记 warning，兼容过渡期。
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return CurrentUser(tier=UserTier.GUEST)

    token = auth.removeprefix("Bearer ").strip()
    try:
        # 2026-04-30: 双 secret 路由
        # peek user_id（不验签），决定用哪个 secret
        try:
            _unverified = jwt.get_unverified_claims(token)
            _peek_uid   = _unverified.get("user_id")
        except Exception:
            _peek_uid = None

        if _peek_uid == 0:
            # 超管路径：必须用 SUPER_ADMIN_JWT_SECRET
            if not SUPER_ADMIN_JWT_SECRET:
                log.error("[Auth] user_id=0 token 收到，但 SUPER_ADMIN_JWT_SECRET 未配置，拒绝")
                return CurrentUser(tier=UserTier.GUEST)
            try:
                payload = jwt.decode(token, SUPER_ADMIN_JWT_SECRET, algorithms=[JWT_ALGORITHM])
            except JWTError:
                # 兼容窗口：旧 super admin token 用 JWT_SECRET 签发，降级试一次
                try:
                    payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
                    log.warning("[Auth] LEGACY super admin token 仍在使用（用 JWT_SECRET 签发），请重新登录以切换到新 secret")
                except JWTError:
                    return CurrentUser(tier=UserTier.GUEST)
        else:
            # 普通用户路径：用 JWT_SECRET
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

        user_id    = payload.get("user_id")
        role       = payload.get("role", "registered")
        nickname   = payload.get("nickname")
        avatar_url = payload.get("avatar_url")
        jti        = payload.get("jti")
        is_vip     = role == "vip"

        # 检查 VIP 是否真的仍在有效期内
        vip_expires_at = payload.get("vip_expires_at")
        if is_vip and vip_expires_at:
            try:
                exp_dt = datetime.fromisoformat(vip_expires_at)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > exp_dt:
                    is_vip = False
                    role = "registered"
            except (ValueError, TypeError):
                is_vip = False
                role = "registered"

        # jti 白名单校验
        if jti:
            try:
                conn = sqlite3.connect(DB_PATH, timeout=5)
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT revoked_at FROM user_sessions WHERE jti=?", (jti,)
                ).fetchone()
                conn.execute(
                    "UPDATE user_sessions SET last_seen_at=datetime('now') WHERE jti=?", (jti,)
                )
                conn.commit()
                conn.close()
                if row and row["revoked_at"]:
                    # 已被踢出：标记响应头，返回 GUEST
                    try:
                        request.state.session_revoked = True
                    except Exception:
                        pass
                    return CurrentUser(tier=UserTier.GUEST)
            except Exception as e:
                log.warning(f"[Auth] jti 校验异常（宽松处理）: {e}")
        else:
            log.debug(f"[Auth] token 无 jti 字段（旧 token 兼容模式）user_id={user_id}")

        tier = UserTier.VIP if is_vip else UserTier.REGISTERED
        return CurrentUser(
            tier=tier,
            user_id=user_id,
            role=role,
            nickname=nickname,
            avatar_url=avatar_url,
            jti=jti,
        )

    except JWTError:
        return CurrentUser(tier=UserTier.GUEST)


def get_current_user(request: Request) -> CurrentUser:
    """严格拦截：必须带有合法 Token"""
    user = get_optional_user(request)
    if user.is_guest:
        revoked = getattr(request.state, "session_revoked", False)
        if revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="账号已在其他设备登录，当前会话已失效",
                headers={"X-Session-Revoked": "1"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid credentials are required"
        )
    return user


def get_vip_user(request: Request) -> CurrentUser:
    """严格拦截：必须带有合法的 VIP Token 且未过期"""
    user = get_optional_user(request)
    if user.is_guest:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid credentials are required"
        )
    if not user.is_vip:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation requires VIP privileges"
        )
    return user
