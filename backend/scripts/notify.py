"""Server 酱推送的优先级 wrapper。

免费版 Server 酱日限 5 条。本模块：
- 以文件持久化当日已推送计数（跨进程生效）
- 计数 >= 4 时仅 CRITICAL 通过
- 失败永不抛异常
"""

import os
import json
import logging
import requests
from datetime import datetime, timezone

log = logging.getLogger(__name__)

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COUNTER_FILE = os.path.join(PROJECT_ROOT, "backend", "logs", "notify_counter.json")
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "")
DAILY_SOFT_LIMIT = 4  # 留 1 条给 CRITICAL

LEVELS = {"CRITICAL": 3, "WARNING": 2, "INFO": 1}


def _today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_counter():
    try:
        with open(COUNTER_FILE, "r") as f:
            d = json.load(f)
        if d.get("date") != _today_utc():
            return {"date": _today_utc(), "count": 0}
        return d
    except Exception:
        return {"date": _today_utc(), "count": 0}


def _save_counter(d):
    try:
        os.makedirs(os.path.dirname(COUNTER_FILE), exist_ok=True)
        with open(COUNTER_FILE, "w") as f:
            json.dump(d, f)
    except Exception as e:
        log.warning(f"notify counter save 失败: {e}")


def send(title: str, content: str, level: str = "INFO") -> bool:
    """发送通知；返回是否真推送。"""
    level = level.upper()
    if level not in LEVELS:
        level = "INFO"
    counter = _load_counter()
    if counter["count"] >= DAILY_SOFT_LIMIT and level != "CRITICAL":
        log.info(f"[notify] skipped (level={level}, count={counter['count']}/day): {title}")
        return False
    if not SERVERCHAN_KEY:
        log.info(f"[notify] DRY RUN (no key) [{level}] {title}: {content[:120]}")
        return False
    try:
        url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
        r = requests.post(url, data={"title": f"[{level}] {title}", "desp": content}, timeout=10)
        ok = r.status_code == 200
        if ok:
            counter["count"] += 1
            _save_counter(counter)
            log.info(f"[notify] sent [{level}] {title} (day count={counter['count']})")
        else:
            log.warning(f"[notify] HTTP {r.status_code}: {r.text[:200]}")
        return ok
    except Exception as e:
        log.warning(f"[notify] 推送异常: {e}")
        return False


if __name__ == "__main__":
    # smoke
    send("notify.py smoke", "test content", level="INFO")

