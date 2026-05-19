#!/usr/bin/env python3
# Cron: N/A — 手动触发（World Cup cache sync）
"""
sync_worldcup_sportmonks.py — Sportmonks → worldcup.db basic 层同步主脚本

同步顺序（依赖关系不乱）：
  seasons → stages → groups → teams → venues → fixtures → standings

每步开始时往 wc_sync_log 写一行（started_at），结束时 UPDATE 结果。

用法：
  探查模式（只 GET 不写库）：
    python scripts/sync_worldcup_sportmonks.py --discover

  单届 dry-run（完整流程，不写库）：
    python scripts/sync_worldcup_sportmonks.py --season-id 18017 --layer basic --dry-run

  单届实际同步：
    python scripts/sync_worldcup_sportmonks.py --season-id 18017 --layer basic

  全部 6 届（内置白名单，按年份升序）：
    python scripts/sync_worldcup_sportmonks.py --all --layer basic

  强制重跑（忽略 data_hash 比对）：
    python scripts/sync_worldcup_sportmonks.py --season-id 18017 --layer basic --force

  断点续传（从上次失败 endpoint 续跑）：
    python scripts/sync_worldcup_sportmonks.py --season-id 18017 --layer basic --resume

  自定义请求间隔（默认 500ms）：
    python scripts/sync_worldcup_sportmonks.py --all --layer basic --sleep 800

Step 3 adds deep (events/statistics/lineups) and odds layers.
"""

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# 路径 / 模块导入
# --------------------------------------------------------------------------- #
_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)

sys.path.insert(0, _BACKEND_DIR)

# 手动加载 .env（与 qwen_client.py 同一模式，在 import sportmonks_client 之前）
_ENV_PATH = os.path.join(_BACKEND_DIR, ".env")
if os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from sportmonks_client import SportmonksClient  # noqa: E402

# --------------------------------------------------------------------------- #
# 日志配置
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("sync_worldcup")

# --------------------------------------------------------------------------- #
# 常量：6 届世界杯白名单（spec 已确认，直接写死）
# --------------------------------------------------------------------------- #
SEASON_WHITELIST: Dict[int, int] = {
    2006: 5794,
    2010: 5795,
    2014: 5796,
    2018: 892,
    2022: 18017,
    2026: 26618,
}

# 赛季预期 fixture 数量（quality check 用）
EXPECTED_FIXTURE_COUNTS: Dict[int, int] = {
    5794:  64,   # 2006
    5795:  64,   # 2010
    5796:  64,   # 2014
    892:   64,   # 2018
    18017: 64,   # 2022
    26618: 104,  # 2026
}

# 历史届次（一次写入，不再触发重同步）
HISTORICAL_SEASON_IDS = {5794, 5795, 5796}

# standings 预期行数（quality check 用）
EXPECTED_STANDINGS_ROWS: Dict[int, int] = {
    5794:  34,   # 2006 — 异常多 2 行，允许（数据质量规则）
    5795:  32,   # 2010
    5796:  32,   # 2014
    892:   32,   # 2018
    18017: 32,   # 2022
    26618: 48,   # 2026
}

# Sportmonks standing_details type_id 映射
_STANDING_TYPE: Dict[str, int] = {
    "played":          130,
    "won":             131,
    "draw":            132,
    "lost":            133,
    "goals_for":       134,
    "goals_against":   135,
    "goal_difference": 136,
    "points":          137,
}

# DB 路径
DB_PATH = os.environ.get(
    "WORLDCUP_DB_PATH",
    os.path.join(_BACKEND_DIR, "worldcup.db"),
)

API_VERSION = "v3"
SYNC_SOURCE_DEFAULT = "cron"


# =========================================================================== #
# 工具函数
# =========================================================================== #

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _canonical_hash(obj: Any) -> str:
    """sha256 of canonical JSON（sort_keys=True）"""
    s = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(s.encode()).hexdigest()


def _json_text(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn


def _row_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    """返回所有 wc_* 表的行数"""
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'wc_%'"
        ).fetchall()
    ]
    counts = {}
    for t in sorted(tables):
        counts[t] = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
    return counts


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _to_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return _json_text(value)
    return str(value)


def _inc(counter: Dict[str, int], status: str) -> None:
    if status == "inserted":
        counter["inserted"] += 1
    elif status == "updated":
        counter["updated"] += 1
    else:
        counter["unchanged"] += 1


# =========================================================================== #
# wc_sync_log 辅助
# =========================================================================== #

