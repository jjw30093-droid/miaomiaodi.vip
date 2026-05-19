"""
rate_limit.py — 极简内存限流工具

基于固定窗口（Fixed Window），适合单进程 PM2 部署。
不依赖 Redis 或外部存储。

⚠️ 关键修复（2026-04-22）:
  在 Cloudflare / nginx 反向代理架构下，`request.client.host` 只会返回
  127.0.0.1 (nginx 回源地址)，导致全部用户共用一个限流桶。
  必须使用 `client_ip(request)` 从 X-Forwarded-For / CF-Connecting-IP 提取真实 IP。
"""

import time
import os
from fastapi import HTTPException, Request

# bucket_key -> {count, reset_at}
_cache: dict[str, dict] = {}

# 可信代理链（只信任这些来源写入的 X-Forwarded-For）
# nginx loopback + Docker 常见内网段
_TRUSTED_PROXIES = {"127.0.0.1", "::1", "localhost"}


def client_ip(request: Request) -> str:
    """
    在反代架构下提取真实客户端 IP。
    优先级：
      1. CF-Connecting-IP (Cloudflare 官方头，最可靠)
      2. X-Real-IP (nginx set by proxy_set_header)
      3. X-Forwarded-For 链表首项
      4. request.client.host 兜底
    """
    # 1. Cloudflare (如果 Cloudflare 作为前置)
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()

    # 2. nginx X-Real-IP
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()

    # 3. X-Forwarded-For (取最左 = 最初源)
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()

    # 4. 兜底
    return request.client.host if request.client else "unknown"


def hit(bucket: str, ip: str, max_per_min: int) -> None:
    """
    在指定桶内对 IP 计数。超限时抛 429。

    bucket     — 桶名，区分不同接口（如 'wechat_code', 'cdk_redeem'）
    ip         — 客户端 IP (应来自 client_ip() 而非 request.client.host)
    max_per_min — 每分钟最大请求次数
    """
    key = f"{bucket}:{ip}"
    now = time.time()
    entry = _cache.get(key)
    if not entry or now > entry["reset_at"]:
        _cache[key] = {"count": 1, "reset_at": now + 60}
    else:
        entry["count"] += 1
        if entry["count"] > max_per_min:
            raise HTTPException(
                status_code=429,
                detail=f"请求过于频繁，请 1 分钟后再试。"
            )


def hit_request(bucket: str, request: Request, max_per_min: int) -> None:
    """便捷封装：自动提取真实 IP 后限流。"""
    hit(bucket, client_ip(request), max_per_min)
