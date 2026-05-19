"""
repair_2026_05_02_big_five.py — 一次性补救脚本（CLAUDE.md §17 事故 #7）

背景：
- 5/1 04:00 UTC Thordata 代理过期 → fotmob_scheduler API 全失败
- fallback 保留逻辑 kickoff_time 时区 bug → 连续 2 天误删未来场次 (34→30→26)
- 5/2 run_tonight 加载 26 场，5 场 BIG_FIVE 永远漏出 pipeline

漏掉的 5 场：
- 4803380 Como vs Napoli (Serie A) 0:0
- 4813716 Arsenal vs Fulham (Premier League) 3:0
- 4829594 Bayer Leverkusen vs RB Leipzig (Bundesliga) 4:1
- 4830740 Metz vs Monaco (Ligue 1) 1:2
- 4837440 Deportivo Alaves vs Athletic Club (LaLiga) 2:4

执行步骤（idempotent，默认 --dry-run）：
1. 为 5 场补抓赔率 → 写入 odds/match_odds_data.json → upsert silver_match_odds
2. 为 5 场补建 prediction_audit 行（picked_market=NULL，actual_wdl 从 dim_match 取）
3. 记录 ingest_failure_log（step='lost_pre_match_report'）

用法：
    python3 scripts/repair_2026_05_02_big_five.py            # dry-run（默认）
    python3 scripts/repair_2026_05_02_big_five.py --apply    # 实际写库
    python3 scripts/repair_2026_05_02_big_five.py --apply --skip-odds  # 跳过赔率抓取
"""

import os
import sys
import argparse
import sqlite3
import json
import logging
import time
import random

