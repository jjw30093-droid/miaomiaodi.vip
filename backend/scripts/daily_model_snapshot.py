#!/usr/bin/env python3
"""Daily model-page snapshot — 聚合当日前端需要的所有数据，写 model_page_snapshot。

调度：pm2 cron `0 5 * * *` UTC (job-post-match-review 03:45 之后 1h15min)
"""
import os, sys, json, sqlite3, argparse, logging
from datetime import datetime, timezone, timedelta, date

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_env_db = os.environ.get("DB_PATH")
if _env_db:
    DB_PATH = _env_db
else:
    # 兼容两种部署形态：
    # - PROJECT_ROOT=/home/ubuntu/app        => backend/football_uk.db
    # - PROJECT_ROOT=/home/ubuntu/app/backend => football_uk.db
    candidate_1 = os.path.join(PROJECT_ROOT, "backend", "football_uk.db")
    candidate_2 = os.path.join(PROJECT_ROOT, "football_uk.db")
    DB_PATH = candidate_2 if os.path.exists(candidate_2) else candidate_1

MODELS_DIR = os.path.join(PROJECT_ROOT, "backend", "models_v4") if os.path.isdir(os.path.join(PROJECT_ROOT, "backend")) else os.path.join(PROJECT_ROOT, "models_v4")

# 让 import 能找到 backend/ 下的模块
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("model_snapshot")

WIN_RATE_THRESHOLD = 0.51   # 窗口胜率隐藏阈值
SAMPLE_FLOOR = 200          # 总样本量下限（低于此全页隐藏业绩数字）
BEST_WIN_MIN_DAYS = 7       # 择优窗口最小天数
BEST_WIN_MAX_DAYS = 90      # 择优窗口最大天数
BEST_WIN_MIN_SAMPLE = 20    # 择优窗口最小样本量

# ─── helpers ────────────────────────────────────────────────────────

def _single_pick_window(conn, days: int, as_of: date) -> dict:
    """近 N 天单推命中率/ROI，as_of 为快照日（含当天）。"""
    start = (as_of - timedelta(days=days - 1)).isoformat()
    rows = conn.execute("""
        SELECT picked_market, picked_direction, picked_odds, picked_confidence, picked_correct
        FROM prediction_audit
        WHERE picked_market IS NOT NULL
          AND match_date >= ? AND match_date <= ?
          AND actual_wdl IS NOT NULL
    """, (start, as_of.isoformat())).fetchall()
    settled = [r for r in rows if r[4] is not None]
    n = len(settled)
    hits = sum(1 for r in settled if r[4] == 1)
    hit_rate = hits / n if n else None
    pnl_rows = [r for r in settled if r[2]]
    pnl = sum((r[2] - 1) if r[4] == 1 else -1 for r in pnl_rows)
    roi = pnl / len(pnl_rows) if pnl_rows else None
    visible = hit_rate is not None and hit_rate >= WIN_RATE_THRESHOLD
    return {
        "window_days": days,
        "n_settled": n,
        "hits": hits,
        "hit_rate": hit_rate,
        "roi": roi,
        "visible": visible,
    }


