#!/usr/bin/env python3
"""
eval_v5_vs_v6.py — V5 vs V6 原型全面对比评估

评估维度：
  WDL 准确率 + RPS (Ranked Probability Score)
  OU  准确率 + Brier Score
  AH  准确率
  λ   MAE (home + away)
  Paired Bootstrap 1000× 95% CI
  Per-League_ID 分解

测试集：mart_lambda_dataset_v6_train 的 split='test'（1,525 行）
V5 模型：models_v5_lambda/Model_*_{H/A}_{Full/Pure}.cbm + rho.json
V6 模型：models/v6_prototype/Model_*_v6.cbm + rho_v6.json

输出：
  reports/v6_prototype_eval.md
  models/v6_prototype/ou_calibration_v5_vs_v6.png
"""
from __future__ import annotations
import json, os, sys, sqlite3, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

sys.path.insert(0, os.path.dirname(__file__))
from inference_lambda import build_score_matrix, derive_wdl, derive_ou, derive_ah

DB_PATH    = '/home/ubuntu/app/backend/football_uk.db'
V5_DIR     = '/home/ubuntu/app/backend/models_v5_lambda'
V6_DIR     = '/home/ubuntu/app/backend/models/v6_prototype'
REPORT_DIR = '/home/ubuntu/app/backend/reports'
os.makedirs(REPORT_DIR, exist_ok=True)

LEAGUE_NAMES = {47:'英超(EPL)', 55:'西甲(La Liga)', 87:'德甲(Bundesliga)',
                53:'法甲(Ligue 1)', 54:'意甲(Serie A)',
                113:'澳超', 223:'J联赛', 9080:'K联赛'}

ODDS_PATTERN_KEYWORDS = [
    'raw_home', 'raw_away', 'raw_draw',
    'fair_home', 'fair_draw', 'fair_away',
    'implied', 'ah_implied_diff',
    'ah_raw_home', 'ah_raw_away', 'ah_odds_movement',
    'closing_eu_raw', 'closing_ah_raw', 'closing_ou_raw',
    'closing_eu_fair', 'closing_ah_fair', 'closing_ou_fair',
    'open_eu_fair', 'open_ah_fair', 'open_ou_fair',
    'eu_odds', 'eu_implied',
]

META_COLS_V5 = [
    'match_id','match_date','Season','Home_Team_ID','Away_Team_ID',
    'Home_Team_Name','Away_Team_Name','days_from_latest','sample_weight',
    'split','ah_source','ah_line_category',
]
META_COLS_V6 = META_COLS_V5 + ['is_fd_fallback']
TARGET_COLS  = ['target_home_score', 'target_away_score']


# ─────────────────────────────────────────────────────────────────────
# 1. 数据加载
# ─────────────────────────────────────────────────────────────────────

def load_test_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT * FROM mart_lambda_dataset_v6_train WHERE split='test'", conn)
    conn.close()
    print(f'  测试集: {len(df):,} 行 × {len(df.columns)} 列')
    return df


def prep_features(df: pd.DataFrame, meta_cols: list) -> tuple[pd.DataFrame, list, list]:
    """返回 (df_clean, feat_full, feat_pure)"""
    null_rates = df.isnull().mean()
    drop_cols  = null_rates[null_rates > 0.40].index.tolist()
    df = df.drop(columns=drop_cols, errors='ignore')

    non_feat = set(meta_cols + TARGET_COLS)
    cands    = [c for c in df.columns if c not in non_feat]

    feat_full = cands
    feat_pure = [c for c in cands if not any(
        kw.lower() in c.lower() for kw in ODDS_PATTERN_KEYWORDS)]

    # NULL 填充
    for c in feat_full:
        if df[c].dtype in [np.float64, np.float32, float, np.int64, np.int32, int]:
            df[c] = df[c].fillna(-999)
        elif df[c].dtype == object:
            df[c] = df[c].fillna('__NA__')

    return df, feat_full, feat_pure


# ─────────────────────────────────────────────────────────────────────
# 2. 模型加载 + 推理
# ─────────────────────────────────────────────────────────────────────

