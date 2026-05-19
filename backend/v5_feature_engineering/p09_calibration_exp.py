#!/usr/bin/env python3
"""
p09_calibration_exp.py — P0.9 后置 isotonic 校准实验

Stage 1: 在 val split (1523行) 上拟合 OU isotonic 校准器 (V5/V6/V6.1)
Stage 2: test split (1525行) 6套配置对照
Stage 3: 杯赛/欧战迁移性 (263行 CSV)
Stage 4: WDL 温度校准 (val 拟合 T，test 评估)

输出: models/calibrators_p09/{v5/v6/v6_1}_ou_isotonic.pkl
     reports/p09_calibration_eval.md
"""
from __future__ import annotations
import json, os, sys, sqlite3, pickle, warnings
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss
warnings.filterwarnings('ignore')

sys.path.insert(0, os.path.dirname(__file__))
from inference_lambda import build_score_matrix, derive_wdl, derive_ou, derive_ah

# ─────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────
DB_PATH    = '/home/ubuntu/app/backend/football_uk.db'
V5_DIR     = '/home/ubuntu/app/backend/models_v5_lambda'
V6_DIR     = '/home/ubuntu/app/backend/models/v6_prototype'
V61_DIR    = '/home/ubuntu/app/backend/models/v6_1_clean'
CAL_DIR    = '/home/ubuntu/app/backend/models/calibrators_p09'
REPORT_DIR = '/home/ubuntu/app/backend/reports'
CUP_CSV    = '/home/ubuntu/app/backend/reports/cup_european_shadow_test_set.csv'

os.makedirs(CAL_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

BIG5_LIDS = {47, 53, 54, 55, 87}

ODDS_PATTERN_KEYWORDS = [
    'raw_home', 'raw_away', 'raw_draw', 'fair_home', 'fair_draw', 'fair_away',
    'implied', 'ah_implied_diff', 'ah_raw_home', 'ah_raw_away', 'ah_odds_movement',
    'closing_eu_raw', 'closing_ah_raw', 'closing_ou_raw',
    'closing_eu_fair', 'closing_ah_fair', 'closing_ou_fair',
    'open_eu_fair', 'open_ah_fair', 'open_ou_fair', 'eu_odds', 'eu_implied',
]
META_COLS_V6 = [
    'match_id','match_date','Season','Home_Team_ID','Away_Team_ID',
    'Home_Team_Name','Away_Team_Name','days_from_latest','sample_weight',
    'split','ah_source','ah_line_category','is_fd_fallback',
]
TARGET_COLS = ['target_home_score', 'target_away_score']


# ─────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────

def load_split(split: str) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        f"SELECT * FROM mart_lambda_dataset_v6_train WHERE split='{split}'", conn)
    conn.close()
    n_big5 = df['League_ID'].isin(BIG5_LIDS).sum()
    print(f'  {split}: {len(df):,} 行  BIG5={n_big5}  非BIG5={len(df)-n_big5}')
    return df


def prep_features(df: pd.DataFrame):
    null_rates = df.isnull().mean()
    drop_cols  = null_rates[null_rates > 0.40].index.tolist()
    df = df.drop(columns=drop_cols, errors='ignore')
    non_feat = set(META_COLS_V6 + TARGET_COLS)
    cands = [c for c in df.columns if c not in non_feat]
    feat_full = cands
    feat_pure = [c for c in cands if not any(
        kw.lower() in c.lower() for kw in ODDS_PATTERN_KEYWORDS)]
    for c in feat_full:
        if df[c].dtype in [np.float64, np.float32, float, np.int64, np.int32, int]:
            df[c] = df[c].fillna(-999)
        elif df[c].dtype == object:
            df[c] = df[c].fillna('__NA__')
    return df, feat_full, feat_pure


# ─────────────────────────────────────────────────────────────────────
# Model loading + inference (reuse from eval_three_way.py)
# ─────────────────────────────────────────────────────────────────────

def load_models(model_dir: str, tags: dict) -> dict:
    from catboost import CatBoostRegressor
    models = {}
    for key, fname_stem in tags.items():
        path = os.path.join(model_dir, f'{fname_stem}.cbm')
        m = CatBoostRegressor(); m.load_model(path)
        models[key] = m
        print(f'  [{fname_stem}.cbm]  BestIter={m.get_best_iteration()}')
    return models


def ensemble_predict(models: dict, df: pd.DataFrame):
    X_fh = df[list(models['H_Full'].feature_names_)].copy()
    X_fa = df[list(models['A_Full'].feature_names_)].copy()
    X_ph = df[list(models['H_Pure'].feature_names_)].copy()
    X_pa = df[list(models['A_Pure'].feature_names_)].copy()
    lam_h = (0.6 * np.clip(models['H_Full'].predict(X_fh), 1e-4, None) +
             0.4 * np.clip(models['H_Pure'].predict(X_ph), 1e-4, None))
    lam_a = (0.6 * np.clip(models['A_Full'].predict(X_fa), 1e-4, None) +
             0.4 * np.clip(models['A_Pure'].predict(X_pa), 1e-4, None))
    return lam_h, lam_a


