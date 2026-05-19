#!/usr/bin/env python3
"""
cleanup_null_line_odds.py
=========================
一次性清理 silver_match_odds 中因 footballdata 路径 bug（2026-04-16 批次）
写入的 raw_line=NULL 的 OU opening/closing 记录，并尽量通过 NowGoal 重抓补齐。

流程：
  Step 1: 备份坏数据到 silver_match_odds_null_line_backup，然后 DELETE
  Step 2: 通过 NowGoal API 重抓缺失盘口（best-effort，受保留窗口限制）
  Step 3: closing-line 反填 opening-line（121 场兜底）
  Step 4: 重建 mart_ou_dataset_v5 / mart_ou_features_v5

用法：
    python3 scripts/cleanup_null_line_odds.py --dry-run
    python3 scripts/cleanup_null_line_odds.py --apply
    python3 scripts/cleanup_null_line_odds.py --apply --skip-nowgoal-refetch

CLAUDE.md §3: 唯一生产库 = /home/ubuntu/app/backend/football_uk.db
CLAUDE.md §17 防御要点 1: 失败用 record_failure 不用 silent warning
"""

from __future__ import annotations
import os, sys, time, random, sqlite3, argparse, logging, subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

SCRIPT_NAME = "cleanup_null_line_odds"


# ──────────────────────────────────────────────────────────────────────────
# Step 1: 备份 + DELETE 坏数据
# ──────────────────────────────────────────────────────────────────────────

