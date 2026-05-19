"""轻量 helper：向 ingest_failure_log 写一行失败记录，P0 级别同时推 Server 酱。

设计原则：
- 永不抛异常（日志记录失败不应影响主流程）
- 自己管理连接，避免与主流程共享 cursor
- P0 步骤通过 notify_utils.notify() 推 Server 酱（SERVERCHAN_KEY 必须在 .env 配置）

P0 步骤白名单（触发推送）：
    sanity_check, target_coverage_gap, league_coverage_regression,
    weekend_prefetch, drift_auto_recalibrate, pipeline_healthcheck
"""

import logging
import os
import sqlite3

log = logging.getLogger(__name__)

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_env_db = os.environ.get("DB_PATH")
if _env_db:
    DB_PATH = _env_db
else:
    # 兼容两种部署形态：
    # - /home/ubuntu/app/        + backend/football_uk.db
    # - /home/ubuntu/app/backend + football_uk.db
    candidate_1 = os.path.join(PROJECT_ROOT, "backend", "football_uk.db")
    candidate_2 = os.path.join(PROJECT_ROOT, "football_uk.db")
    DB_PATH = candidate_2 if os.path.exists(candidate_2) else candidate_1

# P0 步骤：触发 Server 酱推送
# 注意：drift_auto_recalibrate 已从此处移除（2026-05-16）
# 漂移事件改由 drift_notifier.record_drift_event() 写 model_drift_log + 推 Server 酱，
# 不再污染 ingest_failure_log（Phase 2 重构）。
_P0_STEPS = frozenset({
    "sanity_check",
    "target_coverage_gap",
    "league_coverage_regression",
    "weekend_prefetch",
    "pipeline_healthcheck",
})


def _notify_p0(script_name: str, step: str, error_msg: str) -> None:
    """P0 告警推 Server 酱，失败仅 log.error 不抛出。"""
    try:
        import sys
        sys.path.insert(0, PROJECT_ROOT)
        from notify_utils import notify
        title = f"🚨 Pipeline P0 告警 [{step}]"
        desp = f"**脚本**: {script_name}\n**步骤**: {step}\n**错误**: {error_msg[:800]}"
        notify(desp, title=title)
    except Exception as e:
        log.error(f"P0 Server酱推送失败（忽略）: {e}")


def record_failure(script_name: str, match_id=None, step: str = "fetch", error_msg: str = ""):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute(
            "INSERT INTO ingest_failure_log (script_name, match_id, step, error_msg) VALUES (?, ?, ?, ?)",
            (script_name, str(match_id) if match_id is not None else None, step, str(error_msg)[:2000]),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"record_failure 自身失败（忽略）: {e}")

    # P0 步骤额外推 Server 酱（落盘后再推，推失败不影响落盘已完成）
    if step in _P0_STEPS:
        _notify_p0(script_name, step, str(error_msg))

