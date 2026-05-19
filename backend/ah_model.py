"""
ah_model.py
===========
Asian Handicap (AH) Prediction Model
Architecture:
- Layer 1: DixonColesModel (Poisson + Low Score Correction + Time Decay)
- Layer 2: XGBoostLambda (LightGBM Regression for xG Prediction)
- Layer 3: AHPredictor (Blending + AH Probability Integration)

Author: Antigravity AI
"""

import os
import json
import pickle
import sqlite3
import logging
import math
from datetime import datetime

import numpy as np
import pandas as pd
import lightgbm as lgb
from scipy.stats import poisson
from scipy.optimize import minimize

logger = logging.getLogger(__name__)

# =============================================================================
# Layer 1: DixonColesModel
# =============================================================================

class DixonColesModel:
    """
    Dixon-Coles 1997: 双泊松 + 低比分修正 + 时间衰减。
    参数: attack_i, defense_i (每队), home_adv (全局), rho (低比分修正)
    """
    def __init__(self, xi=0.003):
        self.xi = xi  # 时间衰减参数
        self.teams = []
        self.params = {}
        self.is_fitted = False

    def _tau_vectorized(self, x, y, lambda_h, mu_a, rho):
        """向量化版本的 tau 修正函数"""
        tau = np.ones_like(x, dtype=float)
        
        # 0-0: 1 - lambda * mu * rho
        mask00 = (x == 0) & (y == 0)
        tau[mask00] = 1 - lambda_h[mask00] * mu_a[mask00] * rho
        
        # 0-1: 1 + lambda * rho
        mask01 = (x == 0) & (y == 1)
        tau[mask01] = 1 + lambda_h[mask01] * rho
        
        # 1-0: 1 + mu * rho
        mask10 = (x == 1) & (y == 0)
        tau[mask10] = 1 + mu_a[mask10] * rho
        
        # 1-1: 1 - rho
        mask11 = (x == 1) & (y == 1)
        tau[mask11] = 1 - rho
        
        return tau

    def _log_likelihood(self, params, h_idx, a_idx, h_goals, a_goals, weights):
        """
        向量化加权对数似然函数
        """
        n_teams = len(self.teams)
        att = params[:n_teams]
        dfn = params[n_teams:2*n_teams]
        home_adv = params[2*n_teams]
        rho = params[2*n_teams + 1]

        # Compute lambdas and mus for all matches
        l_h = np.exp(att[h_idx] + dfn[a_idx] + home_adv)
        m_a = np.exp(att[a_idx] + dfn[h_idx])
        
        # Dixon-Coles correction
        t = self._tau_vectorized(h_goals, a_goals, l_h, m_a, rho)
        
        # Avoid log of non-positive
        if np.any(t <= 1e-10):
            return 1e10
            
        # Log-likelihood terms
        log_poisson_h = poisson.logpmf(h_goals, l_h)
        log_poisson_a = poisson.logpmf(a_goals, m_a)
        
        ll = np.sum(weights * (np.log(t) + log_poisson_h + log_poisson_a))
            
        return -ll

    def fit(self, matches_df):
        """
        fit(matches_df) — 输入 DataFrame 需要列：home_team, away_team, home_goals, away_goals, days_ago
        """
        logger.info("Fitting Dixon-Coles model (Vectorized)...")
        self.teams = sorted(list(set(matches_df['home_team']) | set(matches_df['away_team'])))
        n_teams = len(self.teams)
        team_to_idx = {team: i for i, team in enumerate(self.teams)}
        
        # Convert data to numpy arrays for vectorization
        h_idx = matches_df['home_team'].map(team_to_idx).values
        a_idx = matches_df['away_team'].map(team_to_idx).values
        h_goals = matches_df['home_goals'].values
        a_goals = matches_df['away_goals'].values
        weights = np.exp(-self.xi * matches_df['days_ago'].values)
            
        # Initial parameters: att=0, def=0, home_adv=0.2, rho=0
        init_params = np.zeros(2 * n_teams + 2)
        init_params[2 * n_teams] = 0.2 # home_adv
        init_params[2 * n_teams + 1] = 0.0 # rho
        
        # Identifier constraint: sum(attack) = 0
        constraints = [{'type': 'eq', 'fun': lambda x: np.sum(x[:n_teams])}]
        
        # Rho bounds to keep probabilities clean
        bounds = [(None, None)] * (2 * n_teams + 1) + [(-1.0, 1.0)]
        
        res = minimize(
            self._log_likelihood,
            init_params,
            args=(h_idx, a_idx, h_goals, a_goals, weights),
            method='SLSQP',
            constraints=constraints,
            bounds=bounds,
            options={'disp': False, 'maxiter': 500, 'ftol': 1e-9}
        )
        
        if not res.success:
            logger.warning(f"Dixon-Coles optimization warning: {res.message}")
            
        # Store results
        optimized_params = res.x
        self.attack_params = {team: optimized_params[i] for i, team in enumerate(self.teams)}
        self.defense_params = {team: optimized_params[i + n_teams] for i, team in enumerate(self.teams)}
        self.params = {
            'attack': self.attack_params,
            'defense': self.defense_params,
            'home_adv': optimized_params[2 * n_teams],
            'rho': optimized_params[2 * n_teams + 1]
        }
        self.is_fitted = True
        logger.info(f"Dixon-Coles fitted. Teams: {n_teams}, home_adv: {self.params['home_adv']:.4f}, rho: {self.params['rho']:.4f}")

    def get_lambda(self, home_team, away_team):
        """get_lambda(home_team, away_team) -> (lambda_home, mu_away)"""
        if not self.is_fitted:
            return 1.0, 1.0 # Default if not fitted
            
        if home_team not in self.attack_params or away_team not in self.attack_params:
            return None, None
            
        l_h = np.exp(self.attack_params[home_team] + self.defense_params[away_team] + self.params['home_adv'])
        m_a = np.exp(self.attack_params[away_team] + self.defense_params[home_team])
        return float(l_h), float(m_a)

    def get_params(self):
        """get_params() -> dict"""
        return self.params

    def _tau(self, x, y, lambda_h, mu_a, rho):
        """ Scalar version of tau for single match prediction if needed """
        if x == 0 and y == 0:
            return 1 - lambda_h * mu_a * rho
        elif x == 0 and y == 1:
            return 1 + lambda_h * rho
        elif x == 1 and y == 0:
            return 1 + mu_a * rho
        elif x == 1 and y == 1:
            return 1 - rho
        else:
            return 1.0

