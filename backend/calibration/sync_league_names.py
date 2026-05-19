#!/usr/bin/env python3
"""
sync_league_names.py
====================
把 dim_match 中出现但 calibration_league 缺失的 League_ID 增量写入，
确保 calibration_league 始终覆盖全量联赛，避免 JOIN 时出现错误标签。

用法：
    python3 calibration/sync_league_names.py --dry-run
    python3 calibration/sync_league_names.py --apply

CLAUDE.md §3: 唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""

from __future__ import annotations
import os, sys, sqlite3, argparse, logging
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────
# 已知 League_ID → 名称映射（手工维护）
# 新联赛出现后在此添加，不影响已有记录
# ──────────────────────────────────────────────────────────────────────────
LID_NAMES: dict[int, str] = {
    # 英格兰
    47: "英超",
    88: "英冠",
    87: "英甲",
    89: "英乙",
    132: "英格兰联赛杯",
    133: "英格兰足总杯",

    # 西班牙
    55: "西甲",
    90: "西乙",
    138: "西班牙杯/低级别联赛",

    # 德国
    35: "德甲",
    36: "德乙",
    209: "德国杯",

    # 法国
    53: "法甲",
    75: "法乙",
    134: "法国杯",

    # 意大利
    54: "意甲",
    93: "意乙",
    141: "意大利杯",

    # 欧洲杯赛
    42: "欧冠",
    73: "欧联",
    108: "欧会联",

    # 荷兰
    57: "荷甲",

    # 葡萄牙
    61: "葡超",

    # 苏格兰
    113: "苏超",

    # 土耳其
    103: "土超",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="增量同步 calibration_league 联赛字典")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写入")
    parser.add_argument("--apply", action="store_true", help="执行写入")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("请指定 --dry-run 或 --apply")
        parser.print_help()
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    try:
        _sync(conn, dry_run=args.dry_run)
    finally:
        conn.close()


def _sync(conn: sqlite3.Connection, dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "APPLY"
    log.info(f"\n{'='*60}")
    log.info(f"  sync_league_names  [{mode}]")
    log.info(f"{'='*60}")

    # 当前 calibration_league 覆盖
    existing_ids: set[int] = {
        row[0] for row in conn.execute("SELECT league_id FROM calibration_league").fetchall()
    }

    # dim_match 中所有 League_ID（含出现场次）
    all_lids = conn.execute("""
        SELECT League_ID, COUNT(*) as cnt
        FROM dim_match
        GROUP BY League_ID
        ORDER BY cnt DESC
    """).fetchall()

    missing = [(lid, cnt) for lid, cnt in all_lids if lid not in existing_ids]

    log.info(f"  calibration_league 现有: {len(existing_ids)} 条")
    log.info(f"  dim_match 总联赛数: {len(all_lids)} 个")
    log.info(f"  缺失（需写入）: {len(missing)} 个")

    if not missing:
        log.info("  ✅ 已全量覆盖，无需写入")
        return

    now_str = datetime.now(timezone.utc).isoformat()

    print(f"\n  {'lid':>6}  {'league_name':<30}  {'match_cnt':>10}")
    print("  " + "-" * 52)
    for lid, cnt in missing:
        name = LID_NAMES.get(lid, f"League_{lid}")
        print(f"  {lid:>6}  {name:<30}  {cnt:>10}")

    if dry_run:
        log.info(f"\n  [dry-run] 将写入 {len(missing)} 行，实际不执行")
        return

    inserted = 0
    for lid, cnt in missing:
        name = LID_NAMES.get(lid, f"League_{lid}")
        conn.execute("""
            INSERT OR IGNORE INTO calibration_league
                (league_id, league_name, ou_line, updated_at)
            VALUES (?, ?, 2.5, ?)
        """, (lid, name, now_str))
        inserted += 1

    conn.commit()
    log.info(f"\n  ✅ 写入 {inserted} 行到 calibration_league")

    # 验证
    total_after = conn.execute("SELECT COUNT(*) FROM calibration_league").fetchone()[0]
    dim_count = conn.execute("SELECT COUNT(DISTINCT League_ID) FROM dim_match").fetchone()[0]
    log.info(f"  calibration_league: {total_after} 条 vs dim_match 联赛数: {dim_count}")
    if total_after >= dim_count:
        log.info("  ✅ 全量覆盖验证通过")
    else:
        log.warning(f"  ⚠️  仍有 {dim_count - total_after} 个联赛未覆盖")


if __name__ == "__main__":
    main()
