#!/usr/bin/env python3
"""
World Cup 数据缓存层 — worldcup.db 初始化脚本 (Step 1)

用途：
  创建 worldcup.db 独立 SQLite 文件，包含 12 张 wc_* 表和全部索引。
  与 football_uk.db 物理隔离，wc_* 表与现有业务表零外键关联。

用法：
  python scripts/init_worldcup_db.py             # 初始化（表已存在则跳过）
  python scripts/init_worldcup_db.py --drop-existing  # 先删所有 wc_* 表再重建

DB 路径：/home/ubuntu/app/backend/worldcup.db

注意：
  - 不写任何同步逻辑，不调 Sportmonks API
  - wc_sync_log 是内部审计表，sportmonks_id / data_hash 字段可为 NULL
  - 脚本幂等，可重复执行
"""

import argparse
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# 路径约定（与 football_uk.db 同目录）
# --------------------------------------------------------------------------- #
BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("WORLDCUP_DB_PATH", str(BACKEND_DIR / "worldcup.db"))

# --------------------------------------------------------------------------- #
# DDL：维度表 (5 张)
# --------------------------------------------------------------------------- #

DDL_WC_SEASONS = """
CREATE TABLE IF NOT EXISTS wc_seasons (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 通用字段
    sportmonks_id           INTEGER NOT NULL,
    raw_json                TEXT    NOT NULL,
    data_hash               TEXT    NOT NULL,
    synced_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_source             TEXT    NOT NULL,           -- 'manual'/'cron'/'backfill'
    api_version             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 业务字段
    year                    INTEGER NOT NULL,           -- e.g. 2026
    name                    TEXT    NOT NULL,           -- e.g. 'FIFA World Cup 2026'
    host_country            TEXT,                      -- e.g. 'USA/Canada/Mexico'
    total_teams             INTEGER,                   -- e.g. 48
    winner_team_sportmonks_id INTEGER                  -- NULL 直到赛事结束
)
"""

DDL_WC_STAGES = """
CREATE TABLE IF NOT EXISTS wc_stages (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 通用字段
    sportmonks_id           INTEGER NOT NULL,
    raw_json                TEXT    NOT NULL,
    data_hash               TEXT    NOT NULL,
    synced_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_source             TEXT    NOT NULL,
    api_version             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 业务字段
    season_sportmonks_id    INTEGER NOT NULL,
    name                    TEXT    NOT NULL,           -- e.g. 'Group Stage', 'Round of 16'
    type                    TEXT,                      -- 'group' / 'knockout'
    sort_order              INTEGER                    -- 排序用
)
"""

DDL_WC_GROUPS = """
CREATE TABLE IF NOT EXISTS wc_groups (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 通用字段
    sportmonks_id           INTEGER NOT NULL,
    raw_json                TEXT    NOT NULL,
    data_hash               TEXT    NOT NULL,
    synced_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_source             TEXT    NOT NULL,
    api_version             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 业务字段
    season_sportmonks_id    INTEGER NOT NULL,
    stage_sportmonks_id     INTEGER NOT NULL,
    name                    TEXT    NOT NULL            -- e.g. 'Group A'
)
"""

DDL_WC_TEAMS = """
CREATE TABLE IF NOT EXISTS wc_teams (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 通用字段
    sportmonks_id           INTEGER NOT NULL,
    raw_json                TEXT    NOT NULL,
    data_hash               TEXT    NOT NULL,
    synced_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_source             TEXT    NOT NULL,
    api_version             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 业务字段（跨届去重，团队信息不含赛季上下文）
    name                    TEXT    NOT NULL,
    short_name              TEXT,
    country_id              INTEGER,
    logo_path               TEXT,
    founded                 INTEGER
)
"""