# =============================================================================
# Layer 2: XGBoostLambda
# =============================================================================

LAMBDA_FEATURES = [
    'home_roll_opp_adj_npxgd', 'away_roll_opp_adj_npxgd',
    'home_roll_shot_pace', 'away_roll_shot_pace',
    'home_roll_5_npxGD', 'away_roll_5_npxGD',
    'home_roll_5_xGD', 'away_roll_5_xGD',
    'home_roll_5_ppda', 'away_roll_5_ppda',
    'home_roll_5_field_tilt', 'away_roll_5_field_tilt',
    'home_roll_5_box_shot_ratio', 'away_roll_5_box_shot_ratio',
    'home_roll_5_big_chances_created', 'away_roll_5_big_chances_created',
    'home_roll_5_shot_quality_added', 'away_roll_5_shot_quality_added',
    'home_pre_match_elo', 'away_pre_match_elo',
    'elo_diff',
    'home_rest_days', 'away_rest_days',
    'is_cup',
]

class XGBoostLambda:
    """用 LightGBM 回归预测主客队进球期望（训练目标=xG，非实际进球）"""
    def __init__(self):
        self.model_home = None
        self.model_away = None
        self.lgb_params = {
            'objective': 'regression',
            'metric': 'rmse',
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'verbose': -1,
            'seed': 42
        }

    def fit(self, X, y_home_xg, y_away_xg, n_rounds=300, early_stopping_rounds=30):
        """fit(X, y_home_xg, y_away_xg) — 80/20 时间序列 split"""
        logger.info(f"Fitting XGBoostLambda (LightGBM) models. X shape: {X.shape}")
        
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
        y_h_train, y_h_val = y_home_xg[:split_idx], y_home_xg[split_idx:]
        y_a_train, y_a_val = y_away_xg[:split_idx], y_away_xg[split_idx:]
        
        # Model Home
        logger.info("Training model_home...")
        d_train_h = lgb.Dataset(X_train, label=y_h_train)
        d_val_h = lgb.Dataset(X_val, label=y_h_val, reference=d_train_h)
        self.model_home = lgb.train(
            self.lgb_params, d_train_h,
            num_boost_round=n_rounds,
            valid_sets=[d_val_h],
            callbacks=[lgb.early_stopping(early_stopping_rounds), lgb.log_evaluation(50)]
        )
        
        # Model Away
        logger.info("Training model_away...")
        d_train_a = lgb.Dataset(X_train, label=y_a_train)
        d_val_a = lgb.Dataset(X_val, label=y_a_val, reference=d_train_a)
        self.model_away = lgb.train(
            self.lgb_params, d_train_a,
            num_boost_round=n_rounds,
            valid_sets=[d_val_a],
            callbacks=[lgb.early_stopping(early_stopping_rounds), lgb.log_evaluation(50)]
        )

    def predict(self, X):
        """predict(X) → (lambda_hat_home, lambda_hat_away) numpy arrays"""
        if self.model_home is None or self.model_away is None:
            raise ValueError("Models not fitted.")
        
        pred_h = self.model_home.predict(X)
        pred_a = self.model_away.predict(X)
        return pred_h, pred_a

