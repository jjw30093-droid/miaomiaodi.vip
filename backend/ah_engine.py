"""
亚盘概率映射引擎
从 WDL 概率推导任意让球线下的亚盘胜率
"""
import math
import sqlite3
import statistics
from difflib import SequenceMatcher
from typing import Dict, Tuple

MAX_GOALS = 9
KELLY_FRACTION = 0.25   # 分数Kelly（四分之一）

def poisson_prob(lam: float, k: int) -> float:
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def score_matrix(lam_h: float, lam_a: float) -> list:
    matrix = []
    for h in range(MAX_GOALS):
        row = [poisson_prob(lam_h, h) * poisson_prob(lam_a, a) for a in range(MAX_GOALS)]
        matrix.append(row)
    return matrix

def wdl_to_lambda(p_home: float, p_draw: float, p_away: float) -> Tuple[float, float]:
    """从 WDL 概率反推泊松参数（迭代校准）"""
    # 初始估计
    ratio = p_home / max(p_away, 0.01)
    base = 1.3 + (p_home + p_away) * 0.5
    lam_h = base * (ratio ** 0.4) / (1 + ratio ** 0.4) * 2
    lam_a = base * 2 - lam_h
    lam_h = max(0.3, min(4.0, lam_h))
    lam_a = max(0.3, min(4.0, lam_a))

    # 迭代校准：让生成的比分矩阵WDL接近输入概率
    for _ in range(50):
        mat = score_matrix(lam_h, lam_a)
        ph = sum(mat[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS) if h > a)
        pd = sum(mat[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS) if h == a)
        pa = sum(mat[h][a] for h in range(MAX_GOALS) for a in range(MAX_GOALS) if h < a)
        if ph + pd + pa < 1e-9: break
        ph /= (ph + pd + pa); pd /= (ph + pd + pa); pa /= (ph + pd + pa)
        err_h = p_home - ph
        err_a = p_away - pa
        if abs(err_h) < 1e-4 and abs(err_a) < 1e-4:
            break
        lam_h = max(0.3, min(4.0, lam_h + err_h * 0.5))
        lam_a = max(0.3, min(4.0, lam_a + err_a * 0.5))

    return lam_h, lam_a

def ah_prob(matrix: list, handicap: float) -> Dict[str, float]:
    """计算亚盘概率（含四分球处理）"""
    frac = handicap % 0.5
    if abs(frac - 0.25) < 1e-9 or abs(frac + 0.25) < 1e-9:
        r1 = ah_prob(matrix, handicap - 0.25)
        r2 = ah_prob(matrix, handicap + 0.25)
        return {k: (r1[k] + r2[k]) / 2 for k in r1}

    p_home_win = p_away_win = p_push = 0.0
    for h in range(MAX_GOALS):
        for a in range(MAX_GOALS):
            prob = matrix[h][a]
            net = (h + handicap) - a
            if abs(net) < 1e-9:
                p_push += prob
            elif net > 0:
                p_home_win += prob
            else:
                p_away_win += prob
    total = p_home_win + p_away_win + p_push
    return {'home_win': p_home_win/total, 'home_lose': p_away_win/total, 'push': p_push/total}

def implied_ah_prob(odds_h: float, odds_a: float) -> Dict[str, float]:
    if not odds_h or not odds_a or odds_h <= 1 or odds_a <= 1:
        return None
    raw_h, raw_a = 1/odds_h, 1/odds_a
    total = raw_h + raw_a
    return {'home_win': raw_h/total, 'home_lose': raw_a/total}


def compute_kelly(model_prob: float, odds: float, kelly_fraction: float = KELLY_FRACTION) -> float:
    """分数Kelly公式: f = (p*o-1)/(o-1) * fraction"""
    if not model_prob or not odds or odds <= 1.0:
        return 0.0
    full_kelly = (model_prob * odds - 1) / (odds - 1)
    return round(max(0.0, full_kelly * kelly_fraction), 4)

def compute_ah_clv(p_home, p_draw, p_away, ah_line, odds_h, odds_a) -> Dict:
    lam_h, lam_a = wdl_to_lambda(p_home, p_draw, p_away)
    matrix = score_matrix(lam_h, lam_a)
    model_ah = ah_prob(matrix, ah_line)
    market_ah = implied_ah_prob(odds_h, odds_a)
    if not market_ah:
        return None
    ah_clv = model_ah['home_win'] - market_ah['home_win']
    threshold = 0.04
    if ah_clv > threshold:
        rec = f"主队有利 edge={ah_clv*100:+.1f}%"
    elif ah_clv < -threshold:
        rec = f"客队有利 edge={-ah_clv*100:+.1f}%"
    else:
        rec = f"无明显优势 ({ah_clv*100:+.1f}%)"
    # Kelly 计算
    if ah_clv > 0:
        kelly = compute_kelly(model_ah['home_win'], odds_h)
        kelly_side = 'home'
        kelly_odds = odds_h
    else:
        kelly = compute_kelly(model_ah['home_lose'], odds_a)
        kelly_side = 'away'
        kelly_odds = odds_a
    if abs(ah_clv) < threshold:
        kelly = 0.0

    return {
        'lam_home': round(lam_h, 3),
        'lam_away': round(lam_a, 3),
        'ah_line': ah_line,
        'model_home_win': round(model_ah['home_win'] * 100, 1),
        'model_away_win': round(model_ah['home_lose'] * 100, 1),
        'model_push':     round(model_ah.get('push', 0) * 100, 1),
        'market_home_win': round(market_ah['home_win'] * 100, 1),
        'market_away_win': round(market_ah['home_lose'] * 100, 1),
        'ah_clv': round(ah_clv * 100, 2),
        'recommendation': rec,
        'odds_home': odds_h,
        'odds_away': odds_a,
        'kelly_stake': kelly,
        'kelly_side': kelly_side,
        'kelly_odds': kelly_odds,
    }

