#!/usr/bin/env python3
"""
迁移 007 — 为 prediction_audit 添加 market_* / edge_* / kelly_fraction 列。
幂等：列已存在时自动跳过。
"""
import os, sys, sqlite3

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(os.path.join(__file__, "../.."))))
DB_PATH      = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))

NEW_COLS = [
    ("market_home",    "REAL"),
    ("market_draw",    "REAL"),
    ("market_away",    "REAL"),
    ("edge_home",      "REAL"),
    ("edge_draw",      "REAL"),
    ("edge_away",      "REAL"),
    ("edge_label",     "TEXT"),   # 'value_home'|'value_draw'|'value_away'|'no_edge'
    ("kelly_fraction", "REAL"),
]


def run(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(prediction_audit)").fetchall()}
    added = []
    for col, dtype in NEW_COLS:
        if col not in existing:
            conn.execute(f"ALTER TABLE prediction_audit ADD COLUMN {col} {dtype}")
            added.append(col)
    conn.commit()
    conn.close()
    if added:
        print(f"[007] 新增列: {added}")
    else:
        print("[007] 所有列已存在，跳过。")


if __name__ == "__main__":
    run()
    print(f"[007] 迁移完成 → {DB_PATH}")