# =============================================================================
# Layer 3: AHPredictor
# =============================================================================

class AHPredictor:
    """顶层 AH 预测器：混合 DC + xG 模型，输出任意 AH 线的覆盖概率"""
    def __init__(self, blend_alpha=0.4):
        self.dc_model = DixonColesModel()
        self.xg_model = XGBoostLambda()
        self.blend_alpha = blend_alpha  # alpha for DC, (1-alpha) for xG
        # Lambda 校准系数（训练后由 run_ah_training.py 计算并存储）
        self.lambda_scale_home = 1.0   # predicted_mean → actual_goals_mean
        self.lambda_scale_away = 1.0
        self.meta = {}

    def score_matrix(self, lambda_h, mu_a, rho=0, max_goals=9):
        """
        score_matrix(lambda_h, mu_a, rho=0, max_goals=9) → 9×9 numpy array
        max_goals=9 means we consider goals 0 to 8.
        """
        matrix = np.zeros((max_goals, max_goals))
        
        # Core poisson probabilities
        h_probs = poisson.pmf(np.arange(max_goals), lambda_h)
        a_probs = poisson.pmf(np.arange(max_goals), mu_a)
        
        for i in range(max_goals):
            for j in range(max_goals):
                prob = h_probs[i] * a_probs[j]
                
                # Dixon-Coles tau correction
                if i <= 1 and j <= 1:
                    t = self.dc_model._tau(i, j, lambda_h, mu_a, rho)
                    prob *= t
                    
                matrix[i, j] = prob
                
        # Normalize to ensure it's a probability distribution
        total = matrix.sum()
        if total > 0:
            matrix /= total
        return matrix

    def ah_cover_prob(self, lambda_h, mu_a, rho, line):
        """ah_cover_prob(lambda_h, mu_a, rho, line) → (p_cover, p_push)"""
        # Quarter-line handling
        if abs(line * 4 % 1) < 1e-4 and abs(line * 2 % 1) > 1e-4:
            # line is .25 or .75
            line_a = math.floor(line * 2) / 2
            line_b = math.ceil(line * 2) / 2
            
            c_a, p_a = self._calc_raw_ah(lambda_h, mu_a, rho, line_a)
            c_b, p_b = self._calc_raw_ah(lambda_h, mu_a, rho, line_b)
            
            return (c_a + c_b) / 2, (p_a + p_b) / 2
        else:
            return self._calc_raw_ah(lambda_h, mu_a, rho, line)

    def _calc_raw_ah(self, lambda_h, mu_a, rho, line):
        """Helper to calculate AH cover/push for a standard line (0 or 0.5)"""
        matrix = self.score_matrix(lambda_h, mu_a, rho)
        p_cover = 0.0
        p_push = 0.0
        
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]):
                margin = i - j + line
                if margin > 1e-9:
                    p_cover += matrix[i, j]
                elif abs(margin) < 1e-9:
                    p_push += matrix[i, j]
                    
        return p_cover, p_push

    def predict_match(self, home_team, away_team, features_df, ah_line):
        """predict_match(home_team, away_team, features_df, ah_line) → dict"""
        # Ensure features_df only contains LAMBDA_FEATURES in correct order
        X = features_df[LAMBDA_FEATURES]
        
        # 1. DC Prediction
        l_dc, m_dc = self.dc_model.get_lambda(home_team, away_team)
        rho = self.dc_model.get_params().get('rho', 0)
        
        # 2. xG Prediction
        l_xg_arr, m_xg_arr = self.xg_model.predict(X)
        l_xg, m_xg = float(l_xg_arr[0]), float(m_xg_arr[0])
        
        # 3. Blending
        if l_dc is None:
            # Team not found in DC model
            l_final = l_xg
            m_final = m_xg
            alpha_used = 0.0
        else:
            l_final = self.blend_alpha * l_dc + (1 - self.blend_alpha) * l_xg
            m_final = self.blend_alpha * m_dc + (1 - self.blend_alpha) * m_xg
            alpha_used = self.blend_alpha

        # 3b. 校准修正：消除 λ 系统性低估偏差
        l_final *= self.lambda_scale_home
        m_final *= self.lambda_scale_away

        # 4. Probabilities
        p_cover, p_push = self.ah_cover_prob(l_final, m_final, rho, ah_line)
        p_away_cover = 1.0 - p_cover - p_push
        
        # 5. Score Matrix for report
        s_matrix = self.score_matrix(l_final, m_final, rho)
        
        return {
            "ah_cover": float(p_cover),
            "ah_push": float(p_push),
            "ah_away_cover": float(p_away_cover),
            "lambda_home": float(l_final),
            "lambda_away": float(m_final),
            "score_matrix": s_matrix.tolist(),
            "alpha_used": alpha_used,
            "rho": float(rho)
        }

    def save(self, model_dir):
        """save(model_dir) — 序列化到 models_v4/"""
        os.makedirs(model_dir, exist_ok=True)
        
        # 1. DC Params
        with open(os.path.join(model_dir, 'ah_dc_params.json'), 'w') as f:
            json.dump(self.dc_model.get_params(), f, indent=2)
            
        # 2. XGBoost Models
        if self.xg_model.model_home:
            self.xg_model.model_home.save_model(os.path.join(model_dir, 'ah_xg_home.lgb'))
        if self.xg_model.model_away:
            self.xg_model.model_away.save_model(os.path.join(model_dir, 'ah_xg_away.lgb'))
            
        # 3. Meta
        meta_path = os.path.join(model_dir, 'ah_meta.json')
        self.meta['blend_alpha'] = self.blend_alpha
        self.meta['lambda_scale_home'] = self.lambda_scale_home
        self.meta['lambda_scale_away'] = self.lambda_scale_away
        self.meta['trained_at'] = datetime.now().isoformat()
        with open(meta_path, 'w') as f:
            json.dump(self.meta, f, indent=2)
            
        logger.info(f"AHPredictor saved to {model_dir}")

    def load(self, model_dir):
        """load(model_dir)"""
        # 1. DC Params
        dc_path = os.path.join(model_dir, 'ah_dc_params.json')
        if os.path.exists(dc_path):
            with open(dc_path, 'r') as f:
                params = json.load(f)
                self.dc_model.params = params
                self.dc_model.teams = sorted(list(params['attack'].keys()))
                self.dc_model.attack_params = params['attack']
                self.dc_model.defense_params = params['defense']
                self.dc_model.is_fitted = True
                
        # 2. XGBoost Models
        mh_path = os.path.join(model_dir, 'ah_xg_home.lgb')
        ma_path = os.path.join(model_dir, 'ah_xg_away.lgb')
        if os.path.exists(mh_path):
            self.xg_model.model_home = lgb.Booster(model_file=mh_path)
        if os.path.exists(ma_path):
            self.xg_model.model_away = lgb.Booster(model_file=ma_path)
            
        # 3. Meta
        meta_path = os.path.join(model_dir, 'ah_meta.json')
        if os.path.exists(meta_path):
            with open(meta_path, 'r') as f:
                self.meta = json.load(f)
                self.blend_alpha        = self.meta.get('blend_alpha', self.blend_alpha)
                self.lambda_scale_home  = self.meta.get('lambda_scale_home', 1.0)
                self.lambda_scale_away  = self.meta.get('lambda_scale_away', 1.0)
                
        logger.info(f"AHPredictor loaded from {model_dir}")

