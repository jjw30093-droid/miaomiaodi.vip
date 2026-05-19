import requests, sqlite3, logging, datetime

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "football_uk.db"))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def scrape_postmatch(match_id: str, match: dict):
    url = f"https://www.fotmob.com/api/matchDetails?matchId={match_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200: return
        data = resp.json()
        
        # 提取比分与状态
        header = data.get("header", {})
        status = header.get("status", {})
        if not status.get("finished"):
            return # 比赛尚未结束

        home_score = header.get("teams", [])[0].get("score")
        away_score = header.get("teams", [])[1].get("score")
        
        postmatch_data = {
            "final_score": f"{home_score} - {away_score}",
            "stats_summary": "FotMob 赛后核心数据已同步。"
        }

        # 调用报告生成器 (REVIEW 模式)
        from report_generator import generate_report
        generate_report(match_id, match, mode="review", postmatch_data=postmatch_data)
        
        # 更新数据库
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE match_pipeline SET status='REVIEW_GENERATED', review_generated_at=? WHERE match_id=?",
            [datetime.datetime.now().isoformat(), str(match_id)]
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error scraping postmatch for {match_id}: {e}")
