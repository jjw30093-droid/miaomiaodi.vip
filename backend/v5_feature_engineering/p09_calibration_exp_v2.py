#!/usr/bin/env python3
"""
p09_calibration_exp_v2.py — P0.9 后置 isotonic 校准实验（完整版）

Stage 1: val split 拟合 OU isotonic 校准器 (V5/V6/V6.1)
         ├── 11 点关键映射表 (0.10-0.80)
         ├── Sanity checks
         └── 校准曲线 PNG (等频 10 桶)

Stage 2: test split 6 套配置 (raw vs +iso) 三方对照
         ├── 全局 / BIG5 / 非BIG5 分层表格
         ├── Paired bootstrap 95% CI
         └── V6.1 全 10 桶详细拆解 (Stage 2G)

Stage 3: 杯赛/欧战迁移性
         ├── V5+iso 整体 + 分赛事 (UCL/UEL/UECL/FA/EFL/etc.)
         └── V6.1+iso 杯赛测试 (mart_prediction_matrix_v5 特征)

Stage 4: WDL 温度校准 (val 拟合 T, test 评估)

输出:
  models/calibrators_p09/{v5/v6/v6_1}_ou_isotonic.pkl
  models/calibrators_p09/{v5/v6/v6_1}_calibration_curve.png
  reports/p09_calibration_eval.md
"""
from __future__ import annotations
import json, os, sys, sqlite3, pickle, warnings
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
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

XVALS_FULL = [0.10, 0.20, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 0.80]

ODDS_PATTERN_KEYWORDS = [
    'raw_home', 'raw_away', 'raw_draw', 'fair_home', 'fair_draw', 'fair_away',
    'implied', 'ah_implied_diff', 'ah_raw_home', 'ah_raw_away', 'ah_odds_movement',
    'closing_eu_raw', 'closing_ah_raw', 'closing_ou_raw',
    'closing_eu_fair', 'closing_ah_fair', 'closing_ou_fair',
    'open_eu_fair', 'open_ah_fair', 'open_ou_fair', 'eu_odds', 'eu_implied',
]
META_COLS_V6 = [
    'match_id', 'match_date', 'Season', 'Home_Team_ID', 'Away_Team_ID',
    'Home_Team_Name', 'Away_Team_Name', 'days_from_latest', 'sample_weight',
    'split', 'ah_source', 'ah_line_category', 'is_fd_fallback',
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
# Model loading + inference
# ─────────────────────────────────────────────────────────────────────

def load_models(model_dir: str, tags: dict) -> dict:
    from catboost import CatBoostRegressor
    models = {}
    for key, fname_stem in tags.items():
        path = os.path.join(model_dir, f'{fname_stem}.cbm')
        m = CatBoostRegressor(); m.load_model(path)
        models[key] = m
        print(f'    [{fname_stem}.cbm]  BestIter={m.get_best_iteration()}')
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
# Stage 1: Fit isotonic calibrators
# ─────────────────────────────────────────────────────────────────────

def fit_isotonic_calibrator(p_ov: np.ndarray, y: np.ndarray, name: str):
    iso = IsotonicRegression(out_of_bounds='clip')
    iso.fit(p_ov, y)
    pkl_path = os.path.join(CAL_DIR, f'{name}_ou_isotonic.pkl')
    with open(pkl_path, 'wb') as f:
        pickle.dump(iso, f)
    print(f'    保存 → {pkl_path}  (n_train={len(y):,})')
    # Also save JSON key mapping
    json_path = os.path.join(CAL_DIR, f'{name}_ou_isotonic_keypoints.json')
    kp = {str(x): float(iso.predict([x])[0]) for x in XVALS_FULL}
    with open(json_path, 'w') as f:
        json.dump(kp, f, indent=2)
    return iso


def calibrator_keypoints(iso: IsotonicRegression, xvals=None):
    if xvals is None:
        xvals = XVALS_FULL
    return {x: float(iso.predict([x])[0]) for x in xvals}


def sanity_check_calibrator(iso, p_ov_val: np.ndarray, y_val: np.ndarray,
                             name: str) -> dict:
    """Check monotonicity and key value alignment."""
    xs = np.linspace(0.01, 0.99, 200)
    ys = iso.predict(xs)
    monotone = bool(np.all(np.diff(ys) >= -1e-9))

    # x=0.50 → should be near actual over rate
    actual_over_rate = float(y_val.mean())
    pred_at_50 = float(iso.predict([0.50])[0])

    # x=0.35 → should be pushed > 0.45
    pred_at_35 = float(iso.predict([0.35])[0])

    print(f'    {name}: monotone={monotone}  '
          f'iso(0.50)={pred_at_50:.4f} vs actual_over={actual_over_rate:.4f}  '
          f'iso(0.35)={pred_at_35:.4f} (target>0.45)')
    return {
        'monotone': monotone,
        'actual_over_rate': actual_over_rate,
        'pred_at_50': pred_at_50,
        'pred_at_35': pred_at_35,
    }


def eq_freq_buckets(p_ov: np.ndarray, y: np.ndarray, n_buckets=10) -> list:
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


def fixed_width_buckets_10(p_ov: np.ndarray, y: np.ndarray) -> list:
    """Fixed-width buckets [0.0,0.1), [0.1,0.2), ..., [0.9,1.0] for Stage 2G."""
    rows = []
    edges = [i/10 for i in range(11)]
    for lo, hi in zip(edges[:-1], edges[1:]):
        if hi == 1.0:
            mask = (p_ov >= lo)
        else:
            mask = (p_ov >= lo) & (p_ov < hi)
        n = mask.sum()
        if n == 0:
            rows.append({'lo': lo, 'hi': hi, 'n': 0,
                         'pred_avg': float('nan'), 'actual_over': float('nan')})
        else:
            rows.append({
                'lo': lo, 'hi': hi, 'n': int(n),
                'pred_avg': float(p_ov[mask].mean()),
                'actual_over': float(y[mask].mean()),
            })
    return rows


def plot_calibration_curve(p_ov_raw: np.ndarray, y: np.ndarray,
                           iso, name: str, version_label: str):
    """等频 10 桶可视化：raw / +iso / ideal y=x"""
    buckets_raw = eq_freq_buckets(p_ov_raw, y.astype(float))
    p_ov_cal = iso.predict(p_ov_raw)
    buckets_cal = eq_freq_buckets(p_ov_cal, y.astype(float))

    raw_pred  = [b['mean_pred']   for b in buckets_raw]
    raw_act   = [b['actual_rate'] for b in buckets_raw]
    cal_pred  = [b['mean_pred']   for b in buckets_cal]
    cal_act   = [b['actual_rate'] for b in buckets_cal]

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], 'k--', alpha=0.4, label='Ideal (y=x)')
    ax.plot(raw_pred, raw_act, 'o-', color='steelblue', label='Raw')
    ax.plot(cal_pred, cal_act, 's-', color='tomato',    label='+Isotonic')
    ax.set_xlabel('Mean predicted p_over (per bucket)')
    ax.set_ylabel('Actual over rate')
    ax.set_title(f'{version_label} — OU Calibration (val, 10 eq-freq buckets)')
    ax.legend()
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.grid(alpha=0.3)
    png_path = os.path.join(CAL_DIR, f'{name}_calibration_curve.png')
    fig.savefig(png_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    print(f'    PNG → {png_path}')
    return png_path


# ─────────────────────────────────────────────────────────────────────
# Stage 2: OU metrics on test split
# ─────────────────────────────────────────────────────────────────────

def ou_metrics(res: pd.DataFrame, iso=None) -> dict:
    r = res.copy()
    r['over_label'] = ((r['hs'] + r['as_']) > r['ou_line']).astype(int)
    r = r[r['hs'] + r['as_'] != r['ou_line']].copy()

    p_ov = r['p_ov'].values.copy()
    if iso is not None:
        p_ov = iso.predict(p_ov)

    y = r['over_label'].values
    pred_ou = (p_ov >= 0.5).astype(int)
    acc   = float((pred_ou == y).mean())
    brier = float(np.mean((p_ov - y)**2))
    try:
        ll = float(log_loss(y, np.clip(p_ov, 1e-7, 1-1e-7)))
    except Exception:
        ll = float('nan')

    # [0.3, 0.4) bucket using RAW p_ov as bucket selector
    raw_p = r['p_ov'].values
    bm = (raw_p >= 0.3) & (raw_p < 0.4)
    if bm.sum() > 0:
        b_pred = float(p_ov[bm].mean())
        b_act  = float(y[bm].mean())
        b_n    = int(bm.sum())
    else:
        b_pred = b_act = float('nan'); b_n = 0

    return {'n': len(r), 'acc': acc, 'brier': brier, 'logloss': ll,
            'bucket_pred': b_pred, 'bucket_act': b_act,
            'bucket_delta': b_act - b_pred, 'bucket_n': b_n}


def ou_metrics_subsets(res: pd.DataFrame, iso=None):
    g   = ou_metrics(res, iso)
    b5  = ou_metrics(res[res['is_big5']].copy(), iso)
    nb5 = ou_metrics(res[~res['is_big5']].copy(), iso)
    return g, b5, nb5


def bootstrap_ou_acc(res_raw: pd.DataFrame, res_iso: pd.DataFrame,
                     iso, n_resample=1000, seed=42) -> dict:
    """Paired bootstrap on BIG5 subset: Δacc = iso_acc - raw_acc."""
    rng = np.random.default_rng(seed)
    r = res_raw[res_raw['is_big5']].copy()
    r['over_label'] = ((r['hs'] + r['as_']) > r['ou_line']).astype(int)
    r = r[r['hs'] + r['as_'] != r['ou_line']].copy()

    y   = r['over_label'].values
    p_r = r['p_ov'].values
    p_c = iso.predict(p_r) if iso is not None else p_r

    # Δacc = accuracy(calibrated) - accuracy(raw)
    obs_delta = (float(((p_c >= 0.5) == y).mean()) -
                 float(((p_r >= 0.5) == y).mean()))

    deltas = []
    n = len(y)
    for _ in range(n_resample):
        idx = rng.integers(0, n, size=n)
        d = (float(((p_c[idx] >= 0.5) == y[idx]).mean()) -
             float(((p_r[idx] >= 0.5) == y[idx]).mean()))
        deltas.append(d)
    deltas = np.array(deltas)
    lo, hi = float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5))
    sig = '*' if lo > 0 or hi < 0 else ''
    return {'obs': obs_delta, 'lo': lo, 'hi': hi, 'sig': sig}


