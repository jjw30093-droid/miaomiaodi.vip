"""
migrate_wc_tables.py
====================
在 worldcup.db 里创建 WC 研报系统所需的三张新表：
  - wc_reports          : 研报内容（对标 cc 的 report_store，但完全独立）
  - wc_prediction_audit : WC 预测审计（物理隔离 ROI，不进联赛 prediction_audit）
  - wc_odds_snapshot    : T-30 闭盘快照（补 wc_odds 缺失的快照逻辑）

用法：
  python backend/scripts/migrate_wc_tables.py
  python backend/scripts/migrate_wc_tables.py --dry-run   # 仅打印 SQL，不执行

幂等：每张 CREATE TABLE 都用 IF NOT EXISTS，可多次执行。
"""

import os
import sys
import argparse
import sqlite3
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WC_DB_PATH = os.environ.get("WC_DB_PATH", os.path.join(PROJECT_ROOT, "worldcup.db"))

# ──────────────────────────────────────────────────────────────────────────────
# DDL
# ──────────────────────────────────────────────────────────────────────────────

DDL_WC_REPORTS = """
CREATE TABLE IF NOT EXISTS wc_reports (
    match_id                TEXT PRIMARY KEY,          -- 'wc_{fixture_id}'
    fixture_sportmonks_id   INTEGER NOT NULL,
    report_markdown         TEXT,                      -- 正文（serving 端按 is_gated 物理截断）
    payload_json            TEXT,                      -- 完整复合 payload JSON（market-implied + 每分钟序列 + 球队表 + inference + json_meta）
    inference               TEXT,                      -- '【HIGH】主胜 @2.10 62.3% (62.3%/21.5%/16.2%)'
    pipeline_status         TEXT    NOT NULL DEFAULT 'DRAFT',  -- 'DRAFT'|'REPORT_READY'|'FINAL_REPORT_READY'
    home_team               TEXT,
    away_team               TEXT,
    match_time              TEXT,                      -- ISO UTC '2026-06-11T18:00:00Z'
    league                  TEXT    NOT NULL DEFAULT 'World Cup',
    is_free                 INTEGER NOT NULL DEFAULT 0,-- 1 = 免费场次
    home_prob               REAL,
    draw_prob               REAL,
    away_prob               REAL,
    beginner_summary        TEXT,                      -- 新手大白话
    key_risk                TEXT,
    key_variables           TEXT,                      -- JSON array
    chart_insights          TEXT,                      -- JSON dict
    post_match_review       TEXT,                      -- 赛后复盘 Markdown
    match_status            TEXT    NOT NULL DEFAULT 'upcoming',  -- 'upcoming'|'live'|'finished'
    preview_content         TEXT,                      -- 公开预览摘要
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

DDL_WC_PREDICTION_AUDIT = """
CREATE TABLE IF NOT EXISTS wc_prediction_audit (
    match_id                TEXT PRIMARY KEY,          -- 'wc_{fixture_id}'
    match_date              TEXT,                      -- 'YYYY-MM-DD'
    home                    TEXT,
    away                    TEXT,
    picked_market           TEXT,                      -- 'wdl'（WC 只出 WDL 推荐）
    picked_direction        TEXT,                      -- 'home_win'|'draw'|'away_win'
    picked_odds             REAL,
    picked_confidence       TEXT,                      -- 'HIGH'|'MID'|'LOW'|'SKIP'
    picked_correct          INTEGER,                   -- 1赢/0输/-1走水/NULL未结算
    actual_home_score       INTEGER,
    actual_away_score       INTEGER,
    actual_wdl              TEXT,                      -- 'home_win'|'draw'|'away_win'（FT）
    audit_time              TIMESTAMP
)
"""

DDL_WC_ODDS_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS wc_odds_snapshot (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    fixture_sportmonks_id   INTEGER NOT NULL,
    market_id               INTEGER,
    bookmaker_id            INTEGER,
    label                   TEXT,
    value                   TEXT,                      -- 赔率（十进制字符串）
    total                   TEXT,                      -- OU 线值，如 '2.5' 或 '2.0,2.5'
    handicap                TEXT,                      -- AH 让球线
    probability             TEXT,
    period                  TEXT    NOT NULL DEFAULT 'closing',
    snapshot_ts             TEXT    NOT NULL,          -- T-30 墙钟时间戳（closing 代理）
    inserted_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

DDL_WC_ODDS_SNAPSHOT_IDX = """
CREATE INDEX IF NOT EXISTS idx_wcsnap_fixture ON wc_odds_snapshot(fixture_sportmonks_id)
"""

DDL_WC_ODDS = """
CREATE TABLE IF NOT EXISTS wc_odds (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    sportmonks_id           INTEGER,
    raw_json                TEXT,
    data_hash               TEXT,
    synced_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_source             TEXT,
    api_version             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fixture_sportmonks_id   INTEGER NOT NULL,
    market_id               INTEGER,
    bookmaker_id            INTEGER,
    label                   TEXT,
    original_label          TEXT,
    name                    TEXT,
    market_description      TEXT,
    value                   TEXT,
    probability             TEXT,
    dp3                     TEXT,
    fractional              TEXT,
    american                TEXT,
    total                   TEXT,
    handicap                TEXT,
    stopped                 INTEGER,
    winning                 INTEGER,
    latest_bookmaker_update TEXT,
    participants            TEXT,
    sort_order              INTEGER
)
"""

DDLS = [
    ("wc_reports", DDL_WC_REPORTS),
    ("wc_prediction_audit", DDL_WC_PREDICTION_AUDIT),
    ("wc_odds_snapshot", DDL_WC_ODDS_SNAPSHOT),
    ("wc_odds (if missing)", DDL_WC_ODDS),
]

INDEXES = [
    DDL_WC_ODDS_SNAPSHOT_IDX,
    "CREATE INDEX IF NOT EXISTS idx_wc_odds_fixture ON wc_odds(fixture_sportmonks_id)",
    "CREATE INDEX IF NOT EXISTS idx_wc_reports_fixture ON wc_reports(fixture_sportmonks_id)",
    "CREATE INDEX IF NOT EXISTS idx_wc_reports_status ON wc_reports(pipeline_status)",
]


def run_migration(db_path: str, dry_run: bool = False):
    if not os.path.exists(db_path) and not dry_run:
        log.warning(f"worldcup.db not found at {db_path} — migration will create an empty DB.")

    log.info(f"Migration target: {db_path} (dry_run={dry_run})")

    if dry_run:
        for name, ddl in DDLS:
            log.info(f"[DRY-RUN] Would create table {name}:\n{ddl.strip()}")
        for idx_sql in INDEXES:
            log.info(f"[DRY-RUN] Index: {idx_sql.strip()}")
        return

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        for name, ddl in DDLS:
            log.info(f"Creating table {name}...")
            conn.executescript(ddl)

        for idx_sql in INDEXES:
            log.info(f"Creating index...")
            conn.execute(idx_sql)

        conn.commit()
        log.info("✅ Migration complete.")
    except Exception as e:
        conn.rollback()
        log.error(f"Migration failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate worldcup.db WC report tables")
    parser.add_argument("--db", default=WC_DB_PATH, help="Path to worldcup.db")
    parser.add_argument("--dry-run", action="store_true", help="Print DDL only, don't execute")
    args = parser.parse_args()

    run_migration(args.db, args.dry_run)
