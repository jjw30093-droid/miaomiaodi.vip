#!/usr/bin/env python3
"""
build_ah_dataset_v5.py — AH 数据集构建

数据源：
  silver_match_odds  (market='ah', period='opening'+'closing')
  dim_match          (home_score, away_score)

⚠️  符号约定（standardized_line，home 视角）：
  负数 = 主队让球（主强）   例：-1.5 = 主让 1.5
  正数 = 主队受让（主弱）   例：+0.5 = 主受让 0.5

  footballdata 原始值已符合此约定（AHh 列）。
  NowGoal 原始值约定相反（正数=主队让球），写入 DB 时符号已正确处理：
    titan_odds_spider.py:361: ah[period]["line"] = str(-float(line))  ← is_swapped 时
  但对非 swapped 场次，NowGoal raw_line 仍使用其原始约定（正=让），
  → 本脚本读取后对 source='nowgoal' 的盘口线做符号翻转（negate）以统一标准。

AH Outcome 计算（home 视角）：
  adjusted_diff = (home_score - away_score) + ah_line
    > 0  → home 全赢 (1.0)
    < 0  → home 全输 (0.0)
    = 0  → push   (-1.0, 整盘专属)

  季球盘（quarter-ball，-0.75 / -0.25 / 0.25 / 0.75）：
    拆成相邻整/半盘各 50% 仓位，结果取平均
    可能出现 0.25（半负）/ 0.75（半赢）

二分类 label（ah_binary_label）：
  1.0 → 1  (home covers)
  0.0 → 0  (away covers)
  其他（0.25 / 0.5 / 0.75 / -1.0）→ None（不参与训练）

CLAUDE.md §3: 唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations
import math, os, sqlite3
import numpy as np
import pandas as pd

DB_PATH = '/home/ubuntu/app/backend/football_uk.db'

# NowGoal 符号翻转阈值：仅对非 swapped 的 nowgoal 行翻转
# 实证：fd=-1.25 对应 ng=+1.25（相同比赛），确认 ng 使用正=让约定
NOWGOAL_LINE_NEGATE = True


# ─────────────────────────────────────────────────────────────────────
# AH Outcome 计算
# ─────────────────────────────────────────────────────────────────────

def compute_ah_outcome(home_score: int, away_score: int, ah_line: float) -> float:
    """
    计算 AH 结果（home 视角）。
    ah_line 已标准化为 fd 约定：负=让，正=受让。
    返回：1.0 / 0.75 / 0.5 / 0.25 / 0.0（push 记为 -1.0 便于过滤）
    """
    # 季球盘（quarter-ball）：小数部分为 0.25 或 0.75
    frac = ah_line - math.floor(ah_line)
    if abs(frac - 0.25) < 1e-9 or abs(frac - 0.75) < 1e-9:
        # 拆成相邻两个半盘各 0.5 仓位
        lower = math.floor(ah_line * 2) / 2   # 更小（更负）的那个半盘
        upper = math.ceil(ah_line * 2) / 2    # 更大（更正）的那个半盘
        r_lower = _compute_simple(home_score, away_score, lower)
        r_upper = _compute_simple(home_score, away_score, upper)
        return (r_lower + r_upper) / 2

    # 整盘 / 半盘：push 0.5 → 转为 -1.0 哨兵便于过滤
    result = _compute_simple(home_score, away_score, ah_line)
    return -1.0 if abs(result - 0.5) < 1e-9 else result


def _compute_simple(home_score: int, away_score: int, ah_line: float) -> float:
    """
    整盘 / 半盘计算（供 compute_ah_outcome 调用）。
    返回 0.5 表示 push，便于季球盘取均值：
      quarter avg(push=0.5, win=1.0) = 0.75  → 半赢
      quarter avg(push=0.5, loss=0.0) = 0.25 → 半负
    非季球场景由 compute_ah_outcome 将 0.5 转为 -1.0（push 哨兵）。
    """
    adjusted_diff = (home_score - away_score) + ah_line
    if abs(adjusted_diff) < 1e-9:
        return 0.5    # push（整盘专属；季球拆盘时作为 0.5 参与均值）
    return 1.0 if adjusted_diff > 0 else 0.0


def compute_ah_binary(ah_outcome: float) -> int | None:
    """1.0 → 1, 0.0 → 0, 其他 → None"""
    if abs(ah_outcome - 1.0) < 1e-9:
        return 1
    if abs(ah_outcome - 0.0) < 1e-9:
        return 0
    return None


# ─────────────────────────────────────────────────────────────────────
# AH line 类型分类
# ─────────────────────────────────────────────────────────────────────

def line_category(line: float) -> str:
    """整/半/季球盘分类"""
    if line is None or np.isnan(line):
        return 'unknown'
    frac = abs(line) % 1
    if abs(frac) < 1e-9 or abs(frac - 1.0) < 1e-9:
        return 'integer'
    if abs(frac - 0.5) < 1e-9:
        return 'half'
    if abs(frac - 0.25) < 1e-9 or abs(frac - 0.75) < 1e-9:
        return 'quarter'
    return 'other'


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main():
    conn = sqlite3.connect(DB_PATH)

    # ── Step 1: 数据探查 ──────────────────────────────────────────────
    print('='*60)
    print('  Step 1: AH 数据源探查')
    print('='*60)

    src_dist = pd.read_sql_query('''
        SELECT source, COUNT(DISTINCT match_id) as matches, COUNT(*) as rows
        FROM silver_match_odds
        WHERE market='ah' AND period='opening' AND raw_line IS NOT NULL
        GROUP BY source ORDER BY rows DESC
    ''', conn)
    print(f'\n  Opening 来源分布:')
    for _, r in src_dist.iterrows():
        print(f'    source={r.source:<15}  matches={int(r.matches):>5}  rows={int(r.rows):>5}')

    overlap = conn.execute('''
        SELECT COUNT(DISTINCT match_id) FROM silver_match_odds
        WHERE market='ah' AND period='opening' AND raw_line IS NOT NULL
          AND match_id IN (
              SELECT match_id FROM silver_match_odds
              WHERE market='ah' AND period='opening' AND source='nowgoal'
          )
          AND match_id IN (
              SELECT match_id FROM silver_match_odds
              WHERE market='ah' AND period='opening' AND source='footballdata'
          )
    ''').fetchone()[0]
    print(f'    fd+ng 双重覆盖: {overlap} 场（优先使用 footballdata）')

    # ── Step 2: 读取数据（优先 footballdata，dedup by match_id）────────
    print('\n' + '='*60)
    print('  Step 2: 读取 + JOIN 数据')
    print('='*60)

    sql = '''
    SELECT
        o.match_id,
        o.raw_line         AS ah_line_opening_raw,
        o.raw_home         AS raw_home,
        o.raw_away         AS raw_away,
        o.source           AS source_opening,
        c.raw_line         AS ah_line_closing_raw,
        c.raw_home         AS closing_home,
        c.raw_away         AS closing_away,
        d.home_score,
        d.away_score,
        d.Season,
        d.League_ID
    FROM silver_match_odds o
    JOIN dim_match d
        ON CAST(d.Match_ID AS TEXT) = CAST(o.match_id AS TEXT)
    LEFT JOIN silver_match_odds c
        ON  CAST(c.match_id AS TEXT) = CAST(o.match_id AS TEXT)
        AND c.market = 'ah'
        AND c.period = 'closing'
        AND c.source = o.source
    WHERE o.market = 'ah'
      AND o.period = 'opening'
      AND o.raw_line IS NOT NULL
      AND d.home_score IS NOT NULL
      AND d.away_score IS NOT NULL
    ORDER BY o.match_id,
             CASE o.source WHEN 'footballdata' THEN 0 ELSE 1 END
    '''
    df = pd.read_sql_query(sql, conn)
    print(f'\n  JOIN 后原始行数: {len(df)}  (含重复)')

    # 去重：同一 match_id 保留 footballdata 优先的第一行
    df = df.groupby('match_id', as_index=False).first()
    print(f'  去重后: {len(df)} 行')

    # ── Step 3: 标准化 AH line（符号约定对齐）────────────────────────
    print('\n' + '='*60)
    print('  Step 3: 标准化 AH line 符号（fd 约定：负=让）')
    print('='*60)

    df['ah_line_opening_raw'] = pd.to_numeric(df['ah_line_opening_raw'], errors='coerce')
    df['ah_line_closing_raw'] = pd.to_numeric(df['ah_line_closing_raw'], errors='coerce')

    if NOWGOAL_LINE_NEGATE:
        ng_mask = df['source_opening'] == 'nowgoal'
        ng_count = ng_mask.sum()
        # nowgoal 约定：正=让 → 取反对齐 fd 约定（负=让）
        df.loc[ng_mask, 'ah_line_opening_raw'] = -df.loc[ng_mask, 'ah_line_opening_raw']
        df.loc[ng_mask, 'ah_line_closing_raw'] = -df.loc[ng_mask, 'ah_line_closing_raw']
        print(f'  NowGoal 行 {ng_count} 场：raw_line 符号已翻转')

    df.rename(columns={
        'ah_line_opening_raw': 'ah_line_opening',
        'ah_line_closing_raw': 'ah_line_closing',
    }, inplace=True)

    # ── Step 4: 特征工程 ──────────────────────────────────────────────
    df['home_score'] = pd.to_numeric(df['home_score'], errors='coerce')
    df['away_score'] = pd.to_numeric(df['away_score'], errors='coerce')
    df['raw_home']   = pd.to_numeric(df['raw_home'],   errors='coerce')
    df['raw_away']   = pd.to_numeric(df['raw_away'],   errors='coerce')
    df['closing_home'] = pd.to_numeric(df['closing_home'], errors='coerce')
    df['closing_away'] = pd.to_numeric(df['closing_away'], errors='coerce')
    df = df.dropna(subset=['home_score', 'away_score', 'ah_line_opening'])

    df['home_score'] = df['home_score'].astype(int)
    df['away_score'] = df['away_score'].astype(int)

    # 盘口移动（closing - opening）：正 = 线向主队利方向移
    df['ah_line_movement'] = df['ah_line_closing'] - df['ah_line_opening']

    # 隐含偏差（home cover 的市场隐含概率优势）
    df['ah_implied_diff'] = (1.0 / df['raw_home']) - (1.0 / df['raw_away'])

    # 赔率移动
    df['ah_odds_movement'] = df['closing_home'] - df['raw_home']

    # 盘口类型
    df['line_category'] = df['ah_line_opening'].apply(line_category)

    # ── Step 5: 计算 AH label ─────────────────────────────────────────
    df['ah_outcome_value'] = df.apply(
        lambda r: compute_ah_outcome(r['home_score'], r['away_score'], r['ah_line_opening']),
        axis=1
    )

    df['ah_binary_label'] = df['ah_outcome_value'].apply(compute_ah_binary)

    # ── Step 6: 整理输出列 ────────────────────────────────────────────
    out_cols = [
        'match_id',
        'Season', 'League_ID',
        'home_score', 'away_score',
        'ah_line_opening', 'ah_line_closing', 'ah_line_movement',
        'raw_home', 'raw_away',
        'closing_home', 'closing_away', 'ah_odds_movement',
        'ah_implied_diff',
        'line_category',
        'ah_outcome_value',
        'ah_binary_label',
        'source_opening',
    ]
    out = df[[c for c in out_cols if c in df.columns]].copy()

    # ── Step 7: 写入数据库 ────────────────────────────────────────────
    print('\n' + '='*60)
    print('  Step 7: 写入 mart_ah_dataset_v5')
    print('='*60)
    conn.execute('DROP TABLE IF EXISTS mart_ah_dataset_v5')
    out.to_sql('mart_ah_dataset_v5', conn, if_exists='replace', index=False)
    conn.commit()
    print(f'  ✔ 写入完成: {len(out)} 行')

    # ── Step 8: 统计报告 ──────────────────────────────────────────────
    print('\n' + '='*60)
    print('  Step 8: 统计报告')
    print('='*60)

    print(f'\n  总行数: {len(out)}')

    # ah_line 分布
    print(f'\n  AH line 分布（前 15）:')
    lc = out['ah_line_opening'].value_counts().sort_index()
    total = len(out)
    for line_val, cnt in lc.items():
        print(f'    {line_val:>6.2f}  n={cnt:>5}  {cnt/total*100:>5.1f}%')

    # push / half 样本占比
    print(f'\n  ah_outcome_value 分布（home 视角）:')
    vc = out['ah_outcome_value'].value_counts().sort_index()
    push_n = int((out['ah_outcome_value'] == -1.0).sum())
    for v, cnt in vc.items():
        label = {-1.0:'push（整盘）', 0.0:'away covers',
                 0.25:'home half-lose（季球）', 0.5:'push（不应出现）',
                 0.75:'home half-win（季球）', 1.0:'home covers'}.get(v, str(v))
        print(f'    {v:>5.2f} ({label:<20})  n={cnt:>5}  {cnt/total*100:>5.1f}%')

    # 二分类训练样本
    binary_df = out[out['ah_binary_label'].notna()]
    non_binary = len(out) - len(binary_df)
    print(f'\n  ──────────────────────────────────────────')
    print(f'  ah_binary_label 训练样本: {len(binary_df):>6}  ({len(binary_df)/total*100:.1f}%)')
    print(f'  非二分类样本（push/half）: {non_binary:>6}  ({non_binary/total*100:.1f}%)  '
          f'← 不参与训练，用于产品 ROI 评估')
    if len(binary_df) > 0:
        home_cover = int((binary_df['ah_binary_label'] == 1).sum())
        away_cover = len(binary_df) - home_cover
        print(f'    home cover: {home_cover:>5}  ({home_cover/len(binary_df)*100:.1f}%)')
        print(f'    away cover: {away_cover:>5}  ({away_cover/len(binary_df)*100:.1f}%)')

    # 按赛季的漏斗
    print(f'\n  赛季维度训练样本:')
    for season, grp in out.groupby('Season'):
        b = grp['ah_binary_label'].notna().sum()
        print(f'    {season:<12}  total={len(grp):>5}  binary={b:>5}  '
              f'home_cover_rate={grp.loc[grp.ah_binary_label==1,"ah_binary_label"].count()/b*100 if b>0 else 0:.1f}%')

    # line_category 分布
    print(f'\n  line_category 分布（按盘口类型）:')
    for cat, grp in out.groupby('line_category'):
        b = grp['ah_binary_label'].notna().sum()
        print(f'    {cat:<10}  n={len(grp):>5}  binary={b:>5}')

    # source 分布
    print(f'\n  source 分布:')
    for src, cnt in out['source_opening'].value_counts().items():
        print(f'    {src:<15}  n={cnt:>5}  {cnt/total*100:.1f}%')

    conn.close()
    print('\n  ✅ build_ah_dataset_v5 完成')


if __name__ == '__main__':
    main()
