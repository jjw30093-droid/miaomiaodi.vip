"""
wc_devig.py
===========
世界杯去水中位共识模块。

用法：
    from wc_devig import devig_consensus
    result = devig_consensus(conn_wc, fixture_id=19609127, period='opening')

返回结构：
    {
      'wdl_consensus': {
          'home': float, 'draw': float, 'away': float,
          'n_books': int, 'divergence': float   # std of fair_home across books
      },
      'ou_consensus': {
          'line': str,        # e.g. '2.5' or '2.0,2.5'
          'over': float,
          'under': float,
          'n_books': int,
          'split': str,       # 'simple' | 'quarter'
          'baseline_disclaimer': str
      },
      'ah_implied': {
          'line': float,      # median handicap (negative = home favored)
          'magnitude': float, # abs value
          'n_books': int
      },
      'market_id_used': {'wdl': 1, 'ou': 7, 'ah': int|None}
    }

period='opening'  → reads from wc_odds
period='closing'  → reads from wc_odds_snapshot
"""

import logging
import statistics
from typing import Optional

# [REUSE-IMPORT] 复用 silver_builder 的去水原语（不修改源文件）
from silver_builder import _normalize_3way, _normalize_2way  # type: ignore

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────────────

WDL_MARKET_ID = 1
OU_MARKET_ID = 7   # Goal Line (= Exact Total Goals，非 market-80)

# OU "历史基线建立中" 免责声明（必须出现在所有 OU 展示场景）
OU_BASELINE_DISCLAIMER = "历史基线建立中，2026实盘滚动验证"

# 已知的 label 映射（SportMonks WC 数据）
_WDL_HOME_LABELS   = {"home", "1", "home win"}
_WDL_DRAW_LABELS   = {"draw", "x", "draw/draw"}
_WDL_AWAY_LABELS   = {"away", "2", "away win"}
_OU_OVER_LABELS    = {"over"}
_OU_UNDER_LABELS   = {"under"}


# ──────────────────────────────────────────────────────────────────────────────
# 内部辅助
# ──────────────────────────────────────────────────────────────────────────────

def _safe_float(v) -> Optional[float]:
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(v)
    except (ValueError, TypeError):
        return None


def _classify_wdl_label(label: str, home_team: str = "", away_team: str = "") -> Optional[str]:
    """把 SportMonks label 归一化为 'home'|'draw'|'away'|None。"""
    if not label:
        return None
    lo = label.strip().lower()
    if lo in _WDL_HOME_LABELS:
        return "home"
    if lo in _WDL_DRAW_LABELS:
        return "draw"
    if lo in _WDL_AWAY_LABELS:
        return "away"
    # 球队名匹配（宽松前缀）
    if home_team and lo.startswith(home_team.strip().lower()[:4]):
        return "home"
    if away_team and lo.startswith(away_team.strip().lower()[:4]):
        return "away"
    return None


def _median_safe(values: list) -> Optional[float]:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return statistics.median(clean)


# ──────────────────────────────────────────────────────────────────────────────
# 读取函数
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_odds_rows(conn, fixture_id: int, market_id: int, period: str) -> list[dict]:
    """
    从 wc_odds（period='opening'）或 wc_odds_snapshot（period='closing'）
    读取指定 fixture + market 的所有赔率行。
    """
    if period == "closing":
        sql = """
            SELECT bookmaker_id, label, value, total, handicap, probability
            FROM   wc_odds_snapshot
            WHERE  fixture_sportmonks_id = ?
              AND  market_id = ?
        """
    else:
        sql = """
            SELECT bookmaker_id, label, value, total, handicap, probability
            FROM   wc_odds
            WHERE  fixture_sportmonks_id = ?
              AND  market_id = ?
        """
    try:
        rows = conn.execute(sql, (fixture_id, market_id)).fetchall()
    except Exception as e:
        log.warning(f"[wc_devig] fetch odds rows failed (fixture={fixture_id}, market={market_id}): {e}")
        return []
    return [dict(r) for r in rows]


