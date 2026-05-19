#!/usr/bin/env python3
"""
Scan dim_match for BIG5 matches missing OU odds in silver_match_odds.
Outputs a manifest JSON and a console summary table.
"""
import json
import os
import sqlite3
from datetime import date

DB_PATH = os.environ.get("DB_PATH", "/home/ubuntu/app/backend/football_uk.db")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

LEAGUE_NAMES = {47: "EPL", 53: "Serie A", 54: "Bundesliga", 55: "Ligue 1", 87: "La Liga"}

SQL = """
SELECT
    d.Match_ID,
    d.League_ID,
    d.Season,
    d.Date,
    d.Home_Team_Name,
    d.Away_Team_Name,
    SUM(CASE WHEN o.period='opening' THEN 1 ELSE 0 END) AS has_open,
    SUM(CASE WHEN o.period='closing' THEN 1 ELSE 0 END) AS has_close,
    COUNT(CASE WHEN o2.market IN ('1x2','ah') THEN 1 END) AS has_other
FROM dim_match d
LEFT JOIN silver_match_odds o
    ON o.match_id = d.Match_ID AND o.market = 'ou'
LEFT JOIN silver_match_odds o2
    ON o2.match_id = d.Match_ID AND o2.period = 'closing'
WHERE d.status = 'Finish'
  AND d.League_ID IN (47, 53, 54, 55, 87)
GROUP BY d.Match_ID
HAVING has_open = 0 OR has_close = 0
ORDER BY d.League_ID, d.Date
"""

def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(SQL).fetchall()
    con.close()

    manifest = []
    for r in rows:
        missing_periods = []
        if r["has_open"] == 0:
            missing_periods.append("opening")
        if r["has_close"] == 0:
            missing_periods.append("closing")
        manifest.append({
            "match_id": r["Match_ID"],
            "league_id": r["League_ID"],
            "league_name": LEAGUE_NAMES.get(r["League_ID"], str(r["League_ID"])),
            "season": r["Season"],
            "date": r["Date"],
            "home": r["Home_Team_Name"],
            "away": r["Away_Team_Name"],
            "missing_periods": missing_periods,
            "has_other_markets": r["has_other"] > 0,
        })

    # Write manifest
    out_path = os.path.join(OUTPUT_DIR, f"missing_ou_manifest_{date.today().strftime('%Y%m%d')}.json")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # Console summary
    from collections import defaultdict
    by_season_league = defaultdict(int)
    for m in manifest:
        by_season_league[(m["season"], m["league_name"])] += 1

    print(f"\n{'='*60}")
    print(f"Missing OU scan — {date.today()} — Total: {len(manifest)} matches")
    print(f"{'='*60}")
    print(f"{'Season':<12} {'League':<12} {'Missing':>8}")
    print(f"{'-'*34}")
    for (season, league), cnt in sorted(by_season_league.items()):
        print(f"{season:<12} {league:<12} {cnt:>8}")
    print(f"{'-'*34}")
    print(f"{'TOTAL':<25} {len(manifest):>8}")
    print(f"\nManifest written → {out_path}")

if __name__ == "__main__":
    main()
