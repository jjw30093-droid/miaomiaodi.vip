#!/usr/bin/env python3
"""
train_global_v5.py — Phase 1: 全局模型训练（含 2021/22 扩充数据集）

与生产版 train_lambda_v5.py 的区别：
  1. 保存到 models_v5_lambda/global/（不覆盖生产模型）
  2. 增加 Test 集按联赛 AH/OU/WDL 评估
  3. 生成 eval_report.csv（供 Phase 3 A/B 对比）

训练 4 个 CatBoost Poisson Regressor：
  Model_H_Full / Model_A_Full  — 含赔率特征（Ensemble 0.6F + 0.4P）
  Model_H_Pure / Model_A_Pure  — 无赔率特征

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
DB_PATH    = '/home/ubuntu/app/backend/football_uk.db'
GLOBAL_DIR = '/home/ubuntu/app/backend/models_v5_lambda/global'
os.makedirs(GLOBAL_DIR, exist_ok=True)

# ─── 联赛映射 ────────────────────────────────────────────────────────
LEAGUE_NAMES = {
    47: 'EPL', 87: 'LaLiga', 54: 'Bundesliga',
    55: 'SerieA', 53: 'Ligue1',
    113: 'A-League', 223: 'J-League', 9080: 'K-League',
}

# ─── CatBoost 参数 ────────────────────────────────────────────────────
CB_PARAMS = dict(
    iterations=2000,
    depth=6,
    learning_rate=0.03,
    l2_leaf_reg=4,
    loss_function='Poisson',
    eval_metric='Poisson',
    early_stopping_rounds=150,
    random_seed=42,
    verbose=200,
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

ENSEMBLE_FULL = 0.6
ENSEMBLE_PURE = 0.4


# ─────────────────────────────────────────────────────────────────────
# 1. 数据加载 + 特征准备
# ─────────────────────────────────────────────────────────────────────

def load_and_prepare():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query('SELECT * FROM mart_lambda_dataset_v5', conn)
    conn.close()
    print(f'  总行数: {len(df)}  列数: {len(df.columns)}')

    # Drop NULL>40% cols
    null_rates = df.isnull().mean()
    drop_cols = null_rates[null_rates > 0.40].index.tolist()
    if drop_cols:
        print(f'  删除 NULL>40% 列 ({len(drop_cols)}): {drop_cols[:5]}')
        df = df.drop(columns=drop_cols, errors='ignore')

    non_feat = set(META_COLS + TARGET_COLS)
    candidate_cols = [c for c in df.columns if c not in non_feat]

    feat_full = candidate_cols.copy()
    feat_pure = [c for c in candidate_cols
                 if not any(kw.lower() in c.lower() for kw in ODDS_PATTERN_KEYWORDS)]

    cat_features = ['League_ID'] if 'League_ID' in feat_full else []

    # NULL 填充 -999 / __NA__
    for c in feat_full:
        if df[c].dtype.kind in 'iuf':
            df[c] = df[c].fillna(-999)
        elif df[c].dtype == object:
            df[c] = df[c].fillna('__NA__')

    print(f'  feat_full: {len(feat_full)}  feat_pure: {len(feat_pure)}'
          f'  (排除 {len(feat_full)-len(feat_pure)} 赔率列)')
    return df, feat_full, feat_pure, cat_features


# ─────────────────────────────────────────────────────────────────────
# 2. 训练单个模型
# ─────────────────────────────────────────────────────────────────────

def train_one(name, X_tr, y_tr, w_tr, X_val, y_val, cat_features, params, out_dir):
    print(f'\n  ── {name} ──')
    print(f'     train={len(X_tr):,}  val={len(X_val):,}  features={X_tr.shape[1]}')
    model = CatBoostRegressor(**params)
    t0 = time.time()
    model.fit(
        Pool(X_tr, y_tr, weight=w_tr, cat_features=cat_features),
        eval_set=Pool(X_val, y_val, cat_features=cat_features),
        use_best_model=True,
    )
    elapsed = time.time() - t0
    bi  = model.get_best_iteration()
    tl  = model.get_best_score()['learn']['Poisson']
    vl  = model.get_best_score()['validation']['Poisson']
    print(f'     BestIter={bi}  TrainLoss={tl:.4f}  ValLoss={vl:.4f}  用时={elapsed:.0f}s')
    path = os.path.join(out_dir, f'{name}.cbm')
    model.save_model(path)
    print(f'     💾 {path}')
    return model


# ─────────────────────────────────────────────────────────────────────
# 3. Dixon-Coles ρ
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


def estimate_rho(lh, la, h, a, w, bounds=(-0.20, 0.10)):
    res = minimize_scalar(dc_neg_loglik, bounds=bounds, method='bounded', args=(lh, la, h, a, w))
    return res.x, res.success


# ─────────────────────────────────────────────────────────────────────
# 4. Test 集评估（AH / OU / WDL 按联赛）
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
        r_l = _ah_outcome_simple(hs, as_, lower)
        r_u = _ah_outcome_simple(hs, as_, upper)
        combined = (r_l + r_u) / 2
        if abs(combined - 1.0) < 1e-9:   return 'ah_home'
        elif abs(combined - 0.0) < 1e-9: return 'ah_away'
        elif combined > 0.5:              return 'ah_home_half'
        else:                             return 'ah_away_half'
    else:
        r = _ah_outcome_simple(hs, as_, ah_line)
        if abs(r - 0.5) < 1e-9: return 'push'
        return 'ah_home' if r > 0.5 else 'ah_away'


def evaluate_test(models, rho_data, df_all, feat_full, feat_pure, cat_features):
    """
    评估 test 集全市场准确率，返回 per-league 指标 dict。
    """
    test_df = df_all[df_all['split'] == 'test'].reset_index(drop=True)
    n = len(test_df)
    print(f'\n  Test 集: {n} 行')

    cat_f = [c for c in cat_features if c in feat_full]
    cat_p = [c for c in cat_features if c in feat_pure]

    X_f = test_df[feat_full]
    X_p = test_df[[c for c in feat_pure if c in test_df.columns]]

    lh_f = np.clip(models['H_Full'].predict(Pool(X_f, cat_features=cat_f)), 1e-4, None)
    la_f = np.clip(models['A_Full'].predict(Pool(X_f, cat_features=cat_f)), 1e-4, None)
    lh_p = np.clip(models['H_Pure'].predict(Pool(X_p, cat_features=cat_p)), 1e-4, None)
    la_p = np.clip(models['A_Pure'].predict(Pool(X_p, cat_features=cat_p)), 1e-4, None)

    lh = ENSEMBLE_FULL * lh_f + ENSEMBLE_PURE * lh_p
    la = ENSEMBLE_FULL * la_f + ENSEMBLE_PURE * la_p

    rho_by_league = {int(k): v for k, v in rho_data['rho_by_league'].items()}
    rho_global = rho_data['rho_global']

    records = []
    for i in range(n):
        lid = int(test_df.iloc[i]['League_ID'])
        rho = rho_by_league.get(lid, rho_global)
        hs  = float(test_df.iloc[i]['target_home_score'])
        as_ = float(test_df.iloc[i]['target_away_score'])

        matrix = build_score_matrix(float(lh[i]), float(la[i]), rho)
        ph, pd_, pa = derive_wdl(matrix)
        wdl_pred = ['home_win', 'draw', 'away_win'][np.argmax([ph, pd_, pa])]
        wdl_actual = ('home_win' if hs > as_ else
                      ('draw' if hs == as_ else 'away_win'))

        # OU
        ou_line_raw = test_df.iloc[i].get('open_ou_line', None)
        ou_acc = None
        if ou_line_raw is not None and not (isinstance(ou_line_raw, float) and math.isnan(ou_line_raw)) and float(ou_line_raw) not in (-999, 0):
            ou_line = float(ou_line_raw)
            p_ov, p_un, _ = derive_ou(matrix, ou_line)
            ou_pred = 'over' if p_ov > p_un else 'under'
            total = hs + as_
            if abs(total - ou_line) > 1e-9:
                ou_actual = 'over' if total > ou_line else 'under'
                ou_acc = int(ou_pred == ou_actual)

        # AH
        ah_line_raw = test_df.iloc[i].get('ah_line_opening', None)
        ah_acc = None
        if ah_line_raw is not None and not (isinstance(ah_line_raw, float) and math.isnan(ah_line_raw)) and float(ah_line_raw) != -999:
            ah_line = float(ah_line_raw)
            p_ahh, p_aha, _ = derive_ah(matrix, ah_line)
            ah_pred = 'ah_home' if p_ahh > p_aha else 'ah_away'
            actual_ah = ah_outcome(hs, as_, ah_line)
            if actual_ah in ('ah_home', 'ah_away'):
                ah_acc = int(ah_pred == actual_ah)

        records.append({
            'league_id': lid,
            'wdl_correct': int(wdl_pred == wdl_actual),
            'ou_acc': ou_acc,
            'ah_acc': ah_acc,
        })

    result_df = pd.DataFrame(records)

    # 全局指标
    def pct(col):
        sub = result_df[result_df[col].notna()]
        if len(sub) == 0:
            return None, 0
        return sub[col].mean(), len(sub)

    global_wdl = result_df['wdl_correct'].mean()
    global_ou, n_ou = pct('ou_acc')
    global_ah, n_ah = pct('ah_acc')

    print(f'\n  ─── 全局 Test 指标 ───')
    print(f'  WDL acc: {global_wdl:.3f}  ({result_df.wdl_correct.sum()}/{len(result_df)})')
    print(f'  OU  acc: {global_ou:.3f}  (n={n_ou})' if global_ou is not None else '  OU  acc: N/A')
    print(f'  AH  acc: {global_ah:.3f}  (n={n_ah})' if global_ah is not None else '  AH  acc: N/A')

    # Per-league 指标
    league_metrics = {}
    print(f'\n  ─── 联赛级别 Test 指标 ───')
    print(f'  {"联赛":<12} {"WDL":>7} {"OU":>7} {"AH":>7}  n_wdl  n_ou  n_ah')
    print('  ' + '─' * 55)

    for lid, grp in result_df.groupby('league_id'):
        name = LEAGUE_NAMES.get(lid, str(lid))
        wdl_a = grp['wdl_correct'].mean()
        ou_sub = grp['ou_acc'].dropna()
        ah_sub = grp['ah_acc'].dropna()
        ou_a = ou_sub.mean() if len(ou_sub) > 0 else None
        ah_a = ah_sub.mean() if len(ah_sub) > 0 else None

        print(f'  {name:<12} {wdl_a:>7.3f}'
              f' {ou_a:>7.3f}' if ou_a is not None else f'  {name:<12} {wdl_a:>7.3f}     N/A',
              end='')
        if ah_a is not None:
            print(f' {ah_a:>7.3f}  {len(grp):>5}  {len(ou_sub):>4}  {len(ah_sub):>4}')
        else:
            print(f'     N/A  {len(grp):>5}  {len(ou_sub):>4}     0')

        league_metrics[lid] = {
            'league': name,
            'n_wdl': len(grp),
            'n_ou': len(ou_sub),
            'n_ah': len(ah_sub),
            'wdl_acc': round(float(wdl_a), 4),
            'ou_acc': round(float(ou_a), 4) if ou_a is not None else None,
            'ah_acc': round(float(ah_a), 4) if ah_a is not None else None,
        }

    return {
        'global': {
            'wdl_acc': round(float(global_wdl), 4),
            'ou_acc': round(float(global_ou), 4) if global_ou is not None else None,
            'ah_acc': round(float(global_ah), 4) if global_ah is not None else None,
            'n_wdl': len(result_df),
            'n_ou': n_ou,
            'n_ah': n_ah,
        },
        'by_league': league_metrics,
    }


# ─────────────────────────────────────────────────────────────────────
# 5. eval_report.csv
# ─────────────────────────────────────────────────────────────────────

def write_eval_report(metrics: dict, out_dir: str):
    path = os.path.join(out_dir, 'eval_report.csv')
    rows = []

    # global row
    g = metrics['global']
    rows.append({
        'model': 'global', 'league_id': 'ALL', 'league': 'ALL',
        **g,
    })

    for lid, m in metrics['by_league'].items():
        rows.append({
            'model': 'global', 'league_id': lid,
            **m,
        })

    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['model', 'league_id', 'league',
                                          'n_wdl', 'n_ou', 'n_ah',
                                          'wdl_acc', 'ou_acc', 'ah_acc'])
        w.writeheader()
        w.writerows(rows)

    print(f'\n  💾 eval_report.csv → {path}')


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    print('=' * 65)
    print('  train_global_v5  — Phase 1 全局训练')
    print(f'  输出目录: {GLOBAL_DIR}')
    print('=' * 65)

    # ── 1. 加载数据 ────────────────────────────────────────────────────
    print('\n[Step 1] 加载数据')
    df, feat_full, feat_pure, cat_features = load_and_prepare()

    train_df = df[df['split'] == 'train'].copy()
    val_df   = df[df['split'] == 'val'].copy()
    print(f'  Train: {len(train_df)}  Val: {len(val_df)}  '
          f'Test: {(df["split"]=="test").sum()}')

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

    cat_f = [c for c in cat_features if c in feat_full]
    cat_p = [c for c in cat_features if c in feat_pure]

    # ── 2. 训练 4 个模型 ───────────────────────────────────────────────
    print('\n[Step 2] 训练 4 个 CatBoost Poisson Regressor')

    M_H_Full = train_one('Model_H_Full', X_tr_f, y_tr_h, w_tr, X_va_f, y_va_h, cat_f, CB_PARAMS, GLOBAL_DIR)
    M_A_Full = train_one('Model_A_Full', X_tr_f, y_tr_a, w_tr, X_va_f, y_va_a, cat_f, CB_PARAMS, GLOBAL_DIR)
    M_H_Pure = train_one('Model_H_Pure', X_tr_p, y_tr_h, w_tr, X_va_p, y_va_h, cat_p, CB_PARAMS, GLOBAL_DIR)
    M_A_Pure = train_one('Model_A_Pure', X_tr_p, y_tr_a, w_tr, X_va_p, y_va_a, cat_p, CB_PARAMS, GLOBAL_DIR)

    models = {
        'H_Full': M_H_Full, 'A_Full': M_A_Full,
        'H_Pure': M_H_Pure, 'A_Pure': M_A_Pure,
    }

    # ── 3. Val 集回归指标 ──────────────────────────────────────────────
    print('\n[Step 3] Val 集回归指标')
    for name, model, X_va, y_va in [
        ('H_Full', M_H_Full, X_va_f, y_va_h),
        ('A_Full', M_A_Full, X_va_f, y_va_a),
        ('H_Pure', M_H_Pure, X_va_p, y_va_h),
        ('A_Pure', M_A_Pure, X_va_p, y_va_a),
    ]:
        preds = model.predict(X_va)
        rmse = np.sqrt(np.mean((y_va.values - preds) ** 2))
        corr = np.corrcoef(preds, y_va.values)[0, 1]
        print(f'  {name:<10} RMSE={rmse:.4f}  Corr={corr:.4f}')

    # ── 4. Dixon-Coles ρ ──────────────────────────────────────────────
    print('\n[Step 4] Dixon-Coles ρ 估计（Train 集）')
    lh_tr = np.clip(
        ENSEMBLE_FULL * M_H_Full.predict(X_tr_f) + ENSEMBLE_PURE * M_H_Pure.predict(X_tr_p),
        1e-4, None
    )
    la_tr = np.clip(
        ENSEMBLE_FULL * M_A_Full.predict(X_tr_f) + ENSEMBLE_PURE * M_A_Pure.predict(X_tr_p),
        1e-4, None
    )
    h_tr = y_tr_h.values.astype(int)
    a_tr = y_tr_a.values.astype(int)

    rho_global, ok = estimate_rho(lh_tr, la_tr, h_tr, a_tr, w_tr.values)
    print(f'  全局 ρ = {rho_global:.4f}  (success={ok})')

    rho_by_league: dict[str, float] = {}
    print(f'\n  {"联赛":<12} {"ρ":>8}  {"n":>6}')
    print('  ' + '─' * 30)
    for lid in [47, 87, 54, 55, 53, 113, 223, 9080]:
        mask = train_df['League_ID'] == lid
        n_lid = int(mask.sum())
        if n_lid < 200:
            print(f'  {LEAGUE_NAMES.get(lid, str(lid)):<12} {"—":>8}  {n_lid:>6}  (样本不足)')
            continue
        idx_positions = train_df.index.get_indexer(train_df.index[mask])
        lh_l = lh_tr[idx_positions]
        la_l = la_tr[idx_positions]
        h_l  = h_tr[idx_positions]
        a_l  = a_tr[idx_positions]
        w_l  = w_tr.values[idx_positions]
        rho_l, _ = estimate_rho(lh_l, la_l, h_l, a_l, w_l)
        rho_by_league[str(lid)] = float(rho_l)
        print(f'  {LEAGUE_NAMES.get(lid, str(lid)):<12} {rho_l:>8.4f}  {n_lid:>6}')

    rho_data = {
        'rho_global': float(rho_global),
        'rho_by_league': rho_by_league,
    }
    rho_path = os.path.join(GLOBAL_DIR, 'rho.json')
    with open(rho_path, 'w') as f:
        json.dump(rho_data, f, indent=2, ensure_ascii=False)
    print(f'\n  💾 rho.json → {rho_path}')

    # ── 5. Test 集评估 ─────────────────────────────────────────────────
    print('\n[Step 5] Test 集评估（AH / OU / WDL 按联赛）')
    metrics = evaluate_test(models, rho_data, df, feat_full, feat_pure, cat_features)

    # ── 6. eval_report.csv ────────────────────────────────────────────
    print('\n[Step 6] 写出 eval_report.csv')
    write_eval_report(metrics, GLOBAL_DIR)

    # 也保存为 JSON（Phase 3 方便读取）
    metrics_path = os.path.join(GLOBAL_DIR, 'eval_metrics.json')
    with open(metrics_path, 'w') as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    print(f'  💾 eval_metrics.json → {metrics_path}')

    # ── 7. Phase 1 通过判定 ────────────────────────────────────────────
    print('\n' + '=' * 65)
    print('  Phase 1 通过判定')
    print('=' * 65)

    g = metrics['global']
    ah_ok  = g['ah_acc'] is not None and g['ah_acc'] >= 0.52
    wdl_ok = g['wdl_acc'] >= 0.50

    print(f'  全局 AH acc  = {g["ah_acc"]}  {"✅ ≥0.52" if ah_ok else "⚠️  <0.52"}')
    print(f'  全局 WDL acc = {g["wdl_acc"]}  {"✅ ≥0.50" if wdl_ok else "⚠️  <0.50"}')
    print(f'\n  {"✅ PASS → 进入 Phase 2 联赛级训练" if (ah_ok or wdl_ok) else "⚠️  请检查特征质量"}')
    print('\n  ✅ train_global_v5 完成')


if __name__ == '__main__':
    main()
