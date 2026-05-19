"""
fuzzy_match_odds.py
===================
Phase 2 Pillar A 改造：旧版 TEAM_ALIASES / get_mapped_name / normalize_name 已被
team_resolver 统一替代，但此脚本为离线批量修正工具，需要连接 football_uk.db。

team_resolver 从 dim_team + team_mapping 加载别名，比以前的硬编码 dict 更完整。
"""

import os
import sys
import sqlite3
import datetime

# Phase 2: 统一别名解析器（替代旧版 TEAM_ALIASES / normalize_name / word_similarity）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)  # scripts/ 的上级目录
sys.path.insert(0, _PROJECT_ROOT)

try:
    from team_resolver import resolve_team as _resolver_resolve_team, _norm_similarity, _similarity
    _RESOLVER_AVAILABLE = True
except ImportError:
    _RESOLVER_AVAILABLE = False

# ── legacy 函数保留（供旧调用方兼容，内部已重定向到 team_resolver）────────────
import re
import unicodedata
from difflib import SequenceMatcher


def normalize_name(name):
    """[Legacy] 移除重音 + 小写 + 删常见词 + 排序（已被 team_resolver._normalize 替代）"""
    if not name: return ""
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('utf-8')
    name = name.lower()
    name = re.sub(r'\b(fc|u23|united|city|rovers|town|afc|f.c.|athletic|club|de|la|el|vfl|vfb|sv|as|sc|1|05|04|09|cf|rcd|sd|real)\b', '', name)
    name = re.sub(r'[^a-z0-9]', ' ', name)
    words = sorted(name.split())
    return " ".join(words)


def similarity(a, b):
    """[Legacy] 标准字符串相似度"""
    if _RESOLVER_AVAILABLE:
        return _similarity(a, b)
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def word_similarity(a, b):
    """[Legacy] 归一化后字符串相似度"""
    if _RESOLVER_AVAILABLE:
        return _norm_similarity(a, b)
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb: return 0
    return SequenceMatcher(None, na, nb).ratio()


def get_mapped_name(div, team_name, season=None):
    """
    [Legacy → team_resolver] 别名解析。
    优先走 team_resolver；resolver 失败时保留法甲特殊处理 + 原 TEAM_ALIASES 硬编码。
    """
    # 法甲特殊情况（赛季感知）
    if div == 'F1':
        if team_name == 'Paris FC' and season in ['2023/2024', '2024/2025']:
            return 'Paris Saint-Germain'
        if team_name == 'Paris SG':
            return 'Paris Saint-Germain'

    # Phase 2: team_resolver
    if _RESOLVER_AVAILABLE:
        res = _resolver_resolve_team(team_name, league=div)
        if res and res.get('canonical_name'):
            return res['canonical_name']

    # Legacy fallback（保留以防 dim_team 尚未建立）
    _LEGACY_ALIASES = {
        ('E0', 'Wolves'): 'Wolverhampton Wanderers',
        ('E0', "Nott'm Forest"): 'Nottingham Forest',
        ('E0', 'Man United'): 'Manchester United',
        ('E0', 'Man City'): 'Manchester City',
        ('E0', 'Sheffield Utd'): 'Sheffield United',
        ('E0', 'Brighton'): 'Brighton & Hove Albion',
        ('E0', 'Tottenham'): 'Tottenham Hotspur',
        ('SP1', 'Ath Madrid'): 'Atletico Madrid',
        ('SP1', 'Ath Bilbao'): 'Athletic Club',
        ('D1', 'Bayern Munich'): 'Bayern München',
        ('D1', 'Leverkusen'): 'Bayer Leverkusen',
        ('D1', 'RB Leipzig'): 'Leipzig',
    }
    return _LEGACY_ALIASES.get((div, team_name), team_name)


DB_PATH = os.path.join(_PROJECT_ROOT, "football_uk.db")

LEAGUE_MAP = {
    47: 'E0',
    54: 'D1',
    87: 'SP1',
    55: 'I1',
    53: 'F1',
    223: 'J1',
    9080: 'K1',
    113: 'A1'
}

