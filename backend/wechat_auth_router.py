"""
微信公众号验证码登录 + JWT 鉴权路由
依赖：pip install python-jose[cryptography]

环境变量：
  WECHAT_TOKEN   — 微信公众号后台配置的 Token（服务器验证用）
  JWT_SECRET     — JWT 签名密钥（生产环境必须修改）
  DB_PATH        — SQLite 数据库路径（默认同项目路径）
"""

import os
import uuid
import random
import hashlib
import time
import sqlite3
import logging
import xml.etree.ElementTree as ET
from typing import Optional

import httpx
from fastapi import APIRouter, Request, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse
from auth_deps import make_jwt, issue_session_token  # 统一 JWT 签发，避免重复实现
from rate_limit import hit as _rate_hit, client_ip as _client_ip

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 微信账号 access_token（公众号接口调用凭证，用于拉取用户信息）
# ---------------------------------------------------------------------------
WECHAT_APPID     = os.environ.get("WECHAT_APPID", "")
WECHAT_APPSECRET = os.environ.get("WECHAT_APPSECRET", "")

_wx_access_token: str = ""
_wx_token_expires: float = 0.0


async def _get_wx_access_token() -> str:
    """获取/刷新公众号 access_token（有效期 7200s，提前 60s 刷新）。"""
    global _wx_access_token, _wx_token_expires
    if not WECHAT_APPID or not WECHAT_APPSECRET:
        return ""
    if _wx_access_token and time.time() < _wx_token_expires:
        return _wx_access_token
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://api.weixin.qq.com/cgi-bin/token",
                params={"grant_type": "client_credential",
                        "appid": WECHAT_APPID,
                        "secret": WECHAT_APPSECRET},
            )
            data = resp.json()
        if "access_token" in data:
            _wx_access_token = data["access_token"]
            _wx_token_expires = time.time() + data.get("expires_in", 7200) - 60
            return _wx_access_token
        log.warning("[WeChatAuth] access_token 获取失败: %s", data)
    except Exception as e:
        log.warning("[WeChatAuth] access_token 请求异常: %s", e)
    return ""


async def _fetch_wx_userinfo(openid: str) -> tuple[str, str]:
    """
    拉取微信用户的 nickname 和 headimgurl。
    返回 (nickname, headimgurl)；失败时返回 ('足球探索者', '')。
    """
    token = await _get_wx_access_token()
    if not token:
        return "足球探索者", ""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://api.weixin.qq.com/cgi-bin/user/info",
                params={"access_token": token, "openid": openid, "lang": "zh_CN"},
            )
            data = resp.json()
        if "nickname" in data:
            return data.get("nickname", "足球探索者"), data.get("headimgurl", "")
        log.warning("[WeChatAuth] 用户信息获取失败: %s", data)
    except Exception as e:
        log.warning("[WeChatAuth] 用户信息请求异常: %s", e)
    return "足球探索者", ""

router = APIRouter(prefix="/api/v1/auth/wechat", tags=["WeChat Auth"])

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(_THIS_DIR, "football_uk.db"))

_wechat_token_raw = os.environ.get("WECHAT_TOKEN", "")
if not _wechat_token_raw:
    import logging as _log
    _log.warning(
        "[WeChatAuth] WECHAT_TOKEN 未配置 —— 所有微信 Webhook 签名验证将失败。"
        "请在 .env 中设置与微信公众平台一致的 Token 后重启服务。"
    )
WECHAT_TOKEN = _wechat_token_raw

# 验证码有效期（秒）
CODE_TTL = 300

