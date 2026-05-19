#!/usr/bin/env python3
"""
migrate_worldcup_step3.py — worldcup.db Step 3 deep + odds migration.

Adds the wc_odds table and indexes. Existing deep tables are preserved.
Idempotent and safe to rerun.
"""

import os
import sqlite3
import sys


_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
DB_PATH = os.environ.get(
    "WORLDCUP_DB_PATH",
    os.path.join(_BACKEND_DIR, "worldcup.db"),
)


DDL_WC_ODDS = """
CREATE TABLE IF NOT EXISTS wc_odds (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    sportmonks_id           INTEGER,
    raw_json                TEXT    NOT NULL,
    data_hash               TEXT    NOT NULL,
    synced_at               TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sync_source             TEXT    NOT NULL,
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
    stopped                 BOOLEAN,
    winning                 BOOLEAN,
    latest_bookmaker_update TIMESTAMP,
    participants            TEXT,
    sort_order              INTEGER
)
"""


INDEXES = [
    ("idx_wc_odds_fixture", "wc_odds", "fixture_sportmonks_id"),
    ("idx_wc_odds_sportmonks_id", "wc_odds", "sportmonks_id"),
    ("idx_wc_odds_market_bookmaker", "wc_odds", "market_id, bookmaker_id"),
]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def main() -> int:
    if not os.path.exists(DB_PATH):
        print(f"❌ worldcup.db 不存在: {DB_PATH}")
        return 1

    print(f"\n{'='*60}")
    print("  worldcup.db Schema 迁移 (Step 3)")
    print(f"  DB 路径: {DB_PATH}")
    print(f"{'='*60}")

    conn = sqlite3.connect(DB_PATH)
    try:
        before_exists = table_exists(conn, "wc_odds")
        conn.execute(DDL_WC_ODDS)
        conn.commit()
        print("\n[ 新增表 ]")
        print(f"  {'ℹ️  已存在（跳过）' if before_exists else '✅ 已创建'}  wc_odds")

        print("\n[ 新增索引 ]")
        for idx_name, table, cols in INDEXES:
            existed = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
                (idx_name,),
            ).fetchone()
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS [{idx_name}] ON [{table}]({cols})"
            )
            print(f"  {'ℹ️  已存在（跳过）' if existed else '✅ 已创建'}  {idx_name}")
        conn.commit()
    finally:
        conn.close()

    print(f"\n{'='*60}")
    print("  完成！")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