def fuzzy_match():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 查出所有未匹配的比赛
    unmatched_query = """
    SELECT m.Match_ID, m.Date, m.Home_Team_Name, m.Away_Team_Name, m.League_ID, m.Season
    FROM dim_match m
    WHERE m.League_ID IN (47, 54, 87, 55, 53, 223, 9080, 113)
    AND m.Season IN ('2023-2024', '2024-2025', '2023/2024', '2024/2025', '2025/2026', '2024', '2025', '2026')
    AND NOT EXISTS (
        SELECT 1 FROM raw_footballdata_odds o
        WHERE o.HomeTeam = m.Home_Team_Name
        AND o.AwayTeam = m.Away_Team_Name
        AND m.Date LIKE o.Date || '%'
    )
    """
    
    cursor.execute(unmatched_query)
    unmatched = cursor.fetchall()
    
    print(f"Checking {len(unmatched)} unmatched matches...")
    
    updates = []
    seen_rowids = set()
    
    for match_id, m_date_str, m_home, m_away, l_id, m_season in unmatched:
        div = LEAGUE_MAP.get(l_id)
        if not div: continue
        
        try:
            m_date = datetime.datetime.strptime(m_date_str[:10], '%Y-%m-%d')
        except:
            continue
            
        # 允许 +/- 1 天的容差
        date_start = (m_date - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        date_end = (m_date + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        
        # 查找该分区在对应日期窗口内的所有裸数据
        cursor.execute("""
            SELECT Date, HomeTeam, AwayTeam, ROWID 
            FROM raw_footballdata_odds 
            WHERE Div = ? AND Date BETWEEN ? AND ?
        """, (div, date_start, date_end))
        
        candidates = cursor.fetchall()
        
        best_candidate = None
        max_score = 0
        
        for o_date, o_home, o_away, rowid in candidates:
            if rowid in seen_rowids: continue

            # Phase 2: 统一走 get_mapped_name（内部调用 team_resolver，season 为可选参数）
            mapped_o_home = get_mapped_name(div, o_home, season=m_season)
            mapped_o_away = get_mapped_name(div, o_away, season=m_season)
            
            # 1. 直接匹配 (After Alias)
            if mapped_o_home == m_home and mapped_o_away == m_away:
                best_candidate = (rowid, o_home, o_away, o_date)
                max_score = 2.0 # Perfect mapping score
                break
                
            # 2. 相似度计算
            h_sim = similarity(m_home, mapped_o_home)
            a_sim = similarity(m_away, mapped_o_away)
            
            # 3. 分词相似度
            h_w_sim = word_similarity(m_home, mapped_o_home)
            a_w_sim = word_similarity(m_away, mapped_o_away)
            
            avg_sim = (max(h_sim, h_w_sim) + max(a_sim, a_w_sim)) / 2
            
            if avg_sim > 0.8 or (h_w_sim > 0.85 and a_w_sim > 0.85):
                if avg_sim > max_score:
                    max_score = avg_sim
                    best_candidate = (rowid, o_home, o_away, o_date)
        
        if best_candidate:
            rowid, o_home, o_away, o_date = best_candidate
            # print(f"MATCH: [{m_date_str[:10]}] {m_home} vs {m_away} <-> [{o_date}] {o_home} vs {o_away}")
            updates.append((m_home, m_away, m_date_str[:10], rowid))
            seen_rowids.add(rowid)

    if updates:
        print(f"\nApplying {len(updates)} manual+fuzzy corrections...")
        for standard_home, standard_away, standard_date, rowid in updates:
            cursor.execute("""
                UPDATE raw_footballdata_odds 
                SET HomeTeam = ?, AwayTeam = ?, Date = ?
                WHERE ROWID = ?
            """, (standard_home, standard_away, standard_date, rowid))
        conn.commit()
        print("Done.")
    else:
        print("No matches found.")

    conn.close()

if __name__ == "__main__":
    fuzzy_match()
