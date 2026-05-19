"""
bivariate_poisson.py
====================
Bivariate Poisson (Karlis & Ntzoufras 2003) 进球模型。

与 Dixon-Coles 的关键差异：
- DC 用 τ(x,y,λ,μ,ρ) 对 (0,0)/(0,1)/(1,0)/(1,1) 打补丁修正独立性偏差，
  在低比分外等同于独立双泊松。
- BP 在全概率空间显式建模主客队进球相关性：
      X = X₁ + X₃,  Y = X₂ + X₃  (X₁,X₂,X₃ 相互独立 Poisson)
      P(X=x, Y=y) = Σ_{k=0..min(x,y)} Pois(x-k;λ₁)·Pois(y-k;λ₂)·Pois(k;λ₃)
  Cov(X,Y) = λ₃ ≥ 0，正相关自然捕捉(0-0 / 1-1 多发 / 大胜少见)。

参数：
  attack_i / defense_i (每队)
  home_adv             (全局主场优势, log 尺度)
  log_lambda3          (全局共同强度, log 尺度)

时间衰减：weight_i = exp(-xi · days_ago_i)。

产出可直接给出 WDL / AH / OU 三市场的联合概率。
"""

import os
import json
import logging
from datetime import datetime
from math import lgamma, log, exp

import numpy as np
from scipy.stats import poisson
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


