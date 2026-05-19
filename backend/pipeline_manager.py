"""
pipeline_manager.py
===================
生产自动化大脑 · 本地运行版

调度规则
─────────────────────────────────────────────
[宏观 - 每天定时]
  12:00  赛程爬取（未来3天）→ 立刻为所有新场次生成初版研报 → 推 AWS
  13:00  复盘昨日所有完赛场次 + 模型漂移检测

[微观 - 每5分钟轮询]
  赛前 24H  → 更新赔率 → 重新生成研报 → 推 AWS
  赛前 12H  → 更新赔率 → 重新生成研报 → 推 AWS
  赛前  6H  → 更新赔率 → 重新生成研报 → 推 AWS
  赛前  1H  → 更新赔率 → 重新生成研报 → 推 AWS
  赛前 45M  → 更新赔率 + 首发阵容 → 生成定稿研报 → 推 AWS

启动方式：
    python pipeline_manager.py
"""

# DEPRECATED 2026-04-23 — 仅手动调试用，生产调度在 pm2/ecosystem.config.js
# 所有真正的定时任务由 pm2 cron 管理；此文件保留仅供本地手动触发单步验证。

import os, sys, json, sqlite3, logging, subprocess
from datetime import datetime, timedelta

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

DB_PATH     = os.path.join(PROJECT_ROOT, "football_uk.db")
SCHEDULE_FILE = os.path.join(PROJECT_ROOT, "schedule", "target_matches.json")
ODDS_FILE   = os.path.join(PROJECT_ROOT, "odds", "match_odds_data.json")
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")
LOG_DIR     = os.path.join(PROJECT_ROOT, "logs")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(LOG_DIR, "pipeline.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ─── 任务状态机 ───────────────────────────────────────────────────────────────

def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_log (
            match_id   TEXT,
            stage      TEXT,
            status     TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (match_id, stage)
        )
    """)
    conn.commit()
    return conn

def is_done(match_id, stage) -> bool:
    conn = _db()
    row = conn.execute(
        "SELECT status FROM task_log WHERE match_id=? AND stage=?", (match_id, stage)
    ).fetchone()
    conn.close()
    return row is not None and row[0] == "DONE"

def mark_done(match_id, stage):
    conn = _db()
    conn.execute("""
        INSERT INTO task_log (match_id, stage, status)
        VALUES (?, ?, 'DONE')
        ON CONFLICT(match_id, stage) DO UPDATE SET status='DONE', updated_at=CURRENT_TIMESTAMP
    """, (match_id, stage))
    conn.commit()
    conn.close()


# ─── 工具函数 ────────────────────────────────────────────────────────────────

def run(cmd: list, label: str):
    log.info(f"▶ {label}")
    ret = subprocess.run(cmd, capture_output=True, text=True)
    if ret.returncode != 0:
        log.warning(f"  ⚠️  {label} 返回非零码: {ret.returncode}")
        if ret.stderr.strip():
            log.warning(f"  STDERR: {ret.stderr.strip()[:300]}")
    else:
        log.info(f"  ✅ {label} 完成")
    return ret.returncode == 0

def push_to_aws(match_id: str):
    """将研报快照推送到 AWS"""
    pusher = os.path.join(PROJECT_ROOT, "scripts", "aws_pusher.py")
    if os.path.exists(pusher):
        run(["python3", pusher, str(match_id)], f"AWS推送 match={match_id}")
    else:
        log.warning("aws_pusher.py 不存在，跳过推送")

def load_schedule() -> list:
    if not os.path.exists(SCHEDULE_FILE):
        return []
    with open(SCHEDULE_FILE, encoding="utf-8") as f:
        return json.load(f)

def scrape_odds(match_ids: list):
    """调用赔率爬虫更新目标场次的赔率"""
    scraper = os.path.join(PROJECT_ROOT, "scripts", "scrape_euro_odds.py")
    if os.path.exists(scraper):
        run(["python3", scraper], "赔率爬取")
    else:
        log.warning("scrape_euro_odds.py 不存在，跳过赔率爬取")

def fetch_lineup(match_id: str) -> bool:
    """尝试爬取首发阵容，返回是否成功"""
    lineup_script = os.path.join(PROJECT_ROOT, "scripts", "batch_lineup_sync_and_filter.py")
    if not os.path.exists(lineup_script):
        log.warning(f"首发爬取脚本不存在，跳过 match={match_id}")
        return False
    ok = run(["python3", lineup_script, "--match_id", str(match_id)], f"首发爬取 match={match_id}")
    return ok

def generate_report(match_id: str = None, label: str = "", final: bool = False):
    """调用研报生成脚本"""
    script = os.path.join(PROJECT_ROOT, "generate_match_report.py")
    cmd = ["python3", script]
    if match_id:
        cmd += ["--match_id", str(match_id)]
    if final:
        cmd += ["--final"]
    run(cmd, f"研报生成{' · ' + label if label else ''}")


# ─── 宏观任务 ────────────────────────────────────────────────────────────────

def job_schedule_sync():
    """
    12:00 每日执行
    1. 爬取未来3天赛程 → target_matches.json
    2. 对所有新场次立刻生成初版研报 + 推 AWS
    """
    log.info("=" * 60)
    log.info("📅 [12:00] 赛程同步任务启动（未来3天）")

    # Step 1: 爬取赛程
    scheduler = os.path.join(PROJECT_ROOT, "fotmob_scheduler.py")
    run(["python3", scheduler], "FotMob赛程爬取")

    # Step 2: 对新增场次生成初版研报
    matches = load_schedule()
    if not matches:
        log.warning("target_matches.json 为空，跳过研报生成")
        return

    log.info(f"共 {len(matches)} 场比赛，开始生成初版研报...")
    for m in matches:
        mid = str(m["match_id"])
        if is_done(mid, "INITIAL_REPORT"):
            log.info(f"  跳过（已生成）: {m.get('match_name', mid)}")
            continue
        scrape_odds([mid])
        generate_report(match_id=mid, label="初版")
        push_to_aws(mid)
        mark_done(mid, "INITIAL_REPORT")
        log.info(f"  ✅ 初版研报完成: {m.get('match_name', mid)}")

    log.info("📅 赛程同步任务完成")


def job_daily_review():
    """
    13:00 每日执行
    步骤：
      1. FotMob 爬虫：抓取昨日联赛范围内所有完赛场次 → 写入 football_uk.db
      2. 特征工程：为新入库场次重建 rolling features (feature_engineering.py)
      3. dbt 增量刷新：重建 int_team_rolling_features (int_team_match_flattened)
      4. 赛后复盘 + 模型漂移检测
    """
    log.info("=" * 60)
    log.info("🔍 [13:00] 赛后全流程启动")

    # Step 1: 爬虫 - 昨日完赛比赛入库
    sync_script = os.path.join(PROJECT_ROOT, "scripts", "batch_fotmob_sync.py")
    run(["python3", sync_script], "FotMob昨日赛事入库")

    # Step 2: 特征工程 - 为新场次补全 rolling extended / Elo 等
    fe_script = os.path.join(PROJECT_ROOT, "feature_engineering.py")
    run(["python3", fe_script], "特征工程 rolling 重建")

    # Step 3: dbt 增量刷新 - 重建 int_team_rolling_features
    dbt_dir = os.path.join(PROJECT_ROOT, "quant_dbt")
    if os.path.isdir(dbt_dir):
        run(
            ["dbt", "run", "--select", "int_team_match_flattened", "int_team_rolling_features"],
            "dbt 增量刷新",
        )
    else:
        log.warning("quant_dbt 目录不存在，跳过 dbt 刷新")

    # Step 4: 复盘 + 漂移检测
    review_script = os.path.join(PROJECT_ROOT, "post_match_review.py")
    run(["python3", review_script], "赛后复盘+漂移检测")

    log.info("🔍 赛后全流程完成")


# ─── 微观轮询 ────────────────────────────────────────────────────────────────

# 触发节点定义：(阶段名, 分钟数上限, 是否抓首发, 是否定稿)
STAGES = [
    ("24H",    24 * 60, False, False),
    ("12H",    12 * 60, False, False),
    ("6H",      6 * 60, False, False),
    ("1H",      1 * 60, False, False),
    ("45M",         45, True,  True ),   # 45分钟：首发+定稿
]

def job_monitor_matches():
    """每5分钟轮询：处理赛前各时间节点的赔率更新 / 首发 / 定稿"""
    now = datetime.now()
    matches = load_schedule()
    if not matches:
        return

    for m in matches:
        mid = str(m["match_id"])
        kickoff_str = m.get("kickoff_time", "")
        if not kickoff_str:
            continue
        try:
            kickoff = datetime.strptime(kickoff_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

        minutes_to_kick = (kickoff - now).total_seconds() / 60.0
        if minutes_to_kick < 0:
            continue  # 已开赛，不处理

        for stage, threshold, need_lineup, is_final in STAGES:
            if minutes_to_kick > threshold:
                continue  # 还没到这个节点
            if is_done(mid, stage):
                continue  # 已触发过

            log.info(f"⚽ [{stage}] {m.get('match_name', mid)}（距开球 {int(minutes_to_kick)}分钟）")

            # 更新赔率
            scrape_odds([mid])

            # 尝试抓首发（45分钟节点）
            lineup_ok = False
            if need_lineup:
                lineup_ok = fetch_lineup(mid)
                if not lineup_ok:
                    log.warning(f"  首发未出，挂起等待下次轮询（match={mid}）")
                    break  # 不打 DONE，下次轮询继续重试

            # 生成研报
            label = "定稿" if is_final else stage
            generate_report(match_id=mid, label=label, final=is_final)
            push_to_aws(mid)
            mark_done(mid, stage)

            break  # 每次轮询每场比赛只触发一个节点（最紧迫的那个）


# ─── 主程序：APScheduler 调度 ─────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        log.error("缺少 apscheduler，请运行: pip install apscheduler")
        sys.exit(1)

    log.info("🚀 Pipeline Manager 启动...")
    log.info(f"   DB:      {DB_PATH}")
    log.info(f"   赛程:    {SCHEDULE_FILE}")
    log.info(f"   研报:    {REPORTS_DIR}")

    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    # 每天 12:00 赛程同步 + 初版研报
    scheduler.add_job(
        job_schedule_sync,
        CronTrigger(hour=12, minute=0),
        id="schedule_sync",
        name="赛程同步+初版研报",
        replace_existing=True,
    )

    # 每天 13:00 赛后复盘
    scheduler.add_job(
        job_daily_review,
        CronTrigger(hour=13, minute=0),
        id="daily_review",
        name="赛后复盘+漂移检测",
        replace_existing=True,
    )

    # 每5分钟微观轮询
    scheduler.add_job(
        job_monitor_matches,
        IntervalTrigger(minutes=5),
        id="match_monitor",
        name="赛前更新轮询",
        replace_existing=True,
    )

    # 启动时立刻跑一次轮询
    log.info("⚡ 启动时执行一次赛前轮询...")
    job_monitor_matches()

    log.info("⏰ 调度器已启动，等待定时任务...")
    log.info("   Ctrl+C 安全退出")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("🛑 Pipeline Manager 已安全关闭。")
