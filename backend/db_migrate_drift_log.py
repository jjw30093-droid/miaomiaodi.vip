#!/usr/bin/env python3
"""
db_migrate_drift_log.py — 幂等创建 model_drift_log 表

用法：
  cd /home/ubuntu/app/backend
  venv/bin/python db_migrate_drift_log.py

Phase 2 (P1)：将 drift 告警从 ingest_failure_log 拆分到独立表。
"""

import os
import sqlite3
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BACKEND_DIR, "football_uk.db"))


def migrate(db_path: str = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 检查表是否已存在
    exists = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='model_drift_log'"
    ).fetchone()

    if exists:
        print(f"[db_migrate_drift_log] model_drift_log 已存在，跳过 CREATE。")
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS model_drift_log (
              id                 INTEGER PRIMARY KEY AUTOINCREMENT,
              triggered_at       TEXT    DEFAULT CURRENT_TIMESTAMP,
              model_version      TEXT,
              wdl_acc            REAL,
              ou_acc             REAL,
              ah_acc             REAL,
              brier_wdl          REAL,
              window_size        INTEGER,
              triggered_metrics  TEXT,
              recalibrate_pid    INTEGER,
              recalibrate_status TEXT,
              notes              TEXT
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_drift_triggered_at
            ON model_drift_log(triggered_at);
        """)
        conn.commit()
        print(f"[db_migrate_drift_log] ✅ model_drift_log 创建成功（{db_path}）")

    # 验证
    info = cur.execute("PRAGMA table_info(model_drift_log)").fetchall()
    cols = [row[1] for row in info]
    print(f"[db_migrate_drift_log] 列：{cols}")

    conn.close()


if __name__ == "__main__":
    migrate()
    print("[db_migrate_drift_log] 完成。")
