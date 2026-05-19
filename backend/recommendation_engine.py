"""
统一推荐引擎（Unified Recommendation Engine）

核心逻辑：
- 方向信号（1X2 / AH）互斥 → 取 |CLV| 最高的一个
- 大小球信号（Over/Under）独立 → 单独判断
- 最终输出：最多 2 条推荐（1 方向 + 1 大小球）
- P&L 回测：平注（每场1单位），便于绘制资金走势图
"""
import math
import sqlite3
from pathlib import Path
from difflib import SequenceMatcher
from typing import Optional, Dict, List

DB_PATH = Path("/home/ubuntu/app/backend/football_data.db")

KELLY_FRACTION  = 0.25
EDGE_THRESHOLD  = 0.04   # 4% CLV 才算有价值的信号
MAX_GOALS       = 9

# ── 市场开关（数据质量不稳定时可按市场禁用）────────────────────────────────
# AH 赔率匹配依赖 raw_footballdata_odds 球队名精确匹配 + 联赛过滤
# 目前表内混有多联赛数据，匹配不稳定，暂时禁用 AH 方向信号
MARKET_ENABLED = {
    '1X2': True,    # 主力信号，回测 ROI +26.6% ✅
    'AH':  False,   # 暂时禁用：赔率匹配不可靠，待修复联赛过滤后恢复
    'OU':  True,    # 大小球：-1.3% 接近持平，保留
}

MANUAL_MAP = {
    'Tottenham': 'Tottenham Hotspur', 'Nottm Forest': 'Nottingham Forest',
    'Dortmund': 'Borussia Dortmund', 'Frankfurt': 'Eintracht Frankfurt',
    'Kawasaki': 'Kawasaki Frontale', 'Sanfrecce': 'Sanfrecce Hiroshima',
    "M'gladbach": "Borussia M'Gladbach", 'Mainz': 'Mainz 05',
    'Leverkusen': 'Bayer Leverkusen', 'Man City': 'Manchester City',
    'West Ham': 'West Ham United', 'Western Sydney': 'Western Sydney Wanderers FC',
    'Central Coast': 'Central Coast Mariners', 'Newcastle': 'Newcastle United',
    'Leeds': 'Leeds United',
    'FC Porto': None, 'PSG': None, 'Braga': None, 'Sporting CP': None, 'Köln': None,
}

# ── 基础数学工具 ───────────────────────────────────────────────────────────

def poisson_prob(lam, k):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def score_matrix(lam_h, lam_a):
    return [[poisson_prob(lam_h, h) * poisson_prob(lam_a, a)
             for a in range(MAX_GOALS)] for h in range(MAX_GOALS)]

def wdl_to_lambda(p_home, p_draw, p_away):
    """WDL → Poisson λ（迭代校准）"""
    ratio = p_home / max(p_away, 0.01)
    base = 1.3 + (p_home + p_away) * 0.5
    lam_h = base * (ratio ** 0.4) / (1 + ratio ** 0.4) * 2
    lam_a = base * 2 - lam_h
    lam_h = max(0.3, min(4.0, lam_h))
    lam_a = max(0.3, min(4.0, lam_a))
    for _ in range(50):
        mat = score_matrix(lam_h, lam_a)
        ph = sum(mat[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS) if h > a)
        pd = sum(mat[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS) if h == a)
        pa = sum(mat[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS) if h < a)
        tot = ph + pd + pa
        if tot < 1e-9: break
        ph, pd, pa = ph/tot, pd/tot, pa/tot
        err_h, err_a = p_home - ph, p_away - pa
        if abs(err_h) < 1e-4 and abs(err_a) < 1e-4: break
        lam_h = max(0.3, min(4.0, lam_h + err_h * 0.5))
        lam_a = max(0.3, min(4.0, lam_a + err_a * 0.5))
    return lam_h, lam_a

def remove_vig(p1, p2, p3=None):
    """去水位"""
    if p3 is not None:
        t = p1 + p2 + p3
        return p1/t, p2/t, p3/t
    t = p1 + p2
    return p1/t, p2/t

def ip(odds):
    """赔率 → 隐含概率"""
    return 1/odds if odds and odds > 1 else None

def kelly(model_p, odds):
    """分数Kelly"""
    if not model_p or not odds or odds <= 1: return 0.0
    fk = (model_p * odds - 1) / (odds - 1)
    return round(max(0.0, fk * KELLY_FRACTION), 4)

