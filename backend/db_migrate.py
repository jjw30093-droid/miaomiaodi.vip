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
        # ── Phase 4: 商业化基础表（Day 2）────────────────────────────────────
        _upgrade_user_unlocks_v2(conn)
        _create_products_table(conn)
        _create_orders_table(conn)
        _seed_base_products(conn)
        _seed_worldcup_products(conn)
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


# ─────────────────────────────────────────────────────────────
# Migration 8a: user_unlocks v2（user_id 列迁移 + 补全字段）
#
# 旧表（生产可能存在）至少有 username + match_id 两列。
# 升级路径：
#   1. 表不存在 → 直接建 v2 完整结构
#   2. 表存在但缺 user_id 列 → ALTER TABLE 添加，通过 JOIN users 回填
#   3. 无论哪条路径，幂等补全 unlock_source / source_ref / expires_at + 索引
# ─────────────────────────────────────────────────────────────

def _upgrade_user_unlocks_v2(conn: sqlite3.Connection) -> None:
    table_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='user_unlocks'"
    ).fetchone() is not None

    if not table_exists:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_unlocks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                match_id        TEXT NOT NULL,
                unlock_source   TEXT NOT NULL DEFAULT 'unknown',
                source_ref      TEXT,
                unlocked_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at      TIMESTAMP,
                UNIQUE(user_id, match_id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        log.info("[Migrations] Created table: user_unlocks (v2, fresh)")
    else:
        # 幂等补全各列
        for col, defn in [
            ("user_id",       "INTEGER"),
            ("unlock_source", "TEXT NOT NULL DEFAULT 'unknown'"),
            ("source_ref",    "TEXT"),
            ("expires_at",    "TIMESTAMP"),
        ]:
            try:
                conn.execute(f"ALTER TABLE user_unlocks ADD COLUMN {col} {defn}")
                log.info(f"[Migrations] Added column: user_unlocks.{col}")
            except sqlite3.OperationalError:
                pass  # 列已存在

        # 若旧表含 username 列，通过 JOIN users 回填 user_id
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(user_unlocks)")}
        if "username" in existing_cols:
            try:
                conn.execute("""
                    UPDATE user_unlocks
                       SET user_id = (
                           SELECT id FROM users
                            WHERE users.username = user_unlocks.username
                       )
                     WHERE user_id IS NULL
                """)
                log.info("[Migrations] user_unlocks.user_id backfilled via users.username")
            except Exception as e:
                log.warning(f"[Migrations] user_unlocks.user_id backfill skipped: {e}")

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_unlocks_user_match
          ON user_unlocks(user_id, match_id)
    """)
    log.info("[Migrations] user_unlocks v2 ensured.")


# ─────────────────────────────────────────────────────────────
# Migration 8b: products（套餐 SKU 表）
# ─────────────────────────────────────────────────────────────

def _create_products_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sku             TEXT NOT NULL UNIQUE,
            name            TEXT NOT NULL,
            type            TEXT NOT NULL,
            price_cents     INTEGER NOT NULL,
            currency        TEXT DEFAULT 'CNY',
            metadata        TEXT DEFAULT '{}',
            is_active       INTEGER DEFAULT 1,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_products_sku    ON products(sku)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_products_active ON products(is_active)")
    log.info("[Migrations] products table ensured.")


# ─────────────────────────────────────────────────────────────
# Migration 8c: orders（订单流水表，依赖 products 先建好）
# ─────────────────────────────────────────────────────────────

def _create_orders_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no            TEXT NOT NULL UNIQUE,
            user_id             INTEGER NOT NULL,
            product_id          INTEGER NOT NULL,
            sku_snapshot        TEXT NOT NULL,
            name_snapshot       TEXT NOT NULL,
            price_cents         INTEGER NOT NULL,
            currency            TEXT DEFAULT 'CNY',
            payment_provider    TEXT NOT NULL,
            provider_order_id   TEXT,
            status              TEXT NOT NULL,
            paid_at             TIMESTAMP,
            refunded_at         TIMESTAMP,
            expires_at          TIMESTAMP,
            match_id            TEXT,
            metadata            TEXT DEFAULT '{}',
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id)    REFERENCES users(id),
            FOREIGN KEY(product_id) REFERENCES products(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_user        ON orders(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_status      ON orders(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_order_no    ON orders(order_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_provider_id ON orders(provider_order_id)")
    log.info("[Migrations] orders table ensured.")


# ─────────────────────────────────────────────────────────────
# Migration 8d: 世界杯套餐 SKU 预填
# INSERT OR IGNORE：sku 唯一约束冲突时静默跳过，不覆盖已改价格。
# ─────────────────────────────────────────────────────────────

def _seed_base_products(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """INSERT OR IGNORE INTO products (sku, name, type, price_cents, metadata)
           VALUES (?, ?, ?, ?, ?)""",
        [
            ("single_match_std", "单场研报", "single_match", 2990, '{}'),
        ]
    )
    log.info("[Migrations] Base product SKUs seeded (OR IGNORE).")


def _seed_worldcup_products(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """INSERT OR IGNORE INTO products (sku, name, type, price_cents, metadata)
           VALUES (?, ?, ?, ?, ?)""",
        [
            ("wc_single_group", "世界杯单场研报(小组赛)", "single_match",  1990, '{"stage":"group"}'),
            ("wc_single_ko",    "世界杯单场研报(淘汰赛)", "single_match",  2990, '{"stage":"knockout"}'),
            ("wc_single_final", "世界杯单场研报(决赛圈)", "single_match",  4990, '{"stage":"final"}'),
            ("wc_group_pack",   "世界杯小组赛全包(48场)", "package",      19900, '{"scope":"group_stage","match_count":48}'),
            ("wc_ko_pack",      "世界杯淘汰赛通票(16场)", "package",      29900, '{"scope":"knockout","match_count":16}'),
            ("wc_full_pack_1",  "世界杯全包-上半段",      "package",      29900, '{"scope":"full_half_1"}'),
            ("wc_full_pack_2",  "世界杯全包-下半段",      "package",      19900, '{"scope":"full_half_2"}'),
        ]
    )
    log.info("[Migrations] World Cup product SKUs seeded (OR IGNORE).")
