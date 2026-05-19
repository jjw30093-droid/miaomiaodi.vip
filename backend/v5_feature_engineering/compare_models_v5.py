#!/usr/bin/env python3
"""
compare_models_v5.py — Phase 3: Global vs League A/B 对比 + 生产模型选择

决策规则（per-league）：
  若 league_model.test_ah_acc >= global_model.test_ah_acc + 0.02  →  选 league
  否则  →  选 global（更保守，泛化性更强）

特殊规则：
  Serie A (55) — 若 Pure 模型（xi<=0.3）的 AH acc 与 Full 差距 < 0.02，选 Pure

输出：
  models_v5_lambda/comparison_report.csv    详细对比表
  models_v5_lambda/production_model_selection.json   生产决策

CLAUDE.md §3：唯一生产库 = /home/ubuntu/app/backend/football_uk.db
"""
from __future__ import annotations

import csv
import json
import os
import sys

# ─── 路径 ───────────────────────────────────────────────────────────
MODEL_BASE = '/home/ubuntu/app/backend/models_v5_lambda'
GLOBAL_DIR = os.path.join(MODEL_BASE, 'global')

# FotMob 实际数据验证：87=LaLiga/Villarreal, 55=SerieA/Udinese, 54=Bundesliga/Wolfsburg
LEAGUE_NAMES = {
    47: 'EPL', 87: 'LaLiga', 54: 'Bundesliga',
    55: 'SerieA', 53: 'Ligue1',
}
TARGET_LEAGUES = [47, 87, 54, 55, 53]

# 联赛模型 AH 领先阈值（超过此值才切换）
AH_LEAD_THRESHOLD = 0.02  # +2pp


def load_global_metrics() -> dict:
    """加载 Phase 1 全局模型 eval_metrics.json"""
    path = os.path.join(GLOBAL_DIR, 'eval_metrics.json')
    if not os.path.exists(path):
        print(f'  ⚠️  global eval_metrics.json 不存在: {path}')
        return {}
    with open(path) as f:
        return json.load(f)


