"""
batch_fotmob_sync.py v2.0（无浏览器版）
=========================================
每天 11:00 执行，将前一天 12:00 → 当天 11:00 结束的比赛数据入库。

变更：DrissionPage + Chrome → FotMobClient（curl_cffi + ThorData 代理）

写入表：
  - dim_match
  - fact_team_match_stats
  - fact_shotmap
  - fact_player_match_stats
  - dim_player
"""

import os
import sys
import time
import random
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 失败日志 helper（写 ingest_failure_log；永不抛异常）
from ingest_failure_helper import record_failure

# ── 项目路径 ─────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.environ.get("PROJECT_ROOT", str(Path(__file__).resolve().parent.parent))
DB_PATH      = os.environ.get("DB_PATH",      os.path.join(PROJECT_ROOT, "football_uk.db"))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── 联赛 ID 配置 ─────────────────────────────────────────────────────────────
BIG_FIVE_LIDS     = [47, 87, 54, 55, 53]
DOMESTIC_CUP_LIDS = [132, 133, 138, 209, 141, 134]
EURO_LIDS         = [42, 73, 10216]
ASIA_PAC_LIDS     = [223, 9080, 113]
TARGET_LIDS       = BIG_FIVE_LIDS + DOMESTIC_CUP_LIDS + EURO_LIDS + ASIA_PAC_LIDS
TARGET_LIDS_SET   = set(TARGET_LIDS)
WHITELIST_LIDS    = set(BIG_FIVE_LIDS + DOMESTIC_CUP_LIDS + EURO_LIDS)

# 7 天窗口（从 6 扩到 7，兼容 04-17 这类卡边场景 + 给 closing_odds 漏抓留余地）
# CLAUDE.md §4：FotMob API 按 CST(UTC+8) 分桶，必须用 CST 日期作查询参数。
# 修复（2026-05-04）：原用 datetime.now()（裸 UTC），深夜 UTC 00-08 期间与 CST 日期差 1 天。
_CST = timezone(timedelta(hours=8))
TARGET_DATES = [(datetime.now(_CST) - timedelta(days=i)).strftime("%Y%m%d") for i in range(0, 7)]


# ─────────────────────────────────────────────────────────────────────────────
# 球队白名单（五大联赛顶级球队 ID）
# ─────────────────────────────────────────────────────────────────────────────
def fetch_top_tier_teams(client) -> tuple:
    """
    动态从五大联赛联赛表获取顶级球队 ID + 名称白名单。
    返回 (id_set, name_set)
    """
    log.info("📡 动态提取五大联赛球队白名单...")
    team_ids   = set()
    team_names = set()

    def _add(tid, name):
        if tid is not None:
            team_ids.add(str(tid))
        if name:
            team_names.add(name.lower().strip())

    for lid in BIG_FIVE_LIDS:
        try:
            data = client.league_matches(lid)
            added = 0
            # 从 standings table 提取
            tables = data.get("table", [])
            if isinstance(tables, dict):
                tables = [tables]
            for t in tables:
                for entry in t.get("data", {}).get("table", {}).get("all", []):
                    _add(entry.get("id"), entry.get("name") or entry.get("shortName"))
                    added += 1
            # 从 overview.teams 提取（备选路径）
            for team in data.get("overview", {}).get("teams", []):
                _add(team.get("id"), team.get("name"))
                added += 1
            log.info(f"   League {lid}: {added} 支球队")
        except Exception as e:
            log.warning(f"   League {lid} 白名单获取失败: {e}")
            record_failure("batch_fotmob_sync", match_id=None, step="fetch", error_msg=f"league {lid}: {e}")

    log.info(f"✅ 白名单共 {len(team_ids)} 支球队")
    return team_ids, team_names


def _name_matches_whitelist(team_name: str, name_set: set) -> bool:
    n = team_name.lower().strip()
    for wn in name_set:
        if len(wn) > 4 and (n in wn or wn in n):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# DB 工具
