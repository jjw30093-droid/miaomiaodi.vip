"""
run_ah_training.py
==================
训练和验证 AH（亚盘）独立预测模型。

用法:
  python run_ah_training.py                    # 训练 + 验证
  python run_ah_training.py --validate         # 仅验证（加载已有模型）
  python run_ah_training.py --alpha 0.3        # 调整 DC/xG 混合权重
"""

import argparse
import logging
import sys
import os

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(__file__) or '.')
from ah_model import AHPredictor, prepare_ah_data, LAMBDA_FEATURES


def run_validation(predictor, df_val):
    """对验证集做 AH 预测，返回结果 DataFrame + 打印指标"""
    log.info(f"Running validation on {len(df_val)} matches...")
    val_results = []

    for idx, row in df_val.iterrows():
        ah_line   = row.get('ah_line')
        home_odds = row.get('ah_home_odds', 0) or 0
        away_odds = row.get('ah_away_odds', 0) or 0
        if pd.isna(ah_line) or (home_odds <= 0 and away_odds <= 0):
            continue

        try:
            features = pd.DataFrame([{c: (row[c] if not pd.isna(row[c]) else 0)
                                       for c in LAMBDA_FEATURES}])
            pred = predictor.predict_match(
                row['home_team'], row['away_team'], features, float(ah_line)
            )
        except Exception as e:
            log.debug(f"Prediction failed for match {idx}: {e}")
            continue

        margin = row['home_score'] - row['away_score'] + float(ah_line)
        actual = 'home_cover' if margin > 1e-9 else ('away_cover' if margin < -1e-9 else 'push')

        mkt_implied = 0.5
        if home_odds > 1 and away_odds > 1:
            mkt_implied = (1 / home_odds) / (1 / home_odds + 1 / away_odds)

        val_results.append({
            'ah_line':     float(ah_line),
            'pred_cover':  pred['ah_cover'],
            'pred_push':   pred['ah_push'],
            'pred_away':   pred['ah_away_cover'],
            'mkt_implied': mkt_implied,
            'actual':      actual,
            'label':       1 if actual == 'home_cover' else 0,
            'is_push':     actual == 'push',
            'lambda_home': pred['lambda_home'],
            'lambda_away': pred['lambda_away'],
            'home_odds':   home_odds,
            'away_odds':   away_odds,
        })

    vdf = pd.DataFrame(val_results)
    if vdf.empty:
        log.error("No validation results generated.")
        return None

    vdf_nc = vdf[~vdf['is_push']].copy()

    model_brier  = brier_score_loss(vdf_nc['label'], vdf_nc['pred_cover'])
    market_brier = brier_score_loss(vdf_nc['label'], vdf_nc['mkt_implied'])
    model_ll     = log_loss(vdf_nc['label'], np.clip(vdf_nc['pred_cover'], 1e-6, 1 - 1e-6))
    market_ll    = log_loss(vdf_nc['label'], np.clip(vdf_nc['mkt_implied'], 1e-6, 1 - 1e-6))

    SEP = '=' * 58
    print(f"\n{SEP}")
    print(f"  AH 验证集  (排除走水 n={len(vdf_nc)} / 总{len(vdf)})")
    print(SEP)
    print(f"  走水场次:    {vdf['is_push'].sum()} ({vdf['is_push'].mean()*100:.1f}%)")
    print(f"  主队覆盖率:  {vdf_nc['label'].mean()*100:.1f}%   市场均值: {vdf_nc['mkt_implied'].mean():.3f}")
    print()
    print(f"  Brier Score  模型: {model_brier:.5f}  市场: {market_brier:.5f}  优势: {(market_brier-model_brier)/market_brier*100:+.2f}%")
    print(f"  Log Loss     模型: {model_ll:.5f}  市场: {market_ll:.5f}  优势: {(market_ll-model_ll)/market_ll*100:+.2f}%")

    # 模拟投注
    EDGE = 0.03
    bets = []
    for _, r in vdf_nc.iterrows():
        eh = r['pred_cover'] - r['mkt_implied']
        ea = r['pred_away']  - (1 - r['mkt_implied'])
        if eh >= EDGE and r['home_odds'] > 1:
            bets.append({'pnl': (r['home_odds']-1) if r['label']==1 else -1,
                         'odds': r['home_odds'], 'edge': eh})
        elif ea >= EDGE and r['away_odds'] > 1:
            bets.append({'pnl': (r['away_odds']-1) if r['label']==0 else -1,
                         'odds': r['away_odds'], 'edge': ea})

    print()
    if bets:
        bdf = pd.DataFrame(bets)
        print(f"  模拟投注 (edge≥{EDGE*100:.0f}%, 平注1单位)")
        print(f"  触发: {len(bdf)}/{len(vdf_nc)} ({len(bdf)/len(vdf_nc)*100:.1f}%)")
        print(f"  胜率: {(bdf['pnl']>0).mean()*100:.1f}%   平均赔率: {bdf['odds'].mean():.2f}   平均edge: {bdf['edge'].mean()*100:.1f}%")
        print(f"  总盈亏: {bdf['pnl'].sum():+.2f} 单位   ROI: {bdf['pnl'].sum()/len(bdf)*100:+.2f}%")
    else:
        print(f"  模拟投注: 0 场触发 (edge≥{EDGE*100:.0f}%)")

    # 按 AH 线分段
    print(f"\n  {'─'*55}")
    print("  按盘口线分段 Brier Score")
    print(f"  {'─'*55}")
    for mask, label in [
        (vdf_nc['ah_line'] <= -1.0,                                  '主让≥1球    '),
        ((vdf_nc['ah_line'] > -1.0) & (vdf_nc['ah_line'] <= -0.5),  '主让0.5-0.75'),
        ((vdf_nc['ah_line'] > -0.5) & (vdf_nc['ah_line'] <=  0.0),  '平手/主让0.25'),
        (vdf_nc['ah_line'] > 0.0,                                    '客让        '),
    ]:
        sub = vdf_nc[mask]
        if len(sub) < 10:
            continue
        bm = brier_score_loss(sub['label'], sub['pred_cover'])
        bk = brier_score_loss(sub['label'], sub['mkt_implied'])
        print(f"  {label} n={len(sub):>4}:  model={bm:.4f}  mkt={bk:.4f}  {(bk-bm)/bk*100:+.1f}%")

    # Lambda 分析
    print(f"\n  {'─'*55}")
    print("  Lambda 分析（进球期望 vs 实际）")
    print(f"  {'─'*55}")
    print(f"  λ_home预测: mean={vdf['lambda_home'].mean():.3f}  std={vdf['lambda_home'].std():.3f}")
    print(f"  λ_away预测: mean={vdf['lambda_away'].mean():.3f}  std={vdf['lambda_away'].std():.3f}")
    print(f"  实际主队进球: mean={df_val['home_score'].mean():.3f}")
    print(f"  实际客队进球: mean={df_val['away_score'].mean():.3f}")
    print(f"{SEP}\n")

    return vdf, model_brier, market_brier


