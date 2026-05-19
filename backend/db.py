"""
db.py — 中央 SQLite 连接工厂
==============================
所有后端模块统一通过 get_conn() 获取数据库连接，保证：
  - WAL 模式（写不阻塞读，大幅降低 locked 概率）
  - NORMAL 同步（性能与安全的平衡点）
  - 15 秒忙等超时（短暂写锁等待，而非立即抛 OperationalError）
  - check_same_thread=False（FastAPI 线程池安全）
"""

import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "/home/ubuntu/app/backend/football_uk.db")

_WAL_INITIALIZED = False


def get_conn(db_path: str = None, row_factory=True) -> sqlite3.Connection:
    """
    返回已配置好 WAL + NORMAL + busy_timeout 的 SQLite 连接。

    用法（替换旧的 sqlite3.connect(DB_PATH)）：
        from db import get_conn
        conn = get_conn()
        conn.row_factory = sqlite3.Row   # 如果需要字典式访问（默认已启用）
    """
    path = db_path or DB_PATH
    conn = sqlite3.connect(
        path,
        timeout=15,                  # Python 层：等待锁最多 15 秒再抛异常
        check_same_thread=False,     # FastAPI 多线程环境必须
    )
    if row_factory:
        conn.row_factory = sqlite3.Row

    # SQLite 层配置（每次连接都执行，幂等）
    conn.execute("PRAGMA journal_mode=WAL")   # 写不阻塞读
    conn.execute("PRAGMA synchronous=NORMAL") # 性能/安全平衡
    conn.execute("PRAGMA busy_timeout=15000") # SQLite C 层等待 15s（与 Python timeout 互补）
    conn.execute("PRAGMA cache_size=-8000")   # 8MB 页缓存，减少磁盘 I/O
    conn.execute("PRAGMA temp_store=MEMORY")  # 临时表放内存

    return conn


def init_wal(db_path: str = None):
    """
    在应用启动时调用一次，确保 WAL 模式持久化到数据库文件。
    WAL 是文件级设置，设置一次后所有后续连接（含爬虫进程）自动继承。
    """
    global _WAL_INITIALIZED
    if _WAL_INITIALIZED:
        return
    conn = get_conn(db_path, row_factory=False)
    result = conn.execute("PRAGMA journal_mode=WAL").fetchone()
    conn.close()
    _WAL_INITIALIZED = True
    import logging
    logging.getLogger(__name__).info(f"[db] WAL mode initialized: {result[0]}")