def load_models(model_dir: str, suffix: str = '') -> dict:
    """加载 4 个 CatBoost 模型"""
    from catboost import CatBoostRegressor
    models = {}
    for tag in ['H_Full', 'A_Full', 'H_Pure', 'A_Pure']:
        fname = f'Model_{tag}{suffix}.cbm'
        path  = os.path.join(model_dir, fname)
        m     = CatBoostRegressor()
        m.load_model(path)
        models[tag] = m
        print(f'  加载 {fname}  (BestIter={m.get_best_iteration()})')
    return models


def load_rho(model_dir: str, fname: str) -> dict:
    path = os.path.join(model_dir, fname)
    with open(path) as f:
        return json.load(f)


def align_features(df: pd.DataFrame, model) -> pd.DataFrame:
    """按模型 feature_names_ 对齐列，缺列填 -999"""
    expected = list(model.feature_names_)
    for c in expected:
        if c not in df.columns:
            df[c] = -999
    return df[expected]


def ensemble_predict(models: dict, df: pd.DataFrame,
                     feat_full: list, feat_pure: list) -> tuple[np.ndarray, np.ndarray]:
    """0.6×Full + 0.4×Pure 集成，返回 (lam_h, lam_a)"""
    X_f = align_features(df.copy(), models['H_Full'])[list(models['H_Full'].feature_names_)]
    X_p = align_features(df.copy(), models['H_Pure'])[list(models['H_Pure'].feature_names_)]
    # Sanity check: use model feature_names directly
    X_f_h = df[list(models['H_Full'].feature_names_)].copy()
    X_f_a = df[list(models['A_Full'].feature_names_)].copy()
    X_p_h = df[list(models['H_Pure'].feature_names_)].copy()
    X_p_a = df[list(models['A_Pure'].feature_names_)].copy()

    lam_h = (0.6 * np.clip(models['H_Full'].predict(X_f_h), 1e-4, None) +
             0.4 * np.clip(models['H_Pure'].predict(X_p_h), 1e-4, None))
    lam_a = (0.6 * np.clip(models['A_Full'].predict(X_f_a), 1e-4, None) +
             0.4 * np.clip(models['A_Pure'].predict(X_p_a), 1e-4, None))
    return lam_h, lam_a


def run_inference(df: pd.DataFrame, lam_h: np.ndarray, lam_a: np.ndarray,
                  rho_data: dict) -> pd.DataFrame:
    """从 lam_h/lam_a + rho → 推断 WDL/OU/AH 各市场概率"""
    rho_global = rho_data['rho_global']
    rho_league = rho_data.get('rho_by_league', {})

    records = []
    for i in range(len(df)):
        row   = df.iloc[i]
        lid   = str(int(row.get('League_ID', 0)))
        rho   = rho_league.get(lid, rho_global)

        lh, la = float(lam_h[i]), float(lam_a[i])
        mat = build_score_matrix(lh, la, rho)

        p_hw, p_d, p_aw = derive_wdl(mat)

        # OU 线
        ou_line = float(row.get('closing_ou_line', row.get('open_ou_line', 2.5)))
        if ou_line <= 0 or np.isnan(ou_line):
            ou_line = 2.5
        p_ov, p_un, _ = derive_ou(mat, ou_line)

        # AH 线
        ah_line = float(row.get('closing_ah_line', row.get('ah_line_opening', 0.0)))
        if np.isnan(ah_line):
            ah_line = 0.0
        p_hc, p_ac, _ = derive_ah(mat, ah_line)

        records.append({
            'match_id':   row['match_id'],
            'League_ID':  row.get('League_ID', 0),
            'Season':     row.get('Season', ''),
            'hs':         int(row['target_home_score']),
            'as_':        int(row['target_away_score']),
            'ou_line':    ou_line,
            'ah_line':    ah_line,
            'lam_h':      lh,
            'lam_a':      la,
            'p_hw':       p_hw, 'p_d': p_d, 'p_aw': p_aw,
            'p_ov':       p_ov, 'p_un': p_un,
            'p_hc':       p_hc, 'p_ac': p_ac,
        })
    return pd.DataFrame(records)


# ─────────────────────────────────────────────────────────────────────
# 3. 指标计算
# ─────────────────────────────────────────────────────────────────────

