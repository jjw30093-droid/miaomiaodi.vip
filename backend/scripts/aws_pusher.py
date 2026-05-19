import os
import re
import sqlite3
import json
import glob
import requests
import logging
from datetime import datetime
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# ================= 配置区 =================
_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(_SCRIPT_DIR))
DB_PATH      = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))
REPORTS_DIR  = os.path.join(PROJECT_ROOT, "reports")
# 云端 API 2.0 汇总点 (修复后的正确端点)
CLOUD_SYNC_URL = os.environ.get("CLOUD_SYNC_URL", "https://miaomiaodi.cc/api/v1/sync/match_payload")
SYNC_TOKEN = os.environ.get("INTERNAL_SYNC_TOKEN", "miaodi_secret_2026")

# 🚩 球队名映射字典：解决 FotMob 缩写与数据库全称的对冲 (如 PSG -> Paris Saint-Germain)
TEAM_NAME_MAP = {
    "PSG": "Paris Saint-Germain",
    "Man City": "Manchester City",
    "Man Utd": "Manchester United",
    "Tottenham": "Tottenham Hotspur",
    "Newcastle": "Newcastle United",
    "Brighton": "Brighton & Hove Albion",
    "Gladbach": "Borussia Mönchengladbach",
    "M'gladbach": "Mönchengladbach",
    "Leverkusen": "Bayer Leverkusen"
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["POST"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def get_report_content(match_id):
    """读取本地 Markdown 研报 (取最新版本)"""
    pattern = os.path.join(REPORTS_DIR, f"*{match_id}.md")
    files = glob.glob(pattern)
    if not files:
        return "暂无研报内容"
    # 按修改时间排序，取最新的
    files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    try:
        with open(files[0], 'r', encoding='utf-8') as f:
            content = f.read()
            return content if content.strip() else "暂无研报内容"
    except Exception:
        return "暂无研报内容"

def fetch_npxg_trend(cursor, team_id, current_match_id, venue_type='overall', skip_date_filter=False):
    """从数据库提取特定维度的 npxG 趋势"""
    # venue_type: 'overall', 'home_only', 'away_only'
    where_clause = "WHERE T.team_id = ?"
    params = [team_id]
    
    if not skip_date_filter:
        where_clause += " AND T.match_date < (SELECT Date FROM dim_match WHERE Match_ID = ? LIMIT 1)"
        params.append(current_match_id)
    
    if venue_type == 'home_only':
        where_clause += " AND T.is_home = 1"
    elif venue_type == 'away_only':
        where_clause += " AND T.is_home = 0"
    
    query = f"""
        SELECT 
            CASE WHEN T.is_home=1 THEN M.Away_Team_Name ELSE M.Home_Team_Name END as opponent,
            T.npxGD as npxg_diff
        FROM int_team_match_flattened T
        JOIN dim_match M ON T.match_id = M.Match_ID
        {where_clause}
        ORDER BY T.match_date DESC LIMIT 5
    """
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]

def fetch_shot_map_per_match(cursor, team_id, historical_match_ids):
    """
    按场次分组返回射门数据，每场包含：
    match_id / date / opponent / is_home / result /
    total_shots / situation_counts(dict) / shots[]
    每个 shot: {x, y, xg, outcome, situation, player, minute}
    """
    if not historical_match_ids:
        return []

    placeholders = ', '.join(['?'] * len(historical_match_ids))
    query = f"""
        SELECT
            s.Match_ID            AS match_id,
            m.Date                AS date,
            CASE WHEN t.is_home = 1
                 THEN m.Away_Team_Name
                 ELSE m.Home_Team_Name END AS opponent,
            t.is_home             AS is_home,
            m.home_score          AS home_score,
            m.away_score          AS away_score,
            s.X_Coord             AS x,
            s.Y_Coord             AS y,
            s.xG                  AS xg,
            COALESCE(s.Outcome,   '')   AS outcome,
            COALESCE(s.Situation, '')   AS situation,
            COALESCE(s.Shot_Type, '')   AS shot_type,
            COALESCE(s.Period,    '')   AS period,
            COALESCE(s.Minute,    0)    AS minute,
            COALESCE(dp.player_name, '') AS player
        FROM fact_shotmap s
        JOIN int_team_match_flattened t
            ON s.Match_ID = t.match_id AND t.team_id = ?
        JOIN (SELECT Match_ID, Date, Home_Team_Name, Away_Team_Name, home_score, away_score
              FROM dim_match GROUP BY Match_ID) m ON s.Match_ID = m.Match_ID
        LEFT JOIN (SELECT Match_ID, Player_ID, Team_ID FROM fact_player_match_stats
                   GROUP BY Match_ID, Player_ID, Team_ID) p
            ON s.Match_ID = p.Match_ID
           AND s.Player_ID = p.Player_ID
           AND p.Team_ID = ?
        LEFT JOIN dim_player dp ON p.Player_ID = dp.player_id
        WHERE s.Match_ID IN ({placeholders})
          AND s.Team_ID = ?
          -- 排除点球大战（J联赛本赛季打平直接互射点球，FotMob 把这些
          --   射门也存进 fact_shotmap，会污染射门图和进球计数）
          AND COALESCE(s.Period, '') != 'PenaltyShootout'
        ORDER BY m.Date DESC, s.Minute
    """
    cursor.execute(query, (team_id, team_id, *historical_match_ids, team_id))
    rows = [dict(row) for row in cursor.fetchall()]

    from collections import defaultdict, OrderedDict
    matches: OrderedDict = OrderedDict()

    for row in rows:
        mid = row['match_id']
        if mid not in matches:
            is_home = bool(row['is_home'])
            h, a = (row.get('home_score') or 0), (row.get('away_score') or 0)
            result = f"{h}-{a}" if is_home else f"{a}-{h}"
            matches[mid] = {
                'match_id':        mid,
                'date':            row['date'] or '',
                'opponent':        row['opponent'] or '',
                'is_home':         is_home,
                'result':          result,
                'total_shots':     0,
                'situation_counts': defaultdict(int),
                'shots':           [],
            }

        shot = {
            'x':         round(float(row['x']  or 0), 2),
            'y':         round(float(row['y']  or 0), 2),
            'xg':        round(float(row['xg'] or 0), 4),
            'Outcome':   row['outcome'],
            'Situation': row['situation'],
            'Shot_Type': row['shot_type'],
            'Period':    row['period'],
            'Minute':    int(row['minute'] or 0),
            'Player':    row['player'],
        }
        m = matches[mid]
        m['shots'].append(shot)
        m['total_shots'] += 1
        if row['situation']:
            m['situation_counts'][row['situation']] += 1

    result_list = []
    for m in matches.values():
        m['situation_counts'] = dict(m['situation_counts'])
        result_list.append(m)
    return result_list

def _fetch_local_meta(db, match_id):
    """从本地 report_store 读取元数据，并合并本地最新的赔率数据"""
    row = db.execute(
        """SELECT title, home_team, away_team, home_icon, away_icon,
                  home_prob, away_prob, draw_prob, league, match_time,
                  status, inference, pipeline_status, preview_content
           FROM report_store WHERE match_id = ? LIMIT 1""",
        (str(match_id),)
    ).fetchone()
    if not row:
        return None
    
    meta = dict(row)
    
    # 🧪 核心增强：注入本地 Titan 赔率数据
    try:
        odds_file = os.path.join(PROJECT_ROOT, "odds", "match_odds_data.json")
        if os.path.exists(odds_file):
            with open(odds_file, 'r', encoding='utf-8') as f:
                odds_data = json.load(f)
                # 寻找匹配的赔率对象
                match_odds = None
                if isinstance(odds_data, dict):
                    match_odds = odds_data.get(str(match_id))
                elif isinstance(odds_data, list):
                    for item in odds_data:
                        if str(item.get("fotmob_id")) == str(match_id):
                            match_odds = item
                            break
                
                if match_odds:
                    raw_odds = match_odds.get("odds", {})
                    ah = raw_odds.get("asian_handicap", {}).get("latest", {})
                    ou = raw_odds.get("over_under", {}).get("latest", {})
                    eu = raw_odds.get("european_1x2", {}).get("latest", {})
                    
                    meta["odds"] = {
                        "home_win": eu.get("home_win") or eu.get("home"),
                        "draw": eu.get("draw"),
                        "away_win": eu.get("away_win") or eu.get("away"),
                        "handicap": ah.get("line"),
                        "h_odds": ah.get("over_or_home"),
                        "a_odds": ah.get("under_or_away"),
                        "over": ou.get("line"),
                        "under": ou.get("line"),
                        "ou_odds_h": ou.get("over_or_home"),
                        "ou_odds_a": ou.get("under_or_away"),
                        "cid": match_odds.get("cid"),
                        "cname": raw_odds.get("provider", "Titan")
                    }
    except Exception as e:
        logging.warning(f"⚠️ 注入赔率数据失败: {e}")

    return meta


def _build_structured_inference(markdown, home_prob, draw_prob, away_prob):
    """
    从 markdown 的 "🎯 喵弟结论" 小节抽取 推荐方向 / 赔率 / ML 概率 / 置信等级，
    拼装成前端 GlassPickBlock 期望的结构化串：
        【<中文把握>】<label> @<odds> <prob>% (<home>%/<draw>%/<away>%)
    若字段不全返回 None（调用方保留原 free-form inference）。
    """
    if not markdown:
        return None
    conf_map = {'HIGH': '高把握', 'MEDIUM': '中把握', 'LOW': '低把握'}
    m_dir  = re.search(r'\*\*推荐方向\*\*[：:]\s*([^\s@（(]+).*?@\s*([\d.]+)', markdown)
    m_prob = re.search(r'\*\*ML\s*概率\*\*[：:]\s*([\d.]+)%', markdown)
    m_conf = re.search(r'\*\*置信等级\*\*[：:]\s*(HIGH|MEDIUM|LOW)', markdown)
    if not (m_dir and m_prob and m_conf):
        return None
    label   = m_dir.group(1)
    odds    = m_dir.group(2)
    prob    = m_prob.group(1)
    conf_cn = conf_map[m_conf.group(1)]
    hp = int(round(home_prob or 0))
    dp = int(round(draw_prob or 0))
    ap = int(round(away_prob or 0))
    return f'【{conf_cn}】{label} @{odds} {prob}% ({hp}%/{dp}%/{ap}%)'


def _lineup_to_impact(lineup_data: dict, home_name: str, away_name: str) -> dict | None:
    """
    将 lineup_fetcher 格式转换为前端 LineupImpact 格式。

    lineup_fetcher 格式:
      { "status": "confirmed", "home": { "starters": [...], "missing": [...] }, "away": { ... } }
    每个球员: { "id", "name", "position", "xg_xa_share", "def_share", "reason"(可选) }

    前端 LineupImpact 格式:
      { homeTeam: { teamName, starters: [LineupImpactPlayer], absentees: [...] }, awayTeam: { ... } }
    每个 LineupImpactPlayer: { name, position, shirt, status, offenseScore, defenseScore, hasData }
    """
    if not lineup_data or not isinstance(lineup_data, dict):
        return None

    # 0.50 / 0.35 作为 100 分参考上限（覆盖绝大多数球员）
    OFF_CAP = 0.50
    DEF_CAP = 0.35

    def _scale(val: float, cap: float) -> int | None:
        if val is None or val <= 0:
            return None
        return min(int(val / cap * 100), 100)

    def _convert(players: list, default_status: str) -> list:
        result = []
        for p in players:
            if not isinstance(p, dict):
                continue
            xg  = float(p.get("xg_xa_share") or 0.0)
            df  = float(p.get("def_share")    or 0.0)
            off = _scale(xg, OFF_CAP)
            dep = _scale(df, DEF_CAP)
            status = default_status
            reason = p.get("reason", "")
            if default_status != "starter" and reason:
                r_lo = reason.lower()
                if "suspend" in r_lo or "yellow" in r_lo or "red" in r_lo or "停赛" in reason:
                    status = "suspended"
                else:
                    status = "injured"
            entry: dict = {
                "name":         p.get("name", ""),
                "position":     p.get("position", ""),
                "shirt":        p.get("id", 0),
                "status":       status,
                "offenseScore": off,
                "defenseScore": dep,
                "hasData": {
                    "offense": off is not None,
                    "defense": dep is not None,
                },
            }
            if status != "starter" and reason:
                entry["injuryNote"] = reason
            result.append(entry)
        return result

    h = lineup_data.get("home", {})
    a = lineup_data.get("away", {})
    return {
        "homeTeam": {
            "teamName":  home_name,
            "starters":  _convert(h.get("starters", []), "starter"),
            "absentees": _convert(h.get("missing",  []), "injured"),
        },
        "awayTeam": {
            "teamName":  away_name,
            "starters":  _convert(a.get("starters", []), "starter"),
            "absentees": _convert(a.get("missing",  []), "injured"),
        },
    }


def push_match_payload(match_id):
    """
    单场比赛详情同步引擎 (修复 & SQL 实现版)
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    db = conn.cursor()
    
    try:
        # 1. 初始化空结构 (防御性分类对象，而非空数组)
        npxg_trend = {
            "home_team": {"overall": [], "home_only": [], "away_only": []},
            "away_team": {"overall": [], "home_only": [], "away_only": []}
        }
        shot_map_data = {
            "home_team": {"team_name": "", "matches": []},
            "away_team": {"team_name": "", "matches": []},
        }

        # 2. 获取主客队 ID (原有逻辑 + 模糊兜底逻辑)
        db.execute("SELECT Home_Team_ID, Away_Team_ID FROM dim_match WHERE Match_ID = ?", (match_id,))
        match_info = db.fetchone()
        
        h_id, a_id = None, None
        skip_date_filter = False

        if match_info:
            h_id, a_id = match_info['Home_Team_ID'], match_info['Away_Team_ID']
        else:
            # 🔍 兜底逻辑：如果 match_id 不在 dim_match 中，从 report_store 找队名，并尝试模糊匹配 ID
            logging.info(f"⚠️ Match {match_id} not in dim_match. Attempting fallback via name lookup...")
            db.execute("SELECT home_team, away_team FROM report_store WHERE match_id = ?", (match_id,))
            names = db.fetchone()
            if names:
                h_name, a_name = names['home_team'], names['away_team']
                
                # 🍏 尝试映射名，如果没在字典里则原样保留
                mapped_h_name = TEAM_NAME_MAP.get(h_name, h_name)
                mapped_a_name = TEAM_NAME_MAP.get(a_name, a_name)
                
                # 🔍 修正逻辑：分别在主客列查找，确保拿到的 ID 与队名匹配
                # 模糊查找主队 ID
                db.execute("SELECT Home_Team_ID FROM dim_match WHERE Home_Team_Name LIKE ? ORDER BY Date DESC LIMIT 1", (f"%{mapped_h_name}%",))
                res = db.fetchone()
                if not res:
                    db.execute("SELECT Away_Team_ID FROM dim_match WHERE Away_Team_Name LIKE ? ORDER BY Date DESC LIMIT 1", (f"%{mapped_h_name}%",))
                    res = db.fetchone()
                h_id = res[0] if res else None
                
                # 模糊查找客队 ID
                db.execute("SELECT Home_Team_ID FROM dim_match WHERE Home_Team_Name LIKE ? ORDER BY Date DESC LIMIT 1", (f"%{mapped_a_name}%",))
                res = db.fetchone()
                if not res:
                    db.execute("SELECT Away_Team_ID FROM dim_match WHERE Away_Team_Name LIKE ? ORDER BY Date DESC LIMIT 1", (f"%{mapped_a_name}%",))
                    res = db.fetchone()
                a_id = res[0] if res else None
                
                if h_id or a_id:
                    logging.info(f"🎯 Fallback IDs found: Home({h_name})={h_id}, Away({a_name})={a_id}. Skipping date filter.")
                    skip_date_filter = True

        # 3. 提取数据
        if h_id or a_id:
            # 3.1 提取 npxG 趋势 (三维度)
            npxg_trend["home_team"]["overall"] = fetch_npxg_trend(db, h_id, match_id, 'overall', skip_date_filter) if h_id else []
            npxg_trend["home_team"]["home_only"] = fetch_npxg_trend(db, h_id, match_id, 'home_only', skip_date_filter) if h_id else []
            npxg_trend["away_team"]["overall"] = fetch_npxg_trend(db, a_id, match_id, 'overall', skip_date_filter) if a_id else []
            npxg_trend["away_team"]["away_only"] = fetch_npxg_trend(db, a_id, match_id, 'away_only', skip_date_filter) if a_id else []

            # 3.2 提取射门图点位（按场次分组，近 5 场）
            def _get_mids(tid, extra_where="", extra_params=None):
                q = "SELECT match_id FROM int_team_match_flattened WHERE team_id = ?"
                p = [tid]
                if extra_where:
                    q += " " + extra_where
                    p += (extra_params or [])
                if not skip_date_filter:
                    q += " AND match_date < (SELECT Date FROM dim_match WHERE Match_ID = ? ORDER BY Date DESC LIMIT 1)"
                    p.append(match_id)
                q += " ORDER BY match_date DESC LIMIT 5"
                db.execute(q, p)
                return [r[0] for r in db.fetchall()]

            if h_id:
                h_mids = _get_mids(h_id)
                shot_map_data["home_team"]["matches"] = fetch_shot_map_per_match(db, h_id, h_mids)
                # 从 dim_match 补全队名
                db.execute("SELECT Home_Team_Name FROM dim_match WHERE Home_Team_ID = ? ORDER BY Date DESC LIMIT 1", (h_id,))
                r = db.fetchone()
                if not r:
                    db.execute("SELECT Away_Team_Name FROM dim_match WHERE Away_Team_ID = ? ORDER BY Date DESC LIMIT 1", (h_id,))
                    r = db.fetchone()
                shot_map_data["home_team"]["team_name"] = r[0] if r else ""

            if a_id:
                a_mids = _get_mids(a_id)
                shot_map_data["away_team"]["matches"] = fetch_shot_map_per_match(db, a_id, a_mids)
                db.execute("SELECT Away_Team_Name FROM dim_match WHERE Away_Team_ID = ? ORDER BY Date DESC LIMIT 1", (a_id,))
                r = db.fetchone()
                if not r:
                    db.execute("SELECT Home_Team_Name FROM dim_match WHERE Home_Team_ID = ? ORDER BY Date DESC LIMIT 1", (a_id,))
                    r = db.fetchone()
                shot_map_data["away_team"]["team_name"] = r[0] if r else ""

        # 4. 提取本场球员数据 + 球队整体数据
        POSITION_MAP = {1: 'DF', 2: 'MF', 3: 'FW'}

        def _fetch_team_players(team_id):
            db.execute("""
                SELECT shirt_number, player_name, usual_position, is_goalkeeper,
                       minutes_played, rating_title, goals, assists, expected_goals,
                       ShotsOnTarget, is_captain, Player_ID
                FROM fact_player_match_stats
                WHERE Match_ID = ? AND Team_ID = ? AND minutes_played > 0
                ORDER BY is_goalkeeper DESC, usual_position, minutes_played DESC
            """, (match_id, team_id))
            players = []
            for r in db.fetchall():
                r = dict(r)
                if r['is_goalkeeper']:
                    pos = 'GK'
                else:
                    pos = POSITION_MAP.get(r['usual_position'], 'MF')
                players.append({
                    'player_id':      str(r['Player_ID'] or ''),
                    'name':           r['player_name'] or f"#{r['shirt_number'] or '?'}",
                    'shirt':          r['shirt_number'] or '',
                    'position':       pos,
                    'minutes':        int(r['minutes_played'] or 0),
                    'rating':         round(float(r['rating_title'] or 0), 1),
                    'goals':          int(r['goals'] or 0),
                    'assists':        int(r['assists'] or 0),
                    'xg':             round(float(r['expected_goals'] or 0), 2),
                    'shots_on_target': int(r['ShotsOnTarget'] or 0),
                    'is_captain':     bool(r['is_captain']),
                })
            return players

        def _fetch_team_match_stats(team_id):
            db.execute("""
                SELECT BallPossesion, expected_goals, total_shots, ShotsOnTarget,
                       big_chance, accurate_passes, passes, corners, yellow_cards
                FROM fact_team_match_stats
                WHERE Match_ID = ? AND Team_ID = ? AND Period = 'All'
                LIMIT 1
            """, (match_id, team_id))
            r = db.fetchone()
            if not r:
                return {}
            r = dict(r)
            total = r['total_shots'] or 0
            on_target = r['ShotsOnTarget'] or 0
            return {
                'possession':      round(float(r['BallPossesion'] or 0), 1),
                'xg':              round(float(r['expected_goals'] or 0), 2),
                'total_shots':     int(total),
                'shots_on_target': int(on_target),
                'shot_accuracy':   round(on_target / total * 100, 1) if total > 0 else 0,
                'big_chances':     int(r['big_chance'] or 0),
                'corners':         int(r['corners'] or 0),
                'yellow_cards':    int(r['yellow_cards'] or 0),
            }

        player_stats = {'home_team': [], 'away_team': []}
        team_match_stats = {'home_team': {}, 'away_team': {}}
        if h_id:
            player_stats['home_team']    = _fetch_team_players(h_id)
            team_match_stats['home_team'] = _fetch_team_match_stats(h_id)
        if a_id:
            player_stats['away_team']    = _fetch_team_players(a_id)
            team_match_stats['away_team'] = _fetch_team_match_stats(a_id)

        report_md = get_report_content(match_id)
        local_meta = _fetch_local_meta(db, match_id)

        # 🧠 将 markdown 的"🎯 喵弟结论"结构化，覆盖 inference 字段
        # 让前端 GlassPickBlock 正则解析成功（原自由句保留在 report_store，不改）
        if local_meta:
            structured = _build_structured_inference(
                report_md,
                local_meta.get('home_prob'),
                local_meta.get('draw_prob'),
                local_meta.get('away_prob'),
            )
            if structured:
                local_meta['inference'] = structured

        # 4b. 读取持久化的阵容数据并转换为 LineupImpact 格式
        lineup_impact_data = None
        try:
            db.execute(
                "SELECT lineup_data, home_team, away_team FROM report_store WHERE match_id=?",
                (match_id,)
            )
            lu_row = db.fetchone()
            if lu_row and lu_row["lineup_data"]:
                raw_lineup = json.loads(lu_row["lineup_data"])
                lineup_impact_data = _lineup_to_impact(
                    raw_lineup,
                    lu_row["home_team"] or "",
                    lu_row["away_team"] or "",
                )
                if lineup_impact_data:
                    logging.info(f"[pusher] ✅ 阵容转换成功: {lu_row['home_team']} vs {lu_row['away_team']}")
        except Exception as _le:
            logging.warning(f"[pusher] ⚠️ 读取阵容数据失败: {_le}")

        # 5. 组装同步载荷
        payload = {
            "match_id":           str(match_id),
            "report_markdown":    report_md,
            "npxg_trend":         npxg_trend,
            "shot_map_data":      shot_map_data,
            "player_stats":       player_stats,
            "team_match_stats":   team_match_stats,
            "match_meta":         local_meta,
            "odds":               local_meta.pop("odds", {}) if local_meta else {},
            "lineup_impact_data": lineup_impact_data,
        }
        
        # 6. 执行同步
        session = get_session()
        headers = {"X-Sync-Token": SYNC_TOKEN, "Content-Type": "application/json"}
        
        logging.info(f"📡 正在同步详情 [Match {match_id}] -> {CLOUD_SYNC_URL}")
        response = session.post(CLOUD_SYNC_URL, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 200:
            logging.info(f"✅ Match {match_id} 详情同步成功")
            return True
        else:
            logging.error(f"❌ 同步失败 ({response.status_code}): {response.text}")
            return False
            
    except Exception as e:
        logging.error(f"💥 同步异常 [Match {match_id}]: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    import sys
    mid = sys.argv[1] if len(sys.argv) > 1 else "5130428"
    push_match_payload(mid)
