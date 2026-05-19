#!/usr/bin/env python3
"""
build_lambda_dataset_v5.py — Lambda 双模型训练数据集

目标：
  训练双 Poisson 回归模型预测 λ_home + λ_away（主客进球期望值）。
  一个模型框架同时支持 OU / AH / BTTS / Correct Score 推断。

数据源：
  mart_prediction_matrix_v5  ← V5 base features (~165 列)
  mart_ah_dataset_v5          ← sign-corrected AH line + implied diff
  dim_match                   ← 比赛元信息

目标联赛：
  47=英超 55=西甲 87=德甲 53=法甲 54=意甲 (五大)
  113=澳超 223=J联赛 9080=K联赛

Target：
  target_home_score (= home_score)
  target_away_score (= away_score)

Feature：
  全部 V5 rolling diff / venue / trend / PI / ELO / 赔率特征
  AH line（sign-corrected）+ ah_implied_diff

时间衰减权重：
  sample_weight = exp(-0.003 * days_from_latest)
  latest_date = 全 train set 内最晚比赛日期

Train/Val/Test 切分：
  严格按 match_date 升序，70% / 15% / 15%
  不随机 shuffle

输出表：mart_lambda_dataset_v5

CLAUDE.md §3: 唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations
import os, sqlite3
import numpy as np
import pandas as pd

DB_PATH = '/home/ubuntu/app/backend/football_uk.db'

TARGET_LEAGUES = (47, 55, 87, 53, 54, 113, 223, 9080)
DECAY_RATE = 0.003   # per day; 365d → weight ≈ 0.33

# Columns to EXCLUDE from feature set (targets or pure classification labels)
EXCLUDE_COLS = {
    'home_score', 'away_score',
    'result', 'label_enc', 'wdl_label',
    # AH columns from V5 matrix that may have un-corrected sign; replaced by mart_ah_dataset_v5
    # (keep open_ah_line / closing_ah_line for now as corroborating signal)
}


# ─────────────────────────────────────────────────────────────────────
# Step 1: 读取 + JOIN
# ─────────────────────────────────────────────────────────────────────

def load_data(conn: sqlite3.Connection, include_future: bool = False) -> pd.DataFrame:
    print('  读取 mart_prediction_matrix_v5 ...')
    score_filter = '' if include_future else 'AND home_score IS NOT NULL'
    mpv = pd.read_sql_query(
        f'''
        SELECT * FROM mart_prediction_matrix_v5
        WHERE League_ID IN ({",".join(str(l) for l in TARGET_LEAGUES)})
          {score_filter}
        ''',
        conn
    )
    print(f'  mart_prediction_matrix_v5: {len(mpv)} 行 (include_future={include_future})')

    print('  读取 mart_ah_dataset_v5 ...')
    ah = pd.read_sql_query(
        '''
        SELECT
            match_id,
            ah_line_opening,
            raw_home        AS ah_raw_home,
            raw_away        AS ah_raw_away,
            ah_line_movement,
            ah_implied_diff,
            ah_odds_movement,
            line_category   AS ah_line_category,
            source_opening  AS ah_source
        FROM mart_ah_dataset_v5
        ''',
        conn
    )
    print(f'  mart_ah_dataset_v5: {len(ah)} 行')

    # JOIN
    df = mpv.merge(ah, on='match_id', how='left')
    print(f'  JOIN 后: {len(df)} 行  (AH 覆盖率: '
          f'{df["ah_line_opening"].notna().sum()} / {len(df)} = '
          f'{df["ah_line_opening"].notna().mean()*100:.1f}%)')

    # ── is_fd_fallback：标记 OU 来自 footballdata 而非 nowgoal 的行 ──
    # 约 500 条 BIG5 23/24+24/25 行因 nowgoal 当时缺失，OU 特征来自 footballdata
    # 作为 audit 标记保留在训练集中；训练时可选择过滤或直接保留
    ou_src = pd.read_sql_query(
        '''
        SELECT match_id,
               MAX(CASE WHEN source = "nowgoal"      THEN 1 ELSE 0 END) AS has_nowgoal,
               MAX(CASE WHEN source = "footballdata"  THEN 1 ELSE 0 END) AS has_fd
        FROM silver_match_odds
        WHERE market = "ou" AND period = "opening"
        GROUP BY match_id
        ''',
        conn
    )
    ou_src['is_fd_fallback'] = (
        (ou_src['has_fd'] == 1) & (ou_src['has_nowgoal'] == 0)
    ).astype(int)
    df = df.merge(ou_src[['match_id', 'is_fd_fallback']], on='match_id', how='left')
    df['is_fd_fallback'] = df['is_fd_fallback'].fillna(0).astype(int)
    fd_cnt = int(df['is_fd_fallback'].sum())
    print(f'  is_fd_fallback: {fd_cnt} 行来自 footballdata OU（其余为 nowgoal 或无 OU）')
    return df


# ─────────────────────────────────────────────────────────────────────
# Step 2: 构建目标列 + 特征集
# ─────────────────────────────────────────────────────────────────────

def build_features(df: pd.DataFrame, include_future: bool = False) -> pd.DataFrame:
    # 目标列
    df = df.rename(columns={
        'home_score': 'target_home_score',
        'away_score': 'target_away_score',
    })
    df['target_home_score'] = pd.to_numeric(df['target_home_score'], errors='coerce').astype('Int64')
    df['target_away_score'] = pd.to_numeric(df['target_away_score'], errors='coerce').astype('Int64')

    # match_date → datetime
    df['match_date'] = pd.to_datetime(df['match_date'], errors='coerce')
    if include_future:
        # 仅 dropna 日期；保留 target=NaN 的未来场次行
        df = df.dropna(subset=['match_date'])
    else:
        df = df.dropna(subset=['match_date', 'target_home_score', 'target_away_score'])

    # 排序（时间正序）
    df = df.sort_values('match_date').reset_index(drop=True)
    return df


# ─────────────────────────────────────────────────────────────────────
# Step 3: 时间衰减权重（基于整体最晚日期计算）
# ─────────────────────────────────────────────────────────────────────

def add_sample_weight(df: pd.DataFrame) -> pd.DataFrame:
    latest_date = df['match_date'].max()
    df['days_from_latest'] = (latest_date - df['match_date']).dt.days
    df['sample_weight'] = np.exp(-DECAY_RATE * df['days_from_latest'])
    return df


# ─────────────────────────────────────────────────────────────────────
# Step 4: Train / Val / Test split（严格时间顺序）
# ─────────────────────────────────────────────────────────────────────

def time_split(df: pd.DataFrame, train_pct=0.70, val_pct=0.15):
    n = len(df)
    n_train = int(n * train_pct)
    n_val   = int(n * val_pct)

    train = df.iloc[:n_train].copy()
    val   = df.iloc[n_train: n_train + n_val].copy()
    test  = df.iloc[n_train + n_val:].copy()

    # 给每行打上 split 标签
    df = df.copy()
    df['split'] = 'train'
    df.loc[n_train: n_train + n_val - 1, 'split'] = 'val'
    df.loc[n_train + n_val:, 'split'] = 'test'

    return df, train, val, test


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--include-future', '--include_future',
                        action='store_true', dest='include_future',
                        help='保留未来场次（target=NULL，split=inference），供 lambda 推理读特征')
    args, _ = parser.parse_known_args()

    conn = sqlite3.connect(DB_PATH)

    print('='*60)
    print('  build_lambda_dataset_v5')
    print('='*60)
    print(f'  mode: {"include_future" if args.include_future else "train_only"}')

    # ── 1. 读取 + JOIN ────────────────────────────────────────────────
    print('\n' + '─'*60)
    print('  Step 1: 读取 + JOIN')
    print('─'*60)
    df = load_data(conn, include_future=args.include_future)

    # ── 2. 构建目标列 ─────────────────────────────────────────────────
    print('\n' + '─'*60)
    print('  Step 2: 构建目标列 + 特征集')
    print('─'*60)
    df = build_features(df, include_future=args.include_future)
    print(f'  有效行数: {len(df)}'
          + (f'（其中未完赛 {df["target_home_score"].isna().sum()}）' if args.include_future else ''))

    # 拆分历史/未来
    if args.include_future:
        df_future = df[df['target_home_score'].isna()].copy()
        df = df[df['target_home_score'].notna()].copy()
        print(f'  历史（参与训练）: {len(df)}, 未来（仅 inference）: {len(df_future)}')
    else:
        df_future = None

    # 列分类
    meta_cols = ['match_id', 'match_date', 'Season', 'League_ID',
                 'Home_Team_ID', 'Away_Team_ID', 'Home_Team_Name', 'Away_Team_Name']
    target_cols = ['target_home_score', 'target_away_score']
    # weight_cols 同时承担"审计元数据"职责（is_fd_fallback 不用作训练特征）
    weight_cols = ['days_from_latest', 'sample_weight', 'split', 'is_fd_fallback']

    all_exclude = set(meta_cols) | set(target_cols) | set(weight_cols) | EXCLUDE_COLS
    feature_cols = [c for c in df.columns if c not in all_exclude]

    print(f'  特征列数: {len(feature_cols)}')
    print(f'  前 10 特征: {feature_cols[:10]}')
    print(f'  ...后 10 特征: {feature_cols[-10:]}')

    # ── 3. 时间衰减权重 ───────────────────────────────────────────────
    print('\n' + '─'*60)
    print('  Step 3: 时间衰减权重')
    print('─'*60)
    df = add_sample_weight(df)
    print(f'  最早日期: {df["match_date"].min().date()}  weight={df["sample_weight"].min():.4f}')
    print(f'  最晚日期: {df["match_date"].max().date()}  weight={df["sample_weight"].max():.4f}')
    print(f'  中位权重: {df["sample_weight"].median():.4f}')

    # ── 4. Train/Val/Test split ───────────────────────────────────────
    print('\n' + '─'*60)
    print('  Step 4: Train / Val / Test split（时间顺序 70/15/15）')
    print('─'*60)
    df, train, val, test = time_split(df, train_pct=0.70, val_pct=0.15)

    print(f'\n  {"split":<8}  {"n":>6}  {"date_start":>12}  {"date_end":>12}')
    print('  ' + '-'*48)
    for name, subset in [('train', train), ('val', val), ('test', test)]:
        print(f'  {name:<8}  {len(subset):>6}  '
              f'{subset["match_date"].min().date()!s:>12}  '
              f'{subset["match_date"].max().date()!s:>12}')

    # ── 5. 写入数据库 ─────────────────────────────────────────────────
    print('\n' + '─'*60)
    print('  Step 5: 写入 mart_lambda_dataset_v5')
    print('─'*60)

    out_cols = meta_cols + target_cols + weight_cols + feature_cols
    out_cols = [c for c in out_cols if c in df.columns]
    out = df[out_cols].copy()

    # 追加未来场次（split='inference'，target=NaN，sample_weight=0）
    if df_future is not None and len(df_future) > 0:
        df_future = df_future.copy()
        df_future['days_from_latest'] = 0
        df_future['sample_weight'] = 0.0
        df_future['split'] = 'inference'
        future_out = df_future.reindex(columns=out_cols, fill_value=None)
        out = pd.concat([out, future_out], ignore_index=True)
        print(f'  ➕ 追加 inference 行: {len(df_future)}')

    conn.execute('DROP TABLE IF EXISTS mart_lambda_dataset_v5')
    out.to_sql('mart_lambda_dataset_v5', conn, if_exists='replace', index=False)
    conn.commit()
    print(f'  ✔ 写入完成: {len(out)} 行 × {len(out.columns)} 列')

    # ── 6. 统计报告 ───────────────────────────────────────────────────
    print('\n' + '='*60)
    print('  Step 6: 数据质量验证报告')
    print('='*60)

    # 总量
    print(f'\n  总行数: {len(df)}')

    # 各赛季
    print(f'\n  按赛季分布:')
    s_grp = df.groupby('Season').agg(
        n=('match_id', 'count'),
        train=('split', lambda x: (x=='train').sum()),
        val=('split', lambda x: (x=='val').sum()),
        test=('split', lambda x: (x=='test').sum()),
    ).reset_index()
    for _, r in s_grp.iterrows():
        print(f'    {r.Season:<12}  total={int(r.n):>5}  train={int(r.train):>5}  '
              f'val={int(r.val):>4}  test={int(r.test):>4}')

    # 各联赛
    LEAGUE_NAMES = {47:'英超', 55:'西甲', 87:'德甲', 53:'法甲', 54:'意甲',
                    113:'澳超', 223:'J联赛', 9080:'K联赛'}
    print(f'\n  按联赛分布:')
    l_grp = df.groupby('League_ID').agg(
        n=('match_id', 'count'),
        train=('split', lambda x: (x=='train').sum()),
        val=('split', lambda x: (x=='val').sum()),
        test=('split', lambda x: (x=='test').sum()),
    ).reset_index()
    for _, r in l_grp.iterrows():
        name = LEAGUE_NAMES.get(int(r.League_ID), str(int(r.League_ID)))
        print(f'    {name:<8} ({int(r.League_ID):>5})  total={int(r.n):>5}  '
              f'train={int(r.train):>5}  val={int(r.val):>4}  test={int(r.test):>4}')

    # Target 分布 + Poisson 验证
    print(f'\n  Target 分布（Poisson 假设：mean ≈ variance）:')
    for col in ['target_home_score', 'target_away_score']:
        vals = df[col].dropna().astype(float)
        print(f'    {col}:')
        print(f'      mean={vals.mean():.4f}  var={vals.var():.4f}  '
              f'ratio(var/mean)={vals.var()/vals.mean():.4f}  '
              f'{"✅ ≈1（Poisson OK）" if abs(vals.var()/vals.mean()-1)<0.3 else "⚠️ 过离散（考虑负二项）"}')
        print(f'      min={int(vals.min())}  max={int(vals.max())}  '
              f'P(0)={float((vals==0).mean()):.3f}  '
              f'P(1)={float((vals==1).mean()):.3f}  '
              f'P(2+)={float((vals>=2).mean()):.3f}')

    # 各联赛进球特征
    print(f'\n  各联赛进球特征:')
    print(f'  {"联赛":<8}  {"avg_home":>9}  {"avg_away":>9}  '
          f'{"avg_total":>10}  {"home_win%":>10}  {"n":>6}')
    print('  ' + '-'*60)
    for lid, grp in df.groupby('League_ID'):
        name = LEAGUE_NAMES.get(int(lid), str(int(lid)))
        h = grp['target_home_score'].astype(float)
        a = grp['target_away_score'].astype(float)
        hw_pct = (h > a).mean() * 100
        print(f'  {name:<8}  {h.mean():>9.3f}  {a.mean():>9.3f}  '
              f'{(h+a).mean():>10.3f}  {hw_pct:>9.1f}%  {len(grp):>6}')

    # 时间衰减权重分布
    print(f'\n  时间衰减权重分布（decay_rate={DECAY_RATE}/day）:')
    pcts = [0, 10, 25, 50, 75, 90, 100]
    w_pcts = np.percentile(df['sample_weight'], pcts)
    for p, w in zip(pcts, w_pcts):
        days = -np.log(w) / DECAY_RATE
        print(f'    p{p:>3}  weight={w:.4f}  (≈ {int(days)} days from latest)')

    # AH 覆盖
    ah_cov = df['ah_line_opening'].notna().sum()
    print(f'\n  AH line 覆盖: {ah_cov}/{len(df)} = {ah_cov/len(df)*100:.1f}%')
    print(f'  AH 缺失场次 (no_ah_line): {len(df) - ah_cov}  '
          f'← 可用 open_ah_line from V5 matrix 作替代或 NaN impute')

    # Split 内联赛分布（确认无极端偏斜）
    print(f'\n  Train/Val/Test 内联赛分布（验证无极端偏斜）:')
    for split_name in ['train', 'val', 'test']:
        subset = df[df['split'] == split_name]
        pcts_str = '  '.join(
            f'{LEAGUE_NAMES.get(int(lid),"?")[:4]}={int(cnt)}'
            for lid, cnt in subset['League_ID'].value_counts().items()
        )
        print(f'    {split_name:<6}: {pcts_str}')

    conn.close()
    print('\n  ✅ build_lambda_dataset_v5 完成')
    return out


if __name__ == '__main__':
    main()