def _best_showcase_window(conn, as_of: date) -> dict:
    """扫描 window(7-90) x market(all/ou/ah/ou+ah) 全组合，返回命中率最高的。

    用于模型页 Hero 卡片"择优展示"——自动选最佳窗口 × 市场组合。
    """
    MARKET_FILTERS = {
        "all":   None,             # 全市场
        "ou":    ("ou",),
        "ah":    ("ah",),
        "ou_ah": ("ou", "ah"),
    }
    MARKET_LABELS = {"all": "全部", "ou": "大小球", "ah": "让球", "ou_ah": "大小球+让球"}

    best_rate = -1.0
    best = None

    for mkt_key, mkt_filter in MARKET_FILTERS.items():
        for days in range(BEST_WIN_MIN_DAYS, BEST_WIN_MAX_DAYS + 1):
            start = (as_of - timedelta(days=days - 1)).isoformat()
            end = as_of.isoformat()
            if mkt_filter:
                placeholders = ",".join("?" * len(mkt_filter))
                row = conn.execute(f"""
                    SELECT COUNT(*) AS n,
                           SUM(CASE WHEN picked_correct=1 THEN 1 ELSE 0 END) AS hits
                    FROM prediction_audit
                    WHERE picked_market IN ({placeholders})
                      AND match_date >= ? AND match_date <= ?
                      AND actual_wdl IS NOT NULL AND picked_correct IS NOT NULL
                """, (*mkt_filter, start, end)).fetchone()
            else:
                row = conn.execute("""
                    SELECT COUNT(*) AS n,
                           SUM(CASE WHEN picked_correct=1 THEN 1 ELSE 0 END) AS hits
                    FROM prediction_audit
                    WHERE picked_market IS NOT NULL
                      AND match_date >= ? AND match_date <= ?
                      AND actual_wdl IS NOT NULL AND picked_correct IS NOT NULL
                """, (start, end)).fetchone()

            n, hits = row[0], row[1] or 0
            if n < BEST_WIN_MIN_SAMPLE:
                continue
            rate = hits / n
            # 同命中率时偏好更长窗口（样本更可靠）
            if rate > best_rate or (rate == best_rate and best and days > best["window_days"]):
                best_rate = rate
                best = {"window_days": days, "n_settled": n, "hits": hits,
                        "market": mkt_key, "hit_rate": rate}

    if not best:
        return {"window_days": 30, "n_settled": 0, "hits": 0, "market": "all",
                "hit_rate": None, "roi": None, "market_label": "全部"}

    # 计算最优组合的 ROI
    start = (as_of - timedelta(days=best["window_days"] - 1)).isoformat()
    end = as_of.isoformat()
    mkt_filter = MARKET_FILTERS[best["market"]]
    if mkt_filter:
        placeholders = ",".join("?" * len(mkt_filter))
        pnl_rows = conn.execute(f"""
            SELECT picked_odds, picked_correct FROM prediction_audit
            WHERE picked_market IN ({placeholders})
              AND match_date >= ? AND match_date <= ?
              AND actual_wdl IS NOT NULL AND picked_correct IS NOT NULL
              AND picked_odds IS NOT NULL
        """, (*mkt_filter, start, end)).fetchall()
    else:
        pnl_rows = conn.execute("""
            SELECT picked_odds, picked_correct FROM prediction_audit
            WHERE picked_market IS NOT NULL
              AND match_date >= ? AND match_date <= ?
              AND actual_wdl IS NOT NULL AND picked_correct IS NOT NULL
              AND picked_odds IS NOT NULL
        """, (start, end)).fetchall()

    pnl = sum((odds - 1) if correct == 1 else -1 for odds, correct in pnl_rows)
    roi = pnl / len(pnl_rows) if pnl_rows else None

    best["roi"] = roi
    best["market_label"] = MARKET_LABELS[best["market"]]
    return best


def _best_showcase_equity(conn, as_of: date, best_window: dict) -> list:
    """为择优窗口生成对应的净值曲线。"""
    days = best_window["window_days"]
    mkt = best_window.get("market", "all")
    start = (as_of - timedelta(days=days - 1)).isoformat()
    end = as_of.isoformat()

    MARKET_FILTERS = {"all": None, "ou": ("ou",), "ah": ("ah",), "ou_ah": ("ou", "ah")}
    mkt_filter = MARKET_FILTERS.get(mkt)

    if mkt_filter:
        placeholders = ",".join("?" * len(mkt_filter))
        rows = conn.execute(f"""
            SELECT match_date, picked_odds, picked_correct
            FROM prediction_audit
            WHERE picked_market IN ({placeholders})
              AND match_date >= ? AND match_date <= ?
              AND actual_wdl IS NOT NULL AND picked_correct IS NOT NULL
              AND picked_odds IS NOT NULL
            ORDER BY match_date ASC
        """, (*mkt_filter, start, end)).fetchall()
    else:
        rows = conn.execute("""
            SELECT match_date, picked_odds, picked_correct
            FROM prediction_audit
            WHERE picked_market IS NOT NULL
              AND match_date >= ? AND match_date <= ?
              AND actual_wdl IS NOT NULL AND picked_correct IS NOT NULL
              AND picked_odds IS NOT NULL
            ORDER BY match_date ASC
        """, (start, end)).fetchall()

    equity = 0.0
    by_date = {}
    for d, odds, correct in rows:
        delta = (odds - 1) if correct == 1 else -1
        equity += delta
        by_date[d] = equity
    return [{"date": d, "value": round(v, 4)} for d, v in sorted(by_date.items())]


