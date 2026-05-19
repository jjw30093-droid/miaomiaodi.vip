"""
notify_utils.py — Server酱微信通知工具
=======================================
所有脚本共用，import 后直接调用 notify()
"""
import os
import json
import logging

log = logging.getLogger(__name__)


def _read_key_from_env_file() -> str:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(env_path):
        return ''
    with open(env_path) as f:
        for line in f:
            if line.startswith('SERVERCHAN_KEY='):
                return line.strip().split('=', 1)[1]
    return ''


def notify(msg: str, title: str = "喵弟系统通知") -> bool:
    """
    发送 Server酱 推送。
    返回 True 表示 Server酱 返回 code==0（真正成功），否则 False。
    注意：Server酱 对消息长度 / 频率 / 每日配额有限制，必须解析响应才能知道真实状态。
    """
    key = os.environ.get('SERVERCHAN_KEY', '') or _read_key_from_env_file()
    if not key:
        log.warning("Server酱未配置 SERVERCHAN_KEY，跳过通知")
        return False

    # Server酱 desp 字段最大长度约 32KB；title 最大 32 字节。超限会 500。
    MAX_DESP = 30000
    if len(msg) > MAX_DESP:
        log.warning(f"Server酱 desp 超长 {len(msg)} > {MAX_DESP}，截断后发送")
        msg = msg[:MAX_DESP] + "\n\n...(已截断)"
    if len(title.encode('utf-8')) > 32:
        title = title[:16]  # 中文保险起见

    try:
        import urllib.request, urllib.parse, urllib.error
        url = f'https://sctapi.ftqq.com/{key}.send'
        payload = urllib.parse.urlencode({'title': title, 'desp': msg}).encode()
        try:
            with urllib.request.urlopen(url, payload, timeout=10) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
                status = resp.status
        except urllib.error.HTTPError as http_err:
            # Server酱 对某些错误（如超配额）返回 4xx，但 body 仍含 JSON 错误码
            raw = http_err.read().decode('utf-8', errors='replace')
            status = http_err.code
    except Exception as e:
        log.warning(f"Server酱 HTTP 通信失败: {e}")
        return False

    # 解析 Server酱 JSON 响应
    try:
        data = json.loads(raw)
    except Exception:
        log.warning(f"Server酱 返回非 JSON (status={status}): {raw[:200]}")
        return False

    code = data.get('code', -1)
    if code == 0:
        pushid = data.get('data', {}).get('pushid', '')
        log.info(f"✅ Server酱 推送成功 pushid={pushid} title={title!r}")
        return True
    else:
        # 常见错误码：40001=title过长, 40002=desp过长/非法, 40003=key错误,
        # 40011/40012=消息被微信拦截，40015=rate-limit, 40024=每日配额耗尽
        message = data.get('message', '')
        log.error(f"❌ Server酱 推送失败 code={code} message={message!r} title={title!r}")
        return False
