"""
db_migrate.py — 幂等数据库迁移脚本

每次服务启动时由 api_server.py 调用 run_migrations()。
所有 ALTER TABLE 均用 try/except 包裹，安全重入。
"""

import os
import sqlite3
import logging

log = logging.getLogger(__name__)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(_THIS_DIR, "football_uk.db"))


def run_migrations(db_path: str = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    try:
        _add_is_free_to_report_store(conn)
        _add_vip_days_to_shop_cdk(conn)
        _add_vip_expires_at_to_wechat_users(conn)
        _add_post_match_fields_to_report_store(conn)
        # ── Phase 3: 用户账户体系 ─────────────────────────────────────────────
        _add_user_account_fields(conn)
        _create_user_sessions_table(conn)
        _migrate_wechat_users_to_users(conn)
        conn.commit()
        log.info("[Migrations] ✅ All migrations applied successfully.")
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────
# Migration 1: report_store.is_free
# ─────────────────────────────────────────────────────────────

def _add_is_free_to_report_store(conn: sqlite3.Connection) -> None:
    """给 report_store 添加 is_free 列（0=付费场，1=免费场）。"""
    try:
        conn.execute(
            "ALTER TABLE report_store ADD COLUMN is_free INTEGER NOT NULL DEFAULT 0"
        )
        log.info("[Migrations] Added column: report_store.is_free")
    except sqlite3.OperationalError:
        pass  # 列已存在，幂等跳过

    # 回填：将现有 status='FREE' 行标记为 is_free=1
    conn.execute(
        "UPDATE report_store SET is_free = 1 WHERE status = 'FREE' AND is_free = 0"
    )


# ─────────────────────────────────────────────────────────────
# Migration 2: shop_cdk.vip_days
# ─────────────────────────────────────────────────────────────

def _add_vip_days_to_shop_cdk(conn: sqlite3.Connection) -> None:
    """
    给 shop_cdk 添加 vip_days 列，表示该卡密兑换后延长的 VIP 天数。
      vip_days = 0  → 报告点数卡（旧逻辑，quota 列）
      vip_days = 7  → 周卡
      vip_days = 30 → 月卡

    同时确保 shop_cdk 表存在（老环境可能尚未建表）。
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shop_cdk (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            code       TEXT    UNIQUE NOT NULL,
            quota      INTEGER NOT NULL DEFAULT 0,
            vip_days   INTEGER NOT NULL DEFAULT 0,
            is_used    INTEGER NOT NULL DEFAULT 0,
            used_by    TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME
        )
    """)

    try:
        conn.execute(
            "ALTER TABLE shop_cdk ADD COLUMN vip_days INTEGER NOT NULL DEFAULT 0"
        )
        log.info("[Migrations] Added column: shop_cdk.vip_days")
    except sqlite3.OperationalError:
        pass  # 列已存在


# ─────────────────────────────────────────────────────────────
# Migration 3: wechat_users.vip_expires_at
# ─────────────────────────────────────────────────────────────

def _add_vip_expires_at_to_wechat_users(conn: sqlite3.Connection) -> None:
    """
    给 wechat_users 添加 vip_expires_at 列（ISO-8601 UTC 字符串）。
    NULL 表示无 VIP 或从未购买过。
    """
    # 确保 wechat_users 表存在（首次部署时可能尚未运行 wechat_auth_router.py 的初始化）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wechat_users (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            openid         TEXT UNIQUE NOT NULL,
            is_vip         INTEGER NOT NULL DEFAULT 0,
            vip_expires_at TEXT,
            created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    try:
        conn.execute(
            "ALTER TABLE wechat_users ADD COLUMN vip_expires_at TEXT"
        )
        log.info("[Migrations] Added column: wechat_users.vip_expires_at")
    except sqlite3.OperationalError:
        pass  # 列已存在


# ─────────────────────────────────────────────────────────────
# Migration 4: report_store 赛后复盘三字段
# ─────────────────────────────────────────────────────────────