PROJECT_ROOT = os.environ.get(
    "PROJECT_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, PROJECT_ROOT)

from scripts.ingest_failure_helper import record_failure

DB_PATH   = os.path.join(PROJECT_ROOT, "football_uk.db")
ODDS_JSON = os.path.join(PROJECT_ROOT, "odds", "match_odds_data.json")
MODEL_DIR = os.path.join(PROJECT_ROOT, "models_v4")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# 5 场漏掉的比赛（已完赛，比分来自 dim_match 实测）
MISSING_MATCHES = [
    {
        "match_id": "4803380",
        "date": "2026-05-02",
        "home": "Como",
        "away": "Napoli",
        "league": "Serie A",
        "league_id": 55,
        "home_score": 0,
        "away_score": 0,
    },
    {
        "match_id": "4813716",
        "date": "2026-05-02",
        "home": "Arsenal",
        "away": "Fulham",
        "league": "Premier League",
        "league_id": 47,
        "home_score": 3,
        "away_score": 0,
    },
    {
        "match_id": "4829594",
        "date": "2026-05-02",
        "home": "Bayer Leverkusen",
        "away": "RB Leipzig",
        "league": "Bundesliga",
        "league_id": 54,
        "home_score": 4,
        "away_score": 1,
    },
    {
        "match_id": "4830740",
        "date": "2026-05-02",
        "home": "Metz",
        "away": "Monaco",
        "league": "Ligue 1",
        "league_id": 53,
        "home_score": 1,
        "away_score": 2,
    },
    {
        "match_id": "4837440",
        "date": "2026-05-02",
        "home": "Deportivo Alaves",
        "away": "Athletic Club",
        "league": "LaLiga",
        "league_id": 87,
        "home_score": 2,
        "away_score": 4,
    },
]


def _derive_actual_wdl(m: dict) -> str:
    """根据比分计算主队 WDL"""
    h, a = m["home_score"], m["away_score"]
    if h > a:
        return "W"
    elif h < a:
        return "L"
    else:
        return "D"


def step1_scrape_odds(apply_mode: bool, skip_odds: bool) -> dict:
    """
    为 5 场比赛补抓赔率，写入 odds/match_odds_data.json，然后 upsert silver_match_odds。
    返回 {match_id: bool} 成功标记。
    """
    results = {}

    if skip_odds:
        log.info("⏭️  --skip-odds：跳过赔率抓取")
        for m in MISSING_MATCHES:
            results[m["match_id"]] = False
        return results

    try:
        from titan_odds_spider import fetch_single_match_odds
    except ImportError as e:
        log.error(f"无法导入 titan_odds_spider: {e}")
        for m in MISSING_MATCHES:
            results[m["match_id"]] = False
        return results

    # 读现有 odds JSON（可能有内容）
    existing_odds = []
    if os.path.exists(ODDS_JSON):
        try:
            with open(ODDS_JSON, "r", encoding="utf-8") as f:
                existing_odds = json.load(f)
            log.info(f"  现有 odds JSON: {len(existing_odds)} 条")
        except Exception as e:
            log.warning(f"  odds JSON 读取失败（将覆盖）: {e}")
            existing_odds = []

    existing_ids = {str(o.get("match_id", "")) for o in existing_odds}
    new_entries = []

    for m in MISSING_MATCHES:
        mid = m["match_id"]
        log.info(f"\n  🔍 抓取赔率: {m['home']} vs {m['away']} ({m['date']}) mid={mid}")

        if mid in existing_ids:
            log.info(f"  ⏭️  odds JSON 已有 {mid}，跳过抓取")
            results[mid] = True
            continue

        if not apply_mode:
            log.info(f"  [DRY-RUN] 会调用 fetch_single_match_odds({mid}, {m['date']}, {m['home']}, {m['away']})")
            results[mid] = False
            continue

        try:
            odds_data = fetch_single_match_odds(
                fotmob_id=mid,
                match_date=m["date"],
                home_en=m["home"],
                away_en=m["away"],
            )
            if odds_data:
                new_entries.append({
                    "fotmob_id": str(mid),
                    "titan_id":  "",
                    "match_name": f"{m['home']} vs {m['away']}",
                    "odds": odds_data,
                })
                results[mid] = True
                log.info(f"  ✅ 赔率抓取成功: {mid}")
            else:
                results[mid] = False
                log.warning(f"  ⚠️  fetch_single_match_odds 返回 None: {mid}")
                record_failure(
                    "repair_2026_05_02_big_five",
                    match_id=mid,
                    step="odds_fetch_failed",
                    error_msg=f"fetch_single_match_odds returned None for {m['home']} vs {m['away']}",
                )
        except Exception as e:
            results[mid] = False
            log.error(f"  ✗ 赔率抓取异常 {mid}: {e}")
            record_failure(
                "repair_2026_05_02_big_five",
                match_id=mid,
                step="odds_fetch_exception",
                error_msg=str(e),
            )

        # 礼貌性延时，避免频繁请求
        time.sleep(random.uniform(2.0, 4.0))

    if apply_mode and new_entries:
        # 写回 odds JSON
        merged = existing_odds + new_entries
        os.makedirs(os.path.dirname(ODDS_JSON), exist_ok=True)
        with open(ODDS_JSON, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        log.info(f"\n  ✅ 已写入 odds JSON: 新增 {len(new_entries)} 条，合计 {len(merged)} 条")

        # 调 silver_builder 把 odds JSON → silver_match_odds
        try:
            from silver_builder import _ingest_nowgoal_odds

            _conn = sqlite3.connect(DB_PATH, timeout=10)
            n = _ingest_nowgoal_odds(_conn)
            _conn.commit()
            _conn.close()
            log.info(f"  ✅ silver_builder._ingest_nowgoal_odds() 完成，upsert {n} 行")
        except Exception as e:
            log.error(f"  ✗ silver_builder upsert 失败: {e}")
            record_failure(
                "repair_2026_05_02_big_five",
                step="silver_upsert_failed",
                error_msg=str(e),
            )

    return results


def step2_backfill_prediction_audit(conn: sqlite3.Connection, apply_mode: bool) -> int:
    """
    为 5 场漏掉的比赛补建 prediction_audit 行。
    这些比赛没有赛前预测（无研报），picked_market=NULL，但要记录 actual_wdl。
    已有行则跳过（idempotent）。
    返回实际插入行数。
    """
    inserted = 0

    existing = {
        str(row[0])
        for row in conn.execute(
            "SELECT match_id FROM prediction_audit WHERE match_id IN ({})".format(
                ",".join("?" * len(MISSING_MATCHES))
            ),
            [m["match_id"] for m in MISSING_MATCHES],
        ).fetchall()
    }

    log.info(f"\n📋 prediction_audit 检查：{len(existing)} 场已有记录，{len(MISSING_MATCHES)-len(existing)} 场需补建")

    for m in MISSING_MATCHES:
        mid = m["match_id"]
        if mid in existing:
            log.info(f"  ⏭️  prediction_audit 已有 {mid}，跳过")
            continue

        actual_wdl = _derive_actual_wdl(m)
        log.info(
            f"  {'[DRY-RUN] 会插入' if not apply_mode else '插入'} "
            f"prediction_audit: mid={mid} {m['home']} vs {m['away']} "
            f"score={m['home_score']}:{m['away_score']} wdl={actual_wdl} picked_market=NULL"
        )

        if apply_mode:
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO prediction_audit
                        (match_id, match_date, home_name, away_name,
                         actual_home_score, actual_away_score, actual_wdl, picked_market)
                    VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        mid,
                        m["date"],
                        m["home"],
                        m["away"],
                        m["home_score"],
                        m["away_score"],
                        actual_wdl,
                    ),
                )
                inserted += 1
                log.info(f"  ✅ prediction_audit 插入成功: {mid}")
            except Exception as e:
                log.error(f"  ✗ prediction_audit 插入失败 {mid}: {e}")
                record_failure(
                    "repair_2026_05_02_big_five",
                    match_id=mid,
                    step="prediction_audit_insert_failed",
                    error_msg=str(e),
                )

    if apply_mode and inserted > 0:
        conn.commit()

    return inserted