DDL_WC_VENUES = """
CREATE TABLE IF NOT EXISTS wc_venues (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 通用字段
    sportmonks_id           INTEGER NOT NULL,
    raw_json                TEXT    NOT NULL,
    data_hash               TEXT    NOT NULL,
    synced_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_source             TEXT    NOT NULL,
    api_version             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 业务字段
    name                    TEXT    NOT NULL,
    city                    TEXT,
    country                 TEXT,
    capacity                INTEGER,
    latitude                REAL,
    longitude               REAL
)
"""

# --------------------------------------------------------------------------- #
# DDL：事实表 (6 张)
# --------------------------------------------------------------------------- #

DDL_WC_FIXTURES = """
CREATE TABLE IF NOT EXISTS wc_fixtures (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 通用字段
    sportmonks_id           INTEGER NOT NULL,
    raw_json                TEXT    NOT NULL,
    data_hash               TEXT    NOT NULL,
    synced_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_source             TEXT    NOT NULL,
    api_version             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 关联维度（外键逻辑不强制，走 sportmonks_id 软关联）
    season_sportmonks_id    INTEGER NOT NULL,
    stage_sportmonks_id     INTEGER,
    group_sportmonks_id     INTEGER,                   -- NULL = 淘汰赛阶段
    venue_sportmonks_id     INTEGER,
    -- 队伍（2026 小组赛前允许占位）
    home_team_sportmonks_id INTEGER,                   -- NULL = 占位赛程
    away_team_sportmonks_id INTEGER,
    placeholder_home        TEXT,                      -- e.g. 'Winner Group A'
    placeholder_away        TEXT,                      -- e.g. 'Runner-up Group B'
    is_placeholder          BOOLEAN NOT NULL DEFAULT 0,-- 1 = 对阵未确定
    -- 比赛信息
    starting_at             TIMESTAMP,                 -- UTC 开球时间
    status                  TEXT,                      -- Sportmonks status string
    round_id                INTEGER,
    leg_num                 INTEGER DEFAULT 1,
    -- 比分（冗余存，wc_scores 存细分）
    home_score              INTEGER,
    away_score              INTEGER,
    -- 数据完整性标记
    has_events              BOOLEAN NOT NULL DEFAULT 0,
    has_lineups             BOOLEAN NOT NULL DEFAULT 0,
    has_statistics          BOOLEAN NOT NULL DEFAULT 0,
    -- 赔率元数据
    odds_markets_count      INTEGER DEFAULT 0,
    odds_last_checked_at    TIMESTAMP,
    -- 历史赛事标记（2006/2010/2014 标 1，永不再触发同步）
    is_historical           BOOLEAN NOT NULL DEFAULT 0,
    -- 裁判
    referee_sportmonks_id   INTEGER
)
"""

DDL_WC_SCORES = """
CREATE TABLE IF NOT EXISTS wc_scores (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 通用字段
    sportmonks_id           INTEGER,                   -- Sportmonks score entity id（部分类型无独立 id）
    raw_json                TEXT    NOT NULL,
    data_hash               TEXT    NOT NULL,
    synced_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_source             TEXT    NOT NULL,
    api_version             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 业务字段
    fixture_sportmonks_id   INTEGER NOT NULL,
    type_id                 INTEGER,
    description             TEXT,                      -- 'CURRENT'/'FT'/'HT'/'ET'/'PEN'
    score_home              INTEGER,
    score_away              INTEGER
)
"""

DDL_WC_EVENTS = """
CREATE TABLE IF NOT EXISTS wc_events (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 通用字段
    sportmonks_id           INTEGER,
    raw_json                TEXT    NOT NULL,
    data_hash               TEXT    NOT NULL,
    synced_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_source             TEXT    NOT NULL,
    api_version             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 业务字段
    fixture_sportmonks_id   INTEGER NOT NULL,
    player_sportmonks_id    INTEGER,
    player_name             TEXT,
    team_sportmonks_id      INTEGER,
    type                    TEXT,                      -- 'goal'/'yellowcard'/'redcard'/'substitution'/'var'
    minute                  INTEGER,
    extra_minute            INTEGER,
    info                    TEXT                       -- 附加描述
)
"""

