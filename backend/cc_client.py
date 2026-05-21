"""
cc 内部 API 客户端。
向 cc 站（172.26.7.30:8000）私网拉取比赛/研报数据。
"""
import os
import logging
import time
from collections import deque
from typing import Optional
import httpx

logger = logging.getLogger("cc_client")

_CC_BASE_URL = os.environ.get("CC_INTERNAL_BASE_URL", "http://172.26.7.30:8000")
_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")
_TIMEOUT = httpx.Timeout(3.0, connect=1.0)

# 滑动窗口：最近 100 次失败时间戳；每小时 >=5 次告警
_FAIL_LOG: deque = deque(maxlen=100)


class CCBackendUnavailable(Exception):
    """cc 内部 API 不可达 / 超时 / 5xx，调用方应自行降级。"""
    pass


def _record_failure():
    now = time.time()
    _FAIL_LOG.append(now)
    recent = sum(1 for t in _FAIL_LOG if now - t < 3600)
    if recent >= 5:
        logger.error("[cc_client] ALERT: %d failures in last hour", recent)


def _client() -> httpx.Client:
    if not _TOKEN:
        raise RuntimeError("INTERNAL_API_TOKEN not configured on vip")
    return httpx.Client(
        base_url=_CC_BASE_URL,
        timeout=_TIMEOUT,
        headers={"X-Internal-Token": _TOKEN},
    )


def _get(path: str, params: Optional[dict] = None) -> dict:
    """
    GET cc 内部端点。timeout=3s（connect=1s），失败重试 1 次（无退避）。
    4xx (含 404 / 403) 直接抛 CCBackendUnavailable，不重试。
    5xx / connect error / read timeout 重试一次后仍失败 → CCBackendUnavailable。
    """
    last_exc = None
    for attempt in range(2):  # 0=首次, 1=重试
        try:
            with _client() as c:
                r = c.get(path, params=params)
            if r.status_code == 200:
                return r.json()
            if 400 <= r.status_code < 500:
                # 4xx 不重试，业务级失败
                raise CCBackendUnavailable(f"cc {r.status_code}: {r.text[:200]}")
            # 5xx 落入重试
            last_exc = CCBackendUnavailable(f"cc {r.status_code}: {r.text[:200]}")
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
            last_exc = CCBackendUnavailable(f"cc transport error: {type(e).__name__}: {e}")
        except CCBackendUnavailable:
            raise
    _record_failure()
    logger.warning("[cc_client] %s failed after retry: %s", path, last_exc)
    raise last_exc


def get_match_payload(match_id: str) -> dict:
    """
    返回 cc build_match_payload 整包，并 flatten match_meta 嵌套到顶层。
    顶层最终含：match_id, report_markdown, npxg_trend, shot_map_data, player_stats,
    team_match_stats, lineup_impact_data, lineup_status, lineup_confirmed_at, odds,
    + match_meta 内部 22 字段（home_team, away_team, home_icon, away_icon, home_prob,
    away_prob, draw_prob, league, match_time, status, inference, pipeline_status,
    preview_content, title, match_status, post_match_review, post_match_shots,
    beginner_summary, chart_insights, key_variables, key_risk, is_free）。
    """
    payload = _get(f"/internal/api/v1/match_payload/{match_id}")
    meta = payload.pop("match_meta", None) or {}
    # match_meta 字段升到顶层，便于 vip 业务代码当扁平 dict 用
    flat = {**payload, **meta}
    return flat


def report_exists(match_id: str) -> dict:
    """返回 {exists: bool, is_free: bool, match_time: str|None}"""
    return _get(f"/internal/api/v1/report/exists/{match_id}")


def get_latest(limit: int = 150) -> list:
    """返回 cc report_store 列表（list of dicts，原始字段）。"""
    data = _get("/internal/api/v1/reports/latest", params={"limit": limit})
    return data if isinstance(data, list) else []


def get_archive(page: int = 1, per_page: int = 20,
                league: Optional[str] = None,
                start_date: Optional[str] = None,
                end_date: Optional[str] = None) -> dict:
    """返回 cc archive {total, page, per_page, items}。"""
    params = {"page": page, "per_page": per_page}
    if league:
        params["league"] = league
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return _get("/internal/api/v1/reports/archive", params=params)


def get_archive_leagues() -> list:
    """
    cc 端无对应 endpoint，从 archive 全量拉一次（per_page=1000）后本地去重。
    若 cc 不可达，抛 CCBackendUnavailable 由调用方降级。
    """
    data = get_archive(page=1, per_page=1000)
    items = data.get("items", [])
    leagues = sorted({item["league"] for item in items if item.get("league")})
    return leagues
