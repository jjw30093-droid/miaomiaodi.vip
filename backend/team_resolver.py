"""
team_resolver.py
================
Phase 2 Pillar A — 统一球队名解析器

所有 fuzzy-match 需求的唯一入口，消灭以下三处重复：
  - scripts/fuzzy_match_odds.py  (TEAM_ALIASES + word_similarity)
  - titan_odds_spider.py         (calculate_overlap)
  - (populate_match_payloads.py  直查 team_id，不需要 fuzzy)

优先级：
  1. exact match on dim_team.canonical_name
  2. exact match on dim_team.aliases (JSON array)
  3. exact match on team_mapping table (legacy, 117 rows)
  4. fuzzy similarity ≥ threshold (SequenceMatcher, league-filtered)
  5. _legacy_overlap (简单单词重叠，兼容 titan_odds_spider 旧逻辑)
"""

import os
import re
import json
import sqlite3
import unicodedata
import threading
import time
import logging
from difflib import SequenceMatcher
from typing import Optional

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "football_uk.db")

log = logging.getLogger(__name__)

# ── 缓存（内存 dict，TTL=300s）────────────────────────────────────────────────
_CACHE_LOCK = threading.Lock()
_cache: dict = {}
_cache_ts: float = 0.0
_CACHE_TTL = 300  # seconds


def _load_cache(conn: Optional[sqlite3.Connection] = None) -> dict:
    """从 dim_team 和 team_mapping 表加载到内存 dict。
    返回结构：
      {
        'canonical': {canonical_name: {'team_id': int, 'canonical_name': str, 'league': str, 'aliases': list}},
        'alias':     {alias_lower: {'team_id': int, 'canonical_name': str, 'league': str}},
        'mapping':   {(div, raw_name): canonical_name},   # 来自 team_mapping 表
        'mapping_noDiv': {raw_name_lower: canonical_name},
      }
    """
    global _cache, _cache_ts
    now = time.time()

    with _CACHE_LOCK:
        if _cache and (now - _cache_ts) < _CACHE_TTL:
            return _cache

    own_conn = conn is None
    if own_conn:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
        except Exception as e:
            log.warning(f"[team_resolver] DB 连接失败: {e}")
            return _cache or {}

    result: dict = {
        'canonical': {},
        'alias':     {},
        'mapping':   {},
        'mapping_noDiv': {},
    }

    # 1. 加载 dim_team（Phase 2 迁移后存在）
    try:
        rows = conn.execute("SELECT team_id, canonical_name, league, aliases FROM dim_team").fetchall()
        for r in rows:
            entry = {
                'team_id':        r['team_id'],
                'canonical_name': r['canonical_name'],
                'league':         r['league'],
                'aliases':        json.loads(r['aliases'] or '[]'),
            }
            result['canonical'][r['canonical_name']] = entry
            result['canonical'][r['canonical_name'].lower()] = entry  # lower 也存一份
            for alias in entry['aliases']:
                result['alias'][alias.lower()] = {
                    'team_id':        r['team_id'],
                    'canonical_name': r['canonical_name'],
                    'league':         r['league'],
                }
    except Exception:
        pass  # dim_team 尚未创建（Phase 2 迁移前），静默跳过

    # 2. 加载 team_mapping 表（footballdata_name → standard_name，117 行）
    try:
        rows = conn.execute("SELECT footballdata_name, standard_name FROM team_mapping LIMIT 1000").fetchall()
        for r in rows:
            fd_name, canonical = r[0], r[1]
            if fd_name and canonical:
                result['mapping_noDiv'][fd_name.lower()] = canonical
                result['mapping'][('', fd_name)] = canonical
    except Exception:
        pass  # team_mapping 不存在，跳过

    # 3. 加载 team_name_mappings.json（"E0|TeamName" → canonical，47 条，含联赛前缀）
    try:
        _jmap_path = os.path.join(PROJECT_ROOT, "team_name_mappings.json")
        if os.path.exists(_jmap_path):
            with open(_jmap_path, encoding='utf-8') as _f:
                _jmap = json.load(_f)
            for key, canonical in _jmap.items():
                div_part = key.split('|', 1)[0] if '|' in key else ''
                raw_name = key.split('|', 1)[-1] if '|' in key else key
                result['mapping'][(div_part.upper(), raw_name)] = canonical
                result['mapping_noDiv'][raw_name.lower()] = canonical
    except Exception:
        pass

    # 4. 加载 team_mapping.json（{raw_name: canonical}，14 条）
    try:
        _jmap2_path = os.path.join(PROJECT_ROOT, "team_mapping.json")
        if os.path.exists(_jmap2_path):
            with open(_jmap2_path, encoding='utf-8') as _f:
                _jmap2 = json.load(_f)
            for raw_name, canonical in _jmap2.items():
                result['mapping_noDiv'][raw_name.lower()] = canonical
    except Exception:
        pass

    if own_conn:
        conn.close()

    with _CACHE_LOCK:
        _cache = result
        _cache_ts = now

    return result


