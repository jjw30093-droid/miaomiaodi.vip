"""
drift_notifier.py — 模型漂移事件记录与通知

功能：
  - 写 model_drift_log 表（Phase 2 新增）
  - 推 Server 酱（限频：同一模型 24h 内最多推 1 次）
  - 不再污染 ingest_failure_log

用法（在 review_engine._auto_recalibrate 中）：
    from drift_notifier import record_drift_event
    record_drift_event(
        model_version="v5",
        wdl_acc=0.405, ou_acc=0.512, ah_acc=0.714,
        brier=0.222,
        window_size=50,
        triggered_metrics=["WDL"],
        recalibrate_pid=12345,
        status="spawned",
    )
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List

log = logging.getLogger(__name__)

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BACKEND_DIR, "football_uk.db"))

# 同一模型 24h 内最多推 1 次
_NOTIFY_COOLDOWN_HOURS = 24


def _get_conn(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _already_notified_today(conn, model_version: str) -> bool:
    """检查近 24h 内是否已推过本模型的漂移告警。"""
    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM model_drift_log
           WHERE model_version = ?
             AND triggered_at >= datetime('now', ?)""",
        (model_version, f"-{_NOTIFY_COOLDOWN_HOURS} hours"),
    ).fetchone()
    return bool(row and row["cnt"] > 0)


def record_drift_event(
    model_version: Optional[str],
    wdl_acc: Optional[float],
    ou_acc: Optional[float],
    ah_acc: Optional[float],
    brier: Optional[float],
    window_size: int,
    triggered_metrics: List[str],
    recalibrate_pid: Optional[int] = None,
    status: str = "spawned",
    notes: Optional[str] = None,
    db_path: str = DB_PATH,
) -> None:
    """
    记录模型漂移事件，推 Server 酱（24h 限频）。

    永不抛异常——失败仅 log.error，不影响调用方主流程。
    """
    try:
        conn = _get_conn(db_path)
        already_notified = _already_notified_today(conn, model_version or "unknown")

        # ── 写 model_drift_log ──────────────────────────────────────────
        conn.execute(
            """INSERT INTO model_drift_log
               (model_version, wdl_acc, ou_acc, ah_acc, brier_wdl,
                window_size, triggered_metrics, recalibrate_pid,
                recalibrate_status, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                model_version,
                wdl_acc,
                ou_acc,
                ah_acc,
                brier,
                window_size,
                json.dumps(triggered_metrics, ensure_ascii=False),
                recalibrate_pid,
                status,
                notes,
            ),
        )
        conn.commit()
        conn.close()

        log.info(
            f"[drift_notifier] 已写入 model_drift_log: mv={model_version} "
            f"WDL={wdl_acc:.1%} OU={ou_acc:.1%} AH={ah_acc:.1%} "
            f"pid={recalibrate_pid} status={status}"
        )

        # ── Server 酱推送（限频，已推过就跳过）────────────────────────────
        if already_notified:
            log.info(f"[drift_notifier] 近 {_NOTIFY_COOLDOWN_HOURS}h 内已推过 {model_version}，跳过 Server 酱")
            return

        _push_server_chan(
            model_version=model_version,
            wdl_acc=wdl_acc,
            ou_acc=ou_acc,
            ah_acc=ah_acc,
            brier=brier,
            triggered_metrics=triggered_metrics,
            recalibrate_pid=recalibrate_pid,
            status=status,
        )

    except Exception as e:
        log.error(f"[drift_notifier] record_drift_event 失败（忽略）: {e}", exc_info=True)


def _push_server_chan(
    model_version, wdl_acc, ou_acc, ah_acc, brier,
    triggered_metrics, recalibrate_pid, status,
) -> None:
    """推 Server 酱，失败仅 log.error 不抛出。"""
    try:
        from notify_utils import notify
    except ImportError:
        log.warning("[drift_notifier] notify_utils 未找到，跳过 Server 酱推送")
        return

    try:
        def _pct(v):
            return f"{v:.1%}" if v is not None else "N/A"

        metrics_str = "/".join(
            f"{m}={_pct(wdl_acc if m == 'WDL' else ou_acc if m == 'OU' else ah_acc)}"
            for m in triggered_metrics
        ) or "unknown"

        pid_str = f"pid={recalibrate_pid}" if recalibrate_pid else "pid=N/A"
        title = f"⚠️ 模型自动重训 | {model_version or 'unknown'}"
        body = (
            f"触发指标：{metrics_str}\n"
            f"全量指标：WDL={_pct(wdl_acc)} OU={_pct(ou_acc)} AH={_pct(ah_acc)}"
            + (f" brier={brier:.4f}" if brier is not None else "") + "\n"
            f"已派发 recalibrate.py（{pid_str}），状态: {status}\n"
            f"时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        notify(body, title=title)
        log.info(f"[drift_notifier] Server 酱推送成功：{title}")
    except Exception as e:
        log.error(f"[drift_notifier] Server 酱推送失败（忽略）: {e}")
