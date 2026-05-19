"""
pick_parser.py
==============
共享解析器：从 report_store.inference 文本反解出结构化 picks。

业务前提：每场比赛收费 → 前端必显示推荐 → inference 是 source of truth。
任何场景下若 prediction_audit.picked_market 缺失但 inference 存在，必须能用
本模块反解并补写，保持两者一致（CLAUDE.md §16）。

典型 inference 字符串格式：
  "小球(≤2.0) @1.78 65.4%  (43.5%/30.8%/25.6%)"
  "客胜 @1.67 82.5%  (6.9%/18.3%/74.8%)  +  客让0.75 @1.83 82.0%"   双推
  "主让0.75 @1.8 88.9%  (62.2%/21.9%/15.9%)"

返回 dict 字段与 ReviewEngine.record_picked 期望签名一致：
  {"market": "wdl"|"ou"|"ah", "direction": str, "odds": float|None,
   "confidence": str|None, "secondary": dict|None}

direction 取值：
  wdl: home_win / draw / away_win
  ou:  over / under
  ah:  ah_home / ah_away
"""

import re
import logging
from typing import Optional

log = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────
# picked_correct 计算（共享）
# CLAUDE.md §18 picked_direction 字符串约定铁律：
#   canonical = 长形式（与 actual_wdl 同一字典）
#     WDL: home_win / draw / away_win
#     OU:  over / under
#     AH:  ah_home / ah_away
#   读取路径必须双形式容错（兼容历史短形式 home/away/ah_home/ah_away）
#   未知值返 None + log.error，不能默认 0（那是错判）
# ───────────────────────────────────────────────────────────

_WDL_NORMALIZE = {
    'home': 'home_win', 'home_win': 'home_win',
    'draw': 'draw',
    'away': 'away_win', 'away_win': 'away_win',
}
_AH_NORMALIZE = {
    'home': 'ah_home', 'ah_home': 'ah_home',
    'away': 'ah_away', 'ah_away': 'ah_away',
}


def compute_picked_correct(picked_market, picked_direction, hs, as_, ah_line, ou_line):
    """统一的 picked_correct 计算，与 review_engine.audit_match 对齐。

    返回：
      1   = 命中（赢）
      0   = 未命中（输）
     -1   = 走水（push，本金返还，不计盈亏）
      None = 数据异常 / 缺分数（异常时同时打 ERROR，不能默认 0）

    picked_correct = -1 与 NULL 的区别：
      -1  = 审计已完成，结果为走水
      NULL = 尚未审计 / 缺失数据
    """
    if hs is None or as_ is None or picked_direction is None:
        return None

    if picked_market == 'wdl':
        target = _WDL_NORMALIZE.get(picked_direction)
        if target is None:
            log.error(f"[compute_picked_correct] WDL 未知方向 {picked_direction!r}（hs={hs} as={as_}）")
            return None
        if hs > as_:
            actual = 'home_win'
        elif hs < as_:
            actual = 'away_win'
        else:
            actual = 'draw'
        return 1 if target == actual else 0

    if picked_market == 'ou':
        line = ou_line if ou_line is not None else 2.5
        total = hs + as_
        diff = total - line
        if diff == 0:
            return -1  # 走水（整数线，总进球 = 线值）
        if picked_direction == 'over':
            return 1 if diff > 0 else 0
        if picked_direction == 'under':
            return 1 if diff < 0 else 0
        log.error(f"[compute_picked_correct] OU 未知方向 {picked_direction!r}")
        return None

    if picked_market == 'ah':
        if ah_line is None:
            return None
        side = _AH_NORMALIZE.get(picked_direction)
        if side is None:
            log.error(f"[compute_picked_correct] AH 未知方向 {picked_direction!r}")
            return None
        adj = hs - as_ - ah_line
        if adj == 0:
            return -1  # 走水（净胜球恰好等于让球线）
        if adj > 0:
            return 1 if side == 'ah_home' else 0
        return 1 if side == 'ah_away' else 0

    log.error(f"[compute_picked_correct] 未知 market {picked_market!r}")
    return None


_ODDS_RE   = re.compile(r'@\s*(\d+(?:\.\d+)?)')
_CONF_RE   = re.compile(r'(\d+(?:\.\d+)?)\s*%')
_OU_LE_RE  = re.compile(r'≤\s*(\d+(?:\.\d+)?)')
_OU_GT_RE  = re.compile(r'>\s*(\d+(?:\.\d+)?)')


def _parse_one(segment: str) -> Optional[dict]:
    """解析单段（不含 '+' 分隔的子串）。返回 dict 或 None。

    检测顺序很重要：
    1) 大球/小球（OU）—— 先于 AH，避免 "小球(≤2.0)" 中 ≤ 不被误读
    2) WDL（主胜 / 客胜 / 平局）—— 先于 AH，避免 "客胜" 中误把 "客" 当 AH
    3) AH（主让 / 客让）
    """
    if not segment:
        return None
    s = segment.strip()
    if not s:
        return None

    odds_m = _ODDS_RE.search(s)
    conf_m = _CONF_RE.search(s)
    odds = float(odds_m.group(1)) if odds_m else None
    conf = f"{float(conf_m.group(1)):.1f}%" if conf_m else None

    # 1) OU
    if '小球' in s or '≤' in s:
        return {"market": "ou", "direction": "under", "odds": odds, "confidence": conf}
    if '大球' in s or '>' in s:
        return {"market": "ou", "direction": "over",  "odds": odds, "confidence": conf}

    # 2) WDL —— 注意必须先于 AH 检测
    if '主胜' in s:
        return {"market": "wdl", "direction": "home_win", "odds": odds, "confidence": conf}
    if '客胜' in s:
        return {"market": "wdl", "direction": "away_win", "odds": odds, "confidence": conf}
    if '平局' in s or s.startswith('平') or '平 @' in s:
        return {"market": "wdl", "direction": "draw", "odds": odds, "confidence": conf}

    # 3) AH
    if '主让' in s:
        return {"market": "ah", "direction": "ah_home", "odds": odds, "confidence": conf}
    if '客让' in s:
        return {"market": "ah", "direction": "ah_away", "odds": odds, "confidence": conf}

    return None


