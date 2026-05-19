"""
post_match_review.py
====================
赛后复盘脚本：将昨日已完赛且有预测记录的比赛写入 audit 结果，
检查模型漂移，输出复盘摘要。

用法：
    python post_match_review.py               # 复盘昨天
    python post_match_review.py --date 2026-04-06  # 复盘指定日期
    python post_match_review.py --days 7      # 复盘近7天（补录）
    python post_match_review.py --recompute   # Phase 2: 用新 ou_line 重算全部已审计行（幂等）
"""

import sys, os, json, argparse, sqlite3, logging
from datetime import datetime, date, timedelta

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from review_engine import ReviewEngine
from bankroll_simulator import BacktestSimulator, print_backtest_report
from scripts.ingest_failure_helper import record_failure
from pick_parser import parse_inference

DB_PATH   = os.path.join(PROJECT_ROOT, "football_uk.db")
MODEL_DIR = os.path.join(PROJECT_ROOT, "models_v4")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def reconcile_missing_picks(conn, days: int = 14) -> int:
    """CLAUDE.md §16 自愈：扫描 picked_market IS NULL 但 inference 已存在的行，
    用 pick_parser 反解后补写。在 audit 主流程之前调用，让 audit_match 后续能
    正常计算 picked_correct（review_engine.py:353 要求 picked_market 非空）。
    返回补写的行数。
    """
    # CLAUDE.md §18：补 picks 后立即回算 picked_correct（已完赛场次）
    from pick_parser import compute_picked_correct
    rows = conn.execute(f"""
        SELECT pa.match_id, rs.inference, pa.pred_ah_line, pa.pred_ou_line,
               d.status, d.home_score, d.away_score
        FROM prediction_audit pa
        JOIN report_store rs ON CAST(rs.match_id AS TEXT) = CAST(pa.match_id AS TEXT)
        LEFT JOIN dim_match d ON CAST(d.Match_ID AS TEXT) = CAST(pa.match_id AS TEXT)
        WHERE pa.match_date >= date('now', '-{days} days')
          AND pa.picked_market IS NULL
          AND rs.inference IS NOT NULL
          AND TRIM(rs.inference) != ''
    """).fetchall()
    fixed = 0
    for r in rows:
        mid = r["match_id"]
        inf = r["inference"]
        parsed = parse_inference(inf)
        if not parsed:
            log.error(f"[reconcile] 无法解析 inference, mid={mid}: {inf[:80]}")
            record_failure("post_match_review", match_id=mid,
                           step="reconcile_parse_failed", error_msg=inf[:500])
            continue
        picked_correct = None
        if r["status"] == "Finish" and r["home_score"] is not None:
            picked_correct = compute_picked_correct(
                parsed["market"], parsed["direction"],
                r["home_score"], r["away_score"],
                r["pred_ah_line"], r["pred_ou_line"],
            )
        conn.execute("""
            UPDATE prediction_audit SET
                picked_market    = ?,
                picked_direction = ?,
                picked_odds      = ?,
                picked_confidence= ?,
                picked_correct   = COALESCE(picked_correct, ?)
            WHERE match_id = ? AND picked_market IS NULL
        """, (parsed["market"], parsed["direction"], parsed.get("odds"),
              parsed.get("confidence"), picked_correct, mid))
        fixed += 1
        log.error(f"[reconcile] 补写 mid={mid}: {parsed['market']}/{parsed['direction']} correct={picked_correct}")
        record_failure("post_match_review", match_id=mid,
                       step="reconcile_backfilled",
                       error_msg=f"{parsed['market']}/{parsed['direction']} correct={picked_correct}")
    if fixed > 0:
        conn.commit()
    return fixed


