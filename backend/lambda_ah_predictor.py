"""
lambda_ah_predictor.py — V5 Lambda 双 CatBoost AH 推理包装（2026-05-04 上线）
============================================================================

接管 v4 ah_model.AHPredictor，返回字典签名完全兼容：
  {'ah_cover': float, 'ah_push': float, 'ah_away_cover': float, ...}

不在 SUPPORTED_LEAGUES 时返回 None → 调用方让 OU 单独竞争。
mart_lambda_dataset_v5 中找不到该 match_id 时也返回 None（特征行未生成）。

模型管线（已落库）：
  1) 4 个 CatBoost Poisson 回归预测 λ_home / λ_away
     Model_H_Full + Model_A_Full（含赔率特征）
     Model_H_Pure + Model_A_Pure（不含赔率值，仅盘口线）
  2) Ensemble: λ = 0.6 × Full + 0.4 × Pure
  3) 取 ρ：rho.json["rho_by_league"] 或 fallback 全局 ρ
  4) build_score_matrix(λ_h, λ_a, ρ) → 11×11 概率矩阵（Dixon-Coles τ 修正）
  5) derive_ah(matrix, ah_line) → (p_home_cover, p_away_cover, p_push)

测试集 56.6%（708 valid，2026-01-10 → 2026-04-27），远超 v4 当前 7d 36.6%。
"""
from __future__ import annotations
import json
import logging
import os
import sqlite3
from typing import Optional

import pandas as pd
from catboost import CatBoostRegressor

# 复用纯函数（无 I/O，无全局状态）
from v5_feature_engineering.inference_lambda import (
    build_score_matrix,
    derive_ah,
    derive_ou,
)

log = logging.getLogger(__name__)

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL_DIR = os.path.join(PROJECT_ROOT, "models_v5_lambda")
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "football_uk.db")


