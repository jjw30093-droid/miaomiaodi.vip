#!/usr/bin/env python3
"""
pipeline_runner.py — 每日主管道编排器
=====================================
替代散乱的 PM2 cron，按依赖顺序执行每日任务。
失败时停止并通知，支持断点续跑。

用法：
  python3 pipeline_runner.py              # 执行完整管道
  python3 pipeline_runner.py --from feature_eng   # 从某步开始
  python3 pipeline_runner.py --only postmatch     # 只跑某一步
  python3 pipeline_runner.py --dry-run            # 只打印不执行
"""

import os
import sys
import subprocess
import time
import json
import logging
import argparse
import sqlite3
from datetime import datetime, date, timedelta

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "football_uk.db")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
PYTHON = os.path.join(PROJECT_ROOT, "venv/bin/python3")

os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "pipeline_runner.log")),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("pipeline")

# ═══════════════════════════════════════
# 管道步骤定义（按依赖顺序）
# ═══════════════════════════════════════

PIPELINE_STEPS = [
    {
        "name": "batch_sync",
        "desc": "Bronze: 昨日比赛数据入库",
        "script": "scripts/batch_fotmob_sync.py",
        "timeout": 600,
        "gate": "validate_bronze",
    },
    {
        "name": "feature_eng",
        "desc": "Gold: 更新滚动特征",
        "script": "feature_engineering.py",
        "timeout": 600,
        "gate": "validate_features",
    },
    {
        "name": "silver_build",
        "desc": "Silver: dim_team 增量更新 + 命中率检查",
        "script": "silver_builder.py",
        "timeout": 300,
        "gate": "validate_silver",
    },
    {
        "name": "scheduler",
        "desc": "发现今明赛程",
        "script": "fotmob_scheduler.py",
        "timeout": 180,
        "gate": "validate_schedule",
    },
    {
        "name": "reports",
        "desc": "Gold: 生成今日研报",
        "script": "run_tonight_reports.py",
        "timeout": 6000,
        "gate": "validate_reports",
    },
    {
        "name": "postmatch",
        "desc": "Gold: 赛后复盘审计",
        "script": "post_match_review.py",
        "timeout": 300,
        "gate": None,
    },
    {
        "name": "retrain_check",
        "desc": "Gold: 模型漂移检测+重训",
        "script": "retrain_if_needed.py",
        "timeout": 1800,
        "gate": None,
    },
]


# ═══════════════════════════════════════
# 质量门（Gate）
# ═══════════════════════════════════════

def validate_bronze():
    """Bronze层校验：昨日数据是否正常入库"""
    conn = sqlite3.connect(DB_PATH)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    issues = []

    # 检查昨日是否有新比赛入库
    match_count = conn.execute(
        "SELECT COUNT(*) FROM dim_match WHERE Date = ? AND status = 'Finish'",
        (yesterday,)
    ).fetchone()[0]

    # 昨天可能没比赛（周一等），检查最近3天是否有数据
    recent_count = conn.execute(
        "SELECT COUNT(*) FROM dim_match WHERE Date >= ? AND status = 'Finish'",
        ((date.today() - timedelta(days=3)).isoformat(),)
    ).fetchone()[0]

    if recent_count == 0:
        issues.append(f"最近3天无任何完赛数据入库")

    # 检查是否有stats数据
    if match_count > 0:
        stats_count = conn.execute("""
            SELECT COUNT(DISTINCT Match_ID) FROM fact_team_match_stats
            WHERE Match_ID IN (SELECT Match_ID FROM dim_match WHERE Date = ?)
        """, (yesterday,)).fetchone()[0]
        if stats_count < match_count * 0.8:
            issues.append(f"昨日 {match_count} 场比赛只有 {stats_count} 场有stats")

    conn.close()

    if issues:
        log.warning(f"⚠️ Bronze Gate 警告: {'; '.join(issues)}")
        return False, issues
    log.info(f"✅ Bronze Gate 通过 (昨日 {match_count} 场, 近3天 {recent_count} 场)")
    return True, []


