"""加用户名注册 + 手动审核表"""
import sqlite3
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH") or os.path.join(_THIS_DIR, "..", "football_uk.db")


def run():
    conn = sqlite3.connect(DB_PATH)
    # 新建 pending_registrations 表（待审核队列）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_registrations (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            username         TEXT UNIQUE NOT NULL,
            password_hash    TEXT NOT NULL,
            nickname         TEXT NOT NULL,
            status           TEXT DEFAULT 'pending',
            approved_user_id INTEGER,
            approved_by      TEXT,
            approved_at      TEXT,
            rejected_reason  TEXT,
            created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
            ip               TEXT,
            user_agent       TEXT
        )
    """)
    print("✅ pending_registrations table created (or already exists)")

    # users 表加 username + password_hash + auth_source
    for col, dfn in [
        ("username",      "TEXT UNIQUE"),
        ("password_hash", "TEXT"),
        ("auth_source",   "TEXT DEFAULT 'wechat'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {dfn}")
            print(f"✅ users.{col} added")
        except Exception as e:
            print(f"⊘ users.{col} skipped: {e}")

    conn.commit()
    conn.close()
    print("✅ 用户名注册 schema migration 完成")


if __name__ == "__main__":
    run()
