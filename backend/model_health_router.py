"""
GET /api/v1/model/health — 模型综合健康指标 API
需要登录（REGISTERED + VIP 均可访问），GUEST 返回 401。
"""
import json
import os
import sqlite3
import sys
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Response

from auth_deps import get_current_user, CurrentUser

# 把 backend 目录加入 sys.path 以便 import post_match_review
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

router = APIRouter(prefix="/api/v1/model", tags=["model"])

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH         = os.environ.get("DB_PATH", os.path.join(_THIS_DIR, "football_uk.db"))
EQUITY_JSON     = os.path.join(_THIS_DIR, "models_v4", "equity_curves.json")
META_JSON       = os.path.join(_THIS_DIR, "models_v4", "meta.json")


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _latest_training() -> dict:
    """Build latest_training block from meta.json + model_training_snapshot."""
    meta: dict = {}
    if os.path.exists(META_JSON):
        with open(META_JSON) as f:
            meta = json.load(f)

    conn = _db()
    row = conn.execute("""
        SELECT trained_at, sample_count, accuracy, brier, auc, features_n
        FROM model_training_snapshot
        WHERE model_name = 'wdl'
        ORDER BY trained_at DESC LIMIT 1
    """).fetchone()
    conn.close()

    trained_at   = meta.get("trained_at") or (row["trained_at"] if row else None)
    sample_count = meta.get("n_samples") or (row["sample_count"] if row else 0)
    features_n   = len(meta.get("features", [])) or (row["features_n"] if row else 0)
    accuracy     = row["accuracy"] if row else None
    brier        = row["brier"] if row else None
    auc          = row["auc"] if row else None

    return {
        "trained_at":   trained_at,
        "sample_count": sample_count,
        "accuracy":     round(accuracy, 4) if accuracy else None,
        "auc":          round(auc, 4) if auc else None,
        "brier":        round(brier, 4) if brier else None,
        "features_n":   features_n,
        "model_versions": {"wdl": "v4", "ou": "v4", "ah": "v1"},
    }


def _rolling() -> dict:
    """Build rolling block directly from prediction_audit (last 30 days)."""
    conn = _db()

    # WDL + OU accuracy and Brier from prediction_audit (ground truth)
    stats = conn.execute("""
        SELECT
          COUNT(*)                                                              AS n,
          CAST(SUM(CASE WHEN wdl_correct=1 THEN 1 ELSE 0 END) AS REAL) / COUNT(*) AS wdl_acc,
          CAST(SUM(CASE WHEN ou_correct=1  THEN 1 ELSE 0 END) AS REAL) /
            NULLIF(SUM(CASE WHEN ou_correct IS NOT NULL THEN 1 ELSE 0 END),0)  AS ou_acc,
          AVG(brier_wdl)                                                        AS brier_wdl,
          AVG(brier_ou)                                                         AS brier_ou,
          MAX(drift_alert)                                                       AS drift_alert
        FROM (
          SELECT pa.wdl_correct, pa.ou_correct, pa.brier_wdl, pa.brier_ou,
                 mh.drift_alert
          FROM prediction_audit pa
          LEFT JOIN model_health_log mh ON mh.log_date = date('now')
          WHERE pa.match_date >= date('now', '-30 days')
            AND pa.wdl_correct IS NOT NULL
        )
    """).fetchone()

    # AH accuracy — only report when sample >= 10 to avoid noise
    ah = conn.execute("""
        SELECT
          COUNT(*)                                                              AS n,
          CAST(SUM(CASE WHEN ah_correct=1 THEN 1 ELSE 0 END) AS REAL) / COUNT(*) AS ah_acc
        FROM prediction_audit
        WHERE ah_correct IS NOT NULL AND ah_correct != -1
          AND match_date >= date('now', '-30 days')
    """).fetchone()
    conn.close()

    n = stats["n"] or 0
    ah_n   = ah["n"] if ah else 0
    ah_acc = round(ah["ah_acc"], 4) if (ah and ah["ah_acc"] and ah_n >= 10) else None

    # Drift: flag if WDL accuracy drops below 50%
    wdl_acc = stats["wdl_acc"]
    drift   = bool(wdl_acc and wdl_acc < 0.50)

    return {
        "window":        30,
        "wdl_accuracy":  round(wdl_acc, 4)          if wdl_acc          else None,
        "ou_accuracy":   round(stats["ou_acc"], 4)  if stats["ou_acc"]  else None,
        "ah_accuracy":   ah_acc,   # None when n < 10
        "ah_sample_n":  ah_n,
        "brier_wdl":     round(stats["brier_wdl"], 4) if stats["brier_wdl"] else None,
        "brier_ou":      round(stats["brier_ou"],  4) if stats["brier_ou"]  else None,
        "total_matches": n,
        "drift_alert":   drift,
    }