def validate_features():
    """Gold特征层校验：滚动特征是否更新"""
    conn = sqlite3.connect(DB_PATH)
    issues = []

    # 检查 int_team_rolling_extended 的最新日期
    latest = conn.execute("""
        SELECT MAX(d.Date) FROM int_team_rolling_extended r
        JOIN dim_match d ON r.match_id = d.Match_ID
    """).fetchone()[0]

    if latest:
        days_stale = (date.today() - date.fromisoformat(latest)).days
        if days_stale > 3:
            issues.append(f"滚动特征最新日期 {latest}，已过期 {days_stale} 天")
    else:
        issues.append("int_team_rolling_extended 无数据")

    # 检查特征行数合理性
    feature_count = conn.execute("SELECT COUNT(*) FROM int_team_rolling_extended").fetchone()[0]
    if feature_count < 1000:
        issues.append(f"滚动特征仅 {feature_count} 行，可能未完整计算")

    conn.close()

    if issues:
        log.warning(f"⚠️ Feature Gate 警告: {'; '.join(issues)}")
        return False, issues
    log.info(f"✅ Feature Gate 通过 (最新日期 {latest}, {feature_count} 行)")
    return True, []


def validate_reports():
    """Gold研报层校验：今日研报是否生成"""
    conn = sqlite3.connect(DB_PATH)
    issues = []
    today_str = date.today().isoformat()

    # 检查 report_store 今日记录
    report_count = conn.execute(
        "SELECT COUNT(*) FROM report_store WHERE match_time >= ?",
        (today_str,)
    ).fetchone()[0]

    # 检查 target_matches.json 有多少场
    sched_path = os.path.join(PROJECT_ROOT, "schedule", "target_matches.json")
    scheduled = 0
    if os.path.exists(sched_path):
        try:
            with open(sched_path) as f:
                scheduled = len(json.load(f))
        except:
            pass

    if scheduled > 0 and report_count == 0:
        issues.append(f"赛程有 {scheduled} 场导致研报为0")

    # 检查 prediction_audit 是否写入
    audit_count = conn.execute(
        "SELECT COUNT(*) FROM prediction_audit WHERE match_date >= ?",
        (today_str,)
    ).fetchone()[0]
    if scheduled > 0 and audit_count == 0:
        issues.append(f"prediction_audit 今日无记录")

    conn.close()

    if issues:
        log.warning(f"⚠️ Report Gate 警告: {'; '.join(issues)}")
        return False, issues
    log.info(f"✅ Report Gate 通过 (赛程 {scheduled} 场, 研报 {report_count} 场, 审计 {audit_count} 条)")
    return True, []



def validate_schedule():
    """调度器校验：target_matches.json 是否有未来比赛"""
    from datetime import datetime as _dt
    sched_path = os.path.join(PROJECT_ROOT, "schedule", "target_matches.json")
    issues = []
    if not os.path.exists(sched_path):
        issues.append("target_matches.json 不存在")
    else:
        try:
            with open(sched_path) as f:
                matches = json.load(f)
            # 过滤出未来比赛（开球时间 > 当前时间）
            now = _dt.now()
            future = [m for m in matches if _dt.strptime(m.get("kickoff_time","2000-01-01 00:00:00"), "%Y-%m-%d %H:%M:%S") > now]
            stale = len(matches) - len(future)
            if len(future) == 0:
                issues.append(f"无未来比赛（总{len(matches)}场, {stale}场已过期）")
            else:
                if stale > 0:
                    log.info(f"  📋 赛程: {len(future)}场未来 + {stale}场已过期")
                log.info(f"✅ Schedule Gate 通过 ({len(future)} 场未来比赛)")
        except Exception as e:
            issues.append(f"JSON 解析失败: {e}")
    if issues:
        log.warning(f"⚠️ Schedule Gate 警告: {'; '.join(issues)}")
        return False, issues
    return True, []