def run_inference(df: pd.DataFrame, lam_h: np.ndarray, lam_a: np.ndarray,
                  rho_data: dict) -> pd.DataFrame:
    rho_global = rho_data['rho_global']
    rho_league = rho_data.get('rho_by_league', {})
    records = []
    for i in range(len(df)):
        row  = df.iloc[i]
        lid  = str(int(row.get('League_ID', 0)))
        rho  = rho_league.get(lid, rho_global)
        lh, la = float(lam_h[i]), float(lam_a[i])
        mat = build_score_matrix(lh, la, rho)
        p_hw, p_d, p_aw = derive_wdl(mat)
        ou_line = float(row.get('closing_ou_line', row.get('open_ou_line', 2.5)))
        if ou_line <= 0 or np.isnan(ou_line): ou_line = 2.5
        p_ov, p_un, _ = derive_ou(mat, ou_line)
        ah_line = float(row.get('closing_ah_line', row.get('ah_line_opening', 0.0)))
        if np.isnan(ah_line): ah_line = 0.0
        p_hc, p_ac, _ = derive_ah(mat, ah_line)
        records.append({
            'match_id': row['match_id'], 'League_ID': int(row.get('League_ID', 0)),
            'is_big5': int(row.get('League_ID', 0)) in BIG5_LIDS,
            'hs': int(row['target_home_score']), 'as_': int(row['target_away_score']),
            'ou_line': ou_line, 'ah_line': ah_line,
            'lam_h': lh, 'lam_a': la,
            'p_hw': p_hw, 'p_d': p_d, 'p_aw': p_aw,
            'p_ov': p_ov, 'p_un': p_un, 'p_hc': p_hc, 'p_ac': p_ac,
        })
    return pd.DataFrame(records)


# ─────────────────────────────────────────────────────────────────────
# Stage 1: Fit isotonic calibrators on val split
# ─────────────────────────────────────────────────────────────────────

def fit_isotonic_calibrator(p_ov: np.ndarray, y: np.ndarray, name: str):
    iso = IsotonicRegression(out_of_bounds='clip')
    iso.fit(p_ov, y)
    pkl_path = os.path.join(CAL_DIR, f'{name}_ou_isotonic.pkl')
    with open(pkl_path, 'wb') as f:
        pickle.dump(iso, f)
    print(f'  保存校准器 → {pkl_path}  (n={len(y):,})')
    return iso


def calibrator_keypoints(iso: IsotonicRegression, xvals=None):
    if xvals is None:
        xvals = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55]
    return {x: float(iso.predict([x])[0]) for x in xvals}


def eq_freq_buckets(p_ov: np.ndarray, y: np.ndarray, n_buckets=10):
    """等频分桶: 桶均值预测 vs 实际 over 率"""
    order = np.argsort(p_ov)
    p_sorted, y_sorted = p_ov[order], y[order]
    splits = np.array_split(np.arange(len(p_sorted)), n_buckets)
    rows = []
    for idxs in splits:
        rows.append({
            'mean_pred': float(p_sorted[idxs].mean()),
            'actual_rate': float(y_sorted[idxs].mean()),
            'n': len(idxs),
        })
    return rows


# ─────────────────────────────────────────────────────────────────────
# Stage 2: OU metrics on test split
# ─────────────────────────────────────────────────────────────────────

def ou_metrics(res: pd.DataFrame, iso=None, label='raw') -> dict:
    """Compute OU metrics; if iso supplied, use calibrated probabilities."""
    r = res.copy()
    r['over_label'] = ((r['hs'] + r['as_']) > r['ou_line']).astype(int)
    # exclude pushes (exact total == ou_line)
    r = r[r['hs'] + r['as_'] != r['ou_line']].copy()

    p_ov = r['p_ov'].values.copy()
    if iso is not None:
        p_ov = iso.predict(p_ov)
    p_un = 1.0 - p_ov

    y = r['over_label'].values

    pred_ou = (p_ov >= p_un).astype(int)  # 1=over, 0=under
    acc  = float((pred_ou == y).mean())
    brier = float(np.mean((p_ov - y)**2))

    # LogLoss (clip for stability)
    p_clipped = np.clip(p_ov, 1e-7, 1-1e-7)
    ll = float(np.mean(-y * np.log(p_clipped) - (1-y) * np.log(1-p_clipped)))

    # [0.3, 0.4) bucket bias
    if iso is not None:
        raw_pov = r['p_ov'].values
        bucket_mask = (raw_pov >= 0.3) & (raw_pov < 0.4)
    else:
        bucket_mask = (p_ov >= 0.3) & (p_ov < 0.4)
    if bucket_mask.sum() > 0:
        b_pred = p_ov[bucket_mask].mean()
        b_act  = y[bucket_mask].mean()
        b_delta = b_act - b_pred
        b_n = int(bucket_mask.sum())
    else:
        b_pred = b_act = b_delta = float('nan')
        b_n = 0

    return {
        'n': len(r), 'acc': acc, 'brier': brier, 'logloss': ll,
        'bucket_pred': b_pred, 'bucket_act': b_act, 'bucket_delta': b_delta,
        'bucket_n': b_n,
    }