class LambdaAHPredictor:
    """V5 Lambda AH 预测器；签名兼容 v4 ah_model.AHPredictor.predict_match()。"""

    # 当前 Lambda 训练涵盖的 8 个联赛（Track B 扩展后同步更新此集合）
    SUPPORTED_LEAGUES = frozenset({47, 53, 54, 55, 87, 113, 223, 9080})

    # Ensemble 权重（与 evaluate_lambda_v5.py 一致）
    ENSEMBLE_FULL = 0.6
    ENSEMBLE_PURE = 0.4

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.models: dict = {}      # 'H_Full', 'H_Pure', 'A_Full', 'A_Pure'
        self.rho: dict = {}
        self.feat_full: list = []
        self.feat_pure: list = []
        self.loaded = False

    # ─────────────────────────────────────────────────────────────────
    # Loading
    # ─────────────────────────────────────────────────────────────────

    def load(self, model_dir: str = DEFAULT_MODEL_DIR):
        for key, fname in [
            ("H_Full", "Model_H_Full.cbm"),
            ("H_Pure", "Model_H_Pure.cbm"),
            ("A_Full", "Model_A_Full.cbm"),
            ("A_Pure", "Model_A_Pure.cbm"),
        ]:
            path = os.path.join(model_dir, fname)
            m = CatBoostRegressor()
            m.load_model(path)
            self.models[key] = m

        with open(os.path.join(model_dir, "rho.json")) as f:
            self.rho = json.load(f)

        # CatBoost 模型自带训练时的 feature_names_，避免硬编码列表
        self.feat_full = list(self.models["H_Full"].feature_names_)
        self.feat_pure = list(self.models["H_Pure"].feature_names_)
        self.loaded = True
        log.info(
            f"[LambdaAH] loaded: 4 models, ρ_global={self.rho.get('rho_global'):.4f}, "
            f"feat_full={len(self.feat_full)}, feat_pure={len(self.feat_pure)}, "
            f"supported_leagues={sorted(self.SUPPORTED_LEAGUES)}"
        )

    # ─────────────────────────────────────────────────────────────────
    # Inference
    # ─────────────────────────────────────────────────────────────────

    def predict_match_full(
        self,
        match_id: Optional[int] = None,
        league_id: Optional[int] = None,
        ou_line: Optional[float] = None,
        ah_line: Optional[float] = None,
    ) -> Optional[dict]:
        """单次推理同时输出 OU 和 AH，复用同一个 score_matrix（避免重算 4 次 CatBoost）。

        2026-05-04：OU 也接管 Lambda，与 AH 同源一致。

        Returns:
            {
              'ou': {'over_25': float, 'under_25': float, 'push': float,
                     'line': float, 'source': 'v5_lambda'},
              'ah': {'ah_cover': float, 'ah_push': float, 'ah_away_cover': float,
                     'ah_lambda_h': float, 'ah_lambda_a': float, 'ah_rho': float,
                     'ah_source': 'v5_lambda'},
              'lambda': {'lam_h': float, 'lam_a': float, 'rho': float},
            }
          或 None（不支持该联赛 / 特征行未生成 / 推理异常）。
        """
        if not self.loaded:
            return None
        if league_id is None or league_id not in self.SUPPORTED_LEAGUES:
            return None
        if match_id is None or ah_line is None or ou_line is None:
            return None

        # 从 mart 读特征行（split='inference' 或 'test/val/train' 都可，模型只需特征列）
        try:
            conn = sqlite3.connect(self.db_path)
            df = pd.read_sql(
                "SELECT * FROM mart_lambda_dataset_v5 WHERE match_id = ? LIMIT 1",
                conn,
                params=(int(match_id),),
            )
            conn.close()
        except Exception as e:
            log.warning(f"[LambdaAH] DB read failed for match_id={match_id}: {e}")
            return None

        if df.empty:
            log.info(f"[LambdaAH] match_id={match_id} not in mart_lambda_dataset_v5; "
                     f"ETL may not have run yet")
            return None

        # 拼 X（缺列填 0，与训练时 fillna(0) 一致）
        try:
            X_full = df.reindex(columns=self.feat_full, fill_value=0)
            X_pure = df.reindex(columns=self.feat_pure, fill_value=0)
        except Exception as e:
            log.warning(f"[LambdaAH] reindex failed for match_id={match_id}: {e}")
            return None

        # 推 λ
        try:
            lam_h_full = float(self.models["H_Full"].predict(X_full)[0])
            lam_a_full = float(self.models["A_Full"].predict(X_full)[0])
            lam_h_pure = float(self.models["H_Pure"].predict(X_pure)[0])
            lam_a_pure = float(self.models["A_Pure"].predict(X_pure)[0])
        except Exception as e:
            log.warning(f"[LambdaAH] CatBoost predict failed for match_id={match_id}: {e}")
            return None

        lam_h = self.ENSEMBLE_FULL * lam_h_full + self.ENSEMBLE_PURE * lam_h_pure
        lam_a = self.ENSEMBLE_FULL * lam_a_full + self.ENSEMBLE_PURE * lam_a_pure

        # 选 ρ：联赛级优先，缺失则全局
        rho_by_league = self.rho.get("rho_by_league", {})
        rho = rho_by_league.get(str(int(league_id)),
                                self.rho.get("rho_global", 0.0))

        # 推 score matrix → OU + AH 概率（同一次矩阵计算）
        try:
            matrix = build_score_matrix(lam_h, lam_a, rho=rho, max_goals=10)
            p_over, p_under, p_push_ou = derive_ou(matrix, float(ou_line))
            p_home, p_away, p_push_ah = derive_ah(matrix, float(ah_line))
        except Exception as e:
            log.warning(f"[LambdaAH] score_matrix/derive failed for match_id={match_id}: {e}")
            return None

        # 防御：概率 NaN/超界
        for name, v in [("p_over", p_over), ("p_under", p_under),
                        ("p_home", p_home), ("p_away", p_away),
                        ("p_push_ah", p_push_ah)]:
            if v != v or not (0.0 <= v <= 1.001):  # NaN 或越界
                log.warning(f"[LambdaAH] invalid prob {name}={v} for match_id={match_id}")
                return None

        return {
            "ou": {
                "over_25":  float(p_over),
                "under_25": float(p_under),
                "push":     float(p_push_ou),
                "line":     float(ou_line),
                "source":   "v5_lambda",
            },
            "ah": {
                "ah_cover":      float(p_home),
                "ah_push":       float(p_push_ah),
                "ah_away_cover": float(p_away),
                "ah_lambda_h":   round(lam_h, 4),
                "ah_lambda_a":   round(lam_a, 4),
                "ah_rho":        round(rho, 4),
                "ah_source":     "v5_lambda",
            },
            "lambda": {
                "lam_h": lam_h,
                "lam_a": lam_a,
                "rho":   rho,
            },
        }

    def predict_match(
        self,
        home_team: Optional[str] = None,
        away_team: Optional[str] = None,
        features_df=None,            # 旧接口签名兼容；本类不使用
        ah_line: Optional[float] = None,
        *,
        match_id: Optional[int] = None,
        league_id: Optional[int] = None,
        **kwargs,
    ) -> Optional[dict]:
        """向后兼容入口；委托给 predict_match_full 并只返回 AH 字段。

        调用方若需同时获取 OU + AH，请直接调用 predict_match_full()。
        """
        if ah_line is None or match_id is None:
            return None
        ou_line = kwargs.get("ou_line", 2.5)
        result = self.predict_match_full(
            match_id=match_id,
            league_id=league_id,
            ou_line=ou_line,
            ah_line=ah_line,
        )
        return result["ah"] if result else None