def validate_silver():
    """Silver 层质量门 Gate 4：dim_team 命中率 ≥ 90%"""
    conn = sqlite3.connect(DB_PATH)
    issues = []
    try:
        row = conn.execute(
            "SELECT resolve_rate, resolve_checked, status FROM silver_build_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            issues.append("silver_build_log 无记录，silver_build 可能未执行")
        else:
            rate, checked, status = row[0], row[1], row[2]
            if checked == 0:
                log.info("✅ Silver Gate 通过（今明无赛事，跳过命中率检查）")
            elif rate < 0.90:
                issues.append(f"命中率 {rate:.2%} < 90%（{checked} 支队检查）")
            else:
                log.info(f"✅ Silver Gate 通过 (命中率 {rate:.2%}, {checked} 支队)")
    except Exception as e:
        issues.append(f"silver_build_log 查询失败: {e}")
    finally:
        conn.close()

    # Phase 2.5: odds coverage WARN (non-blocking)
    try:
        _conn2 = __import__('sqlite3').connect(DB_PATH)
        schedule_count = _conn2.execute(
            "SELECT COUNT(*) FROM dim_match WHERE Date >= date('now','-1 day') AND Date <= date('now','1 day')"
        ).fetchone()[0]
        odds_count = _conn2.execute(
            "SELECT COUNT(DISTINCT match_id) FROM silver_match_odds WHERE match_date >= date('now','-1 day')"
        ).fetchone()[0]
        _conn2.close()
        if schedule_count > 0:
            odds_cov = odds_count / schedule_count
            if odds_cov < 0.50:
                log.warning(f"Gate 4 WARN: odds coverage {odds_cov:.0%} ({odds_count}/{schedule_count} 场)")
            else:
                log.info(f"  odds coverage: {odds_cov:.0%} ({odds_count}/{schedule_count} 场) ✅")
    except Exception as _oe:
        log.debug(f"Gate 4 odds coverage 检查失败（非致命）: {_oe}")

    if issues:
        log.warning(f"⚠️ Silver Gate 警告: {'; '.join(issues)}")
        return False, issues
    return True, []


GATE_FUNCS = {
    "validate_bronze": validate_bronze,
    "validate_features": validate_features,
    "validate_silver": validate_silver,
    "validate_reports": validate_reports,
    "validate_schedule": validate_schedule,
}


# ═══════════════════════════════════════
# 通知
# ═══════════════════════════════════════

def notify(msg: str, title: str = "喵弟管道通知"):
    """发送 Server酱 微信通知"""
    key = os.environ.get('SERVERCHAN_KEY', '')
    if not key:
        return
    try:
        import urllib.request, urllib.parse
        url = f'https://sctapi.ftqq.com/{key}.send'
        payload = urllib.parse.urlencode({'title': title, 'desp': msg}).encode()
        urllib.request.urlopen(url, payload, timeout=10)
        log.info(f"  📱 微信通知已发送: {title}")
    except Exception as e:
        log.warning(f"Server酱通知失败: {e}")


# ═══════════════════════════════════════
# 执行引擎
# ═══════════════════════════════════════

def run_step(step: dict, dry_run: bool = False) -> bool:
    """执行单个管道步骤，返回 True=成功 False=失败"""
    name = step["name"]
    script = os.path.join(PROJECT_ROOT, step["script"])
    timeout = step["timeout"]

    log.info(f"\n{'='*60}")
    log.info(f"▶ [{name}] {step['desc']}")
    log.info(f"  脚本: {step['script']}  超时: {timeout}s")

    if dry_run:
        log.info(f"  [DRY-RUN] 跳过执行")
        return True

    if not os.path.exists(script):
        log.error(f"  ❌ 脚本不存在: {script}")
        return False

    start_time = time.time()
    try:
        result = subprocess.run(
            [PYTHON, script],
            cwd=PROJECT_ROOT,
            timeout=timeout,
            capture_output=True,
            text=True,
            env={**os.environ, "PROJECT_ROOT": PROJECT_ROOT, "DB_PATH": DB_PATH}
        )
        elapsed = time.time() - start_time

        if result.returncode != 0:
            log.error(f"  ❌ 执行失败 (exit={result.returncode}, {elapsed:.1f}s)")
            if result.stderr:
                log.error(f"  STDERR: {result.stderr[-500:]}")
            return False

        log.info(f"  ✅ 完成 ({elapsed:.1f}s)")

        # 最后几行 stdout 输出
        if result.stdout:
            for line in result.stdout.strip().split('\n')[-5:]:
                log.info(f"  │ {line}")

    except subprocess.TimeoutExpired:
        log.error(f"  ❌ 超时 ({timeout}s)")
        return False
    except Exception as e:
        log.error(f"  ❌ 异常: {e}")
        return False

    # 质量门检查
    gate_name = step.get("gate")
    if gate_name and gate_name in GATE_FUNCS:
        log.info(f"  🔍 执行质量门: {gate_name}")
        passed, issues = GATE_FUNCS[gate_name]()
        if not passed:
            log.warning(f"  ⚠️ 质量门未通过 (非阻断，继续执行): {issues}")
            # 质量门失败是警告，不阻断管道（数据可能正常但不完整）

    return True


def run_pipeline(from_step=None, only_step=None, dry_run=False):
    """执行完整管道或部分管道"""
    log.info(f"\n{'#'*60}")
    log.info(f"# 喵弟量化 · 每日管道 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"# from={from_step or 'start'} only={only_step or 'all'} dry_run={dry_run}")
    log.info(f"{'#'*60}")

    started = from_step is None
    total, passed, failed = 0, 0, 0
    failed_steps = []

    for step in PIPELINE_STEPS:
        if only_step and step["name"] != only_step:
            continue
        if not started:
            if step["name"] == from_step:
                started = True
            else:
                log.info(f"  ⏭ 跳过 [{step['name']}]")
                continue

        total += 1
        success = run_step(step, dry_run=dry_run)

        if success:
            passed += 1
        else:
            failed += 1
            failed_steps.append(step["name"])
            # 失败后是否继续：batch_sync/feature_eng 失败阻断后续，其他步骤继续
            if step["name"] in ["batch_sync", "feature_eng"]:
                log.error(f"  🛑 关键步骤 [{step['name']}] 失败，管道中止")
                notify(
                    f"失败步骤详情见下方\n"
                    f"失败步骤: {step['name']}\n"
                    f"时间: {datetime.now().strftime('%H:%M:%S')}"
                )
                break
            else:
                log.warning(f"  ⚠️ [{step['name']}] 失败，继续后续步骤")

    # 汇总
    log.info(f"\n{'='*60}")
    log.info(f"📊 管道执行完成: {passed}/{total} 步成功")
    if failed_steps:
        log.warning(f"❌ 失败步骤: {', '.join(failed_steps)}")
        notify(
            f"⚠️ 喵弟管道完成 ({passed}/{total})\n"
            f"失败: {', '.join(failed_steps)}\n"
            f"时间: {datetime.now().strftime('%H:%M:%S')}"
        )
    else:
        log.info(f"✅ 全部通过")

    # 收集关键指标
    try:
        import sqlite3 as _sq
        _conn = _sq.connect(DB_PATH)
        _today = date.today().isoformat()
        _yesterday = (date.today() - timedelta(days=1)).isoformat()
        _synced = _conn.execute("SELECT COUNT(*) FROM dim_match WHERE Date=? AND status='Finish'", (_yesterday,)).fetchone()[0]
        _reports = _conn.execute("SELECT COUNT(*) FROM report_store WHERE match_time >= ?", (_today,)).fetchone()[0]
        import json as _json
        _sched_path = os.path.join(PROJECT_ROOT, "schedule", "target_matches.json")
        _sched = 0
        if os.path.exists(_sched_path):
            with open(_sched_path) as _f:
                _sched = len(_json.load(_f))
        _conn.close()
        _stats = f"入库{_synced}场 | 赛程{_sched}场 | 研报{_reports}场"
    except:
        _stats = ""

    if failed_steps:
        notify(
            f"失败步骤: {', '.join(failed_steps)}\n{_stats}",
            title=f"⚠️ 管道 {passed}/{total} ({_stats})"
        )
    else:
        notify(
            _stats,
            title=f"✅ 管道 {passed}/{total} ({_stats})"
        )
    log.info(f"{'='*60}")

    return failed == 0


def main():
    parser = argparse.ArgumentParser(description="喵弟量化 · 每日管道编排器")
    parser.add_argument("--from", dest="from_step", help="从某步开始执行")
    parser.add_argument("--only", dest="only_step", help="只执行某一步")
    parser.add_argument("--dry-run", action="store_true", help="只打印不执行")
    parser.add_argument("--list", action="store_true", help="列出所有步骤")
    args = parser.parse_args()

    if args.list:
        print("\n管道步骤:")
        for i, s in enumerate(PIPELINE_STEPS):
            gate = f" [Gate: {s['gate']}]" if s.get('gate') else ""
            print(f"  {i+1}. {s['name']:20s} {s['desc']}{gate}")
        return

    success = run_pipeline(
        from_step=args.from_step,
        only_step=args.only_step,
        dry_run=args.dry_run,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
