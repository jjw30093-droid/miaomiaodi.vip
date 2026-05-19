import sqlite3, json, os

PROJECT_ROOT = "/home/ubuntu/app/backend"
DB_PATH = os.path.join(PROJECT_ROOT, "football_uk.db")
ODDS_JSON = os.path.join(PROJECT_ROOT, "odds", "match_odds_data.json")

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    if not os.path.exists(ODDS_JSON):
        print(f"赔率文件不存在: {ODDS_JSON}")
        return
    with open(ODDS_JSON, encoding="utf-8") as f:
        odds_list = json.load(f)
    print(f"JSON 赔率记录总计: {len(odds_list)}")
    
    # 获取已有赔率，避免冲突
    existing = set()
    for r in conn.execute("SELECT HomeTeam, AwayTeam, Date FROM raw_footballdata_odds"):
        existing.add((r[0], r[1], r[2]))
    print(f"raw_footballdata_odds 表当前记录数: {len(existing)}")
    
    inserted = 0
    skipped = 0
    no_match = 0
    
    for item in odds_list:
        fid = str(item.get("fotmob_id", ""))
        odds = item.get("odds", {})
        eu = odds.get("european_1x2", {}).get("latest", {})
        
        if not eu or not eu.get("home"):
            continue
        
        # 查 dim_match 获取标准化队名和日期
        match = conn.execute(
            "SELECT Home_Team_Name, Away_Team_Name, Date FROM dim_match WHERE CAST(Match_ID AS TEXT) = ?",
            (fid,)
        ).fetchone()
        
        if not match:
            no_match += 1
            continue
        
        home, away, date = match[0], match[1], match[2]
        
        if (home, away, date) in existing:
            skipped += 1
            continue
        
        try:
            b365h = float(eu.get("home", 0) or 0)
            b365d = float(eu.get("draw", 0) or 0)
            b365a = float(eu.get("away", 0) or 0)
        except (ValueError, TypeError):
            continue
        
        if b365h <= 1 or b365d <= 1 or b365a <= 1:
            continue
        
        # 解析 Over/Under
        ou = odds.get("over_under", {}).get("latest", {})
        ou_line = float(ou.get("line", 2.5) or 2.5)
        ou_over_water = float(ou.get("over_or_home", 0) or 0)
        ou_under_water = float(ou.get("under_or_away", 0) or 0)
        b365_over = round(1 + ou_over_water, 2) if ou_over_water > 0 else 0
        b365_under = round(1 + ou_under_water, 2) if ou_under_water > 0 else 0
        
        # 解析 Asian Handicap
        ah = odds.get("asian_handicap", {}).get("latest", {})
        ah_line = float(ah.get("line", 0) or 0)
        ah_home_water = float(ah.get("over_or_home", 0) or 0)
        ah_away_water = float(ah.get("under_or_away", 0) or 0)
        
        conn.execute("""
            INSERT OR IGNORE INTO raw_footballdata_odds 
            (HomeTeam, AwayTeam, Date, B365H, B365D, B365A,
             "B365>2.5", "B365<2.5", AHh, B365AHH, B365AHA)
            VALUES (?,?,?,?,?,?, ?,?,?,?,?)
        """, (home, away, date, b365h, b365d, b365a,
              b365_over, b365_under, ah_line, 
              round(1+ah_home_water, 2) if ah_home_water > 0 else 0,
              round(1+ah_away_water, 2) if ah_away_water > 0 else 0))
        inserted += 1
    
    conn.commit()
    
    # 统计覆盖率
    total_finish = conn.execute("SELECT COUNT(*) FROM dim_match WHERE status='Finish' AND home_score IS NOT NULL").fetchone()[0]
    coverage = conn.execute("""
        SELECT COUNT(*) FROM dim_match m
        INNER JOIN raw_footballdata_odds o 
            ON m.Home_Team_Name = o.HomeTeam 
            AND m.Away_Team_Name = o.AwayTeam 
            AND m.Date = o.Date
        WHERE m.status = 'Finish' AND m.home_score IS NOT NULL
    """).fetchone()[0]
    
    print(f"\n✅ 回填统计:")
    print(f"   - 新增记录: {inserted}")
    print(f"   - 跳过(重复): {skipped}")
    print(f"   - 未找到匹配场次: {no_match}")
    print(f"   - 历史总完赛场次: {total_finish}")
    print(f"   - 赔率覆盖场次: {coverage}")
    print(f"   - 覆盖率提升至: {coverage/total_finish*100:.2f}%")
    
    conn.close()

if __name__ == "__main__":
    main()
