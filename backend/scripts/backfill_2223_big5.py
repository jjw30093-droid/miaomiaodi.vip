"""
backfill_2223_big5.py — 2022/23 赛季 BIG5 历史数据回填脚本

目标：将五大联赛 2022/23 赛季的比赛数据写入：
  - dim_match
  - fact_shotmap
  - fact_player_match_stats
  - fact_team_match_stats
  - dim_player

设计原则：
  - 已完整的比赛（dim_match 有比分 + shotmap 有记录）直接跳过
  - 断点续传：每场写完立即 commit，中断后重跑自动跳过已完成场次
  - 礼貌限速：每场请求后随机等待 2~5 秒
  - Dry-run 模式：只列出待抓场次，不实际请求
  - 失败不中断：单场失败记 ingest_failure_log，继续下一场

用法:
  # Dry-run（列出待抓场次，不抓取）
  python3 scripts/backfill_2223_big5.py --dry-run

  # 正式运行
  python3 scripts/backfill_2223_big5.py

  # 只处理某个联赛
  python3 scripts/backfill_2223_big5.py --league 47

  # 限制每次最多抓 N 场（分批运行）
  python3 scripts/backfill_2223_big5.py --limit 50
"""

import os
import sys
import time
import random
import sqlite3
import logging
import argparse
from pathlib import Path
from typing import Optional

# ── 路径配置 ────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.environ.get(
    "PROJECT_ROOT",
    str(Path(__file__).resolve().parent.parent)
)
DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))
sys.path.insert(0, PROJECT_ROOT)

from fotmob_client import FotMobClient
from ingest_failure_helper import record_failure

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(PROJECT_ROOT, "logs", "backfill_2223.log"),
            mode="a",
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger(__name__)

# ── 目标配置 ────────────────────────────────────────────────────────────────
SEASON_STR = "2022/2023"          # DB 中 Season 字段存储格式
FOTMOB_SEASON = "2022/2023"       # FotMob API season 参数格式

# BIG5 联赛：DB League_ID → 名称（与 fotmob_client.py 中 BIG_FIVE_LIDS 一致）
BIG5_LEAGUES = {
    47: "EPL (英超)",
    87: "La Liga (西甲)",
    54: "Bundesliga (德甲)",
    55: "Serie A (意甲)",
    53: "Ligue 1 (法甲)",
}

# 理论全赛季场数（用于进度展示）
SEASON_TOTAL = {
    47: 380,
    87: 380,
    54: 306,
    55: 380,
    53: 306,
}

# 请求间隔（秒）
DELAY_MIN = 2.5
DELAY_MAX = 5.0

# ── 射门坐标系常量 ───────────────────────────────────────────────────────────
# FotMob 使用真实米数坐标（105m × 68m 球场，进攻方向 x 值增大趋向对方球门）
# 禁区边界：距对方球门线 16.5m（x > 88.5），宽 40.32m 居中（y: 13.84 ~ 54.16）
BOX_X_MIN = 88.5
BOX_Y_MIN = 13.84
BOX_Y_MAX = 54.16

# Situation 分类集合（与 fact_shotmap.Situation 字段一致）
OPEN_PLAY_SITS = {"RegularPlay", "FastBreak", "IndividualPlay"}
SET_PLAY_SITS  = {"FromCorner", "SetPiece", "FreeKick", "ThrowInSetPiece"}
PENALTY_SIT    = "Penalty"


# ── DB 工具 ─────────────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _upsert_ignore(conn: sqlite3.Connection, table: str, rec: dict):
    """
    INSERT OR IGNORE — 仅插入 DB 中不存在的行。
    列名用双引号包裹（兼容含点号的列名，如 matchstats.headers.tackles）。
    """
    rec = {k: v for k, v in rec.items() if v is not None}
    if not rec:
        return
    cols = list(rec.keys())
    placeholders = [f":{c.replace('.', '_dot_')}" for c in cols]
    bindings = {c.replace('.', '_dot_'): v for c, v in rec.items()}
    col_sql = ", ".join(f'"{c}"' for c in cols)
    ph_sql  = ", ".join(placeholders)
    conn.execute(
        f'INSERT OR IGNORE INTO "{table}" ({col_sql}) VALUES ({ph_sql})',
        bindings,
    )


