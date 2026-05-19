"""
sportmonks_client.py — Sportmonks REST API v3 HTTP 客户端

设计原则：
  - 纯标准库 + requests（项目已有，无新依赖）
  - 自动加载 .env（与 qwen_client.py 同一模式）
  - Token 从 SPORTMONKS_API_TOKEN 环境变量读取，**不打印 token 本身**
  - 支持自动分页（get_all）
  - HTTP 429 指数退避，最多重试 3 次
  - Rate limit 余量从响应头读取并记录

用法：
  from sportmonks_client import SportmonksClient

  client = SportmonksClient()
  season   = client.get_season(18017)
  fixtures = client.get_fixtures(18017, include="participants;venue;scores;state")
  standings = client.get_standings(18017)
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 自动加载 .env（与 qwen_client.py 同一模式）
# --------------------------------------------------------------------------- #
_PROJECT_ROOT = os.environ.get(
    "PROJECT_ROOT",
    os.path.dirname(os.path.abspath(__file__)),          # backend/
)
_ENV_PATH = os.path.join(_PROJECT_ROOT, ".env")

if not os.environ.get("SPORTMONKS_API_TOKEN") and os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
BASE_URL = "https://api.sportmonks.com"


# --------------------------------------------------------------------------- #
# 客户端类
# --------------------------------------------------------------------------- #

class SportmonksClient:
    """Sportmonks REST API v3 客户端。

    Args:
        token:            API token（默认从 SPORTMONKS_API_TOKEN 环境变量读取）
        timeout:          单次请求超时秒数（默认 30）
        max_retries:      最大重试次数（默认 3，429/5xx 才重试）
        retry_base_delay: 指数退避基础秒数（默认 2.0）
        per_page:         分页每页条数（默认 50）
        sleep_between:    分页请求间隔秒数（默认 0.5，可被调用方覆盖）
    """

    # ── token 来源说明（供日志打印，不打印 token 值）
    TOKEN_SOURCE: str = "unknown"

    def __init__(
        self,
        token: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        retry_base_delay: float = 2.0,
        per_page: int = 50,
        sleep_between: float = 0.5,
    ):
        if token:
            self.token = token
            SportmonksClient.TOKEN_SOURCE = "explicit argument"
        else:
            self.token = os.environ.get("SPORTMONKS_API_TOKEN", "")
            if self.token:
                SportmonksClient.TOKEN_SOURCE = f"env SPORTMONKS_API_TOKEN (from {_ENV_PATH if os.path.exists(_ENV_PATH) else 'os.environ'})"
            else:
                SportmonksClient.TOKEN_SOURCE = "NOT FOUND"

        if not self.token:
            raise ValueError(
                "Sportmonks API token 未配置。"
                f"请在 {_ENV_PATH} 中添加：SPORTMONKS_API_TOKEN=<your_token>"
            )

        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.per_page = per_page
        self.sleep_between = sleep_between

        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
        })

        # Rate limit 追踪（从响应头更新）
        self._rate_limit_remaining: Optional[int] = None
        self._rate_limit_reset: Optional[int] = None

    # ---------------------------------------------------------------------- #
    # 内部：带重试的单次 HTTP GET
    # ---------------------------------------------------------------------- #

    def _request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """执行单次 GET 请求，含 429 指数退避（最多 max_retries 次）。

        Returns:
            完整响应体 dict（含 data, pagination, subscription, rate_limit 等）

        Raises:
            Exception: 超过重试次数仍失败，或 4xx（非 429）客户端错误
        """
        url = f"{BASE_URL}{endpoint}"
        p = dict(params or {})
        # Sportmonks Football API v3 accepts token authentication via the
        # api_token query parameter. We keep the public client interface
        # unchanged and inject the token internally for every request.
        p.setdefault("api_token", self.token)

        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = self._session.get(url, params=p, timeout=self.timeout)

                # ── 更新 rate limit 追踪 ─────────────────────────────────── #
                for header in ("x-ratelimit-remaining", "X-RateLimit-Remaining",
                               "x-rate-limit-remaining"):
                    v = r.headers.get(header)
                    if v is not None:
                        try:
                            self._rate_limit_remaining = int(v)
                        except ValueError:
                            pass
                        break

                for header in ("x-ratelimit-reset", "X-RateLimit-Reset",
                               "x-rate-limit-reset"):
                    v = r.headers.get(header)
                    if v is not None:
                        try:
                            self._rate_limit_reset = int(v)
                        except ValueError:
                            pass
                        break

                if r.status_code == 200:
                    return r.json()

                if r.status_code == 429:
                    retry_after = int(r.headers.get("Retry-After", 60))
                    wait = retry_after * (2 ** (attempt - 1))
                    log.warning(
                        "[Sportmonks] 429 Rate Limited on %s — waiting %ds (attempt %d/%d)",
                        endpoint, wait, attempt, self.max_retries,
                    )
                    time.sleep(wait)
                    last_err = Exception(f"HTTP 429 (attempt {attempt})")
                    continue

                # 5xx → 重试；4xx（非 429）→ 立即报错
                msg = f"HTTP {r.status_code} on {endpoint}: {r.text[:300]}"
                log.warning("[Sportmonks] %s (attempt %d/%d)", msg, attempt, self.max_retries)
                last_err = Exception(msg)

                if r.status_code < 500:
                    raise last_err

            except requests.RequestException as e:
                log.warning(
                    "[Sportmonks] Request error on %s (attempt %d/%d): %s",
                    endpoint, attempt, self.max_retries, e,
                )
                last_err = e

            if attempt < self.max_retries:
                delay = self.retry_base_delay * (2 ** (attempt - 1))
                time.sleep(delay)

        raise last_err or Exception(f"Failed after {self.max_retries} retries: {endpoint}")

    # ---------------------------------------------------------------------- #
    # 公开 API — 通用 GET（单页 / 分页）
    # ---------------------------------------------------------------------- #

    def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        include: Optional[str] = None,
        filters: Optional[str] = None,
    ) -> Dict:
        """单页 GET。返回完整响应 dict（含 pagination / meta）。

        对于会返回多页的端点，推荐用 get_all()。
        """
        p = dict(params or {})
        if include:
            p["include"] = include
        if filters:
            p["filters"] = filters
        return self._request(endpoint, p)

    def get_all(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        include: Optional[str] = None,
        filters: Optional[str] = None,
        sleep_between_pages: Optional[float] = None,
    ) -> List[Dict]:
        """分页 GET，自动翻页，返回 data 列表（所有页合并）。

        Sportmonks v3 分页字段（response.pagination）：
          has_more: bool
          next_page: int | null
          current_page: int
          total: int
        """
        p = dict(params or {})
        p.setdefault("per_page", self.per_page)
        if include:
            p["include"] = include
        if filters:
            p["filters"] = filters
        sleep = sleep_between_pages if sleep_between_pages is not None else self.sleep_between

        all_data: List[Dict] = []
        page = 1

        while True:
            p["page"] = page
            resp = self._request(endpoint, p)

            data = resp.get("data", [])
            if not isinstance(data, list):
                # 某些端点返回单个 dict（非列表）
                if isinstance(data, dict):
                    all_data.append(data)
                break

            all_data.extend(data)
            log.debug(
                "[Sportmonks] %s page=%d got=%d total_so_far=%d",
                endpoint, page, len(data), len(all_data),
            )

            pagination = resp.get("pagination", {})
            if not pagination or not pagination.get("has_more"):
                break

            next_page = pagination.get("next_page")
            if isinstance(next_page, int) and next_page != page:
                page = next_page
            else:
                page += 1
            if sleep > 0:
                time.sleep(sleep)

        return all_data

    # ---------------------------------------------------------------------- #
    # 便捷方法（按 basic 层 7 类 Sportmonks 端点封装）
    # ---------------------------------------------------------------------- #

    def get_season(self, season_id: int) -> Optional[Dict]:
        """获取单个赛季元信息。

        Returns:
            赛季 dict，或 None（不存在 / 无访问权限）
        """
        try:
            resp = self.get(f"/v3/football/seasons/{season_id}")
            data = resp.get("data")
            return data if isinstance(data, dict) else None
        except Exception as e:
            log.warning("[Sportmonks] get_season(%d) failed: %s", season_id, e)
            return None

    def get_stages(self, season_id: int) -> List[Dict]:
        """获取赛季所有阶段（Group Stage / Round of 16 / QF / SF / Final 等）"""
        return self.get_all(f"/v3/football/stages/seasons/{season_id}")

    def get_groups(self, season_id: int) -> List[Dict]:
        """获取赛季所有小组（A-H / A-L）。

        Sportmonks 当前 football v3 没有可用的 /groups endpoint。
        小组对象会随 standings include=group 返回，因此这里从 standings
        派生唯一 group 列表，保持调用方接口不变。
        """
        standings = self.get_all(
            f"/v3/football/standings/seasons/{season_id}",
            include="group",
        )
        seen = set()
        groups: List[Dict] = []
        for row in standings:
            group = row.get("group")
            if not isinstance(group, dict):
                continue
            group_id = group.get("id")
            if group_id is None or group_id in seen:
                continue
            seen.add(group_id)
            groups.append(group)
        return groups

    def get_teams(self, season_id: int) -> List[Dict]:
        """获取赛季所有参赛队伍（teams endpoint）"""
        return self.get_all(f"/v3/football/teams/seasons/{season_id}")

    def get_venues_by_season(self, season_id: int) -> List[Dict]:
        """获取赛季相关场馆"""
        return self.get_all(f"/v3/football/venues/seasons/{season_id}")

    def get_fixtures(
        self,
        season_id: int,
        include: str = "participants;venue;scores;state",
    ) -> List[Dict]:
        """获取赛季所有比赛（含队伍、场馆、比分、状态）。

        include 默认值涵盖 basic 层所需字段：
          participants  → home/away team_id + placeholder 标记
          venue         → 场馆信息
          scores        → HT/FT/ET/PEN 比分
          state         → 比赛状态（NS/LIVE/FT 等）

        如需额外数据（如 stage、group），可在 include 参数追加。
        """
        league_id = os.environ.get("SPORTMONKS_WORLD_CUP_LEAGUE_ID", "732")
        return self.get_all(
            "/v3/football/fixtures",
            include=include,
            filters=f"fixtureLeagues:{league_id};fixtureSeasons:{season_id}",
        )

    def get_standings(self, season_id: int) -> List[Dict]:
        """获取赛季积分榜（含参赛队和统计详情）"""
        return self.get_all(
            f"/v3/football/standings/seasons/{season_id}",
            include="participant;details.type;form;stage;group",
        )

    def get_fixture_detail(
        self,
        fixture_id: int,
        include: str = "events.type;statistics.type;lineups",
    ) -> Dict:
        """获取单场 deep 层详情（事件、技术统计、阵容）。"""
        resp = self.get(f"/v3/football/fixtures/{fixture_id}", include=include)
        data = resp.get("data")
        return data if isinstance(data, dict) else {}

    def get_fixture_odds(self, fixture_id: int) -> List[Dict]:
        """获取单场 pre-match odds，自动分页。"""
        return self.get_all(
            f"/v3/football/odds/pre-match/fixtures/{fixture_id}",
            params={"per_page": 100},
        )

    # ---------------------------------------------------------------------- #
    # 诊断
    # ---------------------------------------------------------------------- #

    @property
    def rate_limit_status(self) -> str:
        """返回可读的 rate limit 状态（最近一次请求的响应头）"""
        if self._rate_limit_remaining is not None:
            info = f"remaining={self._rate_limit_remaining}"
            if self._rate_limit_reset:
                info += f" reset_at={self._rate_limit_reset}"
            return info
        return "rate_limit=unknown (no header seen yet)"

    def ping(self) -> bool:
        """发一个轻量请求验证 token 有效性。返回 True = token 有效。"""
        try:
            # 用 /v3/football/leagues 端点（通常都有权限）验证 token
            resp = self.get("/v3/football/leagues", params={"per_page": 1, "page": 1})
            return isinstance(resp.get("data"), list)
        except Exception as e:
            log.warning("[Sportmonks] ping failed: %s", e)
            return False


# --------------------------------------------------------------------------- #
# 命令行自检（python3 sportmonks_client.py）
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        client = SportmonksClient()
    except ValueError as e:
        print(f"❌ {e}")
        raise SystemExit(1)

    print(f"Token 来源: {SportmonksClient.TOKEN_SOURCE}")
    print(f"Rate limit: {client.rate_limit_status}")

    print("\n▶ ping token...")
    ok = client.ping()
    print(f"  token 有效: {'✅' if ok else '❌'}")

    if ok:
        print("\n▶ 测试 get_season(18017) [2022 World Cup]...")
        s = client.get_season(18017)
        if s:
            print(f"  name={s.get('name')} year={s.get('year', '?')}")
        else:
            print("  ❌ 返回 None（套餐可能不含世界杯数据）")