def _single_pick_equity(conn, as_of: date, days: int = 60) -> list:
    """单推累计 PnL 曲线（每场单位注金 1，从 0 起累计盈亏）。"""
    start = (as_of - timedelta(days=days - 1)).isoformat()
    rows = conn.execute("""
        SELECT match_date, picked_odds, picked_correct
        FROM prediction_audit
        WHERE picked_market IS NOT NULL
          AND match_date >= ? AND match_date <= ?
          AND actual_wdl IS NOT NULL AND picked_correct IS NOT NULL
          AND picked_odds IS NOT NULL
        ORDER BY match_date ASC
    """, (start, as_of.isoformat())).fetchall()
    equity = 0.0
    by_date = {}
    for d, odds, correct in rows:
        delta = (odds - 1) if correct == 1 else -1
        equity += delta
        by_date[d] = equity
    return [{"date": d, "value": round(v, 4)} for d, v in sorted(by_date.items())]


def _direction_trend(conn, as_of: date, window: int = 30, series_days: int = 60) -> dict:
    """每日滑窗 window 天准确率，覆盖 as_of 前 series_days 天。返回 wdl/ou/ah 三序列 + current。"""
    def series_for(col: str, ah_min_sample: int = 0):
        pts = []
        for i in range(series_days):
            day = as_of - timedelta(days=series_days - 1 - i)
            start = (day - timedelta(days=window - 1)).isoformat()
            end = day.isoformat()
            row = conn.execute(f"""
                SELECT
                  SUM(CASE WHEN {col}=1 THEN 1 ELSE 0 END) AS hits,
                  SUM(CASE WHEN {col} IS NOT NULL THEN 1 ELSE 0 END) AS n
                FROM prediction_audit
                WHERE match_date >= ? AND match_date <= ?
            """, (start, end)).fetchone()
            hits, n = row[0] or 0, row[1] or 0
            acc = (hits / n) if n and n >= max(ah_min_sample, 1) else None
            pts.append({"date": end, "acc": acc, "n": n})
        return pts

    wdl = series_for("wdl_correct")
    ou = series_for("ou_correct")
    ah = series_for("ah_correct", ah_min_sample=10)

    def current_of(series):
        last = series[-1] if series else {"acc": None}
        acc = last.get("acc")
        hidden = (acc is None) or (acc < WIN_RATE_THRESHOLD)
        return {"acc": acc, "hidden": hidden,
                "reason": "win_rate<51" if (acc is not None and acc < WIN_RATE_THRESHOLD) else
                          ("insufficient_sample" if acc is None else None)}
    return {
        "wdl": wdl, "ou": ou, "ah": ah,
        "current": {"wdl": current_of(wdl), "ou": current_of(ou), "ah": current_of(ah)},
    }


def _calibration(conn, as_of: date, days: int = 90) -> list:
    start = (as_of - timedelta(days=days - 1)).isoformat()
    rows = conn.execute("""
        SELECT pred_wdl_home, wdl_correct
        FROM prediction_audit
        WHERE wdl_correct IS NOT NULL AND pred_wdl_home IS NOT NULL
          AND match_date >= ?
    """, (start,)).fetchall()
    bins = [[] for _ in range(10)]
    for p, c in rows:
        idx = min(int(p * 10), 9)
        bins[idx].append((p, c))
    out = []
    for i, bucket in enumerate(bins):
        if not bucket:
            continue
        n = len(bucket)
        out.append({
            "bin_center": round((i + 0.5) / 10, 2),
            "predicted": round(sum(x[0] for x in bucket) / n, 4),
            "actual":    round(sum(x[1] for x in bucket) / n, 4),
            "n": n,
        })
    return out


def _recent_single_picks(conn, as_of: date, n: int = 30) -> list:
    rows = conn.execute("""
        SELECT match_id, match_date, home_name, away_name,
               picked_market, picked_direction, picked_odds, picked_correct,
               picked_confidence, actual_home_score, actual_ou, actual_wdl
        FROM prediction_audit
        WHERE picked_market IS NOT NULL AND match_date <= ?
        ORDER BY match_date DESC, match_id DESC
        LIMIT ?
    """, (as_of.isoformat(), n)).fetchall()
    out = []
    for mid, d, h, a, mkt, direction, odds, correct, confidence, actual_score, actual_ou, actual_wdl in rows:
        if correct == 1:
            outcome, pnl = "hit", (odds - 1) if odds else None
        elif correct == 0:
            outcome, pnl = "miss", -1
        elif actual_score is not None:
            # 比赛已结算但 picked_correct=NULL，区分两种子情况
            if actual_ou == "push" or actual_wdl == "push":
                outcome, pnl = "push", 0      # 平注/退注
            else:
                outcome, pnl = "pending", None  # 审计尚未写入（极罕见）
        else:
            outcome, pnl = "pending", None   # 比赛尚未开踢
        out.append({
            "match_id": mid, "date": d, "home": h, "away": a,
            "market": mkt, "pick": direction, "odds": odds,
            "outcome": outcome, "pnl": pnl,
        })
    return out


