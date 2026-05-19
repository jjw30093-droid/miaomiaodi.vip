"""
Phase 3: Fetch NowGoal odds for all mapped 2021/22 BIG5 matches.
Uses the same endpoint as production titan_odds_spider.py.
Output: odds/match_odds_data_2122.json (CLAUDE.md §25 envelope format)

Runs serially with 2.5-5s delay between requests (~1.5-2.2 hours for 1622 matches).
Supports resume: already-fetched fotmob_ids are skipped.
"""

import json
import os
import random
import sqlite3
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAPPING_PATH = os.path.join(BACKEND_DIR, "data", "nowgoal_2122_mapping.json")
OUT_PATH = os.path.join(BACKEND_DIR, "odds", "match_odds_data_2122.json")
DB_PATH = os.path.join(BACKEND_DIR, "football_uk.db")

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

# Identical to titan_odds_spider.py production settings
TARGET_CIDS = [8, 31]
HEADERS = {
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9",
    "referer": "https://www.nowgoal26.com/football/fixture",
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
}


def load_match_info(fotmob_ids: list) -> dict:
    """Load Home_Team_Name, Away_Team_Name, Date from dim_match."""
    if not fotmob_ids:
        return {}
    conn = sqlite3.connect(DB_PATH)
    placeholders = ",".join("?" * len(fotmob_ids))
    rows = conn.execute(
        f"SELECT Match_ID, Home_Team_Name, Away_Team_Name, Date FROM dim_match WHERE Match_ID IN ({placeholders})",
        fotmob_ids,
    ).fetchall()
    conn.close()
    return {r[0]: {"home": r[1], "away": r[2], "date": r[3]} for r in rows}


def fetch_odds(titan_id: str, max_retries: int = 3) -> dict | None:
    """Direct copy of titan_odds_spider.fetch_and_parse_json_odds logic."""
    for attempt in range(max_retries):
        flesh_val = random.random()
        url = (
            f"https://www.nowgoal26.com/ajax/soccerajax"
            f"?type=14&t=1&id={titan_id}&h=0&s=0&flesh={flesh_val}"
        )
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                time.sleep(random.uniform(2.0, 4.0))
                continue

            if "Just a moment" in resp.text or "cloudflare" in resp.text.lower():
                time.sleep(random.uniform(5.0, 10.0))
                continue

            data = resp.json()
            mixodds = data.get("Data", {}).get("mixodds", [])
            if not mixodds:
                return None

            def format_market(m_data, is_euro=False):
                if not m_data:
                    return None
                f = m_data.get("f", {})
                l = m_data.get("l", {})
                if not f or not l:
                    return None
                if not any(str(v).strip() for v in f.values()):
                    return None
                if is_euro:
                    return {
                        "initial": {"home": f.get("u"), "draw": f.get("g"), "away": f.get("d")},
                        "latest": {"home": l.get("u"), "draw": l.get("g"), "away": l.get("d")},
                    }
                else:
                    return {
                        "initial": {
                            "over_or_home": f.get("u"),
                            "line": f.get("g"),
                            "under_or_away": f.get("d"),
                        },
                        "latest": {
                            "over_or_home": l.get("u"),
                            "line": l.get("g"),
                            "under_or_away": l.get("d"),
                        },
                    }

            def bookie_valid(b):
                for key in ["euro", "ah", "ou"]:
                    mkt = b.get(key) or {}
                    f = mkt.get("f") or {}
                    if any(str(v).strip() for v in f.values()):
                        return True
                return False

            target = None
            for cid in TARGET_CIDS:
                candidate = next((b for b in mixodds if b.get("cid") == cid), None)
                if candidate and bookie_valid(candidate):
                    target = candidate
                    break
            if not target:
                target = next((b for b in mixodds if bookie_valid(b)), None)
            if not target:
                return None

            return {
                "provider": target.get("cn"),
                "asian_handicap": format_market(target.get("ah")),
                "over_under": format_market(target.get("ou")),
                "european_1x2": format_market(target.get("euro"), is_euro=True),
            }

        except requests.exceptions.ReadTimeout:
            time.sleep(random.uniform(2.0, 4.0))
        except Exception as e:
            print(f"    [ERROR] {e}")
            time.sleep(random.uniform(1.0, 2.0))

    return None