# ---------------------------------------------------------------------------
# 内存 Session 池  session_id -> {code, openid, verified, expires_at}
# ---------------------------------------------------------------------------
_sessions: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# DB 初始化（首次导入时执行）
# ---------------------------------------------------------------------------
def _init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            openid         TEXT UNIQUE NOT NULL,      -- 微信 OpenID，系统唯一凭证
            nickname       TEXT DEFAULT '足球探索者', -- 默认昵称
            avatar_url     TEXT DEFAULT '',           -- 用户头像URL
            role           TEXT DEFAULT 'registered', -- 角色标识：guest, registered, vip, admin
            vip_expires_at DATETIME,                  -- VIP 到期时间 (ISO-8601 UTC)
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


_init_db()


# ---------------------------------------------------------------------------
# 内部工具函数
# ---------------------------------------------------------------------------
def _cleanup_sessions() -> None:
    """惰性清理过期 session，避免内存泄漏。"""
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if s["expires_at"] < now]
    for sid in expired:
        del _sessions[sid]


def _verify_wechat_signature(signature: str, timestamp: str, nonce: str) -> bool:
    """校验微信服务器请求的合法性（SHA1 签名）。"""
    items = sorted([WECHAT_TOKEN, timestamp, nonce])
    digest = hashlib.sha1("".join(items).encode()).hexdigest()
    return digest == signature



# ---------------------------------------------------------------------------
# 接口 1：前端请求验证码
# ---------------------------------------------------------------------------
@router.post("/code")
async def create_wechat_code(request: Request):
    """
    前端调用，生成一个 4 位数验证码和对应的 session_id。
    前端展示验证码，引导用户把验证码发送到微信公众号。
    """
    _rate_hit("wechat_code", _client_ip(request), 10)
    _cleanup_sessions()

    code = str(random.randint(1000, 9999))
    session_id = str(uuid.uuid4())
    _sessions[session_id] = {
        "code": code,
        "openid": None,
        "verified": False,
        "expires_at": time.time() + CODE_TTL,
    }
    return {
        "session_id": session_id,
        "code": code,
        "expires_in": CODE_TTL,
    }


# ---------------------------------------------------------------------------
# 接口 2：微信服务器 Webhook（GET = URL 验证，POST = 消息接收）
# ---------------------------------------------------------------------------
@router.get("/webhook", response_class=PlainTextResponse)
async def wechat_webhook_verify(
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    """微信平台在配置服务器 URL 时发起的 GET 请求，原样返回 echostr 完成验证。"""
    if not _verify_wechat_signature(signature, timestamp, nonce):
        raise HTTPException(status_code=403, detail="Invalid signature")
    return echostr


@router.post("/webhook")
async def wechat_webhook_message(
    request: Request,
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
):
    """
    接收用户发给公众号的消息。
    当消息内容恰好是某个待验证的 4 位验证码时，
    把该用户的 OpenID 绑定到对应 session，并在数据库中创建/确认用户记录。
    """
    if not _verify_wechat_signature(signature, timestamp, nonce):
        raise HTTPException(status_code=403, detail="Invalid signature")

    # 额外防护：按请求 IP 限流（微信服务器出口 IP 较固定，异常暴增即可告警）
    # 仅作 DoS 兜底，不影响正常流量（微信回调通常 < 20 req/s）
    try:
        _rate_hit("wechat_webhook", _client_ip(request), 120)
    except HTTPException:
        log.warning("[WeChatAuth] webhook 超限 (>120/min from same IP)")
        raise

    body = await request.body()
    try:
        root = ET.fromstring(body.decode("utf-8"))
    except ET.ParseError:
        raise HTTPException(status_code=400, detail="Invalid XML")

    msg_type   = root.findtext("MsgType", "")
    openid     = root.findtext("FromUserName", "")   # 用户 OpenID
    to_name    = root.findtext("ToUserName", "")     # 公众号原始 ID（gh_xxx）
    content    = (root.findtext("Content") or "").strip()

    def _wx_reply(reply_content: str) -> Response:
        """构造微信被动回复 XML（服务器在 5s 内同步返回）"""
        ts = int(time.time())
        xml_body = (
            f"<xml>"
            f"<ToUserName><![CDATA[{openid}]]></ToUserName>"
            f"<FromUserName><![CDATA[{to_name}]]></FromUserName>"
            f"<CreateTime>{ts}</CreateTime>"
            f"<MsgType><![CDATA[text]]></MsgType>"
            f"<Content><![CDATA[{reply_content}]]></Content>"
            f"</xml>"
        )
        return Response(content=xml_body, media_type="application/xml")

    # 只处理文本消息且内容非空
    if msg_type != "text" or not openid or not content:
        return PlainTextResponse("success")

    # 在 pending session 中寻找匹配的验证码
    now = time.time()
    matched_sid: str | None = None
    for sid, session in _sessions.items():
        if (
            session["code"] == content
            and not session["verified"]
            and session["expires_at"] > now
        ):
            matched_sid = sid
            break

    if not matched_sid:
        # 验证码不匹配或已过期 —— 回复提示，避免用户困惑
        log.info("[WeChatAuth] 收到未匹配消息: openid=%s content=%s", openid, content)
        return _wx_reply("验证码无效或已过期，请返回网页重新获取验证码后再试 🔄")

    # 标记验证通过，写入 OpenID
    _sessions[matched_sid]["openid"] = openid
    _sessions[matched_sid]["verified"] = True

    # 保证用户在 DB 中存在
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO users (openid) VALUES (?)", (openid,)
        )
        conn.commit()
    finally:
        conn.close()

    log.info("[WeChatAuth] 验证成功: openid=%s session=%s", openid, matched_sid)
    return _wx_reply("验证成功 ✅ 请返回网页完成登录。")


