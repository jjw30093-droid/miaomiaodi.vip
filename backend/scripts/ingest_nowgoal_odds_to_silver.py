"""
Ingest NowGoal odds into silver_match_odds for any season.
Supports market filtering (default: OU only) and cleans up old footballdata OU rows.

Usage:
  python3 ingest_nowgoal_odds_to_silver.py --season 2023/2024 --season-tag 2324 --markets ou
  python3 ingest_nowgoal_odds_to_silver.py --season 2024/2025 --season-tag 2425 --markets ou
  python3 ingest_nowgoal_odds_to_silver.py --season 2022/2023 --season-tag 2223 --markets all

--markets: comma-separated list of markets to ingest (ou, ah, 1x2), or 'all'
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BACKEND_DIR, "football_uk.db")

from silver_builder import _parse_nowgoal_nested


def parse_markets_arg(markets_str: str) -> set | None:
    """Parse --markets arg. Returns None for 'all', else a set of market names."""
    if markets_str.strip().lower() == "all":
        return None  # None means no filter
    return {m.strip().lower() for m in markets_str.split(",")}


def ingest(conn: sqlite3.Connection, season: str, tag: str, markets_filter: set | None) -> int:
    odds_path = os.path.join(BACKEND_DIR, "odds", f"match_odds_data_{tag}.json")

    if not os.path.exists(odds_path):
        print(f"ERROR: {odds_path} not found. Run fetch_nowgoal_odds.py --season-tag {tag} first.")
        return 0

    with open(odds_path, encoding="utf-8") as f:
        records = json.load(f)

    # Guard against §25 envelope corruption
    valid_records = [r for r in records if "fotmob_id" in r and "odds" in r]
    if len(valid_records) < len(records):
        print(f"  ⚠️  Skipped {len(records) - len(valid_records)} corrupted records (missing fotmob_id or odds)")
    print(f"Records in JSON: {len(valid_records)}")

    # Build fotmob_id → (match_id, match_date) map
    db_season = season  # e.g. "2023/2024"
    dim_rows = conn.execute(
        "SELECT Match_ID, Date FROM dim_match WHERE Season=? AND League_ID IN (47,87,54,55,53)",
        (db_season,)
    ).fetchall()
    mid_map = {str(r[0]): (int(r[0]), r[1] or "") for r in dim_rows}
    print(f"dim_match {season} BIG5 entries: {len(mid_map)}")

    if markets_filter:
        print(f"Market filter: {sorted(markets_filter)}")
    else:
        print("Market filter: all markets")

    count = 0
    skipped_no_match = 0
    skipped_market = 0
    now_ts = datetime.now().isoformat()

    for rec in valid_records:
        fotmob_id = str(rec.get("fotmob_id", ""))
        if not fotmob_id or fotmob_id not in mid_map:
            skipped_no_match += 1
            continue

        match_id, match_date = mid_map[fotmob_id]
        odds_blob = rec.get("odds") or {}
        provider = odds_blob.get("provider", "Bet365") or "Bet365"

        market_rows = _parse_nowgoal_nested(rec, match_id, match_date, provider, now_ts)

        for row in market_rows:
            (market, period, raw_h, raw_d, raw_a, raw_line,
             fair_h, fair_d, fair_a, overround,
             mid, mdate, prov, ts) = row

            # Apply market filter
            if markets_filter is not None and market not in markets_filter:
                skipped_market += 1
                continue

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
    print(f"Rows written (UPSERT): {count}")
    if skipped_no_match:
        print(f"Skipped (no dim_match entry): {skipped_no_match}")

    # ── DELETE old footballdata OU rows where nowgoal OU now exists ──────
    # Only deletes for match_ids that now have a nowgoal OU replacement.
    # Strictly scoped to market='ou' AND source='footballdata'.
    if markets_filter is None or "ou" in markets_filter:
        delete_result = conn.execute("""
            DELETE FROM silver_match_odds
            WHERE source='footballdata' AND market='ou'
              AND match_id IN (
                SELECT d.Match_ID FROM dim_match d
                WHERE d.Season=?
                  AND d.League_ID IN (47,87,54,55,53)
                  AND EXISTS (
                    SELECT 1 FROM silver_match_odds s2
                    WHERE s2.match_id = d.Match_ID
                      AND s2.market = 'ou'
                      AND s2.source = 'nowgoal'
                  )
              )
        """, (db_season,))
        conn.commit()
        deleted = delete_result.rowcount
        print(f"Deleted old footballdata OU rows (replaced by nowgoal): {deleted}")
    else:
        print("Skipping footballdata OU cleanup (ou not in markets filter)")

    return count


def main():
    parser = argparse.ArgumentParser(description="Ingest NowGoal odds into silver_match_odds")
    parser.add_argument("--season", required=True,
                        help="Season in DB format, e.g. 2023/2024")
    parser.add_argument("--season-tag", required=True, dest="season_tag",
                        help="Short tag matching odds file, e.g. 2324")
    parser.add_argument("--markets", default="ou",
                        help="Markets to ingest: 'ou', 'ah', '1x2', comma-separated, or 'all' (default: ou)")
    args = parser.parse_args()

    season = args.season
    tag = args.season_tag
    markets_filter = parse_markets_arg(args.markets)

    print(f"=== Ingest NowGoal Odds → silver_match_odds: {season} (tag={tag}) ===")

    conn = sqlite3.connect(DB_PATH)
    rows_written = ingest(conn, season, tag, markets_filter)

    # Verification query
    result = conn.execute("""
        SELECT market, period, COUNT(*) as cnt
        FROM silver_match_odds s
        JOIN dim_match d ON d.Match_ID = s.match_id
        WHERE d.Season=?
          AND d.League_ID IN (47,87,54,55,53)
          AND d.status='Finish'
          AND s.source='nowgoal'
        GROUP BY market, period
        ORDER BY market, period
    """, (season,)).fetchall()

    print(f"\nsilver_match_odds {season} nowgoal coverage:")
    print(f"  {'market':<8} {'period':<10} {'count':>6}")
    print(f"  {'-'*26}")
    for market, period, cnt in result:
        print(f"  {market:<8} {period:<10} {cnt:>6}")

    covered = conn.execute("""
        SELECT COUNT(DISTINCT s.match_id)
        FROM silver_match_odds s
        JOIN dim_match d ON d.Match_ID = s.match_id
        WHERE d.Season=?
          AND d.League_ID IN (47,87,54,55,53)
          AND d.status='Finish'
          AND s.source='nowgoal'
    """, (season,)).fetchone()[0]

    total_finish = conn.execute("""
        SELECT COUNT(*) FROM dim_match
        WHERE Season=? AND League_ID IN (47,87,54,55,53) AND status='Finish'
    """, (season,)).fetchone()[0]

    print(f"\n  Distinct matches with ≥1 nowgoal odds row: {covered} / {total_finish}")

    # Verify no footballdata OU rows remain for matches that have nowgoal OU
    remaining_fd_ou = conn.execute("""
        SELECT COUNT(*) FROM silver_match_odds s
        JOIN dim_match d ON d.Match_ID = s.match_id
        WHERE d.Season=? AND d.League_ID IN (47,87,54,55,53)
          AND s.source='footballdata' AND s.market='ou'
    """, (season,)).fetchone()[0]
    print(f"  Remaining footballdata OU rows: {remaining_fd_ou} (should be ~0 if nowgoal covered all)")

    conn.close()


if __name__ == "__main__":
    main()