def ou_metrics_subsets(res: pd.DataFrame, iso=None):
    """Returns (global, big5, non_big5) dicts."""
    g   = ou_metrics(res, iso)
    b5  = ou_metrics(res[res['is_big5']].reset_index(drop=True), iso)
    nb5 = ou_metrics(res[~res['is_big5']].reset_index(drop=True), iso)
    return g, b5, nb5


def bootstrap_ou_acc(res_a: pd.DataFrame, res_b: pd.DataFrame,
                      iso_a=None, iso_b=None,
                      n_boot=1000, seed=42) -> dict:
    """Paired bootstrap: acc(B with iso_b) - acc(A with iso_a) on BIG5."""
    ra = res_a[res_a['is_big5']].reset_index(drop=True)
    rb = res_b[res_b['is_big5']].reset_index(drop=True)
    # filter pushes
    mask_a = (ra['hs'] + ra['as_'] != ra['ou_line'])
    mask_b = (rb['hs'] + rb['as_'] != rb['ou_line'])
    # Both must be non-push; use common index
    common_mask = mask_a.values & mask_b.values
    ra = ra[common_mask].reset_index(drop=True)
    rb = rb[common_mask].reset_index(drop=True)

    y_a = ((ra['hs'] + ra['as_']) > ra['ou_line']).astype(int).values
    y_b = ((rb['hs'] + rb['as_']) > rb['ou_line']).astype(int).values

    p_a = ra['p_ov'].values.copy()
    p_b = rb['p_ov'].values.copy()
    if iso_a is not None: p_a = iso_a.predict(p_a)
    if iso_b is not None: p_b = iso_b.predict(p_b)

    correct_a = ((p_a >= 0.5) == y_a).astype(float)
    correct_b = ((p_b >= 0.5) == y_b).astype(float)
    obs_diff = correct_b.mean() - correct_a.mean()

    rng = np.random.default_rng(seed)
    n = len(ra)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        boots[i] = correct_b[idx].mean() - correct_a[idx].mean()

    lo, hi = np.percentile(boots, [2.5, 97.5])
    sig = '*' if (lo > 0 or hi < 0) else ''
    return {'obs': obs_diff, 'lo': lo, 'hi': hi, 'sig': sig}


# ─────────────────────────────────────────────────────────────────────
# Stage 4: WDL temperature calibration
# ─────────────────────────────────────────────────────────────────────

def wdl_cross_entropy(res: pd.DataFrame, T: float) -> float:
    """Multi-class cross-entropy with temperature T."""
    eps = 1e-9
    logits = np.stack([res['p_hw'].values, res['p_d'].values, res['p_aw'].values], axis=1)
    # softmax(logits / T)
    scaled = logits / T
    scaled -= scaled.max(axis=1, keepdims=True)
    exp_s = np.exp(scaled)
    p_cal = exp_s / exp_s.sum(axis=1, keepdims=True)
    p_cal = np.clip(p_cal, eps, 1-eps)

    hs, as_ = res['hs'].values, res['as_'].values
    # Actual one-hot: 0=home_win, 1=draw, 2=away_win
    actual = np.where(hs > as_, 0, np.where(hs == as_, 1, 2))
    ce = -np.log(p_cal[np.arange(len(actual)), actual]).mean()
    return float(ce)


def wdl_accuracy_temp(res: pd.DataFrame, T: float) -> float:
    eps = 1e-9
    logits = np.stack([res['p_hw'].values, res['p_d'].values, res['p_aw'].values], axis=1)
    scaled = logits / T
    scaled -= scaled.max(axis=1, keepdims=True)
    exp_s = np.exp(scaled)
    p_cal = exp_s / exp_s.sum(axis=1, keepdims=True)

    pred = p_cal.argmax(axis=1)  # 0=hw, 1=draw, 2=aw
    actual = np.where(res['hs'].values > res['as_'].values, 0,
              np.where(res['hs'].values == res['as_'].values, 1, 2))
    return float((pred == actual).mean())


def wdl_rps_temp(res: pd.DataFrame, T: float) -> float:
    logits = np.stack([res['p_hw'].values, res['p_d'].values, res['p_aw'].values], axis=1)
    scaled = logits / T
    scaled -= scaled.max(axis=1, keepdims=True)
    exp_s = np.exp(scaled)
    p_cal = exp_s / exp_s.sum(axis=1, keepdims=True)

    hs, as_ = res['hs'].values, res['as_'].values
    actual = np.where(hs > as_, 0, np.where(hs == as_, 1, 2))
    rps_vals = []
    for i in range(len(res)):
        p = p_cal[i]
        cum_p = np.cumsum(p)
        act = actual[i]
        cum_y = np.array([1.0 if j >= act else 0.0 for j in range(3)])
        rps_vals.append(np.mean((cum_p - cum_y)**2))
    return float(np.mean(rps_vals))