def compute_metrics(res: pd.DataFrame, label: str) -> dict:
    """计算 WDL acc/RPS, OU acc/Brier, AH acc, λ MAE"""
    r = res.copy()

    # ── Actual outcomes ──
    r['actual_wdl'] = np.where(r['hs'] > r['as_'], 'home_win',
                      np.where(r['hs'] == r['as_'], 'draw', 'away_win'))
    total_goals = r['hs'] + r['as_']
    r['actual_ou'] = np.where(total_goals > r['ou_line'], 'over',
                     np.where(total_goals < r['ou_line'], 'under', 'push'))
    adj_diff = r['hs'] - r['as_'] + r['ah_line']
    r['actual_ah'] = np.where(adj_diff > 1e-9, 'home',
                     np.where(adj_diff < -1e-9, 'away', 'push'))

    # ── WDL acc ──
    r['pred_wdl'] = np.where(
        (r['p_hw'] >= r['p_d']) & (r['p_hw'] >= r['p_aw']), 'home_win',
        np.where(r['p_d'] >= r['p_aw'], 'draw', 'away_win'))
    wdl_acc = (r['pred_wdl'] == r['actual_wdl']).mean()

    # ── WDL RPS ──
    # ordered: [home_win, draw, away_win]
    def to_cum(p_hw, p_d, p_aw):
        return np.array([p_hw, p_hw + p_d, p_hw + p_d + p_aw])

    def actual_cum(wdl):
        if wdl == 'home_win':  return np.array([1., 1., 1.])
        if wdl == 'draw':      return np.array([0., 1., 1.])
        return np.array([0., 0., 1.])

    rps_vals = []
    for _, row in r.iterrows():
        cp = to_cum(row['p_hw'], row['p_d'], row['p_aw'])
        ca = actual_cum(row['actual_wdl'])
        rps_vals.append(np.mean((cp - ca) ** 2))
    wdl_rps = float(np.mean(rps_vals))

    # ── OU acc + Brier (exclude push) ──
    ou_valid = r[r['actual_ou'] != 'push'].copy()
    ou_valid['pred_ou'] = np.where(ou_valid['p_ov'] >= ou_valid['p_un'], 'over', 'under')
    ou_acc   = (ou_valid['pred_ou'] == ou_valid['actual_ou']).mean()
    ou_actual_bin = (ou_valid['actual_ou'] == 'over').astype(float)
    ou_brier = float(np.mean((ou_valid['p_ov'] - ou_actual_bin) ** 2))

    # ── AH acc (exclude push) ──
    ah_valid = r[r['actual_ah'] != 'push'].copy()
    ah_valid['pred_ah'] = np.where(ah_valid['p_hc'] >= ah_valid['p_ac'], 'home', 'away')
    ah_acc = (ah_valid['pred_ah'] == ah_valid['actual_ah']).mean() if len(ah_valid) > 0 else float('nan')

    # ── λ MAE ──
    lam_h_mae = float(np.mean(np.abs(r['lam_h'] - r['hs'])))
    lam_a_mae = float(np.mean(np.abs(r['lam_a'] - r['as_'])))

    return {
        'label': label, 'n': len(r),
        'wdl_acc': wdl_acc, 'wdl_rps': wdl_rps,
        'ou_acc': ou_acc, 'ou_brier': ou_brier, 'ou_n': len(ou_valid),
        'ah_acc': ah_acc, 'ah_n': len(ah_valid),
        'lam_h_mae': lam_h_mae, 'lam_a_mae': lam_a_mae,
    }


# ─────────────────────────────────────────────────────────────────────
# 4. Paired Bootstrap
# ─────────────────────────────────────────────────────────────────────

