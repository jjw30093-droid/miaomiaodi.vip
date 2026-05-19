#!/usr/bin/env python3
"""
evaluate_lambda_v5.py — Lambda 双模型 Test Set 全市场评估

流程：
  1. 加载 4 个 CatBoost 模型 + rho.json
  2. 重建训练时相同的 feat_full / feat_pure 特征集
  3. 对 954 个 test 样本推断 λ_h / λ_a（Full + Pure），Ensemble 0.6F + 0.4P
  4. 按联赛选 ρ，构建 Score Matrix，推断 WDL / OU / AH / BTTS / CS
  5. 写入 mart_lambda_predictions_test
  6. 多市场评估 + Agreement Filter + Tier 分析 + go/no-go 报告

Tier 定义：
  锁单: Full 与 Pure 方向一致 AND max_p > 0.65
  优选: Full 与 Pure 方向一致 AND max_p ∈ [0.55, 0.65)
  关注: 其余

go/no-go 基准（与 V5 WDL 比较）：
  V5 WDL baseline: Acc=51.5%  RPS=0.2055  high-conf acc=85.3%

CLAUDE.md §3：唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations
import json, math, os, sqlite3, warnings
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool

warnings.filterwarnings('ignore')
sys_path = os.path.dirname(os.path.abspath(__file__))
import sys; sys.path.insert(0, sys_path)
from inference_lambda import build_score_matrix, derive_wdl, derive_ou, derive_ah, derive_btts, derive_top_scores

# ─── 路径 ───────────────────────────────────────────────────────────
DB_PATH    = '/home/ubuntu/app/backend/football_uk.db'
MODEL_DIR  = '/home/ubuntu/app/backend/models_v5_lambda'

# ─── 联赛名称 ────────────────────────────────────────────────────────
LEAGUE_NAMES = {47:'英超', 55:'西甲', 87:'德甲', 53:'法甲', 54:'意甲',
                113:'澳超', 223:'J联赛', 9080:'K联赛'}

# ─── 特征列定义（与 train_lambda_v5.py 完全一致）─────────────────────
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

# ─── Tier 阈值 ────────────────────────────────────────────────────────
TIER_LOCK_THRESH   = 0.65  # 锁单
TIER_PRIME_THRESH  = 0.55  # 优选（lower bound）


# ─────────────────────────────────────────────────────────────────────
# 1. 数据加载
# ─────────────────────────────────────────────────────────────────────

def load_data(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query('SELECT * FROM mart_lambda_dataset_v5', conn)
    print(f'  总行数: {len(df)}  列数: {len(df.columns)}')
    return df


def build_feature_sets(df: pd.DataFrame):
    """重建 feat_full / feat_pure，与 train_lambda_v5.py 逻辑完全一致"""
    # 删除 NULL>40% 的列
    n = len(df)
    null_rates = df.isnull().mean()
    drop_high_null = null_rates[null_rates > 0.40].index.tolist()
    if drop_high_null:
        df = df.drop(columns=drop_high_null, errors='ignore')

    non_feat = set(META_COLS + TARGET_COLS)
    candidate_cols = [c for c in df.columns if c not in non_feat]

    def is_odds_col(col: str) -> bool:
        col_lower = col.lower()
        return any(kw.lower() in col_lower for kw in ODDS_PATTERN_KEYWORDS)

    feat_full = candidate_cols.copy()
    feat_pure = [c for c in candidate_cols if not is_odds_col(c)]
    cat_features = ['League_ID'] if 'League_ID' in feat_full else []

    # NULL 填充 -999
    for c in feat_full:
        if df[c].dtype in [np.float64, np.float32, float, np.int64, np.int32, int]:
            df[c] = df[c].fillna(-999)
        elif df[c].dtype == object:
            df[c] = df[c].fillna('__NA__')

    print(f'  feat_full: {len(feat_full)} 列  feat_pure: {len(feat_pure)} 列')
    return df, feat_full, feat_pure, cat_features


# ─────────────────────────────────────────────────────────────────────
# 2. 加载模型 + ρ
# ─────────────────────────────────────────────────────────────────────

def load_models():
    models = {}
    for name in ['Model_H_Full', 'Model_A_Full', 'Model_H_Pure', 'Model_A_Pure']:
        path = os.path.join(MODEL_DIR, f'{name}.cbm')
        m = CatBoostRegressor()
        m.load_model(path)
        models[name] = m
        print(f'  加载 {name}: {path}')

    rho_path = os.path.join(MODEL_DIR, 'rho.json')
    with open(rho_path) as f:
        rho_data = json.load(f)
    print(f'  加载 rho.json: global={rho_data["rho_global"]:.4f}  '
          f'leagues={list(rho_data["rho_by_league"].keys())}')
    return models, rho_data


# ─────────────────────────────────────────────────────────────────────
# 3. 推断 λ + 全市场
# ─────────────────────────────────────────────────────────────────────

def predict_lambda(models, rho_data, X_full: pd.DataFrame, X_pure: pd.DataFrame,
                   cat_features: list) -> dict[str, np.ndarray]:
    """返回每个模型的预测 λ 数组"""
    pool_f = Pool(X_full, cat_features=cat_features)
    pool_p = Pool(X_pure, cat_features=cat_features)

    lam_h_full = models['Model_H_Full'].predict(pool_f)
    lam_a_full = models['Model_A_Full'].predict(pool_f)
    lam_h_pure = models['Model_H_Pure'].predict(pool_p)
    lam_a_pure = models['Model_A_Pure'].predict(pool_p)

    # Ensemble
    lam_h = ENSEMBLE_FULL * lam_h_full + ENSEMBLE_PURE * lam_h_pure
    lam_a = ENSEMBLE_FULL * lam_a_full + ENSEMBLE_PURE * lam_a_pure

    # 保证非负
    lam_h = np.clip(lam_h, 0.01, None)
    lam_a = np.clip(lam_a, 0.01, None)

    return {
        'lam_h': lam_h, 'lam_a': lam_a,
        'lam_h_full': lam_h_full, 'lam_a_full': lam_a_full,
        'lam_h_pure': lam_h_pure, 'lam_a_pure': lam_a_pure,
    }


def predict_all_markets(
    lambdas: dict,
    rho_data: dict,
    league_ids: np.ndarray,
    ou_lines: np.ndarray,
    ah_lines: np.ndarray,
) -> list[dict]:
    """对每个样本推断全市场，返回 list of dicts"""
    rho_by_league = {int(k): v for k, v in rho_data['rho_by_league'].items()}
    rho_global = rho_data['rho_global']

    results = []
    n = len(lambdas['lam_h'])

    for i in range(n):
        lh = float(lambdas['lam_h'][i])
        la = float(lambdas['lam_a'][i])
        lh_full = float(lambdas['lam_h_full'][i])
        la_full = float(lambdas['lam_a_full'][i])
        lh_pure = float(lambdas['lam_h_pure'][i])
        la_pure = float(lambdas['lam_a_pure'][i])

        lid = int(league_ids[i])
        rho = rho_by_league.get(lid, rho_global)

        matrix = build_score_matrix(lh, la, rho)
        ph, pd_, pa = derive_wdl(matrix)
        byes, bno = derive_btts(matrix)
        top5 = derive_top_scores(matrix, top_n=5)

        # Agreement (Full vs Pure)
        def wdl_dir(lh_, la_):
            m_ = build_score_matrix(lh_, la_, rho)
            ph_, pd__, pa_ = derive_wdl(m_)
            return ['home_win', 'draw', 'away_win'][np.argmax([ph_, pd__, pa_])]

        wdl_dir_ens = ['home_win', 'draw', 'away_win'][np.argmax([ph, pd_, pa])]
        wdl_dir_full = wdl_dir(lh_full, la_full)
        wdl_dir_pure = wdl_dir(lh_pure, la_pure)
        wdl_agree = (wdl_dir_full == wdl_dir_pure)
        wdl_max_p = max(ph, pd_, pa)

        # OU
        ou_line = float(ou_lines[i]) if ou_lines[i] not in (None, -999) else None
        if ou_line is not None and not math.isnan(ou_line) and ou_line > 0:
            p_ov, p_un, p_push_ou = derive_ou(matrix, ou_line)
            ou_dir = 'over' if p_ov > p_un else 'under'

            def ou_dir_fn(lh_, la_):
                m_ = build_score_matrix(lh_, la_, rho)
                ov_, un_, _ = derive_ou(m_, ou_line)
                return 'over' if ov_ > un_ else 'under'

            ou_agree = (ou_dir_fn(lh_full, la_full) == ou_dir_fn(lh_pure, la_pure))
            ou_max_p = max(p_ov, p_un)
        else:
            p_ov = p_un = p_push_ou = ou_max_p = None
            ou_dir = None
            ou_agree = None

        # AH
        ah_line = float(ah_lines[i]) if ah_lines[i] not in (None, -999) else None
        if ah_line is not None and not math.isnan(ah_line):
            p_ahh, p_aha, p_push_ah = derive_ah(matrix, ah_line)
            ah_dir = 'ah_home' if p_ahh > p_aha else 'ah_away'

            def ah_dir_fn(lh_, la_):
                m_ = build_score_matrix(lh_, la_, rho)
                hc_, ac_, _ = derive_ah(m_, ah_line)
                return 'ah_home' if hc_ > ac_ else 'ah_away'

            ah_agree = (ah_dir_fn(lh_full, la_full) == ah_dir_fn(lh_pure, la_pure))
            ah_max_p = max(p_ahh, p_aha)
        else:
            p_ahh = p_aha = p_push_ah = ah_max_p = None
            ah_dir = None
            ah_agree = None

        # Tier（基于 WDL agreement + max_p）
        if wdl_agree:
            if wdl_max_p >= TIER_LOCK_THRESH:
                tier = '锁单'
            elif wdl_max_p >= TIER_PRIME_THRESH:
                tier = '优选'
            else:
                tier = '关注'
        else:
            tier = '关注'

        # Top scores 序列化
        top_scores_str = ';'.join(f'{h}-{a}:{p:.4f}' for h, a, p in top5)

        results.append({
            'lam_h': lh, 'lam_a': la,
            'lam_h_full': lh_full, 'lam_a_full': la_full,
            'lam_h_pure': lh_pure, 'lam_a_pure': la_pure,
            'rho': rho,
            'expected_total': lh + la,
            # WDL
            'p_home_win': ph, 'p_draw': pd_, 'p_away_win': pa,
            'wdl_pred': wdl_dir_ens,
            'wdl_agree': int(wdl_agree),
            'wdl_max_p': wdl_max_p,
            # OU
            'p_over': p_ov, 'p_under': p_un, 'p_push_ou': p_push_ou,
            'ou_pred': ou_dir,
            'ou_agree': int(ou_agree) if ou_agree is not None else None,
            'ou_max_p': ou_max_p,
            # AH
            'p_ah_home': p_ahh, 'p_ah_away': p_aha, 'p_push_ah': p_push_ah,
            'ah_pred': ah_dir,
            'ah_agree': int(ah_agree) if ah_agree is not None else None,
            'ah_max_p': ah_max_p,
            # BTTS
            'p_btts_yes': byes, 'p_btts_no': bno,
            # CS
            'top_scores': top_scores_str,
            # Tier
            'tier': tier,
        })

    return results


# ─────────────────────────────────────────────────────────────────────
# 4. 写入 mart_lambda_predictions_test
# ─────────────────────────────────────────────────────────────────────

def write_predictions(conn: sqlite3.Connection, test_df: pd.DataFrame,
                      results: list[dict]) -> pd.DataFrame:
    pred_df = pd.DataFrame(results)

    meta_cols = ['match_id', 'match_date', 'Season', 'League_ID',
                 'Home_Team_Name', 'Away_Team_Name',
                 'target_home_score', 'target_away_score',
                 'open_ou_line', 'ah_line_opening']
    existing_meta = [c for c in meta_cols if c in test_df.columns]

    out = pd.concat([
        test_df[existing_meta].reset_index(drop=True),
        pred_df.reset_index(drop=True),
    ], axis=1)

    conn.execute('DROP TABLE IF EXISTS mart_lambda_predictions_test')
    out.to_sql('mart_lambda_predictions_test', conn, if_exists='replace', index=False)
    conn.commit()
    print(f'  ✔ 写入 mart_lambda_predictions_test: {len(out)} 行 × {len(out.columns)} 列')
    return out


# ─────────────────────────────────────────────────────────────────────
# 5. 多市场评估
# ─────────────────────────────────────────────────────────────────────

def _rps_wdl(ph, pd_, pa, actual_wdl: str) -> float:
    """WDL RPS (Ranked Probability Score)，越低越好"""
    probs = [ph, pd_, pa]
    dirs  = ['home_win', 'draw', 'away_win']
    actual_idx = dirs.index(actual_wdl)
    actual_dist = [1.0 if i == actual_idx else 0.0 for i in range(3)]
    cum_p = np.cumsum(probs)
    cum_a = np.cumsum(actual_dist)
    return float(np.mean((cum_p[:-1] - cum_a[:-1]) ** 2))


def evaluate_wdl(df: pd.DataFrame) -> None:
    """WDL 评估：准确率 + RPS + 各联赛分布"""
    print('\n' + '─'*60)
    print('  WDL 市场评估')
    print('─'*60)

    # actual WDL
    df = df.copy()
    df['actual_wdl'] = df.apply(
        lambda r: 'home_win' if r.target_home_score > r.target_away_score
                  else ('draw' if r.target_home_score == r.target_away_score else 'away_win'),
        axis=1
    )

    # 准确率
    df['wdl_correct'] = df['wdl_pred'] == df['actual_wdl']
    acc = df['wdl_correct'].mean()
    print(f'  Overall WDL Accuracy: {acc:.3f}  ({df.wdl_correct.sum()}/{len(df)})')

    # RPS
    rps_vals = df.apply(
        lambda r: _rps_wdl(r.p_home_win, r.p_draw, r.p_away_win, r.actual_wdl), axis=1
    )
    rps = rps_vals.mean()
    print(f'  Overall WDL RPS:      {rps:.4f}  (V5 WDL baseline: 0.2055)')

    # 方向分布
    print(f'\n  预测方向分布:')
    for d, cnt in df['wdl_pred'].value_counts().items():
        pct = cnt/len(df)*100
        corr = df.loc[df['wdl_pred']==d,'wdl_correct'].mean()
        print(f'    {d:<12}: n={cnt:>4} ({pct:>5.1f}%)  acc={corr:.3f}')

    print(f'\n  实际方向分布:')
    for d, cnt in df['actual_wdl'].value_counts().items():
        print(f'    {d:<12}: n={cnt:>4} ({cnt/len(df)*100:>5.1f}%)')

    # 各联赛
    print(f'\n  各联赛 WDL 准确率:')
    for lid, grp in df.groupby('League_ID'):
        name = LEAGUE_NAMES.get(int(lid), str(int(lid)))
        a = grp['wdl_correct'].mean()
        r = grp.apply(lambda r: _rps_wdl(r.p_home_win, r.p_draw, r.p_away_win, r.actual_wdl), axis=1).mean()
        print(f'    {name:<8} ({int(lid):>5}): n={len(grp):>4}  acc={a:.3f}  rps={r:.4f}')

    # Agreement Filter 分析
    print(f'\n  Agreement Filter 分析（WDL）:')
    for agree_val, label in [(1, '一致'), (0, '分歧')]:
        sub = df[df['wdl_agree'] == agree_val]
        if len(sub) == 0:
            continue
        a = sub['wdl_correct'].mean()
        print(f'    {label} (n={len(sub):>4}): acc={a:.3f}')

    # Tier 分析（WDL）
    print(f'\n  Tier 分析（WDL）:')
    for tier in ['锁单', '优选', '关注']:
        sub = df[df['tier'] == tier]
        if len(sub) == 0:
            continue
        a = sub['wdl_correct'].mean()
        print(f'    {tier} (n={len(sub):>4}  {len(sub)/len(df)*100:.1f}%): acc={a:.3f}')

    # max_p 分组
    print(f'\n  按 max_p 分组 WDL 准确率:')
    bins = [0, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 1.0]
    labels_bins = ['<0.45','0.45-0.50','0.50-0.55','0.55-0.60','0.60-0.65','0.65-0.70','>=0.70']
    df['max_p_bin'] = pd.cut(df['wdl_max_p'], bins=bins, labels=labels_bins, right=False)
    for lb, grp in df.groupby('max_p_bin', observed=True):
        if len(grp) == 0:
            continue
        a = grp['wdl_correct'].mean()
        print(f'    {lb:<12}: n={len(grp):>4}  acc={a:.3f}')


def evaluate_ou(df: pd.DataFrame) -> None:
    """OU 评估"""
    print('\n' + '─'*60)
    print('  OU 市场评估')
    print('─'*60)

    sub = df.dropna(subset=['p_over', 'target_home_score', 'target_away_score']).copy()
    sub = sub[sub['open_ou_line'].notna() & (sub['open_ou_line'] != -999)]
    print(f'  有效 OU 样本: {len(sub)}/{len(df)}')
    if len(sub) == 0:
        print('  ⚠️  无有效 OU 样本')
        return

    sub['actual_total'] = sub['target_home_score'].astype(float) + sub['target_away_score'].astype(float)
    sub['actual_ou'] = sub.apply(
        lambda r: 'over' if r.actual_total > r.open_ou_line else
                  ('under' if r.actual_total < r.open_ou_line else 'push'),
        axis=1
    )

    valid = sub[sub['actual_ou'] != 'push']
    print(f'  去除 push 后: {len(valid)}')
    if len(valid) == 0:
        return

    acc = (valid['ou_pred'] == valid['actual_ou']).mean()
    print(f'  Overall OU Accuracy: {acc:.3f}  ({(valid["ou_pred"]==valid["actual_ou"]).sum()}/{len(valid)})')

    # 各 OU 线
    print(f'\n  按 OU 线分组:')
    for line, grp in valid.groupby('open_ou_line'):
        a = (grp['ou_pred'] == grp['actual_ou']).mean()
        pred_over = (grp['ou_pred'] == 'over').sum()
        act_over = (grp['actual_ou'] == 'over').sum()
        print(f'    OU {line:<5}: n={len(grp):>4}  acc={a:.3f}  pred_over={pred_over}  act_over={act_over}')

    # Agreement
    print(f'\n  Agreement Filter 分析（OU）:')
    for agree_val, label in [(1, '一致'), (0, '分歧')]:
        s = valid[valid['ou_agree'] == agree_val]
        if len(s) == 0:
            continue
        a = (s['ou_pred'] == s['actual_ou']).mean()
        print(f'    {label} (n={len(s):>4}): acc={a:.3f}')

    # Tier
    print(f'\n  Tier 分析（OU，基于 ou_max_p）:')
    valid = valid.copy()
    valid['ou_tier'] = valid.apply(
        lambda r: ('锁单' if r.ou_agree == 1 and r.ou_max_p >= TIER_LOCK_THRESH
                   else ('优选' if r.ou_agree == 1 and r.ou_max_p >= TIER_PRIME_THRESH
                         else '关注')),
        axis=1
    )
    for tier in ['锁单', '优选', '关注']:
        s = valid[valid['ou_tier'] == tier]
        if len(s) == 0:
            continue
        a = (s['ou_pred'] == s['actual_ou']).mean()
        print(f'    {tier} (n={len(s):>4}  {len(s)/len(valid)*100:.1f}%): acc={a:.3f}')


def evaluate_ah(df: pd.DataFrame) -> None:
    """AH 评估"""
    print('\n' + '─'*60)
    print('  AH 市场评估')
    print('─'*60)

    sub = df.dropna(subset=['p_ah_home', 'ah_line_opening']).copy()
    sub = sub[sub['ah_line_opening'] != -999]
    print(f'  有效 AH 样本: {len(sub)}/{len(df)}')
    if len(sub) == 0:
        print('  ⚠️  无有效 AH 样本')
        return

    def ah_outcome(row) -> str:
        hs = float(row.target_home_score)
        as_ = float(row.target_away_score)
        ah_line = float(row.ah_line_opening)
        # quarter-ball: average of two sub-legs
        frac = ah_line - math.floor(ah_line)
        is_qb = abs(frac - 0.25) < 1e-9 or abs(frac - 0.75) < 1e-9
        if is_qb:
            lower = math.floor(ah_line * 2) / 2
            upper = math.ceil(ah_line * 2) / 2
            r_l = _ah_outcome_simple(hs, as_, lower)
            r_u = _ah_outcome_simple(hs, as_, upper)
            combined = (r_l + r_u) / 2
            if abs(combined - 1.0) < 1e-9:
                return 'ah_home'
            elif abs(combined - 0.0) < 1e-9:
                return 'ah_away'
            elif abs(combined - 0.5) < 1e-9:
                return 'push'
            elif combined > 0.5:
                return 'ah_home_half'
            else:
                return 'ah_away_half'
        else:
            r = _ah_outcome_simple(hs, as_, ah_line)
            if abs(r - 0.5) < 1e-9:
                return 'push'
            return 'ah_home' if r > 0.5 else 'ah_away'

    def _ah_outcome_simple(hs, as_, line) -> float:
        adj = (hs - as_) + line
        if abs(adj) < 1e-9:
            return 0.5  # push
        return 1.0 if adj > 0 else 0.0

    sub['actual_ah'] = sub.apply(ah_outcome, axis=1)

    # 去掉 push 和 half
    valid = sub[sub['actual_ah'].isin(['ah_home', 'ah_away'])]
    print(f'  去除 push/half 后: {len(valid)}')
    if len(valid) == 0:
        return

    acc = (valid['ah_pred'] == valid['actual_ah']).mean()
    print(f'  Overall AH Accuracy: {acc:.3f}  ({(valid["ah_pred"]==valid["actual_ah"]).sum()}/{len(valid)})')

    # 各联赛
    print(f'\n  各联赛 AH 准确率:')
    for lid, grp in valid.groupby('League_ID'):
        name = LEAGUE_NAMES.get(int(lid), str(int(lid)))
        a = (grp['ah_pred'] == grp['actual_ah']).mean()
        print(f'    {name:<8}: n={len(grp):>4}  acc={a:.3f}')

    # Agreement
    print(f'\n  Agreement Filter 分析（AH）:')
    for agree_val, label in [(1, '一致'), (0, '分歧')]:
        s = valid[valid['ah_agree'] == agree_val]
        if len(s) == 0:
            continue
        a = (s['ah_pred'] == s['actual_ah']).mean()
        print(f'    {label} (n={len(s):>4}): acc={a:.3f}')


def evaluate_btts(df: pd.DataFrame) -> None:
    """BTTS 评估"""
    print('\n' + '─'*60)
    print('  BTTS 市场评估')
    print('─'*60)

    df = df.copy()
    df['actual_btts'] = (
        (df['target_home_score'].astype(float) >= 1) &
        (df['target_away_score'].astype(float) >= 1)
    ).map({True: 'yes', False: 'no'})

    df['btts_pred'] = (df['p_btts_yes'] > 0.5).map({True: 'yes', False: 'no'})
    acc = (df['btts_pred'] == df['actual_btts']).mean()
    print(f'  Overall BTTS Accuracy: {acc:.3f}  ({(df["btts_pred"]==df["actual_btts"]).sum()}/{len(df)})')

    for d, grp in df.groupby('btts_pred'):
        a = (grp['btts_pred'] == grp['actual_btts']).mean()
        print(f'    pred={d}: n={len(grp):>4}  acc={a:.3f}')


def evaluate_correct_score(df: pd.DataFrame) -> None:
    """Correct Score Top-1 命中率"""
    print('\n' + '─'*60)
    print('  Correct Score Top-N 评估')
    print('─'*60)

    def parse_top_scores(s: str) -> list[tuple[int, int]]:
        if not isinstance(s, str):
            return []
        cells = []
        for part in s.split(';'):
            try:
                score, _ = part.split(':')
                h, a = score.split('-')
                cells.append((int(h), int(a)))
            except Exception:
                pass
        return cells

    df = df.copy()
    df['actual_h'] = df['target_home_score'].astype(int)
    df['actual_a'] = df['target_away_score'].astype(int)

    for top_n in [1, 3, 5]:
        hits = 0
        for _, row in df.iterrows():
            preds = parse_top_scores(row['top_scores'])[:top_n]
            if (row['actual_h'], row['actual_a']) in preds:
                hits += 1
        rate = hits / len(df)
        print(f'  Top-{top_n} 命中率: {rate:.3f}  ({hits}/{len(df)})')


# ─────────────────────────────────────────────────────────────────────
# 6. ROI 模拟（公平赔率）
# ─────────────────────────────────────────────────────────────────────

def roi_simulation(df: pd.DataFrame) -> None:
    """
    简单 ROI 模拟：假设用公平赔率下注（无 margin），
    计算各 Tier 的理论期望。

    公平赔率 = 1 / predicted_prob（无 margin 情况）
    实际结果 × 赔率 - 1 = net return
    """
    print('\n' + '─'*60)
    print('  ROI 模拟（公平赔率，无 margin）')
    print('─'*60)

    df = df.copy()
    df['actual_wdl'] = df.apply(
        lambda r: 'home_win' if r.target_home_score > r.target_away_score
                  else ('draw' if r.target_home_score == r.target_away_score else 'away_win'),
        axis=1
    )
    df['wdl_correct'] = df['wdl_pred'] == df['actual_wdl']

    # 公平赔率 = 1 / max_p（在预测方向上）
    df['fair_odds'] = 1.0 / df['wdl_max_p'].clip(lower=0.01)
    df['roi'] = df.apply(
        lambda r: r.fair_odds - 1.0 if r.wdl_correct else -1.0,
        axis=1
    )

    print(f'\n  按 Tier 统计 ROI（WDL，公平赔率）:')
    for tier in ['锁单', '优选', '关注']:
        s = df[df['tier'] == tier]
        if len(s) == 0:
            print(f'    {tier}: n=0')
            continue
        avg_roi = s['roi'].mean()
        acc = s['wdl_correct'].mean()
        avg_odds = s['fair_odds'].mean()
        print(f'    {tier} (n={len(s):>4}): acc={acc:.3f}  avg_odds={avg_odds:.3f}  '
              f'avg_ROI/bet={avg_roi:+.3f}  cum_ROI={s["roi"].sum():+.2f}')


# ─────────────────────────────────────────────────────────────────────
# 7. Go/No-go 报告
# ─────────────────────────────────────────────────────────────────────

def go_nogo_report(df: pd.DataFrame) -> None:
    print('\n' + '='*60)
    print('  Go / No-go 报告')
    print('='*60)

    df = df.copy()
    df['actual_wdl'] = df.apply(
        lambda r: 'home_win' if r.target_home_score > r.target_away_score
                  else ('draw' if r.target_home_score == r.target_away_score else 'away_win'),
        axis=1
    )
    df['wdl_correct'] = df['wdl_pred'] == df['actual_wdl']

    rps_vals = df.apply(
        lambda r: _rps_wdl(r.p_home_win, r.p_draw, r.p_away_win, r.actual_wdl), axis=1
    )

    acc = df['wdl_correct'].mean()
    rps = rps_vals.mean()

    # High-conf: agree + max_p >= 0.55
    hc = df[(df['wdl_agree'] == 1) & (df['wdl_max_p'] >= 0.55)]
    hc_acc = hc['wdl_correct'].mean() if len(hc) > 0 else 0.0
    hc_pct = len(hc) / len(df)

    print(f'''
  指标                  Lambda v5       V5 WDL 基准     判定
  ──────────────────────────────────────────────────────────
  WDL 准确率            {acc:.3f}           0.515           {"✅ PASS" if acc >= 0.50 else "❌ FAIL"}
  WDL RPS               {rps:.4f}          0.2055          {"✅ PASS" if rps <= 0.2100 else "❌ FAIL"}
  高置信准确率(≥0.55)   {hc_acc:.3f}           0.853           {"✅ PASS" if hc_acc >= 0.55 else "⚠️  LOW"} (n={len(hc)}, {hc_pct:.1%})
  ''')

    # Tier 覆盖率
    for tier in ['锁单', '优选', '关注']:
        n = (df['tier'] == tier).sum()
        pct = n / len(df)
        print(f'  {tier} 覆盖率: {n}/{len(df)} = {pct:.1%}')

    # 市场优先级建议
    print(f'''
  市场上线建议：
  - WDL：{"✅ 可上线" if acc >= 0.50 and rps <= 0.2100 else "❌ 暂缓"}
  - OU：  需人工确认 OU 评估结果
  - AH：  需人工确认 AH 评估结果
  - BTTS：需人工确认 BTTS 评估结果
  ''')


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    conn = sqlite3.connect(DB_PATH)

    print('='*60)
    print('  evaluate_lambda_v5')
    print('='*60)

    # ── 1. 数据加载 ──────────────────────────────────────────────────
    print('\n' + '─'*60)
    print('  Step 1: 数据加载 + 特征集重建')
    print('─'*60)
    df_all = load_data(conn)
    df_all, feat_full, feat_pure, cat_features = build_feature_sets(df_all)

    test_df = df_all[df_all['split'] == 'test'].reset_index(drop=True)
    print(f'  Test set: {len(test_df)} 行')

    # ── 2. 加载模型 ──────────────────────────────────────────────────
    print('\n' + '─'*60)
    print('  Step 2: 加载模型 + ρ')
    print('─'*60)
    models, rho_data = load_models()

    # ── 3. 推断 λ ────────────────────────────────────────────────────
    print('\n' + '─'*60)
    print('  Step 3: 推断 λ（Full + Pure + Ensemble）')
    print('─'*60)

    # 对 full 集合构建特征矩阵（用全量数据的特征，只预测 test 行）
    # 必须用 Full dataset 来确定哪些列被 drop（NULL>40%），然后子集
    cat_f = [c for c in cat_features if c in feat_full]
    cat_p = [c for c in cat_features if c in feat_pure]

    X_full = test_df[feat_full]
    X_pure = test_df[[c for c in feat_pure if c in test_df.columns]]

    lambdas = predict_lambda(models, rho_data, X_full, X_pure, cat_f)

    # OU / AH 线
    ou_lines  = test_df['open_ou_line'].values if 'open_ou_line' in test_df.columns else np.full(len(test_df), None)
    ah_lines  = test_df['ah_line_opening'].values if 'ah_line_opening' in test_df.columns else np.full(len(test_df), None)
    league_ids = test_df['League_ID'].values

    print(f'  λ_h 均值={lambdas["lam_h"].mean():.3f}  λ_a 均值={lambdas["lam_a"].mean():.3f}')

    # ── 4. 推断全市场 ─────────────────────────────────────────────────
    print('\n' + '─'*60)
    print('  Step 4: 推断全市场（WDL/OU/AH/BTTS/CS）')
    print('─'*60)
    results = predict_all_markets(lambdas, rho_data, league_ids, ou_lines, ah_lines)
    print(f'  推断完成: {len(results)} 条')

    # ── 5. 写入数据库 ─────────────────────────────────────────────────
    print('\n' + '─'*60)
    print('  Step 5: 写入 mart_lambda_predictions_test')
    print('─'*60)
    out_df = write_predictions(conn, test_df, results)

    # ── 6. 多市场评估 ─────────────────────────────────────────────────
    print('\n' + '='*60)
    print('  Step 6: 多市场评估')
    print('='*60)

    evaluate_wdl(out_df)
    evaluate_ou(out_df)
    evaluate_ah(out_df)
    evaluate_btts(out_df)
    evaluate_correct_score(out_df)
    roi_simulation(out_df)
    go_nogo_report(out_df)

    conn.close()
    print('\n  ✅ evaluate_lambda_v5 完成')


if __name__ == '__main__':
    main()