def _fetch_fixture_teams(conn, fixture_id: int) -> tuple[str, str]:
    """返回 (home_team_name, away_team_name)，可能为空串。"""
    try:
        row = conn.execute(
            "SELECT home_team_name, away_team_name FROM wc_fixtures WHERE sportmonks_id=?",
            (fixture_id,)
        ).fetchone()
        if row:
            return row[0] or "", row[1] or ""
    except Exception:
        pass
    return "", ""


# ──────────────────────────────────────────────────────────────────────────────
# WDL 去水
# ──────────────────────────────────────────────────────────────────────────────

def _devig_wdl(rows: list[dict], home_team: str = "", away_team: str = "") -> dict:
    """
    每家各跑 _normalize_3way → 跨家取中位 → 归一化。
    返回 {'home', 'draw', 'away', 'n_books', 'divergence'} 或 None。
    """
    # 按 bookmaker_id 分组
    books: dict[int, dict[str, float]] = {}
    for r in rows:
        bid  = r["bookmaker_id"]
        side = _classify_wdl_label(r.get("label", ""), home_team, away_team)
        val  = _safe_float(r.get("value"))
        if side is None or val is None or val <= 0:
            continue
        books.setdefault(bid, {})[side] = val

    per_book_fair: list[dict] = []
    for bid, odds in books.items():
        h = odds.get("home")
        d = odds.get("draw")
        a = odds.get("away")
        if h is None or d is None or a is None:
            continue
        fh, fd, fa, over = _normalize_3way(h, d, a)
        if fh is None:
            continue
        per_book_fair.append({"home": fh, "draw": fd, "away": fa})

    n = len(per_book_fair)
    if n == 0:
        return {}

    homes  = [b["home"]  for b in per_book_fair]
    draws  = [b["draw"]  for b in per_book_fair]
    aways  = [b["away"]  for b in per_book_fair]

    med_h = statistics.median(homes)
    med_d = statistics.median(draws)
    med_a = statistics.median(aways)

    # 归一化（中位数之和不一定恰好=1，做一次修正）
    total = med_h + med_d + med_a
    if total <= 0:
        return {}

    div = statistics.stdev(homes) if n >= 2 else 0.0

    return {
        "home":       round(med_h / total, 6),
        "draw":       round(med_d / total, 6),
        "away":       round(med_a / total, 6),
        "n_books":    n,
        "divergence": round(div, 6),
    }


# ──────────────────────────────────────────────────────────────────────────────
# OU 去水
# ──────────────────────────────────────────────────────────────────────────────

def _devig_ou(rows: list[dict]) -> dict:
    """
    market7 Goal Line 去水。

    支持两种 total 格式：
      - "2.5"       → simple line（过/不过）
      - "2.0,2.5"   → quarter line（四分盘，使用复合赔率直接去水，无需拆腿）

    每家各跑 _normalize_2way(over_odds, under_odds) → 跨家取中位。
    返回 {'line', 'over', 'under', 'n_books', 'split', 'baseline_disclaimer'} 或 {}。
    """
    # 按 (bookmaker_id, total) 分组
    books_by_line: dict[str, dict] = {}   # key: "bookmaker_id|total"
    for r in rows:
        bid   = r["bookmaker_id"]
        label = (r.get("label") or "").strip().lower()
        val   = _safe_float(r.get("value"))
        total = (r.get("total") or "").strip()
        if val is None or val <= 0 or not total:
            continue
        key = f"{bid}|{total}"
        if label in _OU_OVER_LABELS:
            books_by_line.setdefault(key, {"bid": bid, "total": total})["over"] = val
        elif label in _OU_UNDER_LABELS:
            books_by_line.setdefault(key, {"bid": bid, "total": total})["under"] = val

    if not books_by_line:
        return {}

    # 找最常见的线（majority vote），排除不完整对
    complete = [v for v in books_by_line.values() if "over" in v and "under" in v]
    if not complete:
        return {}

    from collections import Counter
    total_counts = Counter(v["total"] for v in complete)
    main_line = total_counts.most_common(1)[0][0]
    split = "quarter" if "," in main_line else "simple"

    per_book_fair: list[dict] = []
    for v in complete:
        if v["total"] != main_line:
            continue
        fo, fu, _ = _normalize_2way(v["over"], v["under"])
        if fo is None:
            continue
        per_book_fair.append({"over": fo, "under": fu})

    n = len(per_book_fair)
    if n == 0:
        return {}

    overs  = [b["over"]  for b in per_book_fair]
    unders = [b["under"] for b in per_book_fair]

    med_o = statistics.median(overs)
    med_u = statistics.median(unders)
    total_p = med_o + med_u
    if total_p <= 0:
        return {}

    return {
        "line":                 main_line,
        "over":                 round(med_o / total_p, 6),
        "under":                round(med_u / total_p, 6),
        "n_books":              n,
        "split":                split,
        "baseline_disclaimer":  OU_BASELINE_DISCLAIMER,
    }


