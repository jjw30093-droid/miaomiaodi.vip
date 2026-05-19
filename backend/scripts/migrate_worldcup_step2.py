#!/usr/bin/env python3
"""
migrate_worldcup_step2.py — worldcup.db Schema 微调（Step 2 前置）

执行以下幂等 ALTER TABLE / CREATE INDEX：
  - wc_teams:     ADD is_placeholder, image_path
  - wc_fixtures:  ADD match_label, state_short_name
  - wc_standings: ADD position, points, played, win, draw, lose,
                  goals_for, goals_against, goal_difference, participant_sportmonks_id
  - INDEX: idx_wc_standings_participant, idx_wc_teams_placeholder

幂等：已存在的列 / 索引跳过，不报错，可重复执行。

用法：
  cd /home/ubuntu/app/backend
  venv/bin/python scripts/migrate_worldcup_step2.py
"""

import os
import sqlite3
import sys

# --------------------------------------------------------------------------- #
# DB 路径（与 init_worldcup_db.py 保持一致）
# --------------------------------------------------------------------------- #
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
DB_PATH = os.environ.get(
    "WORLDCUP_DB_PATH",
    os.path.join(_BACKEND_DIR, "worldcup.db"),
)


# --------------------------------------------------------------------------- #
# 迁移定义
# --------------------------------------------------------------------------- #

# 格式：(table_name, column_name, column_definition)
NEW_COLUMNS = [
    # wc_teams 新增字段
    ("wc_teams",     "is_placeholder",          "BOOLEAN NOT NULL DEFAULT 0"),
    ("wc_teams",     "image_path",               "TEXT"),

    # wc_fixtures 新增字段
    ("wc_fixtures",  "match_label",              "TEXT"),      # e.g. "Match 88"
    ("wc_fixtures",  "state_short_name",         "TEXT"),      # e.g. "NS", "FT", "HT"

    # wc_standings 冗余业务字段（方案 A：raw_json + 冗余常用字段，避免每次解析 JSON）
    ("wc_standings", "position",                 "INTEGER"),
    ("wc_standings", "points",                   "INTEGER"),
    ("wc_standings", "played",                   "INTEGER"),
    ("wc_standings", "win",                      "INTEGER"),
    ("wc_standings", "draw",                     "INTEGER"),
    ("wc_standings", "lose",                     "INTEGER"),
    ("wc_standings", "goals_for",                "INTEGER"),
    ("wc_standings", "goals_against",            "INTEGER"),
    ("wc_standings", "goal_difference",          "INTEGER"),
    ("wc_standings", "participant_sportmonks_id","INTEGER"),
]

# 格式：(index_name, table_name, columns, is_unique)
NEW_INDEXES = [
    ("idx_wc_standings_participant", "wc_standings", "participant_sportmonks_id", False),
    ("idx_wc_teams_placeholder",     "wc_teams",     "is_placeholder",            False),
]


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #

def get_existing_columns(conn: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def get_existing_indexes(conn: sqlite3.Connection) -> set:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }


def run_migration(conn: sqlite3.Connection) -> dict:
    """执行所有迁移，返回统计 {columns_added, columns_skipped, indexes_added, indexes_skipped}"""
    cur = conn.cursor()
    stats = dict(columns_added=0, columns_skipped=0, indexes_added=0, indexes_skipped=0)

    # ── 新增列 ─────────────────────────────────────────────────────────────── #
    print("\n[ 新增列 ]")
    for table, col, definition in NEW_COLUMNS:
        existing_cols = get_existing_columns(conn, table)
        if col in existing_cols:
            print(f"  ℹ️  已存在（跳过）  {table}.{col}")
            stats["columns_skipped"] += 1
        else:
            cur.execute(f"ALTER TABLE [{table}] ADD COLUMN [{col}] {definition}")
            print(f"  ✅ 已添加          {table}.{col}  {definition}")
            stats["columns_added"] += 1

    conn.commit()

    # ── 新增索引 ───────────────────────────────────────────────────────────── #
    print("\n[ 新增索引 ]")
    for idx_name, table, cols, is_unique in NEW_INDEXES:
        existing_idxs = get_existing_indexes(conn)
        if idx_name in existing_idxs:
            print(f"  ℹ️  已存在（跳过）  {idx_name}")
            stats["indexes_skipped"] += 1
        else:
            unique_kw = "UNIQUE" if is_unique else ""
            cur.execute(
                f"CREATE {unique_kw} INDEX IF NOT EXISTS [{idx_name}] "
                f"ON [{table}]({cols})"
            )
            print(f"  ✅ 已创建          {idx_name} ON {table}({cols})")
            stats["indexes_added"] += 1

    conn.commit()
    return stats


# --------------------------------------------------------------------------- #
# 主程序
# --------------------------------------------------------------------------- #

def main() -> int:
    if not os.path.exists(DB_PATH):
        print(f"❌ worldcup.db 不存在: {DB_PATH}")
        print("   请先运行 scripts/init_worldcup_db.py")
        return 1

    print(f"\n{'='*60}")
    print(f"  worldcup.db Schema 迁移 (Step 2)")
    print(f"  DB 路径: {DB_PATH}")
    print(f"{'='*60}")

    conn = sqlite3.connect(DB_PATH)
    try:
        stats = run_migration(conn)
    finally:
        conn.close()

    print(f"\n{'='*60}")
    print(f"  完成！")
    print(f"  列：{stats['columns_added']} 新增，{stats['columns_skipped']} 已存在")
    print(f"  索引：{stats['indexes_added']} 新增，{stats['indexes_skipped']} 已存在")
    print(f"{'='*60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