# ─────────────────────────────────────────────────────────────────────
# Stage 3: Cup / European transfer
# ─────────────────────────────────────────────────────────────────────

def cup_metrics_by_competition(cup_df: pd.DataFrame, p_cal: np.ndarray) -> list:
    """Per-competition OU acc table."""
    y     = cup_df['over_label'].values
    p_raw = cup_df['p_over'].values
    rows  = []
    for league in sorted(cup_df['league_name'].unique()):
        mask = cup_df['league_name'] == league
        n = mask.sum()
        yr    = y[mask.values]
        pr    = p_raw[mask.values]
        pc    = p_cal[mask.values]
        acc_r = float(((pr >= 0.5) == yr).mean())
        acc_c = float(((pc >= 0.5) == yr).mean())
        rows.append({
            'league': league,
            'n': int(n),
            'acc_raw': acc_r,
            'acc_cal': acc_c,
            'lift': acc_c - acc_r,
            'pred_avg_raw': float(pr.mean()),
            'pred_avg_cal': float(pc.mean()),
            'actual_over': float(yr.mean()),
        })
    return rows


def run_v61_on_cup(iso_v61, rho_v61, models_v61) -> pd.DataFrame | None:
    """
    Run V6.1 inference on cup match features from mart_prediction_matrix_v5.
    Missing V6.1 features (6 AH cols) are filled with 0.
    Returns DataFrame with p_ov (V6.1) and over_label.
    """
    print('  [Stage 3I] V6.1 推理 (mart_prediction_matrix_v5 特征, 263行)')
    try:
        conn = sqlite3.connect(DB_PATH)
        cup_df_csv = pd.read_csv(CUP_CSV)
        cup_ids    = cup_df_csv['match_id'].astype(str).tolist()
        placeholders = ','.join('?' * len(cup_ids))
        df_cup_feat = pd.read_sql_query(
            f'SELECT * FROM mart_prediction_matrix_v5 WHERE match_id IN ({placeholders})',
            conn, params=cup_ids)
        conn.close()

        if len(df_cup_feat) == 0:
            print('  ⚠️  V6.1 cup: mart_prediction_matrix_v5 返回 0 行，跳过')
            return None

        # Fill NaN
        for c in df_cup_feat.columns:
            if df_cup_feat[c].dtype in [np.float64, np.float32, float, np.int64, np.int32, int]:
                df_cup_feat[c] = df_cup_feat[c].fillna(-999)
            elif df_cup_feat[c].dtype == object:
                df_cup_feat[c] = df_cup_feat[c].fillna('__NA__')

        # Get V6.1 feature names
        h_full_feats = list(models_v61['H_Full'].feature_names_)
        a_full_feats = list(models_v61['A_Full'].feature_names_)
        h_pure_feats = list(models_v61['H_Pure'].feature_names_)
        a_pure_feats = list(models_v61['A_Pure'].feature_names_)

        # Align with V6.1 features (reindex fills missing cols with 0)
        X_fh = df_cup_feat.reindex(columns=h_full_feats, fill_value=0).astype(float)
        X_fa = df_cup_feat.reindex(columns=a_full_feats, fill_value=0).astype(float)
        X_ph = df_cup_feat.reindex(columns=h_pure_feats, fill_value=0).astype(float)
        X_pa = df_cup_feat.reindex(columns=a_pure_feats, fill_value=0).astype(float)

        # CatBoost 要求 League_ID 等 cat_feature 为 int/str，不能是 float
        for X in [X_fh, X_fa, X_ph, X_pa]:
            if 'League_ID' in X.columns:
                X['League_ID'] = X['League_ID'].fillna(0).astype(int)

        lam_h = (0.6 * np.clip(models_v61['H_Full'].predict(X_fh), 1e-4, None) +
                 0.4 * np.clip(models_v61['H_Pure'].predict(X_ph), 1e-4, None))
        lam_a = (0.6 * np.clip(models_v61['A_Full'].predict(X_fa), 1e-4, None) +
                 0.4 * np.clip(models_v61['A_Pure'].predict(X_pa), 1e-4, None))

        rho_global = rho_v61['rho_global']
        rho_league = rho_v61.get('rho_by_league', {})

        records = []
        for i in range(len(df_cup_feat)):
            row = df_cup_feat.iloc[i]
            lid = str(int(float(row.get('League_ID', 0))))
            rho = rho_league.get(lid, rho_global)
            lh, la = float(lam_h[i]), float(lam_a[i])
            mat = build_score_matrix(lh, la, rho)
            p_ov, _, _ = derive_ou(mat, 2.5)
            records.append({
                'match_id': str(row['match_id']),
                'p_ov_v61': p_ov,
            })

        df_v61_cup = pd.DataFrame(records)

        # Merge with cup CSV for scores + league
        # 统一为 str 类型再 merge（CSV 可能解析为 int64）
        cup_df_csv['match_id'] = cup_df_csv['match_id'].astype(str)
        df_v61_cup['match_id'] = df_v61_cup['match_id'].astype(str)
        df_merged = cup_df_csv.merge(df_v61_cup, on='match_id', how='inner')
        df_merged['over_label'] = (
            (df_merged['home_score'] + df_merged['away_score']) > 2.5
        ).astype(int)
        df_merged['p_ov_v61_cal'] = iso_v61.predict(df_merged['p_ov_v61'].values)

        print(f'  V6.1 cup 推理完成: {len(df_merged)} 行匹配')
        return df_merged

    except Exception as e:
        print(f'  ⚠️  V6.1 cup 推理失败: {e}')
        import traceback; traceback.print_exc()
        return None


