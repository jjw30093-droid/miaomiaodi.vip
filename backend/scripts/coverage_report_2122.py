"""
Phase 4b: Generate 2021/22 BIG5 NowGoal odds backfill coverage report.
Output: reports/nowgoal_2122_coverage.md + reports/nowgoal_2122_coverage.csv
"""

import csv
import json
import os
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BACKEND_DIR, "football_uk.db")
UNMAPPED_PATH = os.path.join(BACKEND_DIR, "data", "nowgoal_2122_unmapped.json")
ODDS_PATH = os.path.join(BACKEND_DIR, "odds", "match_odds_data_2122.json")
REPORTS_DIR = os.path.join(BACKEND_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

LEAGUE_NAMES = {47: "EPL", 87: "La Liga", 54: "Bundesliga", 55: "Serie A", 53: "Ligue 1"}
TOTAL_FINISH = 1624


def main():
    print("=== Coverage Report: 2021/22 NowGoal Odds Backfill ===")

    conn = sqlite3.connect(DB_PATH)

    # All 2021/22 Finish matches
    all_matches = conn.execute("""
        SELECT Match_ID, Date, League_ID, Home_Team_Name, Away_Team_Name
        FROM dim_match
        WHERE Season='2021/2022'
          AND League_ID IN (47,87,54,55,53)
          AND status='Finish'
        ORDER BY Date, Match_ID
    """).fetchall()

    # silver_match_odds coverage per match
    smo_rows = conn.execute("""
        SELECT s.match_id, s.market, s.period
        FROM silver_match_odds s
        JOIN dim_match d ON d.Match_ID = s.match_id
        WHERE d.Season='2021/2022'
          AND d.League_ID IN (47,87,54,55,53)
          AND d.status='Finish'
          AND s.source='nowgoal'
    """).fetchall()

    conn.close()

    # Build coverage map: match_id → set of (market, period)
    coverage = defaultdict(set)
    for match_id, market, period in smo_rows:
        coverage[match_id].add((market, period))

    FULL_SET = {
        ("1x2", "opening"), ("1x2", "closing"),
        ("ou", "opening"), ("ou", "closing"),
        ("ah", "opening"), ("ah", "closing"),
    }

    # Load unmapped info
    unmapped_ids = set()
    if os.path.exists(UNMAPPED_PATH):
        with open(UNMAPPED_PATH) as f:
            unmapped = json.load(f)
        unmapped_ids = {u["fotmob_id"] for u in unmapped}

    # Per-league stats
    league_stats = defaultdict(lambda: {"total": 0, "has_any": 0, "full_6": 0, "partial": 0, "none": 0})

    missing_rows = []   # complete misses
    partial_rows = []   # some markets missing

    for match_id, date, league_id, home, away in all_matches:
        lname = LEAGUE_NAMES.get(league_id, str(league_id))
        league_stats[lname]["total"] += 1

        cov = coverage.get(match_id, set())
        missing_markets = FULL_SET - cov

        if len(cov) == 0:
            league_stats[lname]["none"] += 1
            reason = "no_nowgoal_mapping" if str(match_id) in unmapped_ids else "fetch_failed_or_no_data"
            missing_rows.append({
                "match_id": match_id,
                "date": date,
                "league": lname,
                "home": home,
                "away": away,
                "reason": reason,
                "markets_present": 0,
            })
        elif missing_markets:
            league_stats[lname]["partial"] += 1
            league_stats[lname]["has_any"] += 1
            partial_rows.append({
                "match_id": match_id,
                "date": date,
                "league": lname,
                "home": home,
                "away": away,
                "markets_present": len(cov),
                "missing": sorted(f"{m}/{p}" for m, p in missing_markets),
            })
        else:
            league_stats[lname]["full_6"] += 1
            league_stats[lname]["has_any"] += 1

    # Totals
    total_any = sum(s["has_any"] for s in league_stats.values())
    total_full = sum(s["full_6"] for s in league_stats.values())
    total_none = sum(s["none"] for s in league_stats.values())
    total_partial = sum(s["partial"] for s in league_stats.values())

    # ─── Markdown Report ───────────────────────────────────────────
    lines = []
    lines.append("# 2021/22 BIG5 NowGoal 赔率回填覆盖报告\n")
    lines.append(f"生成时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append("## 总体\n")
    lines.append(f"- FotMob Finish 场次: **{TOTAL_FINISH}**")
    lines.append(f"- silver_match_odds 覆盖（≥1 行）: **{total_any}** 场 ({total_any/TOTAL_FINISH*100:.1f}%)")
    lines.append(f"- 6 行齐全（3市场×双盘）: **{total_full}** 场 ({total_full/TOTAL_FINISH*100:.1f}%)")
    lines.append(f"- 部分覆盖（1-5 行）: **{total_partial}** 场")
    lines.append(f"- 完全无赔率: **{total_none}** 场\n")

    lines.append("## 各联赛覆盖率\n")
    lines.append("| 联赛 | Finish | 有赔率 | 6行齐全 | 覆盖率 |")
    lines.append("|------|--------|--------|---------|--------|")
    for lname in ["EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1"]:
        s = league_stats[lname]
        pct = s["has_any"] / s["total"] * 100 if s["total"] else 0
        lines.append(f"| {lname} | {s['total']} | {s['has_any']} | {s['full_6']} | {pct:.1f}% |")
    lines.append("")

    if missing_rows:
        lines.append(f"## 完全无赔率（{len(missing_rows)} 场）\n")
        for r in missing_rows:
            lines.append(f"- [{r['match_id']}] {r['home']} vs {r['away']} ({r['date']}, {r['league']}) — {r['reason']}")
        lines.append("")

    if partial_rows:
        lines.append(f"## 部分覆盖（{len(partial_rows)} 场，缺部分市场）\n")
        for r in partial_rows[:50]:  # cap at 50 in markdown
            lines.append(f"- [{r['match_id']}] {r['home']} vs {r['away']} ({r['date']}, {r['league']}) — {r['markets_present']}/6 markets, missing: {', '.join(r['missing'])}")
        if len(partial_rows) > 50:
            lines.append(f"- ... and {len(partial_rows) - 50} more (see CSV)")
        lines.append("")

    if unmapped_ids:
        lines.append(f"## NowGoal 映射失败（{len(unmapped_ids)} 场）\n")
        if os.path.exists(UNMAPPED_PATH):
            with open(UNMAPPED_PATH) as f:
                unmapped = json.load(f)
            for u in unmapped:
                lines.append(f"- [{u['fotmob_id']}] {u['fotmob_home']} vs {u['fotmob_away']} ({u['match_date']}, {u['league']}) — {u['reason']}")
        lines.append("")

    md_path = os.path.join(REPORTS_DIR, "nowgoal_2122_coverage.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Markdown report: {md_path}")

    # ─── CSV ───────────────────────────────────────────────────────
    csv_path = os.path.join(REPORTS_DIR, "nowgoal_2122_coverage.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["match_id", "date", "league", "home", "away",
                                           "markets_present", "status", "notes"])
        w.writeheader()

        all_match_ids = {m[0] for m in all_matches}
        match_lookup = {m[0]: m for m in all_matches}

        for match_id, date, league_id, home, away in all_matches:
            cov = coverage.get(match_id, set())
            lname = LEAGUE_NAMES.get(league_id, str(league_id))
            n = len(cov)
            if n == 6:
                status = "full"
                notes = ""
            elif n > 0:
                status = "partial"
                notes = f"missing: {', '.join(sorted(f'{m}/{p}' for m,p in FULL_SET - cov))}"
            else:
                status = "none"
                notes = "no_mapping" if str(match_id) in unmapped_ids else "no_data"
            w.writerow({
                "match_id": match_id, "date": date, "league": lname,
                "home": home, "away": away, "markets_present": n,
                "status": status, "notes": notes,
            })
    print(f"CSV report: {csv_path}")

    # Print summary
    print(f"\n=== Summary ===")
    print(f"{'League':<12} {'Finish':>7} {'Any odds':>9} {'Full 6':>7} {'Coverage':>9}")
    print("-" * 48)
    for lname in ["EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1"]:
        s = league_stats[lname]
        pct = s["has_any"] / s["total"] * 100 if s["total"] else 0
        print(f"{lname:<12} {s['total']:>7} {s['has_any']:>9} {s['full_6']:>7} {pct:>8.1f}%")
    print("-" * 48)
    print(f"{'TOTAL':<12} {TOTAL_FINISH:>7} {total_any:>9} {total_full:>7} {total_any/TOTAL_FINISH*100:>8.1f}%")


if __name__ == "__main__":
    main()