# ─────────────────────────────────────────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _upsert(conn, table: str, rec: dict, unique_keys: list | None = None):
    """INSERT OR IGNORE，只插入非 None 的字段。
    列名用双引号包裹（支持含点号的列名如 matchstats.headers.tackles）；
    绑定参数名用 _dot_ 替换点号（SQLite 不允许参数名含点号）。
    """
    rec = {k: v for k, v in rec.items() if v is not None}
    if not rec:
        return

    # 获取主键（如果没传 unique_keys，查 sqlite schema）
    # 注意：部分 fact_* 表没有 PK / UNIQUE 约束；此时退回 INSERT OR IGNORE（避免阻断回灌 dim_match）
    if not unique_keys:
        pk_info = conn.execute(f"PRAGMA table_info({table})").fetchall()
        unique_keys = [r[1] for r in pk_info if r[5] > 0]  # pk 列

    cols = list(rec.keys())
    cols_sql = ", ".join(f'"{c}"' for c in cols)
    vals_sql = ", ".join(f":{c.replace('.', '_dot_')}" for c in cols)

    # ON CONFLICT DO UPDATE：更新非主键字段（rec 已过滤 None，所以不会用 None 覆盖旧值）
    if not unique_keys:
        params = {k.replace(".", "_dot_"): v for k, v in rec.items()}
        sql = f'INSERT OR IGNORE INTO {table} ({cols_sql}) VALUES ({vals_sql})'
        conn.execute(sql, params)
        return

    update_cols = [c for c in cols if c not in unique_keys]
    pk_sql = ", ".join(f'"{k}"' for k in unique_keys)

    params = {k.replace(".", "_dot_"): v for k, v in rec.items()}

    if update_cols:
        set_sql = ", ".join(f'"{c}"=excluded."{c}"' for c in update_cols)
        sql = (
            f'INSERT INTO {table} ({cols_sql}) VALUES ({vals_sql}) '
            f'ON CONFLICT({pk_sql}) DO UPDATE SET {set_sql}'
        )
    else:
        sql = f'INSERT OR IGNORE INTO {table} ({cols_sql}) VALUES ({vals_sql})'

    conn.execute(sql, params)