def _training_meta() -> dict:
    meta_path = os.path.join(MODELS_DIR, "meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"meta.json 读取失败: {e}")
    return {}


def _drift_status(conn, as_of: date) -> dict:
    rows = conn.execute("""
        SELECT log_date, drift_alert FROM model_health_log
        WHERE log_date <= ? ORDER BY log_date DESC LIMIT 14
    """, (as_of.isoformat(),)).fetchall()
    adjusting_days = 0
    for _, alert in rows:
        if alert == 1:
            adjusting_days += 1
        else:
            break
    return {
        "status": "adjusting" if adjusting_days > 0 else "ok",
        "adjusting_days": adjusting_days,
    }


# ─── main ───────────────────────────────────────────────────────────

def build_payload(conn, as_of: date) -> dict:
    w7  = _single_pick_window(conn, 7, as_of)
    w14 = _single_pick_window(conn, 14, as_of)
    w30 = _single_pick_window(conn, 30, as_of)
    best = _best_showcase_window(conn, as_of)
    best_curve = _best_showcase_equity(conn, as_of, best)
    total_sample_row = conn.execute("SELECT COUNT(*) FROM prediction_audit WHERE actual_wdl IS NOT NULL").fetchone()
    total_sample = total_sample_row[0] if total_sample_row else 0
    cold_start = total_sample < SAMPLE_FLOOR
    log.info(f"  best_showcase: market={best.get('market')} window={best.get('window_days')}d "
             f"hit_rate={best.get('hit_rate', 0):.1%} roi={best.get('roi', 0):.2%}")
    return {
        "snapshot_date": as_of.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cold_start": cold_start,
        "total_settled": total_sample,
        "single_pick": {
            "w7": w7, "w14": w14, "w30": w30,
            "equity_curve": _single_pick_equity(conn, as_of),
            "best": best,
            "best_equity_curve": best_curve,
        },
        "direction_trend": _direction_trend(conn, as_of),
        "calibration": _calibration(conn, as_of),
        "recent_picks": _recent_single_picks(conn, as_of),
        "training_meta": _training_meta(),
        "drift": _drift_status(conn, as_of),
    }


def write_snapshot(conn, as_of: date, payload: dict):
    conn.execute("""
        INSERT OR REPLACE INTO model_page_snapshot (snapshot_date, generated_at, payload, schema_version)
        VALUES (?, ?, ?, 1)
    """, (as_of.isoformat(), payload["generated_at"], json.dumps(payload, ensure_ascii=False)))
    conn.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD，默认今天 UTC")
    ap.add_argument("--backfill-days", type=int, default=0, help="从今天往前回填 N 天")
    args = ap.parse_args()

    today = datetime.now(timezone.utc).date()
    target_dates = []
    if args.backfill_days > 0:
        for i in range(args.backfill_days):
            target_dates.append(today - timedelta(days=i))
    elif args.date:
        target_dates.append(date.fromisoformat(args.date))
    else:
        target_dates.append(today)

    if not os.path.exists(DB_PATH):
        log.error(f"DB not found: {DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    try:
        for d in target_dates:
            payload = build_payload(conn, d)
            write_snapshot(conn, d, payload)
            log.info(f"✅ snapshot written: {d.isoformat()} "
                     f"(settled={payload['total_settled']}, drift={payload['drift']['status']})")
    except Exception as e:
        log.error(f"snapshot 异常: {e}", exc_info=True)
        try:
            from scripts.ingest_failure_helper import record_failure
            record_failure("daily_model_snapshot", step="insert", error_msg=str(e))
        except Exception:
            pass
        sys.exit(2)
    finally:
        conn.close()

if __name__ == "__main__":
    main()