def _log_start(
    conn: sqlite3.Connection,
    endpoint: str,
    sync_source: str,
    season_id: Optional[int],
    layer: str,
    dry_run: bool = False,
) -> Optional[int]:
    """往 wc_sync_log 写一行，返回 row id。dry_run 时返回 None。"""
    if dry_run:
        return None
    started = _now_utc()
    cur = conn.execute(
        """INSERT INTO wc_sync_log
           (endpoint, sync_source, api_version, layer, season_sportmonks_id,
            started_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (endpoint, sync_source, API_VERSION, layer, season_id,
         started, started, started),
    )
    conn.commit()
    return cur.lastrowid


def _log_finish(
    conn: sqlite3.Connection,
    log_id: Optional[int],
    inserted: int,
    updated: int,
    unchanged: int,
    error_msg: Optional[str] = None,
    retry_count: int = 0,
    dry_run: bool = False,
) -> None:
    if dry_run or log_id is None:
        return
    finished = _now_utc()
    conn.execute(
        """UPDATE wc_sync_log
           SET finished_at=?, rows_inserted=?, rows_updated=?,
               rows_unchanged=?, error_msg=?, retry_count=?,
               http_status=?, updated_at=?
           WHERE id=?""",
        (
            finished, inserted, updated, unchanged,
            error_msg, retry_count,
            200 if not error_msg else 500,
            finished, log_id,
        ),
    )
    conn.commit()


# =========================================================================== #
# 核心 upsert
# =========================================================================== #

_UpsertResult = Tuple[str, int]   # ('inserted'|'updated'|'unchanged', row_id)


def _upsert(
    conn: sqlite3.Connection,
    table: str,
    sportmonks_id: Optional[int],
    raw_data: Any,
    biz: Dict[str, Any],
    sync_source: str,
    dry_run: bool = False,
    commit: bool = True,
) -> _UpsertResult:
    """幂等 upsert 单个实体。

    逻辑：
      - 不存在 → INSERT
      - 存在 + hash 不同 → UPDATE
      - 存在 + hash 相同 → 跳过（unchanged）

    dry_run=True 时只模拟，不写 DB。
    """
    raw_json_str = json.dumps(raw_data, ensure_ascii=False, separators=(",", ":"))
    data_hash = _canonical_hash(raw_data)
    now = _now_utc()

    if sportmonks_id is not None:
        row = conn.execute(
            f"SELECT id, data_hash FROM [{table}] WHERE sportmonks_id=?",
            (sportmonks_id,),
        ).fetchone()
    else:
        row = None

    if row is None:
        # INSERT
        cols = ["sportmonks_id", "raw_json", "data_hash", "synced_at",
                "sync_source", "api_version", "created_at", "updated_at"]
        vals: List[Any] = [sportmonks_id, raw_json_str, data_hash, now,
                           sync_source, API_VERSION, now, now]
        for k, v in biz.items():
            cols.append(k)
            vals.append(v)

        placeholders = ",".join("?" * len(cols))
        col_str = ",".join(f"[{c}]" for c in cols)
        sql = f"INSERT INTO [{table}] ({col_str}) VALUES ({placeholders})"

        if dry_run:
            return ("inserted", -1)
        cur = conn.execute(sql, vals)
        if commit:
            conn.commit()
        return ("inserted", cur.lastrowid)

    existing_hash = row["data_hash"]
    if existing_hash == data_hash:
        return ("unchanged", row["id"])

    # UPDATE
    set_parts = ["raw_json=?", "data_hash=?", "synced_at=?", "updated_at=?"]
    set_vals: List[Any] = [raw_json_str, data_hash, now, now]
    for k, v in biz.items():
        set_parts.append(f"[{k}]=?")
        set_vals.append(v)
    set_vals.append(row["id"])

    sql = f"UPDATE [{table}] SET {', '.join(set_parts)} WHERE id=?"
    if dry_run:
        return ("updated", row["id"])
    conn.execute(sql, set_vals)
    if commit:
        conn.commit()
    return ("updated", row["id"])


# =========================================================================== #
# 实体解析辅助
# =========================================================================== #

def _parse_fixture_participants(
    fixture: Dict,
) -> Tuple[Optional[int], Optional[int], Optional[str], Optional[str], List[Dict]]:
    """从 fixture.participants[] 解析主客队。

    Returns:
        (home_id, away_id, placeholder_home_name, placeholder_away_name, all_teams_raw)
    """
    home_id: Optional[int] = None
    away_id: Optional[int] = None
    placeholder_home: Optional[str] = None
    placeholder_away: Optional[str] = None
    teams: List[Dict] = []

    for p in fixture.get("participants", []):
        meta = p.get("meta") or {}
        location = meta.get("location")
        team_id = p.get("id")
        team_name = p.get("name")
        is_ph = bool(p.get("placeholder", False))

        teams.append(p)

        if location == "home":
            home_id = team_id
            if is_ph:
                placeholder_home = team_name
        elif location == "away":
            away_id = team_id
            if is_ph:
                placeholder_away = team_name

    return home_id, away_id, placeholder_home, placeholder_away, teams


def _parse_fixture_scores(fixture: Dict) -> Tuple[Optional[int], Optional[int], List[Dict]]:
    """从 fixture.scores[] 解析当前全场比分和原始 score 列表。

    Returns:
        (home_score, away_score, raw_scores_list)
    """
    scores_raw = fixture.get("scores", [])
    home_score: Optional[int] = None
    away_score: Optional[int] = None

    for sc in scores_raw:
        desc = (sc.get("description") or "").upper()
        if desc in ("CURRENT", "FT", "FULLTIME", "2ND_HALF"):
            score_inner = sc.get("score", {})
            if isinstance(score_inner, dict):
                participant = (score_inner.get("participant") or "").lower()
                goals = score_inner.get("goals")
                if participant == "home" and goals is not None:
                    try:
                        home_score = int(goals)
                    except (TypeError, ValueError):
                        pass
                elif participant == "away" and goals is not None:
                    try:
                        away_score = int(goals)
                    except (TypeError, ValueError):
                        pass

    return home_score, away_score, scores_raw


def _parse_standing_details(standing: Dict) -> Dict[str, Optional[int]]:
    """从 standing.details[] 的 type_id 映射解析统计字段，同时支持直接字段。

    优先级：直接字段 → details type_id 解析。
    """
    result: Dict[str, Optional[int]] = {
        "played": None, "won": None, "draw": None, "lost": None,
        "goals_for": None, "goals_against": None, "goal_difference": None,
        "points": None,
    }

    # 1. 先尝试直接字段（Sportmonks v3 部分端点直接提供）
    direct_field_map = {
        "played":          ("played", "games_played"),
        "won":             ("won", "win"),
        "draw":            ("draw", "draws"),
        "lost":            ("lost", "lose", "losses"),
        "goals_for":       ("goals_scored", "goals_for", "gf"),
        "goals_against":   ("goals_against", "goals_conceded", "ga"),
        "goal_difference": ("goal_difference", "gd"),
        "points":          ("points", "pts"),
    }
    for key, field_names in direct_field_map.items():
        for fn in field_names:
            v = standing.get(fn)
            if v is not None:
                try:
                    result[key] = int(v)
                    break
                except (TypeError, ValueError):
                    pass

    # 2. 从 details 补充缺失字段
    details = standing.get("details", []) or standing.get("standing_details", []) or []
    type_to_key = {v: k for k, v in _STANDING_TYPE.items()}

    for detail in details:
        tid = detail.get("type_id")
        val = detail.get("value")
        if tid in type_to_key and val is not None:
            key = type_to_key[tid]
            if result.get(key) is None:
                try:
                    result[key] = int(val)
                except (TypeError, ValueError):
                    pass

    # 3. 计算 goal_difference（如果前两个有值但 gd 没有）
    if result["goal_difference"] is None:
        gf = result["goals_for"]
        ga = result["goals_against"]
        if gf is not None and ga is not None:
            result["goal_difference"] = gf - ga

    return result


def _event_type(event: Dict) -> Optional[str]:
    event_type = event.get("type")
    if isinstance(event_type, dict):
        return (
            event_type.get("developer_name")
            or event_type.get("code")
            or event_type.get("name")
            or _to_text(event_type.get("id"))
        )
    return _to_text(event.get("type_id"))


def _stat_type(stat: Dict) -> Optional[str]:
    stat_type = stat.get("type")
    if isinstance(stat_type, dict):
        return (
            stat_type.get("developer_name")
            or stat_type.get("code")
            or stat_type.get("name")
            or _to_text(stat_type.get("id"))
        )
    return _to_text(stat.get("type_id"))


def _stat_value(stat: Dict) -> str:
    data = stat.get("data")
    if isinstance(data, dict) and "value" in data:
        return _to_text(data.get("value")) or ""
    return _to_text(stat.get("value")) or ""


def _lineup_position(lineup: Dict) -> Optional[str]:
    position = lineup.get("position")
    if isinstance(position, dict):
        return (
            position.get("developer_name")
            or position.get("name")
            or position.get("code")
            or _to_text(position.get("id"))
        )
    return _to_text(lineup.get("position_id"))


def _lineup_player_id(lineup: Dict, fixture_id: int) -> int:
    """Return a NOT NULL player id for wc_lineups.

    Older World Cup lineups can contain rows without player_id while the Step 1
    schema requires player_sportmonks_id NOT NULL. Keep the raw payload intact
    and store a deterministic negative sentinel so the row remains traceable.
    """
    player_id = lineup.get("player_id")
    if player_id is not None:
        try:
            return int(player_id)
        except (TypeError, ValueError):
            pass
    lineup_id = lineup.get("id")
    if lineup_id is not None:
        try:
            return -abs(int(lineup_id))
        except (TypeError, ValueError):
            pass
    return -abs(int(fixture_id))


def _is_lineup_starter(lineup: Dict) -> int:
    # Sportmonks World Cup samples: type_id=11 starter, type_id=12 substitute.
    type_id = lineup.get("type_id")
    if type_id == 12:
        return 0
    return 1


# =========================================================================== #
# 主同步类
# =========================================================================== #

class WorldCupSyncer:
    """World Cup cache syncer."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        client: SportmonksClient,
        dry_run: bool = False,
        force: bool = False,
        sleep_secs: float = 0.5,
        sync_source: str = "manual",
    ):
        self.conn = conn
        self.client = client
        self.dry_run = dry_run
        self.force = force
        self.sleep_secs = sleep_secs
        self.sync_source = sync_source

    # ---------------------------------------------------------------------- #
    # 公开方法：同步单届
    # ---------------------------------------------------------------------- #

    def sync_season(self, season_id: int) -> Dict:
        """同步一届世界杯的 basic 层数据。

        Returns:
            counters dict，各子步骤的 inserted/updated/unchanged 统计
        """
        year = next((y for y, sid in SEASON_WHITELIST.items() if sid == season_id), "?")
        log.info("▶ 开始同步 %s World Cup (season_id=%d)", year, season_id)
        start_ts = time.time()

        if self.force:
            log.info("  [force] 忽略 data_hash 比对，强制更新所有行")

        totals: Dict[str, Dict[str, int]] = {}

        # ── Step 1: seasons ──────────────────────────────────────────────── #
        totals["seasons"] = self._sync_seasons(season_id)

        # ── Step 2: stages ───────────────────────────────────────────────── #
        totals["stages"] = self._sync_stages(season_id)

        # ── Step 3: groups ───────────────────────────────────────────────── #
        totals["groups"] = self._sync_groups(season_id)

        # ── Step 4: teams ────────────────────────────────────────────────── #
        totals["teams"] = self._sync_teams(season_id)

        # ── Step 5: venues ───────────────────────────────────────────────── #
        totals["venues"] = self._sync_venues(season_id)

        # ── Step 6: fixtures（同时补充 teams / venues / scores）─────────── #
        f_counters, s_counters = self._sync_fixtures(season_id)
        totals["fixtures"] = f_counters
        totals["scores"] = s_counters

        # Merge placeholder teams into teams totals
        totals["teams"]["inserted"] += totals["fixtures"].pop("teams_from_fixtures", 0)

        # ── Step 7: standings ────────────────────────────────────────────── #
        totals["standings"] = self._sync_standings(season_id)

        # ── Step 8: 历史赛事标记 ─────────────────────────────────────────── #
        if season_id in HISTORICAL_SEASON_IDS:
            self._mark_historical(season_id)

        duration = time.time() - start_ts

        # ── Quality check ───────────────────────────────────────────────── #
        quality = self._quality_check(season_id)

        return {
            "season_id":  season_id,
            "year":       year,
            "totals":     totals,
            "quality":    quality,
            "duration_s": round(duration, 1),
        }

    def sync_deep_layer(self, season_id: int, resume: bool = False) -> Dict:
        """同步一届 fixtures 的 events/statistics/lineups。"""
        year = next((y for y, sid in SEASON_WHITELIST.items() if sid == season_id), "?")
        log.info("▶ 开始 deep 同步 %s World Cup (season_id=%d)", year, season_id)
        start_ts = time.time()
        endpoint = f"deep/season/{season_id}"
        log_id = _log_start(self.conn, endpoint, self.sync_source, season_id, "deep", self.dry_run)

        totals: Dict[str, Any] = {
            "events": {"inserted": 0, "updated": 0, "unchanged": 0},
            "statistics": {"inserted": 0, "updated": 0, "unchanged": 0},
            "lineups": {"inserted": 0, "updated": 0, "unchanged": 0},
            "fixtures": {"processed": 0, "failed": 0},
        }
        errors: List[str] = []
        fixtures = self._target_fixtures_for_deep(season_id, resume)

        for row in fixtures:
            fixture_id = int(row["sportmonks_id"])
            try:
                detail = self.client.get_fixture_detail(fixture_id)
                time.sleep(self.sleep_secs)
                events = detail.get("events") or []
                statistics = detail.get("statistics") or []
                lineups = detail.get("lineups") or []

                for event in events:
                    if self.force:
                        event = dict(event)
                        event["__force_ts__"] = _now_utc()
                    biz = {
                        "fixture_sportmonks_id": fixture_id,
                        "player_sportmonks_id": event.get("player_id"),
                        "player_name": event.get("player_name"),
                        "team_sportmonks_id": event.get("participant_id"),
                        "type": _event_type(event),
                        "minute": event.get("minute"),
                        "extra_minute": event.get("extra_minute"),
                        "info": event.get("info"),
                    }
                    status, _ = _upsert(
                        self.conn, "wc_events", event.get("id"),
                        event, biz, self.sync_source, self.dry_run, commit=False,
                    )
                    _inc(totals["events"], status)

                for stat in statistics:
                    if self.force:
                        stat = dict(stat)
                        stat["__force_ts__"] = _now_utc()
                    biz = {
                        "fixture_sportmonks_id": fixture_id,
                        "team_sportmonks_id": stat.get("participant_id"),
                        "player_sportmonks_id": stat.get("player_id"),
                        "type": _stat_type(stat) or _to_text(stat.get("type_id")) or "UNKNOWN",
                        "value": _stat_value(stat),
                    }
                    status, _ = _upsert(
                        self.conn, "wc_statistics", stat.get("id"),
                        stat, biz, self.sync_source, self.dry_run, commit=False,
                    )
                    _inc(totals["statistics"], status)

                for lineup in lineups:
                    if self.force:
                        lineup = dict(lineup)
                        lineup["__force_ts__"] = _now_utc()
                    formation_position = lineup.get("formation_position")
                    formation_field = lineup.get("formation_field")
                    if formation_position is None and formation_field is not None:
                        formation_position = formation_field
                    biz = {
                        "fixture_sportmonks_id": fixture_id,
                        "team_sportmonks_id": lineup.get("team_id") or 0,
                        "player_sportmonks_id": _lineup_player_id(lineup, fixture_id),
                        "player_name": lineup.get("player_name"),
                        "jersey_number": lineup.get("jersey_number"),
                        "position": _lineup_position(lineup),
                        "is_starter": _is_lineup_starter(lineup),
                        "formation_position": _to_text(formation_position),
                    }
                    status, _ = _upsert(
                        self.conn, "wc_lineups", lineup.get("id"),
                        lineup, biz, self.sync_source, self.dry_run, commit=False,
                    )
                    _inc(totals["lineups"], status)

                if not self.dry_run:
                    self.conn.execute(
                        """UPDATE wc_fixtures
                           SET has_events=1, has_statistics=1, has_lineups=1,
                               updated_at=?
                           WHERE sportmonks_id=?""",
                        (_now_utc(), fixture_id),
                    )
                    self.conn.commit()
                totals["fixtures"]["processed"] += 1
            except Exception as e:
                if not self.dry_run:
                    self.conn.rollback()
                totals["fixtures"]["failed"] += 1
                msg = f"fixture {fixture_id}: {str(e)[:180]}"
                errors.append(msg)
                log.warning("  deep fixture failed: %s", msg)

        err_text = "\n".join(errors) if errors else None
        _log_finish(
            self.conn, log_id,
            totals["events"]["inserted"] + totals["statistics"]["inserted"] + totals["lineups"]["inserted"],
            totals["events"]["updated"] + totals["statistics"]["updated"] + totals["lineups"]["updated"],
            totals["events"]["unchanged"] + totals["statistics"]["unchanged"] + totals["lineups"]["unchanged"],
            error_msg=err_text,
            dry_run=self.dry_run,
        )

        return {
            "season_id": season_id,
            "year": year,
            "layer": "deep",
            "totals": totals,
            "quality": self._deep_quality(season_id) if not self.dry_run else {"note": "skipped in dry-run"},
            "duration_s": round(time.time() - start_ts, 1),
            "error": err_text,
        }

    def sync_odds_layer(self, season_id: int, resume: bool = False) -> Dict:
        """同步一届 fixtures 的 pre-match odds。"""
        year = next((y for y, sid in SEASON_WHITELIST.items() if sid == season_id), "?")
        log.info("▶ 开始 odds 同步 %s World Cup (season_id=%d)", year, season_id)
        start_ts = time.time()
        endpoint = f"odds/season/{season_id}"
        log_id = _log_start(self.conn, endpoint, self.sync_source, season_id, "odds", self.dry_run)

        totals: Dict[str, Any] = {
            "odds": {"inserted": 0, "updated": 0, "unchanged": 0},
            "fixtures": {"processed": 0, "failed": 0, "with_odds": 0, "empty": 0},
        }
        errors: List[str] = []
        fixtures = self._target_fixtures_for_odds(season_id, resume)

        for row in fixtures:
            fixture_id = int(row["sportmonks_id"])
            try:
                odds = self.client.get_fixture_odds(fixture_id)
                time.sleep(self.sleep_secs)
                if odds:
                    totals["fixtures"]["with_odds"] += 1
                else:
                    totals["fixtures"]["empty"] += 1

                for odd in odds:
                    if self.force:
                        odd = dict(odd)
                        odd["__force_ts__"] = _now_utc()
                    biz = {
                        "fixture_sportmonks_id": odd.get("fixture_id") or fixture_id,
                        "market_id": odd.get("market_id"),
                        "bookmaker_id": odd.get("bookmaker_id"),
                        "label": odd.get("label"),
                        "original_label": odd.get("original_label"),
                        "name": odd.get("name"),
                        "market_description": odd.get("market_description"),
                        "value": _to_text(odd.get("value")),
                        "probability": _to_text(odd.get("probability")),
                        "dp3": _to_text(odd.get("dp3")),
                        "fractional": _to_text(odd.get("fractional")),
                        "american": _to_text(odd.get("american")),
                        "total": _to_text(odd.get("total")),
                        "handicap": _to_text(odd.get("handicap")),
                        "stopped": int(bool(odd.get("stopped"))) if odd.get("stopped") is not None else None,
                        "winning": int(bool(odd.get("winning"))) if odd.get("winning") is not None else None,
                        "latest_bookmaker_update": odd.get("latest_bookmaker_update"),
                        "participants": _to_text(odd.get("participants")),
                        "sort_order": odd.get("sort_order"),
                    }
                    status, _ = _upsert(
                        self.conn, "wc_odds", odd.get("id"),
                        odd, biz, self.sync_source, self.dry_run, commit=False,
                    )
                    _inc(totals["odds"], status)

                if not self.dry_run:
                    self.conn.execute(
                        """UPDATE wc_fixtures
                           SET odds_markets_count=?, odds_last_checked_at=?, updated_at=?
                           WHERE sportmonks_id=?""",
                        (len(odds), _now_utc(), _now_utc(), fixture_id),
                    )
                    self.conn.commit()
                totals["fixtures"]["processed"] += 1
            except Exception as e:
                if not self.dry_run:
                    self.conn.rollback()
                totals["fixtures"]["failed"] += 1
                msg = f"fixture {fixture_id}: {str(e)[:180]}"
                errors.append(msg)
                log.warning("  odds fixture failed: %s", msg)

        err_text = "\n".join(errors) if errors else None
        _log_finish(
            self.conn, log_id,
            totals["odds"]["inserted"],
            totals["odds"]["updated"],
            totals["odds"]["unchanged"],
            error_msg=err_text,
            dry_run=self.dry_run,
        )

        return {
            "season_id": season_id,
            "year": year,
            "layer": "odds",
            "totals": totals,
            "quality": self._odds_quality(season_id) if not self.dry_run else {"note": "skipped in dry-run"},
            "duration_s": round(time.time() - start_ts, 1),
            "error": err_text,
        }

    # ---------------------------------------------------------------------- #
    # 内部：各子步骤
    # ---------------------------------------------------------------------- #

    def _sync_seasons(self, season_id: int) -> Dict[str, int]:
        endpoint = f"seasons/{season_id}"
        log_id = _log_start(self.conn, endpoint, self.sync_source, season_id, "basic", self.dry_run)
        inserted = updated = unchanged = 0

        try:
            season = self.client.get_season(season_id)
            time.sleep(self.sleep_secs)

            if season is None:
                raise ValueError(f"get_season({season_id}) 返回 None（套餐限制 or 不存在）")

            if self.force:
                season["__force_ts__"] = _now_utc()

            biz = {
                "year":         season.get("year") or season.get("name", "")[:4],
                "name":         season.get("name", ""),
                "host_country": season.get("country_id"),      # resolved later if needed
            }
            status, rid = _upsert(
                self.conn, "wc_seasons", season.get("id"),
                season, biz, self.sync_source, self.dry_run,
            )
            if status == "inserted": inserted += 1
            elif status == "updated": updated += 1
            else: unchanged += 1
            log.info("  seasons: %s (id=%s)", status, season.get("id"))

        except Exception as e:
            msg = str(e)
            log.error("  seasons FAILED: %s", msg)
            _log_finish(self.conn, log_id, inserted, updated, unchanged,
                        error_msg=msg, dry_run=self.dry_run)
            return dict(inserted=inserted, updated=updated, unchanged=unchanged, error=msg)

        _log_finish(self.conn, log_id, inserted, updated, unchanged, dry_run=self.dry_run)
        return dict(inserted=inserted, updated=updated, unchanged=unchanged)

    def _sync_stages(self, season_id: int) -> Dict[str, int]:
        endpoint = f"stages/seasons/{season_id}"
        log_id = _log_start(self.conn, endpoint, self.sync_source, season_id, "basic", self.dry_run)
        inserted = updated = unchanged = 0

        try:
            stages = self.client.get_stages(season_id)
            time.sleep(self.sleep_secs)

            for stage in stages:
                if self.force:
                    stage["__force_ts__"] = _now_utc()
                biz = {
                    "season_sportmonks_id": season_id,
                    "name":        stage.get("name", ""),
                    "type":        stage.get("type"),
                    "sort_order":  stage.get("sort_order"),
                }
                status, _ = _upsert(
                    self.conn, "wc_stages", stage.get("id"),
                    stage, biz, self.sync_source, self.dry_run,
                )
                if status == "inserted": inserted += 1
                elif status == "updated": updated += 1
                else: unchanged += 1

            log.info("  stages: %d total → ins=%d upd=%d unch=%d",
                     len(stages), inserted, updated, unchanged)

        except Exception as e:
            msg = str(e)
            log.error("  stages FAILED: %s", msg)
            _log_finish(self.conn, log_id, inserted, updated, unchanged,
                        error_msg=msg, dry_run=self.dry_run)
            return dict(inserted=inserted, updated=updated, unchanged=unchanged, error=msg)

        _log_finish(self.conn, log_id, inserted, updated, unchanged, dry_run=self.dry_run)
        return dict(inserted=inserted, updated=updated, unchanged=unchanged)

    def _sync_groups(self, season_id: int) -> Dict[str, int]:
        endpoint = f"groups/seasons/{season_id}"
        log_id = _log_start(self.conn, endpoint, self.sync_source, season_id, "basic", self.dry_run)
        inserted = updated = unchanged = 0

        try:
            groups = self.client.get_groups(season_id)
            time.sleep(self.sleep_secs)

            for grp in groups:
                if self.force:
                    grp["__force_ts__"] = _now_utc()
                biz = {
                    "season_sportmonks_id": season_id,
                    "stage_sportmonks_id":  grp.get("stage_id"),
                    "name":                 grp.get("name", ""),
                }
                status, _ = _upsert(
                    self.conn, "wc_groups", grp.get("id"),
                    grp, biz, self.sync_source, self.dry_run,
                )
                if status == "inserted": inserted += 1
                elif status == "updated": updated += 1
                else: unchanged += 1

            log.info("  groups: %d total → ins=%d upd=%d unch=%d",
                     len(groups), inserted, updated, unchanged)

        except Exception as e:
            msg = str(e)
            log.warning("  groups FAILED (non-fatal, group data may come via fixtures): %s", msg)
            _log_finish(self.conn, log_id, inserted, updated, unchanged,
                        error_msg=msg, dry_run=self.dry_run)
            return dict(inserted=inserted, updated=updated, unchanged=unchanged, warning=msg)

        _log_finish(self.conn, log_id, inserted, updated, unchanged, dry_run=self.dry_run)
        return dict(inserted=inserted, updated=updated, unchanged=unchanged)

    def _sync_teams(self, season_id: int) -> Dict[str, int]:
        endpoint = f"teams/seasons/{season_id}"
        log_id = _log_start(self.conn, endpoint, self.sync_source, season_id, "basic", self.dry_run)
        inserted = updated = unchanged = 0

        try:
            teams = self.client.get_teams(season_id)
            time.sleep(self.sleep_secs)

            for team in teams:
                self._upsert_team(team)
                # count approximate (placeholder teams added later via fixtures)
                inserted += 1  # simplified: just count from endpoint

            # Reset and do proper counting
            inserted = updated = unchanged = 0
            for team in teams:
                if self.force:
                    team["__force_ts__"] = _now_utc()
                biz = {
                    "name":           team.get("name", ""),
                    "short_name":     team.get("short_name") or team.get("short"),
                    "country_id":     team.get("country_id"),
                    "image_path":     team.get("image_path"),
                    "is_placeholder": int(bool(team.get("placeholder", False))),
                }
                status, _ = _upsert(
                    self.conn, "wc_teams", team.get("id"),
                    team, biz, self.sync_source, self.dry_run,
                )
                if status == "inserted": inserted += 1
                elif status == "updated": updated += 1
                else: unchanged += 1

            log.info("  teams: %d from endpoint → ins=%d upd=%d unch=%d",
                     len(teams), inserted, updated, unchanged)

        except Exception as e:
            msg = str(e)
            log.error("  teams FAILED: %s", msg)
            _log_finish(self.conn, log_id, inserted, updated, unchanged,
                        error_msg=msg, dry_run=self.dry_run)
            return dict(inserted=inserted, updated=updated, unchanged=unchanged, error=msg)

        _log_finish(self.conn, log_id, inserted, updated, unchanged, dry_run=self.dry_run)
        return dict(inserted=inserted, updated=updated, unchanged=unchanged)

    def _upsert_team(self, team: Dict) -> str:
        """单个 team upsert，返回 status。供 _sync_teams 和 _sync_fixtures 共用。"""
        if self.force:
            team = dict(team)
            team["__force_ts__"] = _now_utc()
        biz = {
            "name":           team.get("name", ""),
            "short_name":     team.get("short_name") or team.get("short"),
            "country_id":     team.get("country_id"),
            "image_path":     team.get("image_path"),
            "is_placeholder": int(bool(team.get("placeholder", False))),
        }
        status, _ = _upsert(
            self.conn, "wc_teams", team.get("id"),
            team, biz, self.sync_source, self.dry_run,
        )
        return status

    def _sync_venues(self, season_id: int) -> Dict[str, int]:
        endpoint = f"venues/seasons/{season_id}"
        log_id = _log_start(self.conn, endpoint, self.sync_source, season_id, "basic", self.dry_run)
        inserted = updated = unchanged = 0

        try:
            venues = self.client.get_venues_by_season(season_id)
            time.sleep(self.sleep_secs)

            for venue in venues:
                if self.force:
                    venue["__force_ts__"] = _now_utc()
                biz = {
                    "name":     venue.get("name", ""),
                    "city":     venue.get("city") or (venue.get("city_name")),
                    "country":  venue.get("country_id"),
                    "capacity": venue.get("capacity"),
                }
                # Try latitude/longitude from various structures
                surface = venue.get("surface")
                if isinstance(surface, dict):
                    biz["latitude"]  = surface.get("lat")
                    biz["longitude"] = surface.get("lon")

                status, _ = _upsert(
                    self.conn, "wc_venues", venue.get("id"),
                    venue, biz, self.sync_source, self.dry_run,
                )
                if status == "inserted": inserted += 1
                elif status == "updated": updated += 1
                else: unchanged += 1

            log.info("  venues: %d total → ins=%d upd=%d unch=%d",
                     len(venues), inserted, updated, unchanged)

        except Exception as e:
            msg = str(e)
            log.warning("  venues FAILED (non-fatal, venues may come via fixtures): %s", msg)
            _log_finish(self.conn, log_id, inserted, updated, unchanged,
                        error_msg=msg, dry_run=self.dry_run)
            return dict(inserted=inserted, updated=updated, unchanged=unchanged, warning=msg)

        _log_finish(self.conn, log_id, inserted, updated, unchanged, dry_run=self.dry_run)
        return dict(inserted=inserted, updated=updated, unchanged=unchanged)

    def _sync_fixtures(self, season_id: int) -> Tuple[Dict, Dict]:
        """同步 fixtures，同时补充 teams / venues / scores。

        Returns:
            (fixture_counters, score_counters)
        """
        endpoint = f"fixtures/seasons/{season_id}"
        log_id = _log_start(self.conn, endpoint, self.sync_source, season_id, "basic", self.dry_run)

        f_ins = f_upd = f_unch = 0
        s_ins = s_upd = s_unch = 0
        teams_from_fixtures = 0

        try:
            fixtures = self.client.get_fixtures(
                season_id,
                include="participants;venue;scores;state",
            )
            time.sleep(self.sleep_secs)

            log.info("  fixtures: %d retrieved from API", len(fixtures))

            for fx in fixtures:
                if self.force:
                    fx["__force_ts__"] = _now_utc()

                fx_id = fx.get("id")

                # ── Participants → teams ─────────────────────────────────── #
                (home_id, away_id,
                 ph_home, ph_away,
                 all_teams) = _parse_fixture_participants(fx)

                for team in all_teams:
                    ts = self._upsert_team(team)
                    if ts == "inserted":
                        teams_from_fixtures += 1

                # ── Venue ────────────────────────────────────────────────── #
                venue_id: Optional[int] = None
                venue_obj = fx.get("venue")
                if isinstance(venue_obj, dict):
                    venue_id = venue_obj.get("id")
                    if venue_id is not None:
                        biz_v = {
                            "name":     venue_obj.get("name", ""),
                            "city":     venue_obj.get("city"),
                            "capacity": venue_obj.get("capacity"),
                        }
                        _upsert(
                            self.conn, "wc_venues", venue_id,
                            venue_obj, biz_v, self.sync_source, self.dry_run,
                        )
                elif isinstance(fx.get("venue_id"), int):
                    venue_id = fx.get("venue_id")

                # ── Scores ───────────────────────────────────────────────── #
                home_score, away_score, scores_raw = _parse_fixture_scores(fx)
                for sc in scores_raw:
                    if self.force:
                        sc = dict(sc)
                        sc["__force_ts__"] = _now_utc()
                    biz_s = {
                        "fixture_sportmonks_id": fx_id,
                        "type_id":    sc.get("type_id"),
                        "description": sc.get("description"),
                        "score_home": None,
                        "score_away": None,
                    }
                    # Parse score inner dict
                    score_inner = sc.get("score", {})
                    if isinstance(score_inner, dict):
                        participant = (score_inner.get("participant") or "").lower()
                        goals = score_inner.get("goals")
                        if participant == "home":
                            biz_s["score_home"] = goals
                        elif participant == "away":
                            biz_s["score_away"] = goals
                    # sportmonks_id for scores may not be unique across sessions
                    # use sc.get("id") but allow NULL
                    ss, _ = _upsert(
                        self.conn, "wc_scores", sc.get("id"),
                        sc, biz_s, self.sync_source, self.dry_run,
                    )
                    if ss == "inserted": s_ins += 1
                    elif ss == "updated": s_upd += 1
                    else: s_unch += 1

                # ── State ────────────────────────────────────────────────── #
                state_obj = fx.get("state") or {}
                state_short = None
                if isinstance(state_obj, dict):
                    state_short = (state_obj.get("short_name")
                                   or state_obj.get("developer_name"))
                elif isinstance(state_obj, str):
                    state_short = state_obj

                # ── Fixture business fields ──────────────────────────────── #
                biz_f = {
                    "season_sportmonks_id":    season_id,
                    "stage_sportmonks_id":     fx.get("stage_id"),
                    "group_sportmonks_id":     fx.get("group_id"),
                    "venue_sportmonks_id":     venue_id,
                    "home_team_sportmonks_id": home_id,
                    "away_team_sportmonks_id": away_id,
                    "placeholder_home":        ph_home,
                    "placeholder_away":        ph_away,
                    "is_placeholder":          int(bool(fx.get("placeholder", False))),
                    "starting_at":             fx.get("starting_at"),
                    "status":                  (fx.get("state", {}) or {}).get("developer_name")
                                               or fx.get("result_info"),
                    "state_short_name":        state_short,
                    "match_label":             fx.get("details") or fx.get("name"),
                    "home_score":              home_score,
                    "away_score":              away_score,
                    "has_events":              0,
                    "has_lineups":             0,
                    "has_statistics":          0,
                    "is_historical":           int(season_id in HISTORICAL_SEASON_IDS),
                    "referee_sportmonks_id":   fx.get("referee_id"),
                }
                fs, _ = _upsert(
                    self.conn, "wc_fixtures", fx_id,
                    fx, biz_f, self.sync_source, self.dry_run,
                )
                if fs == "inserted": f_ins += 1
                elif fs == "updated": f_upd += 1
                else: f_unch += 1

            log.info(
                "  fixtures: ins=%d upd=%d unch=%d | scores: ins=%d upd=%d unch=%d | teams_via_fixtures: %d",
                f_ins, f_upd, f_unch, s_ins, s_upd, s_unch, teams_from_fixtures,
            )

        except Exception as e:
            msg = str(e)
            log.error("  fixtures FAILED: %s", msg)
            _log_finish(self.conn, log_id, f_ins, f_upd, f_unch,
                        error_msg=msg, dry_run=self.dry_run)
            f_counters = dict(inserted=f_ins, updated=f_upd, unchanged=f_unch,
                              teams_from_fixtures=teams_from_fixtures, error=msg)
            return f_counters, dict(inserted=s_ins, updated=s_upd, unchanged=s_unch)

        _log_finish(self.conn, log_id, f_ins, f_upd, f_unch, dry_run=self.dry_run)
        f_counters = dict(inserted=f_ins, updated=f_upd, unchanged=f_unch,
                          teams_from_fixtures=teams_from_fixtures)
        return f_counters, dict(inserted=s_ins, updated=s_upd, unchanged=s_unch)

    def _sync_standings(self, season_id: int) -> Dict[str, int]:
        endpoint = f"standings/seasons/{season_id}"
        log_id = _log_start(self.conn, endpoint, self.sync_source, season_id, "basic", self.dry_run)
        inserted = updated = unchanged = 0

        try:
            standings = self.client.get_standings(season_id)
            time.sleep(self.sleep_secs)

            for st in standings:
                if self.force:
                    st["__force_ts__"] = _now_utc()

                stats = _parse_standing_details(st)
                participant_id = (st.get("participant_id")
                                  or (st.get("participant") or {}).get("id"))

                biz = {
                    "season_sportmonks_id":    season_id,
                    "stage_sportmonks_id":     st.get("stage_id"),
                    "group_sportmonks_id":     st.get("group_id"),
                    "team_sportmonks_id":      participant_id,
                    "participant_sportmonks_id": participant_id,
                    "position":                st.get("position"),
                    "points":                  stats.get("points") or st.get("points"),
                    "played":                  stats.get("played"),
                    "won":                     stats.get("won"),
                    "win":                     stats.get("won"),   # alias
                    "drawn":                   stats.get("draw"),
                    "draw":                    stats.get("draw"),  # alias
                    "lost":                    stats.get("lost"),
                    "lose":                    stats.get("lost"),  # alias
                    "goals_for":               stats.get("goals_for"),
                    "goals_against":           stats.get("goals_against"),
                    "goal_difference":         stats.get("goal_difference"),
                }
                status, _ = _upsert(
                    self.conn, "wc_standings", st.get("id"),
                    st, biz, self.sync_source, self.dry_run,
                )
                if status == "inserted": inserted += 1
                elif status == "updated": updated += 1
                else: unchanged += 1

            log.info("  standings: %d total → ins=%d upd=%d unch=%d",
                     len(standings), inserted, updated, unchanged)

        except Exception as e:
            msg = str(e)
            log.error("  standings FAILED: %s", msg)
            _log_finish(self.conn, log_id, inserted, updated, unchanged,
                        error_msg=msg, dry_run=self.dry_run)
            return dict(inserted=inserted, updated=updated, unchanged=unchanged, error=msg)

        _log_finish(self.conn, log_id, inserted, updated, unchanged, dry_run=self.dry_run)
        return dict(inserted=inserted, updated=updated, unchanged=unchanged)

    def _mark_historical(self, season_id: int) -> None:
        """将历史赛事（06/10/14）的 fixtures 标记 is_historical=1。"""
        if self.dry_run:
            log.info("  [dry-run] would mark is_historical=1 for season %d", season_id)
            return
        updated = self.conn.execute(
            "UPDATE wc_fixtures SET is_historical=1 WHERE season_sportmonks_id=?",
            (season_id,),
        ).rowcount
        self.conn.commit()
        if updated > 0:
            log.info("  is_historical=1 标记 %d 行 (season=%d)", updated, season_id)

    def _target_fixtures_for_deep(self, season_id: int, resume: bool = False) -> List[sqlite3.Row]:
        """返回 deep 层需要检查的 fixtures。

        2026 placeholder / 未开赛比赛也要请求；空数组代表已检查。
        """
        where = ["season_sportmonks_id=?"]
        params: List[Any] = [season_id]
        if resume:
            where.append("(has_events=0 OR has_statistics=0 OR has_lineups=0)")
        sql = (
            "SELECT sportmonks_id FROM wc_fixtures "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY starting_at, sportmonks_id"
        )
        rows = self.conn.execute(sql, params).fetchall()
        log.info("  deep target fixtures: %d (resume=%s)", len(rows), resume)
        return rows

    def _target_fixtures_for_odds(self, season_id: int, resume: bool = False) -> List[sqlite3.Row]:
        """返回 odds 层需要请求的 fixtures。

        只请求 Sportmonks basic payload 标记 has_odds=1 的比赛。
        """
        where = [
            "season_sportmonks_id=?",
            "COALESCE(json_extract(raw_json, '$.has_odds'), 0)=1",
        ]
        params: List[Any] = [season_id]
        if resume:
            where.append("odds_last_checked_at IS NULL")
        sql = (
            "SELECT sportmonks_id FROM wc_fixtures "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY starting_at, sportmonks_id"
        )
        rows = self.conn.execute(sql, params).fetchall()
        log.info("  odds target fixtures: %d (resume=%s)", len(rows), resume)
        return rows

    def _deep_quality(self, season_id: int) -> Dict[str, Any]:
        """deep 层同步后的表级验收统计。"""
        fixtures_row = self.conn.execute(
            """SELECT COUNT(*) AS total,
                      COALESCE(SUM(has_events), 0) AS checked_events,
                      COALESCE(SUM(has_statistics), 0) AS checked_statistics,
                      COALESCE(SUM(has_lineups), 0) AS checked_lineups
               FROM wc_fixtures
               WHERE season_sportmonks_id=?""",
            (season_id,),
        ).fetchone()
        event_rows = self.conn.execute(
            """SELECT COUNT(*)
               FROM wc_events e
               JOIN wc_fixtures f ON f.sportmonks_id=e.fixture_sportmonks_id
               WHERE f.season_sportmonks_id=?""",
            (season_id,),
        ).fetchone()[0]
        stat_rows = self.conn.execute(
            """SELECT COUNT(*)
               FROM wc_statistics s
               JOIN wc_fixtures f ON f.sportmonks_id=s.fixture_sportmonks_id
               WHERE f.season_sportmonks_id=?""",
            (season_id,),
        ).fetchone()[0]
        lineup_rows = self.conn.execute(
            """SELECT COUNT(*)
               FROM wc_lineups l
               JOIN wc_fixtures f ON f.sportmonks_id=l.fixture_sportmonks_id
               WHERE f.season_sportmonks_id=?""",
            (season_id,),
        ).fetchone()[0]
        return {
            "fixtures_checked": {
                "total": fixtures_row["total"],
                "events": fixtures_row["checked_events"],
                "statistics": fixtures_row["checked_statistics"],
                "lineups": fixtures_row["checked_lineups"],
            },
            "rows": {
                "events": event_rows,
                "statistics": stat_rows,
                "lineups": lineup_rows,
            },
        }

    def _odds_quality(self, season_id: int) -> Dict[str, Any]:
        """odds 层同步后的表级验收统计。"""
        fixture_row = self.conn.execute(
            """SELECT COUNT(*) AS eligible,
                      COALESCE(SUM(CASE WHEN odds_last_checked_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS checked,
                      COALESCE(SUM(odds_markets_count), 0) AS odds_markets_count
               FROM wc_fixtures
               WHERE season_sportmonks_id=?
                 AND COALESCE(json_extract(raw_json, '$.has_odds'), 0)=1""",
            (season_id,),
        ).fetchone()
        odds_rows = self.conn.execute(
            """SELECT COUNT(*)
               FROM wc_odds o
               JOIN wc_fixtures f ON f.sportmonks_id=o.fixture_sportmonks_id
               WHERE f.season_sportmonks_id=?""",
            (season_id,),
        ).fetchone()[0]
        return {
            "fixtures": {
                "eligible": fixture_row["eligible"],
                "checked": fixture_row["checked"],
                "odds_markets_count": fixture_row["odds_markets_count"],
            },
            "rows": {
                "odds": odds_rows,
            },
        }

    def _quality_check(self, season_id: int) -> Dict:
        """同步结束后的数据质量校验。"""
        if self.dry_run:
            return {"note": "skipped in dry-run"}

        year = next((y for y, sid in SEASON_WHITELIST.items() if sid == season_id), "?")
        q: Dict[str, Any] = {}

        # fixtures count
        actual_fx = self.conn.execute(
            "SELECT COUNT(*) FROM wc_fixtures WHERE season_sportmonks_id=?",
            (season_id,),
        ).fetchone()[0]
        placeholder_fx = self.conn.execute(
            "SELECT COUNT(*) FROM wc_fixtures WHERE season_sportmonks_id=? AND is_placeholder=1",
            (season_id,),
        ).fetchone()[0]
        expected_fx = EXPECTED_FIXTURE_COUNTS.get(season_id, "?")
        fx_ok = (actual_fx == expected_fx) if isinstance(expected_fx, int) else True
        q["fixtures"] = {
            "expected":     expected_fx,
            "actual":       actual_fx,
            "placeholder":  placeholder_fx,
            "ok":           fx_ok,
            "warning":      None if fx_ok else f"expected {expected_fx} but got {actual_fx}",
        }

        # standings count + distinct participants
        actual_st = self.conn.execute(
            "SELECT COUNT(*) FROM wc_standings WHERE season_sportmonks_id=?",
            (season_id,),
        ).fetchone()[0]
        distinct_st = self.conn.execute(
            "SELECT COUNT(DISTINCT participant_sportmonks_id) FROM wc_standings "
            "WHERE season_sportmonks_id=?",
            (season_id,),
        ).fetchone()[0]
        expected_st = EXPECTED_STANDINGS_ROWS.get(season_id, "?")
        st_ok = (actual_st == expected_st) if isinstance(expected_st, int) else True
        # 2006 34行/32distinct 是已知的，不算真正失败
        if season_id == 5794 and actual_st == 34 and distinct_st == 32:
            st_ok = True
        st_warning = None
        if not st_ok:
            st_warning = f"expected ~{expected_st} but got {actual_st} ({distinct_st} distinct)"
        elif actual_st != distinct_st:
            st_warning = (f"2006 known anomaly" if season_id == 5794
                          else f"{actual_st} rows but only {distinct_st} distinct participants")
        q["standings"] = {
            "expected":   expected_st,
            "actual":     actual_st,
            "distinct":   distinct_st,
            "ok":         st_ok,
            "warning":    st_warning,
        }

        # teams count
        total_teams = self.conn.execute(
            "SELECT COUNT(*) FROM wc_teams"
        ).fetchone()[0]
        ph_teams = self.conn.execute(
            "SELECT COUNT(*) FROM wc_teams WHERE is_placeholder=1"
        ).fetchone()[0]
        q["teams"] = {
            "total":       total_teams,
            "placeholder": ph_teams,
        }

        warnings = sum(1 for v in q.values()
                       if isinstance(v, dict) and v.get("warning") is not None)
        q["warnings_count"] = warnings
        return q


