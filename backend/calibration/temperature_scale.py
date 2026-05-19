"""
temperature_scale.py
====================
A3: WDL 温度缩放 + 主场偏置校正

使用 prediction_audit 中已审计行，用 scipy.optimize 拟合温度参数 T
使 softmax(log(p)/T) 的交叉熵在验证集上最小。

同时计算三路方向的全局偏置：
  home_bias = avg(pred_home) - actual_home_rate
  draw_bias = avg(pred_draw) - actual_draw_rate
  away_bias = avg(pred_away) - actual_away_rate

产出：models_v4/calibration.json
  {
    "wdl_temperature": float,    # 温度参数（>1 更平 / <1 更尖）
    "home_adj": float,           # 主场概率加法修正（负值 = 降低主场概率）
    "draw_adj": float,
    "away_adj": float,
    "n_samples": int,
    "updated_at": str
  }

用法：
  python3 calibration/temperature_scale.py
  python3 calibration/temperature_scale.py --dry
"""

import os
import sys
import json
import sqlite3
import argparse
import logging
import numpy as np
from datetime import datetime

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH      = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))
MODEL_DIR    = os.path.join(PROJECT_ROOT, "models_v4")
OUT_PATH     = os.path.join(MODEL_DIR, "calibration.json")
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

WDL_MAP = {"home_win": 0, "draw": 1, "away_win": 2}


def softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


def cross_entropy(probs: np.ndarray, labels: np.ndarray) -> float:
    """probs: (N, 3)，labels: (N,) int 0/1/2"""
    eps = 1e-7
    return -np.mean(np.log(probs[np.arange(len(labels)), labels] + eps))


def temperature_loss(T: float, log_probs: np.ndarray, labels: np.ndarray) -> float:
    cal_probs = softmax(log_probs / T)
    return cross_entropy(cal_probs, labels)


def fit_temperature(conn) -> dict:
    """
    计算 WDL 方向偏置校正（加法）。
    策略：用实际频率 − 模型均值作为加法修正项，不使用温度缩放。
    原因：温度 T 过大时会压平极端预测（如 0.72→0.51），导致 HIGH 置信被误判为 SKIP。
    加法修正在保持极端预测相对大小的同时，让平均概率收敛到实际频率。
    """
    # 读取有实际结果的行
    rows = conn.execute("""
        SELECT pred_wdl_home, pred_wdl_draw, pred_wdl_away, actual_wdl
        FROM prediction_audit
        WHERE actual_wdl IS NOT NULL
          AND pred_wdl_home IS NOT NULL
          AND pred_wdl_draw IS NOT NULL
          AND pred_wdl_away IS NOT NULL
    """).fetchall()

    if len(rows) < 10:
        log.warning(f"样本不足（{len(rows)} 行），返回默认参数")
        return {"wdl_temperature": 1.0, "home_adj": 0.0, "draw_adj": 0.0, "away_adj": 0.0,
                "n_samples": len(rows), "status": "insufficient"}

    probs  = np.array([[r[0], r[1], r[2]] for r in rows], dtype=float)
    labels = np.array([WDL_MAP.get(r[3], -1) for r in rows])

    # 过滤无效行
    valid = labels >= 0
    probs  = probs[valid]
    labels = labels[valid]
    n = len(labels)

    # 归一化
    probs = probs / probs.sum(axis=1, keepdims=True)
    eps = 1e-7
    probs = np.clip(probs, eps, 1 - eps)

    # 实际频率（one-hot 平均）
    one_hot = np.zeros((n, 3))
    one_hot[np.arange(n), labels] = 1.0
    actual_rates = one_hot.mean(axis=0)   # [home_rate, draw_rate, away_rate]

    # 模型平均预测
    pred_avg = probs.mean(axis=0)

    # 加法修正量 = 实际频率 − 模型均值（期望应用于每个预测，使均值对齐）
    home_adj = round(float(actual_rates[0] - pred_avg[0]), 4)
    draw_adj = round(float(actual_rates[1] - pred_avg[1]), 4)
    away_adj = round(float(actual_rates[2] - pred_avg[2]), 4)

    # 校准后的均值（用于验证）
    cal_avg = pred_avg + np.array([home_adj, draw_adj, away_adj])

    # 交叉熵改善估算（加法校正在期望意义上收敛，此处计算均值对齐后的近似改善）
    loss_before = cross_entropy(probs, labels)
    # 对验证集应用加法修正
    cal_probs = probs + np.array([[home_adj, draw_adj, away_adj]])
    cal_probs = np.clip(cal_probs, eps, None)
    cal_probs = cal_probs / cal_probs.sum(axis=1, keepdims=True)
    loss_after = cross_entropy(cal_probs, labels)

    log.info(f"样本数: {n}")
    log.info(f"实际频率: H={actual_rates[0]:.3f} D={actual_rates[1]:.3f} A={actual_rates[2]:.3f}")
    log.info(f"原始均值: H={pred_avg[0]:.3f} D={pred_avg[1]:.3f} A={pred_avg[2]:.3f}")
    log.info(f"加法修正: H={home_adj:+.4f} D={draw_adj:+.4f} A={away_adj:+.4f}")
    log.info(f"校准均值: H={cal_avg[0]:.3f} D={cal_avg[1]:.3f} A={cal_avg[2]:.3f}")
    log.info(f"交叉熵: {loss_before:.4f} → {loss_after:.4f}  (Δ={loss_before-loss_after:+.4f})")

    return {
        "wdl_temperature": 1.0,   # 不使用温度缩放（保留字段向后兼容）
        "home_adj":        home_adj,
        "draw_adj":        draw_adj,
        "away_adj":        away_adj,
        "n_samples":       n,
        "cross_entropy_before": round(loss_before, 4),
        "cross_entropy_after":  round(loss_after,  4),
        "updated_at": datetime.utcnow().isoformat(),
        "status": "ok",
    }


def apply_wdl_calibration(wdl: dict, calib: dict) -> dict:
    """
    推理时调用：对 WDL 字典应用加法偏置校正。
    使用加法（而非温度缩放）避免极端预测被过度压平（如 0.72 不会压到 0.51）。
    wdl: {"home": float, "draw": float, "away": float}
    返回校正后的同结构字典。
    """
    hadj = calib.get("home_adj", 0.0)
    dadj = calib.get("draw_adj", 0.0)
    aadj = calib.get("away_adj", 0.0)

    p = [wdl["home"] + hadj,
         wdl["draw"] + dadj,
         wdl["away"] + aadj]

    # 钳位到 [0.01, 0.99] 范围
    p = [max(0.01, min(0.99, x)) for x in p]

    # 重归一化
    s = sum(p)
    cal = [x / s for x in p]

    return {"home": round(cal[0], 4), "draw": round(cal[1], 4), "away": round(cal[2], 4)}


def load_calibration(model_dir: str = MODEL_DIR) -> dict:
    """推理时加载校正参数。若文件不存在，返回恒等变换。"""
    path = os.path.join(model_dir, "calibration.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"wdl_temperature": 1.0, "home_adj": 0.0, "draw_adj": 0.0, "away_adj": 0.0}


def main(dry_run: bool = False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    calib = fit_temperature(conn)
    conn.close()

    if calib.get("status") == "insufficient":
        log.warning("数据不足，不更新 calibration.json")
        return calib

    if dry_run:
        log.info("DRY RUN — 不写入文件")
        print(json.dumps(calib, indent=2, ensure_ascii=False))
        return calib

    os.makedirs(MODEL_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(calib, f, indent=2, ensure_ascii=False)
    log.info(f"✅ 写入: {OUT_PATH}")
    return calib


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry)