def parse_inference(inference: str) -> Optional[dict]:
    """从 inference 文本反解出 picks。

    支持双推格式 "A + B"：取 + 左侧为 primary，右侧入 secondary。
    左右两侧分别独立解析（避免 "客胜 + 客让0.75" 中 客让 误覆盖 客胜）。

    返回 None 表示无法解析（典型场景：inference 为空或全是 markdown）。
    """
    if not inference:
        return None

    # 用 " + " 分割（前后必须有空格，避免误切 "客让0.75" 中的 +/-）
    parts = re.split(r'\s+\+\s+', inference, maxsplit=1)
    primary = _parse_one(parts[0])
    if primary is None:
        return None

    if len(parts) == 2:
        secondary = _parse_one(parts[1])
        if secondary:
            primary["secondary"] = secondary

    return primary


# ───────────────────────────────────────────────────────────
# 自测：python3 pick_parser.py
# ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    cases = [
        # (inference, expected_market, expected_direction)
        ('小球(≤2.0) @1.78 65.4%  (43.5%/30.8%/25.6%)', 'ou', 'under'),
        ('大球(>2.5) @1.85 68.3%', 'ou', 'over'),
        ('客胜 @1.67 82.5%  (6.9%/18.3%/74.8%)  +  客让0.75 @1.83 82.0%', 'wdl', 'away_win'),
        ('主胜 @2.05 60.0%', 'wdl', 'home_win'),
        ('平局 @3.20 30.5%', 'wdl', 'draw'),
        ('主让0.75 @1.8 88.9%  (62.2%/21.9%/15.9%)', 'ah', 'ah_home'),
        ('客让0.25 @1.95 56.9%  (38.6%/42.9%/18.5%)', 'ah', 'ah_away'),
    ]
    ok = 0
    for inf, em, ed in cases:
        r = parse_inference(inf)
        assert r and r['market'] == em and r['direction'] == ed, f"FAIL: {inf!r} → {r}"
        print(f"OK  {em}/{ed:9} ← {inf[:50]}")
        ok += 1

    # 双推：primary=客胜, secondary=ah_away
    r = parse_inference('客胜 @1.67 82.5%  +  客让0.75 @1.83 82.0%')
    assert r['market'] == 'wdl' and r['direction'] == 'away_win'
    assert r.get('secondary', {}).get('market') == 'ah'
    assert r['secondary']['direction'] == 'ah_away'
    print("OK  双推 primary=wdl/away_win + secondary=ah/ah_away")
    ok += 1

    # 空 / 不可解析
    assert parse_inference("") is None
    assert parse_inference(None) is None
    assert parse_inference("# Markdown header") is None
    print("OK  空 / 不可解析返回 None")
    ok += 1

    # ── compute_picked_correct 双形式容错测试 ──
    cpc = compute_picked_correct
    # WDL 长形式
    assert cpc('wdl', 'home_win', 1, 0, None, None) == 1
    assert cpc('wdl', 'away_win', 1, 0, None, None) == 0
    assert cpc('wdl', 'draw',     1, 1, None, None) == 1
    # WDL 短形式（历史兼容）
    assert cpc('wdl', 'home', 1, 0, None, None) == 1
    assert cpc('wdl', 'away', 1, 0, None, None) == 0
    # OU
    assert cpc('ou', 'over',  3, 1, None, 2.5) == 1
    assert cpc('ou', 'under', 1, 0, None, 2.5) == 1
    assert cpc('ou', 'over',  2, 1, None, 3.0) == -1  # 走水：总球数=线值
    # AH 长形式 + 短形式
    assert cpc('ah', 'ah_home', 2, 0, None, None) is None  # ah_line=None → None
    assert cpc('ah', 'ah_home', 2, 0, -0.5, None) == 1
    assert cpc('ah', 'home',    2, 0, -0.5, None) == 1
    assert cpc('ah', 'ah_away', 2, 0, -0.5, None) == 0
    assert cpc('ah', 'ah_home', 1, 0, 1.0, None) == -1  # 走水：净胜=让球线
    # 未知方向 → None
    import logging as _lg
    _lg.disable(_lg.CRITICAL)
    assert cpc('wdl', 'banana', 1, 0, None, None) is None
    assert cpc('xx',  'home',   1, 0, None, None) is None
    _lg.disable(_lg.NOTSET)
    print("OK  compute_picked_correct 双形式 + 未知值容错")
    ok += 1

    print(f"\n=> {ok} cases passed.")