def _normalize(s: str) -> str:
    """去重音 + 小写 + 删常见无意义词 + 按字母序"""
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('utf-8')
    s = s.lower()
    s = re.sub(
        r'\b(fc|u23|united|city|rovers|town|afc|f\.?c\.?|athletic|club|'
        r'de|la|el|vfl|vfb|sv|as|sc|1|05|04|09|cf|rcd|sd|real)\b',
        '', s
    )
    s = re.sub(r'[^a-z0-9]', ' ', s)
    words = sorted(w for w in s.split() if w)
    return ' '.join(words)


def _similarity(a: str, b: str) -> float:
    """直接字符串相似度"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _norm_similarity(a: str, b: str) -> float:
    """归一化后字符串相似度"""
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _legacy_overlap(team_name: str, target_text: str) -> float:
    """旧版 calculate_overlap 逻辑（titan_odds_spider 兼容）"""
    words = [w.lower() for w in team_name.split()
             if len(w) > 2 and w.lower() not in ('fc', 'afc', 'united', 'city')]
    if not words:
        return 0.0
    hits = sum(1 for w in words if w in target_text.lower())
    return hits / len(words)


# ── 公开 API ──────────────────────────────────────────────────────────────────

def resolve_team(
    name: str,
    league: Optional[str] = None,
    league_id: Optional[int] = None,
    date_hint: Optional[str] = None,
    threshold: float = 0.80,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[dict]:
    """
    统一球队名解析。

    Parameters
    ----------
    name       : 待解析的队名（可能是 FotMob / footballdata / NowGoal 等不同来源）
    league     : 联赛代码，如 'E0', 'SP1'（可选，提供后 fuzzy 仅在本联赛内匹配）
    league_id  : FotMob 联赛 ID（可选）
    date_hint  : 比赛日期 YYYY-MM-DD（未来可用于赛季感知，当前预留）
    threshold  : fuzzy 最小相似度（默认 0.80）
    conn       : 已有 SQLite 连接（可选，不传则内部创建）

    Returns
    -------
    dict | None
      {'team_id': int, 'canonical_name': str, 'league': str,
       'score': float, 'hit_type': str}
      hit_type ∈ {'exact_canonical', 'exact_alias', 'mapping', 'fuzzy', 'none'}
      score < threshold 时返回 None
    """
    if not name or not name.strip():
        return None

    cache = _load_cache(conn)
    name_strip = name.strip()
    name_lower = name_strip.lower()

    # 1. exact canonical（原始大小写 and 小写）
    if name_strip in cache['canonical']:
        e = cache['canonical'][name_strip]
        return {**e, 'score': 1.0, 'hit_type': 'exact_canonical'}
    if name_lower in cache['canonical']:
        e = cache['canonical'][name_lower]
        return {**e, 'score': 1.0, 'hit_type': 'exact_canonical'}

    # 2. exact alias
    if name_lower in cache['alias']:
        e = cache['alias'][name_lower]
        return {**e, 'score': 1.0, 'hit_type': 'exact_alias'}

    # 3. team_mapping 表（legacy）
    league_upper = (league or '').upper()
    mapping_key_div = (league_upper, name_strip)
    mapping_key_nodiv = name_lower
    if mapping_key_div in cache['mapping']:
        canonical = cache['mapping'][mapping_key_div]
        # 用 canonical 在 dim_team 里查 team_id
        if canonical in cache['canonical']:
            e = cache['canonical'][canonical]
            return {**e, 'score': 0.99, 'hit_type': 'mapping'}
        # dim_team 尚未建，返回 canonical_name only
        return {'team_id': None, 'canonical_name': canonical, 'league': league,
                'score': 0.99, 'hit_type': 'mapping'}
    if mapping_key_nodiv in cache['mapping_noDiv']:
        canonical = cache['mapping_noDiv'][mapping_key_nodiv]
        if canonical in cache['canonical']:
            e = cache['canonical'][canonical]
            return {**e, 'score': 0.95, 'hit_type': 'mapping'}
        return {'team_id': None, 'canonical_name': canonical, 'league': league,
                'score': 0.95, 'hit_type': 'mapping'}

    # 4. Fuzzy 相似度（在 dim_team 内）
    if not cache['canonical']:
        return None  # dim_team 为空，无法做 fuzzy

    best_score = 0.0
    best_entry = None
    for cname, entry in cache['canonical'].items():
        if cname == cname.lower() and cname != cname:
            # 跳过重复的小写 key
            continue
        # league 过滤（仅当都提供时）
        if league and entry.get('league') and entry['league'] != league:
            continue
        s1 = _similarity(name_strip, cname)
        s2 = _norm_similarity(name_strip, cname)
        sc = max(s1, s2)
        if sc > best_score:
            best_score = sc
            best_entry = entry

    if best_score >= threshold and best_entry:
        return {**best_entry, 'score': round(best_score, 4), 'hit_type': 'fuzzy'}

    return None


def resolve_pair(
    home: str,
    away: str,
    league: Optional[str] = None,
    date_hint: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> tuple:
    """
    同时解析主客两队，并检测主客颠倒情况。

    Returns
    -------
    (home_resolved, away_resolved, is_swapped)
    is_swapped=True 表示原始 home/away 实际是 away/home
    """
    h = resolve_team(home, league=league, date_hint=date_hint, conn=conn)
    a = resolve_team(away, league=league, date_hint=date_hint, conn=conn)

    # 如果正向未完全命中，尝试反向（主客互换）
    if (h is None or a is None):
        h_swap = resolve_team(away, league=league, date_hint=date_hint, conn=conn)
        a_swap = resolve_team(home, league=league, date_hint=date_hint, conn=conn)
        if h_swap and a_swap:
            h_score = (h['score'] if h else 0) + (a['score'] if a else 0)
            swap_score = h_swap['score'] + a_swap['score']
            if swap_score > h_score:
                return h_swap, a_swap, True

    return h, a, False


def resolve_nowgoal_match(
    home_team: str,
    away_team: str,
    titan_home: str,
    titan_away: str,
) -> tuple:
    """
    专为 titan_odds_spider 设计：比较 FotMob 主客队与 NowGoal 行文本的重叠度，
    返回 (avg_score, is_swapped)。
    替代旧版 calculate_overlap 内联逻辑。
    """
    h_score  = _legacy_overlap(home_team, titan_home)
    a_score  = _legacy_overlap(away_team, titan_away)
    avg_normal = (h_score + a_score) / 2

    h_score_swap = _legacy_overlap(home_team, titan_away)
    a_score_swap = _legacy_overlap(away_team, titan_home)
    avg_swap = (h_score_swap + a_score_swap) / 2

    if avg_normal >= avg_swap:
        return avg_normal, False
    else:
        return avg_swap, True


def record_alias(team_id: int, alias: str, conn: Optional[sqlite3.Connection] = None):
    """
    运行时发现新别名 → 写回 dim_team.aliases（JSON append）。
    幂等：如果别名已存在则跳过。
    同时使内存缓存失效，下次调用时重新加载。
    """
    own_conn = conn is None
    if own_conn:
        try:
            conn = sqlite3.connect(DB_PATH)
        except Exception as e:
            log.warning(f"[team_resolver] record_alias DB 连接失败: {e}")
            return

    try:
        row = conn.execute(
            "SELECT aliases FROM dim_team WHERE team_id=?", (team_id,)
        ).fetchone()
        if not row:
            return
        existing = json.loads(row[0] or '[]')
        if alias in existing:
            return
        existing.append(alias)
        conn.execute(
            "UPDATE dim_team SET aliases=?, updated_at=CURRENT_TIMESTAMP WHERE team_id=?",
            (json.dumps(existing, ensure_ascii=False), team_id)
        )
        conn.commit()
        log.info(f"[team_resolver] 新别名已记录: {alias} → team_id={team_id}")
        # 使缓存失效
        global _cache_ts
        with _CACHE_LOCK:
            _cache_ts = 0.0
    except Exception as e:
        log.warning(f"[team_resolver] record_alias 失败: {e}")
    finally:
        if own_conn:
            conn.close()


def invalidate_cache():
    """手动使缓存失效（如迁移后）"""
    global _cache_ts
    with _CACHE_LOCK:
        _cache_ts = 0.0


# ── CLI 测试 ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    names = sys.argv[1:] or [
        'Man Utd', 'Manchester United', 'Man United', 'Nott\'m Forest',
        'Bayern Munich', 'Bayern', 'Atletico Madrid', 'Athletico Madrid',
        'Paris SG', 'Wolverhampton Wanderers', 'Wolves',
    ]
    print(f"{'队名':<35} {'命中类型':<20} {'canonical':<30} {'score'}")
    print("-" * 95)
    for n in names:
        r = resolve_team(n)
        if r:
            print(f"{n:<35} {r['hit_type']:<20} {r['canonical_name']:<30} {r['score']:.3f}")
        else:
            print(f"{n:<35} {'none':<20} —")