DDL_WC_STATISTICS = """
CREATE TABLE IF NOT EXISTS wc_statistics (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 通用字段
    sportmonks_id           INTEGER,
    raw_json                TEXT    NOT NULL,
    data_hash               TEXT    NOT NULL,
    synced_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_source             TEXT    NOT NULL,
    api_version             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 业务字段
    fixture_sportmonks_id   INTEGER NOT NULL,
    team_sportmonks_id      INTEGER,                   -- NULL = 球员统计
    player_sportmonks_id    INTEGER,                   -- NULL = 球队统计
    type                    TEXT    NOT NULL,           -- e.g. 'shots_on_target'/'possession'
    value                   TEXT    NOT NULL            -- 存 string，调用方自行解析数值
)
"""

DDL_WC_LINEUPS = """
CREATE TABLE IF NOT EXISTS wc_lineups (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 通用字段
    sportmonks_id           INTEGER,
    raw_json                TEXT    NOT NULL,
    data_hash               TEXT    NOT NULL,
    synced_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_source             TEXT    NOT NULL,
    api_version             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 业务字段
    fixture_sportmonks_id   INTEGER NOT NULL,
    team_sportmonks_id      INTEGER NOT NULL,
    player_sportmonks_id    INTEGER NOT NULL,
    player_name             TEXT,
    jersey_number           INTEGER,
    position                TEXT,                      -- 'goalkeeper'/'defender'/'midfielder'/'attacker'
    is_starter              BOOLEAN NOT NULL DEFAULT 1,-- 0 = 替补
    formation_position      TEXT                       -- e.g. '4-3-3' 中的位置标识
)
"""

DDL_WC_STANDINGS = """
CREATE TABLE IF NOT EXISTS wc_standings (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 通用字段
    sportmonks_id           INTEGER,
    raw_json                TEXT    NOT NULL,
    data_hash               TEXT    NOT NULL,
    synced_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_source             TEXT    NOT NULL,
    api_version             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 业务字段
    season_sportmonks_id    INTEGER NOT NULL,
    stage_sportmonks_id     INTEGER,
    group_sportmonks_id     INTEGER,
    team_sportmonks_id      INTEGER NOT NULL,
    position                INTEGER,
    played                  INTEGER DEFAULT 0,
    won                     INTEGER DEFAULT 0,
    drawn                   INTEGER DEFAULT 0,
    lost                    INTEGER DEFAULT 0,
    goals_for               INTEGER DEFAULT 0,
    goals_against           INTEGER DEFAULT 0,
    points                  INTEGER DEFAULT 0,
    form                    TEXT                       -- e.g. 'WWDLL'
)
"""

# --------------------------------------------------------------------------- #
# DDL：元数据表 (1 张)
# --------------------------------------------------------------------------- #

DDL_WC_SYNC_LOG = """
CREATE TABLE IF NOT EXISTS wc_sync_log (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 通用字段（内部审计表：sportmonks_id / data_hash 无实体意义，允许 NULL）
    sportmonks_id           INTEGER,
    raw_json                TEXT,                      -- 完整 API 响应，调试用，可 NULL
    data_hash               TEXT,
    synced_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_source             TEXT    NOT NULL,
    api_version             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- 同步审计字段
    endpoint                TEXT    NOT NULL,          -- Sportmonks API endpoint
    http_status             INTEGER,
    rows_inserted           INTEGER DEFAULT 0,
    rows_updated            INTEGER DEFAULT 0,
    rows_unchanged          INTEGER DEFAULT 0,
    error_msg               TEXT,
    retry_count             INTEGER DEFAULT 0,
    started_at              TIMESTAMP NOT NULL,
    finished_at             TIMESTAMP,
    duration_ms             INTEGER,
    season_sportmonks_id    INTEGER,
    layer                   TEXT                       -- 'basic'/'deep'/'odds'
)
"""