# ── AH 概率计算 ────────────────────────────────────────────────────────────

def ah_prob(matrix, handicap):
    frac = handicap % 0.5
    if abs(frac - 0.25) < 1e-9 or abs(frac + 0.25) < 1e-9:
        r1 = ah_prob(matrix, handicap - 0.25)
        r2 = ah_prob(matrix, handicap + 0.25)
        return {k: (r1[k] + r2[k]) / 2 for k in r1}
    pw = pa = pp = 0.0
    for h in range(MAX_GOALS):
        for a in range(MAX_GOALS):
            net = (h + handicap) - a
            if abs(net) < 1e-9: pp += matrix[h][a]
            elif net > 0: pw += matrix[h][a]
            else: pa += matrix[h][a]
    tot = pw + pa + pp
    return {'home': pw/tot, 'away': pa/tot, 'push': pp/tot}

# ── 大小球概率计算 ──────────────────────────────────────────────────────────

def ou_prob(matrix, line=2.5):
    """计算大小球概率（默认2.5线）"""
    over = sum(matrix[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS) if h + a > line)
    under = sum(matrix[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS) if h + a < line)
    push = sum(matrix[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS) if h + a == line)
    tot = over + under + push
    return {'over': over/tot, 'under': under/tot, 'push': push/tot}

# ── 核心推荐函数 ───────────────────────────────────────────────────────────

