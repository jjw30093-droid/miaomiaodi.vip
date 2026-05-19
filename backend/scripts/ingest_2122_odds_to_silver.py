"""
Phase 4: Ingest 2021/22 NowGoal odds into silver_match_odds.
Reads odds/match_odds_data_2122.json → UPSERT silver_match_odds.
Uses the same _parse_nowgoal_nested + UPSERT logic as silver_builder._ingest_nowgoal_odds.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ODDS_PATH = os.path.join(BACKEND_DIR, "odds", "match_odds_data_2122.json")
DB_PATH = os.path.join(BACKEND_DIR, "football_uk.db")

# Import silver_builder helpers (don't trigger its main() logic)
from silver_builder import _parse_nowgoal_nested


def ingest(conn: sqlite3.Connection) -> int:
    if not os.path.exists(ODDS_PATH):
        print(f"ERROR: {ODDS_PATH} not found. Run fetch_nowgoal_odds_2122.py first.")
        return 0

    with open(ODDS_PATH, encoding="utf-8") as f:
        records = json.load(f)
    print(f"Records in JSON: {len(records)}")

    # Build fotmob_id → (match_id, match_date) map
    dim_rows = conn.execute(
        "SELECT Match_ID, Date FROM dim_match WHERE Season='2021/2022' AND League_ID IN (47,87,54,55,53)"
    ).fetchall()
    mid_map = {str(r[0]): (int(r[0]), r[1] or "") for r in dim_rows}
    print(f"dim_match 2021/22 BIG5 entries: {len(mid_map)}")

    count = 0
    skipped = 0
    now_ts = datetime.now().isoformat()

    for rec in records:
        fotmob_id = str(rec.get("fotmob_id", ""))
        if not fotmob_id or fotmob_id not in mid_map:
            skipped += 1
            continue

        match_id, match_date = mid_map[fotmob_id]
        odds_blob = rec.get("odds") or {}
        provider = odds_blob.get("provider", "Bet365") or "Bet365"

        market_rows = _parse_nowgoal_nested(rec, match_id, match_date, provider, now_ts)

        for row in market_rows:
            (market, period, raw_h, raw_d, raw_a, raw_line,
             fair_h, fair_d, fair_a, overround,
             mid, mdate, prov, ts) = row
            try:
                conn.execute("""
                    INSERT INTO silver_match_odds
                        (match_id, match_date, market, period, provider,
                         raw_home, raw_draw, raw_away, raw_line,
                         fair_home, fair_draw, fair_away, overround,
                         source, scraped_at)
                    VALUES (?, ?, ?, ?, ?,
                            ?, ?, ?, ?,
                            ?, ?, ?, ?,
                            'nowgoal', ?)
                    ON CONFLICT(match_id, market, period, source) DO UPDATE SET
                        raw_home=excluded.raw_home, raw_draw=excluded.raw_draw,
                        raw_away=excluded.raw_away, raw_line=excluded.raw_line,
                        fair_home=excluded.fair_home, fair_draw=excluded.fair_draw,
                        fair_away=excluded.fair_away, overround=excluded.overround,
                        scraped_at=excluded.scraped_at
                """, (mid, mdate, market, period, prov,
                      raw_h, raw_d, raw_a, raw_line,
                      fair_h, fair_d, fair_a, overround,
                      ts))
                count += 1
            except Exception as e:
                print(f"  UPSERT ERROR [{mid}/{market}/{period}]: {e}")

    conn.commit()
    return count


def main():
    print("=== Phase 4: Ingest 2021/22 Odds → silver_match_odds ===")

    conn = sqlite3.connect(DB_PATH)
    rows_written = ingest(conn)

    # Verification query
    print(f"\nRows written (UPSERT): {rows_written}")

    result = conn.execute("""
        SELECT market, period, COUNT(*) as cnt
        FROM silver_match_odds s
        JOIN dim_match d ON d.Match_ID = s.match_id
        WHERE d.Season='2021/2022'
          AND d.League_ID IN (47,87,54,55,53)
          AND d.status='Finish'
          AND s.source='nowgoal'
        GROUP BY market, period
        ORDER BY market, period
    """).fetchall()

    print("\nsilver_match_odds 2021/22 coverage:")
    print(f"  {'market':<8} {'period':<10} {'count':>6}")
    print(f"  {'-'*26}")
    for market, period, cnt in result:
        print(f"  {market:<8} {period:<10} {cnt:>6}")

    covered = conn.execute("""
        SELECT COUNT(DISTINCT s.match_id)
        FROM silver_match_odds s
        JOIN dim_match d ON d.Match_ID = s.match_id
        WHERE d.Season='2021/2022'
          AND d.League_ID IN (47,87,54,55,53)
          AND d.status='Finish'
          AND s.source='nowgoal'
    """).fetchone()[0]
    print(f"\n  Distinct matches with ≥1 odds row: {covered} / 1624")

    conn.close()


if __name__ == "__main__":
    main()