# ── 从 shotmap 推算缺失的 team_stats 字段 ────────────────────────────────────

def _derive_stats_from_shotmap(shots: list) -> dict:
    """
    从已抓取的 shotmap 数据推算 fact_team_match_stats 里 2022/23 旧 API 可能缺失的字段。

    可推算（不依赖旧页面是否提供）：
      shots_inside_box / shots_outside_box     — 仅依赖 X/Y 坐标
      expected_goals_non_penalty               — SUM(xG) 排除点球（坐标辅助识别）

    条件可推算（依赖 Situation 字段是否存在）：
      expected_goals_open_play / expected_goals_set_play
      — 若 shots 中无任何 Situation 数据，返回 None（不强行写 0）

    不可推算（仍 NULL）：
      own_half_passes / opposition_half_passes  — 需要传球位置数据，shotmap 无法提供

    Returns: {team_id: {col_name: value_or_None}}
    """
    from collections import defaultdict

    by_team = defaultdict(lambda: {
        "inside": 0, "outside": 0,
        "xg_open": 0.0, "xg_set": 0.0, "xg_nonpen": 0.0,
        "has_sit": False,   # 是否有任何有效 Situation 值
        "has_xy":  False,   # 是否有任何有效坐标
    })

    for shot in shots:
        tid = shot.get("Team_ID")
        if not tid:
            continue

        t   = by_team[tid]
        x   = shot.get("X_Coord")
        y   = shot.get("Y_Coord")
        xg  = float(shot.get("xG") or 0.0)
        sit = shot.get("Situation")   # 可能为 None（旧场次 SSR 缺失）

        # ── 禁区内外（仅依赖坐标）────────────────────────────
        if x is not None and y is not None:
            t["has_xy"] = True
            if x > BOX_X_MIN and BOX_Y_MIN < float(y) < BOX_Y_MAX:
                t["inside"] += 1
            else:
                t["outside"] += 1

        # ── xG 分类（依赖 Situation）──────────────────────────
        if sit == PENALTY_SIT:
            # 点球：不计入 non_penalty / open / set
            pass
        elif sit in OPEN_PLAY_SITS:
            t["has_sit"] = True
            t["xg_open"]   += xg
            t["xg_nonpen"] += xg
        elif sit in SET_PLAY_SITS:
            t["has_sit"] = True
            t["xg_set"]    += xg
            t["xg_nonpen"] += xg
        elif sit is None:
            # Situation 缺失时：用坐标+xG值启发式判断是否为点球
            # 点球特征：xG > 0.70 且落点接近点球点 (x≈94, y≈34)
            is_likely_penalty = (
                xg > 0.70
                and x is not None and x > 90
                and y is not None and abs(float(y) - 34) < 5
            )
            if not is_likely_penalty:
                t["xg_nonpen"] += xg   # 保守计入 non_penalty
        else:
            # 未知新分类（未来 FotMob 可能新增），按开放进攻球处理
            t["has_sit"] = True
            t["xg_open"]   += xg
            t["xg_nonpen"] += xg

    result = {}
    for tid, t in by_team.items():
        result[tid] = {
            # 坐标可推算（有坐标数据时写入，否则 None）
            "shots_inside_box":          t["inside"]  if t["has_xy"] else None,
            "shots_outside_box":         t["outside"] if t["has_xy"] else None,
            # Situation 可推算（有 Situation 数据时写入，否则 None）
            "expected_goals_open_play":  round(t["xg_open"], 4)   if t["has_sit"] else None,
            "expected_goals_set_play":   round(t["xg_set"], 4)    if t["has_sit"] else None,
            # non_penalty 用坐标启发式辅助，始终写入（有 shots 时）
            "expected_goals_non_penalty": round(t["xg_nonpen"], 4) if t["has_xy"] else None,
        }
    return result