# =========================================================================== #
# Discover 模式
# =========================================================================== #

def run_discover(client: SportmonksClient) -> None:
    """仅 GET 并打印 6 届赛季元信息，不写库。"""
    print(f"\n{'='*65}")
    print(f"  [--discover] Sportmonks API 探查（不写库）")
    print(f"  Token 来源: {SportmonksClient.TOKEN_SOURCE}")
    print(f"{'='*65}\n")

    # ping token
    print("▶ 验证 token...")
    ok = client.ping()
    print(f"  token 有效: {'✅ OK' if ok else '❌ FAILED（请检查 SPORTMONKS_API_TOKEN）'}")
    if not ok:
        return
    print(f"  Rate limit: {client.rate_limit_status}\n")

    print("▶ 探查 6 届世界杯赛季：")
    print(f"  {'年份':>6}  {'season_id':>10}  {'状态':<8}  {'名称'}")
    print(f"  {'-'*6}  {'-'*10}  {'-'*8}  {'-'*40}")

    for year in sorted(SEASON_WHITELIST.keys()):
        season_id = SEASON_WHITELIST[year]
        try:
            season = client.get_season(season_id)
            time.sleep(0.4)
            if season:
                name = season.get("name", "(no name)")
                sy   = season.get("year", "?")
                print(f"  {year:>6}  {season_id:>10}  ✅ OK      {name} (year={sy})")
            else:
                print(f"  {year:>6}  {season_id:>10}  ⚠️  None   (可能套餐不含此届)")
        except Exception as e:
            print(f"  {year:>6}  {season_id:>10}  ❌ ERROR  {str(e)[:60]}")

    print()
    print("▶ 探查 endpoint 可用性（以 2022 season_id=18017 为测试）：")
    test_id = 18017
    checks = [
        ("stages", lambda: client.get_stages(test_id)),
        ("groups (derived from standings.group)", lambda: client.get_groups(test_id)),
        ("teams", lambda: client.get_teams(test_id)),
        ("venues", lambda: client.get_venues_by_season(test_id)),
        ("standings", lambda: client.get_standings(test_id)),
        ("fixtures (filters fixtureLeagues+fixtureSeasons)", lambda: client.get_fixtures(test_id, include="participants;scores;state;stage;venue")),
    ]

    for label, getter in checks:
        try:
            data = getter()
            time.sleep(0.3)
            count = len(data) if isinstance(data, list) else ("dict" if isinstance(data, dict) else "?")
            print(f"  {label:<45} ✅ 返回 {count} 条")
        except Exception as e:
            print(f"  {label:<45} ❌ {str(e)[:70]}")

    print()
    print("▶ fixture 样本（2022 season，只取前 3 条）：")
    try:
        fixtures = client.get_fixtures(
            test_id,
            include="participants;scores;state",
        )[:3]
        for fx in fixtures[:3]:
            participants = fx.get("participants", [])
            teams = [p.get("name", "?") + ("(ph)" if p.get("placeholder") else "")
                     for p in participants]
            state_obj = fx.get("state") or {}
            state = state_obj.get("short_name") if isinstance(state_obj, dict) else str(state_obj)
            print(f"  [{fx.get('id')}] {' vs '.join(teams) or fx.get('name','?')}"
                  f" | state={state} | placeholder={fx.get('placeholder')}"
                  f" | details={fx.get('details')}")
    except Exception as e:
        print(f"  ❌ {e}")

    print(f"\n{'='*65}\n")


