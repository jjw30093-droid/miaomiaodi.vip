#!/usr/bin/env python3
"""
train_league_v5.py — Phase 2: BIG5 联赛级独立模型训练

对每个 BIG5 联赛单独训练 4 个 CatBoost 模型（H_Full/A_Full/H_Pure/A_Pure），
然后在 Val 集上 grid-search 最优混合权重 ξ（Full:Pure）。

特殊规则：
  Serie A (55) — ξ 搜索范围限制在 [0.0, 0.3]（Pure 为主），确认用 Pure 主力

输出：
  models_v5_lambda/{league_id}/Model_H_Full.cbm
  models_v5_lambda/{league_id}/Model_A_Full.cbm
  models_v5_lambda/{league_id}/Model_H_Pure.cbm
  models_v5_lambda/{league_id}/Model_A_Pure.cbm
  models_v5_lambda/{league_id}/rho.json         (包含 best_xi + rho)
  models_v5_lambda/{league_id}/eval_report.csv  (val + test 指标)

CLAUDE.md §3：唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
import time
import warnings
import sqlite3

import numpy as np
import pandas as pd
from scipy import stats as ss
from scipy.optimize import minimize_scalar
from catboost import CatBoostRegressor, Pool

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inference_lambda import build_score_matrix, derive_wdl, derive_ou, derive_ah

# ─── 路径 ───────────────────────────────────────────────────────────
DB_PATH   = '/home/ubuntu/app/backend/football_uk.db'
MODEL_BASE = '/home/ubuntu/app/backend/models_v5_lambda'

# BIG5 联赛（Phase 2 只训 BIG5）
BIG5_LEAGUES = {
    47:  'EPL',
    87:  'LaLiga',
    54:  'Bundesliga',
    55:  'SerieA',
    53:  'Ligue1',
}
# 联赛 ID → 名称（FotMob 实际数据验证：87=LaLiga/Villarreal, 55=SerieA/Udinese, 54=Bundesliga/Wolfsburg）
LEAGUE_NAMES = {
    47: 'EPL', 87: 'LaLiga', 54: 'Bundesliga',
    55: 'SerieA', 53: 'Ligue1',
    113: 'A-League', 223: 'J-League', 9080: 'K-League',
}
TARGET_LEAGUES = [47, 87, 54, 55, 53]  # BIG5

# ─── CatBoost 参数（联赛级 —— 数据量少，加强正则）────────────────────
CB_PARAMS_LEAGUE = dict(
    iterations=1500,
    depth=5,
    learning_rate=0.04,
    l2_leaf_reg=8,
    loss_function='Poisson',
    eval_metric='Poisson',
    early_stopping_rounds=120,
    random_seed=42,
    verbose=0,       # 安静模式（联赛级训练多，减少输出）
    thread_count=-1,
)

# ─── 赔率类特征（Pure 模型排除）──────────────────────────────────────
ODDS_PATTERN_KEYWORDS = [
    'raw_home', 'raw_away', 'raw_draw',
    'fair_home', 'fair_draw', 'fair_away',
    'implied',
    'ah_implied_diff',
    'ah_raw_home', 'ah_raw_away',
    'ah_odds_movement',
    'closing_eu_raw', 'closing_ah_raw',
    'closing_ou_raw',
    'closing_eu_fair', 'closing_ah_fair',
    'closing_ou_fair',
    'open_eu_fair', 'open_ah_fair',
    'open_ou_fair',
    'eu_odds', 'eu_implied',
]
META_COLS = [
    'match_id', 'match_date', 'Season',
    'Home_Team_ID', 'Away_Team_ID',
    'Home_Team_Name', 'Away_Team_Name',
    'days_from_latest', 'sample_weight', 'split',
    'ah_source', 'ah_line_category',
]
TARGET_COLS = ['target_home_score', 'target_away_score']


# ─────────────────────────────────────────────────────────────────────
# 数据加载 + 特征准备
# ─────────────────────────────────────────────────────────────────────

def load_and_prepare():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query('SELECT * FROM mart_lambda_dataset_v5', conn)
    conn.close()

    # Drop NULL>40% cols（全量决定，保持列集一致）
    null_rates = df.isnull().mean()
    drop_cols = null_rates[null_rates > 0.40].index.tolist()
    if drop_cols:
        df = df.drop(columns=drop_cols, errors='ignore')

    non_feat = set(META_COLS + TARGET_COLS)
    candidate_cols = [c for c in df.columns if c not in non_feat]

    feat_full = candidate_cols.copy()
    feat_pure = [c for c in candidate_cols
                 if not any(kw.lower() in c.lower() for kw in ODDS_PATTERN_KEYWORDS)]
    cat_features = ['League_ID'] if 'League_ID' in feat_full else []

    # NULL 填充 -999 / __NA__（全量统一处理）
    for c in feat_full:
        if df[c].dtype.kind in 'iuf':
            df[c] = df[c].fillna(-999)
        elif df[c].dtype == object:
            df[c] = df[c].fillna('__NA__')

    return df, feat_full, feat_pure, cat_features


# ─────────────────────────────────────────────────────────────────────
# 训练单个模型
# ─────────────────────────────────────────────────────────────────────

def train_one(name, X_tr, y_tr, w_tr, X_val, y_val, cat_features, out_dir):
    model = CatBoostRegressor(**CB_PARAMS_LEAGUE)
    model.fit(
        Pool(X_tr, y_tr, weight=w_tr, cat_features=cat_features),
        eval_set=Pool(X_val, y_val, cat_features=cat_features),
        use_best_model=True,
    )
    bi  = model.get_best_iteration()
    vl  = model.get_best_score()['validation']['Poisson']
    path = os.path.join(out_dir, f'{name}.cbm')
    model.save_model(path)
    print(f'     {name}: BestIter={bi}  ValLoss={vl:.4f}  → {path}')
    return model


# ─────────────────────────────────────────────────────────────────────
# Dixon-Coles ρ 估计
# ─────────────────────────────────────────────────────────────────────

def dc_tau_vec(h, a, lh, la, rho):
    tau = np.ones(len(lh))
    tau[(h == 0) & (a == 0)] = 1 - lh[(h == 0) & (a == 0)] * la[(h == 0) & (a == 0)] * rho
    tau[(h == 0) & (a == 1)] = 1 + lh[(h == 0) & (a == 1)] * rho
    tau[(h == 1) & (a == 0)] = 1 + la[(h == 1) & (a == 0)] * rho
    tau[(h == 1) & (a == 1)] = 1 - rho
    return np.clip(tau, 1e-10, None)


def dc_neg_loglik(rho, lh, la, h, a, w):
    tau = dc_tau_vec(h, a, lh, la, rho)
    log_p = (ss.poisson.logpmf(h, lh) + ss.poisson.logpmf(a, la) + np.log(tau))
    return -float(np.sum(w * log_p))


def estimate_rho(lh, la, h, a, w, bounds=(-0.25, 0.10)):
    res = minimize_scalar(dc_neg_loglik, bounds=bounds, method='bounded', args=(lh, la, h, a, w))
    return float(res.x), bool(res.success)


# ─────────────────────────────────────────────────────────────────────
# ξ Grid-Search（混合权重，在 Val 集 AH acc 上优化）
# ─────────────────────────────────────────────────────────────────────

def _ah_outcome_simple(hs, as_, line):
    adj = (hs - as_) + line
    if abs(adj) < 1e-9:
        return 0.5
    return 1.0 if adj > 0 else 0.0


def ah_outcome(hs, as_, ah_line):
    frac = ah_line - math.floor(ah_line)
    is_qb = abs(frac - 0.25) < 1e-9 or abs(frac - 0.75) < 1e-9
    if is_qb:
        lower = math.floor(ah_line * 2) / 2
        upper = math.ceil(ah_line * 2) / 2
        combined = (_ah_outcome_simple(hs, as_, lower) + _ah_outcome_simple(hs, as_, upper)) / 2
        if abs(combined - 1.0) < 1e-9:   return 'ah_home'
        elif abs(combined - 0.0) < 1e-9: return 'ah_away'
        elif combined > 0.5:              return 'ah_home_half'
        else:                             return 'ah_away_half'
    else:
        r = _ah_outcome_simple(hs, as_, ah_line)
        if abs(r - 0.5) < 1e-9: return 'push'
        return 'ah_home' if r > 0.5 else 'ah_away'


def xi_grid_search(models, rho, val_df, feat_full, feat_pure, cat_f, cat_p,
                   xi_range, league_id):
    """
    在 val_df 上搜索最优 ξ（Full 权重），以 AH acc 为目标。
    xi_range: list of floats in [0.0, 1.0]
    返回 best_xi, best_ah_acc
    """
    X_f = val_df[feat_full]
    X_p = val_df[[c for c in feat_pure if c in val_df.columns]]

    lh_f = np.clip(models['H_Full'].predict(Pool(X_f, cat_features=cat_f)), 1e-4, None)
    la_f = np.clip(models['A_Full'].predict(Pool(X_f, cat_features=cat_f)), 1e-4, None)
    lh_p = np.clip(models['H_Pure'].predict(Pool(X_p, cat_features=cat_p)), 1e-4, None)
    la_p = np.clip(models['A_Pure'].predict(Pool(X_p, cat_features=cat_p)), 1e-4, None)

    # AH outcomes for val set
    ah_actuals = []
    ah_lines   = []
    hs_vals    = []
    as_vals    = []
    for i in range(len(val_df)):
        row = val_df.iloc[i]
        ah_raw = row.get('ah_line_opening', None)
        if ah_raw is None or (isinstance(ah_raw, float) and math.isnan(ah_raw)) or float(ah_raw) == -999:
            ah_actuals.append(None)
            ah_lines.append(None)
            hs_vals.append(None)
            as_vals.append(None)
            continue
        hs  = float(row['target_home_score'])
        as_ = float(row['target_away_score'])
        actual = ah_outcome(hs, as_, float(ah_raw))
        ah_actuals.append(actual)
        ah_lines.append(float(ah_raw))
        hs_vals.append(hs)
        as_vals.append(as_)

    best_xi = xi_range[0]
    best_acc = -1.0
    print(f'    ξ grid search (xi_range={[round(x,2) for x in xi_range]}):')

    for xi in xi_range:
        lh = np.clip(xi * lh_f + (1 - xi) * lh_p, 1e-4, None)
        la = np.clip(xi * la_f + (1 - xi) * la_p, 1e-4, None)

        hits = 0
        n_valid = 0
        for i in range(len(val_df)):
            actual = ah_actuals[i]
            if actual not in ('ah_home', 'ah_away'):
                continue
            matrix = build_score_matrix(float(lh[i]), float(la[i]), rho)
            p_ahh, p_aha, _ = derive_ah(matrix, ah_lines[i])
            pred = 'ah_home' if p_ahh > p_aha else 'ah_away'
            hits += int(pred == actual)
            n_valid += 1

        acc = hits / n_valid if n_valid > 0 else 0.0
        print(f'      ξ={xi:.2f}: AH acc={acc:.3f}  (n={n_valid})')
        if acc > best_acc:
            best_acc = acc
            best_xi = xi

    print(f'    → best ξ = {best_xi:.2f}  (val AH acc = {best_acc:.3f})')
    return best_xi, best_acc


# ─────────────────────────────────────────────────────────────────────
# Test 集评估（给定 ξ + rho）
# ─────────────────────────────────────────────────────────────────────

def evaluate_test_set(models, rho, xi, test_df, feat_full, feat_pure, cat_f, cat_p):
    X_f = test_df[feat_full]
    X_p = test_df[[c for c in feat_pure if c in test_df.columns]]

    lh_f = np.clip(models['H_Full'].predict(Pool(X_f, cat_features=cat_f)), 1e-4, None)
    la_f = np.clip(models['A_Full'].predict(Pool(X_f, cat_features=cat_f)), 1e-4, None)
    lh_p = np.clip(models['H_Pure'].predict(Pool(X_p, cat_features=cat_p)), 1e-4, None)
    la_p = np.clip(models['A_Pure'].predict(Pool(X_p, cat_features=cat_p)), 1e-4, None)

    lh = np.clip(xi * lh_f + (1 - xi) * lh_p, 1e-4, None)
    la = np.clip(xi * la_f + (1 - xi) * la_p, 1e-4, None)

    wdl_hits = 0
    ou_hits = ou_total = 0
    ah_hits = ah_total = 0

    for i in range(len(test_df)):
        row = test_df.iloc[i]
        hs  = float(row['target_home_score'])
        as_ = float(row['target_away_score'])
        matrix = build_score_matrix(float(lh[i]), float(la[i]), rho)

        # WDL
        ph, pd_, pa = derive_wdl(matrix)
        wdl_pred = ['home_win', 'draw', 'away_win'][np.argmax([ph, pd_, pa])]
        wdl_actual = 'home_win' if hs > as_ else ('draw' if hs == as_ else 'away_win')
        wdl_hits += int(wdl_pred == wdl_actual)

        # OU
        ou_raw = row.get('open_ou_line', None)
        if ou_raw is not None and not (isinstance(ou_raw, float) and math.isnan(ou_raw)) and float(ou_raw) not in (-999, 0):
            ou_line = float(ou_raw)
            p_ov, p_un, _ = derive_ou(matrix, ou_line)
            ou_pred = 'over' if p_ov > p_un else 'under'
            total = hs + as_
            if abs(total - ou_line) > 1e-9:
                ou_actual = 'over' if total > ou_line else 'under'
                ou_hits += int(ou_pred == ou_actual)
                ou_total += 1

        # AH
        ah_raw = row.get('ah_line_opening', None)
        if ah_raw is not None and not (isinstance(ah_raw, float) and math.isnan(ah_raw)) and float(ah_raw) != -999:
            ah_line = float(ah_raw)
            p_ahh, p_aha, _ = derive_ah(matrix, ah_line)
            ah_pred = 'ah_home' if p_ahh > p_aha else 'ah_away'
            actual_ah = ah_outcome(hs, as_, ah_line)
            if actual_ah in ('ah_home', 'ah_away'):
                ah_hits += int(ah_pred == actual_ah)
                ah_total += 1

    n = len(test_df)
    return {
        'n_wdl': n,
        'n_ou': ou_total,
        'n_ah': ah_total,
        'wdl_acc': round(wdl_hits / n, 4) if n > 0 else None,
        'ou_acc': round(ou_hits / ou_total, 4) if ou_total > 0 else None,
        'ah_acc': round(ah_hits / ah_total, 4) if ah_total > 0 else None,
    }


# ─────────────────────────────────────────────────────────────────────
# 单联赛训练主流程
# ─────────────────────────────────────────────────────────────────────

def train_league(lid: int, df: pd.DataFrame, feat_full, feat_pure, cat_features):
    name = LEAGUE_NAMES.get(lid, str(lid))
    out_dir = os.path.join(MODEL_BASE, str(lid))
    os.makedirs(out_dir, exist_ok=True)

    print(f'\n{"="*60}')
    print(f'  联赛: {name} (id={lid})')
    print(f'  输出目录: {out_dir}')
    print(f'{"="*60}')

    # 过滤联赛数据
    league_df = df[df['League_ID'] == lid].copy()
    train_df  = league_df[league_df['split'] == 'train'].reset_index(drop=True)
    val_df    = league_df[league_df['split'] == 'val'].reset_index(drop=True)
    test_df   = league_df[league_df['split'] == 'test'].reset_index(drop=True)

    print(f'  Train={len(train_df)}  Val={len(val_df)}  Test={len(test_df)}')

    if len(train_df) < 100:
        print(f'  ⚠️  训练集不足 100 行，跳过联赛 {name}')
        return None

    cat_f = [c for c in cat_features if c in feat_full]
    cat_p = [c for c in cat_features if c in feat_pure]

    def make_xy(subset, feats):
        X = subset[feats].copy()
        return (X,
                subset['target_home_score'].astype(float),
                subset['target_away_score'].astype(float),
                subset['sample_weight'].astype(float))

    X_tr_f, y_tr_h, y_tr_a, w_tr = make_xy(train_df, feat_full)
    X_va_f, y_va_h, y_va_a, _    = make_xy(val_df,   feat_full)
    X_tr_p, _, _, _               = make_xy(train_df, feat_pure)
    X_va_p, _, _, _               = make_xy(val_df,   feat_pure)

    # ── 训练 4 个模型 ──────────────────────────────────────────────────
    print('\n  [训练]')
    t0 = time.time()
    M_H_Full = train_one('Model_H_Full', X_tr_f, y_tr_h, w_tr, X_va_f, y_va_h, cat_f, out_dir)
    M_A_Full = train_one('Model_A_Full', X_tr_f, y_tr_a, w_tr, X_va_f, y_va_a, cat_f, out_dir)
    M_H_Pure = train_one('Model_H_Pure', X_tr_p, y_tr_h, w_tr, X_va_p, y_va_h, cat_p, out_dir)
    M_A_Pure = train_one('Model_A_Pure', X_tr_p, y_tr_a, w_tr, X_va_p, y_va_a, cat_p, out_dir)
    elapsed = time.time() - t0
    print(f'  训练用时: {elapsed:.0f}s')

    models = {
        'H_Full': M_H_Full, 'A_Full': M_A_Full,
        'H_Pure': M_H_Pure, 'A_Pure': M_A_Pure,
    }

    # ── Dixon-Coles ρ（联赛训练集）───────────────────────────────────
    print('\n  [ρ 估计]')
    lh_tr_f = np.clip(M_H_Full.predict(X_tr_f), 1e-4, None)
    la_tr_f = np.clip(M_A_Full.predict(X_tr_f), 1e-4, None)
    lh_tr_p = np.clip(M_H_Pure.predict(X_tr_p), 1e-4, None)
    la_tr_p = np.clip(M_A_Pure.predict(X_tr_p), 1e-4, None)

    # 先用默认 xi=0.6 做 ρ（val 之前的近似）
    lh_tr = np.clip(0.6 * lh_tr_f + 0.4 * lh_tr_p, 1e-4, None)
    la_tr = np.clip(0.6 * la_tr_f + 0.4 * la_tr_p, 1e-4, None)

    rho, ok = estimate_rho(lh_tr, la_tr,
                           y_tr_h.values.astype(int),
                           y_tr_a.values.astype(int),
                           w_tr.values)
    print(f'  ρ = {rho:.4f}  (success={ok})')

    # ── ξ Grid-Search（Val AH acc）───────────────────────────────────
    print('\n  [ξ grid-search on Val set]')
    if lid == 55:  # Serie A (55=SerieA confirmed) → Pure 为主（xG覆盖率81%，用户决策）
        xi_range = [0.0, 0.1, 0.2, 0.3]
        print('  Serie A (lid=55): ξ 限制在 [0.0, 0.3]（Pure 主力，xG覆盖率81%）')
    else:
        xi_range = [round(x * 0.1, 1) for x in range(11)]  # 0.0 → 1.0

    best_xi, best_val_ah = xi_grid_search(
        models, rho, val_df, feat_full, feat_pure, cat_f, cat_p, xi_range, lid
    )

    # ── Test 集评估（best ξ）─────────────────────────────────────────
    print('\n  [Test 集评估]')
    test_metrics = evaluate_test_set(
        models, rho, best_xi, test_df, feat_full, feat_pure, cat_f, cat_p
    )
    print(f'  WDL={test_metrics["wdl_acc"]}  OU={test_metrics["ou_acc"]}  '
          f'AH={test_metrics["ah_acc"]}  '
          f'(n_wdl={test_metrics["n_wdl"]}, n_ah={test_metrics["n_ah"]})')

    # ── 保存 rho.json（含 best_xi）───────────────────────────────────
    rho_data = {
        'rho': rho,
        'best_xi': best_xi,
        'best_val_ah_acc': best_val_ah,
        'league_id': lid,
        'league': name,
    }
    rho_path = os.path.join(out_dir, 'rho.json')
    with open(rho_path, 'w') as f:
        json.dump(rho_data, f, indent=2)
    print(f'  💾 rho.json → {rho_path}')

    # ── eval_report.csv ───────────────────────────────────────────────
    csv_path = os.path.join(out_dir, 'eval_report.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['model', 'league_id', 'league', 'split',
                                          'n_wdl', 'n_ou', 'n_ah',
                                          'wdl_acc', 'ou_acc', 'ah_acc',
                                          'best_xi', 'rho'])
        w.writeheader()
        w.writerow({
            'model': f'league_{lid}', 'league_id': lid, 'league': name,
            'split': 'val', 'n_wdl': len(val_df), 'n_ou': '-', 'n_ah': '-',
            'wdl_acc': '-', 'ou_acc': '-', 'ah_acc': round(best_val_ah, 4),
            'best_xi': best_xi, 'rho': round(rho, 4),
        })
        w.writerow({
            'model': f'league_{lid}', 'league_id': lid, 'league': name,
            'split': 'test', **test_metrics,
            'best_xi': best_xi, 'rho': round(rho, 4),
        })
    print(f'  💾 eval_report.csv → {csv_path}')

    # eval_metrics.json（供 Phase 3 compare_models_v5.py 读取）
    eval_metrics = {
        'league': name,
        'league_id': lid,
        'rho': round(rho, 6),
        'xi': best_xi,
        'best_val_ah_acc': round(best_val_ah, 4) if best_val_ah is not None else None,
        **{f'n_{k}': test_metrics.get(f'n_{k}') for k in ['wdl', 'ou', 'ah']},
        **{f'{k}_acc': test_metrics.get(f'{k}_acc') for k in ['wdl', 'ou', 'ah']},
    }
    metrics_path = os.path.join(out_dir, 'eval_metrics.json')
    with open(metrics_path, 'w') as f:
        json.dump(eval_metrics, f, indent=2, ensure_ascii=False)
    print(f'  💾 eval_metrics.json → {metrics_path}')

    return {
        'league_id': lid,
        'league': name,
        'rho': rho,
        'best_xi': best_xi,
        'best_val_ah': best_val_ah,
        'test': test_metrics,
    }


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    print('=' * 60)
    print('  train_league_v5  — Phase 2 BIG5 联赛级训练')
    print('=' * 60)

    # ── 1. 加载全量数据（一次性，后面按联赛过滤）──────────────────────
    print('\n[Step 1] 加载数据')
    df, feat_full, feat_pure, cat_features = load_and_prepare()
    print(f'  总行数: {len(df)}  feat_full={len(feat_full)}  feat_pure={len(feat_pure)}')

    # ── 2. 每个联赛依次训练 ─────────────────────────────────────────────
    summary = {}
    for lid in TARGET_LEAGUES:
        result = train_league(lid, df, feat_full, feat_pure, cat_features)
        if result:
            summary[lid] = result

    # ── 3. 汇总报告 ─────────────────────────────────────────────────────
    print('\n\n' + '=' * 60)
    print('  Phase 2 汇总')
    print('=' * 60)
    print(f'\n  {"联赛":<12} {"ξ":>6} {"ρ":>8} {"ValAH":>8} {"TestAH":>8} {"TestOU":>8} {"TestWDL":>8}')
    print('  ' + '─' * 58)
    for lid, r in summary.items():
        t = r['test']
        print(f'  {r["league"]:<12} {r["best_xi"]:>6.2f} {r["rho"]:>8.4f}'
              f' {r["best_val_ah"]:>8.3f}'
              f' {str(t["ah_acc"]):>8}'
              f' {str(t["ou_acc"]):>8}'
              f' {str(t["wdl_acc"]):>8}')

    # 保存汇总 JSON
    summary_path = os.path.join(MODEL_BASE, 'league_summary.json')
    with open(summary_path, 'w') as f:
        json.dump({str(k): v for k, v in summary.items()}, f, indent=2)
    print(f'\n  💾 league_summary.json → {summary_path}')
    print('\n  ✅ train_league_v5 完成')


if __name__ == '__main__':
    main()