# ---------------------------------------------------------------------------
# 接口 3：前端轮询，验证通过后下发真实 JWT
# ---------------------------------------------------------------------------
@router.get("/poll/{session_id}")
async def poll_wechat_session(session_id: str, request: Request):
    """
    前端每隔 2 秒调用此接口。
    - pending：用户还未发送验证码，继续等待
    - ok：验证成功，返回 JWT（包含 user_id 和 is_vip）
    - 404/410：session 不存在或已过期
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    if time.time() > session["expires_at"]:
        del _sessions[session_id]
        raise HTTPException(status_code=410, detail="Session expired")

    if not session["verified"]:
        return {"status": "pending"}

    # 查询用户信息并生成 JWT
    openid = session["openid"]
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, role, nickname, avatar_url, vip_expires_at FROM users WHERE openid = ?", (openid,))
        user = cursor.fetchone()
    finally:
        conn.close()

    if not user:
        raise HTTPException(status_code=500, detail="User record missing")

    # 尝试从微信 API 拉取最新头像和昵称（配置了 APPID/APPSECRET 才生效）
    nickname   = user["nickname"]   or "足球探索者"
    avatar_url = user["avatar_url"] or ""
    if WECHAT_APPID and WECHAT_APPSECRET:
        wx_nickname, wx_avatar = await _fetch_wx_userinfo(openid)
        if wx_nickname and wx_nickname != "足球探索者":
            nickname = wx_nickname
        if wx_avatar:
            avatar_url = wx_avatar
        # 更新 DB 里的最新用户信息
        conn2 = sqlite3.connect(DB_PATH)
        try:
            conn2.execute(
                "UPDATE users SET nickname=?, avatar_url=?, updated_at=datetime('now') WHERE openid=?",
                (nickname, avatar_url, openid)
            )
            conn2.commit()
        finally:
            conn2.close()

    vip_expires_at = user["vip_expires_at"] if "vip_expires_at" in user.keys() else None
    token = issue_session_token(
        user_id=user["id"],
        role=user["role"],
        nickname=nickname,
        avatar_url=avatar_url,
        vip_expires_at=vip_expires_at,
        ip=_client_ip(request),
        ua=request.headers.get("User-Agent", ""),
    )

    # 消耗 session（一次性）
    del _sessions[session_id]

    return {"status": "confirmed", "token": token}