# ──────────────────────────────────────────────────────────────────────────────
# AH 隐含让球
# ──────────────────────────────────────────────────────────────────────────────

def _devig_ah(rows: list[dict]) -> dict:
    """
    AH：仅取中位让球幅度，绝不返回胜率/probability。
    返回 {'line', 'magnitude', 'n_books'} 或 {}。
    """
    lines: list[float] = []
    seen_bids: set = set()
    for r in rows:
        bid  = r["bookmaker_id"]
        if bid in seen_bids:
            continue
        hcap = _safe_float(r.get("handicap"))
        if hcap is None:
            continue
        seen_bids.add(bid)
        lines.append(hcap)

    if not lines:
        return {}

    med_line = statistics.median(lines)
    return {
        "line":      round(med_line, 2),
        "magnitude": round(abs(med_line), 2),
        "n_books":   len(lines),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 公开 API
# ──────────────────────────────────────────────────────────────────────────────

def devig_consensus(conn, fixture_id: int, period: str = "opening") -> dict:
    """
    主入口：对 wc_fixtures 中的 fixture_id 计算三市场去水共识。

    Args:
        conn      : worldcup.db sqlite3 connection（调用方持有）
        fixture_id: SportMonks fixture ID（整数，非 'wc_' 前缀形式）
        period    : 'opening'（读 wc_odds）| 'closing'（读 wc_odds_snapshot）

    Returns:
        dict with keys: wdl_consensus, ou_consensus, ah_implied, market_id_used
        任何子市场无数据时，对应 key 为空 dict {}。
    """
    log.info(f"[wc_devig] devig_consensus fixture={fixture_id} period={period}")

    home_team, away_team = _fetch_fixture_teams(conn, fixture_id)

    # ── WDL ──
    wdl_rows = _fetch_odds_rows(conn, fixture_id, WDL_MARKET_ID, period)
    wdl      = _devig_wdl(wdl_rows, home_team, away_team)
    if wdl:
        log.info(f"  WDL n_books={wdl['n_books']} divergence={wdl['divergence']:.4f} "
                 f"h={wdl['home']:.3f} d={wdl['draw']:.3f} a={wdl['away']:.3f}")
    else:
        log.warning(f"  WDL: no usable rows (period={period})")

    # ── OU (market7) ──
    ou_rows = _fetch_odds_rows(conn, fixture_id, OU_MARKET_ID, period)
    ou      = _devig_ou(ou_rows)
    if ou:
        log.info(f"  OU  line={ou['line']} split={ou['split']} n_books={ou['n_books']} "
                 f"over={ou['over']:.3f} under={ou['under']:.3f}")
    else:
        log.warning(f"  OU: no usable rows (period={period})")

    # ── AH (any market_id with handicap data) ──
    # AH 的 market_id 在 SportMonks WC 数据中不固定，尝试常见 id
    ah = {}
    ah_mid_used = None
    for mid in (2, 10, 45, 46, 47, 48):   # 常见亚盘 market_id
        ah_rows = _fetch_odds_rows(conn, fixture_id, mid, period)
        if ah_rows:
            ah = _devig_ah(ah_rows)
            if ah:
                ah_mid_used = mid
                log.info(f"  AH  market_id={mid} line={ah['line']} magnitude={ah['magnitude']} n_books={ah['n_books']}")
                break

    return {
        "wdl_consensus":  wdl,
        "ou_consensus":   ou,
        "ah_implied":     ah,
        "market_id_used": {
            "wdl": WDL_MARKET_ID,
            "ou":  OU_MARKET_ID,
            "ah":  ah_mid_used,
        },
    }
