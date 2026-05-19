"""
check_recalib_trigger.py — 样本数累积型自动触发器（2026-05-04 落地）
=================================================================

为什么存在：用户期望"满 200 场样本就自动 recalibrate"，但代码里此前并无该分支。
review_engine.check_drift 只看最近 50 场胜率，不计累积；recalibrate.py 只在周一 cron 跑。
结果 4/14 ~ 5/4 累积了 289 场仍未触发，calibrators.pkl 一直停在 4/14 版本。

工作方式
--------
- pm2 每日 03:35 UTC 跑（紧贴 03:30 post_match_review 之后）
- 读 models_v4/calibration.json 的 updated_at 作为"上次 recalibrate 完成时戳"
- COUNT(*) prediction_audit WHERE actual_wdl IS NOT NULL AND audit_time > 上次时戳
- 满 TRIGGER_SAMPLES=200 → subprocess 调 `python -m recalibrate`
- 同步写一条 ingest_failure_log（step='auto_recalibrate', resolved=1）作为审计

参考：CLAUDE.md §15 cron 顺序铁律（read prediction_audit.actual_*≥04:00 UTC）。
本脚本读 audit_time 但不修改 prediction_audit，03:35 安全（在 03:30 audit 写入之后）。
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))
CALIB_JSON = os.path.join(PROJECT_ROOT, "models_v4", "calibration.json")

TRIGGER_SAMPLES = int(os.environ.get("RECALIB_TRIGGER_SAMPLES", "200"))


def last_recalib_ts() -> str:
    """读 calibration.json 的 updated_at（recalibrate 跑完会被刷新）。
    缺失或解析失败时返回 1970-01-01（永远满足触发条件，但实际不会，因为 fit_league_offsets 也会写）。"""
    try:
        with open(CALIB_JSON, "r") as f:
            data = json.load(f)
        ts = data.get("updated_at")
        if ts:
            # 兼容 "2026-05-04T05:00:00.599007" / "2026-05-04T05:00:00.599007+00:00"
            return ts
    except Exception:
        pass
    return "1970-01-01T00:00:00"


def settled_since(ts: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        # audit_time 是 prediction_audit 的写入时戳（post_match_review 写入），用 > 严格
        cur = conn.execute(
            """
            SELECT COUNT(*) FROM prediction_audit
            WHERE actual_wdl IS NOT NULL
              AND audit_time IS NOT NULL
              AND audit_time > ?
            """,
            (ts,),
        )
        return cur.fetchone()[0]
    finally:
        conn.close()


def record_audit_entry(n_samples: int, last_ts: str, action: str):
    """写 ingest_failure_log 一条（resolved=1，作为审计痕迹而非告警）。"""
    try:
        from scripts.ingest_failure_helper import record_failure
        record_failure(
            "check_recalib_trigger",
            step="auto_recalibrate" if action == "triggered" else "no_op",
            error_msg=f"action={action} n_samples_since_{last_ts}={n_samples} threshold={TRIGGER_SAMPLES}",
        )
        # 立刻把它标记为 resolved（这是审计而非问题）
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                "UPDATE ingest_failure_log SET resolved=1 "
                "WHERE script_name='check_recalib_trigger' "
                "  AND created_at >= datetime('now', '-1 minutes') "
                "  AND resolved=0"
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[WARN] record_audit_entry failed: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印判定结果，不执行 recalibrate")
    parser.add_argument("--threshold", type=int, default=None,
                        help="覆盖 TRIGGER_SAMPLES（默认 200）")
    args = parser.parse_args()
    threshold = args.threshold or TRIGGER_SAMPLES

    last_ts = last_recalib_ts()
    n = settled_since(last_ts)
    print(f"[check_recalib_trigger] last_recalib_ts={last_ts}")
    print(f"[check_recalib_trigger] settled_samples_since={n}  threshold={threshold}")

    if n < threshold:
        print(f"[check_recalib_trigger] ⏸  累积 {n} < {threshold}，不触发")
        if not args.dry_run:
            record_audit_entry(n, last_ts, action="no_op")
        return 0

    print(f"[check_recalib_trigger] 🔔 累积 {n} ≥ {threshold}，触发 recalibrate")
    if args.dry_run:
        print("[check_recalib_trigger] DRY-RUN 跳过 subprocess")
        return 0

    record_audit_entry(n, last_ts, action="triggered")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "recalibrate"],
            cwd=PROJECT_ROOT,
            timeout=180,
            capture_output=True,
            text=True,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            print(f"[check_recalib_trigger] ❌ recalibrate exit={result.returncode}", file=sys.stderr)
            try:
                from scripts.ingest_failure_helper import record_failure
                record_failure("check_recalib_trigger", step="recalibrate_subprocess_failed",
                               error_msg=f"exit={result.returncode}: {result.stderr[:500]}")
            except Exception:
                pass
            return result.returncode
        print("[check_recalib_trigger] ✅ recalibrate 完成")
        return 0
    except subprocess.TimeoutExpired:
        print("[check_recalib_trigger] ❌ recalibrate timeout (180s)", file=sys.stderr)
        try:
            from scripts.ingest_failure_helper import record_failure
            record_failure("check_recalib_trigger", step="recalibrate_timeout",
                           error_msg="subprocess timed out after 180s")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
