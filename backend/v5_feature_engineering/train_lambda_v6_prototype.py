#!/usr/bin/env python3
"""
train_lambda_v6_prototype.py — Dual Poisson Regression + Dixon-Coles ρ  [V6 原型]

框架：
  训练 4 个 CatBoost Poisson Regressor：
    Model_H_Full_v6 / Model_A_Full_v6  — 含全部赔率特征
    Model_H_Pure_v6 / Model_A_Pure_v6  — 仅保留盘口线，不含赔率值

  然后估计全局 Dixon-Coles ρ + 各联赛独立 ρ。

V6 vs V5 改动（4 处）:
  [C1] SQL: SELECT * FROM mart_lambda_dataset_v6_train（10,158 行，含 21/22 + 22/23）
  [C2] MODEL_DIR: models/v6_prototype/（硬隔离，不覆盖 V5 生产模型）
  [C3] 模型/ρ/SHAP 产物加 _v6 后缀（Model_H_Full_v6.cbm / rho_v6.json / shap_*_v6.png）
  [C4] META_COLS 加 'is_fd_fallback'（审计标志，不进特征集）

输出：
  ./models/v6_prototype/Model_*_v6.cbm   CatBoost 模型
  ./models/v6_prototype/rho_v6.json      全局 + 联赛 ρ
  ./models/v6_prototype/shap_*_v6.png    SHAP Top-20 图

CLI:
  python train_lambda_v6_prototype.py             # 正式训练
  python train_lambda_v6_prototype.py --dry-run   # 10 步 dry-run，保存到 /tmp/v6_dryrun/

CLAUDE.md §3：唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations
import argparse, json, os, sys, time, warnings, sqlite3
import numpy as np
import pandas as pd
from scipy import stats as ss
from scipy.optimize import minimize_scalar
from catboost import CatBoostRegressor, Pool
warnings.filterwarnings('ignore')

# ─── 路径 ───────────────────────────────────────────────────────────
DB_PATH   = '/home/ubuntu/app/backend/football_uk.db'
# [C2] V6 专属输出目录，与 V5 生产目录完全隔离
MODEL_DIR = '/home/ubuntu/app/backend/models/v6_prototype'
os.makedirs(MODEL_DIR, exist_ok=True)

# ─── 联赛映射 ────────────────────────────────────────────────────────
LEAGUE_NAMES = {47:'英超', 55:'西甲', 87:'德甲', 53:'法甲', 54:'意甲',
                113:'澳超', 223:'J联赛', 9080:'K联赛'}

# ─── CatBoost 参数（与 V5 完全相同）──────────────────────────────────
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
# 原则：排除 raw odds、fair/implied 概率、赔率变动；保留盘口线
ODDS_PATTERN_KEYWORDS = [
    'raw_home', 'raw_away', 'raw_draw',      # 原始赔率
    'fair_home', 'fair_draw', 'fair_away',    # fair value
    'implied',                                # implied probability
    'ah_implied_diff',                        # derived from odds
    'ah_raw_home', 'ah_raw_away',             # AH raw odds
    'ah_odds_movement',                       # odds change
    'closing_eu_raw', 'closing_ah_raw',       # closing raw odds
    'closing_ou_raw',
    'closing_eu_fair', 'closing_ah_fair',     # closing fair
    'closing_ou_fair',
    'open_eu_fair', 'open_ah_fair',           # open fair
    'open_ou_fair',
    'eu_odds', 'eu_implied',                  # EU odds
]

# [C4] 元信息列（不进模型）— 新增 is_fd_fallback
META_COLS = [
    'match_id', 'match_date', 'Season',
    'Home_Team_ID', 'Away_Team_ID',
    'Home_Team_Name', 'Away_Team_Name',
    'days_from_latest', 'sample_weight', 'split',
    'ah_source',         # 来源标识，非特征
    'ah_line_category',  # 文本分类，处理后可用，此处保守排除
    'is_fd_fallback',    # [C4] 审计标志（OU 来源 footballdata），不进特征集
]

TARGET_COLS = ['target_home_score', 'target_away_score']


# ─────────────────────────────────────────────────────────────────────
# 1. 数据加载
# ─────────────────────────────────────────────────────────────────────

def load_dataset() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    # [C1] 读 V6 训练集（10,158 行，含 21/22+22/23，无 is_fd_fallback 过滤）
    df = pd.read_sql_query('SELECT * FROM mart_lambda_dataset_v6_train', conn)
    conn.close()
    print(f'  总行数: {len(df)}  列数: {len(df.columns)}')
    # 打印 is_fd_fallback 分布（审计用）
    if 'is_fd_fallback' in df.columns:
        fb_cnt = df['is_fd_fallback'].sum()
        print(f'  is_fd_fallback=1: {int(fb_cnt)} 行 ({fb_cnt/len(df)*100:.1f}%)')
    return df


# ─────────────────────────────────────────────────────────────────────
# 2. 特征清洗 + 两组 feature set
# ─────────────────────────────────────────────────────────────────────

def prepare_features(df: pd.DataFrame):
    """返回 (df_clean, feat_full, feat_pure, cat_features)"""

    # 2a. 删除 NULL 率 > 40% 的列
    n = len(df)
    null_rates = df.isnull().mean()
    drop_high_null = null_rates[null_rates > 0.40].index.tolist()
    if drop_high_null:
        print(f'  删除 NULL>40% 列 ({len(drop_high_null)}): {drop_high_null[:5]}...')
        df = df.drop(columns=drop_high_null, errors='ignore')

    # 2b. 确定特征候选（剔除 meta + target）
    all_cols = set(df.columns)
    non_feat = set(META_COLS + TARGET_COLS)
    candidate_cols = [c for c in df.columns if c not in non_feat]

    # 2c. Full feature set = 所有候选
    feat_full = candidate_cols.copy()

    # 2d. Pure feature set = 排除赔率类
    def is_odds_col(col: str) -> bool:
        col_lower = col.lower()
        return any(kw.lower() in col_lower for kw in ODDS_PATTERN_KEYWORDS)

    feat_pure = [c for c in candidate_cols if not is_odds_col(c)]

    # 2e. cat_features = ['League_ID']（整数型但应作类别）
    cat_features = ['League_ID'] if 'League_ID' in feat_full else []

    # 2f. NULL 填充 -999
    for c in feat_full:
        if df[c].dtype in [np.float64, np.float32, float, np.int64, np.int32, int]:
            df[c] = df[c].fillna(-999)
        elif df[c].dtype == object:
            df[c] = df[c].fillna('__NA__')

    print(f'  feat_full: {len(feat_full)} 列')
    print(f'  feat_pure: {len(feat_pure)} 列  '
          f'(排除 {len(feat_full)-len(feat_pure)} 个赔率列)')
    print(f'  cat_features: {cat_features}')

    return df, feat_full, feat_pure, cat_features


# ─────────────────────────────────────────────────────────────────────
# 3. 训练单个模型（含 instrumentation 输出）
# ─────────────────────────────────────────────────────────────────────

def train_one(name: str, X_tr, y_tr, w_tr, X_val, y_val,
              cat_features: list, params: dict,
              model_dir: str) -> CatBoostRegressor:
    print(f'\n  ── {name} ──')
    print(f'     train={len(X_tr):,}  val={len(X_val):,}  features={X_tr.shape[1]}')

    model = CatBoostRegressor(**params)
    t0 = time.time()

    train_pool = Pool(X_tr, y_tr, weight=w_tr, cat_features=cat_features)
    val_pool   = Pool(X_val, y_val, cat_features=cat_features)

    model.fit(train_pool, eval_set=val_pool, use_best_model=True)
    elapsed = time.time() - t0

    bi       = model.get_best_iteration()
    total_it = len(model.get_evals_result().get('validation', {}).get('Poisson', []))
    tr_loss  = model.get_best_score()['learn']['Poisson']
    val_loss = model.get_best_score()['validation']['Poisson']
    print(f'     BestIter={bi}  TotalIter={total_it}  '
          f'TrainLoss={tr_loss:.4f}  ValLoss={val_loss:.4f}  用时={elapsed:.0f}s')

    # ── Instrumentation: val loss 最后 100 步 ──────────────────────────
    val_history = model.get_evals_result().get('validation', {}).get('Poisson', [])
    if val_history:
        tail = val_history[-100:]
        print(f'     [Instrumentation] Val Poisson loss — 最后 {len(tail)} 步:')
        step_start = max(0, total_it - len(tail))
        for i, v in enumerate(tail[::10]):  # 每10步打一个，避免刷屏
            print(f'       step {step_start + i*10 + 1:>4}: {v:.5f}')
        print(f'       ... (best={val_loss:.5f} @ iter {bi})')

    save_path = os.path.join(model_dir, f'{name}.cbm')
    model.save_model(save_path)
    print(f'     保存到 {save_path}')

    return model


# ─────────────────────────────────────────────────────────────────────
# 4. 回归评估
# ─────────────────────────────────────────────────────────────────────

def evaluate(model, X, y_true, name: str) -> dict:
    preds = model.predict(X)
    preds = np.clip(preds, 1e-4, None)
    y = y_true.values.astype(float)
    residuals = y - preds
    rmse = np.sqrt(np.mean(residuals ** 2))
    mae  = np.mean(np.abs(residuals))
    corr = np.corrcoef(preds, y)[0, 1]
    return dict(model=name, rmse=rmse, mae=mae, corr=corr, residual_mean=residuals.mean())


# ─────────────────────────────────────────────────────────────────────
# 5. Dixon-Coles ρ（向量化）
# ─────────────────────────────────────────────────────────────────────

def dc_tau(h: np.ndarray, a: np.ndarray,
           lh: np.ndarray, la: np.ndarray, rho: float) -> np.ndarray:
    tau = np.ones(len(lh))
    tau[(h==0)&(a==0)] = 1 - lh[(h==0)&(a==0)] * la[(h==0)&(a==0)] * rho
    tau[(h==0)&(a==1)] = 1 + lh[(h==0)&(a==1)] * rho
    tau[(h==1)&(a==0)] = 1 + la[(h==1)&(a==0)] * rho
    tau[(h==1)&(a==1)] = 1 - rho
    return np.clip(tau, 1e-10, None)


def dc_neg_loglik(rho: float, lh: np.ndarray, la: np.ndarray,
                  h: np.ndarray, a: np.ndarray, w: np.ndarray) -> float:
    tau = dc_tau(h, a, lh, la, rho)
    log_p = (ss.poisson.logpmf(h, lh) +
             ss.poisson.logpmf(a, la) +
             np.log(tau))
    return -float(np.sum(w * log_p))


def estimate_rho(lh: np.ndarray, la: np.ndarray,
                 h: np.ndarray, a: np.ndarray, w: np.ndarray,
                 bounds=(-0.20, 0.10)) -> tuple[float, bool]:
    result = minimize_scalar(
        dc_neg_loglik,
        bounds=bounds,
        method='bounded',
        args=(lh, la, h, a, w),
    )
    return result.x, result.success


# ─────────────────────────────────────────────────────────────────────
# 6. SHAP Top-20
# ─────────────────────────────────────────────────────────────────────

def shap_top20(model: CatBoostRegressor, X: pd.DataFrame,
               name: str, feat_names: list, model_dir: str) -> pd.DataFrame:
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(X[:500])          # 500 样本够快
        mean_abs  = np.abs(shap_vals).mean(axis=0)
        top_idx   = np.argsort(mean_abs)[::-1][:20]
        top_df    = pd.DataFrame({
            'feature': [feat_names[i] for i in top_idx],
            'mean_abs_shap': mean_abs[top_idx],
        })

        # 绘图（[C3] 文件名已含 _v6 后缀，因 name 参数含 _v6）
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 7))
        ax.barh(top_df['feature'][::-1], top_df['mean_abs_shap'][::-1], color='steelblue')
        ax.set_xlabel('Mean |SHAP value|')
        ax.set_title(f'SHAP Top-20: {name}')
        plt.tight_layout()
        # [C3] shap_Model_H_Full_v6.png 等（name 已含 _v6）
        path = os.path.join(model_dir, f'shap_{name}.png')
        plt.savefig(path, dpi=120)
        plt.close()
        print(f'     SHAP 图 → {path}')
        return top_df
    except Exception as e:
        print(f'     SHAP 失败: {e}')
        # 用 CatBoost 内置 feature importance 作替代
        fi = model.get_feature_importance(type='FeatureImportance')
        top_idx = np.argsort(fi)[::-1][:20]
        return pd.DataFrame({
            'feature': [feat_names[i] for i in top_idx],
            'mean_abs_shap': fi[top_idx],
        })


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true',
                        help='10 步快速验证，模型保存到 /tmp/v6_dryrun/')
    args = parser.parse_args()

    # dry-run 模式：覆盖参数
    cb_params = dict(CB_PARAMS)
    model_dir = MODEL_DIR
    if args.dry_run:
        cb_params['iterations'] = 10
        cb_params['early_stopping_rounds'] = 5
        cb_params['verbose'] = 2
        model_dir = '/tmp/v6_dryrun'
        os.makedirs(model_dir, exist_ok=True)
        print('[DRY-RUN] iterations=10, 模型保存到 /tmp/v6_dryrun/')

    print('='*65)
    print('  train_lambda_v6_prototype  — Dual Poisson + Dixon-Coles ρ')
    print(f'  MODEL_DIR = {model_dir}')
    print('='*65)

    # ── 1. 加载 ───────────────────────────────────────────────────────
    print('\n[Step 1] 加载数据')
    df = load_dataset()
    df, feat_full, feat_pure, cat_features = prepare_features(df)

    # ── 2. Split ──────────────────────────────────────────────────────
    train_df = df[df['split'] == 'train'].copy()
    val_df   = df[df['split'] == 'val'].copy()
    test_df  = df[df['split'] == 'test'].copy()
    print(f'  split: train={len(train_df):,}  val={len(val_df):,}  test={len(test_df):,}')

    def make_xy(subset, feats):
        X = subset[feats].copy()
        return (X,
                subset['target_home_score'].astype(float),
                subset['target_away_score'].astype(float),
                subset['sample_weight'].astype(float))

    X_tr_f, y_tr_h, y_tr_a, w_tr = make_xy(train_df, feat_full)
    X_va_f, y_va_h, y_va_a, w_va = make_xy(val_df,   feat_full)

    X_tr_p, _, _, _ = make_xy(train_df, feat_pure)
    X_va_p, _, _, _ = make_xy(val_df,   feat_pure)

    cat_full = [f for f in cat_features if f in feat_full]
    cat_pure = [f for f in cat_features if f in feat_pure]

    # ── 3. 训练 4 个模型 ──────────────────────────────────────────────
    print('\n[Step 2] 训练 4 个 CatBoost Poisson Regressor')
    t_train_start = time.time()

    # [C3] 模型名加 _v6 后缀
    M_H_Full = train_one('Model_H_Full_v6', X_tr_f, y_tr_h, w_tr,
                          X_va_f, y_va_h, cat_full, cb_params, model_dir)
    M_A_Full = train_one('Model_A_Full_v6', X_tr_f, y_tr_a, w_tr,
                          X_va_f, y_va_a, cat_full, cb_params, model_dir)
    M_H_Pure = train_one('Model_H_Pure_v6', X_tr_p, y_tr_h, w_tr,
                          X_va_p, y_va_h, cat_pure, cb_params, model_dir)
    M_A_Pure = train_one('Model_A_Pure_v6', X_tr_p, y_tr_a, w_tr,
                          X_va_p, y_va_a, cat_pure, cb_params, model_dir)

    t_train_total = time.time() - t_train_start
    print(f'\n  4 模型总训练时间: {t_train_total:.0f}s ({t_train_total/60:.1f}min)')

    if args.dry_run:
        print('\n[DRY-RUN] 清理 /tmp/v6_dryrun/ 模型文件...')
        import shutil
        shutil.rmtree('/tmp/v6_dryrun', ignore_errors=True)
        print('[DRY-RUN] 完成 — 脚本可以正常运行，无错误')
        return

    # ── 4. 回归评估 ───────────────────────────────────────────────────
    print('\n[Step 3] Val 集回归评估')
    evals = [
        evaluate(M_H_Full, X_va_f, y_va_h, 'Model_H_Full_v6'),
        evaluate(M_A_Full, X_va_f, y_va_a, 'Model_A_Full_v6'),
        evaluate(M_H_Pure, X_va_p, y_va_h, 'Model_H_Pure_v6'),
        evaluate(M_A_Pure, X_va_p, y_va_a, 'Model_A_Pure_v6'),
    ]
    print(f'\n  {"模型":<18}  {"RMSE":>7}  {"MAE":>7}  {"Corr":>7}  {"残差均值":>9}  {"质量"}')
    print('  ' + '─'*68)
    for e in evals:
        grade = ('✅ 优秀' if e['rmse'] < 1.0 else
                 '✅ 可用' if e['rmse'] < 1.3 else
                 '⚠️  较弱' if e['rmse'] < 1.5 else '❌ 不可用')
        print(f'  {e["model"]:<18}  {e["rmse"]:>7.4f}  {e["mae"]:>7.4f}  '
              f'{e["corr"]:>7.4f}  {e["residual_mean"]:>9.4f}  {grade}')

    # ── 5. Dixon-Coles ρ（全局）──────────────────────────────────────
    print('\n[Step 4] Dixon-Coles ρ 估计（全局，训练集）')

    lh_tr = np.clip(M_H_Full.predict(X_tr_f), 1e-4, None)
    la_tr = np.clip(M_A_Full.predict(X_tr_f), 1e-4, None)
    h_tr  = y_tr_h.values.astype(int)
    a_tr  = y_tr_a.values.astype(int)

    rho_global, ok = estimate_rho(lh_tr, la_tr, h_tr, a_tr, w_tr.values)
    print(f'  全局 ρ = {rho_global:.4f}  (success={ok})')
    in_range = -0.15 <= rho_global <= 0.10
    print(f'  {"✅ 在学术标杆范围 [-0.15,+0.10] 内" if in_range else "⚠️  超出标杆范围，检查数据"}')

    # ── 6. 各联赛 ρ ───────────────────────────────────────────────────
    print('\n[Step 5] 各联赛独立 ρ 估计（n>200 才估）')
    rho_by_league: dict[str, float] = {}
    print(f'  {"联赛":<10}  {"ρ":>8}  {"n":>6}  {"状态"}')
    print('  ' + '─'*38)
    for lid in [47, 55, 87, 53, 54, 113, 223, 9080]:
        mask = train_df['League_ID'] == lid
        n_lid = mask.sum()
        if n_lid < 200:
            print(f'  {LEAGUE_NAMES[lid]:<10}  {"—":>8}  {n_lid:>6}  样本不足')
            continue
        idx = train_df.index[mask]
        lh_l = lh_tr[train_df.index.get_indexer(idx)]
        la_l = la_tr[train_df.index.get_indexer(idx)]
        h_l  = h_tr[train_df.index.get_indexer(idx)]
        a_l  = a_tr[train_df.index.get_indexer(idx)]
        w_l  = w_tr.values[train_df.index.get_indexer(idx)]
        rho_l, _ = estimate_rho(lh_l, la_l, h_l, a_l, w_l)
        rho_by_league[str(lid)] = float(rho_l)
        marker = '✅' if -0.15 <= rho_l <= 0.10 else '⚠️ '
        print(f'  {LEAGUE_NAMES[lid]:<10}  {rho_l:>8.4f}  {n_lid:>6}  {marker}')

    # [C3] 保存 rho_v6.json
    rho_data = {'rho_global': float(rho_global), 'rho_by_league': rho_by_league}
    rho_path = os.path.join(model_dir, 'rho_v6.json')
    with open(rho_path, 'w') as f:
        json.dump(rho_data, f, indent=2, ensure_ascii=False)
    print(f'\n  rho_v6.json 保存 → {rho_path}')

    # ── 7. SHAP Top-20 ────────────────────────────────────────────────
    print('\n[Step 6] SHAP Top-20 分析')
    shap_results: dict[str, pd.DataFrame] = {}
    for model, X_val, feats, name in [
        (M_H_Full, X_va_f, feat_full, 'Model_H_Full_v6'),
        (M_A_Full, X_va_f, feat_full, 'Model_A_Full_v6'),
        (M_H_Pure, X_va_p, feat_pure, 'Model_H_Pure_v6'),
        (M_A_Pure, X_va_p, feat_pure, 'Model_A_Pure_v6'),
    ]:
        print(f'\n  {name}:')
        top_df = shap_top20(model, X_val, name, feats, model_dir)
        shap_results[name] = top_df
        for rank, (_, row) in enumerate(top_df.head(10).iterrows(), 1):
            print(f'     {rank:>2}. {row["feature"]:<50}  {row["mean_abs_shap"]:.4f}')

    # ── 8. 完整报告 ───────────────────────────────────────────────────
    print('\n' + '='*65)
    print('  最终训练报告 — V6 原型')
    print('='*65)

    # 模型详情（含 instrumentation）
    print('\n  ▌ 模型配置 + Instrumentation:')
    print(f'  {"模型":<18}  {"BestIter":>8}  {"TotalIter":>9}  {"TrainLoss":>9}  {"ValLoss":>8}')
    print('  ' + '─'*62)
    for m, name in [(M_H_Full,'H_Full_v6'),(M_A_Full,'A_Full_v6'),
                    (M_H_Pure,'H_Pure_v6'),(M_A_Pure,'A_Pure_v6')]:
        bi    = m.get_best_iteration()
        total = len(m.get_evals_result().get('validation', {}).get('Poisson', []))
        tl    = m.get_best_score()['learn']['Poisson']
        vl    = m.get_best_score()['validation']['Poisson']
        print(f'  {name:<18}  {bi:>8}  {total:>9}  {tl:>9.4f}  {vl:>8.4f}')

    # 精度对比
    print('\n  ▌ Val 集精度对比:')
    print(f'  {"模型":<18}  {"RMSE":>7}  {"MAE":>7}  {"Corr":>7}  {"质量"}')
    print('  ' + '─'*58)
    for e in evals:
        grade = ('✅ 优秀' if e['rmse'] < 1.0 else
                 '✅ 可用' if e['rmse'] < 1.3 else
                 '⚠️  较弱' if e['rmse'] < 1.5 else '❌ 不可用')
        print(f'  {e["model"]:<18}  {e["rmse"]:>7.4f}  {e["mae"]:>7.4f}  '
              f'{e["corr"]:>7.4f}  {grade}')

    # ρ 汇总
    print(f'\n  ▌ Dixon-Coles ρ (rho_v6.json):')
    print(f'    全局: {rho_global:.4f}')
    for lid_str, r in rho_by_league.items():
        print(f'    {LEAGUE_NAMES.get(int(lid_str), lid_str)}: {r:.4f}')

    # Phase 门控
    print('\n  ▌ Phase 1 通过判定:')
    best_rmse = min(e['rmse'] for e in evals)
    rho_ok    = -0.15 <= rho_global <= 0.10
    rmse_ok   = best_rmse < 1.3
    gate_pass = rmse_ok and rho_ok
    print(f'    最优 RMSE = {best_rmse:.4f}  {"✅ <1.3" if rmse_ok else "❌ ≥1.3"}')
    print(f'    全局 ρ   = {rho_global:.4f}  {"✅ ∈ [-0.15,+0.10]" if rho_ok else "❌ 超范围"}')
    print(f'\n    {"✅ PASS → 可进入 V5 vs V6 评估（Stage 4）" if gate_pass else "❌ FAIL → 检查特征 / 调参后重训"}')

    print('\n  ✅ train_lambda_v6_prototype 完成')
    print(f'  产物目录: {model_dir}/')


if __name__ == '__main__':
    main()