def _apply_derived_stats(conn: sqlite3.Connection, match_id: int, shots: list):
    """
    推算 shotmap 派生字段，用 COALESCE 方式回填 fact_team_match_stats。
    只更新 IS NULL 的列，不覆盖 FotMob API 已写入的数据。
    仅更新 Period='All' 行（训练特征只用 All）。
    """
    derived = _derive_stats_from_shotmap(shots)
    if not derived:
        return

    for team_id, stats in derived.items():
        updates = {k: v for k, v in stats.items() if v is not None}
        if not updates:
            continue

        set_sql = ", ".join(f'"{k}" = COALESCE("{k}", ?)' for k in updates)
        conn.execute(
            f'UPDATE fact_team_match_stats SET {set_sql} '
            f'WHERE Match_ID = ? AND Team_ID = ? AND Period = \'All\'',
            list(updates.values()) + [match_id, team_id],
        )

    log.debug("  [derive] match=%d 推算字段已回填", match_id)


# ── 完整性检查 ───────────────────────────────────────────────────────────────

def check_existing(conn: sqlite3.Connection, match_id: int) -> dict:
    """
    返回某场比赛在各表中的现有数据状态。
    {
      'in_dim':         bool,   # dim_match 已有该场且有比分
      'shotmap_count':  int,    # fact_shotmap 记录数
      'player_count':   int,    # fact_player_match_stats 记录数
      'team_count':     int,    # fact_team_match_stats 记录数
    }
    """
    row = conn.execute(
        "SELECT home_score, away_score, status FROM dim_match WHERE Match_ID = ?",
        (match_id,)
    ).fetchone()
    in_dim = row is not None and row["home_score"] is not None

    # Unknown 状态 = 延期/判负/取消场次，FotMob 永远无 shotmap 数据，直接标完整跳过
    if row is not None and row["status"] == "Unknown":
        return {"in_dim": True, "shotmap_count": 999, "player_count": 999, "team_count": 999}

    sc = conn.execute(
        "SELECT COUNT(*) FROM fact_shotmap WHERE Match_ID = ?",
        (match_id,)
    ).fetchone()[0]

    pc = conn.execute(
        "SELECT COUNT(*) FROM fact_player_match_stats WHERE Match_ID = ?",
        (match_id,)
    ).fetchone()[0]

    tc = conn.execute(
        "SELECT COUNT(*) FROM fact_team_match_stats WHERE Match_ID = ?",
        (match_id,)
    ).fetchone()[0]

    return {
        "in_dim":        in_dim,
        "shotmap_count": sc,
        "player_count":  pc,
        "team_count":    tc,
    }


def is_complete(status: dict) -> bool:
    """
    完整性定义：dim_match 有比分 + shotmap 至少有 1 条 + player_stats 至少有 1 条。
    team_stats 允许为 0（部分旧场次 API 不返回）。
    """
    return (
        status["in_dim"]
        and status["shotmap_count"] > 0
        and status["player_count"] > 0
    )


# ── 联赛 Fixtures 解析 ────────────────────────────────────────────────────────

def parse_fixtures(league_data: dict, league_id: int) -> list[dict]:
    """
    从 FotMob leagues API 响应中提取 fixtures 列表。
    FotMob 有两种结构：
      1. data["allMatches"] — 平铺列表
      2. data["matches"]["allMatches"] — 嵌套
      3. data["fixtures"] / data["rounds"] — 旧格式

    每个 fixture 提取:
      {match_id, home_id, home_name, away_id, away_name,
       date (YYYY-MM-DD UTC), round, status_finished}
    """
    fixtures = []

    # 尝试各种路径（优先级从高到低）
    raw_list = (
        league_data.get("allMatches")                              # 平铺列表
        or league_data.get("matches", {}).get("allMatches")       # 嵌套 matches
        or league_data.get("fixtures", {}).get("allMatches")      # fixtures.allMatches（FotMob 当前格式）
        or []
    )

    # 旧格式：rounds → 展开
    if not raw_list:
        for round_obj in league_data.get("rounds", []):
            raw_list.extend(round_obj.get("matches", []))

    log.info("  [parse_fixtures] 原始记录数: %d", len(raw_list))

    for m in raw_list:
        match_id = m.get("id")
        if not match_id:
            continue

        # 主客队
        home = m.get("home") or {}
        away = m.get("away") or {}

        # 日期：优先取 UTC 时间
        status = m.get("status") or {}
        utc_time = status.get("utcTime") or m.get("utcTime") or ""
        date_str = utc_time.split("T")[0] if "T" in utc_time else utc_time[:10]
        if not date_str:
            date_str = (m.get("date") or m.get("matchDate") or "")[:10]

        # 是否已完赛
        finished = bool(
            status.get("finished")
            or status.get("reason", {}).get("short") in ("FT", "AET", "Pen")
        )

        fixtures.append({
            "match_id":       int(match_id),
            "home_id":        home.get("id"),
            "home_name":      home.get("name") or home.get("shortName"),
            "away_id":        away.get("id"),
            "away_name":      away.get("name") or away.get("shortName"),
            "date":           date_str,
            "round":          m.get("roundId") or m.get("round"),
            "finished":       finished,
        })

    return fixtures