def paired_bootstrap(res_v5: pd.DataFrame, res_v6: pd.DataFrame,
                     n_boot: int = 1000, seed: int = 42) -> dict:
    """1000× paired bootstrap — 95% CI for WDL acc, OU acc, AH acc differences (V6-V5)"""
    assert len(res_v5) == len(res_v6), "Row counts must match"
    rng = np.random.default_rng(seed)
    n   = len(res_v5)

    # Pre-compute per-row correct flags
    def wdl_correct(res):
        actual = np.where(res['hs'] > res['as_'], 'home_win',
                 np.where(res['hs'] == res['as_'], 'draw', 'away_win'))
        pred   = np.where(
            (res['p_hw'] >= res['p_d']) & (res['p_hw'] >= res['p_aw']), 'home_win',
            np.where(res['p_d'] >= res['p_aw'], 'draw', 'away_win'))
        return (pred == actual).astype(float)

    def ou_correct(res):
        total_g  = res['hs'] + res['as_']
        actual   = np.where(total_g > res['ou_line'], 'over',
                   np.where(total_g < res['ou_line'], 'under', 'push'))
        pred     = np.where(res['p_ov'] >= res['p_un'], 'over', 'under')
        mask     = actual != 'push'
        c        = np.full(n, np.nan)
        c[mask]  = (pred[mask] == actual[mask])
        return c

    def ah_correct(res):
        adj  = res['hs'] - res['as_'] + res['ah_line']
        act  = np.where(adj > 1e-9, 'home', np.where(adj < -1e-9, 'away', 'push'))
        pred = np.where(res['p_hc'] >= res['p_ac'], 'home', 'away')
        mask = act != 'push'
        c    = np.full(n, np.nan)
        c[mask] = (pred[mask] == act[mask])
        return c

    # Numpy arrays
    v5a = res_v5.values if isinstance(res_v5, pd.Series) else None
    wdl5 = wdl_correct(res_v5); wdl6 = wdl_correct(res_v6)
    ou5  = ou_correct(res_v5);  ou6  = ou_correct(res_v6)
    ah5  = ah_correct(res_v5);  ah6  = ah_correct(res_v6)

    obs_wdl = np.nanmean(wdl6) - np.nanmean(wdl5)
    obs_ou  = np.nanmean(ou6)  - np.nanmean(ou5)
    obs_ah  = np.nanmean(ah6)  - np.nanmean(ah5)

    boot_wdl = np.empty(n_boot); boot_ou = np.empty(n_boot); boot_ah = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boot_wdl[b] = np.nanmean(wdl6[idx]) - np.nanmean(wdl5[idx])
        boot_ou[b]  = np.nanmean(ou6[idx])  - np.nanmean(ou5[idx])
        boot_ah[b]  = np.nanmean(ah6[idx])  - np.nanmean(ah5[idx])

    def ci(obs, boots):
        lo, hi = np.percentile(boots, [2.5, 97.5])
        sig = '*' if lo > 0 or hi < 0 else ''
        return {'obs': obs, 'lo': lo, 'hi': hi, 'sig': sig}

    return {
        'wdl': ci(obs_wdl, boot_wdl),
        'ou':  ci(obs_ou,  boot_ou),
        'ah':  ci(obs_ah,  boot_ah),
    }


# ─────────────────────────────────────────────────────────────────────
# 5. Per-League 分解
# ─────────────────────────────────────────────────────────────────────