def step3_record_lost_reports(apply_mode: bool) -> int:
    """
    记录 ingest_failure_log，标记这 5 场为 lost_pre_match_report。
    研报已无法事后伪造（赛前推荐的业务价值已过期）。
    返回实际记录条数。
    """
    log.info(f"\n📋 记录 ingest_failure_log（step=lost_pre_match_report）")
    recorded = 0

    for m in MISSING_MATCHES:
        msg = (
            f"BIG_FIVE pipeline miss: {m['date']} L{m['league_id']} {m['league']} "
            f"{m['home']} vs {m['away']} | final={m['home_score']}:{m['away_score']} | "
            f"根因: fotmob_scheduler 5/1 Thordata 代理过期+保留逻辑时区 bug → 34→30→26 渐进丢失"
        )
        log.info(
            f"  {'[DRY-RUN] 会记录' if not apply_mode else '记录'} "
            f"mid={m['match_id']} {m['home']} vs {m['away']}"
        )
        if apply_mode:
            try:
                record_failure(
                    "repair_2026_05_02_big_five",
                    match_id=m["match_id"],
                    step="lost_pre_match_report",
                    error_msg=msg,
                )
                recorded += 1
            except Exception as e:
                log.error(f"  ✗ record_failure 失败 {m['match_id']}: {e}")

    return recorded


