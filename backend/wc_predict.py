"""
wc_predict.py
=============
世界杯 WDL 预测模块。

无 WC 专属机器学习模型（WC 特征集与联赛截然不同，且仅有 2018/2022 两届历史数据）。
WC 预测直接使用去水后的市场共识概率作为 WDL/OU 概率——市场共识本身就是最优先验。

用法：
    from wc_predict import wc_predict
    pred = wc_predict(wdl_consensus, ou_consensus)

设计原则（已锁定，不可推翻）：
  - WC pick 只产 WDL；OU/AH 不进推荐竞争
  - 市场共识 = 去水后 N=10-14 家中位；无 recency 加权（2018/2022 等权先验）
  - 不调用联赛 predict_engine，不加载 model_wdl.lgb
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)


def wc_predict(
    wdl_consensus: dict,
    ou_consensus: dict | None = None,
) -> dict:
    """
    用市场共识概率作为 WC WDL 预测结果。

    Args:
        wdl_consensus: devig_consensus()['wdl_consensus'] 的结果
                       需要包含 'home', 'draw', 'away', 'n_books', 'divergence'
        ou_consensus:  devig_consensus()['ou_consensus'] 的结果（可选，仅展示不推荐）

    Returns:
        {
          'wdl': {'home': float, 'draw': float, 'away': float},
          'ou':  {'over': float, 'under': float, 'line': str} | None,
          'n_books_wdl': int,
          'divergence':  float,
          'source': 'market_consensus',    # 标注预测来源
          'model_meta': {
              'method': 'lean_median_devig',
              'wdl_books': int,
              'ou_books': int | None,
              'is_calibrated': False,       # 无 ML 校准
          }
        }
    """
    if not wdl_consensus:
        raise ValueError("[wc_predict] wdl_consensus is empty — devig failed upstream")

    h = wdl_consensus.get("home")
    d = wdl_consensus.get("draw")
    a = wdl_consensus.get("away")
    n = wdl_consensus.get("n_books", 0)
    div = wdl_consensus.get("divergence", 0.0)

    if h is None or d is None or a is None:
        raise ValueError("[wc_predict] wdl_consensus missing prob fields")

    log.info(f"[wc_predict] WDL h={h:.3f} d={d:.3f} a={a:.3f} n_books={n} divergence={div:.4f}")

    # OU（仅展示，不参与推荐）
    ou_out: Optional[dict] = None
    ou_n = None
    if ou_consensus:
        ou_out = {
            "over":                ou_consensus.get("over"),
            "under":               ou_consensus.get("under"),
            "line":                ou_consensus.get("line"),
            "split":               ou_consensus.get("split"),
            "baseline_disclaimer": ou_consensus.get("baseline_disclaimer"),
        }
        ou_n = ou_consensus.get("n_books")
        log.info(f"[wc_predict] OU line={ou_out['line']} over={ou_out['over']:.3f} "
                 f"under={ou_out['under']:.3f} n_books={ou_n} (display-only, no pick)")

    return {
        "wdl": {
            "home": h,
            "draw": d,
            "away": a,
        },
        "ou": ou_out,
        "n_books_wdl": n,
        "divergence":  div,
        "source": "market_consensus",
        "model_meta": {
            "method":       "lean_median_devig",
            "wdl_books":    n,
            "ou_books":     ou_n,
            "is_calibrated": False,
        },
    }
