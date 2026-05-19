"""
generate_cdks.py — 一次性手动发卡脚本（断网应急 / 历史兼容用）。

⚠️ 日常发卡走 /admin/cdk 后台 UI → POST /api/v1/admin/generate-cdks。
⚠️ 该脚本不写 admin_audit_log，绕过任何审计；仅在 API 不可用时使用。

用法：
    cd /home/ubuntu/app/backend && source venv/bin/activate
    python3 scripts/generate_cdks.py
"""
import os
import sqlite3
import secrets
import string
from datetime import datetime, timedelta

# 脚本位于 backend/scripts/，DB 在 backend/，需上溯一层
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
DB_PATH = os.environ.get("DB_PATH", os.path.join(_BACKEND_DIR, "football_uk.db"))

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # 创建 CDK 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shop_cdk (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            quota INTEGER NOT NULL,
            is_used INTEGER DEFAULT 0,
            used_by TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME
        )
    """)
    # 创建用户元数据表 (用于存储额度)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_meta (
            username TEXT PRIMARY KEY,
            report_quota INTEGER DEFAULT 0,
            is_vip INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def generate_cdk_code(length=10):
    """生成高强度随机码，剔除易混淆字符 (O, 0, I, 1)"""
    # 剔除 O, 0, I, 1
    alphabet = "".join(c for c in string.ascii_uppercase + string.digits if c not in "O0I1")
    return "".join(secrets.choice(alphabet) for _ in range(length))

def batch_generate_cdks(count, quota, expire_days=30):
    """批量生成 CDK 并入库"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    expires_at = (datetime.now() + timedelta(days=expire_days)).strftime("%Y-%m-%d %H:%M:%S")
    
    generated_codes = []
    for _ in range(count):
        code = generate_cdk_code()
        try:
            cursor.execute(
                "INSERT INTO shop_cdk (code, quota, expires_at) VALUES (?, ?, ?)",
                (code, quota, expires_at)
            )
            generated_codes.append(code)
        except sqlite3.IntegrityError:
            # 极小概率冲突，跳过
            continue
            
    conn.commit()
    conn.close()
    
    print(f"✅ 成功生成 {len(generated_codes)} 个 CDK (额度: {quota}, 有效期: {expire_days} 天)")
    for c in generated_codes:
        print(f"  - {c}")
    return generated_codes

if __name__ == "__main__":
    # 示例：生成 5 个，每个增加 1 场额度
    batch_generate_cdks(count=5, quota=1)
