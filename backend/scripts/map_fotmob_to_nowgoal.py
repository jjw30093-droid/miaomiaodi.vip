"""
Map FotMob match IDs to NowGoal titan_ids for any season.
Uses team name fuzzy matching via team_resolver.resolve_nowgoal_match().

Usage:
  python3 map_fotmob_to_nowgoal.py --season 2023/2024 --season-tag 2324
  python3 map_fotmob_to_nowgoal.py --season 2024/2025 --season-tag 2425

Note: --season uses DB format YYYY/YYYY; --season-tag is the short file tag.

Input:
  - dim_match (FotMob {season} Finish matches)
  - data/nowgoal_{tag}_fixtures.json

Output:
  - data/nowgoal_{tag}_mapping.json   {fotmob_id → {titan_id, is_swapped, score}}
  - data/nowgoal_{tag}_unmapped.json  [unmapped matches for human review]
"""

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from team_resolver import resolve_nowgoal_match

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BACKEND_DIR, "football_uk.db")

# FotMob League_ID → NowGoal league_id
LEAGUE_MAP = {
    47: 36,   # EPL
    87: 31,   # La Liga
    54: 8,    # Bundesliga
    55: 34,   # Serie A
    53: 11,   # Ligue 1
}

LEAGUE_NAMES = {47: "EPL", 87: "La Liga", 54: "Bundesliga", 55: "Serie A", 53: "Ligue 1"}

MIN_SCORE = 0.5

# Team name normalization for _legacy_overlap compatibility
_UMLAUT = str.maketrans("äöüÄÖÜß", "aouAOUs")

def normalize_team(name: str) -> str:
    """Normalize team name before _legacy_overlap matching."""
    import re
    name = re.sub(r"^\d+\.\s*", "", name)
    name = name.replace("-", " ")
    name = name.translate(_UMLAUT)
    return name


def load_fotmob_matches(conn: sqlite3.Connection, season: str) -> list[dict]:
    rows = conn.execute("""
        SELECT Match_ID, Date, League_ID, Home_Team_Name, Away_Team_Name
        FROM dim_match
        WHERE Season=?
          AND League_ID IN (47,87,54,55,53)
          AND status='Finish'
        ORDER BY Date, Match_ID
    """, (season,)).fetchall()
    return [
        {
            "match_id": r[0],
            "date": r[1],          # UTC date "YYYY-MM-DD"
            "league_id": r[2],
            "home": r[3],
            "away": r[4],
        }
        for r in rows
    ]


def build_nowgoal_index(fixtures: list[dict]) -> dict:
    """
    Index NowGoal fixtures by (nowgoal_league_id, date_str).
    date_str extracted from kickoff_local (CST/UTC+8):
      CST date can be UTC+1 day → index under both date and date-1day.
    """
    idx = defaultdict(list)
    for f in fixtures:
        kickoff = f["kickoff_local"]  # "YYYY-MM-DD HH:MM"
        date_str = kickoff[:10]
        lid = f["league_id_nowgoal"]
        idx[(lid, date_str)].append(f)
        # Also index under date - 1 day (for late UTC matches appearing next CST day)
        d = date.fromisoformat(date_str)
        prev = (d - timedelta(days=1)).isoformat()
        idx[(lid, prev)].append(f)
        # And date + 1 day just in case
        nxt = (d + timedelta(days=1)).isoformat()
        idx[(lid, nxt)].append(f)
    return idx