# ─────────────────────────────────────────────────────────────────────────────
# 主写入逻辑
# ─────────────────────────────────────────────────────────────────────────────
def sync_match(client, mid: str, lid: int, date: str, season: str = "2025/2026"):
    """
    抓取单场比赛详情并写入所有相关表。
    """
    log.info(f"  🔍 抓取 matchId={mid}...")
    try:
        page_props = client.match_details(mid)
    except Exception as e:
        log.error(f"  ❌ match_details 失败: {e}")
        record_failure("batch_fotmob_sync", match_id=mid if 'mid' in locals() else None, step="fetch", error_msg=str(e))
        return False

    # ── 解析 ──────────────────────────────────────────────────────────────
    try:
        dim_rec    = client.parse_match_dim(page_props, mid, league_id=lid, date=date, season=season)
        shots      = client.parse_shotmap_records(page_props, mid)
        t_stats    = client.parse_team_stats_records(page_props, mid)
        p_records  = client.parse_player_stats_records(page_props, mid)
    except Exception as e:
        log.error(f"  ❌ 解析失败: {e}")
        import traceback; traceback.print_exc()
        record_failure("batch_fotmob_sync", match_id=mid if 'mid' in locals() else None, step="parse", error_msg=str(e))
        return False

    # ── 写入 DB ───────────────────────────────────────────────────────────
    try:
        conn = get_conn()

        # dim_match
        _upsert(conn, "dim_match", dim_rec)
        conn.commit()
        log.info(f"  📥 dim_match 写入: {dim_rec.get('Home_Team_Name')} vs {dim_rec.get('Away_Team_Name')}")

        # fact_team_match_stats
        for rec in t_stats:
            _upsert(conn, "fact_team_match_stats", rec)
        conn.commit()
        log.info(f"  📥 fact_team_match_stats 写入: {len(t_stats)} 条")

        # fact_shotmap
        for s in shots:
            _upsert(conn, "fact_shotmap", s)
        conn.commit()
        log.info(f"  📥 fact_shotmap 写入: {len(shots)} 条")

        # fact_player_match_stats + dim_player
        inserted_players = 0
        for rec in p_records:
            # 检查是否已存在（避免重复）
            exists = conn.execute(
                "SELECT 1 FROM fact_player_match_stats WHERE Match_ID=? AND Player_ID=?",
                (rec["Match_ID"], str(rec["Player_ID"]))
            ).fetchone()
            if not exists:
                _upsert(conn, "fact_player_match_stats", rec)
                inserted_players += 1

            # dim_player
            pid  = str(rec["Player_ID"])
            name = rec.get("player_name")
            if name:
                existing = conn.execute(
                    "SELECT player_name FROM dim_player WHERE player_id=?", (pid,)
                ).fetchone()
                if existing:
                    if not existing["player_name"]:
                        conn.execute(
                            "UPDATE dim_player SET player_name=? WHERE player_id=?", (name, pid)
                        )
                else:
                    conn.execute(
                        "INSERT OR IGNORE INTO dim_player (player_id, player_name) VALUES (?, ?)",
                        (pid, name)
                    )
        conn.commit()
        log.info(f"  📥 fact_player_match_stats 写入: {inserted_players}/{len(p_records)} 人")

        conn.close()
        return True

    except Exception as e:
        log.error(f"  ❌ DB 写入失败: {e}")
        import traceback; traceback.print_exc()
        record_failure("batch_fotmob_sync", match_id=mid if 'mid' in locals() else None, step="insert", error_msg=str(e))
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────────────────────
def main():
    from fotmob_client import FotMobClient
    client = FotMobClient()

    log.info("=" * 60)
    log.info("⚡️ FotMob 多联赛同步引擎 v2.0（curl_cffi 无浏览器版）")
    log.info(f"📆 扫描日期窗口: {TARGET_DATES}")
    log.info("=" * 60)

    # 1. 获取球队白名单
    TOP_TIER_IDS, TOP_TIER_NAMES = fetch_top_tier_teams(client)

    # 2. 获取已完整入库比赛 ID（避免重复）
    conn = get_conn()
    existing_ids = {
        str(r[0]) for r in conn.execute(
            """
            SELECT DISTINCT f.Match_ID
            FROM fact_team_match_stats f
            JOIN dim_match d ON CAST(d.Match_ID AS TEXT) = CAST(f.Match_ID AS TEXT)
            WHERE d.home_score IS NOT NULL AND d.away_score IS NOT NULL
            """
        ).fetchall()
    }
    conn.close()

    # 3. 扫描各日期赛程，找出需要同步的比赛
    all_tasks = []
    for d in TARGET_DATES:
        log.info(f"\n📡 扫描 [{d}] 赛程...")
        try:
            data = client.daily_matches(d)
        except Exception as e:
            log.error(f"❌ [{d}] 日程请求失败: {e}")
            record_failure("batch_fotmob_sync", match_id=None, step="fetch", error_msg=f"daily {d}: {e}")
            continue

        for league in data.get("leagues", []):
            lid = league.get("primaryId") or league.get("id")
            if lid not in TARGET_LIDS_SET:
                continue

            league_name = league.get("name", "")
            for match in league.get("matches", []):
                status = match.get("status", {})
                # 只处理已结束的比赛
                if not status.get("finished"):
                    continue

                mid = str(match.get("id", ""))
                if not mid or mid in existing_ids:
                    continue

                home_name = match.get("home", {}).get("name", "")
                away_name = match.get("away", {}).get("name", "")
                home_id   = str(match.get("home", {}).get("id", ""))
                away_id   = str(match.get("away", {}).get("id", ""))
                match_name = f"{home_name} vs {away_name}"

                # 欧洲赛事 + 杯赛需白名单过滤
                if lid in WHITELIST_LIDS:
                    id_ok   = home_id in TOP_TIER_IDS or away_id in TOP_TIER_IDS
                    name_ok = (_name_matches_whitelist(home_name, TOP_TIER_NAMES) or
                               _name_matches_whitelist(away_name, TOP_TIER_NAMES))
                    if not id_ok and not name_ok:
                        log.debug(f"  🚫 过滤（非顶级球队）: {match_name}")
                        continue

                # 用 utcTime 解析 UTC 开球日期，避免 Fotmob 按 CST 分桶导致
                # dim_match.Date 与 report_store.match_time 日期错位（差 1 天）。
                utc_time = status.get("utcTime", "")
                try:
                    _t = utc_time.replace(".000Z", "Z").replace("Z", "+00:00")
                    utc_date = datetime.fromisoformat(_t).strftime("%Y-%m-%d")
                except Exception:
                    utc_date = d[:4] + "-" + d[4:6] + "-" + d[6:]  # fallback to query date

                all_tasks.append({
                    "mid":         mid,
                    "lid":         lid,
                    "date":        utc_date,   # UTC 开球日期（统一标准）
                    "match_name":  match_name,
                    "league_name": league_name,
                })
                log.info(f"  ✨ 待同步: [{league_name}] {match_name}")

        time.sleep(0.5)

    log.info(f"\n🎯 增量采集目标: {len(all_tasks)} 场")

    # 4. 逐场深度采集并写入 DB
    success = 0
    for i, task in enumerate(all_tasks, 1):
        log.info(f"\n[{i}/{len(all_tasks)}] 🚀 同步: [{task['league_name']}] {task['match_name']} (ID={task['mid']})")
        ok = sync_match(client, task["mid"], task["lid"], task["date"])
        if ok:
            success += 1
            log.info(f"  ✅ 入库成功")
        else:
            log.warning(f"  ⚠️ 入库失败，跳过")

        # 场间随机间隔（住宅代理已有保护，但避免太快被识别）
        if i < len(all_tasks):
            sleep = random.uniform(2.0, 4.0)
            time.sleep(sleep)

    log.info(f"\n{'='*60}")
    log.info(f"🏁 同步完成: {success}/{len(all_tasks)} 场成功")

    # ── Server酱通知 ───────────────────────────────────────────────────
    try:
        _notify_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
        sys.path.insert(0, _notify_path)
        from notify_utils import notify
        if all_tasks:
            names = [f"{t['match_name']}" for t in all_tasks[:5]]
            body = "\n".join([f"{'✅' if i < success else '❌'} {n}" for i, n in enumerate(names)])
            if len(all_tasks) > 5:
                body += f"\n…共 {len(all_tasks)} 场"
            notify(title=f"喵弟入库 · {success}/{len(all_tasks)}场成功", msg=body)
        # 无需同步时静默，不发通知
    except Exception as _e:
        log.warning(f"Server酱通知失败: {_e}")


if __name__ == "__main__":
    main()