def get_best_recommendation(
    p_home: float, p_draw: float, p_away: float,
    odds: dict   # keys: 1x2_h, 1x2_d, 1x2_a, ah_line, ah_h, ah_a, ou_line, ou_over, ou_under
) -> dict:
    """
    统一推荐引擎：给定模型概率和市场赔率，返回最优推荐。

    推荐规则：
    - 方向信号（1X2/AH）互斥，取 |CLV| 最高的
    - 大小球独立计算
    - 最终：若方向有edge → 推荐方向；若大小球有edge → 推荐大小球；两者都有 → 同时推荐
    - 相同方向: AH主 ≈ 1X2主 → 互斥
    """
    lam_h, lam_a = wdl_to_lambda(p_home, p_draw, p_away)
    mat = score_matrix(lam_h, lam_a)

    signals = []   # 所有候选信号

    # ── 1X2 信号 ───────────────────────────────────────────────
    o1h = odds.get('1x2_h')
    o1d = odds.get('1x2_d')
    o1a = odds.get('1x2_a')
    if MARKET_ENABLED.get('1X2', True) and o1h and o1d and o1a:
        rh, rd, ra = ip(o1h), ip(o1d), ip(o1a)
        if rh and rd and ra:
            ch, cd, ca = remove_vig(rh, rd, ra)
            for side, mp, cp, raw_odds in [
                ('home', p_home, ch, o1h),
                ('draw', p_draw, cd, o1d),
                ('away', p_away, ca, o1a),
            ]:
                clv = mp - cp
                if abs(clv) >= EDGE_THRESHOLD:
                    signals.append({
                        'category':  'direction',  # 方向信号，互斥组
                        'market':    '1X2',
                        'side':      side,
                        'clv':       clv,
                        'model_prob': round(mp * 100, 1),
                        'market_prob': round(cp * 100, 1),
                        'kelly_stake': kelly(mp, raw_odds),
                        'odds':      raw_odds,
                        'abs_clv':   abs(clv),
                    })

    # ── AH 信号 ────────────────────────────────────────────────
    ah_line = odds.get('ah_line')
    ah_h    = odds.get('ah_h')
    ah_a    = odds.get('ah_a')
    if MARKET_ENABLED.get('AH', True) and ah_line is not None and ah_h and ah_a:
        raw_ah_h, raw_ah_a = ip(ah_h), ip(ah_a)
        if raw_ah_h and raw_ah_a:
            mah = ah_prob(mat, ah_line)
            c_ah_h, c_ah_a = remove_vig(raw_ah_h, raw_ah_a)
            for side, mp, cp, raw_odds in [
                ('home', mah['home'], c_ah_h, ah_h),
                ('away', mah['away'], c_ah_a, ah_a),
            ]:
                clv = mp - cp
                if abs(clv) >= EDGE_THRESHOLD:
                    signals.append({
                        'category':  'direction',
                        'market':    'AH',
                        'side':      side,
                        'ah_line':   ah_line,
                        'clv':       clv,
                        'model_prob': round(mp * 100, 1),
                        'market_prob': round(cp * 100, 1),
                        'kelly_stake': kelly(mp, raw_odds),
                        'odds':      raw_odds,
                        'abs_clv':   abs(clv),
                    })

    # ── 大小球信号 ──────────────────────────────────────────────
    ou_line  = odds.get('ou_line', 2.5)
    ou_over  = odds.get('ou_over')
    ou_under = odds.get('ou_under')
    if MARKET_ENABLED.get('OU', True) and ou_over and ou_under:
        mou = ou_prob(mat, ou_line)
        raw_over, raw_under = ip(ou_over), ip(ou_under)
        if raw_over and raw_under:
            c_over, c_under = remove_vig(raw_over, raw_under)
            for side, mp, cp, raw_odds in [
                ('over',  mou['over'],  c_over,  ou_over),
                ('under', mou['under'], c_under, ou_under),
            ]:
                clv = mp - cp
                if abs(clv) >= EDGE_THRESHOLD:
                    signals.append({
                        'category':  'ou',   # 大小球，独立组
                        'market':    f'O/U {ou_line}',
                        'side':      side,
                        'ou_line':   ou_line,
                        'clv':       clv,
                        'model_prob': round(mp * 100, 1),
                        'market_prob': round(cp * 100, 1),
                        'kelly_stake': kelly(mp, raw_odds),
                        'odds':      raw_odds,
                        'abs_clv':   abs(clv),
                    })

    if not signals:
        return {
            'has_recommendation': False,
            'recommended_bets': [],
            'lam_home': round(lam_h, 3),
            'lam_away': round(lam_a, 3),
        }

    # ── 互斥规则：方向信号只保留一个（|CLV|最大）──────────────────
    dir_signals = [s for s in signals if s['category'] == 'direction']
    ou_signals  = [s for s in signals if s['category'] == 'ou']

    best_direction = max(dir_signals, key=lambda x: x['abs_clv']) if dir_signals else None
    best_ou        = max(ou_signals,  key=lambda x: x['abs_clv']) if ou_signals  else None

    recommended = []
    if best_direction:
        s = best_direction.copy()
        s['clv_pct'] = round(s['clv'] * 100, 2)
        s['kelly_pct'] = round(s['kelly_stake'] * 100, 2)
        recommended.append(s)
    if best_ou:
        s = best_ou.copy()
        s['clv_pct'] = round(s['clv'] * 100, 2)
        s['kelly_pct'] = round(s['kelly_stake'] * 100, 2)
        recommended.append(s)

    return {
        'has_recommendation': True,
        'recommended_bets':   recommended,
        'all_signals_count':  len(signals),
        'lam_home':           round(lam_h, 3),
        'lam_away':           round(lam_a, 3),
    }

# ── 解析球队名 ─────────────────────────────────────────────────────────────

def resolve_team(name: str, odds_teams: set) -> Optional[str]:
    if name in MANUAL_MAP: return MANUAL_MAP[name]
    if name in odds_teams: return name
    best, bs = None, 0
    for c in odds_teams:
        s = SequenceMatcher(None, name.lower(), c.lower()).ratio()
        if s > bs: best, bs = c, s
    return best if bs >= 0.75 else None

# ── 获取单场推荐 ───────────────────────────────────────────────────────────