def match_one(fotmob: dict, candidates: list[dict]) -> tuple[dict | None, float, bool, list]:
    """
    Try to find the best NowGoal candidate for a FotMob match.
    Applies team name normalization before scoring.
    Returns (best_candidate, score, is_swapped, all_scored_candidates).
    """
    fm_home = normalize_team(fotmob["home"])
    fm_away = normalize_team(fotmob["away"])

    scored = []
    for c in candidates:
        score, is_swapped = resolve_nowgoal_match(
            fm_home, fm_away,
            c["home_name"], c["away_name"]
        )
        scored.append({
            "titan_id": c["titan_id"],
            "nowgoal_home": c["home_name"],
            "nowgoal_away": c["away_name"],
            "kickoff_local": c["kickoff_local"],
            "score": round(score, 4),
            "is_swapped": is_swapped,
            "_obj": c,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    best_entry = scored[0] if scored else None
    best_score = best_entry["score"] if best_entry else -1.0
    best_swapped = best_entry["is_swapped"] if best_entry else False
    best_obj = best_entry["_obj"] if best_entry else None

    # Clean up _obj before returning for human review
    top5 = [{k: v for k, v in e.items() if k != "_obj"} for e in scored[:5]]
    return best_obj, best_score, best_swapped, top5


def main():
    parser = argparse.ArgumentParser(description="Map FotMob IDs to NowGoal titan_ids")
    parser.add_argument("--season", required=True,
                        help="Season in DB format, e.g. 2023/2024")
    parser.add_argument("--season-tag", required=True, dest="season_tag",
                        help="Short tag for filenames, e.g. 2324")
    args = parser.parse_args()

    season = args.season
    tag = args.season_tag

    fixtures_path = os.path.join(BACKEND_DIR, "data", f"nowgoal_{tag}_fixtures.json")
    mapping_path  = os.path.join(BACKEND_DIR, "data", f"nowgoal_{tag}_mapping.json")
    unmapped_path = os.path.join(BACKEND_DIR, "data", f"nowgoal_{tag}_unmapped.json")

    print(f"=== FotMob → NowGoal ID Mapping: {season} (tag={tag}) ===")

    with open(fixtures_path, encoding="utf-8") as f:
        nowgoal_fixtures = json.load(f)
    print(f"NowGoal fixtures loaded: {len(nowgoal_fixtures)}")

    conn = sqlite3.connect(DB_PATH)
    fotmob_matches = load_fotmob_matches(conn, season)
    conn.close()
    print(f"FotMob Finish matches: {len(fotmob_matches)}")

    # Build index
    ng_index = build_nowgoal_index(nowgoal_fixtures)

    mapping = {}
    unmapped = []

    # Track already-matched titan_ids to avoid 1:many
    used_titan_ids = set()

    stats = {"mapped": 0, "unmapped": 0, "duplicate_skip": 0}

    for fm in fotmob_matches:
        ng_league_id = LEAGUE_MAP[fm["league_id"]]
        date_str = fm["date"]  # FotMob UTC date

        # Get candidates: from all 3 date buckets combined, deduplicated
        seen_tids = set()
        candidates = []
        for d_offset in (0, -1, 1):
            d = (date.fromisoformat(date_str) + timedelta(days=d_offset)).isoformat()
            for c in ng_index.get((ng_league_id, d), []):
                if c["titan_id"] not in seen_tids:
                    seen_tids.add(c["titan_id"])
                    candidates.append(c)

        if not candidates:
            unmapped.append({
                "fotmob_id": str(fm["match_id"]),
                "match_date": fm["date"],
                "league": LEAGUE_NAMES[fm["league_id"]],
                "fotmob_home": fm["home"],
                "fotmob_away": fm["away"],
                "candidates": [],
                "reason": "no_nowgoal_fixtures_on_date",
            })
            stats["unmapped"] += 1
            continue

        best, score, is_swapped, top5 = match_one(fm, candidates)

        if score < MIN_SCORE:
            unmapped.append({
                "fotmob_id": str(fm["match_id"]),
                "match_date": fm["date"],
                "league": LEAGUE_NAMES[fm["league_id"]],
                "fotmob_home": fm["home"],
                "fotmob_away": fm["away"],
                "candidates": top5,
                "reason": f"best_score_too_low_{score:.3f}",
            })
            stats["unmapped"] += 1
            continue

        titan_id = best["titan_id"]
        if titan_id in used_titan_ids:
            # Try the next-best candidate that's not yet used
            fallback = None
            for cand in top5[1:]:
                if cand["score"] >= MIN_SCORE and cand["titan_id"] not in used_titan_ids:
                    fallback = cand
                    break

            if fallback:
                titan_id = fallback["titan_id"]
                is_swapped = fallback["is_swapped"]
                score = fallback["score"]
                # Find the original NowGoal fixture object
                best = next(
                    (c for c in candidates if c["titan_id"] == titan_id), None
                )
            else:
                unmapped.append({
                    "fotmob_id": str(fm["match_id"]),
                    "match_date": fm["date"],
                    "league": LEAGUE_NAMES[fm["league_id"]],
                    "fotmob_home": fm["home"],
                    "fotmob_away": fm["away"],
                    "candidates": top5,
                    "reason": f"titan_id_{titan_id}_already_used_no_fallback",
                })
                stats["duplicate_skip"] += 1
                stats["unmapped"] += 1
                continue

        used_titan_ids.add(titan_id)
        mapping[str(fm["match_id"])] = {
            "titan_id": titan_id,
            "is_swapped": is_swapped,
            "score": round(score, 4),
            "nowgoal_home": best["home_name"],
            "nowgoal_away": best["away_name"],
            "kickoff_local": best["kickoff_local"],
        }
        stats["mapped"] += 1

    # Save outputs
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    with open(unmapped_path, "w", encoding="utf-8") as f:
        json.dump(unmapped, f, ensure_ascii=False, indent=2)

    total = len(fotmob_matches)
    print(f"\n=== Results ===")
    print(f"Total FotMob matches: {total}")
    print(f"Mapped:   {stats['mapped']} ({stats['mapped']/total*100:.1f}%)")
    print(f"Unmapped: {stats['unmapped']} ({stats['unmapped']/total*100:.1f}%)")
    print(f"  - duplicate skip: {stats['duplicate_skip']}")
    print(f"\nMapping: {mapping_path}")
    print(f"Unmapped: {unmapped_path}")

    if unmapped:
        print(f"\nFirst 10 unmapped:")
        for u in unmapped[:10]:
            print(f"  [{u['league']}] {u['fotmob_home']} vs {u['fotmob_away']} ({u['match_date']}) — {u['reason']}")
            if u["candidates"]:
                print(f"    Best candidate: {u['candidates'][0]['nowgoal_home']} vs {u['candidates'][0]['nowgoal_away']} (score={u['candidates'][0]['score']:.3f})")


if __name__ == "__main__":
    main()