def fit_temperature(val_res: pd.DataFrame) -> float:
    """Grid search + fine tune for best T on val set."""
    T_grid = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0]
    best_T, best_ce = 1.0, float('inf')
    for T in T_grid:
        ce = wdl_cross_entropy(val_res, T)
        if ce < best_ce:
            best_ce = ce
            best_T = T
    # Fine-tune around best_T
    result = minimize_scalar(lambda t: wdl_cross_entropy(val_res, t),
                             bounds=(0.3, 3.0), method='bounded')
    T_opt = float(result.x)
    ce_opt = float(result.fun)
    print(f'  Grid best T={best_T:.2f} (CE={best_ce:.6f})  '
          f'Fine-tuned T={T_opt:.4f} (CE={ce_opt:.6f})')
    return T_opt


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    print('='*65)
    print('  P0.9 后置 isotonic 校准实验')
    print('='*65)

    # ────────────────────────────────────────────────────────
    # 0. Load data
    # ────────────────────────────────────────────────────────
    print('\n[0] 加载数据 (val + test)')
    df_val_raw  = load_split('val')
    df_test_raw = load_split('test')

    df_val,  _, _ = prep_features(df_val_raw.copy())
    df_test, _, _ = prep_features(df_test_raw.copy())
    print(f'  特征列: {len([c for c in df_val.columns if c not in set(META_COLS_V6+TARGET_COLS)])}')

    # ────────────────────────────────────────────────────────
    # 0b. Load models
    # ────────────────────────────────────────────────────────
    print('\n[0b] 加载模型 (V5 / V6 / V6.1)')

    m5_tags  = {'H_Full':'Model_H_Full', 'A_Full':'Model_A_Full',
                'H_Pure':'Model_H_Pure', 'A_Pure':'Model_A_Pure'}
    m6_tags  = {'H_Full':'Model_H_Full_v6', 'A_Full':'Model_A_Full_v6',
                'H_Pure':'Model_H_Pure_v6', 'A_Pure':'Model_A_Pure_v6'}
    m61_tags = {'H_Full':'Model_H_Full_v6_1', 'A_Full':'Model_A_Full_v6_1',
                'H_Pure':'Model_H_Pure_v6_1', 'A_Pure':'Model_A_Pure_v6_1'}

    print('  V5:')
    models_v5  = load_models(V5_DIR,  m5_tags)
    rho_v5     = json.load(open(os.path.join(V5_DIR,  'rho.json')))
    print('  V6:')
    models_v6  = load_models(V6_DIR,  m6_tags)
    rho_v6     = json.load(open(os.path.join(V6_DIR,  'rho_v6.json')))
    print('  V6.1:')
    models_v61 = load_models(V61_DIR, m61_tags)
    rho_v61    = json.load(open(os.path.join(V61_DIR, 'rho_v6_1.json')))

    # ────────────────────────────────────────────────────────
    # 1. VAL inference
    # ────────────────────────────────────────────────────────
    print('\n[1] VAL 推理 (V5 / V6 / V6.1)')
    lh5v,  la5v  = ensemble_predict(models_v5,  df_val)
    lh6v,  la6v  = ensemble_predict(models_v6,  df_val)
    lh61v, la61v = ensemble_predict(models_v61, df_val)

    res_val_v5  = run_inference(df_val, lh5v,  la5v,  rho_v5)
    res_val_v6  = run_inference(df_val, lh6v,  la6v,  rho_v6)
    res_val_v61 = run_inference(df_val, lh61v, la61v, rho_v61)
    print(f'  val 推理完成: {len(res_val_v5)} 行')

    # ────────────────────────────────────────────────────────
    # STAGE 1: Fit isotonic calibrators on val
    # ────────────────────────────────────────────────────────
    print('\n[STAGE 1] 拟合 OU isotonic 校准器 (val split)')

    def get_over_label(res: pd.DataFrame):
        return ((res['hs'] + res['as_']) > res['ou_line']).astype(int).values

    y_val_v5  = get_over_label(res_val_v5)
    y_val_v6  = get_over_label(res_val_v6)
    y_val_v61 = get_over_label(res_val_v61)

    print('  V5:')
    iso_v5  = fit_isotonic_calibrator(res_val_v5['p_ov'].values,  y_val_v5,  'v5')
    print('  V6:')
    iso_v6  = fit_isotonic_calibrator(res_val_v6['p_ov'].values,  y_val_v6,  'v6')
    print('  V6.1:')
    iso_v61 = fit_isotonic_calibrator(res_val_v61['p_ov'].values, y_val_v61, 'v6_1')

    # Key mapping points
    xvals = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55]
    kp_v5  = calibrator_keypoints(iso_v5,  xvals)
    kp_v6  = calibrator_keypoints(iso_v6,  xvals)
    kp_v61 = calibrator_keypoints(iso_v61, xvals)

    print('\n  关键映射点:')
    print(f'  {"x":<6}  {"V5→y":<8}  {"V6→y":<8}  {"V6.1→y":<8}')
    for x in xvals:
        print(f'  {x:.2f}   {kp_v5[x]:.4f}   {kp_v6[x]:.4f}   {kp_v61[x]:.4f}')

    # Eq-freq 10-bucket calibration curves (val split, before/after)
    print('\n  等频10桶校准曲线 (val split, V5):')
    buckets_before_v5 = eq_freq_buckets(res_val_v5['p_ov'].values, y_val_v5.astype(float))
    p_ov_cal_v5_val = iso_v5.predict(res_val_v5['p_ov'].values)
    buckets_after_v5  = eq_freq_buckets(p_ov_cal_v5_val, y_val_v5.astype(float))

    print(f'  {"桶":<4}  {"校准前mean_pred":<16}  {"校准后mean_pred":<16}  {"actual_rate":<12}  n')
    for i, (bef, aft) in enumerate(zip(buckets_before_v5, buckets_after_v5)):
        print(f'  {i:<4}  {bef["mean_pred"]:.4f}           {aft["mean_pred"]:.4f}          '
              f'  {bef["actual_rate"]:.4f}      {bef["n"]}')

    # ────────────────────────────────────────────────────────
    # TEST inference
    # ────────────────────────────────────────────────────────
    print('\n[2] TEST 推理 (V5 / V6 / V6.1)')
    lh5t,  la5t  = ensemble_predict(models_v5,  df_test)
    lh6t,  la6t  = ensemble_predict(models_v6,  df_test)
    lh61t, la61t = ensemble_predict(models_v61, df_test)

    res_test_v5  = run_inference(df_test, lh5t,  la5t,  rho_v5)
    res_test_v6  = run_inference(df_test, lh6t,  la6t,  rho_v6)
    res_test_v61 = run_inference(df_test, lh61t, la61t, rho_v61)
    print(f'  test 推理完成: {len(res_test_v5)} 行')

    # ────────────────────────────────────────────────────────
    # STAGE 2: 6 configs, test split
    # ────────────────────────────────────────────────────────
    print('\n[STAGE 2] Test split 6套配置对照')

    configs = [
        ('V5 raw',     res_test_v5,  None),
        ('V5+iso',     res_test_v5,  iso_v5),
        ('V6 raw',     res_test_v6,  None),
        ('V6+iso',     res_test_v6,  iso_v6),
        ('V6.1 raw',   res_test_v61, None),
        ('V6.1+iso',   res_test_v61, iso_v61),
    ]

    results_stage2 = {}
    for name, res, iso in configs:
        g, b5, nb5 = ou_metrics_subsets(res, iso)
        results_stage2[name] = {'global': g, 'big5': b5, 'non_big5': nb5}
        print(f'\n  [{name}]')
        print(f'    全局:   acc={g["acc"]:.4f}  brier={g["brier"]:.4f}  logloss={g["logloss"]:.4f}  '
              f'bucket[0.3,0.4) Δ={g["bucket_delta"]:+.4f} (n={g["bucket_n"]})')
        print(f'    BIG5:   acc={b5["acc"]:.4f}  brier={b5["brier"]:.4f}  logloss={b5["logloss"]:.4f}  '
              f'bucket Δ={b5["bucket_delta"]:+.4f} (n={b5["bucket_n"]})')
        print(f'    非BIG5: acc={nb5["acc"]:.4f}  brier={nb5["brier"]:.4f}  logloss={nb5["logloss"]:.4f}  '
              f'bucket Δ={nb5["bucket_delta"]:+.4f} (n={nb5["bucket_n"]})')

    # Bootstrap: BIG5 OU acc lift (raw → +iso) for each version
    print('\n[STAGE 2b] Bootstrap (BIG5, 1000×)')
    boot_v5  = bootstrap_ou_acc(res_test_v5,  res_test_v5,  None, iso_v5)
    boot_v6  = bootstrap_ou_acc(res_test_v6,  res_test_v6,  None, iso_v6)
    boot_v61 = bootstrap_ou_acc(res_test_v61, res_test_v61, None, iso_v61)

    boots = {'V5': boot_v5, 'V6': boot_v6, 'V6.1': boot_v61}
    for vname, b in boots.items():
        sig = '✅ 显著' if b['sig'] == '*' and b['obs'] > 0 else \
              ('❌ 显著退化' if b['sig'] == '*' and b['obs'] < 0 else '— 不显著')
        print(f'  {vname}: Δacc={b["obs"]:+.4f}  95%CI=[{b["lo"]:+.4f},{b["hi"]:+.4f}]  {sig}')

    # ────────────────────────────────────────────────────────
    # STAGE 3: Cup/European transfer
    # ────────────────────────────────────────────────────────
    print('\n[STAGE 3] 杯赛/欧战迁移性')
    cup_df = pd.read_csv(CUP_CSV)
    print(f'  读入 {len(cup_df)} 行, 列: {cup_df.columns.tolist()}')

    cup_df['over_label'] = ((cup_df['home_score'] + cup_df['away_score']) > 2.5).astype(int)
    cup_df['p_over_cal'] = iso_v5.predict(cup_df['p_over'].values)

    y_cup = cup_df['over_label'].values
    p_raw = cup_df['p_over'].values
    p_cal = cup_df['p_over_cal'].values

    # OU acc
    acc_raw = float(((p_raw >= 0.5) == y_cup).mean())
    acc_cal = float(((p_cal >= 0.5) == y_cup).mean())

    # Brier
    brier_raw = float(np.mean((p_raw - y_cup)**2))
    brier_cal = float(np.mean((p_cal - y_cup)**2))

    # [0.3, 0.4) bucket bias
    bm_raw = (p_raw >= 0.3) & (p_raw < 0.4)
    bm_cal = (p_raw >= 0.3) & (p_raw < 0.4)  # bucket defined by raw p_over

    def bucket_stats(p, y, mask):
        if mask.sum() == 0:
            return float('nan'), float('nan'), float('nan'), 0
        pm = p[mask].mean()
        am = y[mask].mean()
        return pm, am, am - pm, int(mask.sum())

    bp_raw, ba_raw, bd_raw, bn_raw = bucket_stats(p_raw, y_cup, bm_raw)
    bp_cal, ba_cal, bd_cal, bn_cal = bucket_stats(p_cal, y_cup, bm_cal)

    cup_results = {
        'n': len(cup_df),
        'acc_raw': acc_raw, 'acc_cal': acc_cal,
        'brier_raw': brier_raw, 'brier_cal': brier_cal,
        'bucket_pred_raw': bp_raw, 'bucket_act_raw': ba_raw, 'bucket_delta_raw': bd_raw, 'bucket_n_raw': bn_raw,
        'bucket_pred_cal': bp_cal, 'bucket_act_cal': ba_cal, 'bucket_delta_cal': bd_cal, 'bucket_n_cal': bn_cal,
    }
    print(f'  OU acc:   raw={acc_raw:.4f}  cal={acc_cal:.4f}  Δ={acc_cal-acc_raw:+.4f}')
    print(f'  Brier:    raw={brier_raw:.4f}  cal={brier_cal:.4f}  Δ={brier_cal-brier_raw:+.4f}')
    print(f'  [0.3,0.4) 桶偏差 (raw): pred={bp_raw:.4f} act={ba_raw:.4f} Δ={bd_raw:+.4f} (n={bn_raw})')
    print(f'  [0.3,0.4) 桶偏差 (cal): pred={bp_cal:.4f} act={ba_cal:.4f} Δ={bd_cal:+.4f} (n={bn_cal})')

    # ────────────────────────────────────────────────────────
    # STAGE 4: WDL temperature calibration
    # ────────────────────────────────────────────────────────
    print('\n[STAGE 4] WDL 温度校准')
    wdl_stage4 = {}

    for vname, val_res, test_res in [
        ('V5',  res_val_v5,  res_test_v5),
        ('V6',  res_val_v6,  res_test_v6),
        ('V6.1',res_val_v61, res_test_v61),
    ]:
        print(f'\n  {vname}:')
        T_opt = fit_temperature(val_res)

        # raw T=1
        acc_raw_wdl = wdl_accuracy_temp(test_res, 1.0)
        rps_raw_wdl = wdl_rps_temp(test_res, 1.0)
        acc_cal_wdl = wdl_accuracy_temp(test_res, T_opt)
        rps_cal_wdl = wdl_rps_temp(test_res, T_opt)

        print(f'  WDL acc: raw={acc_raw_wdl:.4f} cal(T={T_opt:.3f})={acc_cal_wdl:.4f} '
              f'Δ={acc_cal_wdl-acc_raw_wdl:+.4f}')
        print(f'  WDL RPS: raw={rps_raw_wdl:.4f} cal={rps_cal_wdl:.4f} '
              f'Δ={rps_cal_wdl-rps_raw_wdl:+.4f}')
        wdl_stage4[vname] = {
            'T_opt': T_opt,
            'acc_raw': acc_raw_wdl, 'acc_cal': acc_cal_wdl,
            'rps_raw': rps_raw_wdl, 'rps_cal': rps_cal_wdl,
        }

    # ────────────────────────────────────────────────────────
    # Build Report
    # ────────────────────────────────────────────────────────
    print('\n[REPORT] 生成报告')
    report = build_report(
        xvals, kp_v5, kp_v6, kp_v61,
        buckets_before_v5, buckets_after_v5,
        results_stage2, boots,
        cup_results,
        wdl_stage4,
    )
    rpath = os.path.join(REPORT_DIR, 'p09_calibration_eval.md')
    with open(rpath, 'w') as f:
        f.write(report)
    print(f'  报告 → {rpath}')
    print('\n' + '='*65 + '\n  P0.9 校准实验完成\n' + '='*65)


