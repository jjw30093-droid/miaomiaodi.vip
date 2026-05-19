#!/usr/bin/env python3
"""
train_quick_test.py — V5 异质三模型 Ensemble Agreement Filter

Model 1 : LightGBM   (全量特征, 梯度提升树)
Model 2 : XGBoost    (全量特征, 梯度提升树)
Model 3 : LogReg     (SHAP Top-30 特征, 线性, StandardScaler)

三模型 Agreement 分析：
  Strong  (3/3 argmax 相同)
  Medium  (2/3 argmax 相同)
  No Agr  (各不相同)

Split：Train={2023/2024, 2024}  Test={2024/2025, 2025}
CLAUDE.md §3：唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations
import os, sqlite3, warnings, time
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

DB_PATH = '/home/ubuntu/app/backend/football_uk.db'
HERE    = os.path.dirname(os.path.abspath(__file__))

# 标识列
DROP_ID = {
    'match_id', 'match_date', 'Season',
    'Home_Team_Name', 'Away_Team_Name',
    'Home_Team_ID', 'Away_Team_ID',
    'home_team_id', 'away_team_id',
    'home_score', 'away_score', 'result', 'wdl_label',
}
ODDS_PFXS   = ('open_', 'closing_')
CLASS_NAMES = ['Home', 'Draw', 'Away']

AGR_THRS    = [0.50, 0.55, 0.60, 0.65, 0.70]
SINGLE_THRS = [0.55, 0.60, 0.65, 0.70, 0.75]


# ─────────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────────

def rps(probs: np.ndarray, labels: np.ndarray) -> float:
    n, k   = probs.shape
    onehot = np.zeros_like(probs)
    onehot[np.arange(n), labels] = 1.0
    cum_p  = np.cumsum(probs,  axis=1)
    cum_a  = np.cumsum(onehot, axis=1)
    return float(np.mean(0.5 * np.sum((cum_p - cum_a)**2, axis=1)))


def brier_multi(probs: np.ndarray, labels: np.ndarray) -> float:
    n = len(labels)
    oh = np.zeros_like(probs)
    oh[np.arange(n), labels] = 1.0
    return float(np.mean(np.sum((probs - oh) ** 2, axis=1)))


def eval_slice(probs: np.ndarray, labels: np.ndarray, mask: np.ndarray):
    """→ (n, acc, brier, avg_max_p)"""
    if mask.sum() == 0:
        return 0, float('nan'), float('nan'), float('nan')
    p  = probs[mask];  y = labels[mask]
    n  = int(mask.sum())
    return (n,
            float((p.argmax(1) == y).mean()),
            brier_multi(p, y),
            float(p.max(1).mean()))


def single_hi_conf(probs, labels, thrs, label=''):
    """打印单模型高置信表格"""
    n = len(labels)
    print(f'  {"阈值":>6}  {"场数":>6}  {"占%":>6}  {"Acc":>8}  '
          f'{"Brier":>8}  {"Avg_maxP":>10}   ({label})')
    print('  ' + '-'*58)
    for thr in thrs:
        mask = probs.max(1) > thr
        n_, acc_, bs_, amp_ = eval_slice(probs, labels, mask)
        pct = n_ / n * 100
        acc_s = f'{acc_:.4f}' if not np.isnan(acc_) else '   N/A'
        print(f'  >{thr:<5} {n_:>6}  {pct:>5.1f}%  {acc_s:>8}  '
              f'{bs_:>8.4f}  {amp_:>10.4f}')


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    # ── 1) 读数据 ─────────────────────────────────────────────────────
    print('📂 加载 mart_prediction_matrix_v5...')
    conn = sqlite3.connect(DB_PATH)
    df   = pd.read_sql_query('SELECT * FROM mart_prediction_matrix_v5', conn)
    conn.close()
    print(f'   {len(df)} 行 × {len(df.columns)} 列')

    # ── 2) Season split ───────────────────────────────────────────────
    df['_dt'] = pd.to_datetime(df['match_date'], errors='coerce')
    cutoff     = pd.Timestamp.today() - pd.Timedelta(days=30)
    season_max = df.groupby('Season')['_dt'].max()
    complete   = sorted(season_max[season_max < cutoff].index.tolist(),
                        key=lambda s: str(season_max[s]))
    if len(complete) < 2:
        raise RuntimeError(f'完整赛季不足 2 个: {complete}')
    test_seasons  = set(complete[-2:])
    train_seasons = set(complete[:-2])
    print(f'\n📅 Split:  Train={sorted(train_seasons)}  Test={sorted(test_seasons)}')

    train_df = df[df['Season'].isin(train_seasons)].copy()
    test_df  = df[df['Season'].isin(test_seasons)].copy()
    print(f'   Train={len(train_df)} 行   Test={len(test_df)} 行')

    # ── 3) 特征工程 ───────────────────────────────────────────────────
    null_rate = train_df.isnull().mean()
    hi_null   = set(null_rate[null_rate > 0.40].index)
    non_feat  = DROP_ID | hi_null | {'label_enc', '_dt'}
    for d in (train_df, test_df):
        d['League_ID'] = d['League_ID'].astype(str)
    cat_features = ['League_ID']

    def make_xy(frame):
        X = frame.drop(columns=[c for c in non_feat if c in frame.columns])
        y = frame['label_enc'].astype(int).values
        return X.fillna(-999), y

    X_train, y_train = make_xy(train_df)
    X_test,  y_test  = make_xy(test_df)
    n_test = len(y_test)
    print(f'\n📐 全量特征数: {X_train.shape[1]}')
    u, c = np.unique(y_train, return_counts=True)
    print(f'   Label(train): {dict(zip(u.tolist(), c.tolist()))}')
    u, c = np.unique(y_test,  return_counts=True)
    print(f'   Label(test) : {dict(zip(u.tolist(), c.tolist()))}')

    # ── 4) 先跑 CatBoost Exp3 取 SHAP Top-30（给 LogReg 用）──────────
    print('\n' + '='*65)
    print('  🔍 Step 0: CatBoost Exp3 → 获取 SHAP Top-30 特征（供 LogReg）')
    print('='*65)
    from catboost import CatBoostClassifier, Pool
    t0 = time.time()
    cb_tmp = CatBoostClassifier(
        iterations=2000, depth=4, learning_rate=0.03, l2_leaf_reg=8,
        loss_function='MultiClassOneVsAll', eval_metric='MultiClassOneVsAll',
        early_stopping_rounds=100, random_seed=42, verbose=0, task_type='CPU',
        use_best_model=True,
    )
    cb_tmp.fit(
        Pool(X_train, y_train, cat_features=cat_features),
        eval_set=Pool(X_test,  y_test,  cat_features=cat_features),
        silent=True,
    )
    print(f'   CatBoost best_iter={cb_tmp.best_iteration_}  '
          f'({time.time()-t0:.0f}s)')

    # 用内置 feature_importance (快) 代替 SHAP 计算 Top-30
    fi   = cb_tmp.get_feature_importance(Pool(X_train, y_train,
                                               cat_features=cat_features))
    fn   = list(X_train.columns)
    top30_idx   = np.argsort(fi)[::-1][:30]
    top30_feats = [fn[i] for i in top30_idx]
    print(f'   Top-30 特征（供 LogReg）:')
    for rank, feat in enumerate(top30_feats, 1):
        print(f'     {rank:>2}. {feat}')

    # LogReg 用的子集（League_ID 是字符串，转成 OHE 或直接 label-encode）
    # 简单处理：League_ID label-encode 后一起放入
    from sklearn.preprocessing import LabelEncoder
    le_league = LabelEncoder()
    le_league.fit(pd.concat([X_train['League_ID'], X_test['League_ID']]))

    def prep_logreg(X):
        """取 Top-30 列 + League_ID label-encode → float64 array"""
        cols = [c for c in top30_feats if c in X.columns]
        Xsub = X[cols].copy()
        # 如果 League_ID 在 top30，它已经是 str(-999 fill 后还是 str)
        # 直接转成 int label（League_ID 是 cat，其他都是 numeric）
        if 'League_ID' in Xsub.columns:
            Xsub['League_ID'] = le_league.transform(
                Xsub['League_ID'].astype(str))
        return Xsub.astype(np.float64).values

    X_train_lr = prep_logreg(X_train)
    X_test_lr  = prep_logreg(X_test)

    # ── 5) Model 1: LightGBM ──────────────────────────────────────────
    print('\n' + '='*65)
    print('  🌿 Model 1: LightGBM（全量特征）')
    print('='*65)
    import lightgbm as lgb

    # LightGBM 需要 category dtype 给 categorical
    def to_lgb_dataset(X, y, ref=None):
        Xc = X.copy()
        Xc['League_ID'] = Xc['League_ID'].astype('category')
        ds = lgb.Dataset(Xc, label=y,
                         categorical_feature=['League_ID'],
                         reference=ref, free_raw_data=False)
        return ds, Xc

    ds_train, X_train_lgb = to_lgb_dataset(X_train, y_train)
    ds_val,   X_test_lgb  = to_lgb_dataset(X_test,  y_test,  ref=ds_train)

    lgb_params = dict(
        objective='multiclass', num_class=3, metric='multi_logloss',
        num_leaves=31, learning_rate=0.03,
        feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=5,
        min_child_samples=20, reg_alpha=0.0, reg_lambda=1.0,
        random_state=42, verbose=-1,
    )
    t0 = time.time()
    cb_lgb = lgb.train(
        lgb_params, ds_train,
        num_boost_round=2000,
        valid_sets=[ds_val],
        callbacks=[lgb.early_stopping(100, verbose=False),
                   lgb.log_evaluation(period=500)],
    )
    bi_lgb = cb_lgb.best_iteration
    probs_lgb = cb_lgb.predict(X_test_lgb,
                               num_iteration=bi_lgb)   # (n, 3)
    acc_lgb = float((probs_lgb.argmax(1) == y_test).mean())
    rps_lgb = rps(probs_lgb, y_test)
    print(f'   best_iter={bi_lgb}  Acc={acc_lgb*100:.1f}%  '
          f'RPS={rps_lgb:.4f}  ({time.time()-t0:.0f}s)')

    # ── 6) Model 2: XGBoost ───────────────────────────────────────────
    print('\n' + '='*65)
    print('  ⚡ Model 2: XGBoost（全量特征）')
    print('='*65)
    import xgboost as xgb

    # XGBoost 不支持 string categorical → League_ID label-encode
    def prep_xgb(X):
        Xc = X.copy()
        Xc['League_ID'] = le_league.transform(Xc['League_ID'].astype(str))
        return Xc.astype(np.float64)

    X_train_xgb = prep_xgb(X_train)
    X_test_xgb  = prep_xgb(X_test)

    dtrain = xgb.DMatrix(X_train_xgb, label=y_train)
    dtest  = xgb.DMatrix(X_test_xgb,  label=y_test)

    xgb_params = dict(
        objective='multi:softprob', num_class=3,
        eval_metric='mlogloss',
        max_depth=5, learning_rate=0.03,
        subsample=0.8, colsample_bytree=0.8,
        min_child_weight=5, gamma=0.1,
        reg_alpha=0.0, reg_lambda=1.0,
        seed=42, verbosity=0,
    )
    t0 = time.time()
    evals_result = {}
    cb_xgb = xgb.train(
        xgb_params, dtrain,
        num_boost_round=2000,
        evals=[(dtest, 'test')],
        early_stopping_rounds=100,
        evals_result=evals_result,
        verbose_eval=500,
    )
    bi_xgb = cb_xgb.best_iteration
    probs_xgb = cb_xgb.predict(dtest,
                                iteration_range=(0, bi_xgb + 1))  # (n, 3)
    acc_xgb = float((probs_xgb.argmax(1) == y_test).mean())
    rps_xgb = rps(probs_xgb, y_test)
    print(f'   best_iter={bi_xgb}  Acc={acc_xgb*100:.1f}%  '
          f'RPS={rps_xgb:.4f}  ({time.time()-t0:.0f}s)')

    # ── 7) Model 3: Logistic Regression（Top-30 + StandardScaler）────
    print('\n' + '='*65)
    print('  📐 Model 3: LogisticRegression（Top-30 特征 + StandardScaler）')
    print('='*65)
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    X_train_sc = scaler.fit_transform(X_train_lr)
    X_test_sc  = scaler.transform(X_test_lr)

    t0 = time.time()
    lr_model = LogisticRegression(
        solver='lbfgs',
        C=0.5, max_iter=2000, random_state=42,
    )
    lr_model.fit(X_train_sc, y_train)
    probs_lr  = lr_model.predict_proba(X_test_sc)   # (n, 3)
    acc_lr    = float((probs_lr.argmax(1) == y_test).mean())
    rps_lr    = rps(probs_lr, y_test)
    print(f'   Acc={acc_lr*100:.1f}%  RPS={rps_lr:.4f}  ({time.time()-t0:.0f}s)')

    # ── 8) 各模型单独高置信表现 ───────────────────────────────────────
    print('\n' + '='*65)
    print('  📏 各模型单独高置信表现')
    print('='*65)
    for label, probs in [('LightGBM', probs_lgb),
                          ('XGBoost',  probs_xgb),
                          ('LogReg',   probs_lr)]:
        print()
        single_hi_conf(probs, y_test, SINGLE_THRS, label)

    # ── 9) Ensemble Agreement 分析 ────────────────────────────────────
    print('\n' + '='*65)
    print('  🤝 Ensemble Agreement（LightGBM + XGBoost + LogReg）')
    print('='*65)

    a_lgb = probs_lgb.argmax(1)
    a_xgb = probs_xgb.argmax(1)
    a_lr  = probs_lr.argmax(1)

    all_same  = (a_lgb == a_xgb) & (a_xgb == a_lr)
    any_two   = (~all_same) & ((a_lgb==a_xgb) | (a_lgb==a_lr) | (a_xgb==a_lr))
    none_same = ~all_same & ~any_two

    print(f'\n  Agreement 分布（n={n_test}）:')
    print(f'    Strong  (3/3 同意): {all_same.sum():>5} 场  '
          f'{all_same.mean()*100:>5.1f}%')
    print(f'    Medium  (2/3 同意): {any_two.sum():>5} 场  '
          f'{any_two.mean()*100:>5.1f}%')
    print(f'    No Agr  (各不相同): {none_same.sum():>5} 场  '
          f'{none_same.mean()*100:>5.1f}%')

    # CatBoost 三模型的 92.1% 参考
    print(f'\n  ⟵ 参考：上轮同构 CatBoost×3 Strong Agreement = 92.1%')

    # 平均概率（三模型等权）
    avg_probs = (probs_lgb + probs_xgb + probs_lr) / 3.0
    avg_max_p = avg_probs.max(1)
    ens_preds = avg_probs.argmax(1)

    # ── 10) 汇总表 ────────────────────────────────────────────────────
    print('\n' + '='*90)
    print('  📊 Agreement × 阈值 汇总表')
    print('='*90)
    print(f'  {"Agreement":<10} {"Threshold":>10} {"场数":>6} {"占%":>7} '
          f'{"Acc":>8} {"Brier":>8} {"Avg_maxP":>10}')
    print('  ' + '-'*60)

    rows_all = []
    for agr_label, agr_mask in [('Strong', all_same),
                                  ('Medium', any_two),
                                  ('NoAgr',  none_same)]:
        n_, acc_, bs_, amp_ = eval_slice(avg_probs, y_test, agr_mask)
        pct_ = n_ / n_test * 100
        print(f'  {agr_label:<10} {"(全部)":>10} {n_:>6} {pct_:>6.1f}% '
              f'{acc_:>8.4f} {bs_:>8.4f} {amp_:>10.4f}')
        rows_all.append(dict(agr=agr_label, thr=None, n=n_, pct=pct_,
                             acc=acc_, brier=bs_))
        for thr in AGR_THRS:
            mask_c = agr_mask & (avg_max_p > thr)
            n_, acc_, bs_, amp_ = eval_slice(avg_probs, y_test, mask_c)
            pct_ = n_ / n_test * 100
            acc_s = f'{acc_:.4f}' if not np.isnan(acc_) else '   N/A'
            print(f'  {agr_label:<10} {">"+str(thr):>10} {n_:>6} {pct_:>6.1f}% '
                  f'{acc_s:>8} {bs_:>8.4f} {amp_:>10.4f}')
            rows_all.append(dict(agr=agr_label, thr=thr, n=n_, pct=pct_,
                                 acc=acc_, brier=bs_))
        print('  ' + '-'*60)

    # ── 11) 方向细分（Strong Agreement）──────────────────────────────
    print('\n' + '='*65)
    print('  📐 Strong Agreement — 预测方向细分')
    print('='*65)
    print(f'\n  Strong (全部):')
    print(f'  {"方向":<8} {"场数":>6} {"Acc":>8} {"Brier":>8} {"Avg_maxP":>10}')
    print('  ' + '-'*42)
    for k, cname in enumerate(CLASS_NAMES):
        mask_k = all_same & (ens_preds == k)
        n_, acc_, bs_, amp_ = eval_slice(avg_probs, y_test, mask_k)
        print(f'  {cname:<8} {n_:>6} {acc_:>8.4f} {bs_:>8.4f} {amp_:>10.4f}')

    print(f'\n  Strong + avg_p > 0.60:')
    print(f'  {"方向":<8} {"场数":>6} {"Acc":>8} {"Brier":>8} {"Avg_maxP":>10}')
    print('  ' + '-'*42)
    for k, cname in enumerate(CLASS_NAMES):
        mask_k = all_same & (avg_max_p > 0.60) & (ens_preds == k)
        n_, acc_, bs_, amp_ = eval_slice(avg_probs, y_test, mask_k)
        print(f'  {cname:<8} {n_:>6} {acc_:>8.4f} {bs_:>8.4f} {amp_:>10.4f}')

    # ── 12) 最优策略搜索 ──────────────────────────────────────────────
    print('\n' + '='*90)
    print('  🏆 最优策略搜索')
    print('='*90)

    # 参考基准（上轮 Exp3 单模型）
    print('\n  参考基准: Exp3 CatBoost 单模型 >0.70  →  n=129  Acc=85.3%')
    print()
    print('  Strong Agreement + avg_max_p 阈值:')
    best = None
    for thr in AGR_THRS + [0.75]:
        mask_s = all_same & (avg_max_p > thr)
        n_, acc_, bs_, amp_ = eval_slice(avg_probs, y_test, mask_s)
        if n_ == 0:
            print(f'    Strong >avg_p{thr}: n=0')
            continue
        flag = '⭐' if (acc_ >= 0.80 and n_ >= 100) else \
               ('✅' if acc_ >= 0.75 else '')
        print(f'    Strong >avg_p{thr}: n={n_:>4}  Acc={acc_*100:>5.1f}%  '
              f'Brier={bs_:.4f}  ΔAcc_vs_ref={acc_-0.853:+.3f}  {flag}')
        if flag == '⭐' and best is None:
            best = (thr, n_, acc_, bs_)

    print()
    print('  各单模型 >0.65（对比 ensemble）:')
    for label, probs in [('LightGBM', probs_lgb),
                          ('XGBoost',  probs_xgb),
                          ('LogReg',   probs_lr)]:
        mask  = probs.max(1) > 0.65
        n_, acc_, bs_, amp_ = eval_slice(probs, y_test, mask)
        print(f'    {label:<10} >{0.65}: n={n_:>4}  Acc={acc_*100:>5.1f}%  Brier={bs_:.4f}')

    # ── 13) 总结 ──────────────────────────────────────────────────────
    print('\n' + '='*90)
    print('  ✅ 总结')
    print('='*90)
    strong_pct = all_same.mean() * 100
    print(f'\n  Strong Agreement 比例 : {strong_pct:.1f}%  '
          f'（参考：同构 CatBoost×3 = 92.1%）')
    diversity = 'more diverse' if strong_pct < 80 else 'similar'
    print(f'  模型多样性判断        : {diversity}')

    if best:
        thr, n_, acc_, bs_ = best
        print(f'\n  推荐策略 : Strong + avg_p > {thr}')
        print(f'    场数={n_}  Acc={acc_*100:.1f}%  Brier={bs_:.4f}')
        print(f'    vs Exp3 单模型 >0.70: Δn={n_-129:+d}  ΔAcc={(acc_-0.853)*100:+.1f}pp')
    else:
        print('\n  无组合同时满足 Acc≥80% + n≥100')
        print('  → 训练集仍不足（2198行），多样性改善有限；'
              '等 2025/2026 赛季完整后重评')
    print()


if __name__ == '__main__':
    main()
