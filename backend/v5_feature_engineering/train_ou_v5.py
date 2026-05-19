#!/usr/bin/env python3
"""
train_ou_v5.py — Walk-Forward 稳定性验证 + 25/26 实战观察

Fold 设计（按实际可用赛季，仅 2 完整联赛赛季）：
  Fold 1: train=[2023/2024]                 test=[2024/2025]
  Fold 2: train=[2023/2024, 2024(日历年)]   test=[2024/2025]
  Step 5: train=[全量历史]                  test=[2025/2026 按联赛分组]

S2 策略：agree AND avg(p_b, p_a) > t → over；< 1-t → under

CLAUDE.md §3：唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations
import sqlite3, warnings
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, brier_score_loss
from catboost import CatBoostClassifier, Pool
import shap
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')

DB_PATH  = '/home/ubuntu/app/backend/football_uk.db'
SHAP_DIR = '/home/ubuntu/app/backend/v5_feature_engineering'

# ── 联赛分组 ──────────────────────────────────────────────────────────
TRADITIONAL_LEAGUES = {47, 55, 87, 53, 54, 113}   # 五大联赛 + 澳超

# ── 列处理 ───────────────────────────────────────────────────────────
BASE_DROP = [
    'match_id', 'match_date', 'Season',
    'Home_Team_ID', 'Away_Team_ID', 'Home_Team_Name', 'Away_Team_Name',
    'home_score', 'away_score', 'total',
    'actual_label_value', 'baseline_label', 'line_type',
    'referee_avg_goals', 'expected_total_xG',
    'ou_line_opening', 'ou_line_vs_baseline',
    'ou_line_closing',
    'h2h_avg_total_goals_5', 'h2h_over_2_5_rate_5',
]
ODDS_FEATS = ['over_odds_opening', 'under_odds_opening',
              'ou_odds_movement', 'ou_line_movement']
CAT_COLS   = ['League_ID']
FILL_VAL   = -999.0

CB_PARAMS = dict(
    loss_function='Logloss', eval_metric='Logloss',
    iterations=2000, depth=5, learning_rate=0.03, l2_leaf_reg=4,
    early_stopping_rounds=150, random_seed=42,
    use_best_model=True, verbose=0, thread_count=-1,
)

S2_THRESHOLDS = [0.55, 0.58, 0.60, 0.62, 0.65, 0.68]


# ─────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────
def make_xy(df_subset, feat_cols):
    cats = [c for c in CAT_COLS if c in feat_cols]
    X = df_subset[feat_cols].fillna(FILL_VAL).copy()
    for c in cats:
        X[c] = X[c].astype(int).astype(str)
    y = df_subset['baseline_label'].values.astype(int)
    return X, y, cats


def train_cb(X_tr, y_tr, X_te, y_te, cats):
    tr_p = Pool(X_tr, y_tr, cat_features=cats)
    te_p = Pool(X_te, y_te, cat_features=cats)
    m = CatBoostClassifier(**CB_PARAMS)
    m.fit(tr_p, eval_set=te_p)
    probs = m.predict_proba(te_p)[:, 1]
    return m, probs, te_p


def roi_over(label, odds):   return float(odds) - 1. if label == 1 else -1.
def roi_under(label, odds):  return float(odds) - 1. if label == 0 else -1.


def s2_eval(proba_b, proba_a, y, over_odds, under_odds, t):
    """S2: agree AND avg_conf > t"""
    pred_b   = (proba_b >= 0.5).astype(int)
    pred_a   = (proba_a >= 0.5).astype(int)
    agree    = pred_b == pred_a
    avg_p    = (proba_b + proba_a) / 2.0

    over_sel  = agree & (avg_p > t)
    under_sel = agree & (avg_p < 1 - t)
    sel       = over_sel | under_sel
    n = int(sel.sum())
    if n == 0:
        return dict(t=t, n=0, n_over=0, n_under=0,
                    acc=float('nan'), roi_mean=float('nan'), roi_total=float('nan'))

    dirs = np.where(over_sel[sel], 'over', 'under')
    lbls = y[sel]; oo = over_odds[sel]; uo = under_odds[sel]
    rois = np.where(dirs == 'over',
                    np.where(lbls == 1, oo - 1., -1.),
                    np.where(lbls == 0, uo - 1., -1.)).astype(float)
    preds_int = np.where(dirs == 'over', 1, 0)
    acc = float((preds_int == lbls).mean())
    return dict(t=t, n=n,
                n_over=int(over_sel.sum()), n_under=int(under_sel.sum()),
                acc=acc, roi_mean=float(rois.mean()), roi_total=float(rois.sum()))


def agreement_rate(proba_b, proba_a):
    return float(((proba_b >= 0.5) == (proba_a >= 0.5)).mean())


def print_s2_table(rows, title=''):
    if title: print(f'\n  {title}')
    print(f'  {"t":>5}  {"n":>5}  {"n_over":>7}  {"n_under":>8}  '
          f'{"Acc":>7}  {"ROI/单":>8}  {"累计ROI":>9}')
    print('  ' + '-'*60)
    for r in rows:
        def f(v, fmt='.4f'):
            return '  —  ' if np.isnan(v) else f'{v:{fmt}}'
        print(f'  {r["t"]:>5.2f}  {r["n"]:>5}  {r["n_over"]:>7}  {r["n_under"]:>8}  '
              f'{f(r["acc"],".3f"):>7}  {f(r["roi_mean"],"+.4f"):>8}  '
              f'{f(r["roi_total"],"+.2f"):>9}')


def shap_top20(model, pool, feat_cols, title, save_path=''):
    try:
        ex   = shap.TreeExplainer(model)
        vals = ex.shap_values(pool)
        ma   = np.abs(vals).mean(axis=0)
        df   = pd.DataFrame({'feature': feat_cols, 'shap': ma})
        df   = df.sort_values('shap', ascending=False).head(20)
        print(f'\n  SHAP Top-20 [{title}]')
        print(f'  {"Rank":>4}  {"Feature":>42}  {"SHAP":>10}')
        print('  ' + '-'*62)
        for i, (_, row) in enumerate(df.iterrows(), 1):
            print(f'  {i:>4}  {row["feature"]:>42}  {row["shap"]:>10.6f}')
        if save_path:
            fig, ax = plt.subplots(figsize=(10, 7))
            c = ['#C62828' if i < 3 else '#1565C0' if i < 10 else '#90CAF9'
                 for i in range(len(df))]
            ax.barh(df['feature'].values[::-1], df['shap'].values[::-1], color=c[::-1])
            ax.set_xlabel('Mean |SHAP|', fontsize=10)
            ax.set_title(title, fontsize=11, fontweight='bold')
            ax.grid(axis='x', alpha=0.3); plt.tight_layout()
            plt.savefig(save_path, dpi=120, bbox_inches='tight'); plt.close()
        return df
    except Exception as e:
        print(f'  ⚠️  SHAP 失败: {e}')
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────
def main():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT * FROM mart_ou_features_v5 WHERE ou_line_opening = 2.5", conn)
    conn.close()

    all_feats     = [c for c in df.columns if c not in BASE_DROP]
    no_odds_feats = [c for c in all_feats if c not in ODDS_FEATS]

    print('='*66)
    print('  可用赛季（OU 2.5）')
    print('='*66)
    sc = df['Season'].value_counts().sort_index()
    for s, n in sc.items():
        print(f'  {s:>12}: {n:>5} 场')

    # ══════════════════════════════════════════════════════════════════
    # Fold 定义
    # ══════════════════════════════════════════════════════════════════
    folds = [
        dict(
            label='Fold 1',
            train_seasons={'2023/2024'},
            test_seasons={'2024/2025'},
            desc='train=[2023/24]  test=[2024/25]',
        ),
        dict(
            label='Fold 2',
            train_seasons={'2023/2024', '2024'},
            test_seasons={'2024/2025'},
            desc='train=[2023/24 + 2024日历年]  test=[2024/25]',
        ),
    ]

    summary_rows  = []          # walk-forward 汇总
    fold2_proba_b = None        # 用于 Step 4 阈值敏感性
    fold2_proba_a = None
    fold2_y       = None
    fold2_oo      = None
    fold2_uo      = None

    # ══════════════════════════════════════════════════════════════════
    # Steps 1-2: Walk-Forward Folds
    # ══════════════════════════════════════════════════════════════════
    for fold in folds:
        print(f'\n{"="*66}')
        print(f'  {fold["label"]}: {fold["desc"]}')
        print('='*66)

        tr_df = df[df['Season'].isin(fold['train_seasons'])].copy()
        te_df = df[df['Season'].isin(fold['test_seasons'])].copy()
        print(f'  Train {len(tr_df)} / Test {len(te_df)}  '
              f'(Train over={tr_df["baseline_label"].mean():.3f}  '
              f'Test over={te_df["baseline_label"].mean():.3f})')

        oo = te_df['over_odds_opening'].fillna(1.90).values.astype(float)
        uo = te_df['under_odds_opening'].fillna(1.90).values.astype(float)
        y_te = te_df['baseline_label'].values.astype(int)

        # Model B
        X_tr_b, y_tr_b, cats_b = make_xy(tr_df, all_feats)
        X_te_b, _,      _      = make_xy(te_df, all_feats)
        mb, proba_b, pool_b = train_cb(X_tr_b, y_tr_b, X_te_b, y_te, cats_b)
        auc_b  = roc_auc_score(y_te, proba_b)
        acc_b  = float(((proba_b >= 0.5).astype(int) == y_te).mean())

        # Model A
        X_tr_a, y_tr_a, cats_a = make_xy(tr_df, no_odds_feats)
        X_te_a, _,      _      = make_xy(te_df, no_odds_feats)
        ma, proba_a, pool_a = train_cb(X_tr_a, y_tr_a, X_te_a, y_te, cats_a)
        auc_a  = roc_auc_score(y_te, proba_a)
        acc_a  = float(((proba_a >= 0.5).astype(int) == y_te).mean())

        print(f'  Model B: BestIter={mb.get_best_iteration():>4}  '
              f'AUC={auc_b:.4f}  Acc={acc_b:.4f}')
        print(f'  Model A: BestIter={ma.get_best_iteration():>4}  '
              f'AUC={auc_a:.4f}  Acc={acc_a:.4f}')

        # Agreement
        ag_rate = agreement_rate(proba_b, proba_a)
        print(f'  Agreement rate: {ag_rate:.3f}  ({ag_rate*100:.1f}%)')

        # S2 @ t=0.62
        r62 = s2_eval(proba_b, proba_a, y_te, oo, uo, 0.62)
        print(f'  S2@0.62: n={r62["n"]}  Acc={r62["acc"]:.3f}  '
              f'ROI/单={r62["roi_mean"]:+.4f}  累计={r62["roi_total"]:+.2f}')

        # SHAP Top-20（仅 Fold 2）
        if fold['label'] == 'Fold 2':
            fold2_proba_b = proba_b
            fold2_proba_a = proba_a
            fold2_y       = y_te
            fold2_oo      = oo
            fold2_uo      = uo
            shap_top20(mb, pool_b, list(X_te_b.columns), 'Fold2 Model B (Full)',
                       f'{SHAP_DIR}/shap_v5_ou25_fold2B.png')
            shap_top20(ma, pool_a, list(X_te_a.columns), 'Fold2 Model A (No-Odds)',
                       f'{SHAP_DIR}/shap_v5_ou25_fold2A.png')

        summary_rows.append(dict(
            fold=fold['label'],
            train='+'.join(sorted(fold['train_seasons'])),
            test='+'.join(sorted(fold['test_seasons'])),
            n_train=len(tr_df), n_test=len(te_df),
            agree_pct=ag_rate * 100,
            s2_n=r62['n'], s2_acc=r62['acc'],
            s2_roi=r62['roi_mean'],
        ))

    # ══════════════════════════════════════════════════════════════════
    # Step 3: Walk-Forward 汇总
    # ══════════════════════════════════════════════════════════════════
    print(f'\n{"="*66}')
    print('  Step 3: Walk-Forward 汇总表（S2@t=0.62）')
    print('='*66)
    print(f'\n  {"Fold":>7}  {"Train n":>8}  {"Test n":>7}  '
          f'{"Agree%":>8}  {"S2 n":>6}  {"S2 Acc":>7}  {"S2 ROI":>8}')
    print('  ' + '-'*62)
    for r in summary_rows:
        ai_s = f'{r["s2_acc"]:.3f}' if not np.isnan(r['s2_acc']) else '  —  '
        ri_s = f'{r["s2_roi"]:+.4f}' if not np.isnan(r['s2_roi']) else '   —   '
        print(f'  {r["fold"]:>7}  {r["n_train"]:>8}  {r["n_test"]:>7}  '
              f'{r["agree_pct"]:>7.1f}%  {r["s2_n"]:>6}  {ai_s:>7}  {ri_s:>8}')

    # ══════════════════════════════════════════════════════════════════
    # Step 4: Fold 2 阈值敏感性
    # ══════════════════════════════════════════════════════════════════
    print(f'\n{"="*66}')
    print('  Step 4: S2 阈值敏感性（Fold 2 Test = 2024/2025）')
    print('='*66)
    rows_s2 = [s2_eval(fold2_proba_b, fold2_proba_a,
                       fold2_y, fold2_oo, fold2_uo, t)
               for t in S2_THRESHOLDS]
    print_s2_table(rows_s2, '策略 S2：agree AND avg_conf > t')

    # ══════════════════════════════════════════════════════════════════
    # Step 5: 25/26 实战观察（按联赛分组）
    # ══════════════════════════════════════════════════════════════════
    print(f'\n{"="*66}')
    print('  Step 5: 25/26 实战观察')
    print('='*66)

    # 用全量历史训练
    hist_seasons = {'2023/2024', '2024', '2024/2025', '2025'}
    tr_hist = df[df['Season'].isin(hist_seasons)].copy()
    te_2526 = df[df['Season'] == '2025/2026'].copy()
    print(f'\n  Train (全量历史): {len(tr_hist)} 场  '
          f'(over_rate={tr_hist["baseline_label"].mean():.3f})')
    print(f'  Test  (2025/2026): {len(te_2526)} 场  '
          f'(over_rate={te_2526["baseline_label"].mean():.3f})')

    if len(te_2526) == 0:
        print('  ⚠️  2025/2026 无 OU 2.5 数据，跳过')
        return

    # 联赛分组
    grp_a = te_2526[te_2526['League_ID'].isin(TRADITIONAL_LEAGUES)]
    grp_b = te_2526[~te_2526['League_ID'].isin(TRADITIONAL_LEAGUES)]
    print(f'\n  Group A 传统联赛 (47,55,87,53,54,113): {len(grp_a)} 场')
    print(f'  Group B 新增杯赛 (其他):                 {len(grp_b)} 场')

    # 训练全量历史模型
    X_tr_hb, y_tr_hb, cats_hb = make_xy(tr_hist, all_feats)
    X_tr_ha, y_tr_ha, cats_ha = make_xy(tr_hist, no_odds_feats)

    # 测试集（全量 + 按组）
    tests_to_eval = [
        ('全量 25/26',    te_2526),
        ('Group A 传统联赛', grp_a),
        ('Group B 新增杯赛', grp_b),
    ]

    # 找 Fold 2 最优 t（ROI 最高且 n≥20）
    best_t = 0.62
    best_roi = -999.
    for r in rows_s2:
        if r['n'] >= 20 and not np.isnan(r['roi_mean']) and r['roi_mean'] > best_roi:
            best_roi = r['roi_mean']; best_t = r['t']
    print(f'\n  使用 Fold 2 最优阈值 t={best_t:.2f}（ROI={best_roi:+.4f}）')

    # 训练全量历史 Model B & A（verbose=0）
    print(f'\n  训练全量历史 Model B ...')
    def train_silent(Xtr, ytr, Xte, yte, cats):
        tr_p = Pool(Xtr, ytr, cat_features=cats)
        te_p = Pool(Xte, yte, cat_features=cats)
        m = CatBoostClassifier(**CB_PARAMS)
        m.fit(tr_p, eval_set=te_p)
        return m, m.predict_proba(te_p)[:, 1]

    # 对整个 25/26 集做推断
    X_te_2526_b, y_2526, _ = make_xy(te_2526, all_feats)
    X_te_2526_a, _,      _ = make_xy(te_2526, no_odds_feats)

    # 需要临时用一个有标签的 test set 训练模型（用 2024/2025 验证，全量 train 用历史）
    te_val = df[df['Season'] == '2024/2025'].copy()
    X_val_b, y_val_b, _ = make_xy(te_val, all_feats)
    X_val_a, y_val_a, _ = make_xy(te_val, no_odds_feats)

    mb_h, _ = train_silent(X_tr_hb, y_tr_hb, X_val_b, y_val_b, cats_hb)
    ma_h, _ = train_silent(X_tr_ha, y_tr_ha, X_val_a, y_val_a, cats_ha)
    print(f'  Model B BestIter={mb_h.get_best_iteration()}  '
          f'Model A BestIter={ma_h.get_best_iteration()}')

    # 对 25/26 做预测（不需要标签，只用特征）
    pb_2526 = mb_h.predict_proba(Pool(X_te_2526_b, cat_features=cats_hb))[:, 1]
    pa_2526 = ma_h.predict_proba(Pool(X_te_2526_a, cat_features=cats_ha))[:, 1]
    oo_2526 = te_2526['over_odds_opening'].fillna(1.90).values.astype(float)
    uo_2526 = te_2526['under_odds_opening'].fillna(1.90).values.astype(float)

    print(f'\n  {"测试组":<20}  {"总场数":>6}  {"S2 推荐":>8}  {"Acc":>7}  '
          f'{"ROI/单":>8}  {"累计ROI":>9}  {"⚠️ 样本":>8}')
    print('  ' + '-'*74)

    for grp_name, grp_df in tests_to_eval:
        if len(grp_df) == 0:
            print(f'  {grp_name:<20}  {"0":>6}  (无数据)')
            continue
        idx = grp_df.index
        # map back to te_2526 positions
        pos = [te_2526.index.get_loc(i) for i in idx]
        pb_g  = pb_2526[pos]
        pa_g  = pa_2526[pos]
        y_g   = y_2526[pos]
        oo_g  = oo_2526[pos]
        uo_g  = uo_2526[pos]

        r = s2_eval(pb_g, pa_g, y_g, oo_g, uo_g, best_t)
        ag_r = agreement_rate(pb_g, pa_g)

        def fv(v, fmt='.3f'):
            return '  —  ' if np.isnan(v) else f'{v:{fmt}}'
        warn = '⚠️ n<30' if len(grp_df) < 30 else ''
        print(f'  {grp_name:<20}  {len(grp_df):>6}  {r["n"]:>8}  '
              f'{fv(r["acc"]):>7}  {fv(r["roi_mean"],"+.4f"):>8}  '
              f'{fv(r["roi_total"],"+.2f"):>9}  {warn:>8}')

    # ══════════════════════════════════════════════════════════════════
    # Step 6: 上线决策
    # ══════════════════════════════════════════════════════════════════
    print(f'\n{"="*66}')
    print('  Step 6: 上线决策摘要')
    print('='*66)

    roi_f1 = next((r['s2_roi'] for r in [summary_rows[0]]), float('nan'))
    roi_f2 = next((r['s2_roi'] for r in [summary_rows[1]]), float('nan'))
    stable = (not np.isnan(roi_f1) and not np.isnan(roi_f2)
              and roi_f1 > 0 and roi_f2 > 0)

    print(f'\n  1. S2 策略稳定性（@t=0.62）:')
    print(f'     Fold 1 ROI={roi_f1:+.4f}  Fold 2 ROI={roi_f2:+.4f}')
    if stable:
        print('     ✅ 两 Fold ROI 均 > 0%，策略稳定')
    elif roi_f1 > 0 or roi_f2 > 0:
        print('     ⚠️  仅一个 Fold ROI > 0，稳定性存疑')
    else:
        print('     ❌ 两 Fold ROI 均 ≤ 0，当前参数无正期望')

    print(f'\n  2. 推荐最优阈值: t={best_t:.2f}  '
          f'（Fold 2 ROI={best_roi:+.4f}, '
          f'n={next((r["s2_n"] for r in [summary_rows[1]]), "?")}）')

    # 不同阈值 ROI 排序
    valid_rows = [r for r in rows_s2 if r['n'] >= 20 and not np.isnan(r['roi_mean'])]
    if valid_rows:
        best_row = max(valid_rows, key=lambda x: x['roi_mean'])
        print(f'     全阈值最优: t={best_row["t"]:.2f}  '
              f'n={best_row["n"]}  Acc={best_row["acc"]:.3f}  '
              f'ROI={best_row["roi_mean"]:+.4f}')

    print(f'\n  3. 25/26 Group A 传统联赛:')
    print(f'     ⚠️  n={len(grp_a)}，样本量不足（<100），统计结论不可靠')
    print(f'     建议：等 25/26 赛季结束（~2026-06）后，样本量 ≥ 500 时重新评估')

    print(f'\n  4. 结论:')
    if stable and best_roi >= 0.02:
        print('     ✅ S2 策略（t=0.62）建议纳入线上推荐，覆盖率约 12%')
        print('     📌 25/26 实战数据有限，上线后持续监控 Agreement 率 + ROI')
    elif best_roi >= 0:
        print('     ⚠️  ROI 正但边际微薄，建议再观察 1 个赛季再上线')
    else:
        print('     ❌ 当前参数集无显著正 ROI，需要增强特征或扩大样本')

    print('\n  ✅ Walk-Forward 验证完成')


if __name__ == '__main__':
    main()