def per_league(res_v5: pd.DataFrame, res_v6: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for lid in sorted(res_v5['League_ID'].unique()):
        r5 = res_v5[res_v5['League_ID'] == lid]
        r6 = res_v6[res_v6['League_ID'] == lid]
        if len(r5) < 20:
            continue
        m5 = compute_metrics(r5, 'v5')
        m6 = compute_metrics(r6, 'v6')
        rows.append({
            'League': LEAGUE_NAMES.get(int(lid), str(int(lid))),
            'n': m5['n'],
            'V5_WDL': f"{m5['wdl_acc']:.3f}",
            'V6_WDL': f"{m6['wdl_acc']:.3f}",
            'ΔWDL':   f"{m6['wdl_acc']-m5['wdl_acc']:+.3f}",
            'V5_OU':  f"{m5['ou_acc']:.3f}",
            'V6_OU':  f"{m6['ou_acc']:.3f}",
            'ΔOU':    f"{m6['ou_acc']-m5['ou_acc']:+.3f}",
            'V5_AH':  f"{m5['ah_acc']:.3f}",
            'V6_AH':  f"{m6['ah_acc']:.3f}",
            'ΔAH':    f"{m6['ah_acc']-m5['ah_acc']:+.3f}",
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────
# 6. OU 校准图
# ─────────────────────────────────────────────────────────────────────

def ou_calibration_plot(res_v5: pd.DataFrame, res_v6: pd.DataFrame, out_path: str):
    """10 个 p_over 桶 × 实际 over 率"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        def calibrate(res):
            ou_valid = res[res['hs'] + res['as_'] != res['ou_line']].copy()
            ou_valid['actual_over'] = (ou_valid['hs'] + ou_valid['as_'] > ou_valid['ou_line']).astype(float)
            ou_valid['bucket'] = pd.cut(ou_valid['p_ov'], bins=10, labels=False)
            g = ou_valid.groupby('bucket').agg(
                pred_mean=('p_ov', 'mean'),
                actual_mean=('actual_over', 'mean'),
                n=('p_ov', 'count')
            ).reset_index()
            return g

        g5 = calibrate(res_v5)
        g6 = calibrate(res_v6)

        fig, ax = plt.subplots(figsize=(8, 6))
        ax.plot([0, 1], [0, 1], 'k--', alpha=0.4, label='Perfect')
        ax.scatter(g5['pred_mean'], g5['actual_mean'], s=g5['n']/3,
                   c='steelblue', alpha=0.8, label='V5', marker='o')
        ax.plot(g5['pred_mean'], g5['actual_mean'], 'b-', alpha=0.5)
        ax.scatter(g6['pred_mean'], g6['actual_mean'], s=g6['n']/3,
                   c='tomato', alpha=0.8, label='V6', marker='s')
        ax.plot(g6['pred_mean'], g6['actual_mean'], 'r-', alpha=0.5)
        ax.set_xlabel('Predicted p(Over)')
        ax.set_ylabel('Actual Over Rate')
        ax.set_title('OU Calibration: V5 vs V6 (10 buckets, bubble size ∝ n)')
        ax.legend()
        ax.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(out_path, dpi=120)
        plt.close()
        print(f'  OU 校准图 → {out_path}')
    except Exception as e:
        print(f'  OU 校准图失败: {e}')


# ─────────────────────────────────────────────────────────────────────
# 7. 生成 Markdown 报告
# ─────────────────────────────────────────────────────────────────────

def build_report(m5: dict, m6: dict, boot: dict, league_df: pd.DataFrame,
                 v5_instrumentation: dict, v6_instrumentation: dict) -> str:
    lines = []
    a = lines.append

    a('# V6 原型评估报告')
    a('')
    a(f'**生成日期**: 2026-05-11')
    a(f'**测试集**: mart_lambda_dataset_v6_train split=test ({m5["n"]:,} 行)')
    a(f'**V5 模型**: models_v5_lambda/ (生产现役)')
    a(f'**V6 模型**: models/v6_prototype/ (原型，本次训练)')
    a('')
    a('---')
    a('')
    a('## 1. 模型 Instrumentation')
    a('')
    a('| 版本 | 模型 | BestIter | TotalIter | TrainLoss | ValLoss |')
    a('|------|------|----------|-----------|-----------|---------|')
    for v, inst in [('V5', v5_instrumentation), ('V6', v6_instrumentation)]:
        for tag in ['H_Full', 'A_Full', 'H_Pure', 'A_Pure']:
            if tag in inst:
                d = inst[tag]
                suf = '_v6' if v == 'V6' else ''
                a(f"| {v} | {tag}{suf} | {d['best_iter']} | {d['total_iter']} | {d['train_loss']:.4f} | {d['val_loss']:.4f} |")
    a('')
    a('---')
    a('')
    a('## 2. 全局指标对比')
    a('')
    a('| 指标 | V5 | V6 | Δ (V6-V5) | Bootstrap 95% CI | 显著？ |')
    a('|------|-----|-----|-----------|-----------------|--------|')

    def fmt_ci(b):
        sig_str = '✅ 显著' if b['sig'] == '*' else '—'
        return f"[{b['lo']:+.4f}, {b['hi']:+.4f}]", sig_str

    wdl_ci, wdl_sig = fmt_ci(boot['wdl'])
    ou_ci,  ou_sig  = fmt_ci(boot['ou'])
    ah_ci,  ah_sig  = fmt_ci(boot['ah'])

    a(f"| WDL 准确率 | {m5['wdl_acc']:.4f} | {m6['wdl_acc']:.4f} | {m6['wdl_acc']-m5['wdl_acc']:+.4f} | {wdl_ci} | {wdl_sig} |")
    a(f"| WDL RPS ↓  | {m5['wdl_rps']:.4f} | {m6['wdl_rps']:.4f} | {m6['wdl_rps']-m5['wdl_rps']:+.4f} | — | — |")
    a(f"| OU 准确率  | {m5['ou_acc']:.4f} | {m6['ou_acc']:.4f} | {m6['ou_acc']-m5['ou_acc']:+.4f} | {ou_ci} | {ou_sig} |")
    a(f"| OU Brier ↓ | {m5['ou_brier']:.4f} | {m6['ou_brier']:.4f} | {m6['ou_brier']-m5['ou_brier']:+.4f} | — | — |")
    a(f"| AH 准确率  | {m5['ah_acc']:.4f} | {m6['ah_acc']:.4f} | {m6['ah_acc']-m5['ah_acc']:+.4f} | {ah_ci} | {ah_sig} |")
    a(f"| λ_h MAE ↓  | {m5['lam_h_mae']:.4f} | {m6['lam_h_mae']:.4f} | {m6['lam_h_mae']-m5['lam_h_mae']:+.4f} | — | — |")
    a(f"| λ_a MAE ↓  | {m5['lam_a_mae']:.4f} | {m6['lam_a_mae']:.4f} | {m6['lam_a_mae']-m5['lam_a_mae']:+.4f} | — | — |")
    a('')
    a(f'*OU n={m5["ou_n"]:,} (非 push)  AH n={m5["ah_n"]:,} (非 push)*')
    a('')
    a('---')
    a('')
    a('## 3. Per-League_ID 分解')
    a('')
    # Markdown table
    header = '| ' + ' | '.join(league_df.columns) + ' |'
    sep    = '| ' + ' | '.join(['---']*len(league_df.columns)) + ' |'
    a(header); a(sep)
    for _, row in league_df.iterrows():
        a('| ' + ' | '.join(str(v) for v in row.values) + ' |')
    a('')
    a('---')
    a('')
    a('## 4. OU 校准图')
    a('')
    a('![OU Calibration](../models/v6_prototype/ou_calibration_v5_vs_v6.png)')
    a('')
    a('---')
    a('')
    a('## 5. 结论与建议')
    a('')

    # Determine recommendation
    wdl_delta = m6['wdl_acc'] - m5['wdl_acc']
    ou_delta  = m6['ou_acc']  - m5['ou_acc']
    ah_delta  = m6['ah_acc']  - m5['ah_acc']
    lam_delta = ((m6['lam_h_mae'] + m6['lam_a_mae']) -
                 (m5['lam_h_mae'] + m5['lam_a_mae']))

    wins = sum([wdl_delta >= 0, ou_delta >= 0, ah_delta >= 0, lam_delta <= 0])
    sig_wins = sum([
        boot['wdl']['sig'] == '*' and wdl_delta > 0,
        boot['ou']['sig']  == '*' and ou_delta  > 0,
        boot['ah']['sig']  == '*' and ah_delta  > 0,
    ])

    if wins >= 3 and (sig_wins >= 1 or wdl_delta + ou_delta > 0.01):
        rec  = '✅ **推荐进入 P0.9（V6 替换生产 V5）**'
        next = '- 下一步：整合 V6 模型到 lambda_ah_predictor.py 生产推理路径'
    elif wins >= 2:
        rec  = '⚠️ **V6 ≈ V5，建议继续观察后再决策**'
        next = '- 可考虑补充 25/26 OU 数据后重训，看是否带来更大改善'
    else:
        rec  = '❌ **V6 < V5，暂停替换，调查原因**'
        next = '- 检查特征对齐、is_fd_fallback 行质量、22/23 赛季数据噪声'

    a(f'{rec}')
    a('')
    a(f'**胜出维度**: {wins}/4  **统计显著改善**: {sig_wins}/3')
    a('')
    a(f'| 维度 | Δ | 状态 |')
    a(f'|------|---|------|')
    a(f'| WDL 准确率 | {wdl_delta:+.4f} | {"✅" if wdl_delta >= 0 else "❌"} |')
    a(f'| OU 准确率  | {ou_delta:+.4f}  | {"✅" if ou_delta  >= 0 else "❌"} |')
    a(f'| AH 准确率  | {ah_delta:+.4f}  | {"✅" if ah_delta  >= 0 else "❌"} |')
    a(f'| λ MAE (avg)| {lam_delta:+.4f}  | {"✅" if lam_delta <= 0 else "❌"} |')
    a('')
    a(next)
    a('')

    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    print('='*65)
    print('  V5 vs V6 原型对比评估')
    print('='*65)

    # 1. 加载测试数据
    print('\n[1] 加载测试集')
    df_raw = load_test_data()

    # 2. Prep features（V6 视角，含 is_fd_fallback 在 META_COLS）
    print('\n[2] 特征预处理')
    df, feat_full, feat_pure = prep_features(df_raw.copy(), META_COLS_V6)
    print(f'  feat_full={len(feat_full)}  feat_pure={len(feat_pure)}')

    # 3. 加载模型
    print('\n[3] 加载 V5 模型')
    models_v5 = load_models(V5_DIR, suffix='')
    rho_v5    = load_rho(V5_DIR, 'rho.json')

    print('\n[4] 加载 V6 模型')
    models_v6 = load_models(V6_DIR, suffix='_v6')
    rho_v6    = load_rho(V6_DIR, 'rho_v6.json')

    # Instrumentation from models
    def get_instrumentation(models, suffix=''):
        inst = {}
        for tag in ['H_Full', 'A_Full', 'H_Pure', 'A_Pure']:
            m = models[tag]
            bi  = m.get_best_iteration()
            res = m.get_evals_result()
            total = len(res.get('validation', {}).get('Poisson', []))
            tl  = m.get_best_score().get('learn', {}).get('Poisson', float('nan'))
            vl  = m.get_best_score().get('validation', {}).get('Poisson', float('nan'))
            inst[tag] = {'best_iter': bi, 'total_iter': total,
                         'train_loss': tl, 'val_loss': vl}
        return inst

    inst_v5 = get_instrumentation(models_v5)
    inst_v6 = get_instrumentation(models_v6)

    # 4. 推理
    print('\n[5] V5 推理')
    lam_h_v5, lam_a_v5 = ensemble_predict(models_v5, df, feat_full, feat_pure)
    res_v5 = run_inference(df, lam_h_v5, lam_a_v5, rho_v5)
    print(f'  λ_h mean={lam_h_v5.mean():.3f}  λ_a mean={lam_a_v5.mean():.3f}')

    print('\n[6] V6 推理')
    lam_h_v6, lam_a_v6 = ensemble_predict(models_v6, df, feat_full, feat_pure)
    res_v6 = run_inference(df, lam_h_v6, lam_a_v6, rho_v6)
    print(f'  λ_h mean={lam_h_v6.mean():.3f}  λ_a mean={lam_a_v6.mean():.3f}')

    # 5. 全局指标
    print('\n[7] 计算全局指标')
    m5 = compute_metrics(res_v5, 'V5')
    m6 = compute_metrics(res_v6, 'V6')

    print(f'\n  {"指标":<14}  {"V5":>8}  {"V6":>8}  {"Δ":>8}')
    print('  ' + '─'*44)
    for key, fmt in [('wdl_acc','WDL Acc'),('wdl_rps','WDL RPS'),
                     ('ou_acc','OU Acc'),('ou_brier','OU Brier'),
                     ('ah_acc','AH Acc'),('lam_h_mae','λ_h MAE'),('lam_a_mae','λ_a MAE')]:
        v5v = m5[key]; v6v = m6[key]
        delta = v6v - v5v
        print(f'  {fmt:<14}  {v5v:>8.4f}  {v6v:>8.4f}  {delta:>+8.4f}')

    # 6. Paired bootstrap
    print('\n[8] Paired Bootstrap (1000×)')
    boot = paired_bootstrap(res_v5, res_v6)
    for mkt, b in boot.items():
        sig = '✅ 显著' if b['sig'] == '*' else '—'
        print(f'  {mkt.upper():4s}  Δ={b["obs"]:+.4f}  95%CI=[{b["lo"]:+.4f},{b["hi"]:+.4f}]  {sig}')

    # 7. Per-league
    print('\n[9] Per-League 分解')
    league_df = per_league(res_v5, res_v6)
    print(league_df.to_string(index=False))

    # 8. OU 校准图
    plot_path = os.path.join(V6_DIR, 'ou_calibration_v5_vs_v6.png')
    ou_calibration_plot(res_v5, res_v6, plot_path)

    # 9. 生成报告
    report_md = build_report(m5, m6, boot, league_df, inst_v5, inst_v6)
    report_path = os.path.join(REPORT_DIR, 'v6_prototype_eval.md')
    with open(report_path, 'w') as f:
        f.write(report_md)
    print(f'\n  报告 → {report_path}')

    print('\n' + '='*65)
    print('  评估完成')
    print('='*65)


if __name__ == '__main__':
    main()
