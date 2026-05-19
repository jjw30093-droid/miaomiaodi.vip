"""
archiver.py
===========
将开球时间超过2小时的比赛标记为 is_archived=1，供赛后复盘任务使用。
可单独运行，也被 PM2 job-archiver 每小时调用。

⚠️ 时区铁律（2026-04-27 修复）：
  report_store.match_time 统一存 UTC（CLAUDE.md §1）。
  归档阈值必须用 datetime.now(timezone.utc) - 2h，与 match_time 同坐标系比较。
  历史 bug：曾用 datetime.now(CST) - 2h，导致比赛在真正开球前 ~6h 被误归档，
  下游 run_post_match_reviews 因 is_archived=1 而对未结束比赛触发复盘，
  向 LLM 发空白 shots/分数，污染 post_match_review 字段。
"""
import os, sqlite3, logging
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get("DB_PATH", "/home/ubuntu/app/backend/football_uk.db")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def run_archiver():
    conn = sqlite3.connect(DB_PATH)
    # match_time 存 UTC，用 UTC now - 2h 作为归档阈值（与 match_time 同坐标系）
    now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    threshold_dt = now_utc_naive - timedelta(hours=2)
    threshold = threshold_dt.strftime("%Y-%m-%d %H:%M:%S")

    # 防御性自检：阈值不得在 UTC now 之后（一旦发生说明时区又错配）
    if threshold_dt > now_utc_naive:
        log.error(f"❌ archiver 阈值异常（>now_utc），拒绝执行: threshold={threshold}, now_utc={now_utc_naive}")
        conn.close()
        return 0
    cur = conn.execute("""
        UPDATE report_store
        SET is_archived = 1, pipeline_status = 'ARCHIVED'
        WHERE is_archived = 0
          AND match_time < ?
          AND home_team != 'Home'
    """, (threshold,))
    updated = cur.rowcount
    conn.commit()
    conn.close()
    if updated:
        log.info(f"✅ 归档完成：{updated} 场比赛标记为 is_archived=1 (threshold={threshold})")
    else:
        log.info(f"ℹ️  无新增归档 (threshold={threshold})")
    return updated


def archive_match(match_id: str, match: dict = None):
    """单场手动归档（供外部调用）"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE report_store SET is_archived=1, pipeline_status='ARCHIVED' WHERE match_id=?",
        (str(match_id),)
    )
    conn.commit()
    conn.close()
    log.info(f"✅ Match {match_id} archived.")
    return True


if __name__ == "__main__":
    run_archiver()