# --------------------------------------------------------------------------- #
# 表清单（顺序 = 创建顺序）
# --------------------------------------------------------------------------- #

DIMENSION_TABLES = [
    ("wc_seasons",   DDL_WC_SEASONS),
    ("wc_stages",    DDL_WC_STAGES),
    ("wc_groups",    DDL_WC_GROUPS),
    ("wc_teams",     DDL_WC_TEAMS),
    ("wc_venues",    DDL_WC_VENUES),
]

FACT_TABLES = [
    ("wc_fixtures",   DDL_WC_FIXTURES),
    ("wc_scores",     DDL_WC_SCORES),
    ("wc_events",     DDL_WC_EVENTS),
    ("wc_statistics", DDL_WC_STATISTICS),
    ("wc_lineups",    DDL_WC_LINEUPS),
    ("wc_standings",  DDL_WC_STANDINGS),
]

META_TABLES = [
    ("wc_sync_log",   DDL_WC_SYNC_LOG),
]

ALL_TABLES = DIMENSION_TABLES + FACT_TABLES + META_TABLES

# --------------------------------------------------------------------------- #
# 索引 DDL
# --------------------------------------------------------------------------- #

# 格式：(index_name, table_name, columns, is_unique)
INDEXES = [
    # ── 维度表：sportmonks_id UNIQUE ─────────────────────────────────────── #
    ("idx_wc_seasons_sportmonks_id",    "wc_seasons",    "sportmonks_id",                                  True),
    ("idx_wc_stages_sportmonks_id",     "wc_stages",     "sportmonks_id",                                  True),
    ("idx_wc_groups_sportmonks_id",     "wc_groups",     "sportmonks_id",                                  True),
    ("idx_wc_teams_sportmonks_id",      "wc_teams",      "sportmonks_id",                                  True),
    ("idx_wc_venues_sportmonks_id",     "wc_venues",     "sportmonks_id",                                  True),

    # ── 事实表：sportmonks_id 普通 INDEX ──────────────────────────────────── #
    ("idx_wc_fixtures_sportmonks_id",   "wc_fixtures",   "sportmonks_id",                                  False),
    ("idx_wc_scores_sportmonks_id",     "wc_scores",     "sportmonks_id",                                  False),
    ("idx_wc_events_sportmonks_id",     "wc_events",     "sportmonks_id",                                  False),
    ("idx_wc_statistics_sportmonks_id", "wc_statistics", "sportmonks_id",                                  False),
    ("idx_wc_lineups_sportmonks_id",    "wc_lineups",    "sportmonks_id",                                  False),

    # ── wc_fixtures 业务组合 ──────────────────────────────────────────────── #
    ("idx_wc_fixtures_season_starting", "wc_fixtures",   "season_sportmonks_id, starting_at",              False),
    ("idx_wc_fixtures_status",          "wc_fixtures",   "status",                                         False),

    # ── 事实子表：按 fixture 查询 ─────────────────────────────────────────── #
    ("idx_wc_scores_fixture",           "wc_scores",     "fixture_sportmonks_id",                          False),
    ("idx_wc_events_fixture",           "wc_events",     "fixture_sportmonks_id",                          False),
    ("idx_wc_statistics_fixture",       "wc_statistics", "fixture_sportmonks_id",                          False),
    ("idx_wc_lineups_fixture",          "wc_lineups",    "fixture_sportmonks_id",                          False),

    # ── wc_standings 小组排名组合 ─────────────────────────────────────────── #
    ("idx_wc_standings_season_group",   "wc_standings",  "season_sportmonks_id, group_sportmonks_id",      False),

    # ── wc_sync_log 按时间倒序查 ─────────────────────────────────────────── #
    ("idx_wc_sync_log_started_at",      "wc_sync_log",   "started_at DESC",                                False),
    ("idx_wc_sync_log_endpoint",        "wc_sync_log",   "endpoint",                                       False),
]


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #

def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")    # wc_* 表用软外键，无需强制
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def drop_all_wc_tables(conn: sqlite3.Connection) -> None:
    """删除所有 wc_* 表和索引（用于 --drop-existing）。"""
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'wc_%'"
    ).fetchall()]
    indexes = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_wc_%'"
    ).fetchall()]
    for idx in indexes:
        cur.execute(f"DROP INDEX IF EXISTS [{idx}]")
    for tbl in tables:
        cur.execute(f"DROP TABLE IF EXISTS [{tbl}]")
    conn.commit()
    print(f"  已删除 {len(tables)} 张表，{len(indexes)} 个索引。")


def create_tables(conn: sqlite3.Connection) -> dict:
    """创建所有表，返回 {table_name: 'created'/'existed'} 字典。"""
    cur = conn.cursor()
    result = {}
    for name, ddl in ALL_TABLES:
        existed = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        cur.executescript(ddl)
        result[name] = "existed" if existed else "created"
    conn.commit()
    return result


def create_indexes(conn: sqlite3.Connection) -> dict:
    """创建所有索引，返回 {index_name: 'created'/'existed'} 字典。"""
    cur = conn.cursor()
    result = {}
    for idx_name, tbl, cols, is_unique in INDEXES:
        existed = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (idx_name,)
        ).fetchone()
        if not existed:
            unique_kw = "UNIQUE" if is_unique else ""
            cur.execute(
                f"CREATE {unique_kw} INDEX IF NOT EXISTS [{idx_name}] "
                f"ON [{tbl}]({cols})"
            )
            result[idx_name] = "created"
        else:
            result[idx_name] = "existed"
    conn.commit()
    return result


# --------------------------------------------------------------------------- #
# 主程序
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(
        description="初始化 worldcup.db — 世界杯数据缓存层 (Step 1)"
    )
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="先删除所有 wc_* 表和索引再重建（不影响非 wc_* 表）",
    )
    parser.add_argument(
        "--db-path",
        default=DB_PATH,
        help=f"DB 路径（默认：{DB_PATH}）",
    )
    args = parser.parse_args()

    db_path = args.db_path
    print(f"\n{'='*60}")
    print(f"  worldcup.db 初始化脚本")
    print(f"  DB 路径: {db_path}")
    print(f"{'='*60}\n")

    conn = get_conn(db_path)

    if args.drop_existing:
        print("[--drop-existing] 删除已有 wc_* 表和索引...")
        drop_all_wc_tables(conn)

    # ── 创建表 ─────────────────────────────────────────────────────────────── #
    print("[ 创建表 ]")
    table_results = create_tables(conn)
    created_count = sum(1 for v in table_results.values() if v == "created")
    skipped_count = sum(1 for v in table_results.values() if v == "existed")

    for name, status in table_results.items():
        marker = "✅ 已创建" if status == "created" else "ℹ️  已存在（跳过）"
        print(f"  {marker}  {name}")

    # ── 创建索引 ───────────────────────────────────────────────────────────── #
    print(f"\n[ 创建索引 ]")
    idx_results = create_indexes(conn)
    idx_created = sum(1 for v in idx_results.values() if v == "created")
    idx_skipped = sum(1 for v in idx_results.values() if v == "existed")

    for idx_name, status in idx_results.items():
        marker = "✅ 已创建" if status == "created" else "ℹ️  已存在（跳过）"
        print(f"  {marker}  {idx_name}")

    # ── 汇总 ───────────────────────────────────────────────────────────────── #
    db_size = os.path.getsize(db_path)
    print(f"\n{'='*60}")
    print(f"  完成！")
    print(f"  表：{created_count} 新建，{skipped_count} 已存在")
    print(f"  索引：{idx_created} 新建，{idx_skipped} 已存在")
    print(f"  DB 大小：{db_size:,} bytes ({db_size / 1024:.1f} KB)")
    print(f"{'='*60}\n")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