# ── 单场数据写入 ──────────────────────────────────────────────────────────────

def upsert_match(
    conn: sqlite3.Connection,
    client: FotMobClient,
    fixture: dict,
    league_id: int,
) -> bool:
    """
    抓取并写入单场比赛的全部数据。
    返回 True=成功，False=失败（已记 ingest_failure_log）。
    """
    match_id = fixture["match_id"]
    label    = f"{fixture['home_name']} vs {fixture['away_name']} [{match_id}]"

    try:
        # 1. 抓取 SSR 页面
        page_props = client.match_details(match_id)

        # 2. dim_match
        dim = client.parse_match_dim(
            page_props,
            match_id,
            league_id=league_id,
            date=fixture["date"],
            season=SEASON_STR,
        )
        _upsert_ignore(conn, "dim_match", dim)

        # 3. fact_shotmap
        shots = client.parse_shotmap_records(page_props, match_id)
        for s in shots:
            _upsert_ignore(conn, "fact_shotmap", s)

        # 4. fact_player_match_stats + dim_player
        players = client.parse_player_stats_records(page_props, match_id)
        for p in players:
            # dim_player 只需要 player_id + player_name
            if p.get("player_name"):
                _upsert_ignore(conn, "dim_player", {
                    "player_id":   str(p["Player_ID"]),
                    "player_name": p["player_name"],
                })
            _upsert_ignore(conn, "fact_player_match_stats", p)

        # 5. fact_team_match_stats
        team_stats = client.parse_team_stats_records(page_props, match_id)
        for ts in team_stats:
            _upsert_ignore(conn, "fact_team_match_stats", ts)

        # 6. 从 shotmap 推算并回填可能缺失的高风险字段
        #    （旧 FotMob 页面可能不含 xG-split / shots_inside_box 等）
        #    COALESCE 方式：只填 NULL，不覆盖 API 已有值
        _apply_derived_stats(conn, match_id, shots)

        conn.commit()

        # 记录推算情况（辅助验证）
        has_sit = any(s.get("Situation") for s in shots)
        log.info(
            "  ✅ %s | shots=%d(sit=%s) players=%d teams=%d",
            label, len(shots), "✓" if has_sit else "✗(坐标推算)",
            len(players), len(team_stats)
        )
        return True

    except Exception as e:
        conn.rollback()
        log.error("  ❌ %s 失败: %s", label, e)
        record_failure(
            "backfill_2223_big5",
            match_id=str(match_id),
            step="fetch_or_insert",
            error_msg=str(e)[:500],
        )
        return False


# ── 主流程 ────────────────────────────────────────────────────────────────────