def apply_swap(odds: dict, is_swapped: bool) -> dict:
    """Flip home/away odds when NowGoal has teams reversed."""
    if not is_swapped or not odds:
        return odds
    result = dict(odds)

    def swap_market(m):
        if not m:
            return m
        out = {}
        for period in ("initial", "latest"):
            p = m.get(period)
            if not p:
                out[period] = p
                continue
            out[period] = {
                "over_or_home": p.get("under_or_away"),
                "line": p.get("line"),
                "under_or_away": p.get("over_or_home"),
            }
        return out

    def swap_euro(m):
        if not m:
            return m
        out = {}
        for period in ("initial", "latest"):
            p = m.get(period)
            if not p:
                out[period] = p
                continue
            out[period] = {
                "home": p.get("away"),
                "draw": p.get("draw"),
                "away": p.get("home"),
            }
        return out

    result["asian_handicap"] = swap_market(odds.get("asian_handicap"))
    result["european_1x2"] = swap_euro(odds.get("european_1x2"))
    # OU line is symmetric — no swap needed
    return result


def load_existing_output() -> dict:
    """Load previously fetched results for resume support."""
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            items = json.load(f)
        return {item["fotmob_id"]: item for item in items}
    return {}


def save_output(records: dict):
    items = list(records.values())
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def main():
    print("=== Phase 3: Fetch NowGoal 2021/22 Odds ===")

    with open(MAPPING_PATH, encoding="utf-8") as f:
        mapping = json.load(f)
    print(f"Mapped matches: {len(mapping)}")

    # Load match info (team names + dates)
    fotmob_ids = [int(fid) for fid in mapping.keys()]
    match_info = load_match_info(fotmob_ids)

    # Resume support
    existing = load_existing_output()
    print(f"Already fetched: {len(existing)}")

    records = dict(existing)
    total = len(mapping)
    done = 0
    skipped = 0
    failed = 0

    items = sorted(mapping.items(), key=lambda x: match_info.get(int(x[0]), {}).get("date", ""))

    for fotmob_id, m in items:
        if fotmob_id in records:
            skipped += 1
            done += 1
            continue

        titan_id = m["titan_id"]
        is_swapped = m["is_swapped"]
        info = match_info.get(int(fotmob_id), {})
        home = info.get("home", "?")
        away = info.get("away", "?")
        date_str = info.get("date", "?")

        print(f"[{done+1}/{total}] {date_str} | {home} vs {away} | titan={titan_id}", end="", flush=True)

        odds = fetch_odds(titan_id)
        if odds:
            odds = apply_swap(odds, is_swapped)
            records[fotmob_id] = {
                "fotmob_id": fotmob_id,
                "titan_id": titan_id,
                "match_name": f"{home} vs {away}",
                "match_date": date_str,
                "odds": odds,
            }
            markets_present = sum(1 for k in ("asian_handicap", "over_under", "european_1x2") if odds.get(k))
            print(f" ✓ ({markets_present}/3 markets)")
        else:
            failed += 1
            print(f" ✗ no data")

        done += 1

        # Save every 50 matches for crash recovery
        if done % 50 == 0:
            save_output(records)
            print(f"  [checkpoint] saved {len(records)} records (done={done}, failed={failed})")

        # Rate limit: 2.5-5s per request
        time.sleep(random.uniform(2.5, 5.0))

    # Final save
    save_output(records)

    print(f"\n=== Summary ===")
    print(f"Total mapped:    {total}")
    print(f"Already cached:  {skipped}")
    print(f"Newly fetched:   {done - skipped - failed}")
    print(f"Failed (no data):{failed}")
    print(f"In output file:  {len(records)}")
    print(f"Output: {OUT_PATH}")


if __name__ == "__main__":
    main()