def reconcile_missing_audit(conn, review: 'ReviewEngine', days: int = 14) -> int:
    """§17 事故 #6 自愈：扫描已完赛但 actual_wdl IS NULL 的行，立即调 audit_match() 补算。
    在 reconcile_missing_picks 之后、run_review_for_date 之前调用，确保所有 dim_match 有
    分数的场次都进入 audit 状态。返回补算的行数。
    """
    rows = conn.execute(f"""
        SELECT pa.match_id
        FROM prediction_audit pa
        INNER JOIN dim_match d ON CAST(d.Match_ID AS TEXT) = CAST(pa.match_id AS TEXT)
        WHERE pa.match_date >= date('now', '-{days} days')
          AND pa.actual_wdl IS NULL
          AND d.status = 'Finish'
          AND d.home_score IS NOT NULL
    """).fetchall()
    fixed = 0
    for r in rows:
        mid = str(r["match_id"])
        try:
            review.audit_match(mid)
            fixed += 1
        except Exception as e:
            log.error(f"[reconcile_audit] audit_match 失败 mid={mid}: {e}")
            record_failure("post_match_review", match_id=mid,
                           step="reconcile_audit", error_msg=str(e))
    if fixed > 0:
        log.error(f"[reconcile_audit] ⚠️ 补算 {fixed} 场 actual_*（cron 顺序回归或 audit 漏跑）")
    return fixed


def get_finished_matches(conn, target_date: str) -> list:
    """取预测日期已完赛且待审计的比赛（用 pa.match_date 驱动，避免 UTC/CST 日期错位）"""
    rows = conn.execute("""
        SELECT d.Match_ID, d.Home_Team_Name, d.Away_Team_Name,
               d.home_score, d.away_score, d.Date
        FROM prediction_audit pa
        INNER JOIN dim_match d ON d.Match_ID = pa.match_id
        WHERE pa.match_date = ?
          AND pa.actual_wdl IS NULL
          AND d.status = 'Finish'
          AND d.home_score IS NOT NULL
    """, (target_date,)).fetchall()

    pending = conn.execute("""
        SELECT COUNT(*) FROM prediction_audit pa
        INNER JOIN dim_match d ON d.Match_ID = pa.match_id
        WHERE pa.match_date = ?
          AND pa.actual_wdl IS NULL
          AND (d.status != 'Finish' OR d.home_score IS NULL)
    """, (target_date,)).fetchone()[0]
    if pending > 0:
        log.error(
            f"[{target_date}] ⚠️ {pending} 场已有 prediction_audit 但 dim_match 缺分数，"
            f"可能 batch-sync 还没跑或失败 — 检查 job-batch-sync 日志（CLAUDE.md §15）"
        )
    return rows


def recompute_all_audited(conn) -> int:
    """
    --recompute 模式：对所有已审计行用 pred_ou_line 重算 actual_ou / ou_correct / brier_ou。
    直接调用 db_migrate_phase2.step_recompute_audit，幂等安全。
    """
    try:
        from db_migrate_phase2 import step_recompute_audit
        step_recompute_audit(conn)
        rows = conn.execute(
            "SELECT COUNT(*) FROM prediction_audit WHERE actual_wdl IS NOT NULL"
        ).fetchone()[0]
        return rows
    except Exception as e:
        log.warning(f"  ⚠️ --recompute 失败: {e}")
        return 0


def _read_audited_summary(conn, target_date: str) -> dict:
    """从 prediction_audit 读取指定日期已审计比赛的汇总统计（供 run_review_for_date 回退用）。
    修复：reconcile_missing_audit 先跑完会让 get_finished_matches 返回空列表，
    导致 summaries count=0，Server 酱推送显示"三方向独立 合计 0 場"。"""
    row = conn.execute("""
        SELECT COUNT(*) AS n,
               SUM(wdl_correct) AS wdl_c,
               SUM(CASE WHEN ou_correct IS NOT NULL THEN ou_correct ELSE 0 END) AS ou_c
        FROM prediction_audit
        WHERE match_date = ?
          AND actual_wdl IS NOT NULL
    """, (target_date,)).fetchone()
    total = row["n"] or 0
    wdl_c = row["wdl_c"] or 0
    ou_c  = row["ou_c"]  or 0
    return {
        "date":        target_date,
        "count":       total,
        "wdl_correct": wdl_c,
        "ou_correct":  ou_c,
        "wdl_acc":     round(wdl_c / total, 3) if total > 0 else None,
        "ou_acc":      round(ou_c  / total, 3) if total > 0 else None,
        "_from_db":    True,   # 标记：统计来自 DB 读取（非本次新审计）
    }


