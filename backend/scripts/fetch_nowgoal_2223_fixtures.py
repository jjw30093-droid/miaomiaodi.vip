"""
Phase 1.2: Fetch NowGoal 2022/23 BIG5 fixture list.
Endpoint: https://football.nowgoal26.com/jsData/matchResult/json/2022-2023/s{league_id}_en.json
Output: data/nowgoal_2223_fixtures.json

League IDs confirmed via probe:
  36 = English Premier League (380 matches)
  31 = Spanish La Liga (380 matches)
   8 = German Bundesliga (306 matches)
  34 = Italy Serie A (380 matches)
  11 = France Ligue 1 (380 matches)
"""

import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(BACKEND_DIR, "data", "nowgoal_2223_fixtures.json")
os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

SEASON = "2022-2023"

BIG5_LEAGUES = {
    36: "English Premier League",
    31: "Spanish La Liga",
    8:  "German Bundesliga",
    34: "Italy Serie A",
    11: "France Ligue 1",
}

EXPECTED_COUNTS = {36: 380, 31: 380, 8: 306, 34: 380, 11: 380}

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://football.nowgoal26.com/league/36",
}


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(BASE_HEADERS)
    s.trust_env = False
    return s


def fetch_league_json(s: requests.Session, league_id: int) -> dict:
    url = f"https://football.nowgoal26.com/jsData/matchResult/json/{SEASON}/s{league_id}_en.json"
    for attempt in range(3):
        try:
            r = s.get(url, timeout=15)
            if r.status_code == 200:
                return json.loads(r.content.decode("utf-8-sig"))
            print(f"  HTTP {r.status_code} (attempt {attempt+1})")
            time.sleep(5 * (attempt + 1))
        except Exception as e:
            print(f"  Error (attempt {attempt+1}): {e}")
            time.sleep(5)
    raise RuntimeError(f"Failed to fetch league {league_id} after 3 attempts")


def extract_matches(sched: dict) -> list:
    """Handle both flat {R_1: [...]} and nested {sub_NNN: {R_1: [...]}} structures."""
    matches = []
    for v in sched.values():
        if isinstance(v, list):
            matches.extend(v)
        elif isinstance(v, dict):
            for rounds in v.values():
                if isinstance(rounds, list):
                    matches.extend(rounds)
    return matches


def get_team_map(team_info: list) -> dict:
    """Build {team_id → team_name} from TeamInfo array."""
    tm = {}
    for entry in team_info:
        if isinstance(entry, list) and len(entry) >= 2:
            tm[entry[0]] = entry[1]
    return tm


def main():
    print("=== Phase 1.2: Fetch NowGoal 2022/23 BIG5 Fixtures ===")
    s = make_session()
    all_fixtures = []

    for league_id, league_name in BIG5_LEAGUES.items():
        print(f"\nFetching {league_name} (id={league_id})...")
        data = fetch_league_json(s, league_id)

        sched = data.get("ScheduleList", {})
        raw_matches = extract_matches(sched)
        team_map = get_team_map(data.get("TeamInfo", []))
        expected = EXPECTED_COUNTS[league_id]

        print(f"  Raw matches: {len(raw_matches)} (expected ~{expected})")

        for m in raw_matches:
            if not isinstance(m, list) or len(m) < 6:
                continue
            titan_id = m[0]
            kickoff = m[3]  # local time string "YYYY-MM-DD HH:MM"
            home_id = m[4]
            away_id = m[5]
            score = m[6] if len(m) > 6 else ""

            home_name = team_map.get(home_id, str(home_id))
            away_name = team_map.get(away_id, str(away_id))

            all_fixtures.append({
                "titan_id": str(titan_id),
                "league_id_nowgoal": league_id,
                "league_name": league_name,
                "kickoff_local": kickoff,
                "home_id": home_id,
                "away_id": away_id,
                "home_name": home_name,
                "away_name": away_name,
                "score": score,
            })

        time.sleep(1.5)

    # Write output
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_fixtures, f, ensure_ascii=False, indent=2)

    print(f"\n=== Summary ===")
    from collections import Counter
    by_league = Counter(f["league_name"] for f in all_fixtures)
    for name, cnt in sorted(by_league.items()):
        print(f"  {name}: {cnt} fixtures")
    print(f"\nTotal: {len(all_fixtures)} fixtures")
    print(f"Output: {OUT_PATH}")


if __name__ == "__main__":
    main()