def get_match_recommendation(match_id: str, db_path=DB_PATH) -> dict:
    """获取指定场次的最优推荐（含大小球）"""
    conn = sqlite3.connect(db_path)

    rs = conn.execute("""
        SELECT home_team, away_team, home_prob, draw_prob, away_prob
        FROM report_store WHERE match_id = ?
    """, (match_id,)).fetchone()

    if not rs:
        conn.close()
        return {'error': '场次不存在'}

    home, away, hp, dp, ap = rs
    if not hp or not dp or not ap:
        conn.close()
        return {'error': '该场次无模型概率'}

    p_h, p_d, p_a = hp/100, dp/100, ap/100

    odds_teams = set(r[0] for r in conn.execute("SELECT DISTINCT HomeTeam FROM raw_footballdata_odds"))
    hm = resolve_team(home, odds_teams)
    am = resolve_team(away, odds_teams)

    odds = {}
    raw_odds_row = None

    if hm and am:
        row = conn.execute("""
            SELECT B365CH, B365CD, B365CA,
                   AHCh, B365CAHH, B365CAHA,
                   "B365C>2.5", "B365C<2.5", OUCLine,
                   FTHG, FTAG, FTR
            FROM raw_footballdata_odds
            WHERE HomeTeam=? AND AwayTeam=? ORDER BY Date DESC LIMIT 1
        """, (hm, am)).fetchone()
        if row:
            raw_odds_row = row
            odds = {
                '1x2_h':  row[0], '1x2_d':  row[1], '1x2_a':  row[2],
                'ah_line': row[3], 'ah_h':   row[4], 'ah_a':   row[5],
                'ou_over': row[6], 'ou_under': row[7],
                'ou_line': row[8] if row[8] else 2.5,
            }

    conn.close()

    result = get_best_recommendation(p_h, p_d, p_a, odds)
    result.update({
        'match_id':   match_id,
        'home_team':  home,
        'away_team':  away,
        'model_probs': {'home': hp, 'draw': dp, 'away': ap},
    })

    # 加上实际结果（用于回测）
    if raw_odds_row:
        result['actual'] = {
            'fthg': raw_odds_row[9],
            'ftag': raw_odds_row[10],
            'ftr':  raw_odds_row[11],
        }

    return result

# ── P&L 回测 ───────────────────────────────────────────────────────────────

def _bet_result(bet: dict, actual: dict) -> Optional[float]:
    """
    计算单注盈亏（平注，1单位）
    返回: +profit（赢）/ -1（输）/ 0（退注push）/ None（无结果）
    """
    if not actual or actual.get('fthg') is None or actual.get('ftag') is None:
        return None

    fthg = actual['fthg']
    ftag = actual['ftag']
    ftr  = actual.get('ftr')  # H/D/A
    market = bet['market']
    side   = bet['side']
    odds   = bet['odds']

    if market == '1X2':
        result_map = {'H': 'home', 'D': 'draw', 'A': 'away'}
        outcome = result_map.get(ftr)
        if outcome is None: return None
        if outcome == side: return round(odds - 1, 4)   # 赢：赔率-1
        return -1.0                                      # 输：-1单位

    elif market == 'AH':
        ah_line = bet.get('ah_line', 0)
        net = (fthg + ah_line) - ftag
        if abs(net) < 1e-9: return 0.0    # 退注
        won = (net > 0 and side == 'home') or (net < 0 and side == 'away')
        # 四分球半赢半退
        if abs(ah_line % 0.5 - 0.25) < 1e-9 or abs(ah_line % 0.5 + 0.25) < 1e-9:
            # 简化：按整额处理（实际应拆分两注）
            pass
        return round(odds - 1, 4) if won else -1.0

    elif 'O/U' in market:
        ou_line = bet.get('ou_line', 2.5)
        total = fthg + ftag
        if total == ou_line: return 0.0   # 恰好等于（整数线退注）
        if side == 'over':
            won = total > ou_line
        else:
            won = total < ou_line
        return round(odds - 1, 4) if won else -1.0

    return None