def _add_post_match_fields_to_report_store(conn: sqlite3.Connection) -> None:
    """
    新增三个赛后字段：
      match_status    TEXT  'upcoming' | 'finished'，默认 'upcoming'
      post_match_shots TEXT  JSON 格式的赛后真实射门坐标，默认 NULL
      post_match_review TEXT AI 生成的复盘 Markdown 长文，默认 NULL
    """
    migrations = [
        ("match_status",     "ALTER TABLE report_store ADD COLUMN match_status TEXT NOT NULL DEFAULT 'upcoming'"),
        ("post_match_shots", "ALTER TABLE report_store ADD COLUMN post_match_shots TEXT"),
        ("post_match_review","ALTER TABLE report_store ADD COLUMN post_match_review TEXT"),
    ]
    for col_name, sql in migrations:
        try:
            conn.execute(sql)
            log.info(f"[Migrations] Added column: report_store.{col_name}")
        except sqlite3.OperationalError:
            pass  # 列已存在，幂等跳过


# ─────────────────────────────────────────────────────────────
# Migration 5: users 表扩展字段（偏好 + 昵称查重）
# ─────────────────────────────────────────────────────────────

def _add_user_account_fields(conn: sqlite3.Connection) -> None:
    """
    给 users 表添加：
      preferences   — JSON 字符串，存储主题/通知偏好
      nickname_lower — 用于昵称唯一性校验（LOWER+TRIM）
    """
    fields = [
        ("preferences",    "ALTER TABLE users ADD COLUMN preferences TEXT NOT NULL DEFAULT '{}'"),
        ("nickname_lower", "ALTER TABLE users ADD COLUMN nickname_lower TEXT"),
    ]
    for col_name, sql in fields:
        try:
            conn.execute(sql)
            log.info(f"[Migrations] Added column: users.{col_name}")
        except sqlite3.OperationalError:
            pass  # 列已存在

    # 唯一索引（partial index，NULL 不参与唯一约束，允许多个未设昵称用户）
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uk_users_nickname_lower
          ON users(nickname_lower)
         WHERE nickname_lower IS NOT NULL
    """)
    # 回填现有行的 nickname_lower（跳过默认昵称，避免误冲突）
    conn.execute("""
        UPDATE users
           SET nickname_lower = LOWER(TRIM(nickname))
         WHERE nickname IS NOT NULL
           AND nickname != '足球探索者'
           AND nickname_lower IS NULL
    """)


# ─────────────────────────────────────────────────────────────
# Migration 6: user_sessions 表（jti 白名单 / 设备管理）
# ─────────────────────────────────────────────────────────────

def _create_user_sessions_table(conn: sqlite3.Connection) -> None:
    """
    创建设备会话白名单表。
    每次登录写入一行 jti，后续请求验证 jti 是否仍在白名单内（未被踢出）。
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            jti           TEXT PRIMARY KEY,
            user_id       INTEGER NOT NULL,
            device_label  TEXT,
            user_agent    TEXT,
            ip            TEXT,
            created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
            revoked_at    DATETIME,
            revoke_reason TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_user_active
          ON user_sessions(user_id, revoked_at)
    """)
    log.info("[Migrations] user_sessions table ensured.")


# ─────────────────────────────────────────────────────────────
# Migration 7: wechat_users → users 数据迁移
# DEPRECATED 2026-04-17 — wechat_users 物理表保留用于回滚
# ─────────────────────────────────────────────────────────────

def _migrate_wechat_users_to_users(conn: sqlite3.Connection) -> None:
    """
    把 wechat_users 中 vip_expires_at 比 users 更新的数据同步到 users。
    只做 UPDATE，不删数据，幂等安全。
    """
    try:
        conn.execute("""
            UPDATE users
               SET vip_expires_at = (
                   SELECT w.vip_expires_at FROM wechat_users w
                    WHERE w.openid = users.openid
                      AND w.vip_expires_at IS NOT NULL
                      AND (users.vip_expires_at IS NULL
                           OR w.vip_expires_at > users.vip_expires_at)
               )
             WHERE EXISTS (
                   SELECT 1 FROM wechat_users w
                    WHERE w.openid = users.openid
                      AND w.vip_expires_at IS NOT NULL)
        """)
        # 同步 role = 'vip' 给有效期仍在的用户
        conn.execute("""
            UPDATE users SET role = 'vip'
             WHERE vip_expires_at IS NOT NULL
               AND datetime(vip_expires_at) > datetime('now')
               AND role != 'admin'
        """)
        log.info("[Migrations] wechat_users → users sync complete.")
    except Exception as e:
        log.warning(f"[Migrations] wechat_users sync skipped: {e}")
