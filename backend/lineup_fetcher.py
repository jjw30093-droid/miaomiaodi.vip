"""
lineup_fetcher.py v2.0（无浏览器版）
=====================================
从 FotMob SSR 页面抓取预计/确认首发 + 缺阵名单，
并从 DB 查询球员重要性指标。

变更：DrissionPage + Chrome + 代理插件 → FotMobClient（curl_cffi + ThorData 代理）

对外接口（与旧版完全兼容）：
  fetch_lineup(match_id)          → 单场抓取
  fetch_lineups_batch(match_ids)  → 批量抓取（复用同一 client 实例）

返回结构 (lineup_data):
{
  "status":     "confirmed" | "predicted" | "unavailable",
  "fetched_at": "ISO 时间",
  "home": {
    "formation":    "4-3-3",
    "starters":     [{"id": 123, "name": "...", "position": "...",
                      "xg_xa_share": 0.18, "def_share": 0.06}],
    "bench":        [...],
    "missing":      [{"id": 456, "name": "...", "reason": "Injury",
                      "xg_xa_share": 0.21, "def_share": 0.05}],
    "key_absences": [...]
  },
  "away": { ... }
}
"""

import json
import sqlite3
import time
import random
import logging
import os
from datetime import datetime

log = logging.getLogger(__name__)

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
DB_PATH      = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))

XG_XA_KEY_THRESHOLD = 0.08
DEF_KEY_THRESHOLD   = 0.12


# ──────────────────────────────────────────
# DB 工具：球员重要性指标
# ──────────────────────────────────────────
def _query_player_stats(conn, player_ids: list) -> dict:
    """
    返回 {player_id: {"name": str, "xg_xa_share": float, "def_share": float}}
    """
    if not player_ids:
        return {}
    placeholders = ",".join("?" * len(player_ids))
    try:
        rows = conn.execute(f"""
            SELECT pi.player_id,
                   dp.player_name,
                   AVG(pi.xg_xa_share)       AS xg_xa,
                   AVG(pi.def_actions_share) AS def_share
            FROM int_player_influence pi
            LEFT JOIN dim_player dp ON dp.player_id = pi.player_id
            WHERE pi.player_id IN ({placeholders})
            GROUP BY pi.player_id
        """, player_ids).fetchall()
    except Exception as e:
        log.warning(f"[Lineup] DB 查询失败: {e}")
        return {}

    return {
        int(r["player_id"]): {
            "name":        r["player_name"] or "",
            "xg_xa_share": round(float(r["xg_xa"] or 0), 3),
            "def_share":   round(float(r["def_share"] or 0), 3),
        }
        for r in rows
    }


# ──────────────────────────────────────────
# FotMob 数据解析（与旧版完全一致）
# ──────────────────────────────────────────
def _extract_name(name_field) -> str:
    if isinstance(name_field, dict):
        return (name_field.get("full")
                or name_field.get("fullName")
                or name_field.get("short")
                or name_field.get("shortName")
                or "")
    return str(name_field or "")


def _parse_player_list(raw: list) -> list:
    """
    解析 FotMob starters / subs / bench / missingPlayers 列表。
    兼容 list[player] 和 list[list[player]]（按排线分组）两种格式。
    """
    result = []
    for item in (raw or []):
        items = item if isinstance(item, list) else [item]
        for p in items:
            if not isinstance(p, dict):
                continue
            name   = _extract_name(p.get("name", ""))
            pid    = p.get("id") or p.get("playerId")
            pos    = p.get("position") or p.get("role", "")
            reason = p.get("reason") or p.get("injuryReason") or ""
            if not reason and "unavailability" in p:
                unav    = p["unavailability"]
                utype   = unav.get("type", "")
                ureturn = unav.get("expectedReturn", "")
                reason  = f"{utype} ({ureturn})" if utype and ureturn else utype
            if name:
                entry = {"id": int(pid) if pid else 0, "name": name, "position": pos}
                if reason:
                    entry["reason"] = reason
                result.append(entry)
    return result


def _parse_side(side_data: dict) -> tuple:
    """返回 (formation, starters, bench, missing) 原始列表"""
    if not side_data:
        return "N/A", [], [], []
    formation = side_data.get("formation", "N/A")
    starters  = (_parse_player_list(side_data.get("starters"))
                 or _parse_player_list(side_data.get("players")))
    bench     = (_parse_player_list(side_data.get("bench"))
                 or _parse_player_list(side_data.get("substitutes"))
                 or _parse_player_list(side_data.get("subs")))
    missing   = (_parse_player_list(side_data.get("missingPlayers"))
                 or _parse_player_list(side_data.get("injured"))
                 or _parse_player_list(side_data.get("unavailable")))
    return formation, starters, bench, missing


