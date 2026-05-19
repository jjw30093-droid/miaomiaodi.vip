from fastapi import FastAPI, HTTPException, Header, Response, Request
from pydantic import BaseModel
import sqlite3
import os
import sys
from datetime import datetime

# 确保能导入同级或上级目录的 sync_router
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sync_router

app = FastAPI(title="Miaodi Quantitative Lab :: Cloud API 2.0")

# 引入外部路由 (同步 2.0 核心)
app.include_router(sync_router.router)

# 数据库配置 (与 sync_router 保持一致)
DB_PATH = os.environ.get("DB_PATH", "../25-26英超全数据.db")
SYNC_TOKEN = os.getenv("X_SYNC_TOKEN", "miaodi_secret_2026")

# ─── 初始化数据库结构 ─────────────────────────────────────────────────────────

def init_cloud_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # 1. 首页大盘快照表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cloud_overview (
            id INTEGER PRIMARY KEY DEFAULT 1,
            data_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 2. 详情页负载快照表 (由 sync_router 维护，此处做兼容性建表)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS match_payloads (
            match_id         TEXT PRIMARY KEY,
            report_markdown  TEXT NOT NULL,
            npxg_trend       TEXT NOT NULL DEFAULT '[]',
            shot_map_data    TEXT NOT NULL DEFAULT '[]',
            updated_at       TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

init_cloud_db()

async def verify_sync_token(x_sync_token: str = Header(None)):
    if x_sync_token != SYNC_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid Sync Token")

# ─── 1. POST 接收端 (Overview 保持在 main) ───────────────────────────────────

@app.post("/api/v1/sync/overview")
async def sync_overview(request: Request, x_sync_token: str = Header(None)):
    await verify_sync_token(x_sync_token)
    raw_body = await request.body()
    data_str = raw_body.decode('utf-8')

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO cloud_overview (id, data_json, updated_at) 
        VALUES (1, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(id) DO UPDATE SET data_json=excluded.data_json, updated_at=CURRENT_TIMESTAMP
    ''', (data_str,))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Overview snapshot updated"}

# ─── 2. GET 透传端 (Public) ──────────────────────────────────────────────────

@app.get("/api/v1/reports/latest")
def get_latest_reports_transparent():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        row = cursor.execute("SELECT data_json FROM cloud_overview WHERE id=1").fetchone()
        conn.close()
        if not row:
            return Response(content="[]", media_type="application/json")
        return Response(content=row[0], media_type="application/json")
    except Exception as e:
        print(f"Cloud API Error (Overview): {e}")
        return Response(content="[]", media_type="application/json")

# 健康检查
@app.get("/api/v1/health")
def health_check():
    return {"status": "healthy", "architecture": "cloud-local-2.0"}