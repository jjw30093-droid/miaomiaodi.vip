import logging, datetime, sqlite3

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "football_uk.db"))

def fetch_injuries(match_id: str, match: dict):
    # 占位：实际生产中可调用第三方 API 或 爬虫
    # 此处仅记录日志并更新采集时间
    now = datetime.datetime.now().isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE match_pipeline SET injury_last_fetched_at=? WHERE match_id=?",
        [now, str(match_id)]
    )
    conn.commit()
    conn.close()
    return True