def main():
    parser = argparse.ArgumentParser(description='AH Model Training & Validation')
    parser.add_argument('--db',        default='football_uk.db')
    parser.add_argument('--model-dir', default='models_v4')
    parser.add_argument('--validate',  action='store_true')
    parser.add_argument('--xi',        type=float, default=0.003)
    parser.add_argument('--alpha',     type=float, default=0.4)
    args = parser.parse_args()

    log.info("Loading AH training data...")
    df = prepare_ah_data(args.db)
    log.info(f"数据集: {len(df)} 场  AH覆盖: {df['ah_line'].notna().mean()*100:.1f}%")

    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date').reset_index(drop=True)
    split_idx  = int(len(df) * 0.8)
    df_train   = df.iloc[:split_idx].copy()
    df_val     = df.iloc[split_idx:].copy()
    log.info(f"训练集: {len(df_train)}  验证集: {len(df_val)}")

    if args.validate:
        predictor = AHPredictor()
        predictor.load(args.model_dir)
        run_validation(predictor, df_val)
        return

    # ── Layer 1: Dixon-Coles ─────────────────────────────────────────────────
    # DC 用全量数据训练（不只用 train 80%），确保 2026 赛季新队（J2/K联赛等）也被纳入参数估计
    log.info("=== Layer 1: Fitting Dixon-Coles model (全量数据) ===")
    predictor = AHPredictor(blend_alpha=args.alpha)
    dc_data = df[['home_team','away_team','home_score','away_score','Date']].copy()
    dc_data = dc_data.rename(columns={'home_score':'home_goals','away_score':'away_goals'})
    max_dt = dc_data['Date'].max()
    dc_data['days_ago'] = (max_dt - dc_data['Date']).dt.days
    predictor.dc_model.xi = args.xi
    predictor.dc_model.fit(dc_data)

    p = predictor.dc_model.get_params()
    log.info(f"DC fitted: {len(predictor.dc_model.teams)} teams | "
             f"home_adv={p['home_adv']:.4f} | rho={p['rho']:.4f}")

    att, dfn = p['attack'], p['defense']
    strength  = {t: att[t] - dfn[t] for t in att}
    top10 = sorted(strength.items(), key=lambda x: x[1], reverse=True)[:10]
    bot5  = sorted(strength.items(), key=lambda x: x[1])[:5]
    print("\n  DC 综合强度 Top 10 (attack - defense):")
    for t, s in top10:
        print(f"    {t:<32} att={att[t]:+.3f}  def={dfn[t]:+.3f}  net={s:+.3f}")
    print("  DC 综合强度 Bottom 5:")
    for t, s in bot5:
        print(f"    {t:<32} att={att[t]:+.3f}  def={dfn[t]:+.3f}  net={s:+.3f}")

    # ── Layer 2: XGBoostLambda ───────────────────────────────────────────────
    log.info("\n=== Layer 2: Fitting XGBoostLambda (LightGBM) ===")
    X_train = df_train[LAMBDA_FEATURES].fillna(0)
    y_home  = df_train['home_xg'].fillna(df_train['home_xg'].median()).values
    y_away  = df_train['away_xg'].fillna(df_train['away_xg'].median()).values
    predictor.xg_model.fit(X_train, y_home, y_away)

    X_val_xg = df_val[LAMBDA_FEATURES].fillna(0)
    ph, pa   = predictor.xg_model.predict(X_val_xg)
    ah_val   = df_val['home_xg'].fillna(df_val['home_xg'].median()).values
    aa_val   = df_val['away_xg'].fillna(df_val['away_xg'].median()).values
    log.info(f"xG RMSE: home={np.sqrt(np.mean((ph-ah_val)**2)):.4f}  "
             f"away={np.sqrt(np.mean((pa-aa_val)**2)):.4f}")

    # ── Layer 2.5: Lambda 校准（消除系统性低估偏差）────────────────────────────
    log.info("\n=== Layer 2.5: Lambda 校准系数计算 ===")
    att_p  = predictor.dc_model.attack_params
    dfn_p  = predictor.dc_model.defense_params
    ha     = predictor.dc_model.params['home_adv']
    alpha  = predictor.blend_alpha

    # 向量化计算训练集每场的 λ_blend
    l_dc_tr = df_train.apply(
        lambda r: np.exp(att_p.get(r['home_team'], 0) + dfn_p.get(r['away_team'], 0) + ha), axis=1
    ).values
    m_dc_tr = df_train.apply(
        lambda r: np.exp(att_p.get(r['away_team'], 0) + dfn_p.get(r['home_team'], 0)), axis=1
    ).values
    l_xg_tr, m_xg_tr = predictor.xg_model.predict(X_train)  # 使用 X_train（已定义）

    l_blend_tr = alpha * l_dc_tr + (1 - alpha) * l_xg_tr
    m_blend_tr = alpha * m_dc_tr + (1 - alpha) * m_xg_tr

    actual_home_mean = df_train['home_score'].mean()
    actual_away_mean = df_train['away_score'].mean()
    pred_home_mean   = l_blend_tr.mean()
    pred_away_mean   = m_blend_tr.mean()

    scale_h = actual_home_mean / pred_home_mean
    scale_a = actual_away_mean / pred_away_mean
    predictor.lambda_scale_home = float(scale_h)
    predictor.lambda_scale_away = float(scale_a)

    log.info(f"  主队: 预测均值 {pred_home_mean:.4f} → 实际均值 {actual_home_mean:.4f}  scale={scale_h:.4f}")
    log.info(f"  客队: 预测均值 {pred_away_mean:.4f} → 实际均值 {actual_away_mean:.4f}  scale={scale_a:.4f}")

    # ── Validation ───────────────────────────────────────────────────────────
    log.info("\n=== Layer 3: AH Validation ===")
    result = run_validation(predictor, df_val)
    vdf, mb, mkb = result if result else (pd.DataFrame(), 0.25, 0.25)

    # ── Save ─────────────────────────────────────────────────────────────────
    predictor.meta.update({
        'n_samples':          len(df_train),
        'n_val':              len(df_val),
        'features':           LAMBDA_FEATURES,
        'dc_teams':           len(predictor.dc_model.teams),
        'xi':                 args.xi,
        'alpha':              args.alpha,
        'val_brier_model':    float(mb),
        'val_brier_market':   float(mkb),
        'lambda_scale_home':  float(scale_h),
        'lambda_scale_away':  float(scale_a),
    })
    predictor.save(args.model_dir)
    log.info(f"✅ AH 模型已保存到 {args.model_dir}/")
    log.info("   ah_dc_params.json  ah_xg_home.lgb  ah_xg_away.lgb  ah_meta.json")


if __name__ == '__main__':
    main()
