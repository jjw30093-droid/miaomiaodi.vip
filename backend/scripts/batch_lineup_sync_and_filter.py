import os
import json
import time
import sqlite3
from datetime import datetime
from lineup_fetcher import fetch_lineup

# ==========================================
# ⚙️ 配置区
# ==========================================
ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEDULE_FILE = os.path.join(ROOT, "schedule/target_matches.json")
ODDS_FILE = os.path.join(ROOT, "odds/match_odds_data.json")
LOG_DIR = os.path.join(ROOT, "logs")
MISSING_LOG = os.path.join(LOG_DIR, "missing_lineups.json")

os.makedirs(LOG_DIR, exist_ok=True)

def main():
    print("=" * 60)
    print("🚀 [阵容/阵型全量扫表] 开始同步周末未开赛比赛信息...")
    print("=" * 60)

    if not os.path.exists(SCHEDULE_FILE) or not os.path.exists(ODDS_FILE):
        print(f"❌ 找不到赛程或赔率文件！")
        return

    with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
        schedule = json.load(f)
    with open(ODDS_FILE, "r", encoding="utf-8") as f:
        odds = json.load(f)

    odds_ids = {str(o["fotmob_id"]) for o in odds if "fotmob_id" in o}
    now = datetime.now()

    # 关键过滤：仅针对【未开赛】且【已有赔率】的比赛
    target_ids = []
    for m in schedule:
        try:
            kickoff = datetime.strptime(m["kickoff_time"], "%Y-%m-%d %H:%M:%S")
        except:
            continue
        
        if kickoff > now and str(m["match_id"]) in odds_ids:
            target_ids.append(str(m["match_id"]))

    print(f"📡 经过时效性过滤，共锁定 {len(target_ids)} 场周末待赛。")

    with_lineup = []
    missing_lineup = []

    for idx, mid in enumerate(target_ids):
        print(f"\n[{idx+1}/{len(target_ids)}] 正在同步 ID: {mid}...")
        
        # 调用 DrissionPage 抓取器
        res = fetch_lineup(mid)
        
        if res and res.get("home", {}).get("formation") and res.get("home", {}).get("formation") != "N/A":
            print(f"✅ 阵容锁定：{res['home']['formation']}")
            with_lineup.append(mid)
        else:
            print(f"⚠️ 阵容暂缺：FotMob 尚未发布或抓取失败。")
            missing_lineup.append(mid)
            
        time.sleep(1)

    # 保存缺失名单
    with open(MISSING_LOG, "w", encoding="utf-8") as f:
        json.dump(missing_lineup, f, ensure_ascii=False, indent=2)

    # 将 with_lineup 保存给 auto_trader 使用
    with open(os.path.join(LOG_DIR, "ready_for_report.json"), "w", encoding="utf-8") as f:
        json.dump(with_lineup, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print(f"🏁 同步完毕！")
    print(f"✅ 具备阵容比赛: {len(with_lineup)} 场")
    print(f"❌ 缺失阵容比赛: {len(missing_lineup)} 场 (已记录至 {MISSING_LOG}，稍后重试)")
    print("=" * 60)

if __name__ == "__main__":
    main()