def verify_results(conn: sqlite3.Connection):
    """输出补救后的验证结果"""
    mids = [m["match_id"] for m in MISSING_MATCHES]
    placeholders = ",".join("?" * len(mids))

    log.info("\n" + "=" * 60)
    log.info("🔍 验证结果")

    # silver_match_odds
    odds_rows = conn.execute(
        f"""
        SELECT match_id, COUNT(*) as cnt
        FROM silver_match_odds
        WHERE match_id IN ({placeholders})
        GROUP BY match_id
        """,
        mids,
    ).fetchall()
    odds_map = {str(r[0]): r[1] for r in odds_rows}
    log.info(f"\n  silver_match_odds:")
    for m in MISSING_MATCHES:
        cnt = odds_map.get(m["match_id"], 0)
        status = "✅" if cnt >= 6 else ("⚠️" if cnt > 0 else "❌")
        log.info(f"  {status} {m['match_id']} {m['home']} vs {m['away']}: {cnt} 行（期望≥6）")

    # prediction_audit
    audit_rows = conn.execute(
        f"""
        SELECT match_id, actual_wdl, picked_market
        FROM prediction_audit
        WHERE match_id IN ({placeholders})
        """,
        mids,
    ).fetchall()
    audit_map = {str(r[0]): (r[1], r[2]) for r in audit_rows}
    log.info(f"\n  prediction_audit:")
    for m in MISSING_MATCHES:
        if m["match_id"] in audit_map:
            wdl, pm = audit_map[m["match_id"]]
            log.info(f"  ✅ {m['match_id']} actual_wdl={wdl} picked_market={pm}")
        else:
            log.info(f"  ❌ {m['match_id']} 缺失")

    # ingest_failure_log
    fail_rows = conn.execute(
        f"""
        SELECT match_id, step FROM ingest_failure_log
        WHERE match_id IN ({placeholders}) AND step='lost_pre_match_report'
        """,
        mids,
    ).fetchall()
    log.info(f"\n  ingest_failure_log (lost_pre_match_report): {len(fail_rows)} 条")


def main():
    ap = argparse.ArgumentParser(description="补救 2026-05-02 BIG_FIVE 漏出 pipeline 的 5 场")
    ap.add_argument("--apply", action="store_true", help="实际写库（默认 dry-run）")
    ap.add_argument("--skip-odds", action="store_true", help="跳过赔率抓取（仅补 prediction_audit）")
    ap.add_argument("--verify-only", action="store_true", help="仅输出当前验证状态，不写库")
    args = ap.parse_args()

    apply_mode = args.apply and not args.verify_only
    label = "VERIFY-ONLY" if args.verify_only else ("APPLY" if apply_mode else "DRY-RUN")

    log.info(f"=== repair_2026_05_02_big_five [{label}] ===")
    log.info(f"目标: {len(MISSING_MATCHES)} 场 BIG_FIVE（2026-05-02 漏出 pipeline）")
    for m in MISSING_MATCHES:
        log.info(f"  · {m['match_id']} {m['league']}: {m['home']} vs {m['away']} "
                 f"{m['home_score']}:{m['away_score']}")

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row

    if args.verify_only:
        verify_results(conn)
        conn.close()
        return

    # Step 1: 赔率
    log.info("\n── Step 1: 补抓赔率 ──────────────────────────────────────")
    odds_results = step1_scrape_odds(apply_mode, args.skip_odds)

    # Step 2: prediction_audit
    log.info("\n── Step 2: 补建 prediction_audit ────────────────────────")
    inserted_audit = step2_backfill_prediction_audit(conn, apply_mode)

    # Step 3: ingest_failure_log
    log.info("\n── Step 3: 记录 ingest_failure_log ─────────────────────")
    recorded_fail = step3_record_lost_reports(apply_mode)

    # 验证
    if apply_mode:
        verify_results(conn)

    # Summary
    log.info("\n" + "=" * 60)
    log.info(f"📊 SUMMARY ({label})")
    log.info(f"  赔率抓取成功   : {sum(odds_results.values())}/{len(MISSING_MATCHES)} 场")
    log.info(f"  prediction_audit: 插入 {inserted_audit} 行")
    log.info(f"  ingest_failure_log: 记录 {recorded_fail} 条")
    log.info("=" * 60)

    if not apply_mode:
        log.info("ℹ️  这是 dry-run，未写库。如需执行：加 --apply")

    conn.close()


if __name__ == "__main__":
    main()
