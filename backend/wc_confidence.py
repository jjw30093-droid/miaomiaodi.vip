"""
wc_confidence.py
================
世界杯置信分级模块。

驱动因素（非赛阶）：
  (a) 跨家共识离散度 divergence（fair_home 跨 N 家的标准差）
  (b) 最高概率段（热门 P>0.5 / 均衡 0.3-0.45 / 冷门 0.2-0.3）
  (c) 样本 n_books（书商数量）

分级规则（已锁定，不可推翻）：
  n_books < MIN_BOOKS         → SKIP  ("观望")
  divergence > DIV_HIGH       → SKIP  (书商分歧过大)
  max_p > P_HIGH_THRESHOLD
    AND divergence < DIV_LOW  → HIGH  (定价准确的热门)
  max_p > P_MID_THRESHOLD     → MID
  0.20 <= max_p <= P_MID_THRESHOLD → LOW + caution_flag + caution_text '市场高估、谨慎'
  else                        → LOW

inference 串格式（前端两个解析器须一致）：
  '【HIGH】主胜 @1.91 75.1% (h/d/a)'
  '【MID】主胜 @2.10 52.3% (h/d/a)'
  '【LOW】让步观望 (h/d/a)'
  '【SKIP】观望 — 书商分歧过大 (h/d/a)'
"""

import logging
from typing import Literal

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 阈值常量（集中管理，实现期可依数据调整）
# ──────────────────────────────────────────────────────────────────────────────

MIN_BOOKS        = 5      # n_books 少于此值 → SKIP
DIV_HIGH         = 0.06   # divergence 超过此值 → SKIP（书商分歧过大）
DIV_LOW          = 0.035  # divergence 低于此值 + max_p 高 → HIGH
P_HIGH_THRESHOLD = 0.52   # max_p 高于此值（且 div < DIV_LOW）→ HIGH
P_MID_THRESHOLD  = 0.42   # max_p 高于此值 → MID；否则 LOW

ConfidenceLevel = Literal["HIGH", "MID", "LOW", "SKIP"]

# WDL 方向中文映射
_DIRECTION_ZH = {
    "home_win": "主胜",
    "draw":     "平局",
    "away_win": "客胜",
}

# 推荐方向 → inference 前端 direction key（GlassPickBlock 用英文解析）
_DIRECTION_EN_ABBR = {
    "home_win": "home",
    "draw":     "draw",
    "away_win": "away",
}


def grade(
    wdl_probs: dict,
    divergence: float,
    n_books: int,
) -> dict:
    """
    对单场比赛的 WDL 共识概率进行置信分级。

    Args:
        wdl_probs:  {'home': float, 'draw': float, 'away': float}（去水后，和≈1）
        divergence: 跨家 fair_home 标准差（来自 wc_devig.wdl_consensus['divergence']）
        n_books:    书商数量

    Returns:
        {
          'confidence':    'HIGH'|'MID'|'LOW'|'SKIP',
          'direction':     'home_win'|'draw'|'away_win'|None,   # SKIP 时 None
          'max_prob':      float,
          'caution_flag':  bool,
          'caution_text':  str|None,  # '市场高估、谨慎' 或 None
          'skip_reason':   str|None,  # SKIP 时说明
        }
    """
    # ── 基础 SKIP 检查 ──
    if n_books < MIN_BOOKS:
        log.info(f"[wc_confidence] SKIP n_books={n_books} < {MIN_BOOKS}")
        return _skip(f"样本不足（{n_books} 家）")

    if divergence > DIV_HIGH:
        log.info(f"[wc_confidence] SKIP divergence={divergence:.4f} > {DIV_HIGH}")
        return _skip(f"书商分歧过大（divergence={divergence:.4f}）")

    # ── 找最高概率方向 ──
    direction_map = {
        "home_win": wdl_probs.get("home", 0.0),
        "draw":     wdl_probs.get("draw", 0.0),
        "away_win": wdl_probs.get("away", 0.0),
    }
    best_dir = max(direction_map, key=lambda k: direction_map[k])
    max_p = direction_map[best_dir]

    # ── 分级逻辑 ──
    if max_p > P_HIGH_THRESHOLD and divergence < DIV_LOW:
        conf: ConfidenceLevel = "HIGH"
        caution = False
        caution_text = None
    elif max_p > P_MID_THRESHOLD:
        conf = "MID"
        caution = False
        caution_text = None
    else:
        conf = "LOW"
        caution = True
        caution_text = "市场高估、谨慎"

    log.info(f"[wc_confidence] {conf} dir={best_dir} max_p={max_p:.3f} "
             f"divergence={divergence:.4f} n_books={n_books} caution={caution}")

    return {
        "confidence":   conf,
        "direction":    best_dir,
        "max_prob":     round(max_p, 6),
        "caution_flag": caution,
        "caution_text": caution_text,
        "skip_reason":  None,
    }


def _skip(reason: str) -> dict:
    return {
        "confidence":   "SKIP",
        "direction":    None,
        "max_prob":     None,
        "caution_flag": False,
        "caution_text": None,
        "skip_reason":  reason,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 单推选择器（WDL-only；联赛 WDL 被 run_tonight_reports.py:597 排除，WC 反向使用）
# ──────────────────────────────────────────────────────────────────────────────

def wc_select_single_pick(
    grade_result: dict,
    wdl_probs: dict,
    ah_implied: dict | None,
    closing_odds_row: dict | None = None,
) -> dict | None:
    """
    WC 单推选择器。只产 WDL 推荐；OU/AH 不进竞争。

    SKIP → 返回 None（外层决定是否记录"观望"）。

    Returns:
        {
          'picked_market':    'wdl',
          'picked_direction': 'home_win'|'draw'|'away_win',
          'picked_odds':      float|None,    # 来自 closing_odds_row 或 None
          'picked_confidence': 'HIGH'|'MID'|'LOW',
          'inference':        str,           # e.g. '【HIGH】主胜 @1.91 75.1% (0.571/0.198/0.231)'
          'caution_text':     str|None,
        }
        or None
    """
    conf = grade_result.get("confidence")
    if conf == "SKIP":
        return None

    direction = grade_result["direction"]
    max_p     = grade_result["max_prob"]

    # 取推荐方向的赔率（来自 closing_odds_row 或从概率反算）
    picked_odds = None
    if closing_odds_row:
        picked_odds = closing_odds_row.get("odds")
    if picked_odds is None and max_p and max_p > 0:
        # 无赔率时用 fair_prob 粗估（仅展示用，不作投注依据）
        picked_odds = round(1.0 / max_p, 2)

    h = wdl_probs.get("home", 0.0)
    d = wdl_probs.get("draw", 0.0)
    a = wdl_probs.get("away", 0.0)

    direction_zh = _DIRECTION_ZH.get(direction, direction)
    prob_pct     = round(max_p * 100, 1)

    caution_text = grade_result.get("caution_text")
    caution_str  = f"（{caution_text}）" if caution_text else ""

    if picked_odds:
        inference = (
            f"【{conf}】{direction_zh}{caution_str} @{picked_odds:.2f} "
            f"{prob_pct}% ({h:.3f}/{d:.3f}/{a:.3f})"
        )
    else:
        inference = (
            f"【{conf}】{direction_zh}{caution_str} "
            f"{prob_pct}% ({h:.3f}/{d:.3f}/{a:.3f})"
        )

    log.info(f"[wc_select_single_pick] {inference}")

    return {
        "picked_market":     "wdl",
        "picked_direction":  direction,
        "picked_odds":       picked_odds,
        "picked_confidence": conf,
        "inference":         inference,
        "caution_text":      caution_text,
    }