def run_review_for_date(review: ReviewEngine, conn, target_date: str) -> dict:
    matches = get_finished_matches(conn, target_date)
    if not matches:
        # reconcile_missing_audit 可能已经把当日 actual_wdl IS NULL 的行全部补算完了，
        # 此时直接读 DB 里已审计的结果作为 summary，避免 Server 酱显示"合计 0 场"。
        fallback = _read_audited_summary(conn, target_date)
        if fallback["count"] > 0:
            log.info(
                f"[{target_date}] 所有比赛已由 reconcile 补审计，"
                f"从 DB 读取汇总：{fallback['count']} 场"
            )
        else:
            log.info(f"[{target_date}] 无待复盘比赛（已全部复盘或无预测记录）")
        return fallback

    wdl_correct = 0
    ou_correct  = 0
    total       = 0

    for row in matches:
        mid = str(row[0])
        try:
            review.audit_match(mid)
            # 读取复盘结果（ou_correct 可能为 NULL in push 场景）
            result = conn.execute(
                "SELECT wdl_correct, ou_correct FROM prediction_audit WHERE match_id=?", (mid,)
            ).fetchone()
            if result:
                wdl_correct += result[0] or 0
                ou_correct  += result[1] or 0  # push 场景 result[1]=None → 0（不计入）
                total += 1
            log.info(f"  ✅ 复盘完成: {row[1]} vs {row[2]}  ({row[3]}:{row[4]})")
        except Exception as e:
            log.warning(f"  ⚠️ 复盘失败 {mid}: {e}")
            record_failure("post_match_review", match_id=mid, step="audit", error_msg=str(e))

    return {
        "date":        target_date,
        "count":       total,
        "wdl_correct": wdl_correct,
        "ou_correct":  ou_correct,
        "wdl_acc":     round(wdl_correct / total, 3) if total > 0 else None,
        "ou_acc":      round(ou_correct  / total, 3) if total > 0 else None,
    }


def compute_single_pick_stats(conn, days: int = 14) -> dict:
    """
    B4 主指标：single_pick 命中率 + 按置信度/市场分层 + ROI。
    只统计最近 `days` 天已审计（picked_correct IS NOT NULL 或 SKIP）的行。
    """
    rows = conn.execute(f"""
        SELECT picked_market, picked_direction, picked_odds, picked_confidence,
               picked_correct
        FROM prediction_audit
        WHERE picked_market IS NOT NULL
          AND match_date >= date('now', '-{days} days')
          AND actual_wdl IS NOT NULL
    """).fetchall()

    # picked_correct 语义：1=赢 / 0=输 / -1=走水 / None=未结算
    pushes  = [r for r in rows if r["picked_correct"] == -1]
    settled = [r for r in rows if r["picked_correct"] in (0, 1)]
    skipped = [r for r in rows if r["picked_confidence"] == "SKIP"]
    n = len(settled)
    hits = sum(1 for r in settled if r["picked_correct"] == 1)
    hit_rate = hits / n if n else None

    # ROI：赢则净赚 odds-1，输则 -1；走水不计入（本金返还）；无赔率的行不计入
    roi_rows = [r for r in settled if r["picked_odds"]]
    if roi_rows:
        pnl = sum(
            (r["picked_odds"] - 1) if r["picked_correct"] == 1 else -1
            for r in roi_rows
        )
        roi = pnl / len(roi_rows)
    else:
        roi = None

    # 按置信度分层（走水不计入胜负，但计入场次 n_push）
    by_conf = {}
    for conf in ("HIGH", "MID", "LOW"):
        sub = [r for r in settled if r["picked_confidence"] == conf]
        if sub:
            h = sum(1 for r in sub if r["picked_correct"] == 1)
            by_conf[conf] = {"n": len(sub), "hits": h, "acc": h / len(sub)}

    # 按市场分层（走水不计入胜负）
    by_market = {}
    for mkt in ("wdl", "ou", "ah"):
        sub = [r for r in settled if r["picked_market"] == mkt]
        if sub:
            h = sum(1 for r in sub if r["picked_correct"] == 1)
            by_market[mkt] = {"n": len(sub), "hits": h, "acc": h / len(sub)}

    # CLAUDE.md §16/§17: 已完赛但 picked_market 缺失 → 必须告警
    # 业务前提：每场收费 → 前端必显推荐 → 复盘必出对错。NULL > 0 即违反不变量。
    n_missing_pick = conn.execute(f"""
        SELECT COUNT(*) FROM prediction_audit pa
        JOIN dim_match d ON CAST(d.Match_ID AS TEXT) = CAST(pa.match_id AS TEXT)
        WHERE pa.picked_market IS NULL
          AND pa.match_date >= date('now', '-{days} days')
          AND d.status = 'Finish'
          AND d.home_score IS NOT NULL
    """).fetchone()[0]

    return {
        "window_days":    days,
        "n_settled":      n,
        "n_push":         len(pushes),       # 走水场次（本金返还，不计胜负）
        "n_skipped":      len(skipped),
        "n_missing_pick": n_missing_pick,
        "hits":           hits,
        "hit_rate":       hit_rate,
        "roi":            roi,
        "by_conf":        by_conf,
        "by_market":      by_market,
    }


