import os, json, time, random, requests
from datetime import datetime, timedelta

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
ODDS_OUTPUT_PATH = os.path.join(PROJECT_ROOT, "odds", "match_odds_data.json")
HEADERS = {
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9",
    "referer": "https://www.nowgoal.com/football/fixture",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
}
TARGET_CIDS = [8, 31]

def get_titan_id_via_nowgoal(date_str, home_team_en, away_team_en):
    try:
        target_date = datetime.fromisoformat(date_str.split(' ')[0]) if '-' in date_str else datetime.strptime(date_str, "%Y%m%d")
    except Exception:
        target_date = datetime.now()

    dates_to_check = [target_date, target_date - timedelta(days=1), target_date + timedelta(days=1)]

    def calculate_overlap(team_name, target_text):
        words = [w.lower() for w in team_name.split() if len(w) > 2 and w.lower() not in ['fc', 'afc', 'united', 'city']]
        if not words: return 0
        hits = sum(1 for w in words if w in target_text)
        return hits / len(words)

    best_id, highest_score = None, 0.0
    for d in dates_to_check:
        formatted_date = d.strftime("%Y-%m-%d")
        url = f"https://www.nowgoal.com/ajax/SoccerAjax?type=6&date={formatted_date}&order=time&timezone=8&flesh={random.random()}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200: continue
            raw_data = resp.json().get("Data", "") if isinstance(resp.json(), dict) else resp.text
            raw_data = raw_data.replace('\r\n', '\n').replace('\r', '\n')

            for line in raw_data.split('\n'):
                if line.startswith('A['):
                    try:
                        parts = line.split('=')[1].strip().split("'")
                        if len(parts) >= 5:
                            tid = parts[0].strip('[').split(',')[0]
                            h_score = calculate_overlap(home_team_en, parts[1].lower())
                            a_score = calculate_overlap(away_team_en, parts[3].lower())
                            avg = (h_score + a_score) / 2
                            if avg > highest_score and avg >= 0.5:
                                highest_score, best_id = avg, tid
                    except Exception: continue
            # 完美匹配时提前退出，否则继续扫描其他日期
            if highest_score >= 1.0:
                break
        except Exception: continue
    return best_id

def fetch_and_parse_json_odds(titan_id):
    url = f"https://www.nowgoal.com/ajax/soccerajax?type=14&t=1&id={titan_id}&h=0&s=0&flesh={random.random()}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200: return None
        data = resp.json()
        mixodds = data.get("Data", {}).get("mixodds", [])
        if not mixodds: return None
        
        bookie = next((b for b in mixodds if b.get("cid") in TARGET_CIDS), mixodds[0])
        def format_market(m, is_euro=False):
            if not m or not m.get('f') or not m.get('l'): return None
            f, l = m['f'], m['l']
            if is_euro:
                return {"initial": {"home": f.get('u'), "draw": f.get('g'), "away": f.get('d')},
                        "latest": {"home": l.get('u'), "draw": l.get('g'), "away": l.get('d')}}
            return {"initial": {"over_or_home": f.get('u'), "line": f.get('g'), "under_or_away": f.get('d')},
                    "latest": {"over_or_home": l.get('u'), "line": l.get('g'), "under_or_away": l.get('d')}}

        return {
            "provider": bookie.get("cn"),
            "asian_handicap": format_market(bookie.get("ah")),
            "over_under": format_market(bookie.get("ou")),
            "european_1x2": format_market(bookie.get("euro"), is_euro=True)
        }
    except Exception: return None

def fetch_odds_for_match(match_id: str, match: dict):
    m_name = match.get("match_name", "")
    h, a = (m_name.split(" vs ") if " vs " in m_name else (match.get("home_team"), match.get("away_team")))
    date = match.get("kickoff_time", datetime.now().isoformat())
    
    titan_id = get_titan_id_via_nowgoal(date, str(h), str(a))
    if not titan_id: return
    
    odds = fetch_and_parse_json_odds(titan_id)
    if not odds: return

    existing = []
    if os.path.exists(ODDS_OUTPUT_PATH):
        try:
            with open(ODDS_OUTPUT_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception: pass
    
    merged = [r for r in existing if str(r["fotmob_id"]) != str(match_id)]
    merged.append({"fotmob_id": str(match_id), "titan_id": titan_id, "match_name": m_name, "odds": odds})
    
    os.makedirs(os.path.dirname(ODDS_OUTPUT_PATH), exist_ok=True)
    with open(ODDS_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=4)
