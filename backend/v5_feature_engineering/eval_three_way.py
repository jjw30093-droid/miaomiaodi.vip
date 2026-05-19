#!/usr/bin/env python3
"""
eval_three_way.py — V5 / V6 / V6.1 三方对照评估

Stage 3(F-J): 在 test split (1,525 行) 上三方推理
  - 全局 / 仅 BIG5 (~1,126 行) / 仅 K-J-澳超 (~399 行) 分层统计
  - BIG5 子集 Bootstrap 95% CI (V6.1 vs V5, V6.1 vs V6)
  - Per-League BIG5 细拆
  - OU calibration (p_over 分桶 × 实际 over 率)
  - 输出 reports/v6_1_eval.md
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
V61_DIR    = '/home/ubuntu/app/backend/models/v6_1_clean'
REPORT_DIR = '/home/ubuntu/app/backend/reports'
os.makedirs(REPORT_DIR, exist_ok=True)

BIG5_LIDS  = {47, 53, 54, 55, 87}
LEAGUE_NAMES = {47:'英超(EPL)', 55:'西甲(La Liga)', 87:'德甲(Bundesliga)',
                53:'法甲(Ligue 1)', 54:'意甲(Serie A)',
                113:'澳超', 223:'J联赛', 9080:'K联赛'}

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
# Data + Feature Prep
# ─────────────────────────────────────────────────────────────────────

def load_test_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT * FROM mart_lambda_dataset_v6_train WHERE split='test'", conn)
    conn.close()
    n_big5 = df['League_ID'].isin(BIG5_LIDS).sum()
    n_other = len(df) - n_big5
    print(f'  测试集: {len(df):,} 行  BIG5={n_big5}  非BIG5={n_other}')
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
# Model Loading + Inference
# ─────────────────────────────────────────────────────────────────────

def load_models(model_dir: str, tags: dict) -> dict:
    """tags = {'H_Full': 'Model_H_Full_v6_1', ...}"""
    from catboost import CatBoostRegressor
    models = {}
    for key, fname_stem in tags.items():
        path = os.path.join(model_dir, f'{fname_stem}.cbm')
        m = CatBoostRegressor(); m.load_model(path)
        models[key] = m
        print(f'  [{fname_stem}.cbm]  BestIter={m.get_best_iteration()}  '
              f'ValLoss={m.get_best_score().get("validation",{}).get("Poisson",float("nan")):.4f}')
    return models


def ensemble_predict(models: dict, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
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
            'match_id': row['match_id'], 'League_ID': row.get('League_ID', 0),
            'Season': row.get('Season', ''),
            'is_big5': int(row.get('League_ID', 0)) in BIG5_LIDS,
            'hs': int(row['target_home_score']), 'as_': int(row['target_away_score']),
            'ou_line': ou_line, 'ah_line': ah_line,
            'lam_h': lh, 'lam_a': la,
            'p_hw': p_hw, 'p_d': p_d, 'p_aw': p_aw,
            'p_ov': p_ov, 'p_un': p_un, 'p_hc': p_hc, 'p_ac': p_ac,
        })
    return pd.DataFrame(records)


# ─────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────

def compute_metrics(res: pd.DataFrame) -> dict:
    r = res.copy()
    r['actual_wdl'] = np.where(r['hs'] > r['as_'], 'home_win',
                      np.where(r['hs'] == r['as_'], 'draw', 'away_win'))
    total_g = r['hs'] + r['as_']
    r['actual_ou'] = np.where(total_g > r['ou_line'], 'over',
                     np.where(total_g < r['ou_line'], 'under', 'push'))
    adj = r['hs'] - r['as_'] + r['ah_line']
    r['actual_ah'] = np.where(adj > 1e-9, 'home',
                     np.where(adj < -1e-9, 'away', 'push'))

    r['pred_wdl'] = np.where(
        (r['p_hw'] >= r['p_d']) & (r['p_hw'] >= r['p_aw']), 'home_win',
        np.where(r['p_d'] >= r['p_aw'], 'draw', 'away_win'))
    wdl_acc = (r['pred_wdl'] == r['actual_wdl']).mean()

    def to_cum(row): return np.array([row['p_hw'], row['p_hw']+row['p_d'],
                                      row['p_hw']+row['p_d']+row['p_aw']])
    def act_cum(w): return {'home_win':np.array([1.,1.,1.]),
                             'draw':np.array([0.,1.,1.]),
                             'away_win':np.array([0.,0.,1.])}[w]
    rps_vals = [np.mean((to_cum(row) - act_cum(row['actual_wdl']))**2)
                for _, row in r.iterrows()]
    wdl_rps = float(np.mean(rps_vals))

    ou_v = r[r['actual_ou'] != 'push'].copy()
    ou_v['pred_ou'] = np.where(ou_v['p_ov'] >= ou_v['p_un'], 'over', 'under')
    ou_acc   = (ou_v['pred_ou'] == ou_v['actual_ou']).mean()
    ou_brier = float(np.mean((ou_v['p_ov'] - (ou_v['actual_ou'] == 'over').astype(float))**2))

    ah_v = r[r['actual_ah'] != 'push'].copy()
    ah_v['pred_ah'] = np.where(ah_v['p_hc'] >= ah_v['p_ac'], 'home', 'away')
    ah_acc = (ah_v['pred_ah'] == ah_v['actual_ah']).mean() if len(ah_v) > 0 else float('nan')

    lh_mae = float(np.mean(np.abs(r['lam_h'] - r['hs'])))
    la_mae = float(np.mean(np.abs(r['lam_a'] - r['as_'])))

    return {'n': len(r), 'ou_n': len(ou_v), 'ah_n': len(ah_v),
            'wdl_acc': wdl_acc, 'wdl_rps': wdl_rps,
            'ou_acc': ou_acc, 'ou_brier': ou_brier,
            'ah_acc': ah_acc, 'lam_h_mae': lh_mae, 'lam_a_mae': la_mae}


# ─────────────────────────────────────────────────────────────────────
# Bootstrap (V6.1 vs V5 and V6.1 vs V6 on BIG5)
# ─────────────────────────────────────────────────────────────────────

def paired_bootstrap_3(r_a: pd.DataFrame, r_b: pd.DataFrame,
                       label_a='V5', label_b='V6.1',
                       n_boot=1000, seed=42) -> dict:
    assert len(r_a) == len(r_b)
    rng = np.random.default_rng(seed)
    n   = len(r_a)

    def wdl_c(r):
        act = np.where(r['hs'] > r['as_'], 'home_win',
               np.where(r['hs'] == r['as_'], 'draw', 'away_win'))
        pred = np.where((r['p_hw']>=r['p_d'])&(r['p_hw']>=r['p_aw']),'home_win',
               np.where(r['p_d']>=r['p_aw'],'draw','away_win'))
        return (pred == act).astype(float)

    def ou_c(r):
        tg = r['hs'] + r['as_']
        act = np.where(tg > r['ou_line'], 'over',
               np.where(tg < r['ou_line'], 'under', 'push'))
        pred = np.where(r['p_ov'] >= r['p_un'], 'over', 'under')
        c = np.full(n, np.nan)
        mask = act != 'push'
        c[mask] = (pred[mask] == act[mask])
        return c

    def ah_c(r):
        adj = r['hs'] - r['as_'] + r['ah_line']
        act = np.where(adj > 1e-9, 'home', np.where(adj < -1e-9, 'away', 'push'))
        pred = np.where(r['p_hc'] >= r['p_ac'], 'home', 'away')
        c = np.full(n, np.nan)
        mask = act != 'push'
        c[mask] = (pred[mask] == act[mask])
        return c

    wa, wb = wdl_c(r_a), wdl_c(r_b)
    oa, ob = ou_c(r_a),  ou_c(r_b)
    aa, ab = ah_c(r_a),  ah_c(r_b)

    obs = {'wdl': np.nanmean(wb)-np.nanmean(wa),
           'ou':  np.nanmean(ob)-np.nanmean(oa),
           'ah':  np.nanmean(ab)-np.nanmean(aa)}

    boots = {k: np.empty(n_boot) for k in ['wdl','ou','ah']}
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boots['wdl'][i] = np.nanmean(wb[idx]) - np.nanmean(wa[idx])
        boots['ou'][i]  = np.nanmean(ob[idx]) - np.nanmean(oa[idx])
        boots['ah'][i]  = np.nanmean(ab[idx]) - np.nanmean(aa[idx])

    result = {}
    for k in ['wdl','ou','ah']:
        lo, hi = np.percentile(boots[k], [2.5, 97.5])
        sig = '*' if lo > 0 or hi < 0 else ''
        result[k] = {'obs': obs[k], 'lo': lo, 'hi': hi, 'sig': sig,
                     'label_a': label_a, 'label_b': label_b}
    return result


# ─────────────────────────────────────────────────────────────────────
# Three-way table printer
# ─────────────────────────────────────────────────────────────────────

def three_way_table(m5: dict, m6: dict, m61: dict, label: str) -> list[str]:
    lines = [f'### {label}  (n={m5["n"]:,})', '']
    lines.append(f'| 指标 | V5 | V6 | V6.1 | V6.1−V5 | V6.1−V6 |')
    lines.append('|------|-----|-----|------|---------|---------|')

    rows = [
        ('WDL 准确率', 'wdl_acc', '+'),
        ('WDL RPS ↓',  'wdl_rps', '-'),
        ('OU 准确率',  'ou_acc',  '+'),
        ('OU Brier ↓', 'ou_brier', '-'),
        ('AH 准确率',  'ah_acc',  '+'),
        ('λ_h MAE ↓',  'lam_h_mae', '-'),
        ('λ_a MAE ↓',  'lam_a_mae', '-'),
    ]
    for label_r, key, better in rows:
        v5v = m5[key]; v6v = m6[key]; v61v = m61[key]
        d1 = v61v - v5v
        d2 = v61v - v6v
        # higher is better if '+', lower is better if '-'
        good1 = (d1 > 0) if better == '+' else (d1 < 0)
        good2 = (d2 > 0) if better == '+' else (d2 < 0)
        star1 = '✅' if good1 else ('—' if abs(d1) < 1e-4 else '❌')
        star2 = '✅' if good2 else ('—' if abs(d2) < 1e-4 else '❌')
        lines.append(
            f'| {label_r} | {v5v:.4f} | {v6v:.4f} | {v61v:.4f} '
            f'| {d1:+.4f} {star1} | {d2:+.4f} {star2} |')
    lines.append(f'')
    return lines


# ─────────────────────────────────────────────────────────────────────
# Per-League BIG5 table
# ─────────────────────────────────────────────────────────────────────

def per_league_big5(r5, r6, r61) -> list[str]:
    lines = []
    header = '| League | n | V5_WDL | V6_WDL | V6.1_WDL | ΔWDL(61-5) | V5_OU | V6_OU | V6.1_OU | ΔOU(61-5) | V5_AH | V6.1_AH | ΔAH(61-5) |'
    sep    = '|---|---|---|---|---|---|---|---|---|---|---|---|---|'
    lines += [header, sep]

    for lid in sorted(BIG5_LIDS):
        f5  = r5[r5['League_ID'] == lid]
        f6  = r6[r6['League_ID'] == lid]
        f61 = r61[r61['League_ID'] == lid]
        if len(f5) < 10: continue
        m5  = compute_metrics(f5)
        m6  = compute_metrics(f6)
        m61 = compute_metrics(f61)
        name = LEAGUE_NAMES.get(int(lid), str(lid))
        lines.append(
            f'| {name} | {m5["n"]} '
            f'| {m5["wdl_acc"]:.3f} | {m6["wdl_acc"]:.3f} | {m61["wdl_acc"]:.3f} '
            f'| {m61["wdl_acc"]-m5["wdl_acc"]:+.3f} '
            f'| {m5["ou_acc"]:.3f} | {m6["ou_acc"]:.3f} | {m61["ou_acc"]:.3f} '
            f'| {m61["ou_acc"]-m5["ou_acc"]:+.3f} '
            f'| {m5["ah_acc"]:.3f} | {m61["ah_acc"]:.3f} '
            f'| {m61["ah_acc"]-m5["ah_acc"]:+.3f} |')
    return lines


# ─────────────────────────────────────────────────────────────────────
# OU Calibration Plot
# ─────────────────────────────────────────────────────────────────────

def ou_calib_plot(r5, r6, r61, out_path: str, title_suffix=''):
    try:
        import matplotlib; matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        def calibrate(res):
            v = res[res['hs']+res['as_'] != res['ou_line']].copy()
            v['actual_over'] = (v['hs']+v['as_'] > v['ou_line']).astype(float)
            v['bucket'] = pd.cut(v['p_ov'], bins=10, labels=False)
            return v.groupby('bucket').agg(
                pm=('p_ov','mean'), am=('actual_over','mean'), n=('p_ov','count')
            ).reset_index()

        g5 = calibrate(r5); g6 = calibrate(r6); g61 = calibrate(r61)

        fig, ax = plt.subplots(figsize=(9, 6))
        ax.plot([0,1],[0,1],'k--',alpha=0.35,label='Perfect')
        ax.scatter(g5['pm'],  g5['am'],  s=g5['n']/3,  c='steelblue', alpha=0.8, label='V5',   marker='o')
        ax.plot(g5['pm'],    g5['am'],  'b-', alpha=0.4)
        ax.scatter(g6['pm'],  g6['am'],  s=g6['n']/3,  c='orange',    alpha=0.8, label='V6',   marker='D')
        ax.plot(g6['pm'],    g6['am'],  color='orange', alpha=0.4, linestyle='--')
        ax.scatter(g61['pm'], g61['am'], s=g61['n']/3, c='tomato',    alpha=0.8, label='V6.1', marker='s')
        ax.plot(g61['pm'],   g61['am'], 'r-', alpha=0.4)
        ax.set_xlabel('Predicted p(Over)')
        ax.set_ylabel('Actual Over Rate')
        ax.set_title(f'OU Calibration: V5 / V6 / V6.1{title_suffix}')
        ax.legend(); ax.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(out_path, dpi=120); plt.close()
        print(f'  OU 校准图 → {out_path}')
    except Exception as e:
        print(f'  校准图失败: {e}')


# ─────────────────────────────────────────────────────────────────────
# Build Report
# ─────────────────────────────────────────────────────────────────────

def build_report(m5_g, m6_g, m61_g,   # global
                 m5_b, m6_b, m61_b,   # BIG5
                 m5_o, m6_o, m61_o,   # other (K/J/澳超)
                 boot_v61_v5,          # bootstrap V6.1 vs V5 (BIG5)
                 boot_v61_v6,          # bootstrap V6.1 vs V6 (BIG5)
                 league_lines: list[str],
                 inst_v5, inst_v6, inst_v61) -> str:

    lines = []
    a = lines.append

    a('# V6.1 fd_fallback 清洗效应隔离实验报告')
    a(''); a(f'**生成日期**: 2026-05-11')
    a(f'**测试集**: mart_lambda_dataset_v6_train split=test (全量 1,525 行)')
    a(f'**V5**: models_v5_lambda/  **V6**: models/v6_prototype/  **V6.1**: models/v6_1_clean/')
    a(''); a('---'); a('')

    # 1. Instrumentation
    a('## 1. 模型 Instrumentation 三方对比')
    a('')
    a('| 版本 | 模型 | BestIter | TotalIter | TrainLoss | ValLoss |')
    a('|------|------|----------|-----------|-----------|---------|')
    for v, inst in [('V5', inst_v5), ('V6', inst_v6), ('V6.1', inst_v61)]:
        tags = (['H_Full','A_Full','H_Pure','A_Pure'] if v == 'V5' else
                [f'H_Full_v6{"_1" if v=="V6.1" else ""}',
                 f'A_Full_v6{"_1" if v=="V6.1" else ""}',
                 f'H_Pure_v6{"_1" if v=="V6.1" else ""}',
                 f'A_Pure_v6{"_1" if v=="V6.1" else ""}'])
        for tag in tags:
            d = inst.get(tag, {})
            a(f'| {v} | {tag} | {d.get("best_iter","?")} | {d.get("total_iter","?")} '
              f'| {d.get("train_loss",float("nan")):.4f} | {d.get("val_loss",float("nan")):.4f} |')
    a(''); a('---'); a('')

    # 2. Three-way tables
    a('## 2. 三方指标对照')
    a('')
    for section_lines in [
        three_way_table(m5_g,  m6_g,  m61_g,  '全局 (1,525 行)'),
        three_way_table(m5_b,  m6_b,  m61_b,  '仅 BIG5 (EPL/La Liga/Bundesliga/Ligue 1/Serie A)'),
        three_way_table(m5_o,  m6_o,  m61_o,  '仅 非BIG5 (K联赛/J联赛/澳超) — V6.1 OOD 预警'),
    ]:
        for l in section_lines: a(l)
    a('---'); a('')

    # 3. Bootstrap
    a('## 3. BIG5 Bootstrap 显著性检验 (1,000×)')
    a('')
    a('### V6.1 vs V5 (BIG5 子集)')
    a('')
    a('| 指标 | Δ (V6.1−V5) | 95% CI | 显著？ |')
    a('|------|------------|--------|-------|')
    for k, label in [('wdl','WDL 准确率'),('ou','OU 准确率'),('ah','AH 准确率')]:
        b = boot_v61_v5[k]
        sig = '✅ **显著改善**' if (b['sig']=='*' and b['obs']>0) else \
              ('❌ 显著退化' if (b['sig']=='*' and b['obs']<0) else '— 不显著')
        a(f'| {label} | {b["obs"]:+.4f} | [{b["lo"]:+.4f}, {b["hi"]:+.4f}] | {sig} |')
    a('')
    a('### V6.1 vs V6 (BIG5 子集)')
    a('')
    a('| 指标 | Δ (V6.1−V6) | 95% CI | 显著？ |')
    a('|------|------------|--------|-------|')
    for k, label in [('wdl','WDL 准确率'),('ou','OU 准确率'),('ah','AH 准确率')]:
        b = boot_v61_v6[k]
        sig = '✅ **显著改善**' if (b['sig']=='*' and b['obs']>0) else \
              ('❌ 显著退化' if (b['sig']=='*' and b['obs']<0) else '— 不显著')
        a(f'| {label} | {b["obs"]:+.4f} | [{b["lo"]:+.4f}, {b["hi"]:+.4f}] | {sig} |')
    a(''); a('---'); a('')

    # 4. Per-league BIG5
    a('## 4. BIG5 各联赛细拆')
    a('')
    for l in league_lines: a(l)
    a(''); a('---'); a('')

    # 5. OU Calibration
    a('## 5. OU 校准图')
    a('')
    a('![全局 OU 校准](../models/v6_1_clean/ou_calib_all.png)')
    a('')
    a('![BIG5 OU 校准](../models/v6_1_clean/ou_calib_big5.png)')
    a(''); a('---'); a('')

    # 6. Conclusions
    a('## 6. 结论')
    a('')

    # 6a: V6.1 on BIG5 vs V5
    b5_wdl_d = m61_b['wdl_acc'] - m5_b['wdl_acc']
    b5_ou_d  = m61_b['ou_acc']  - m5_b['ou_acc']
    b5_ah_d  = m61_b['ah_acc']  - m5_b['ah_acc']
    b5_rps_d = m61_b['wdl_rps'] - m5_b['wdl_rps']
    b5_brier_d = m61_b['ou_brier'] - m5_b['ou_brier']
    sig_count = sum(1 for k in ['wdl','ou','ah']
                    if boot_v61_v5[k]['sig']=='*' and boot_v61_v5[k]['obs']>0)

    a('### (a) BIG5 上 V6.1 是否显著优于 V5？')
    a('')
    big5_win = sum([b5_wdl_d > 0, b5_ou_d > 0, b5_ah_d > 0,
                    b5_rps_d < 0, b5_brier_d < 0])
    if big5_win >= 4 and sig_count >= 1:
        a('✅ **是，V6.1 在 BIG5 上显著优于 V5**')
    elif big5_win >= 3:
        a('⚠️ **V6.1 在 BIG5 上方向性优于 V5，但统计显著性有限**')
    else:
        a('❌ **V6.1 在 BIG5 上未能超越 V5**')
    a('')
    a(f'- WDL acc: V5={m5_b["wdl_acc"]:.4f} → V6.1={m61_b["wdl_acc"]:.4f} ({b5_wdl_d:+.4f})')
    a(f'- OU acc:  V5={m5_b["ou_acc"]:.4f}  → V6.1={m61_b["ou_acc"]:.4f}  ({b5_ou_d:+.4f})')
    a(f'- AH acc:  V5={m5_b["ah_acc"]:.4f}  → V6.1={m61_b["ah_acc"]:.4f}  ({b5_ah_d:+.4f})')
    a(f'- 统计显著改善: {sig_count}/3 个指标')
    a('')

    # 6b: fd_fallback 稀释效应
    gap_wdl = m61_b['wdl_acc'] - m6_b['wdl_acc']
    gap_ou  = m61_b['ou_acc']  - m6_b['ou_acc']
    gap_ah  = m61_b['ah_acc']  - m6_b['ah_acc']
    a('### (b) fd_fallback 是否真的稀释了 V6？')
    a('')
    a(f'V6.1 BIG5 − V6 BIG5 gap（越大说明稀释越明显）：')
    a(f'- WDL: {gap_wdl:+.4f}  OU: {gap_ou:+.4f}  AH: {gap_ah:+.4f}')
    dilution = sum([gap_wdl > 0.005, gap_ou > 0.005, gap_ah > 0.005])
    if dilution >= 2:
        a(f'**✅ 是，fd_fallback 对 BIG5 表现有明显稀释**（≥2 个指标 gap > 0.5pp）')
    elif dilution == 1:
        a(f'**⚠️ 部分稀释**（1 个指标 gap > 0.5pp）')
    else:
        a(f'**— 稀释效应较小**（gap < 0.5pp）')
    a('')

    # 6c: Production strategy
    a('### (c) 生产策略建议')
    a('')
    if big5_win >= 4:
        a('推荐 **路线 X：混合部署**')
        a('- V6.1 用于 BIG5（EPL/La Liga/Bundesliga/Ligue 1/Serie A）')
        a('- V5 继续用于 K/J/澳超（V6.1 为 OOD，退化严重）')
        a('- 待 NowGoal backfill 完成后，V7 统一覆盖全联赛')
    else:
        a('推荐 **路线 Y：等待 NowGoal backfill**')
        a('- 当前 V6.1 BIG5 改善不够显著，混合部署增加工程复杂度不值得')
        a('- 补齐 25/26 OU 数据后（~1,375 场），K/J/澳超数据质量提升，训 V7')
    a('')

    # 6d: Next step
    a('### (d) 下一步推荐')
    a('')
    if big5_win >= 4 and sig_count >= 1:
        a('**直接进 P0.10（titan_odds_spider 改造）**')
        a('- V6.1 在 BIG5 上有统计显著改善，可以先替换 BIG5 推理')
        a('- titan_odds_spider 改造（为 backfill 提供数据源）与模型替换可并行')
    else:
        a('**先做 NowGoal OU backfill（25/26 赛季 1,375 场）**')
        a('- 补齐数据 → 重训 V7 → 再评估是否 BIG5 & K/J/澳超 全联赛替换')
        a('- titan_odds_spider 改造也应推进（为 backfill pipeline 铺路）')
    a('')

    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    print('='*65)
    print('  V5 / V6 / V6.1 三方对照评估')
    print('='*65)

    # 1. 加载数据
    print('\n[1] 加载测试集')
    df_raw = load_test_data()
    df, feat_full, feat_pure = prep_features(df_raw.copy(),)

    print(f'\n[2] 特征: feat_full={len(feat_full)}  feat_pure={len(feat_pure)}')

    # 2. 加载模型
    print('\n[3] 加载 V5 模型')
    m5_tags = {'H_Full':'Model_H_Full','A_Full':'Model_A_Full',
               'H_Pure':'Model_H_Pure','A_Pure':'Model_A_Pure'}
    models_v5 = load_models(V5_DIR, m5_tags)
    rho_v5    = json.load(open(os.path.join(V5_DIR,'rho.json')))

    print('\n[4] 加载 V6 模型')
    m6_tags = {'H_Full':'Model_H_Full_v6','A_Full':'Model_A_Full_v6',
               'H_Pure':'Model_H_Pure_v6','A_Pure':'Model_A_Pure_v6'}
    models_v6 = load_models(V6_DIR, m6_tags)
    rho_v6    = json.load(open(os.path.join(V6_DIR,'rho_v6.json')))

    print('\n[5] 加载 V6.1 模型')
    m61_tags = {'H_Full':'Model_H_Full_v6_1','A_Full':'Model_A_Full_v6_1',
                'H_Pure':'Model_H_Pure_v6_1','A_Pure':'Model_A_Pure_v6_1'}
    models_v61 = load_models(V61_DIR, m61_tags)
    rho_v61    = json.load(open(os.path.join(V61_DIR,'rho_v6_1.json')))

    # instrumentation
    def get_inst(models, key_map):
        inst = {}
        for key, fname in key_map.items():
            m = models[key]
            bi  = m.get_best_iteration()
            evs = m.get_evals_result()
            tot = len(evs.get('validation',{}).get('Poisson',[]))
            tl  = m.get_best_score().get('learn',{}).get('Poisson', float('nan'))
            vl  = m.get_best_score().get('validation',{}).get('Poisson', float('nan'))
            label = fname.replace('Model_','')
            inst[label] = {'best_iter':bi,'total_iter':tot,'train_loss':tl,'val_loss':vl}
        return inst

    inst_v5  = get_inst(models_v5,  m5_tags)
    inst_v6  = get_inst(models_v6,  m6_tags)
    inst_v61 = get_inst(models_v61, m61_tags)

    # 3. 推理
    print('\n[6] V5 推理')
    lh5, la5 = ensemble_predict(models_v5, df)
    res_v5   = run_inference(df, lh5, la5, rho_v5)

    print('[7] V6 推理')
    lh6, la6 = ensemble_predict(models_v6, df)
    res_v6   = run_inference(df, lh6, la6, rho_v6)

    print('[8] V6.1 推理')
    lh61, la61 = ensemble_predict(models_v61, df)
    res_v61    = run_inference(df, lh61, la61, rho_v61)

    # 4. 分层指标
    print('\n[9] 计算指标 (全局 / BIG5 / 非BIG5)')
    # global
    m5_g  = compute_metrics(res_v5)
    m6_g  = compute_metrics(res_v6)
    m61_g = compute_metrics(res_v61)

    # BIG5
    b5_mask = res_v5['is_big5']
    m5_b  = compute_metrics(res_v5[b5_mask].reset_index(drop=True))
    m6_b  = compute_metrics(res_v6[b5_mask].reset_index(drop=True))
    m61_b = compute_metrics(res_v61[b5_mask].reset_index(drop=True))

    # non-BIG5
    o_mask = ~b5_mask
    m5_o  = compute_metrics(res_v5[o_mask].reset_index(drop=True))
    m6_o  = compute_metrics(res_v6[o_mask].reset_index(drop=True))
    m61_o = compute_metrics(res_v61[o_mask].reset_index(drop=True))

    # 打印摘要
    print(f'\n  {"指标":<14}  {"V5":>8}  {"V6":>8}  {"V6.1":>8}  {"Δ(61-5)":>8}  {"Δ(61-6)":>8}')
    print('  ' + '─'*60)
    for key, lbl in [('wdl_acc','WDL Acc'),('ou_acc','OU Acc'),('ah_acc','AH Acc'),
                     ('lam_h_mae','λ_h MAE'),('lam_a_mae','λ_a MAE')]:
        for scope, m5, m6, m61, tag in [
            ('全局', m5_g, m6_g, m61_g, ''),
            ('BIG5', m5_b, m6_b, m61_b, '[BIG5]'),
        ]:
            d1 = m61[key]-m5[key]; d2 = m61[key]-m6[key]
            print(f'  {lbl:<14} {tag:<6} {m5[key]:>8.4f}  {m6[key]:>8.4f}  {m61[key]:>8.4f}  {d1:>+8.4f}  {d2:>+8.4f}')

    # 5. Bootstrap (BIG5)
    print('\n[10] Bootstrap (BIG5, 1000×)')
    r5_b  = res_v5[b5_mask].reset_index(drop=True)
    r6_b  = res_v6[b5_mask].reset_index(drop=True)
    r61_b = res_v61[b5_mask].reset_index(drop=True)

    boot_61v5 = paired_bootstrap_3(r5_b,  r61_b, label_a='V5',  label_b='V6.1')
    boot_61v6 = paired_bootstrap_3(r6_b,  r61_b, label_a='V6',  label_b='V6.1')

    print(f'\n  V6.1 vs V5 (BIG5):')
    for k,lbl in [('wdl','WDL'),('ou','OU'),('ah','AH')]:
        b = boot_61v5[k]
        print(f'    {lbl}: Δ={b["obs"]:+.4f}  95%CI=[{b["lo"]:+.4f},{b["hi"]:+.4f}]  '
              f'{"✅ 显著" if b["sig"]=="*" and b["obs"]>0 else "—"}')
    print(f'\n  V6.1 vs V6 (BIG5):')
    for k,lbl in [('wdl','WDL'),('ou','OU'),('ah','AH')]:
        b = boot_61v6[k]
        print(f'    {lbl}: Δ={b["obs"]:+.4f}  95%CI=[{b["lo"]:+.4f},{b["hi"]:+.4f}]  '
              f'{"✅ 显著" if b["sig"]=="*" and b["obs"]>0 else "—"}')

    # 6. Per-league BIG5
    print('\n[11] Per-League BIG5')
    league_lines = per_league_big5(res_v5, res_v6, res_v61)
    for l in league_lines: print(' ', l)

    # 7. OU calibration plots
    ou_calib_plot(res_v5, res_v6, res_v61,
                  os.path.join(V61_DIR, 'ou_calib_all.png'), '')
    ou_calib_plot(res_v5[b5_mask].reset_index(drop=True),
                  res_v6[b5_mask].reset_index(drop=True),
                  res_v61[b5_mask].reset_index(drop=True),
                  os.path.join(V61_DIR, 'ou_calib_big5.png'), ' (BIG5)')

    # 8. Report
    report = build_report(
        m5_g, m6_g, m61_g,
        m5_b, m6_b, m61_b,
        m5_o, m6_o, m61_o,
        boot_61v5, boot_61v6,
        league_lines,
        inst_v5, inst_v6, inst_v61,
    )
    rpath = os.path.join(REPORT_DIR, 'v6_1_eval.md')
    with open(rpath, 'w') as f: f.write(report)
    print(f'\n  报告 → {rpath}')
    print('\n' + '='*65 + '\n  三方评估完成\n' + '='*65)


if __name__ == '__main__':
    main()