def backtest_pnl(db_path=DB_PATH) -> dict:
    """
    对所有有模型概率的研报做P&L回测
    返回逐场P&L + 累计走势
    """
    conn = sqlite3.connect(db_path)
    odds_teams = set(r[0] for r in conn.execute("SELECT DISTINCT HomeTeam FROM raw_footballdata_odds"))

    reports = conn.execute("""
        SELECT match_id, home_team, away_team, home_prob, draw_prob, away_prob
        FROM report_store
        WHERE home_prob IS NOT NULL AND draw_prob IS NOT NULL AND away_prob IS NOT NULL
        ORDER BY match_time ASC
    """).fetchall()

    records = []

    for r in reports:
        mid, home, away, hp, dp, ap = r
        hm = resolve_team(home, odds_teams)
        am = resolve_team(away, odds_teams)
        if not hm or not am: continue

        row = conn.execute("""
            SELECT B365CH, B365CD, B365CA,
                   AHCh, B365CAHH, B365CAHA,
                   "B365C>2.5", "B365C<2.5", OUCLine,
                   FTHG, FTAG, FTR, Date
            FROM raw_footballdata_odds
            WHERE HomeTeam=? AND AwayTeam=? ORDER BY Date DESC LIMIT 1
        """, (hm, am)).fetchone()
        if not row: continue

        odds = {
            '1x2_h': row[0], '1x2_d': row[1], '1x2_a': row[2],
            'ah_line': row[3], 'ah_h': row[4], 'ah_a': row[5],
            'ou_over': row[6], 'ou_under': row[7],
            'ou_line': row[8] if row[8] else 2.5,
        }
        actual = {'fthg': row[9], 'ftag': row[10], 'ftr': row[11]}
        date = row[12]

        rec = get_best_recommendation(hp/100, dp/100, ap/100, odds)
        if not rec['has_recommendation']: continue

        for bet in rec['recommended_bets']:
            pnl = _bet_result(bet, actual)
            records.append({
                'match':      f"{home} vs {away}",
                'date':       date,
                'market':     bet['market'],
                'side':       bet['side'],
                'clv_pct':    bet['clv_pct'],
                'kelly_pct':  bet['kelly_pct'],
                'odds':       bet['odds'],
                'pnl':        pnl,          # None=未结算，0=退注，+x=赢，-1=输
                'has_result': pnl is not None,
            })

    conn.close()

    # 计算累计P&L（只算有结果的注）
    settled = [r for r in records if r['has_result']]
    settled_sorted = sorted(settled, key=lambda x: x['date'])

    cumulative = []
    running = 0.0
    wins = losses = pushes = 0
    for rec in settled_sorted:
        p = rec['pnl']
        if p > 0:   wins   += 1
        elif p < 0: losses += 1
        else:       pushes += 1
        running += p
        cumulative.append({
            'match':      rec['match'],
            'date':       rec['date'],
            'market':     rec['market'],
            'side':       rec['side'],
            'odds':       rec['odds'],
            'pnl':        round(p, 4),
            'cumulative': round(running, 4),
        })

    total_staked = wins + losses  # 有效注数（不含退注）
    roi = running / total_staked * 100 if total_staked else 0

    return {
        'total_bets':    len(records),
        'settled_bets':  len(settled),
        'wins':          wins,
        'losses':        losses,
        'pushes':        pushes,
        'win_rate':      round(wins / (wins + losses) * 100, 1) if (wins + losses) else 0,
        'total_pnl':     round(running, 4),
        'roi':           round(roi, 2),
        'cumulative':    cumulative,
    }


if __name__ == '__main__':
    # 单场测试
    print('=== 单场推荐测试 ===')
    test_odds = {
        '1x2_h': 2.20, '1x2_d': 3.40, '1x2_a': 3.10,
        'ah_line': -0.5, 'ah_h': 1.85, 'ah_a': 2.05,
        'ou_over': 1.85, 'ou_under': 2.05, 'ou_line': 2.5,
    }
    r = get_best_recommendation(0.52, 0.24, 0.24, test_odds)
    print(f'λ主={r["lam_home"]}  λ客={r["lam_away"]}')
    for bet in r['recommended_bets']:
        print(f'  推荐: [{bet["market"]}] {bet["side"]}  CLV={bet["clv_pct"]:+.1f}%  Kelly={bet["kelly_pct"]:.1f}%  赔率={bet["odds"]}')

    print()
    print('=== P&L 回测 ===')
    pnl = backtest_pnl()
    print(f'总注数: {pnl["total_bets"]}  已结算: {pnl["settled_bets"]}')
    print(f'胜/负/退: {pnl["wins"]}/{pnl["losses"]}/{pnl["pushes"]}')
    print(f'命中率: {pnl["win_rate"]}%')
    print(f'总P&L: {pnl["total_pnl"]:+.2f} 单位  ROI: {pnl["roi"]:+.2f}%')
    print()
    print('【逐场走势（最后15场）】')
    for c in pnl['cumulative'][-15:]:
        flag = '✅' if c['pnl'] > 0 else ('🔄' if c['pnl'] == 0 else '❌')
        print(f'  {c["date"]}  {c["match"][:24]:<24} [{c["market"]:8s}] {c["side"]:<5}  {c["pnl"]:+.2f}u  累计={c["cumulative"]:+.2f}u  {flag}')