def step1_backup_and_delete(conn: sqlite3.Connection, dry_run: bool) -> int:
    """返回删除行数"""
    # 统计
    null_count = conn.execute("""
        SELECT COUNT(*) FROM silver_match_odds
        WHERE market='ou' AND raw_line IS NULL AND source='footballdata'
    """).fetchone()[0]

    log.info(f"\n{'='*60}")
    log.info(f"  Step 1: 备份 + 删除 NULL raw_line 坏数据")
    log.info(f"{'='*60}")
    log.info(f"  待删除 OU 行数 (raw_line IS NULL, source=footballdata): {null_count}")

    if null_count == 0:
        log.info("  ✅ 无坏数据，跳过 Step 1")
        return 0

    if dry_run:
        log.info(f"  [dry-run] 将删除 {null_count} 行，实际不执行")
        return null_count

    # 备份（幂等：如果表已存在则追加）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS silver_match_odds_null_line_backup AS
        SELECT * FROM silver_match_odds WHERE 0
    """)
    conn.execute("""
        INSERT INTO silver_match_odds_null_line_backup
        SELECT * FROM silver_match_odds
        WHERE market='ou' AND raw_line IS NULL AND source='footballdata'
    """)
    backed_up = conn.execute(
        "SELECT COUNT(*) FROM silver_match_odds_null_line_backup"
    ).fetchone()[0]
    log.info(f"  备份表 silver_match_odds_null_line_backup 已写入 {backed_up} 行（累计）")

    # DELETE
    conn.execute("""
        DELETE FROM silver_match_odds
        WHERE market='ou' AND raw_line IS NULL AND source='footballdata'
    """)
    conn.commit()
    log.info(f"  ✅ 已删除 {null_count} 行坏数据")
    return null_count


# ──────────────────────────────────────────────────────────────────────────
# Step 2: NowGoal 重抓
# ──────────────────────────────────────────────────────────────────────────

def step2_nowgoal_refetch(conn: sqlite3.Connection, dry_run: bool) -> dict:
    """返回 {'success': n, 'no_data': n, 'failed': n, 'candidates': n}"""
    from scripts.ingest_failure_helper import record_failure

    log.info(f"\n{'='*60}")
    log.info(f"  Step 2: NowGoal 重抓缺失 OU opening")
    log.info(f"{'='*60}")

    # 找出 25/26 比赛中缺少有效 OU opening 的场次
    candidates = conn.execute("""
        SELECT d.Match_ID, d.Date, d.Home_Team_Name, d.Away_Team_Name, d.League_ID
        FROM dim_match d
        WHERE d.Season IN ('2025/2026', '2026')
          AND NOT EXISTS (
              SELECT 1 FROM silver_match_odds s
              WHERE CAST(s.match_id AS TEXT) = CAST(d.Match_ID AS TEXT)
                AND s.market = 'ou' AND s.period = 'opening'
                AND s.raw_line IS NOT NULL
          )
        ORDER BY d.Date DESC
    """).fetchall()

    log.info(f"  候选（缺少有效 OU opening）: {len(candidates)} 场")

    if not candidates:
        log.info("  ✅ 无缺失场次，跳过 Step 2")
        return {'success': 0, 'no_data': 0, 'failed': 0, 'candidates': 0}

    if dry_run:
        log.info(f"  [dry-run] 将尝试 NowGoal 重抓 {len(candidates)} 场，实际不执行")
        return {'success': 0, 'no_data': 0, 'failed': 0, 'candidates': len(candidates)}

    from titan_odds_spider import fetch_single_match_odds
    from silver_builder import ingest_nowgoal_odds_from_dict

    success = no_data = failed = 0
    for match_id, date_str, home_en, away_en, league_id in candidates:
        log.info(f"  [{date_str}] {home_en} vs {away_en} (id={match_id})")
        try:
            odds_data = fetch_single_match_odds(
                fotmob_id=str(match_id),
                match_date=date_str,
                home_en=home_en,
                away_en=away_en,
            )
            if not odds_data:
                log.warning(f"    ⚠️  NowGoal 无数据（可能超过保留窗口）")
                no_data += 1
            else:
                n = ingest_nowgoal_odds_from_dict(
                    conn=conn,
                    fotmob_id=str(match_id),
                    odds_data=odds_data,
                    match_date=date_str,
                )
                log.info(f"    ✅ 写入 {n} 行")
                success += 1
        except Exception as e:
            log.error(f"    ❌ 失败: {e}")
            record_failure(
                script_name=SCRIPT_NAME,
                match_id=match_id,
                step="fetch",
                error_msg=str(e),
            )
            failed += 1

        time.sleep(random.uniform(1.5, 3.0))

    log.info(f"\n  Step 2 完成 → 成功={success} / 无数据={no_data} / 失败={failed} "
             f"(共 {len(candidates)} 场候选)")
    return {'success': success, 'no_data': no_data, 'failed': failed,
            'candidates': len(candidates)}


# ──────────────────────────────────────────────────────────────────────────
# Step 3: closing-line 反填 opening-line（兜底）
# ──────────────────────────────────────────────────────────────────────────

def step3_closing_proxy(conn: sqlite3.Connection, dry_run: bool) -> int:
    """用 closing line 补 opening（source='closing_proxy'），返回实际插入行数"""
    log.info(f"\n{'='*60}")
    log.info(f"  Step 3: closing-line 反填 opening-line（兜底）")
    log.info(f"{'='*60}")

    # 统计候选
    proxy_count = conn.execute("""
        SELECT COUNT(*) FROM silver_match_odds c
        WHERE c.market='ou' AND c.period='closing' AND c.raw_line IS NOT NULL
          AND CAST(c.match_id AS TEXT) IN (
              SELECT CAST(d.Match_ID AS TEXT)
              FROM dim_match d
              WHERE d.Season IN ('2025/2026', '2026')
                AND NOT EXISTS (
                    SELECT 1 FROM silver_match_odds s2
                    WHERE CAST(s2.match_id AS TEXT) = CAST(d.Match_ID AS TEXT)
                      AND s2.market='ou' AND s2.period='opening'
                      AND s2.raw_line IS NOT NULL
                )
          )
    """).fetchone()[0]

    log.info(f"  可用 closing-proxy 候选: {proxy_count} 行")

    if proxy_count == 0:
        log.info("  ✅ 无需反填，跳过 Step 3")
        return 0

    if dry_run:
        log.info(f"  [dry-run] 将反填 {proxy_count} 行，实际不执行")
        return proxy_count

    conn.execute("""
        INSERT OR IGNORE INTO silver_match_odds
            (match_id, match_date, home_team_id, away_team_id,
             market, period, provider,
             raw_home, raw_draw, raw_away, raw_line,
             fair_home, fair_draw, fair_away, overround,
             source, scraped_at, inserted_at)
        SELECT
            c.match_id, c.match_date, c.home_team_id, c.away_team_id,
            'ou', 'opening', c.provider,
            c.raw_home, NULL, c.raw_away, c.raw_line,
            c.fair_home, NULL, c.fair_away, c.overround,
            'closing_proxy', datetime('now'), datetime('now')
        FROM silver_match_odds c
        WHERE c.market='ou' AND c.period='closing' AND c.raw_line IS NOT NULL
          AND CAST(c.match_id AS TEXT) IN (
              SELECT CAST(d.Match_ID AS TEXT)
              FROM dim_match d
              WHERE d.Season IN ('2025/2026', '2026')
                AND NOT EXISTS (
                    SELECT 1 FROM silver_match_odds s2
                    WHERE CAST(s2.match_id AS TEXT) = CAST(d.Match_ID AS TEXT)
                      AND s2.market='ou' AND s2.period='opening'
                      AND s2.raw_line IS NOT NULL
                )
          )
    """)
    inserted = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    log.info(f"  ✅ closing_proxy 写入 {inserted} 行（source='closing_proxy'）")
    return inserted


# ──────────────────────────────────────────────────────────────────────────
# Step 4: 重建 mart 表
# ──────────────────────────────────────────────────────────────────────────

def step4_rebuild_mart(dry_run: bool) -> None:
    log.info(f"\n{'='*60}")
    log.info(f"  Step 4: 重建 mart_ou_dataset_v5 / mart_ou_features_v5")
    log.info(f"{'='*60}")

    if dry_run:
        log.info("  [dry-run] 跳过重建 mart 表")
        return

    venv_python = os.path.join(PROJECT_ROOT, "venv", "bin", "python3")
    for script in [
        "v5_feature_engineering/build_ou_dataset_v5.py",
        "v5_feature_engineering/build_ou_features_v5.py",
    ]:
        script_path = os.path.join(PROJECT_ROOT, script)
        log.info(f"  运行: {script}")
        result = subprocess.run(
            [venv_python, script_path],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log.error(f"  ❌ {script} 失败:\n{result.stderr[-2000:]}")
        else:
            # 提取最后几行输出
            last_lines = result.stdout.strip().splitlines()[-5:]
            for line in last_lines:
                log.info(f"    {line}")
            log.info(f"  ✅ {script} 完成")


# ──────────────────────────────────────────────────────────────────────────
# 验证报告
# ──────────────────────────────────────────────────────────────────────────

def print_verification(conn: sqlite3.Connection) -> None:
    log.info(f"\n{'='*60}")
    log.info(f"  验证报告")
    log.info(f"{'='*60}")

    # 残余 NULL 数
    null_remaining = conn.execute("""
        SELECT COUNT(*) FROM silver_match_odds
        WHERE market='ou' AND raw_line IS NULL AND source='footballdata'
    """).fetchone()[0]
    log.info(f"  残余坏数据 (NULL raw_line, source=footballdata): {null_remaining}")

    # 25/26 OU opening 覆盖
    rows = conn.execute("""
        SELECT
            s.source,
            COUNT(*) as cnt,
            COUNT(CASE WHEN s.raw_line IS NOT NULL THEN 1 END) as valid
        FROM silver_match_odds s
        JOIN dim_match d ON CAST(d.Match_ID AS TEXT) = CAST(s.match_id AS TEXT)
        WHERE d.Season IN ('2025/2026', '2026')
          AND s.market='ou' AND s.period='opening'
        GROUP BY s.source
        ORDER BY cnt DESC
    """).fetchall()
    log.info(f"  25/26 OU opening 覆盖（按来源）:")
    for source, cnt, valid in rows:
        log.info(f"    source={source:<20} total={cnt:>5}  valid_line={valid:>5}")

    # mart_ou_features_v5 25/26 行数
    try:
        mart_rows = conn.execute("""
            SELECT ou_line_opening, COUNT(*) FROM mart_ou_features_v5
            WHERE Season IN ('2025/2026', '2026')
            GROUP BY ou_line_opening
            ORDER BY ou_line_opening
        """).fetchall()
        log.info(f"  mart_ou_features_v5 25/26 行数（按盘口）:")
        for line, cnt in mart_rows:
            log.info(f"    ou_line={line}  n={cnt}")
    except Exception:
        log.info("  mart_ou_features_v5 尚未生成（需先运行 Step 4）")


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="清理 silver_match_odds NULL raw_line 坏数据")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印统计，不执行写入/删除")
    parser.add_argument("--apply", action="store_true",
                        help="执行实际变更（与 --dry-run 互斥）")
    parser.add_argument("--skip-nowgoal-refetch", action="store_true",
                        help="跳过 NowGoal 重抓（直接从 Step 3 closing proxy 兜底）")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("请指定 --dry-run 或 --apply")
        parser.print_help()
        sys.exit(1)

    dry_run = args.dry_run
    mode = "DRY-RUN" if dry_run else "APPLY"
    log.info(f"\n{'#'*60}")
    log.info(f"  cleanup_null_line_odds  [{mode}]")
    log.info(f"  DB: {DB_PATH}")
    log.info(f"{'#'*60}")

    conn = sqlite3.connect(DB_PATH)

    try:
        # Step 1: 备份 + 删除
        deleted = step1_backup_and_delete(conn, dry_run)

        # Step 2: NowGoal 重抓
        if args.skip_nowgoal_refetch:
            log.info("\n  [--skip-nowgoal-refetch] 跳过 Step 2")
            refetch_stats = {'success': 0, 'no_data': 0, 'failed': 0, 'candidates': 0}
        else:
            refetch_stats = step2_nowgoal_refetch(conn, dry_run)

        # Step 3: closing proxy
        proxy_inserted = step3_closing_proxy(conn, dry_run)

        # Step 4: 重建 mart
        step4_rebuild_mart(dry_run)

        # 验证
        if not dry_run:
            print_verification(conn)

        # 摘要
        log.info(f"\n{'='*60}")
        log.info(f"  完成摘要 [{mode}]")
        log.info(f"{'='*60}")
        log.info(f"  Step 1 删除: {deleted} 行坏数据")
        log.info(f"  Step 2 NowGoal 重抓: "
                 f"候选={refetch_stats['candidates']}  "
                 f"成功={refetch_stats['success']}  "
                 f"无数据={refetch_stats['no_data']}  "
                 f"失败={refetch_stats['failed']}")
        log.info(f"  Step 3 closing_proxy: {proxy_inserted} 行写入")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