# =========================================================================== #
# 断点续传检查
# =========================================================================== #

def check_resume(conn: sqlite3.Connection, season_id: int, layer: str) -> Optional[str]:
    """检查上次同步是否中途失败。

    Returns:
        上次失败时的 endpoint 字符串，或 None（无失败）
    """
    row = conn.execute(
        """SELECT endpoint, error_msg FROM wc_sync_log
           WHERE season_sportmonks_id=? AND layer=?
             AND finished_at IS NULL AND error_msg IS NOT NULL
           ORDER BY started_at DESC LIMIT 1""",
        (season_id, layer),
    ).fetchone()
    if row:
        return row["endpoint"]
    return None


# =========================================================================== #
# 摘要打印
# =========================================================================== #

def _print_summary(result: Dict) -> None:
    year     = result["year"]
    sid      = result["season_id"]
    duration = result["duration_s"]
    totals   = result["totals"]
    quality  = result["quality"]
    layer    = result.get("layer", "basic")

    print(f"\n{'='*60}")
    print(f"  === Sync Summary ===")
    print(f"  Season: {year} World Cup (id={sid})")
    print(f"  Layer:  {layer}")
    print(f"  Duration: {duration}s")
    print()

    if layer == "basic":
        rows = [
            ("seasons",   totals.get("seasons",   {})),
            ("stages",    totals.get("stages",    {})),
            ("groups",    totals.get("groups",    {})),
            ("teams",     totals.get("teams",     {})),
            ("venues",    totals.get("venues",    {})),
            ("fixtures",  totals.get("fixtures",  {})),
            ("scores",    totals.get("scores",    {})),
            ("standings", totals.get("standings", {})),
        ]
        for label, ctr in rows:
            ins  = ctr.get("inserted", 0)
            upd  = ctr.get("updated",  0)
            unch = ctr.get("unchanged", 0)
            err  = ctr.get("error")
            warn = ctr.get("warning")
            status = " ❌" if err else (" ⚠️" if warn else "")
            print(f"  {label:<12}: {ins:>4} inserted, {upd:>4} updated, {unch:>4} unchanged{status}")

        print()
        print("  Data Quality:")
        for key, qdata in quality.items():
            if key == "warnings_count":
                continue
            if isinstance(qdata, dict):
                ok_marker = "OK" if qdata.get("ok", True) else "⚠️ WARNING"
                detail = ""
                if key == "fixtures":
                    detail = (f"({qdata['actual']}/{qdata['expected']}) "
                              f"placeholder={qdata['placeholder']}")
                elif key == "standings":
                    detail = (f"({qdata['actual']} rows, "
                              f"{qdata['distinct']} distinct)")
                elif key == "teams":
                    detail = f"total={qdata['total']} placeholder={qdata['placeholder']}"
                warn = qdata.get("warning")
                w_str = f" ← {warn}" if warn else ""
                print(f"    {key:<12}: {ok_marker} {detail}{w_str}")

        w_count = quality.get("warnings_count", 0)
        print(f"\n  Warnings: {w_count}")

    elif layer == "deep":
        fixtures = totals.get("fixtures", {})
        print(f"  fixtures   : {fixtures.get('processed', 0)} processed, {fixtures.get('failed', 0)} failed")
        for label in ("events", "statistics", "lineups"):
            ctr = totals.get(label, {})
            print(
                f"  {label:<12}: {ctr.get('inserted', 0):>5} inserted, "
                f"{ctr.get('updated', 0):>5} updated, {ctr.get('unchanged', 0):>5} unchanged"
            )
        print()
        print("  Data Quality:")
        if quality.get("note"):
            print(f"    {quality['note']}")
        else:
            checked = quality.get("fixtures_checked", {})
            rows_q = quality.get("rows", {})
            print(
                "    fixtures_checked: "
                f"events={checked.get('events', 0)}/{checked.get('total', 0)}, "
                f"statistics={checked.get('statistics', 0)}/{checked.get('total', 0)}, "
                f"lineups={checked.get('lineups', 0)}/{checked.get('total', 0)}"
            )
            print(
                "    rows            : "
                f"events={rows_q.get('events', 0)}, "
                f"statistics={rows_q.get('statistics', 0)}, "
                f"lineups={rows_q.get('lineups', 0)}"
            )

    elif layer == "odds":
        fixtures = totals.get("fixtures", {})
        odds = totals.get("odds", {})
        print(
            f"  fixtures   : {fixtures.get('processed', 0)} processed, "
            f"{fixtures.get('failed', 0)} failed, "
            f"{fixtures.get('with_odds', 0)} with_odds, {fixtures.get('empty', 0)} empty"
        )
        print(
            f"  odds       : {odds.get('inserted', 0):>5} inserted, "
            f"{odds.get('updated', 0):>5} updated, {odds.get('unchanged', 0):>5} unchanged"
        )
        print()
        print("  Data Quality:")
        if quality.get("note"):
            print(f"    {quality['note']}")
        else:
            f_q = quality.get("fixtures", {})
            rows_q = quality.get("rows", {})
            print(
                "    fixtures: "
                f"eligible={f_q.get('eligible', 0)}, checked={f_q.get('checked', 0)}, "
                f"odds_markets_count={f_q.get('odds_markets_count', 0)}"
            )
            print(f"    rows    : odds={rows_q.get('odds', 0)}")

    if result.get("error"):
        print(f"\n  Errors:\n{result['error']}")
    print(f"{'='*60}\n")