def _enrich(player_list: list, stats: dict, default_reason: str = "") -> list:
    enriched = []
    for p in player_list:
        pid = p.get("id", 0)
        db  = stats.get(pid, {})
        entry = {
            "id":          pid,
            "name":        p["name"],
            "position":    p.get("position", ""),
            "xg_xa_share": db.get("xg_xa_share", 0.0),
            "def_share":   db.get("def_share", 0.0),
        }
        reason = p.get("reason") or default_reason
        if reason:
            entry["reason"] = reason
        enriched.append(entry)
    return enriched


def _key_absences(missing: list) -> list:
    return [
        p for p in missing
        if p["xg_xa_share"] >= XG_XA_KEY_THRESHOLD
        or p["def_share"]   >= DEF_KEY_THRESHOLD
    ]


# ──────────────────────────────────────────
# 核心解析：SSR pageProps → lineup_data
# ──────────────────────────────────────────
def _parse_lineup_from_ssr(page_props: dict, match_id: str, conn) -> dict | None:
    """
    从 FotMob SSR __NEXT_DATA__ 的 pageProps 中解析阵容。
    SSR 结构: pageProps.content.lineup
    """
    content    = page_props.get("content", {})
    raw_lineup = content.get("lineup")

    if not raw_lineup:
        log.warning(f"[Lineup] match_id={match_id} 阵容字段缺失（赛前 >3h 或尚未录入）")
        return None

    # ── 比赛状态（general.started / general.finished）──────────────────
    # FotMob API 在 pageProps.general 中暴露 started/finished 布尔值。
    # 比赛已开球 → 场上 11 人必然是真实首发，可直接判 confirmed。
    general       = page_props.get("general", {})
    match_started  = bool(general.get("started", False))
    match_finished = bool(general.get("finished", False))

    # ── 确认状态 ──────────────────────────────────────────────────────────
    lineup_type   = raw_lineup.get("lineupType", "")
    lineup_source = raw_lineup.get("source", "")
    lineup_status = "predicted"

    # 直接字段判断（多种 FotMob 格式均兼容）
    if (raw_lineup.get("confirmed")
            or raw_lineup.get("lineupStatus") == "Confirmed"
            or raw_lineup.get("isConfirmed")
            or lineup_type.lower() in ("standard", "confirmed")):   # 大小写兼容
        lineup_status = "confirmed"

    # ── 解析双方阵容 ──────────────────────────────────────────────────────
    # 优先使用 homeTeam / awayTeam 键（旧格式），降级到 lineup 数组（新格式）
    h_raw = raw_lineup.get("homeTeam") or raw_lineup.get("home")
    a_raw = raw_lineup.get("awayTeam") or raw_lineup.get("away")

    if not h_raw or not a_raw:
        # 新格式：lineup.lineup = [homeTeamDict, awayTeamDict]
        lineup_list = raw_lineup.get("lineup") or raw_lineup.get("confirmedLineup") or []
        if len(lineup_list) >= 2:
            h_raw = lineup_list[0]
            a_raw = lineup_list[1]
        else:
            log.warning(f"[Lineup] match_id={match_id} 无法定位主客队阵容数据")
            return None

    h_form, h_start, h_bench, h_miss = _parse_side(h_raw)
    a_form, a_start, a_bench, a_miss = _parse_side(a_raw)

    # ── enetpulse 确认检测 ──────────────────────────────────────────────
    # FotMob SSR 的 __NEXT_DATA__ 与直接 API 结构不同，存在两个已知差异：
    #   1. lineupType 在 SSR 缓存中可能与直接 API 值不一致（故加 .lower() 兼容）
    #   2. SSR 格式不包含 subs/bench 列表（bench=0），但直接 API 有完整替补数据
    #
    # 因此额外引入两个可靠的确认信号（优先级从高到低）：
    #   A. 比赛已开球/已结束（general.started / general.finished）
    #      → 上场的 11 人就是真实首发，无歧义
    #   B. enetpulse 来源 + bench≥7（SSR 有时包含完整替补数据）
    if lineup_status == "predicted" and lineup_source == "enetpulse":
        h_cnt = len(h_start)
        a_cnt = len(a_start)

        if len(h_bench) >= 7 and len(a_bench) >= 7 and h_cnt == 11 and a_cnt == 11:
            # 信号 B：SSR 含完整替补数据
            lineup_status = "confirmed"
            log.info(f"[Lineup] match_id={match_id} enetpulse + 11v11 + bench≥7 → confirmed")

        elif (match_started or match_finished) and h_cnt == 11 and a_cnt == 11:
            # 信号 A：比赛已开球/结束，SSR 无 bench 不影响首发真实性
            lineup_status = "confirmed"
            phase = "finished" if match_finished else "started"
            log.info(
                f"[Lineup] match_id={match_id} enetpulse + match {phase} + 11v11 → confirmed "
                f"(bench在SSR中为0，系SSR缓存未含替补数据，不影响首发判断)"
            )

        elif lineup_type.lower() == "standard" and h_cnt == 11 and a_cnt == 11:
            # 信号 C：lineupType=standard（直接 API 字段透传到 SSR 时的降级兼容）
            lineup_status = "confirmed"
            log.info(f"[Lineup] match_id={match_id} enetpulse + lineupType=standard + 11v11 → confirmed")

        else:
            log.info(
                f"[Lineup] match_id={match_id} enetpulse predicted "
                f"(bench: {len(h_bench)}+{len(a_bench)}, starters: {h_cnt}+{a_cnt}, "
                f"started={match_started}, finished={match_finished}, lineupType={lineup_type!r})"
            )

    # ── 批量查 DB 球员指标 ─────────────────────────────────────────────────
    all_players = h_start + h_bench + h_miss + a_start + a_bench + a_miss
    all_ids     = [p["id"] for p in all_players if p.get("id")]
    stats       = _query_player_stats(conn, all_ids)

    h_miss_e = _enrich(h_miss, stats, "Unavailable")
    a_miss_e = _enrich(a_miss, stats, "Unavailable")

    lineup_data = {
        "status":     lineup_status,
        "fetched_at": datetime.now().isoformat(),
        "home": {
            "formation":    h_form,
            "starters":     _enrich(h_start, stats),
            "bench":        _enrich(h_bench, stats),
            "missing":      h_miss_e,
            "key_absences": _key_absences(h_miss_e),
        },
        "away": {
            "formation":    a_form,
            "starters":     _enrich(a_start, stats),
            "bench":        _enrich(a_bench, stats),
            "missing":      a_miss_e,
            "key_absences": _key_absences(a_miss_e),
        },
    }

    log.info(
        f"[Lineup] ✅ [{lineup_status}] "
        f"主({h_form} 首发{len(h_start)} 替补{len(h_bench)} 缺{len(h_miss)}) "
        f"客({a_form} 首发{len(a_start)} 替补{len(a_bench)} 缺{len(a_miss)})"
    )
    return lineup_data