# =============================================================================
# Data Loading Utility
# =============================================================================

def prepare_ah_data(db_path):
    """
    从 SQLite 加载并组装 AH 训练数据。
    修复清单：
    - AH 盘口通过 stg_match_odds（已做 team_mapping 对齐）避免队名不匹配
    - int_match_features_extended 用 AVG 去重（存在 122 个 (match_id,team_id) 重复）
    - int_team_rolling_extended 过滤 window_size=5
    - int_team_rolling_features 只取 LAMBDA_FEATURES 所需列
    """
    conn = sqlite3.connect(db_path)

    # 1. 比分 + xG
    logger.info("Loading match scores and xG data...")
    matches = pd.read_sql("""
        SELECT m.Match_ID, m.Date, m.Home_Team_Name as home_team,
               m.Away_Team_Name as away_team,
               m.home_score, m.away_score,
               fh.expected_goals_non_penalty as home_xg,
               fa.expected_goals_non_penalty as away_xg
        FROM dim_match m
        JOIN fact_team_match_stats fh ON m.Match_ID=fh.Match_ID
            AND m.Home_Team_ID=fh.Team_ID AND fh.Period='All'
        JOIN fact_team_match_stats fa ON m.Match_ID=fa.Match_ID
            AND m.Away_Team_ID=fa.Team_ID AND fa.Period='All'
        WHERE m.status='Finish' AND m.home_score IS NOT NULL
        ORDER BY m.Date
    """, conn)
    logger.info(f"  比分+xG: {len(matches)} 场")

    # 2. AH 盘口 — 通过 stg_match_odds（已做 team_mapping，名称已标准化）
    logger.info("Loading AH odds via stg_match_odds...")
    ah = pd.read_sql("""
        SELECT match_date AS Date,
               standard_home_team_name AS home_team,
               standard_away_team_name AS away_team,
               odds_ah_line    AS ah_line,
               odds_ah_home    AS ah_home_odds,
               odds_ah_away    AS ah_away_odds
        FROM stg_match_odds
        WHERE odds_ah_line IS NOT NULL
    """, conn)
    # stg_match_odds 是视图，底层可能存在重复行（同一场多条记录）。
    # 去重后每场只保留第一条，防止 merge 产生笛卡尔积导致训练集膨胀。
    before_dedup = len(ah)
    ah = ah.drop_duplicates(subset=['Date', 'home_team', 'away_team'], keep='first')
    if before_dedup != len(ah):
        logger.warning(f"  stg_match_odds 去重: {before_dedup} → {len(ah)} 行 (删除 {before_dedup-len(ah)} 重复)")
    matches = matches.merge(ah, on=['home_team', 'away_team', 'Date'], how='left')
    logger.info(f"  AH覆盖: {matches['ah_line'].notna().sum()}/{len(matches)} 场")

    # 3. 滚动特征
    logger.info("Loading rolling features...")

    # Elo + rest_days（存在 122 个重复行，用 AVG 去重）
    ext_df = pd.read_sql("""
        SELECT match_id, team_id,
               AVG(pre_match_elo) AS pre_match_elo,
               AVG(rest_days)     AS rest_days
        FROM int_match_features_extended
        GROUP BY match_id, team_id
    """, conn)

    # Rolling basic (window_size=5 过滤)
    roll_df = pd.read_sql("""
        SELECT match_id, team_id, roll_shot_pace, roll_opp_adj_npxgd
        FROM int_team_rolling_extended
        WHERE window_size = 5
    """, conn)

    # dbt Rolling（只取 LAMBDA_FEATURES 所需列）
    dbt_roll_df = pd.read_sql("""
        SELECT match_id, team_id,
               roll_5_npxGD, roll_5_xGD, roll_5_ppda,
               roll_5_field_tilt, roll_5_box_shot_ratio, roll_5_poss_diff,
               roll_5_big_chances_created, roll_5_shot_quality_added
        FROM int_team_rolling_features
    """, conn)

    # Team IDs + League
    team_ids = pd.read_sql("""
        SELECT Match_ID AS match_id,
               Home_Team_ID AS home_id, Away_Team_ID AS away_id,
               League_ID AS league_id
        FROM dim_match
    """, conn)

    for df_ in [ext_df, roll_df, dbt_roll_df, team_ids]:
        df_['match_id'] = df_['match_id'].astype(str)
    matches['Match_ID'] = matches['Match_ID'].astype(str)

    matches = matches.merge(team_ids, left_on='Match_ID', right_on='match_id', how='left').drop('match_id', axis=1)

    for prefix, id_col in [('home', 'home_id'), ('away', 'away_id')]:
        for feat_df in [ext_df, roll_df, dbt_roll_df]:
            feat_cols = [c for c in feat_df.columns if c not in ('match_id', 'team_id')]
            renamed = feat_df.rename(columns={c: f"{prefix}_{c}" for c in feat_cols})
            matches = matches.merge(
                renamed,
                left_on=['Match_ID', id_col],
                right_on=['match_id', 'team_id'],
                how='left'
            ).drop(['match_id', 'team_id'], axis=1)

    # 4. 衍生特征
    matches['elo_diff'] = matches['home_pre_match_elo'] - matches['away_pre_match_elo']
    CUP_LIDS = {42, 73, 10216, 132, 133, 134, 138, 141, 209}
    matches['is_cup'] = matches['league_id'].apply(lambda x: 1 if x in CUP_LIDS else 0)

    # 5. days_ago（相对最近一场）
    max_date = pd.to_datetime(matches['Date']).max()
    matches['days_ago'] = (max_date - pd.to_datetime(matches['Date'])).dt.days

    matches = matches.fillna(0)
    conn.close()

    logger.info(f"prepare_ah_data 完成: {len(matches)} 行, LAMBDA_FEATURES 全覆盖={all(c in matches.columns for c in LAMBDA_FEATURES)}")
    return matches