def run(
    league_filter: Optional[int],
    dry_run: bool,
    limit: Optional[int],
):
    client = FotMobClient()
    conn   = get_conn()

    # 代理验证
    try:
        ip_info = client.check_ip()
        log.info("🌐 代理 IP: %s", ip_info.get("origin", "?"))
    except Exception as e:
        log.warning("代理 IP 验证失败（继续）: %s", e)

    total_fetched   = 0
    total_skipped   = 0
    total_failed    = 0
    total_already   = 0

    leagues = {k: v for k, v in BIG5_LEAGUES.items()
               if league_filter is None or k == league_filter}

    for league_id, league_name in leagues.items():
        log.info("=" * 70)
        log.info("📋 联赛: %s (LID=%d)  赛季: %s", league_name, league_id, SEASON_STR)

        # Step 1: 获取赛季 Fixtures
        log.info("  📡 拉取赛季 fixtures...")
        try:
            league_data = client.league_matches(league_id, season=FOTMOB_SEASON)
        except Exception as e:
            log.error("  ❌ 无法获取 fixtures for LID=%d: %s", league_id, e)
            record_failure(
                "backfill_2223_big5",
                match_id=None,
                step="fetch_fixtures",
                error_msg=f"league {league_id}: {e}",
            )
            continue

        fixtures = parse_fixtures(league_data, league_id)
        log.info(
            "  📌 共 %d 场 fixtures（理论 %d 场）",
            len(fixtures), SEASON_TOTAL.get(league_id, "?")
        )

        # 只处理已完赛场次（防止抓到空白 future 场次）
        finished = [f for f in fixtures if f["finished"]]
        log.info("  ✅ 其中已完赛: %d 场", len(finished))

        if not finished:
            log.warning("  ⚠️  无已完赛场次，跳过。（注：2022/23 全部场次应已完赛）")
            continue

        # Step 2: 完整性检查 + 筛出待处理场次
        to_fetch = []
        for f in finished:
            status = check_existing(conn, f["match_id"])
            if is_complete(status):
                total_already += 1
            else:
                to_fetch.append((f, status))

        log.info(
            "  📊 已完整: %d场 | 待抓取: %d场",
            len(finished) - len(to_fetch), len(to_fetch)
        )

        if dry_run:
            log.info("  [DRY-RUN] 以下场次待抓取（前20场）:")
            for f, st in to_fetch[:20]:
                log.info(
                    "    [%d] %s vs %s (%s)  dim=%s shots=%d players=%d",
                    f["match_id"], f["home_name"], f["away_name"], f["date"],
                    "✓" if st["in_dim"] else "✗",
                    st["shotmap_count"], st["player_count"]
                )
            if len(to_fetch) > 20:
                log.info("    ... 还有 %d 场", len(to_fetch) - 20)
            total_skipped += len(to_fetch)
            continue

        # Step 3: 逐场抓取
        for idx, (f, _) in enumerate(to_fetch, 1):
            if limit is not None and total_fetched >= limit:
                log.info("  ⏸️  已达到 --limit %d 限制，停止", limit)
                break

            log.info(
                "  [%d/%d] %s vs %s (%s)",
                idx, len(to_fetch),
                f["home_name"], f["away_name"], f["date"]
            )

            ok = upsert_match(conn, client, f, league_id)
            if ok:
                total_fetched += 1
            else:
                total_failed += 1

            # 礼貌限速
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            time.sleep(delay)

    conn.close()

    # 汇总
    log.info("=" * 70)
    log.info("🏁 回填完成")
    log.info("   已跳过（数据完整）: %d 场", total_already)
    log.info("   本次成功写入:       %d 场", total_fetched)
    log.info("   失败（已记日志）:   %d 场", total_failed)
    if dry_run:
        log.info("   [DRY-RUN] 待处理:  %d 场（未实际抓取）", total_skipped)


# ── CLI 入口 ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="回填 2022/23 BIG5 历史数据")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只列出待抓场次，不实际请求 FotMob"
    )
    parser.add_argument(
        "--league", type=int, default=None,
        choices=list(BIG5_LEAGUES.keys()),
        help="只处理指定联赛 ID（47/87/54/55/53）"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="最多抓取 N 场后停止（断点续传用）"
    )
    args = parser.parse_args()

    log.info("🚀 backfill_2223_big5.py 启动")
    log.info("   DB: %s", DB_PATH)
    log.info("   模式: %s", "DRY-RUN" if args.dry_run else "正式运行")
    log.info("   联赛过滤: %s", args.league or "全部 BIG5")
    log.info("   场数限制: %s", args.limit or "无限制")

    run(
        league_filter=args.league,
        dry_run=args.dry_run,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
