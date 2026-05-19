"""
Backfill ah_correct in prediction_audit.
AH result: home team beats the line = home win; otherwise away wins.
Half-line (e.g. 0.5, 1.5) → no push. Quarter-line → half-push not handled here, treat as exact.
"""
import sqlite3
import sys

DB = "backend/football_uk.db"


def ah_result(home_goals: int, away_goals: int, line: float) -> int | None:
    """Return 1 if AH home pick wins, 0 if loses, None if push."""
    # Adjusted score: home - away - line (home team must cover)
    adj = home_goals - away_goals - line
    if adj > 0:
        return 1   # home covers
    elif adj < 0:
        return 0   # away covers
    else:
        return None  # push


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT match_id, home_name, away_name, match_date,
               pred_ah_pick, pred_ah_line,
               actual_home_score, actual_away_score
        FROM prediction_audit
        WHERE pred_ah_pick IS NOT NULL
          AND actual_home_score IS NOT NULL
          AND actual_away_score IS NOT NULL
    """)
    rows = cur.fetchall()
    print(f"Found {len(rows)} rows with AH predictions and outcomes")

    updated = skipped = 0
    for match_id, home, away, date, pick, line, hg, ag in rows:
        if line is None:
            skipped += 1
            continue

        result = ah_result(hg, ag, line)
        if result is None:
            # push — set ah_correct = -1 to indicate void
            correct = -1
        else:
            # pick is 'home' or 'away'; compare with result
            if pick == 'home':
                correct = 1 if result == 1 else 0
            else:
                correct = 1 if result == 0 else 0

        cur.execute(
            "UPDATE prediction_audit SET ah_correct = ? WHERE match_id = ?",
            (correct, match_id)
        )
        updated += 1

    conn.commit()
    conn.close()
    print(f"Updated: {updated}, Skipped (no line): {skipped}")


if __name__ == "__main__":
    main()