# ── 回测 ──────────────────────────────────────────────────────────────────

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

def backtest_ah(db_path):
    conn = sqlite3.connect(db_path)
    odds_teams = set(r[0] for r in conn.execute("SELECT DISTINCT HomeTeam FROM raw_footballdata_odds"))

    def resolve(name):
        if name in MANUAL_MAP: return MANUAL_MAP[name]
        if name in odds_teams: return name
        best, bs = None, 0
        for c in odds_teams:
            s = SequenceMatcher(None, name.lower(), c.lower()).ratio()
            if s > bs: best, bs = c, s
        return best if bs >= 0.75 else None

    reports = conn.execute("""
        SELECT match_id, home_team, away_team, home_prob, draw_prob, away_prob
        FROM report_store
        WHERE home_prob IS NOT NULL AND draw_prob IS NOT NULL AND away_prob IS NOT NULL
    """).fetchall()

    results = []
    for r in reports:
        mid, home, away, hp, dp, ap = r
        hm, am = resolve(home), resolve(away)
        if not hm or not am: continue
        row = conn.execute("""
            SELECT AHCh, B365CAHH, B365CAHA, FTHG, FTAG
            FROM raw_footballdata_odds
            WHERE HomeTeam=? AND AwayTeam=? ORDER BY Date DESC LIMIT 1
        """, (hm, am)).fetchone()
        if not row or not row[0] or not row[1]: continue
        ah_line, odds_h, odds_a, fthg, ftag = row
        res = compute_ah_clv(hp/100, dp/100, ap/100, ah_line, odds_h, odds_a)
        if not res: continue
        ah_actual = None
        if fthg is not None and ftag is not None:
            net = (fthg + ah_line) - ftag
            if abs(net) < 1e-9: ah_actual = 'push'
            elif net > 0: ah_actual = 'home'
            else: ah_actual = 'away'
        res.update({'match': f"{home} vs {away}", 'actual_ah': ah_actual, 'fthg': fthg, 'ftag': ftag})
        results.append(res)

    conn.close()
    return results

if __name__ == '__main__':
    # 单场测试
    print("=== 单场测试：主队51/23/26% AH线-0.25 ===")
    r = compute_ah_clv(0.51, 0.23, 0.26, -0.25, 1.90, 1.95)
    print(f"  λ主={r['lam_home']}  λ客={r['lam_away']}")
    print(f"  模型亚盘主胜={r['model_home_win']}% vs 市场={r['market_home_win']}%")
    print(f"  CLV={r['ah_clv']:+.2f}%  {r['recommendation']}")

    print("\n=== 回测计算中... ===")
    DB = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "football_uk.db"))
    results = backtest_ah(DB)
    print(f"可回测场次: {len(results)}")

    if results:
        clvs = [r['ah_clv'] for r in results]
        pos = [r for r in results if r['ah_clv'] > 4]
        neg = [r for r in results if r['ah_clv'] < -4]

        print(f"\n【亚盘 CLV 统计】")
        print(f"  平均CLV:      {statistics.mean(clvs):+.2f}%")
        print(f"  中位数CLV:    {statistics.median(clvs):+.2f}%")
        print(f"  CLV>4%(主队优势): {len(pos)} 场")
        print(f"  CLV<-4%(客队优势): {len(neg)} 场")

        # 有edge时命中率
        for label, side, group in [('主队有利', 'home', pos), ('客队有利', 'away', neg)]:
            valid = [r for r in group if r['actual_ah'] and r['actual_ah'] != 'push']
            hits = sum(1 for r in valid if r['actual_ah'] == side)
            if valid:
                print(f"  {label}时命中率: {hits}/{len(valid)} ({hits/len(valid)*100:.0f}%)")

        print(f"\n【逐场明细（|CLV|最大15场）】")
        print(f"  {'比赛':<30} {'线':>6} {'模型%':>6} {'市场%':>6} {'CLV':>7} {'结果':>5}")
        for r in sorted(results, key=lambda x: abs(x['ah_clv']), reverse=True)[:15]:
            flag = "✅" if (r['actual_ah']=='home' and r['ah_clv']>0) or \
                          (r['actual_ah']=='away' and r['ah_clv']<0) else \
                   "🔄" if r['actual_ah']=='push' else "❌"
            print(f"  {r['match'][:28]:<30} {r['ah_line']:>+6.2f} {r['model_home_win']:>5.1f}% {r['market_home_win']:>5.1f}% {r['ah_clv']:>+6.1f}%  {flag}")