# =========================================================================== #
# CLI 入口
# =========================================================================== #

def main() -> int:
    parser = argparse.ArgumentParser(
        description="世界杯数据缓存层 — Sportmonks basic/deep/odds 同步",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/sync_worldcup_sportmonks.py --discover
  python scripts/sync_worldcup_sportmonks.py --season-id 18017 --layer basic --dry-run
  python scripts/sync_worldcup_sportmonks.py --season-id 18017 --layer basic
  python scripts/sync_worldcup_sportmonks.py --all --layer basic
  python scripts/sync_worldcup_sportmonks.py --season-id 18017 --layer deep --dry-run --sleep 300
  python scripts/sync_worldcup_sportmonks.py --season-id 18017 --layer odds --dry-run --sleep 300
  python scripts/sync_worldcup_sportmonks.py --all --layer deep --sleep 300
  python scripts/sync_worldcup_sportmonks.py --all --layer odds --sleep 300
        """,
    )

    # 模式互斥
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--discover",   action="store_true",
                      help="探查模式：只 GET 并打印，不写库")
    mode.add_argument("--season-id",  type=int, metavar="ID",
                      help="同步指定 season_id")
    mode.add_argument("--all",        action="store_true",
                      help="同步全部 6 届（内置白名单，按年份升序）")

    parser.add_argument("--layer",    default="basic",
                        choices=["basic", "deep", "odds"],
                        help="同步层（默认 basic）")
    parser.add_argument("--dry-run",  action="store_true",
                        help="完整流程但不写库")
    parser.add_argument("--force",    action="store_true",
                        help="强制重跑（忽略 data_hash 比对）")
    parser.add_argument("--resume",   action="store_true",
                        help="断点续传（从上次失败 endpoint 续跑）")
    parser.add_argument("--sleep",    type=int, default=500, metavar="MS",
                        help="请求间隔毫秒（默认 500）")
    parser.add_argument("--db-path",  default=DB_PATH,
                        help=f"worldcup.db 路径（默认 {DB_PATH}）")
    parser.add_argument("--source",   default="manual",
                        help="wc_sync_log.sync_source 标记（默认 manual）")

    args = parser.parse_args()

    sleep_secs = args.sleep / 1000.0

    # ── 前置打印 ─────────────────────────────────────────────────────────── #
    print(f"\n{'='*60}")
    print(f"  世界杯数据同步 ({args.layer} 层)")
    print(f"  Token 来源: ", end="")

    try:
        client = SportmonksClient(sleep_between=sleep_secs)
    except ValueError as e:
        print("未配置")
        print(f"\n❌ {e}")
        return 1

    print(SportmonksClient.TOKEN_SOURCE)
    print(f"  DB 路径:    {args.db_path}")
    print(f"  Dry-run:    {'YES（不写库）' if args.dry_run else 'NO'}")
    print(f"  Force:      {'YES（忽略 hash）' if args.force else 'NO'}")
    print(f"  Sleep:      {args.sleep}ms")
    print(f"{'='*60}\n")

    # ── Discover 模式 ─────────────────────────────────────────────────────── #
    if args.discover:
        run_discover(client)
        return 0

    # ── DB 连接 ───────────────────────────────────────────────────────────── #
    if not os.path.exists(args.db_path):
        print(f"❌ worldcup.db 不存在: {args.db_path}")
        print("   请先运行: python scripts/init_worldcup_db.py")
        return 1

    conn = _get_conn(args.db_path)

    if args.layer == "odds" and not _table_exists(conn, "wc_odds"):
        print("❌ wc_odds 表不存在。请先运行：")
        print("   ./venv/bin/python scripts/migrate_worldcup_step3.py")
        conn.close()
        return 1

    # 前置：打印各表当前行数
    print("[ 当前 worldcup.db 行数 ]")
    for tbl, cnt in _row_counts(conn).items():
        print(f"  {tbl:<25}: {cnt:>6}")
    print()

    # ── 确定要同步的 season_id 列表 ──────────────────────────────────────── #
    if args.all:
        season_ids = [SEASON_WHITELIST[y] for y in sorted(SEASON_WHITELIST.keys())]
        print(f"[--all] 将同步 {len(season_ids)} 届：{season_ids}")
    else:
        sid = args.season_id
        if sid not in SEASON_WHITELIST.values():
            print(f"⚠️  season_id={sid} 不在内置白名单中：{SEASON_WHITELIST}")
            print(f"   继续...（用户可能知道自己在做什么）")
        season_ids = [sid]

    syncer = WorldCupSyncer(
        conn=conn,
        client=client,
        dry_run=args.dry_run,
        force=args.force,
        sleep_secs=sleep_secs,
        sync_source=args.source,
    )

    # ── 断点续传检查 ─────────────────────────────────────────────────────── #
    for sid in season_ids:
        if args.resume:
            last_failed = check_resume(conn, sid, args.layer)
            if last_failed:
                log.info("[resume] season_id=%d 上次失败于 endpoint=%s，续跑...", sid, last_failed)
            else:
                log.info("[resume] season_id=%d 无上次失败记录，正常跑", sid)
        elif not args.force and not args.dry_run:
            last_failed = check_resume(conn, sid, args.layer)
            if last_failed:
                print(f"⚠️  season_id={sid} 上次同步未完成（失败于 {last_failed}）")
                print(f"   请用 --resume 续跑，或 --force 重跑全量，或忽略继续。")
                print(f"   继续本次同步...")

    # ── 执行同步 ─────────────────────────────────────────────────────────── #
    all_results = []
    for sid in season_ids:
        try:
            if args.layer == "basic":
                result = syncer.sync_season(sid)
            elif args.layer == "deep":
                result = syncer.sync_deep_layer(sid, resume=args.resume)
            elif args.layer == "odds":
                result = syncer.sync_odds_layer(sid, resume=args.resume)
            else:
                raise ValueError(f"unsupported layer: {args.layer}")
            all_results.append(result)
            _print_summary(result)
        except KeyboardInterrupt:
            print("\n❗ 用户中断")
            break
        except Exception as e:
            log.error("season_id=%d 同步失败: %s", sid, e)
            all_results.append({"season_id": sid, "error": str(e)})

    # ── 结束后行数 ───────────────────────────────────────────────────────── #
    if not args.dry_run:
        print("[ 同步后 worldcup.db 行数 ]")
        for tbl, cnt in _row_counts(conn).items():
            print(f"  {tbl:<25}: {cnt:>6}")

    conn.close()

    errors = sum(1 for r in all_results if r.get("error"))
    if errors:
        print(f"\n❌ {errors}/{len(all_results)} 届同步出错，请检查日志")
        return 1

    print(f"\n✅ 全部完成（{'dry-run' if args.dry_run else '已写库'}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