# ──────────────────────────────────────────
# 主入口（与旧版接口完全兼容）
# ──────────────────────────────────────────
def fetch_lineup(match_id: str) -> dict | None:
    """
    单场抓取首发阵容。
    用于单独调试或 poll_lineup.py 中的单场调用。
    批量请使用 fetch_lineups_batch()。

    使用直接 JSON API（无 CDN 缓存），能实时捕捉
    lineupType: "predicted" → "standard" 的转变。
    """
    from fotmob_client import FotMobClient
    log.info(f"[Lineup] 开始抓取 match_id={match_id}")

    client = FotMobClient()
    conn   = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        page_props = client.match_details(match_id)
        return _parse_lineup_from_ssr(page_props, str(match_id), conn)
    except Exception as e:
        log.error(f"[Lineup] 抓取异常: {e}")
        return None
    finally:
        conn.close()


def fetch_lineups_batch(match_ids: list) -> dict:
    """
    批量抓取多场阵容（复用同一 FotMobClient 实例，比循环调用 fetch_lineup 更高效）。
    返回 {match_id_str: lineup_data | None}

    使用直接 JSON API（无 CDN 缓存）。
    """
    from fotmob_client import FotMobClient
    log.info(f"[Lineup] 批量抓取 {len(match_ids)} 场: {match_ids}")

    client = FotMobClient()
    conn   = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    results = {}
    try:
        for mid in match_ids:
            mid_str = str(mid)
            try:
                page_props = client.match_details(mid_str)
                results[mid_str] = _parse_lineup_from_ssr(page_props, mid_str, conn)
            except Exception as e:
                log.error(f"[Lineup] match_id={mid_str} 抓取异常: {e}")
                results[mid_str] = None
            time.sleep(random.uniform(1.5, 3.0))   # 场间间隔（无需像浏览器那么长）
    finally:
        conn.close()

    ok = sum(1 for v in results.values() if v)
    log.info(f"[Lineup] 批量完成: {ok}/{len(match_ids)} 场成功")
    return results


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    mid = sys.argv[1] if len(sys.argv) > 1 else "4803343"
    result = fetch_lineup(mid)
    print(json.dumps(result, ensure_ascii=False, indent=2))
