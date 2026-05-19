import os
import sqlite3
import re
import json
import sys
from datetime import datetime

# 为了能够从 scripts 导入，将当前目录加入 sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from scripts.generate_shot_map import generate_shot_map_vertical

import os as _os
_SR_DIR = _os.path.dirname(_os.path.abspath(__file__))
PROJECT_ROOT_SR = _os.environ.get("PROJECT_ROOT", _SR_DIR)
DB_PATH = _os.environ.get("DB_PATH", _os.path.join(PROJECT_ROOT_SR, "football_uk.db"))
REPORTS_DIR = _os.path.join(PROJECT_ROOT_SR, "reports")
SCHEDULE_JSON = _os.path.join(PROJECT_ROOT_SR, "schedule", "target_matches.json")

def extract_metadata(content):
    """从 Markdown 内容中提取概率和推论"""
    # 提取 npxGD Diff
    diff_match = re.search(r"npxGD Diff\s*\(([\d\.-]+)\)", content)
    diff = float(diff_match.group(1)) if diff_match else 0.0
    
    # 简单的概率换算逻辑 (演示用)
    home_prob = round(50 + (diff * 15), 1)
    away_prob = round(30 - (diff * 5), 1)
    
    # 提取推论 (固定位置: ### 4. 喵弟模型判定 之后的第一段)
    inference = "暂无推论"
    inf_match = re.search(r"### \d+\.\s*喵弟模型判定\s*\n+(.*)", content)
    if inf_match:
        inference = inf_match.group(1).strip().split('。')[0] + '。'
        
    return home_prob, away_prob, inference

def sync():
    # 1. 加载赛程元数据
    metadata_map = {}
    if os.path.exists(SCHEDULE_JSON):
        with open(SCHEDULE_JSON, "r", encoding="utf-8") as f:
            sched_data = json.load(f)
            for m in sched_data:
                metadata_map[str(m['match_id'])] = m
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    files = [f for f in os.listdir(REPORTS_DIR) if f.endswith(".md") and "_" in f]
    print(f"Found {len(files)} reports to sync.")
    
    # 2. 确定排序，并仅处理过去 5 天内的比赛 (从 2026-03-27 到 2026-04-01)
    # 获取当前日期并计算 5 天前的日期
    today = datetime(2026, 4, 1) # 使用当前系统时间 2026-04-01
    five_days_ago = today.replace(day=today.day - 5) if today.day > 5 else datetime(2026, 3, 27) # 简单逻辑处理

    files.sort(reverse=True) 

    for idx, filename in enumerate(files):
        match = re.search(r"_(\d+)\.md$", filename)
        if not match: continue
        match_id = match.group(1)
        
        # 获取赛程背景数据判断时间
        meta = metadata_map.get(match_id, {})

        filepath = os.path.join(REPORTS_DIR, filename)
        
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            
        title_match = re.search(r"^#\s+(.*)", content, re.MULTILINE)
        title = title_match.group(1) if title_match else filename
        
        # 提取动态字段
        h_prob, a_prob, inference = extract_metadata(content)
        
        # 获取赛程背景数据
        meta = metadata_map.get(match_id, {})
        match_name_from_json = meta.get('match_name', '')
        if ' vs ' in match_name_from_json:
            home_team = match_name_from_json.split(' vs ')[0].strip()
            away_team = match_name_from_json.split(' vs ')[1].strip()
        else:
            # 兜底：从文件名解析队名
            # 文件名格式：研报_{HomeTeam}_vs_{AwayTeam}_{matchId}.md
            name_part = filename.replace('研报_', '').replace(f'_{match_id}.md', '')
            if '_vs_' in name_part:
                parts = name_part.split('_vs_')
                home_team = parts[0].replace('_', ' ')
                away_team = parts[1].replace('_', ' ')
            else:
                home_team = "Home"
                away_team = "Away"

        league = meta.get('league', 'J. LEAGUE')
        m_time = meta.get('kickoff_time', '04-01 18:00')
        if m_time and len(m_time) > 16:
            m_time = m_time[5:16] # YYYY-MM-DD HH:MM -> MM-DD HH:MM
            
        home_icon = f"https://images.fotmob.com/image_resources/logo/teamlogo/{meta.get('home_id', 0)}.png"
        away_icon = f"https://images.fotmob.com/image_resources/logo/teamlogo/{meta.get('away_id', 0)}.png"

        # 如果 meta 里没有 team_id，尝试从 dim_match 中查找
        if meta.get('home_id', 0) == 0 or meta.get('away_id', 0) == 0:
            try:
                cursor.execute("""
                    SELECT Home_Team_ID, Away_Team_ID 
                    FROM dim_match 
                    WHERE Home_Team_Name LIKE ? AND Away_Team_Name LIKE ? 
                    LIMIT 1
                """, (f'%{home_team.split()[0]}%', f'%{away_team.split()[0]}%'))
                id_row = cursor.fetchone()
                if id_row:
                    h_id = id_row[0] if meta.get('home_id', 0) == 0 else meta.get('home_id')
                    a_id = id_row[1] if meta.get('away_id', 0) == 0 else meta.get('away_id')
                    home_icon = f"https://images.fotmob.com/image_resources/logo/teamlogo/{h_id}.png"
                    away_icon = f"https://images.fotmob.com/image_resources/logo/teamlogo/{a_id}.png"
            except Exception:
                pass  # 图标查找失败不影响主流程
        
        # 确定状态 (如果是第一场且是神户，设为 HOT；包含 Pro 的设为 VIP)
        status = "FREE"
        if "5130428" in match_id: # 强制锁定神户为 Elite
            status = "HOT"
        elif "Pro" in content or "VIP" in content:
            status = "VIP"
            
        # 3. 视觉注入：如果是赛后复盘（标题含有复盘或正文含有比分）
        if "复盘" in title or "进球" in content:
            # 尝试调用绘图脚本
            img_path = _os.path.join(PROJECT_ROOT_SR, "reports", "images", f"shot_map_{match_id}_9_16.png")
            if not os.path.exists(img_path):
                try:
                    # 假定比分提取
                    score_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", title)
                    score_text = score_match.group(0) if score_match else "0 - 0"
                    generate_shot_map_vertical(match_id, meta.get('home_id'), meta.get('away_id'), home_team, away_team, score_text)
                    print(f"Generated shot map for {match_id}")
                except Exception as e:
                    print(f"Failed to generate shot map: {e}")
            
            # 自动穿插图片引用 (如果 Markdown 里没有)
            if "![" not in content and "shot_map" not in content:
                inject_text = f"\n\n## 📈 赛后复盘：射门分布\n\n![{home_team} vs {away_team} 射门地图](file://{img_path})\n"
                content += inject_text
                print(f"Injected shot map to {filename}")

        # 4. 入库
        cursor.execute("""
        INSERT OR REPLACE INTO report_store (
            match_id, title, markdown_content, 
            home_team, away_team, home_icon, away_icon, 
            home_prob, away_prob, league, match_time, 
            status, inference
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            match_id, title, content, 
            home_team, away_team, home_icon, away_icon, 
            h_prob, a_prob, league, m_time, 
            status, inference
        ))
        print(f"Synced {match_id}: {title} (Status: {status})")
        
    conn.commit()
    conn.close()
    print("Sync complete.")

if __name__ == "__main__":
    sync()