def _equity() -> dict:
    """Read equity block from equity_curves.json."""
    if not os.path.exists(EQUITY_JSON):
        return {}
    with open(EQUITY_JSON) as f:
        data = json.load(f)
    # New schema has equity.fixed + equity.kelly_half
    if "equity" in data:
        return data["equity"]
    return {}


def _recent_picks(n: int = 14) -> list:
    """Return recent N days of picks from prediction_audit."""
    cutoff = (date.today() - timedelta(days=n)).isoformat()
    conn = _db()
    rows = conn.execute("""
        SELECT match_id, match_date, home_name, away_name,
               pred_wdl_pick, odds_final_home, odds_final_draw, odds_final_away,
               wdl_correct, pred_ou_pick, ou_correct,
               pred_ah_pick, ah_correct, pred_ah_line
        FROM prediction_audit
        WHERE match_date >= ?
        ORDER BY match_date DESC
    """, (cutoff,)).fetchall()
    conn.close()

    result = []
    for r in rows:
        pick_type = r["pred_wdl_pick"] or r["pred_ou_pick"] or r["pred_ah_pick"]
        correct   = r["wdl_correct"] if r["wdl_correct"] is not None else r["ou_correct"]
        if correct == 1:
            outcome = "hit"
        elif correct == 0:
            outcome = "miss"
        else:
            outcome = "pending"

        if r["pred_wdl_pick"] == "home":
            odds = r["odds_final_home"]
        elif r["pred_wdl_pick"] == "away":
            odds = r["odds_final_away"]
        elif r["pred_wdl_pick"] == "draw":
            odds = r["odds_final_draw"]
        else:
            odds = None

        pnl = round((odds - 1.0), 3) if (correct == 1 and odds) else (-1.0 if correct == 0 else 0)

        result.append({
            "match_id": r["match_id"],
            "date":     r["match_date"],
            "home":     r["home_name"],
            "away":     r["away_name"],
            "pick":     pick_type,
            "odds":     odds,
            "outcome":  outcome,
            "pnl":      pnl,
        })
    return result


def _calibration() -> list:
    """Build 10-bin reliability data from prediction_audit."""
    conn = _db()
    rows = conn.execute("""
        SELECT pred_wdl_home, wdl_correct
        FROM prediction_audit
        WHERE pred_wdl_home IS NOT NULL AND wdl_correct IS NOT NULL
    """).fetchall()
    conn.close()

    if not rows:
        return []

    bins = [[] for _ in range(10)]
    for r in rows:
        p = r["pred_wdl_home"]
        idx = min(int(p * 10), 9)
        bins[idx].append((p, r["wdl_correct"]))

    result = []
    for i, bucket in enumerate(bins):
        if not bucket:
            continue
        n = len(bucket)
        predicted = sum(p for p, _ in bucket) / n
        actual    = sum(c for _, c in bucket) / n
        result.append({
            "bin_center": round((i + 0.5) / 10, 2),
            "predicted":  round(predicted, 4),
            "actual":     round(actual, 4),
            "n":          n,
        })
    return result


def _single_pick() -> dict:
    """Return single_pick stats for 7d and 30d windows via compute_single_pick_stats."""
    try:
        from post_match_review import compute_single_pick_stats
        conn = _db()
        try:
            stats_7  = compute_single_pick_stats(conn, days=7)
            stats_30 = compute_single_pick_stats(conn, days=30)
        finally:
            conn.close()
        return {"w7": stats_7, "w30": stats_30}
    except Exception as e:
        return {"w7": None, "w30": None, "error": str(e)}


@router.get("/health")
def model_health(response: Response, _user: CurrentUser = Depends(get_current_user)):
    response.headers["X-Deprecated"] = "use /api/v1/model/snapshot"
    return {
        "latest_training": _latest_training(),
        "rolling":         _rolling(),
        "equity":          _equity(),
        "recent_picks":    _recent_picks(14),
        "calibration":     _calibration(),
        "single_pick":     _single_pick(),
    }


import json as _json
from fastapi import HTTPException


@router.get("/snapshot")
def model_snapshot(date: str = "latest", _user: CurrentUser = Depends(get_current_user)):
    """读取 model_page_snapshot；找不到时降级到 live 聚合（返回 {..., "degraded": true}）。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if date == "latest":
            row = conn.execute(
                "SELECT payload FROM model_page_snapshot ORDER BY snapshot_date DESC LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT payload FROM model_page_snapshot WHERE snapshot_date = ?", (date,)
            ).fetchone()
        if row:
            payload = _json.loads(row["payload"])
            payload["degraded"] = False
            return payload
    finally:
        conn.close()

    # fallback — 调用原 /health 实现的 6 个子函数拼一个最小兼容 payload
    return {
        "snapshot_date": None,
        "generated_at": None,
        "degraded": True,
        "single_pick": _single_pick(),
        "direction_trend": None,     # live 模式下暂不算（避免慢查询）
        "calibration": _calibration(),
        "recent_picks": _recent_picks(14),
        "training_meta": _latest_training(),
        "drift": {"status": "unknown", "adjusting_days": 0},
    }
