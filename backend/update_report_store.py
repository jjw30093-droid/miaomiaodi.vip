import json, sqlite3
conn = sqlite3.connect('/home/ubuntu/app/backend/football_uk.db')

with open('/home/ubuntu/app/backend/team_zh.json') as f:
    mapping = json.load(f)

for en, zh in mapping.items():
    conn.execute(
        "UPDATE report_store SET home_team=? WHERE home_team=?", (zh, en)
    )
    conn.execute(
        "UPDATE report_store SET away_team=? WHERE away_team=?", (zh, en)
    )

conn.commit()
conn.close()
print("report_store 球队名更新完成")
