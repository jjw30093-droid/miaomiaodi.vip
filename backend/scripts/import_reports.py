import sqlite3
import os
import re
from datetime import datetime

# 配置路径
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "football_uk.db"))
REPORT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")

# 目标比赛 ID
TARGET_IDS = ["5130278", "5130428", "4965739", "4965742"]

def import_reports():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 确保表存在 (如果不存在则创建，虽然通常应该已经存在)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS report_store (
            match_id TEXT PRIMARY KEY,
            title TEXT,
            markdown_content TEXT,
            created_at TEXT
        )
    ''')

    for match_id in TARGET_IDS:
        # 寻找匹配 ID 的文件
        found_file = None
        for filename in os.listdir(REPORT_DIR):
            if match_id in filename and filename.endswith(".md"):
                found_file = filename
                break
        
        if not found_file:
            print(f"Warning: No report found for Match ID {match_id}")
            continue

        file_path = os.path.join(REPORT_DIR, found_file)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 提取标题 (假设第一行是 # 标题)
        title = found_file.replace(".md", "").replace("研报_", "")
        first_line = content.split('\n')[0]
        if first_line.startswith("#"):
            title = first_line.lstrip("# ").strip()

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 插入或更新
        cursor.execute('''
            INSERT OR REPLACE INTO report_store (match_id, title, markdown_content, created_at)
            VALUES (?, ?, ?, ?)
        ''', (match_id, title, content, created_at))
        
        print(f"✅ Imported: {found_file} -> DB (Match ID: {match_id})")

    conn.commit()
    conn.close()
    print("\n🚀 All target reports imported successfully.")

if __name__ == "__main__":
    import_reports()