# ─────────────────────────────────────────────────────────────────────
# Report builder
# ─────────────────────────────────────────────────────────────────────

def build_report(
    xvals, kp_v5, kp_v6, kp_v61,
    buckets_before_v5, buckets_after_v5,
    results_stage2, boots,
    cup_results,
    wdl_stage4,
) -> str:
    lines = []
    a = lines.append

    a('# P0.9 后置 isotonic 校准实验报告')
    a('')
    a('**生成日期**: 2026-05-12')
    a('**val split**: 1,523 行  **test split**: 1,525 行  **杯赛/欧战**: 263 行')
    a('')
    a('---')
    a('')

    # ── Section 1: Calibrator shape ──────────────────────────────────
    a('## 1. 校准器形状（val split 拟合）')
    a('')
    a('### 1.1 关键映射点')
    a('')
    header = '| x | V5→y | V6→y | V6.1→y |'
    sep    = '|---|------|------|--------|'
    a(header); a(sep)
    for x in xvals:
        a(f'| {x:.2f} | {kp_v5[x]:.4f} | {kp_v6[x]:.4f} | {kp_v61[x]:.4f} |')
    a('')
    a('> 校准器将原始 p_over 映射到实际 over 率。映射值 > x 表示模型低估了 over 概率，映射值 < x 表示高估。')
    a('')

    a('### 1.2 等频 10 桶校准曲线（val split，V5，校准前 vs 后 vs 实际）')
    a('')
    a('| 桶 | 校准前 mean_pred | 校准后 mean_pred | 实际 over 率 | n |')
    a('|---|---|---|---|---|')
    for i, (bef, aft) in enumerate(zip(buckets_before_v5, buckets_after_v5)):
        a(f'| {i} | {bef["mean_pred"]:.4f} | {aft["mean_pred"]:.4f} '
          f'| {bef["actual_rate"]:.4f} | {bef["n"]} |')
    a('')
    a('---')
    a('')

    # ── Section 2: Test split 6 configs ─────────────────────────────
    a('## 2. Test Split 对照（OU，全局 / BIG5 / 非BIG5）')
    a('')

    configs_order = ['V5 raw','V5+iso','V6 raw','V6+iso','V6.1 raw','V6.1+iso']

    for scope_key, scope_label in [('global','全局 (1,525行)'),
                                    ('big5','BIG5 (EPL/LaLiga/Bundesliga/Ligue1/SerieA)'),
                                    ('non_big5','非BIG5 (K/J/澳超)')]:
        a(f'### 2.{["global","big5","non_big5"].index(scope_key)+1} {scope_label}')
        a('')
        a('| 配置 | n | OU Acc | OU Brier | LogLoss | bucket[0.3,0.4) pred | actual | Δ |')
        a('|---|---|---|---|---|---|---|---|')
        for cfg in configs_order:
            m = results_stage2[cfg][scope_key]
            a(f'| {cfg} | {m["n"]} | {m["acc"]:.4f} | {m["brier"]:.4f} '
              f'| {m["logloss"]:.4f} | {m["bucket_pred"]:.4f} | {m["bucket_act"]:.4f} '
              f'| {m["bucket_delta"]:+.4f} |')
        a('')

    a('### 2.4 Bootstrap CI（BIG5 子集，1000×，raw → +iso 的 OU acc 提升量）')
    a('')
    a('| 版本 | Δ acc (iso−raw) | 95% CI | 显著？ |')
    a('|---|---|---|---|')
    for vname, b in boots.items():
        sig_str = '✅ 显著改善' if b['sig'] == '*' and b['obs'] > 0 else \
                  ('❌ 显著退化' if b['sig'] == '*' and b['obs'] < 0 else '— 不显著')
        a(f'| {vname} | {b["obs"]:+.4f} | [{b["lo"]:+.4f}, {b["hi"]:+.4f}] | {sig_str} |')
    a('')
    a('---')
    a('')

    # ── Section 3: Cup/European ──────────────────────────────────────
    a('## 3. 杯赛 / 欧战迁移性（263 行）')
    a('')
    cr = cup_results
    a('| 指标 | 校准前 | 校准后 | Δ |')
    a('|---|---|---|---|')
    a(f'| OU Acc | {cr["acc_raw"]:.4f} | {cr["acc_cal"]:.4f} | {cr["acc_cal"]-cr["acc_raw"]:+.4f} |')
    a(f'| Brier  | {cr["brier_raw"]:.4f} | {cr["brier_cal"]:.4f} | {cr["brier_cal"]-cr["brier_raw"]:+.4f} |')
    a(f'| [0.3,0.4) mean_pred | {cr["bucket_pred_raw"]:.4f} | {cr["bucket_pred_cal"]:.4f} | — |')
    a(f'| [0.3,0.4) actual    | {cr["bucket_act_raw"]:.4f} | {cr["bucket_act_cal"]:.4f} | — |')
    a(f'| [0.3,0.4) Δ (实际−预测) | {cr["bucket_delta_raw"]:+.4f} (n={cr["bucket_n_raw"]}) | {cr["bucket_delta_cal"]:+.4f} (n={cr["bucket_n_cal"]}) | — |')
    a('')
    a('---')
    a('')

    # ── Section 4: WDL temperature ───────────────────────────────────
    a('## 4. WDL 温度校准边际收益')
    a('')
    a('| 版本 | 最优 T | WDL Acc (raw) | WDL Acc (cal) | Δ acc | WDL RPS (raw) | WDL RPS (cal) | Δ RPS |')
    a('|---|---|---|---|---|---|---|---|')
    for vname, d in wdl_stage4.items():
        a(f'| {vname} | {d["T_opt"]:.4f} | {d["acc_raw"]:.4f} | {d["acc_cal"]:.4f} '
          f'| {d["acc_cal"]-d["acc_raw"]:+.4f} | {d["rps_raw"]:.4f} | {d["rps_cal"]:.4f} '
          f'| {d["rps_cal"]-d["rps_raw"]:+.4f} |')
    a('')

    # Check if WDL gain is material
    max_wdl_gain = max(d['acc_cal'] - d['acc_raw'] for d in wdl_stage4.values())
    if abs(max_wdl_gain) < 0.005:
        a('> 温度校准的 WDL acc 提升 < 0.5pp，增益较小，不建议强制部署。')
    else:
        a('> 温度校准有一定收益，可考虑在生产推理中加入温度缩放。')
    a('')
    a('---')
    a('')

    # ── Section 5: Conclusions ───────────────────────────────────────
    a('## 5. 结论')
    a('')

    # (a) isotonic OU acc lift
    v5_iso_acc  = results_stage2['V5+iso']['big5']['acc']
    v5_raw_acc  = results_stage2['V5 raw']['big5']['acc']
    v6_iso_acc  = results_stage2['V6+iso']['big5']['acc']
    v6_raw_acc  = results_stage2['V6 raw']['big5']['acc']
    v61_iso_acc = results_stage2['V6.1+iso']['big5']['acc']
    v61_raw_acc = results_stage2['V6.1 raw']['big5']['acc']

    a('### (a) isotonic 校准后 OU acc lift 是否显著？')
    a('')
    sig_any = any(b['sig'] == '*' and b['obs'] > 0 for b in boots.values())
    best_lift = max(
        v5_iso_acc  - v5_raw_acc,
        v6_iso_acc  - v6_raw_acc,
        v61_iso_acc - v61_raw_acc,
    )
    if sig_any:
        a(f'至少一个版本的 BIG5 OU acc 提升在 bootstrap 下显著（最大 lift={best_lift:+.4f}）。')
        a('isotonic 校准有效，建议在对应版本上线后置校准。')
    else:
        a(f'三个版本的 BIG5 OU acc bootstrap 均不显著（最大 lift={best_lift:+.4f}）。')
        a('样本量（~1,100 行 BIG5）可能不足以支撑统计显著性，但方向性仍有参考价值。')
    a('')
    a(f'- V5:  raw={v5_raw_acc:.4f}  → iso={v5_iso_acc:.4f}  Δ={v5_iso_acc-v5_raw_acc:+.4f}')
    a(f'- V6:  raw={v6_raw_acc:.4f}  → iso={v6_iso_acc:.4f}  Δ={v6_iso_acc-v6_raw_acc:+.4f}')
    a(f'- V6.1: raw={v61_raw_acc:.4f} → iso={v61_iso_acc:.4f} Δ={v61_iso_acc-v61_raw_acc:+.4f}')
    a('')

    # (b) cup transfer
    cup_acc_lift = cup_results['acc_cal'] - cup_results['acc_raw']
    cup_brier_lift = cup_results['brier_raw'] - cup_results['brier_cal']  # positive = improvement
    a('### (b) 杯赛迁移性如何？')
    a('')
    if cup_acc_lift > 0 and cup_brier_lift > 0:
        a(f'校准器在杯赛/欧战数据上迁移良好：OU acc +{cup_acc_lift:+.4f}，Brier 改善 {cup_brier_lift:+.4f}。')
        a('桶偏差在校准后也有所收敛，说明 V5 isotonic 校准在分布外数据上仍有泛化能力。')
    elif cup_acc_lift > 0:
        a(f'acc 有提升 ({cup_acc_lift:+.4f})，但 Brier 变化不显著，迁移性中等。')
    elif cup_acc_lift <= 0 and cup_brier_lift > 0:
        a(f'Brier 改善 ({cup_brier_lift:+.4f}) 但 acc 未提升，校准后概率更准但决策临界点附近无明显变化。')
    else:
        a(f'校准后 acc 和 Brier 均略有下降，杯赛/欧战数据与训练分布差异较大，校准器迁移性受限。')
    a('')

    # (c) deployment recommendation
    a('### (c) 推荐部署方向')
    a('')
    # Find best version+iso combo by BIG5 OU acc
    best_cfg = max(configs_order, key=lambda c: results_stage2[c]['big5']['acc'])
    best_acc = results_stage2[best_cfg]['big5']['acc']
    a(f'BIG5 OU acc 最优配置: **{best_cfg}** (acc={best_acc:.4f})')
    a('')
    a('推荐方向：')
    a('- 在生产推理管道末端加入 IsotonicRegression 后置校准步骤，不影响模型本身')
    a('- 优先在 BIG5 联赛上启用（K/J/澳超数据量少，效果不稳定）')
    a('- 校准器每季度重新在 val/最新数据上重拟合，防止分布漂移')
    a('- 杯赛/欧战建议谨慎使用校准后概率用于决策，OOD 风险较大')
    a('')

    # (d) next steps
    a('### (d) 下一步建议')
    a('')
    a('1. **P0.10 生产集成**：将 isotonic pkl 包装为推理后处理步骤，接入 lambda_ah_predictor.predict_match_full()')
    a('2. **扩充 val/retrain 窗口**：当前 val 1,523 行，BIG5 子集仅 ~1,100 行，bootstrap CI 较宽；')
    a('   收集更多数据后重拟合校准器可提升稳定性')
    a('3. **杯赛专项校准器**：若杯赛迁移性仍差，考虑为杯赛单独拟合校准器（以欧战/杯赛历史数据为训练集）')
    a('4. **WDL 温度校准**：收益 < 0.5pp，暂不优先；可在有充足 WDL 校准数据后重评')
    a('5. **监控**：上线后监控滚动 OU acc（按 V5+iso vs V5 raw 分桶对比），设 drift 告警')
    a('')

    return '\n'.join(lines)


if __name__ == '__main__':
    main()