class BivariatePoissonModel:
    """
    BP 模型。接口模仿 DixonColesModel 以便在 AHPredictor 中互换。
    """

    def __init__(self, xi: float = 0.003, max_goals: int = 10):
        self.xi = xi
        self.max_goals = max_goals
        self.teams = []
        self.attack_params = {}
        self.defense_params = {}
        self.home_adv = 0.20
        self.lambda3  = 0.15         # 全局共同强度（拟合后更新）
        self.is_fitted = False
        self.meta = {}

    # ---------- 核心 pmf ---------------------------------------------------
    @staticmethod
    def _bp_logpmf(x: int, y: int, l1: float, l2: float, l3: float) -> float:
        """log P(X=x, Y=y) for Bivariate Poisson BP(l1,l2,l3).

        使用 log-sum-exp 数值稳定求和。
        """
        if l1 <= 0 or l2 <= 0:
            return -1e10
        k_max = min(x, y)
        # 对 k=0..k_max 求和 log(poispmf(x-k|l1) · poispmf(y-k|l2) · poispmf(k|l3))
        logs = np.empty(k_max + 1)
        for k in range(k_max + 1):
            # Pois(x-k; l1)
            a = (x - k) * log(l1) - l1 - lgamma(x - k + 1)
            b = (y - k) * log(l2) - l2 - lgamma(y - k + 1)
            if l3 > 0:
                c = k * log(l3) - l3 - lgamma(k + 1)
            else:
                # l3 → 0 退化为独立双泊松：只有 k=0 项有效
                c = 0.0 if k == 0 else -1e10
            logs[k] = a + b + c
        # log-sum-exp
        m = logs.max()
        return float(m + log(np.exp(logs - m).sum()))

    @staticmethod
    def score_matrix(l1: float, l2: float, l3: float,
                     max_goals: int = 10) -> np.ndarray:
        """返回 max_goals × max_goals 的 P(X=i, Y=j) 矩阵。"""
        if l3 <= 1e-9:
            # 退化：独立双泊松
            h = poisson.pmf(np.arange(max_goals), l1)
            a = poisson.pmf(np.arange(max_goals), l2)
            return np.outer(h, a)

        # 预计算 Pois(k; l3)  k=0..max_goals-1
        p3 = poisson.pmf(np.arange(max_goals), l3)
        p1 = poisson.pmf(np.arange(max_goals), l1)
        p2 = poisson.pmf(np.arange(max_goals), l2)

        M = np.zeros((max_goals, max_goals))
        for i in range(max_goals):
            for j in range(max_goals):
                s = 0.0
                for k in range(min(i, j) + 1):
                    if (i - k) < max_goals and (j - k) < max_goals:
                        s += p1[i - k] * p2[j - k] * p3[k]
                M[i, j] = s
        # 归一化（截断导致总和略 <1）
        total = M.sum()
        if total > 0:
            M /= total
        return M

    # ---------- 拟合 -------------------------------------------------------
    def _neg_log_likelihood(self, params, h_idx, a_idx, h_goals, a_goals, weights):
        n = len(self.teams)
        att = params[:n]
        dfn = params[n:2 * n]
        home_adv  = params[2 * n]
        log_l3    = params[2 * n + 1]

        l1 = np.exp(att[h_idx] + dfn[a_idx] + home_adv)
        l2 = np.exp(att[a_idx] + dfn[h_idx])
        l3 = np.exp(log_l3)

        total = 0.0
        # 逐场算 BP logpmf —— 典型 match 5-10 goals，内层 sum ≤ 11 项，很快
        for i in range(len(h_goals)):
            lp = self._bp_logpmf(int(h_goals[i]), int(a_goals[i]),
                                 float(l1[i]), float(l2[i]), l3)
            total += weights[i] * lp
        return -total

    def fit(self, matches_df):
        """matches_df: home_team, away_team, home_goals, away_goals, days_ago"""
        logger.info(f"Fitting Bivariate Poisson  xi={self.xi}  n={len(matches_df)}")
        self.teams = sorted(set(matches_df['home_team']) | set(matches_df['away_team']))
        n = len(self.teams)
        t2i = {t: i for i, t in enumerate(self.teams)}

        h_idx  = matches_df['home_team'].map(t2i).values
        a_idx  = matches_df['away_team'].map(t2i).values
        h_gls  = matches_df['home_goals'].values.astype(int)
        a_gls  = matches_df['away_goals'].values.astype(int)
        wts    = np.exp(-self.xi * matches_df['days_ago'].values)

        init   = np.zeros(2 * n + 2)
        init[2 * n]     = 0.25        # home_adv
        init[2 * n + 1] = np.log(0.15)  # log_lambda3

        # 约束：Σ attack = 0（避免参数平移不可辨识）
        constraints = [{'type': 'eq', 'fun': lambda x: x[:n].sum()}]
        # log_lambda3 限制在 log(0.01)..log(1.5)
        bounds = [(None, None)] * (2 * n + 1) + [(np.log(1e-3), np.log(1.5))]

        res = minimize(
            self._neg_log_likelihood, init,
            args=(h_idx, a_idx, h_gls, a_gls, wts),
            method='SLSQP',
            constraints=constraints,
            bounds=bounds,
            options={'disp': False, 'maxiter': 300, 'ftol': 1e-8},
        )
        if not res.success:
            logger.warning(f"BP fit warning: {res.message}")
        p = res.x
        self.attack_params  = {t: float(p[i])     for i, t in enumerate(self.teams)}
        self.defense_params = {t: float(p[n + i]) for i, t in enumerate(self.teams)}
        self.home_adv = float(p[2 * n])
        self.lambda3  = float(np.exp(p[2 * n + 1]))
        self.is_fitted = True
        logger.info(
            f"BP fitted: teams={n}  home_adv={self.home_adv:+.4f}  "
            f"λ₃={self.lambda3:.4f}  final_nll={res.fun:.2f}"
        )

    # ---------- 推理 -------------------------------------------------------
    def get_lambdas(self, home: str, away: str):
        """→ (λ₁, λ₂, λ₃) 或 (None, None, None)"""
        if not self.is_fitted:
            return None, None, None
        if home not in self.attack_params or away not in self.attack_params:
            return None, None, None
        l1 = float(np.exp(self.attack_params[home] + self.defense_params[away] + self.home_adv))
        l2 = float(np.exp(self.attack_params[away] + self.defense_params[home]))
        return l1, l2, self.lambda3

    # ---------- 三市场联合推导 --------------------------------------------
    @classmethod
    def markets_from_matrix(cls, M: np.ndarray, ah_line: float = 0.0,
                            ou_line: float = 2.5) -> dict:
        """
        从 score matrix 直接导出 WDL / AH / OU 三市场概率。
        OU 线支持 .0 / .25 / .5 / .75（quarter-line 做半边平均）。
        AH 线同样支持 quarter。
        """
        mx = M.shape[0]

        # WDL
        p_home = p_draw = p_away = 0.0
        for i in range(mx):
            for j in range(mx):
                pij = M[i, j]
                if i > j:
                    p_home += pij
                elif i == j:
                    p_draw += pij
                else:
                    p_away += pij

        # OU
        def _ou_at(L: float):
            over = under = push = 0.0
            for i in range(mx):
                for j in range(mx):
                    tot = i + j
                    if tot > L + 1e-9:
                        over += M[i, j]
                    elif tot < L - 1e-9:
                        under += M[i, j]
                    else:
                        push += M[i, j]
            return over, under, push

        def _ou_quarter(L: float):
            # quarter line: half-win/half-push
            if abs(L * 4 % 1) < 1e-4 and abs(L * 2 % 1) > 1e-4:
                La = np.floor(L * 2) / 2
                Lb = np.ceil(L * 2) / 2
                oa, ua, pa = _ou_at(La)
                ob, ub, pb = _ou_at(Lb)
                return (oa + ob) / 2, (ua + ub) / 2, (pa + pb) / 2
            return _ou_at(L)

        ou_over, ou_under, ou_push = _ou_quarter(ou_line)

        # AH
        def _ah_at(L: float):
            cov = push = 0.0
            for i in range(mx):
                for j in range(mx):
                    margin = i - j + L
                    if margin > 1e-9:
                        cov += M[i, j]
                    elif abs(margin) < 1e-9:
                        push += M[i, j]
            return cov, push

        def _ah_quarter(L: float):
            if abs(L * 4 % 1) < 1e-4 and abs(L * 2 % 1) > 1e-4:
                La = np.floor(L * 2) / 2
                Lb = np.ceil(L * 2) / 2
                ca, pa = _ah_at(La)
                cb, pb = _ah_at(Lb)
                return (ca + cb) / 2, (pa + pb) / 2
            return _ah_at(L)

        ah_cover, ah_push = _ah_quarter(ah_line)
        ah_away = max(0.0, 1.0 - ah_cover - ah_push)

        return {
            "wdl": {"home": float(p_home), "draw": float(p_draw), "away": float(p_away)},
            "ou":  {"over": float(ou_over), "under": float(ou_under),
                    "push": float(ou_push), "line": float(ou_line)},
            "ah":  {"cover": float(ah_cover), "push": float(ah_push),
                    "away_cover": float(ah_away), "line": float(ah_line)},
        }

    # ---------- 序列化 -----------------------------------------------------
    def to_json(self) -> dict:
        return {
            "model":            "bivariate_poisson",
            "xi":               self.xi,
            "max_goals":        self.max_goals,
            "teams":            self.teams,
            "attack":           self.attack_params,
            "defense":          self.defense_params,
            "home_adv":         self.home_adv,
            "lambda3":          self.lambda3,
            "meta":             self.meta,
            "saved_at":         datetime.utcnow().isoformat(),
        }

    def save(self, model_dir: str, filename: str = "bp_params.json"):
        os.makedirs(model_dir, exist_ok=True)
        path = os.path.join(model_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, indent=2, ensure_ascii=False,
                      default=lambda o: int(o) if isinstance(o, (np.integer,))
                              else (float(o) if isinstance(o, (np.floating,)) else str(o)))
        logger.info(f"BP 保存: {path}")
        return path

    def load(self, model_dir: str, filename: str = "bp_params.json"):
        path = os.path.join(model_dir, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        self.xi             = d.get("xi", self.xi)
        self.max_goals      = d.get("max_goals", self.max_goals)
        self.teams          = d["teams"]
        self.attack_params  = d["attack"]
        self.defense_params = d["defense"]
        self.home_adv       = d["home_adv"]
        self.lambda3        = d["lambda3"]
        self.meta           = d.get("meta", {})
        self.is_fitted      = True
        logger.info(f"BP 加载: {path}  teams={len(self.teams)}  λ₃={self.lambda3:.4f}")
        return self
