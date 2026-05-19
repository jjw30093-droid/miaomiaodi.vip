#!/usr/bin/env python3
"""
build_ou_dataset_v5.py — OU 数据集构建（支持所有盘口）

数据源：
  silver_match_odds  (market='ou', period='opening'+'closing')
  dim_match          (home_score, away_score)

输出表：mart_ou_dataset_v5

盘口类型与 actual_label_value 计算规则：
  整数盘 (2.0, 3.0)：全赢=1, 全输=0, push=-1
  半盘   (2.5, 3.5)：全赢=1, 全输=0（无 push）
  半球盘 (2.25, 2.75, 3.25)：相当于同等金额分注整数盘和半盘
    2.25 = 2.0 + 2.5 各半：
      total >= 3: 全赢 1.0
      total == 2: 2.0 push + 2.5 输 = 0.25（赢一半）
      total <= 1: 全输 0.0
    2.75 = 2.5 + 3.0 各半：
      total >= 4: 全赢 1.0
      total == 3: 2.5 赢 + 3.0 push = 0.75（赢一半）
      total <= 2: 全输 0.0
    3.25 = 3.0 + 3.5 各半：
      total >= 4: 全赢 1.0
      total == 3: 3.0 push + 3.5 输 = 0.25（赢一半）
      total <= 2: 全输 0.0

baseline_label（训练用）：
  total > 2.5 → 1 else 0（2.5 无 push，无需过滤）

CLAUDE.md §3：唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations
import os, sqlite3
import numpy as np
import pandas as pd

DB_PATH = '/home/ubuntu/app/backend/football_uk.db'

# 支持的盘口（排除 1.75 / 3.75 / 4.25 等稀有盘）
SUPPORTED_LINES = {2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5}


# ─────────────────────────────────────────────────────────────────────
# 盘口分类
# ─────────────────────────────────────────────────────────────────────

def line_type(line: float) -> str:
    """整数 / 半盘 / 半球盘"""
    if line is None or np.isnan(line):
        return 'unknown'
    frac = line - int(line)          # 小数部分
    if frac == 0.0:   return 'integer'   # 2.0, 3.0
    if frac == 0.5:   return 'half'      # 2.5, 3.5
    if frac == 0.25:  return 'quarter'   # 2.25, 3.25  (低半球盘)
    if frac == 0.75:  return 'quarter'   # 2.75        (高半球盘)
    return 'other'


# ─────────────────────────────────────────────────────────────────────
# actual_label_value 计算
# ─────────────────────────────────────────────────────────────────────

def compute_actual_label(total: int, ou_line: float) -> float:
    """
    返回 actual_label_value：
      1.0  = 全赢 over
      0.75 = 赢一半（半球盘）
      0.5  = push（整数盘）→ 存 -1 便于评估时过滤
      0.25 = 输一半（半球盘）
      0.0  = 全输
    push 用 -1.0 标记，评估时剔除
    """
    if ou_line == 2.0:
        if total > 2:   return 1.0
        if total == 2:  return -1.0   # push
        return 0.0
    if ou_line == 2.25:
        # 2.0 + 2.5 各半
        if total >= 3:  return 1.0
        if total == 2:  return 0.25   # 2.0 push + 2.5 输 → 赢一半（习惯标记）
        # 注意：2.25 over 意味着 total > 2.25
        # 正确规则：total > 2.25 → 全赢；total == 2 → 半push半输 = 退一半(-0.5 stake)
        # 用业界标准：2.25 = 2.0半 + 2.5半
        #   total >= 3: 2.0赢 + 2.5赢 = 全赢 1.0
        #   total == 2: 2.0push + 2.5输 = 退一半 → label 0.25（返还一半本金，另一半输）
        #   total <= 1: 全输 0.0
        return 0.0
    if ou_line == 2.5:
        return 1.0 if total > 2 else 0.0
    if ou_line == 2.75:
        # 2.5 + 3.0 各半
        if total >= 4:  return 1.0
        if total == 3:  return 0.75   # 2.5赢 + 3.0push = 赢一半
        return 0.0
    if ou_line == 3.0:
        if total > 3:   return 1.0
        if total == 3:  return -1.0   # push
        return 0.0
    if ou_line == 3.25:
        # 3.0 + 3.5 各半
        if total >= 4:  return 1.0
        if total == 3:  return 0.25   # 3.0push + 3.5输 = 退一半
        return 0.0
    if ou_line == 3.5:
        return 1.0 if total > 3 else 0.0
    # 其他盘口：简单阈值
    return 1.0 if total > ou_line else 0.0


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    conn = sqlite3.connect(DB_PATH)

    # ── Step 1: 数据探查 ──────────────────────────────────────────────
    print('='*60)
    print('  Step 1: OU 盘口分布探查')
    print('='*60)
    dist = pd.read_sql_query('''
        SELECT
            raw_line,
            COUNT(*) as cnt,
            COUNT(*) * 100.0 /
                (SELECT COUNT(*) FROM silver_match_odds
                 WHERE market='ou' AND period='opening') as pct
        FROM silver_match_odds
        WHERE market='ou' AND period='opening'
        GROUP BY raw_line
        ORDER BY cnt DESC
    ''', conn)
    total_opening = int(dist['cnt'].sum())
    print(f'\n  Opening 总行数: {total_opening}')
    print(f'\n  {"raw_line":<12} {"cnt":>8}  {"pct%":>7}  {"line_type":>12}')
    print('  ' + '-'*46)
    for _, row in dist.iterrows():
        lt = line_type(row['raw_line']) if row['raw_line'] is not None else 'NULL'
        print(f'  {str(row["raw_line"]):<12} {int(row["cnt"]):>8}  '
              f'{row["pct"]:>6.1f}%  {lt:>12}')

    # ── Step 2: 读取 Opening + Closing 数据 ──────────────────────────
    print('\n' + '='*60)
    print('  Step 2: 读取并 JOIN 数据')
    print('='*60)

    sql = '''
    SELECT
        o.match_id,
        o.raw_line         AS ou_line_opening,
        o.raw_home         AS over_odds_opening,
        o.raw_away         AS under_odds_opening,
        c.raw_line         AS ou_line_closing,
        c.raw_home         AS over_odds_closing,
        c.raw_away         AS under_odds_closing,
        d.home_score,
        d.away_score,
        d.Season
    FROM silver_match_odds o
    JOIN dim_match d
        ON CAST(d.Match_ID AS TEXT) = CAST(o.match_id AS TEXT)
    LEFT JOIN silver_match_odds c
        ON  CAST(c.match_id AS TEXT) = CAST(o.match_id AS TEXT)
        AND c.market = 'ou'
        AND c.period = 'closing'
    WHERE o.market = 'ou'
      AND o.period = 'opening'
      AND o.raw_line IS NOT NULL
      AND d.home_score IS NOT NULL
      AND d.away_score IS NOT NULL
    '''
    df = pd.read_sql_query(sql, conn)
    print(f'\n  JOIN 后原始行数: {len(df)}')

    # ── Step 3: 过滤支持盘口 ─────────────────────────────────────────
    df['ou_line_opening'] = pd.to_numeric(df['ou_line_opening'], errors='coerce')
    df = df[df['ou_line_opening'].isin(SUPPORTED_LINES)].copy()
    print(f'  过滤支持盘口后: {len(df)} 行  (支持: {sorted(SUPPORTED_LINES)})')

    # ── Step 4: 计算 total & labels ───────────────────────────────────
    df['home_score']  = pd.to_numeric(df['home_score'], errors='coerce')
    df['away_score']  = pd.to_numeric(df['away_score'], errors='coerce')
    df = df.dropna(subset=['home_score', 'away_score'])
    df['total'] = (df['home_score'] + df['away_score']).astype(int)

    # baseline_label（2.5 阈值，无 push，直接训练用）
    df['baseline_label'] = (df['total'] > 2.5).astype(int)   # 0 or 1

    # actual_label_value（根据真实盘口）
    df['actual_label_value'] = df.apply(
        lambda r: compute_actual_label(r['total'], r['ou_line_opening']), axis=1)

    # line_type
    df['line_type'] = df['ou_line_opening'].apply(line_type)

    # ── Step 5: Closing 衍生特征 ──────────────────────────────────────
    df['ou_line_closing']   = pd.to_numeric(df['ou_line_closing'],   errors='coerce')
    df['over_odds_opening'] = pd.to_numeric(df['over_odds_opening'], errors='coerce')
    df['over_odds_closing'] = pd.to_numeric(df['over_odds_closing'], errors='coerce')

    # 盘口变动（closing - opening）：正 = 向大方向移动
    df['ou_line_movement'] = df['ou_line_closing'] - df['ou_line_opening']
    # 赔率变动（over 赔率 closing - opening）：负 = over 被压缩 = 盘口向 over 方向动
    df['ou_odds_movement'] = df['over_odds_closing'] - df['over_odds_opening']
    # 盘口偏离 baseline（告诉模型庄家对进球数的预期）
    df['ou_line_vs_baseline'] = df['ou_line_opening'] - 2.5

    # ── Step 6: 整理输出列 ────────────────────────────────────────────
    out_cols = [
        'match_id',
        'ou_line_opening', 'ou_line_closing', 'ou_line_movement',
        'over_odds_opening', 'under_odds_opening', 'ou_odds_movement',
        'ou_line_vs_baseline',
        'baseline_label', 'actual_label_value', 'line_type',
        'total',          # 保留，方便 debug / 评估
        'Season',
    ]
    out = df[out_cols].copy()
    print(f'  最终数据集行数: {len(out)}')

    # ── Step 7: 写入数据库 ────────────────────────────────────────────
    print('\n' + '='*60)
    print('  Step 7: 写入 mart_ou_dataset_v5')
    print('='*60)
    conn.execute('DROP TABLE IF EXISTS mart_ou_dataset_v5')
    out.to_sql('mart_ou_dataset_v5', conn, if_exists='replace', index=False)
    conn.commit()
    print(f'  ✔ 写入完成: {len(out)} 行')

    # ── Step 8: 统计报告 ──────────────────────────────────────────────
    print('\n' + '='*60)
    print('  Step 8: 统计报告')
    print('='*60)

    # 各盘口覆盖
    print('\n  各 ou_line 覆盖数:')
    lc = out.groupby('ou_line_opening').agg(
        cnt=('match_id', 'count'),
        over_rate=('baseline_label', 'mean'),
    ).reset_index()
    print(f'  {"ou_line":>8}  {"cnt":>6}  {"pct%":>6}  {"over_rate%":>11}  {"line_type":>10}')
    print('  ' + '-'*50)
    n_total = len(out)
    for _, row in lc.iterrows():
        lt = line_type(row['ou_line_opening'])
        print(f'  {row["ou_line_opening"]:>8.2f}  {int(row["cnt"]):>6}  '
              f'{row["cnt"]/n_total*100:>5.1f}%  '
              f'{row["over_rate"]*100:>10.1f}%  {lt:>10}')

    # baseline_label 分布（全量）
    bl = out['baseline_label'].value_counts().sort_index()
    print(f'\n  baseline_label 分布（total > 2.5）:')
    for k, v in bl.items():
        print(f'    label={k} ({"over" if k==1 else "under"})  '
              f'n={v}  {v/len(out)*100:.1f}%')

    # line_type 分布
    print(f'\n  line_type 分布:')
    lt_cnt = out['line_type'].value_counts()
    for k, v in lt_cnt.items():
        print(f'    {k:<12}  n={v}  {v/len(out)*100:.1f}%')

    # actual_label_value 分布（含 push）
    print(f'\n  actual_label_value 分布（按盘口类型）:')
    for lt_name in ['integer', 'half', 'quarter']:
        sub = out[out['line_type'] == lt_name]
        if len(sub) == 0:
            continue
        vc = sub['actual_label_value'].value_counts().sort_index()
        push_n = int((sub['actual_label_value'] == -1).sum())
        valid_n = len(sub) - push_n
        over_n  = int((sub['actual_label_value'] >= 0.75).sum())
        under_n = int((sub['actual_label_value'] <= 0.25).sum())
        print(f'    [{lt_name}] n={len(sub)}  '
              f'push={push_n}  valid={valid_n}  '
              f'over(>=0.75)={over_n} '
              f'({over_n/valid_n*100:.0f}%)  '
              f'under(<=0.25)={under_n} '
              f'({under_n/valid_n*100:.0f}%)')

    # 进球数分布
    print(f'\n  total 进球数分布（总览）:')
    tc = out['total'].value_counts().sort_index()
    for g, cnt_ in tc.items():
        print(f'    {g}球: {cnt_:>5} 场  {cnt_/len(out)*100:>4.1f}%')

    # ou_line_movement（盘口移动）非 NULL 统计
    mv_valid = out['ou_line_movement'].dropna()
    if len(mv_valid) > 0:
        shifted = (mv_valid != 0).sum()
        print(f'\n  ou_line_movement（closing≠opening）: {shifted} 场 '
              f'({shifted/len(mv_valid)*100:.1f}%  '
              f'of {len(mv_valid)} 有 closing 数据)')

    # Season 分布
    print(f'\n  Season 分布:')
    sc = out.groupby('Season').size().reset_index(name='cnt')
    for _, row in sc.iterrows():
        print(f'    {row["Season"]}:  {row["cnt"]} 场')

    conn.close()
    print('\n  ✅ build_ou_dataset_v5 完成')


if __name__ == '__main__':
    main()