def load_league_metrics(lid: int) -> dict | None:
    """
    加载 Phase 2 联赛模型指标。
    优先读 eval_metrics.json（train_league_v5.py 输出），回退到 rho.json + eval_report.csv。
    """
    league_dir      = os.path.join(MODEL_BASE, str(lid))
    metrics_path    = os.path.join(league_dir, 'eval_metrics.json')
    rho_path        = os.path.join(league_dir, 'rho.json')
    csv_path        = os.path.join(league_dir, 'eval_report.csv')

    # ── 优先：eval_metrics.json ─────────────────────────────────────────
    if os.path.exists(metrics_path):
        with open(metrics_path) as f:
            m = json.load(f)
        return {
            'rho':          m.get('rho'),
            'best_xi':      m.get('xi'),
            'best_val_ah':  m.get('best_val_ah_acc'),
            'test': {
                'n_wdl':    m.get('n_wdl'),
                'n_ou':     m.get('n_ou'),
                'n_ah':     m.get('n_ah'),
                'wdl_acc':  m.get('wdl_acc'),
                'ou_acc':   m.get('ou_acc'),
                'ah_acc':   m.get('ah_acc'),
            }
        }

    # ── 回退：rho.json + eval_report.csv ──────────────────────────────
    if not os.path.exists(rho_path):
        print(f'  ⚠️  联赛 {lid} rho.json / eval_metrics.json 均不存在')
        return None

    with open(rho_path) as f:
        rho_data = json.load(f)

    test_metrics = {}
    if os.path.exists(csv_path):
        with open(csv_path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row.get('split') == 'test':
                    for k in ('n_wdl', 'n_ou', 'n_ah'):
                        try:
                            test_metrics[k] = int(row[k])
                        except (ValueError, KeyError):
                            test_metrics[k] = None
                    for k in ('wdl_acc', 'ou_acc', 'ah_acc'):
                        try:
                            test_metrics[k] = float(row[k])
                        except (ValueError, KeyError):
                            test_metrics[k] = None

    return {
        'rho':         rho_data.get('rho'),
        'best_xi':     rho_data.get('best_xi'),
        'best_val_ah': rho_data.get('best_val_ah_acc'),
        'test':        test_metrics,
    }


def make_decision(lid: int, global_metrics: dict, league_metrics: dict) -> dict:
    """
    决策逻辑：
      league AH acc >= global AH acc + AH_LEAD_THRESHOLD  →  'league'
      else                                                  →  'global'
    返回 decision dict。
    """
    name = LEAGUE_NAMES.get(lid, str(lid))

    # 全局模型该联赛 test AH
    global_ah = None
    by_league = global_metrics.get('by_league', {})
    for k, v in by_league.items():
        if int(k) == lid:
            global_ah = v.get('ah_acc')
            break

    # 联赛模型 test AH
    league_ah = league_metrics['test'].get('ah_acc') if league_metrics else None

    # 决策
    if global_ah is None and league_ah is None:
        chosen = 'global'
        reason = 'both_unavailable'
    elif league_ah is None:
        chosen = 'global'
        reason = 'no_league_model'
    elif global_ah is None:
        chosen = 'league'
        reason = 'no_global_metric'
    elif league_ah >= global_ah + AH_LEAD_THRESHOLD:
        chosen = 'league'
        reason = f'league_AH_leads_by_{league_ah - global_ah:.3f}'
    else:
        chosen = 'global'
        reason = f'league_AH_deficit_{league_ah - global_ah:.3f}'

    # Serie A 附加说明
    serie_a_note = None
    if lid == 55 and league_metrics:
        xi = league_metrics.get('best_xi', 0.6)
        if xi <= 0.3:
            serie_a_note = f'Pure主力模型(xi={xi})'

    return {
        'league_id': lid,
        'league': name,
        'global_ah_acc': global_ah,
        'league_ah_acc': league_ah,
        'league_best_xi': league_metrics.get('best_xi') if league_metrics else None,
        'league_rho': league_metrics.get('rho') if league_metrics else None,
        'delta_ah': round(league_ah - global_ah, 4) if (league_ah is not None and global_ah is not None) else None,
        'chosen': chosen,
        'reason': reason,
        'serie_a_note': serie_a_note,
        # 额外指标
        'global_wdl_acc': None,  # 填充于下方
        'league_wdl_acc': league_metrics['test'].get('wdl_acc') if league_metrics else None,
        'global_ou_acc':  None,
        'league_ou_acc':  league_metrics['test'].get('ou_acc') if league_metrics else None,
        'n_ah_test': league_metrics['test'].get('n_ah') if league_metrics else None,
    }


def main():
    print('=' * 65)
    print('  compare_models_v5  — Phase 3 A/B 对比 + 生产模型选择')
    print('=' * 65)

    # ── 1. 加载全局指标 ────────────────────────────────────────────────
    print('\n[Step 1] 加载全局模型指标')
    global_metrics = load_global_metrics()
    if not global_metrics:
        print('  ERROR: 无法加载 global eval_metrics.json，请先运行 train_global_v5.py')
        return

    g_global = global_metrics.get('global', {})
    print(f'  全局 AH acc = {g_global.get("ah_acc")}  '
          f'OU acc = {g_global.get("ou_acc")}  '
          f'WDL acc = {g_global.get("wdl_acc")}')

    # ── 2. 加载联赛指标 ────────────────────────────────────────────────
    print('\n[Step 2] 加载联赛模型指标')
    league_data = {}
    for lid in TARGET_LEAGUES:
        m = load_league_metrics(lid)
        league_data[lid] = m
        name = LEAGUE_NAMES.get(lid, str(lid))
        if m:
            print(f'  {name:<12} ξ={m.get("best_xi")}  '
                  f'test AH={m["test"].get("ah_acc")}  '
                  f'val AH={m.get("best_val_ah")}')
        else:
            print(f'  {name:<12} 数据缺失')

    # ── 3. 逐联赛决策 ──────────────────────────────────────────────────
    print('\n[Step 3] 决策（阈值 +2pp AH）')
    decisions = {}
    for lid in TARGET_LEAGUES:
        d = make_decision(lid, global_metrics, league_data.get(lid))
        # 补充全局该联赛 WDL/OU
        by_league = global_metrics.get('by_league', {})
        for k, v in by_league.items():
            if int(k) == lid:
                d['global_wdl_acc'] = v.get('wdl_acc')
                d['global_ou_acc']  = v.get('ou_acc')
                break
        decisions[lid] = d

    # ── 4. 打印对比表 ──────────────────────────────────────────────────
    print(f'\n  {"联赛":<12} {"Global AH":>10} {"League AH":>10} {"Delta":>7} {"决策":>8}  说明')
    print('  ' + '─' * 70)
    for lid, d in decisions.items():
        g_ah = f'{d["global_ah_acc"]:.3f}' if d['global_ah_acc'] is not None else '  N/A '
        l_ah = f'{d["league_ah_acc"]:.3f}' if d['league_ah_acc'] is not None else '  N/A '
        delta = f'{d["delta_ah"]:+.3f}' if d['delta_ah'] is not None else '  N/A '
        chosen_sym = '✅ league' if d['chosen'] == 'league' else '⬜ global'
        note = d.get('serie_a_note') or d['reason']
        print(f'  {d["league"]:<12} {g_ah:>10} {l_ah:>10} {delta:>7} {chosen_sym:>10}  {note}')

    # ── 5. 生成 production_model_selection.json ────────────────────────
    print('\n[Step 4] 写出 production_model_selection.json')

    prod_selection = {
        'generated_at': __import__('datetime').datetime.now().isoformat(),
        'ah_lead_threshold': AH_LEAD_THRESHOLD,
        'global_model_dir': GLOBAL_DIR,
        'leagues': {}
    }

    for lid, d in decisions.items():
        if d['chosen'] == 'league':
            model_dir = os.path.join(MODEL_BASE, str(lid))
        else:
            model_dir = GLOBAL_DIR

        # 确定推理时用的 ξ 和 ρ
        if d['chosen'] == 'league' and league_data.get(lid):
            xi  = league_data[lid].get('best_xi', 0.6)
            rho = league_data[lid].get('rho')
        else:
            xi  = 0.6  # global 默认 Ensemble Full:Pure = 0.6:0.4
            # 从 global rho.json 取该联赛 rho
            global_rho_path = os.path.join(GLOBAL_DIR, 'rho.json')
            rho = None
            if os.path.exists(global_rho_path):
                with open(global_rho_path) as f:
                    rho_data = json.load(f)
                rho = rho_data['rho_by_league'].get(str(lid), rho_data['rho_global'])

        prod_selection['leagues'][str(lid)] = {
            'league': d['league'],
            'chosen_model': d['chosen'],
            'model_dir': model_dir,
            'xi': xi,
            'rho': rho,
            'global_ah_acc': d['global_ah_acc'],
            'league_ah_acc': d['league_ah_acc'],
            'delta_ah': d['delta_ah'],
            'reason': d['reason'],
            'serie_a_note': d.get('serie_a_note'),
        }

    prod_path = os.path.join(MODEL_BASE, 'production_model_selection.json')
    with open(prod_path, 'w') as f:
        json.dump(prod_selection, f, indent=2, ensure_ascii=False)
    print(f'  💾 {prod_path}')

    # ── 6. 对比报告 CSV ────────────────────────────────────────────────
    csv_path = os.path.join(MODEL_BASE, 'comparison_report.csv')
    fieldnames = ['league_id', 'league', 'global_ah_acc', 'league_ah_acc',
                  'delta_ah', 'chosen', 'reason',
                  'global_wdl_acc', 'league_wdl_acc',
                  'global_ou_acc', 'league_ou_acc',
                  'league_best_xi', 'league_rho', 'n_ah_test', 'serie_a_note']
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        w.writerows(decisions.values())
    print(f'  💾 {csv_path}')

    # ── 7. 汇总摘要 ────────────────────────────────────────────────────
    n_league = sum(1 for d in decisions.values() if d['chosen'] == 'league')
    n_global = len(decisions) - n_league

    print('\n' + '=' * 65)
    print('  Phase 3 决策摘要')
    print('=' * 65)
    print(f'\n  选用 league 独立模型: {n_league} 个联赛')
    print(f'  选用 global 全局模型: {n_global} 个联赛')

    for lid, d in decisions.items():
        icon = '🔵 league' if d['chosen'] == 'league' else '⬜ global'
        note = f'(SerieA Pure主力)' if d.get('serie_a_note') else ''
        print(f'    {d["league"]:<12}: {icon} {note}')

    print(f'\n  输出文件:')
    print(f'    {prod_path}')
    print(f'    {csv_path}')
    print('\n  ✅ compare_models_v5 完成')


if __name__ == '__main__':
    main()