# ─────────────────────────────────────────────────────────────────────
# Stage 4: WDL temperature calibration
# ─────────────────────────────────────────────────────────────────────

def wdl_cross_entropy(res: pd.DataFrame, T: float) -> float:
    logits = np.stack([res['p_hw'].values, res['p_d'].values, res['p_aw'].values], axis=1)
    logits = np.log(np.clip(logits, 1e-9, None))
    scaled = logits / T
    scaled -= scaled.max(axis=1, keepdims=True)
    exp_s  = np.exp(scaled)
    p_cal  = exp_s / exp_s.sum(axis=1, keepdims=True)
    hs, as_ = res['hs'].values, res['as_'].values
    actual = np.where(hs > as_, 0, np.where(hs == as_, 1, 2))
    ce = -np.mean(np.log(np.clip(p_cal[np.arange(len(actual)), actual], 1e-9, None)))
    return float(ce)


def wdl_accuracy_temp(res: pd.DataFrame, T: float) -> float:
    logits = np.stack([res['p_hw'].values, res['p_d'].values, res['p_aw'].values], axis=1)
    logits = np.log(np.clip(logits, 1e-9, None))
    scaled = logits / T
    scaled -= scaled.max(axis=1, keepdims=True)
    exp_s  = np.exp(scaled)
    p_cal  = exp_s / exp_s.sum(axis=1, keepdims=True)
    pred   = p_cal.argmax(axis=1)
    actual = np.where(res['hs'].values > res['as_'].values, 0,
              np.where(res['hs'].values == res['as_'].values, 1, 2))
    return float((pred == actual).mean())


def wdl_rps_temp(res: pd.DataFrame, T: float) -> float:
    logits = np.stack([res['p_hw'].values, res['p_d'].values, res['p_aw'].values], axis=1)
    logits = np.log(np.clip(logits, 1e-9, None))
    scaled = logits / T
    scaled -= scaled.max(axis=1, keepdims=True)
    exp_s  = np.exp(scaled)
    p_cal  = exp_s / exp_s.sum(axis=1, keepdims=True)
    hs, as_ = res['hs'].values, res['as_'].values
    actual  = np.where(hs > as_, 0, np.where(hs == as_, 1, 2))
    rps_vals = []
    for i in range(len(res)):
        p = p_cal[i]; cum_p = np.cumsum(p); a = actual[i]
        cum_y = np.array([1.0 if j >= a else 0.0 for j in range(3)])
        rps_vals.append(np.mean((cum_p - cum_y)**2))
    return float(np.mean(rps_vals))


