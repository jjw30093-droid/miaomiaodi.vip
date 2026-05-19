#!/usr/bin/env python3
"""Daily data quality report — 覆盖率矩阵 + 延迟 Finish 检测。"""
import os, sys, sqlite3, logging
from datetime import datetime, timezone

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "backend", "football_uk.db"))

# 允许直接 import backend/scripts 下的 notify.py
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend", "scripts"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("data_quality")

COVERAGE_SQL = """
SELECT 
  d.Date,
  COUNT(*) AS finished,
  SUM(CASE WHEN t.Match_ID IS NOT NULL THEN 1 ELSE 0 END) AS team_stats,
  SUM(CASE WHEN p.match_id IS NOT NULL THEN 1 ELSE 0 END) AS player_stats,
  SUM(CASE WHEN s.match_id IS NOT NULL THEN 1 ELSE 0 END) AS shotmap,
  SUM(CASE WHEN o.match_id IS NOT NULL THEN 1 ELSE 0 END) AS closing_odds
FROM dim_match d
LEFT JOIN fact_team_match_stats t ON t.Match_ID = d.Match_ID AND t.Period='All'
LEFT JOIN (SELECT DISTINCT match_id FROM fact_player_match_stats) p ON p.match_id = CAST(d.Match_ID AS TEXT)
LEFT JOIN (SELECT DISTINCT match_id FROM fact_shotmap) s ON s.match_id = CAST(d.Match_ID AS TEXT)
LEFT JOIN (SELECT DISTINCT match_id FROM silver_match_odds WHERE period='closing') o ON CAST(o.match_id AS TEXT) = CAST(d.Match_ID AS TEXT)
WHERE d.status='Finish' AND d.Date >= date('now', '-2 days')
GROUP BY d.Date ORDER BY d.Date DESC;
"""

DELAYED_FINISH_SQL = """
SELECT Match_ID, Date, Home_Team_Name, Away_Team_Name, status
FROM dim_match
WHERE status != 'Finish'
  AND Match_ID IN (SELECT match_id FROM report_store WHERE match_time < datetime('now', '-6 hours'))
ORDER BY Date DESC;
"""

RECENT_FAILURES_SQL = """
SELECT script_name, step, COUNT(*) AS n, MAX(created_at) AS last_seen
FROM ingest_failure_log
WHERE resolved = 0 AND created_at >= datetime('now', '-24 hours')
GROUP BY script_name, step ORDER BY n DESC;
"""

THRESHOLDS = {
    "team_stats":    ("CRITICAL", 0.95),
    "player_stats":  ("WARNING",  0.90),
    "shotmap":       ("WARNING",  0.80),
    "closing_odds":  ("WARNING",  0.80),
}

def pct(num, den):
    return round(num / den * 100, 1) if den else 0.0

def check_coverage(conn):
    alerts = []
    rows = conn.execute(COVERAGE_SQL).fetchall()
    log.info("=== 覆盖率矩阵（近 2 日 Finish）===")
    if not rows:
        log.info("  无 Finish 场次"); return alerts
    log.info(f"{'Date':<12}{'Fin':>6}{'Team%':>8}{'Player%':>10}{'Shot%':>8}{'CloseOdds%':>12}")
    for date_, fin, ts, ps, sm, co in rows:
        pcts = {"team_stats": pct(ts,fin), "player_stats": pct(ps,fin), "shotmap": pct(sm,fin), "closing_odds": pct(co,fin)}
        log.info(f"{date_:<12}{fin:>6}{pcts['team_stats']:>8}{pcts['player_stats']:>10}{pcts['shotmap']:>8}{pcts['closing_odds']:>12}")
        for k,(lvl,th) in THRESHOLDS.items():
            if pcts[k] < th*100:
                alerts.append((lvl, f"[{date_}] {k}={pcts[k]}% < {int(th*100)}% (fin={fin})"))
    return alerts

def check_delayed_finish(conn):
    alerts = []
    rows = conn.execute(DELAYED_FINISH_SQL).fetchall()
    log.info("=== 延迟 Finish 检测 ===")
    if not rows:
        log.info("  无延迟"); return alerts
    for mid,d,h,a,st in rows:
        msg = f"[{d}] {mid} {h} vs {a} status={st}"
        log.warning("  "+msg); alerts.append(("WARNING", f"delayed_finish: {msg}"))
    return alerts

def check_recent_failures(conn):
    alerts = []
    rows = conn.execute(RECENT_FAILURES_SQL).fetchall()
    log.info("=== 近 24h 未处理失败 ===")
    if not rows:
        log.info("  无"); return alerts
    for script,step,n,last in rows:
        msg = f"{script}/{step}: {n} failures, last={last}"
        log.warning("  "+msg)
        alerts.append(("CRITICAL" if n>=10 else "WARNING", f"ingest_failure: {msg}"))
    return alerts

def main():
    log.info(f"🩺 Daily Data Quality Report @ {datetime.now(timezone.utc).isoformat()}")
    log.info(f"DB: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        log.error(f"DB not found"); sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    try:
        alerts = check_coverage(conn) + check_delayed_finish(conn) + check_recent_failures(conn)
    finally:
        conn.close()
    log.info("="*60)
    if not alerts:
        log.info("✅ 全部指标正常"); return 0
    crit = [a for a in alerts if a[0]=="CRITICAL"]
    warn = [a for a in alerts if a[0]=="WARNING"]
    log.warning(f"⚠️ CRITICAL={len(crit)} WARNING={len(warn)}")
    for lvl,msg in alerts: log.warning(f"  [{lvl}] {msg}")
    try:
        from notify import send as notify_send
        summary_lines = [f"[{lvl}] {msg}" for lvl, msg in alerts]
        level = "CRITICAL" if crit else "WARNING"
        notify_send(
            title=f"数据质量报告 CRIT={len(crit)} WARN={len(warn)}",
            content="\n".join(summary_lines),
            level=level,
        )
    except Exception as e:
        log.warning(f"notify 调用失败（忽略）: {e}")
    return 0 if not crit else 2

if __name__ == "__main__":
    sys.exit(main())
