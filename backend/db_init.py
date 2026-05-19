"""
数据库初始化脚本：幂等执行，可反复运行
建立 match_pipeline 表，并为 report_store 追加必要字段
"""
import sqlite3, os

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "25-26英超全数据.db")

def run():
    conn = sqlite3.connect(DB_PATH)

    # 1. 创建 match_pipeline 状态机表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS match_pipeline (
            match_id                TEXT PRIMARY KEY,
            status                  TEXT DEFAULT 'DISCOVERED',
            -- 状态枚举：
            -- DISCOVERED | PRE_MATCH_READY | ANALYSIS_UPDATED
            -- | LINEUP_CONFIRMED | FINAL_REPORT_READY
            -- | MATCH_FINISHED | REVIEW_GENERATED | ARCHIVED
            league                  TEXT,
            home_team               TEXT,
            away_team               TEXT,
            home_team_id            INTEGER DEFAULT 0,
            away_team_id            INTEGER DEFAULT 0,
            kickoff_time            TEXT,           -- ISO 格式，本地时间

            -- 各阶段时间戳
            odds_last_fetched_at    TEXT,           -- 最近一次赔率抓取
            injury_last_fetched_at  TEXT,           -- 最近一次伤病更新
            pre_match_generated_at  TEXT,           -- PRE_MATCH_READY 生成时间
            analysis_generated_at   TEXT,           -- ANALYSIS_UPDATED 生成时间
            lineup_polling_start_at TEXT,           -- 开始轮询首发的时间
            lineup_confirmed_at     TEXT,           -- 首发确认时间
            lineup_json             TEXT,           -- 首发 JSON 数据
            final_generated_at      TEXT,           -- FINAL_REPORT_READY 生成时间
            push_sent_at            TEXT,           -- 推送时间
            postmatch_scraped_at    TEXT,           -- 赛后数据抓取时间
            review_generated_at     TEXT,           -- 复盘生成时间
            archived_at             TEXT,           -- 归档时间

            -- 错误追踪
            last_error              TEXT,
            retry_count             INTEGER DEFAULT 0,

            created_at              TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 2. 为 report_store 添加新字段（幂等 ALTER TABLE）
    new_columns = [
        ("is_archived",     "INTEGER DEFAULT 0"),
        ("is_public",       "INTEGER DEFAULT 0"),   # 归档后公开（用于 SEO）
        ("preview_content", "TEXT"),                # 免费预览段落（Markdown 片段）
        ("push_sent_at",    "TEXT"),
        ("pipeline_status", "TEXT"),               # 冗余字段，方便 API 直接读取
    ]
    for col_name, col_def in new_columns:
        try:
            conn.execute(f"ALTER TABLE report_store ADD COLUMN {col_name} {col_def}")
            print(f"✅ report_store.{col_name} 已添加")
        except Exception:
            pass  # 字段已存在

    conn.commit()
    conn.close()
    print("✅ 数据库初始化完成")

if __name__ == "__main__":
    run()