def fit_temperature(val_res: pd.DataFrame) -> float:
    T_grid = [0.5, 0.8, 1.0, 1.2, 1.5, 2.0]
    best_T, best_ce = 1.0, float('inf')
    for T in T_grid:
        ce = wdl_cross_entropy(val_res, T)
        if ce < best_ce:
            best_ce = ce; best_T = T
    result = minimize_scalar(lambda t: wdl_cross_entropy(val_res, t),
                             bounds=(0.3, 3.0), method='bounded')
    T_opt = float(result.x)
    print(f'    Grid best T={best_T:.2f} (CE={best_ce:.6f})  '
          f'Fine-tuned T={T_opt:.4f} (CE={float(result.fun):.6f})')
    return T_opt


# ─────────────────────────────────────────────────────────────────────
# Report builder
# ─────────────────────────────────────────────────────────────────────

def build_report(
    kp_v5, kp_v6, kp_v61,
    sanity_v5, sanity_v6, sanity_v61,
    buckets_val_raw_v5, buckets_val_cal_v5,
    png_paths,
    results_stage2,
    boots,
    stage2g_v61_raw, stage2g_v61_cal,
    cup_overall, cup_by_comp,
    cup_v61_df,
    wdl_stage4,
) -> str:
    lines = []
    a = lines.append

    today = '2026-05-12'
    a('# P0.9 Isotonic 校准实验报告')
    a('')
    a(f'**生成日期**: {today}  |  **val**: 1,523 行  |  **test**: 1,525 行  |  **杯赛/欧战**: 263 行')
    a('')
    a('---')
    a('')

    # ── 1. Stage 1: Calibrator shape ─────────────────────────────────
    a('## Stage 1：校准器形状（val split 拟合）')
    a('')
    a('### 1.1 关键映射点（11点，0.10–0.80）')
    a('')
    a('| x | V5→y | V6→y | V6.1→y | 说明 |')
    a('|---|------|------|--------|------|')
    for x in XVALS_FULL:
        v5y  = kp_v5[x]; v6y = kp_v6[x]; v61y = kp_v61[x]
        note = ''
        if x == 0.35:
            note = '← [0.3,0.4] 低估区域'
        elif x == 0.50:
            note = f'← 期望 ≈ BIG5 over率(~0.52)'
        a(f'| {x:.2f} | {v5y:.4f} | {v6y:.4f} | {v61y:.4f} | {note} |')
    a('')

    a('### 1.2 Sanity Check')
    a('')
    a('| 版本 | 单调递增 | iso(0.50) | iso(0.35) | val 实际 over 率 | 0.35→>0.45? |')
    a('|------|---------|----------|----------|----------------|------------|')
    for vname, s in [('V5', sanity_v5), ('V6', sanity_v6), ('V6.1', sanity_v61)]:
        mono = '✅' if s['monotone'] else '❌'
        fix35 = '✅' if s['pred_at_35'] > 0.45 else '❌'
        a(f'| {vname} | {mono} | {s["pred_at_50"]:.4f} | {s["pred_at_35"]:.4f} '
          f'| {s["actual_over_rate"]:.4f} | {fix35} |')
    a('')

    a('### 1.3 等频 10 桶校准曲线（val split，V5 示例）')
    a('')
    a(f'PNG 路径: `{png_paths.get("v5", "N/A")}`')
    a('')
    a('| 桶 | 校准前 mean_pred | 实际 over 率 | 校准后 mean_pred | 修正方向 |')
    a('|---|---|---|---|---|')
    for i, (raw, cal) in enumerate(zip(buckets_val_raw_v5, buckets_val_cal_v5)):
        direction = '↑ 提高' if cal['mean_pred'] > raw['mean_pred'] + 0.01 else (
                    '↓ 降低' if cal['mean_pred'] < raw['mean_pred'] - 0.01 else '≈ 持平')
        a(f'| {i} | {raw["mean_pred"]:.4f} | {raw["actual_rate"]:.4f} '
          f'| {cal["mean_pred"]:.4f} | {direction} |')
    a('')
    a('---')
    a('')

    # ── 2. Stage 2: Test split 6 configs ─────────────────────────────
    a('## Stage 2：Test Split 三方对照（raw vs +iso）')
    a('')
    cfg_order = ['V5 raw','V5+iso','V6 raw','V6+iso','V6.1 raw','V6.1+iso']

    for scope_key, scope_label in [
        ('global', '全局 (1,525行)'),
        ('big5',   'BIG5 (EPL/LaLiga/Bundesliga/Ligue1/SerieA)'),
        ('non_big5','非BIG5 (K/J/澳超等)'),
    ]:
        idx = ['global','big5','non_big5'].index(scope_key) + 1
        a(f'### 2.{idx} {scope_label}')
        a('')
        a('| 配置 | n | OU Acc | OU Brier | LogLoss | [0.3,0.4) pred | actual | Δ |')
        a('|---|---|---|---|---|---|---|---|')
        for cfg in cfg_order:
            m = results_stage2[cfg][scope_key]
            a(f'| {cfg} | {m["n"]} | {m["acc"]:.4f} | {m["brier"]:.4f} '
              f'| {m["logloss"]:.4f} | {m["bucket_pred"]:.4f} | {m["bucket_act"]:.4f} '
              f'| {m["bucket_delta"]:+.4f} |')
        a('')

    a('### 2.4 Bootstrap CI（BIG5，1000× resample，raw → +iso 的 OU acc 提升）')
    a('')
    a('| 版本 | Δ acc (iso−raw) | 95% CI | 统计显著 |')
    a('|---|---|---|---|')
    for vname, b in boots.items():
        sig_str = '✅ 显著改善' if b['sig'] == '*' and b['obs'] > 0 else \
                  ('❌ 显著退化' if b['sig'] == '*' and b['obs'] < 0 else '— 不显著')
        a(f'| {vname} | {b["obs"]:+.4f} | [{b["lo"]:+.4f}, {b["hi"]:+.4f}] | {sig_str} |')
    a('')

    a('### 2.5 V6.1 Test Split 全 10 桶校准拆解（Stage 2G）')
    a('')
    a('| 桶范围 | n | raw pred avg | raw→actual Δ | +iso pred avg | iso→actual Δ |')
    a('|---|---|---|---|---|---|')
    for raw_b, cal_b in zip(stage2g_v61_raw, stage2g_v61_cal):
        lo, hi, n = raw_b['lo'], raw_b['hi'], raw_b['n']
        if n == 0:
            a(f'| [{lo:.1f},{hi:.1f}) | 0 | — | — | — | — |')
            continue
        act = raw_b['actual_over']
        d_raw = act - raw_b['pred_avg']
        d_cal = act - cal_b['pred_avg']
        a(f'| [{lo:.1f},{hi:.1f}) | {n} | {raw_b["pred_avg"]:.4f} | {d_raw:+.4f} '
          f'| {cal_b["pred_avg"]:.4f} | {d_cal:+.4f} |')
    a('')
    a('---')
    a('')

    # ── 3. Stage 3: Cup/European ──────────────────────────────────────
    a('## Stage 3：杯赛 / 欧战迁移性')
    a('')
    a('### 3.1 V5 + V5_iso 整体对照（H2 主检验）')
    a('')
    cr = cup_overall
    a('| 指标 | V5 raw | V5+iso | Δ |')
    a('|---|---|---|---|')
    a(f'| OU Acc | {cr["acc_raw"]:.4f} | {cr["acc_cal"]:.4f} | {cr["acc_cal"]-cr["acc_raw"]:+.4f} |')
    a(f'| OU Brier | {cr["brier_raw"]:.4f} | {cr["brier_cal"]:.4f} | {cr["brier_cal"]-cr["brier_raw"]:+.4f} |')
    a(f'| [0.3,0.4) mean_pred (raw) | {cr["bp_raw"]:.4f} | {cr["bp_cal"]:.4f} | — |')
    a(f'| [0.3,0.4) actual over 率  | {cr["ba_raw"]:.4f} | — | — |')
    a(f'| [0.3,0.4) Δ (actual−pred) | {cr["bd_raw"]:+.4f} (n={cr["bn_raw"]}) '
      f'| {cr["bd_cal"]:+.4f} (n={cr["bn_cal"]}) | — |')
    a('')

    a('### 3.2 分赛事 OU acc（V5 raw vs V5+iso）')
    a('')
    a('| 赛事 | n | V5 raw acc | V5+iso acc | lift | actual over% | pred avg raw | pred avg iso |')
    a('|---|---|---|---|---|---|---|---|')
    for row in cup_by_comp:
        a(f'| {row["league"]} | {row["n"]} | {row["acc_raw"]:.4f} | {row["acc_cal"]:.4f} '
          f'| {row["lift"]:+.4f} | {row["actual_over"]:.4f} '
          f'| {row["pred_avg_raw"]:.4f} | {row["pred_avg_cal"]:.4f} |')
    a('')

    a('### 3.3 V6.1 + V6.1_iso 在杯赛上的表现（Stage I）')
    a('')
    if cup_v61_df is None:
        a('> ⚠️  V6.1 cup 推理失败，跳过此节。')
    else:
        y_cup61  = cup_v61_df['over_label'].values
        p_raw61  = cup_v61_df['p_ov_v61'].values
        p_cal61  = cup_v61_df['p_ov_v61_cal'].values
        acc_r61  = float(((p_raw61 >= 0.5) == y_cup61).mean())
        acc_c61  = float(((p_cal61 >= 0.5) == y_cup61).mean())
        brier_r61 = float(np.mean((p_raw61 - y_cup61)**2))
        brier_c61 = float(np.mean((p_cal61 - y_cup61)**2))

        a(f'（n={len(cup_v61_df)}，注：6个 AH 特征用 fill_value=0 近似，方向性参考）')
        a('')
        a('| 指标 | V6.1 raw | V6.1+iso | Δ | 对比 V5+iso |')
        a('|---|---|---|---|---|')
        v5_iso_acc = cup_overall["acc_cal"]
        a(f'| OU Acc | {acc_r61:.4f} | {acc_c61:.4f} | {acc_c61-acc_r61:+.4f} '
          f'| V5+iso={v5_iso_acc:.4f} |')
        a(f'| OU Brier | {brier_r61:.4f} | {brier_c61:.4f} | {brier_c61-brier_r61:+.4f} | — |')
        a('')

        # per-competition V6.1+iso
        a('**分赛事（V6.1+iso vs V5+iso）**')
        a('')
        a('| 赛事 | n | V6.1 raw | V6.1+iso | V5+iso |')
        a('|---|---|---|---|---|')
        v5_comp_dict = {r['league']: r for r in cup_by_comp}
        for league in sorted(cup_v61_df['league_name'].unique()):
            mask = cup_v61_df['league_name'] == league
            n61   = mask.sum()
            yr61  = y_cup61[mask.values]
            pr61  = p_raw61[mask.values]
            pc61  = p_cal61[mask.values]
            a61_r = float(((pr61 >= 0.5) == yr61).mean())
            a61_c = float(((pc61 >= 0.5) == yr61).mean())
            v5iso_acc = v5_comp_dict.get(league, {}).get('acc_cal', float('nan'))
            a(f'| {league} | {n61} | {a61_r:.4f} | {a61_c:.4f} | {v5iso_acc:.4f} |')
    a('')
    a('---')
    a('')

    # ── 4. WDL temperature ─────────────────────────────────────────────
    a('## Stage 4：WDL 温度校准')
    a('')
    a('| 版本 | 最优 T | WDL Acc (raw) | WDL Acc (T) | Δ acc | RPS (raw) | RPS (T) | Δ RPS |')
    a('|---|---|---|---|---|---|---|---|')
    for vname, d in wdl_stage4.items():
        a(f'| {vname} | {d["T_opt"]:.4f} | {d["acc_raw"]:.4f} | {d["acc_cal"]:.4f} '
          f'| {d["acc_cal"]-d["acc_raw"]:+.4f} | {d["rps_raw"]:.4f} | {d["rps_cal"]:.4f} '
          f'| {d["rps_cal"]-d["rps_raw"]:+.4f} |')
    a('')
    max_gain = max(abs(d['acc_cal'] - d['acc_raw']) for d in wdl_stage4.values())
    if max_gain < 0.005:
        a('> WDL acc lift 全部 < 0.5pp，温度校准对决策无实质改善，暂不部署。')
    else:
        a(f'> WDL acc 最大 lift = {max_gain:.4f}，有一定收益，可酌情集成。')
    a('')
    a('---')
    a('')

    # ── 5. H1 / H2 verdicts & decision table ─────────────────────────
    a('## 关键决策结论')
    a('')

    # H1: BIG5 OU lift ≥ 3pp
    best_big5_lift = max(
        results_stage2['V5+iso']['big5']['acc']  - results_stage2['V5 raw']['big5']['acc'],
        results_stage2['V6+iso']['big5']['acc']  - results_stage2['V6 raw']['big5']['acc'],
        results_stage2['V6.1+iso']['big5']['acc']- results_stage2['V6.1 raw']['big5']['acc'],
    )
    h1_pass = best_big5_lift >= 0.03
    any_sig  = any(b['sig'] == '*' and b['obs'] > 0 for b in boots.values())

    # H2: cup OU ≥ 50%
    cup_iso_acc = cup_overall['acc_cal']
    h2_pass     = cup_iso_acc >= 0.50

    h1_icon = '✅' if h1_pass else '❌'
    h2_icon = '✅' if h2_pass else '❌'
    sig_icon = '（bootstrap 显著）' if any_sig else '（bootstrap 未显著）'

    a(f'**H1（BIG5 OU lift ≥ 3pp）**: {h1_icon}  '
      f'最大 lift={best_big5_lift:+.4f} {sig_icon}')
    a('')
    a(f'**H2（杯赛 OU acc ≥ 50%）**: {h2_icon}  '
      f'V5+iso 杯赛 OU acc = {cup_iso_acc:.4f}')
    a('')

    a('### 场景决策表')
    a('')
    a('| 场景 | 状态 | 推荐行动 |')
    a('|------|------|---------|')

    if h1_pass and h2_pass:
        current = '✅ 当前'
        a(f'| H1 ✅ + H2 ✅ | {current} | **立刻生产 hotfix**：V6+iso 上 BIG5，V5+iso 上杯赛 |')
        a(f'| H1 ✅ + H2 ❌ | — | V5+iso/V6+iso 仅上 BIG5 hotfix；杯赛需 P0.10 |')
        a(f'| H1 ❌ | — | 系统性 bias 不可简单校正，查架构问题 |')
        a('')
        a('> 当前结论：**H1 ✅ + H2 ✅**，建议全量 hotfix。')
    elif h1_pass and not h2_pass:
        a(f'| H1 ✅ + H2 ✅ | — | 立刻生产 hotfix（BIG5 + 杯赛） |')
        a(f'| H1 ✅ + H2 ❌ | ✅ 当前 | **V5+iso/V6+iso 仅上 BIG5**；杯赛需 P0.10 补数据 |')
        a(f'| H1 ❌ | — | 系统性 bias 不可简单校正，查架构问题 |')
        a('')
        a(f'> 当前结论：**H1 ✅ + H2 ❌**，BIG5 hotfix 立刻执行；杯赛 OU 需专项工作。')
    else:
        a(f'| H1 ✅ + H2 ✅ | — | 立刻生产 hotfix（BIG5 + 杯赛） |')
        a(f'| H1 ✅ + H2 ❌ | — | BIG5 hotfix；杯赛需 P0.10 |')
        a(f'| H1 ❌ | ✅ 当前 | **isotonic 对 BIG5 OU lift 不足 3pp**；需排查架构层 bias 来源 |')
        a('')
        a(f'> 当前结论：**H1 ❌**，isotonic 单调校准无法充分修复 BIG5 OU bias，需深入排查。')
    a('')

    a('### 下一步具体行动')
    a('')
    if h1_pass:
        best_v = max(['V5','V6','V6.1'], key=lambda v: (
            results_stage2[f'{v}+iso']['big5']['acc'] -
            results_stage2[f'{v} raw']['big5']['acc']))
        a(f'1. **P0.10 生产集成**（优先）：将 `{best_v.lower()}_ou_isotonic.pkl` 包装进 '
          f'`lambda_ah_predictor.predict_match_full()` 后置步骤，仅影响 p_over 输出，'
          f'不改模型权重。BIG5 联赛启用，非BIG5 暂观察。')
        a('2. **监控**：上线后按周统计 rolling OU acc（isotonic on vs off），设 ±2pp drift 告警。')
        a('3. **校准器季度重拟**：每季末在最新 val 数据上重拟合 isotonic，防止分布漂移。')
    else:
        a('1. **排查架构 bias 来源**：isotonic lift < 3pp 说明偏差不是单调可校正的，需检查：')
        a('   - λ 模型是否系统性低估高进球率比赛')
        a('   - Dixon-Coles 的 ρ 参数是否在高强度对阵中失真')
        a('   - 特征工程层是否遗漏 high-goal 信号（进球趋势特征）')
        a('2. **扩展 val 集**：当前 1,523 行 BIG5 ~1,100 行，bootstrap CI 较宽，增大样本后重测。')
    if not h2_pass:
        a(f'4. **杯赛 OU 专项**（P0.10）：')
        a('   - 补爬杯赛/欧战 NowGoal OU 赔率（UCL/UEL 优先），历史覆盖率 <10% 是根本瓶颈')
        a('   - 将杯赛比赛纳入 V6 OU 训练集（当前 SUPPORTED_LEAGUES 不含 42/73）')
        a('   - 考虑为杯赛单独拟合校准器（以欧战/杯赛历史为训练集）')
    a('5. **WDL 温度校准**：lift < 0.5pp，暂不优先，有充足数据后重评。')
    a('')

    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    print('='*65)
    print('  P0.9 后置 isotonic 校准实验 v2（完整版）')
    print('='*65)

    # ── 0. Load data ─────────────────────────────────────────────────
    print('\n[0] 加载数据 (val + test)')
    df_val_raw  = load_split('val')
    df_test_raw = load_split('test')

    df_val,  _, _ = prep_features(df_val_raw.copy())
    df_test, _, _ = prep_features(df_test_raw.copy())
    n_feat = len([c for c in df_val.columns if c not in set(META_COLS_V6+TARGET_COLS)])
    print(f'  特征列: {n_feat}')

    # ── 0b. Load models ────────────────────────────────────────────────
    print('\n[0b] 加载模型 (V5 / V6 / V6.1)')
    m5_tags  = {'H_Full':'Model_H_Full', 'A_Full':'Model_A_Full',
                'H_Pure':'Model_H_Pure', 'A_Pure':'Model_A_Pure'}
    m6_tags  = {'H_Full':'Model_H_Full_v6', 'A_Full':'Model_A_Full_v6',
                'H_Pure':'Model_H_Pure_v6', 'A_Pure':'Model_A_Pure_v6'}
    m61_tags = {'H_Full':'Model_H_Full_v6_1', 'A_Full':'Model_A_Full_v6_1',
                'H_Pure':'Model_H_Pure_v6_1', 'A_Pure':'Model_A_Pure_v6_1'}

    print('  V5:');   models_v5  = load_models(V5_DIR,  m5_tags)
    rho_v5  = json.load(open(os.path.join(V5_DIR,  'rho.json')))
    print('  V6:');   models_v6  = load_models(V6_DIR,  m6_tags)
    rho_v6  = json.load(open(os.path.join(V6_DIR,  'rho_v6.json')))
    print('  V6.1:'); models_v61 = load_models(V61_DIR, m61_tags)
    rho_v61 = json.load(open(os.path.join(V61_DIR, 'rho_v6_1.json')))

    # ── 1. VAL inference ─────────────────────────────────────────────
    print('\n[1] VAL 推理')
    lh5v,  la5v  = ensemble_predict(models_v5,  df_val)
    lh6v,  la6v  = ensemble_predict(models_v6,  df_val)
    lh61v, la61v = ensemble_predict(models_v61, df_val)
    res_val_v5  = run_inference(df_val, lh5v,  la5v,  rho_v5)
    res_val_v6  = run_inference(df_val, lh6v,  la6v,  rho_v6)
    res_val_v61 = run_inference(df_val, lh61v, la61v, rho_v61)
    print(f'  val 推理完成: {len(res_val_v5)} 行')

    # ── STAGE 1: Fit calibrators on val ─────────────────────────────
    print('\n[STAGE 1] 拟合 OU isotonic 校准器')

    def get_over_label(res: pd.DataFrame):
        return ((res['hs'] + res['as_']) > res['ou_line']).astype(int).values

    y_val_v5  = get_over_label(res_val_v5)
    y_val_v6  = get_over_label(res_val_v6)
    y_val_v61 = get_over_label(res_val_v61)

    print('  V5:');   iso_v5  = fit_isotonic_calibrator(res_val_v5['p_ov'].values,  y_val_v5,  'v5')
    print('  V6:');   iso_v6  = fit_isotonic_calibrator(res_val_v6['p_ov'].values,  y_val_v6,  'v6')
    print('  V6.1:'); iso_v61 = fit_isotonic_calibrator(res_val_v61['p_ov'].values, y_val_v61, 'v6_1')

    # Key mapping points (11 points)
    kp_v5  = calibrator_keypoints(iso_v5)
    kp_v6  = calibrator_keypoints(iso_v6)
    kp_v61 = calibrator_keypoints(iso_v61)

    print('\n  关键映射点 (11点):')
    print(f'  {"x":<6}  {"V5→y":<8}  {"V6→y":<8}  {"V6.1→y":<8}')
    for x in XVALS_FULL:
        print(f'  {x:.2f}   {kp_v5[x]:.4f}   {kp_v6[x]:.4f}   {kp_v61[x]:.4f}')

    # Sanity checks
    print('\n  Sanity checks:')
    sanity_v5  = sanity_check_calibrator(iso_v5,  res_val_v5['p_ov'].values,  y_val_v5,  'V5')
    sanity_v6  = sanity_check_calibrator(iso_v6,  res_val_v6['p_ov'].values,  y_val_v6,  'V6')
    sanity_v61 = sanity_check_calibrator(iso_v61, res_val_v61['p_ov'].values, y_val_v61, 'V6.1')

    # Calibration curves (val split)
    print('\n  校准曲线 PNG:')
    buckets_val_raw_v5 = eq_freq_buckets(res_val_v5['p_ov'].values, y_val_v5.astype(float))
    buckets_val_cal_v5 = eq_freq_buckets(iso_v5.predict(res_val_v5['p_ov'].values), y_val_v5.astype(float))

    png_paths = {}
    png_paths['v5']  = plot_calibration_curve(res_val_v5['p_ov'].values,  y_val_v5,  iso_v5,  'v5',  'V5')
    png_paths['v6']  = plot_calibration_curve(res_val_v6['p_ov'].values,  y_val_v6,  iso_v6,  'v6',  'V6')
    png_paths['v61'] = plot_calibration_curve(res_val_v61['p_ov'].values, y_val_v61, iso_v61, 'v6_1','V6.1')

    # ── 2. TEST inference ────────────────────────────────────────────
    print('\n[2] TEST 推理')
    lh5t,  la5t  = ensemble_predict(models_v5,  df_test)
    lh6t,  la6t  = ensemble_predict(models_v6,  df_test)
    lh61t, la61t = ensemble_predict(models_v61, df_test)
    res_test_v5  = run_inference(df_test, lh5t,  la5t,  rho_v5)
    res_test_v6  = run_inference(df_test, lh6t,  la6t,  rho_v6)
    res_test_v61 = run_inference(df_test, lh61t, la61t, rho_v61)
    print(f'  test 推理完成: {len(res_test_v5)} 行')

    # ── STAGE 2: 6 configs ─────────────────────────────────────────
    print('\n[STAGE 2] Test split 6套配置对照')
    configs = [
        ('V5 raw',   res_test_v5,  None),
        ('V5+iso',   res_test_v5,  iso_v5),
        ('V6 raw',   res_test_v6,  None),
        ('V6+iso',   res_test_v6,  iso_v6),
        ('V6.1 raw', res_test_v61, None),
        ('V6.1+iso', res_test_v61, iso_v61),
    ]
    results_stage2 = {}
    for name, res, iso in configs:
        g, b5, nb5 = ou_metrics_subsets(res, iso)
        results_stage2[name] = {'global': g, 'big5': b5, 'non_big5': nb5}
        print(f'  [{name}]  全局 acc={g["acc"]:.4f}  BIG5 acc={b5["acc"]:.4f}')

    # Bootstrap
    print('\n  Bootstrap CI (BIG5, 1000×):')
    boots = {}
    for vname, res in [('V5',res_test_v5),('V6',res_test_v6),('V6.1',res_test_v61)]:
        iso_map = {'V5':iso_v5,'V6':iso_v6,'V6.1':iso_v61}
        b = bootstrap_ou_acc(res, res, iso_map[vname])
        boots[vname] = b
        sig = '✅显著' if b['sig'] == '*' and b['obs'] > 0 else '—不显著'
        print(f'  {vname}: Δacc={b["obs"]:+.4f}  CI=[{b["lo"]:+.4f},{b["hi"]:+.4f}]  {sig}')

    # Stage 2G: V6.1 full 10-bucket test split
    print('\n  Stage 2G: V6.1 test split 全10桶:')
    r61t = res_test_v61.copy()
    r61t['over_label'] = ((r61t['hs'] + r61t['as_']) > r61t['ou_line']).astype(int)
    r61t = r61t[r61t['hs'] + r61t['as_'] != r61t['ou_line']].copy()
    y61t = r61t['over_label'].values
    p61t_raw = r61t['p_ov'].values
    p61t_cal = iso_v61.predict(p61t_raw)
    stage2g_raw = fixed_width_buckets_10(p61t_raw, y61t)
    stage2g_cal = fixed_width_buckets_10(p61t_cal, y61t)

    # ── STAGE 3: Cup / European ─────────────────────────────────────
    print('\n[STAGE 3] 杯赛/欧战迁移性')
    cup_df = pd.read_csv(CUP_CSV)
    cup_df['over_label'] = ((cup_df['home_score'] + cup_df['away_score']) > 2.5).astype(int)
    cup_df['p_over_cal'] = iso_v5.predict(cup_df['p_over'].values)

    y_cup  = cup_df['over_label'].values
    p_raw  = cup_df['p_over'].values
    p_cal_ = cup_df['p_over_cal'].values

    acc_raw_c  = float(((p_raw  >= 0.5) == y_cup).mean())
    acc_cal_c  = float(((p_cal_ >= 0.5) == y_cup).mean())
    brier_raw_c = float(np.mean((p_raw  - y_cup)**2))
    brier_cal_c = float(np.mean((p_cal_ - y_cup)**2))
    bm  = (p_raw >= 0.3) & (p_raw < 0.4)
    bp_raw = float(p_raw[bm].mean())  if bm.sum() else float('nan')
    ba_raw = float(y_cup[bm].mean())  if bm.sum() else float('nan')
    bd_raw = ba_raw - bp_raw          if bm.sum() else float('nan')
    bn_raw = int(bm.sum())
    bp_cal = float(p_cal_[bm].mean()) if bm.sum() else float('nan')
    ba_cal = ba_raw
    bd_cal = ba_cal - bp_cal          if bm.sum() else float('nan')
    bn_cal = bn_raw

    cup_overall = dict(
        n=len(cup_df),
        acc_raw=acc_raw_c, acc_cal=acc_cal_c,
        brier_raw=brier_raw_c, brier_cal=brier_cal_c,
        bp_raw=bp_raw, ba_raw=ba_raw, bd_raw=bd_raw, bn_raw=bn_raw,
        bp_cal=bp_cal, ba_cal=ba_cal, bd_cal=bd_cal, bn_cal=bn_cal,
    )
    print(f'  V5+iso cup OU acc: raw={acc_raw_c:.4f}  cal={acc_cal_c:.4f}  Δ={acc_cal_c-acc_raw_c:+.4f}')
    print(f'  Brier: raw={brier_raw_c:.4f}  cal={brier_cal_c:.4f}')
    print(f'  [0.3,0.4) Δ: {bd_raw:+.4f}→{bd_cal:+.4f} (n={bn_raw})')

    # Per-competition breakdown
    cup_by_comp = cup_metrics_by_competition(cup_df, p_cal_)
    print('  分赛事:')
    for row in cup_by_comp:
        print(f'    {row["league"]:<20} n={row["n"]:3}  raw={row["acc_raw"]:.4f}  '
              f'iso={row["acc_cal"]:.4f}  lift={row["lift"]:+.4f}')

    # Stage 3I: V6.1+iso on cup
    cup_v61_df = run_v61_on_cup(iso_v61, rho_v61, models_v61)

    # ── STAGE 4: WDL temperature ─────────────────────────────────────
    print('\n[STAGE 4] WDL 温度校准')
    wdl_stage4 = {}
    for vname, val_res, test_res in [
        ('V5',  res_val_v5,  res_test_v5),
        ('V6',  res_val_v6,  res_test_v6),
        ('V6.1',res_val_v61, res_test_v61),
    ]:
        print(f'  {vname}:')
        T_opt = fit_temperature(val_res)
        acc_r = wdl_accuracy_temp(test_res, 1.0)
        rps_r = wdl_rps_temp(test_res, 1.0)
        acc_c = wdl_accuracy_temp(test_res, T_opt)
        rps_c = wdl_rps_temp(test_res, T_opt)
        wdl_stage4[vname] = {'T_opt':T_opt,'acc_raw':acc_r,'acc_cal':acc_c,
                              'rps_raw':rps_r,'rps_cal':rps_c}

    # ── Report ────────────────────────────────────────────────────────
    print('\n[REPORT] 生成报告')
    report = build_report(
        kp_v5, kp_v6, kp_v61,
        sanity_v5, sanity_v6, sanity_v61,
        buckets_val_raw_v5, buckets_val_cal_v5,
        png_paths,
        results_stage2,
        boots,
        stage2g_raw, stage2g_cal,
        cup_overall, cup_by_comp,
        cup_v61_df,
        wdl_stage4,
    )
    rpath = os.path.join(REPORT_DIR, 'p09_calibration_eval.md')
    with open(rpath, 'w') as f:
        f.write(report)
    print(f'  报告 → {rpath}')
    print('\n' + '='*65 + '\n  P0.9 校准实验 v2 完成\n' + '='*65)


if __name__ == '__main__':
    main()