def print_summary(summaries: list, drift: dict, pick_stats: dict = None):
    print("\n" + "="*55)
    print("  赛后复盘摘要")
    print("="*55)
    total_matches = sum(s["count"] for s in summaries)
    total_wdl_c   = sum(s.get("wdl_correct", 0) for s in summaries)
    total_ou_c    = sum(s.get("ou_correct", 0)  for s in summaries)

    for s in summaries:
        if s["count"] == 0:
            print(f"  {s['date']}: 无复盘场次")
        else:
            print(f"  {s['date']}: {s['count']}场  WDL准确率={s['wdl_acc']:.1%}  OU准确率={s['ou_acc']:.1%}")

    if total_matches > 0:
        print(f"\n  合计: {total_matches}场")
        print(f"  WDL准确率: {total_wdl_c/total_matches:.1%}  OU准确率: {total_ou_c/total_matches:.1%}")

    # ── 不变量告警：picked_market 缺失（CLAUDE.md §16/§17）──
    if pick_stats and pick_stats.get("n_missing_pick", 0) > 0:
        n_miss = pick_stats["n_missing_pick"]
        print(
            f"\n  ❌ {n_miss} 场已完赛但 picked_market 缺失（违反"
            f"\"用户付费必出推荐\"铁律）"
        )
        print(
            f"     → 请检查 reconcile 日志或跑 backfill_missing_picks.py 排查"
        )

    # ── B4 主指标：single_pick 命中率 ──
    if pick_stats and pick_stats.get("n_settled"):
        ps = pick_stats
        print(f"\n  🎯 单推命中率（近 {ps['window_days']} 天）")
        hr = ps["hit_rate"]
        roi_str = f"{ps['roi']*100:+.1f}%" if ps["roi"] is not None else "N/A"
        push_str = f"  走水: {ps['n_push']}" if ps.get("n_push") else ""
        print(f"     整体: {ps['hits']}/{ps['n_settled']} = {hr:.1%}  ROI={roi_str}"
              f"  (SKIP: {ps['n_skipped']}{push_str})")
        if ps["by_conf"]:
            print(f"     按置信度:")
            for c in ("HIGH", "MID", "LOW"):
                if c in ps["by_conf"]:
                    b = ps["by_conf"][c]
                    print(f"       {c:5s}  {b['hits']:3d}/{b['n']:3d}  {b['acc']:.1%}")
        if ps["by_market"]:
            print(f"     按市场:")
            for m in ("wdl", "ou", "ah"):
                if m in ps["by_market"]:
                    b = ps["by_market"][m]
                    print(f"       {m:4s}   {b['hits']:3d}/{b['n']:3d}  {b['acc']:.1%}")

    print("\n  模型漂移检测:")
    if drift.get("status") == "insufficient_data":
        print("  ⚪ 数据不足（<20场），暂无漂移判断")
    elif drift.get("drift"):
        wdl_acc = drift.get("wdl_acc")
        ou_acc = drift.get("ou_acc")
        brier_wdl = drift.get("brier_wdl")
        triggers = []
        if wdl_acc is not None and wdl_acc < ReviewEngine.WDL_ACC_THRESHOLD:
            triggers.append(f"WDL<{ReviewEngine.WDL_ACC_THRESHOLD:.0%} (now {wdl_acc:.1%})")
        if ou_acc is not None and ou_acc < ReviewEngine.OU_ACC_THRESHOLD:
            triggers.append(f"OU<{ReviewEngine.OU_ACC_THRESHOLD:.0%} (now {ou_acc:.1%})")
        if brier_wdl is not None and brier_wdl > ReviewEngine.BRIER_WDL_THRESHOLD:
            triggers.append(f"BrierWDL>{ReviewEngine.BRIER_WDL_THRESHOLD:.2f} (now {brier_wdl:.3f})")
        why = " / ".join(triggers) if triggers else "unknown"
        print(f"  🚨 检测到漂移！触发项：{why}")
        print("  → 建议考虑重新训练模型（predict_engine.py ModelTrainer.train()）")
    else:
        print(f"  ✅ 模型状态正常，近50场WDL准确率={drift.get('wdl_acc', 0):.1%}")

    print("="*55)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None, help="指定复盘日期 YYYY-MM-DD，默认昨天")
    parser.add_argument("--days", type=int, default=3,   help="向前复盘天数（含指定日期），默认3天以覆盖时区偏差")
    parser.add_argument("--backtest", action="store_true", help="同时运行资金曲线回测")
    parser.add_argument("--recompute", action="store_true",
                        help="Phase 2: 用 pred_ou_line 重算所有已审计行（幂等，不受 --days 限制）")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # --recompute 模式：重算历史行后继续正常复盘流程
    if args.recompute:
        log.info("🔄 [--recompute] 正在用 pred_ou_line 重算所有已审计行...")
        n = recompute_all_audited(conn)
        log.info(f"  重算完成，涉及 {n} 行")

    # 确定复盘日期范围
    if args.date:
        end_date = date.fromisoformat(args.date)
    else:
        end_date = date.today()  # 包含今天，配合 --days=3 覆盖时区偏差

    dates = [(end_date - timedelta(days=i)).isoformat() for i in range(args.days - 1, -1, -1)]

    review = ReviewEngine(DB_PATH, model_dir=MODEL_DIR)

    # CLAUDE.md §16: 在 audit 跑之前先 reconcile，让 audit_match 能算出 picked_correct
    try:
        n_fixed = reconcile_missing_picks(conn, days=max(14, args.days))
        if n_fixed > 0:
            log.error(
                f"[reconcile] ⚠️ 补写 {n_fixed} 场缺失 picks —— "
                f"上游 record_picked / log_prediction 可能失败，"
                f"检查 ingest_failure_log"
            )
        else:
            log.info("[reconcile] ✅ 近窗 picks 完整，无需补写")
    except Exception as _re:
        log.error(f"[reconcile] 自身失败（不阻塞）: {_re}", exc_info=True)

    # CLAUDE.md §17 事故 #6: picks 补完后，再补 actual_*（处理 cron 顺序回归造成的 audit 漏跑）
    try:
        n_audit = reconcile_missing_audit(conn, review, days=max(14, args.days))
        if n_audit == 0:
            log.info("[reconcile_audit] ✅ 近窗 audit 完整")
    except Exception as _re:
        log.error(f"[reconcile_audit] 自身失败（不阻塞）: {_re}", exc_info=True)

    summaries = []
    for d in dates:
        log.info(f"复盘日期: {d}")
        summary = run_review_for_date(review, conn, d)
        summaries.append(summary)

    # 漂移检测
    drift = review.check_drift()

    # B4: single_pick 主指标
    pick_stats = compute_single_pick_stats(conn, days=max(14, args.days))

    conn.close()
    review.close()

    print_summary(summaries, drift, pick_stats=pick_stats)

    # ── Server酱通知 ───────────────────────────────────────────────────
    try:
        from notify_utils import notify
        total_matches = sum(s["count"] for s in summaries)
        total_wdl_c   = sum(s.get("wdl_correct", 0) for s in summaries)
        total_ou_c    = sum(s.get("ou_correct", 0)  for s in summaries)

        lines = []
        # B4 主指标置顶：单推命中率 + ROI
        if pick_stats and pick_stats.get("n_settled"):
            ps = pick_stats
            hr = f"{ps['hit_rate']:.0%}" if ps["hit_rate"] is not None else "N/A"
            roi = f"{ps['roi']*100:+.1f}%" if ps["roi"] is not None else "N/A"
            push_str = f" ☯{ps['n_push']}走水" if ps.get("n_push") else ""
            lines.append(f"🎯 单推 近{ps['window_days']}天 {ps['hits']}/{ps['n_settled']}={hr}{push_str} | ROI {roi}")
            for c in ("HIGH", "MID", "LOW"):
                if c in ps["by_conf"]:
                    b = ps["by_conf"][c]
                    lines.append(f"   {c}: {b['hits']}/{b['n']}={b['acc']:.0%}")
            lines.append("")  # 空行分隔

        for s in summaries:
            if s["count"] > 0:
                lines.append(f"📅 {s['date']}: {s['count']}场 WDL={s['wdl_acc']:.0%} OU={s['ou_acc']:.0%}")

        wdl_acc_str = f"{total_wdl_c/total_matches:.0%}" if total_matches else "N/A"
        ou_acc_str  = f"{total_ou_c/total_matches:.0%}"  if total_matches else "N/A"
        lines.append(f"\n三方向独立 合计 {total_matches} 场 | WDL={wdl_acc_str} OU={ou_acc_str}")

        wdl_near50 = drift.get("wdl_acc", 0)
        if drift.get("drift"):
            wdl_acc = drift.get("wdl_acc")
            ou_acc = drift.get("ou_acc")
            brier_wdl = drift.get("brier_wdl")
            triggers = []
            if wdl_acc is not None and wdl_acc < ReviewEngine.WDL_ACC_THRESHOLD:
                triggers.append(f"WDL<{ReviewEngine.WDL_ACC_THRESHOLD:.0%}({wdl_acc:.0%})")
            if ou_acc is not None and ou_acc < ReviewEngine.OU_ACC_THRESHOLD:
                triggers.append(f"OU<{ReviewEngine.OU_ACC_THRESHOLD:.0%}({ou_acc:.0%})")
            if brier_wdl is not None and brier_wdl > ReviewEngine.BRIER_WDL_THRESHOLD:
                triggers.append(f"Brier>{ReviewEngine.BRIER_WDL_THRESHOLD:.2f}({brier_wdl:.3f})")
            why = " / ".join(triggers) if triggers else "unknown"
            lines.append(f"🚨 模型漂移警告！触发项：{why}")
        elif drift.get("status") != "insufficient_data":
            lines.append(f"✅ 模型正常 近50场WDL={wdl_near50:.0%}")

        notify(title=f"喵弟复盘 · {total_matches}场", msg="\n".join(lines))
    except Exception as _e:
        log.warning(f"Server酱通知失败: {_e}")

    # 可选：资金曲线回测
    if args.backtest:
        print("\n运行资金曲线回测...")
        sim = BacktestSimulator(DB_PATH)
        result = sim.run(initial_bankroll=10000.0)
        print_backtest_report(result)


if __name__ == "__main__":
    main()
