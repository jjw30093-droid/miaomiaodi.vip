'use client';
import React from 'react';
import type { ModelSnapshotV2 } from '@/lib/modelHealth/types';
import { SAMPLE_FLOOR } from '@/lib/modelHealth/constants';
import EquityHero from '../EquityHero';
import { useTheme } from '@/components/ThemeProvider';

interface Props {
  snap: ModelSnapshotV2;
}

export default function SinglePickHero({ snap }: Props) {
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const CARD_STYLE: React.CSSProperties = {
    background: isDark ? '#0F172A' : '#FFFFFF',
    borderColor: isDark ? '#334155' : '#E2E8F0',
    color: isDark ? '#F1F5F9' : '#0F172A',
  };
  const { single_pick, cold_start, total_settled = 0 } = snap;

  // State 1: cold-start — sample below floor
  if (cold_start || total_settled < SAMPLE_FLOOR) {
    return (
      <section className="rounded-2xl p-6 border text-center" style={CARD_STYLE}>
        <p
          className="text-xs font-bold uppercase tracking-wider mb-3"
          style={{ color: 'var(--v2-text-tertiary)' }}
        >
          模型精度
        </p>
        <p className="text-base font-semibold" style={{ color: 'var(--v2-text-secondary)' }}>
          模型训练中，样本积累至 {SAMPLE_FLOOR} 场后展示
        </p>
        <p className="text-sm font-semibold font-mono mt-2" style={{ color: 'var(--v2-text-tertiary)' }}>
          当前 {total_settled} 场
        </p>
      </section>
    );
  }

  // ── 择优窗口：优先用 best，降级到 w30 ──
  const best = single_pick?.best;
  const w30 = single_pick?.w30;
  const source = best?.hit_rate != null ? best : w30;

  if (!source) {
    return (
      <section className="rounded-2xl p-5 border" style={CARD_STYLE}>
        <p
          className="text-xs font-bold uppercase tracking-wider mb-3"
          style={{ color: 'var(--v2-text-tertiary)' }}
        >
          模型精度
        </p>
        <p className="text-base font-semibold text-center py-4" style={{ color: 'var(--v2-text-secondary)' }}>
          数据加载中，请稍后刷新
        </p>
      </section>
    );
  }

  // 数据来源
  const useBest = best?.hit_rate != null;
  const hits = useBest ? best!.hits : (w30?.hits ?? 0);
  const n = useBest ? best!.n_settled : (w30?.n_settled ?? 0);
  const hitRate = useBest ? best!.hit_rate : (w30?.hit_rate ?? null);
  const windowDays = useBest ? best!.window_days : 30;
  const marketLabel = useBest ? (best!.market_label || '全部') : '全部';

  // 净值曲线：best 专属曲线，降级到全局
  const curve = (useBest && single_pick?.best_equity_curve?.length)
    ? single_pick.best_equity_curve
    : (single_pick?.equity_curve ?? []);

  const endVal = curve.at(-1)?.value ?? 0;
  const hitRatePct = hitRate != null ? (hitRate * 100).toFixed(1) : '—';
  const brierScore = snap.training_meta?.brier ?? null;

  // ── 配色策略 ──
  const COLOR = {
    text:           isDark ? '#F1F5F9' : '#0F172A',
    textSoft:       isDark ? '#CBD5E1' : '#475569',
    label:          isDark ? '#94A3B8' : '#64748B',
    neutralBg:      isDark ? '#1E293B' : '#F8FAFC',
    neutralBorder:  isDark ? '#334155' : '#E2E8F0',
    success:        isDark ? '#34D399' : '#059669',
    successChip:    isDark ? '#10B981' : '#047857',
    successBg:      isDark ? 'rgba(16, 185, 129, 0.12)' : '#ECFDF5',
    successBorder:  isDark ? '#10B981' : '#059669',
  };
  const isHitRateGood = hitRate != null && hitRate >= 0.5;
  const hitRateColor  = isHitRateGood ? COLOR.success       : COLOR.label;
  const hitRateBg     = isHitRateGood ? COLOR.successBg     : COLOR.neutralBg;
  const hitRateBorder = isHitRateGood ? COLOR.successBorder : COLOR.neutralBorder;

  // 标题：显示市场 + 窗口
  const titleSuffix = marketLabel === '全部'
    ? `近 ${windowDays} 天`
    : `${marketLabel} · 近 ${windowDays} 天`;

  return (
    <section className="rounded-2xl p-5 border flex flex-col gap-4" style={CARD_STYLE}>
      <div className="flex items-center justify-between">
        <p
          className="font-bold uppercase tracking-wider"
          style={{ fontSize: 12, color: COLOR.label }}
        >
          预测精度 · {titleSuffix}
        </p>
        <span
          className="font-semibold tabular-nums"
          style={{ fontSize: 12, color: COLOR.label }}
        >
          样本 {n} 场
        </span>
      </div>

      {/* 📊 精度概览卡 */}
      <div
        className="rounded-xl p-4 border-2"
        style={{ background: hitRateBg, borderColor: hitRateBorder }}
      >
        <p className="font-semibold mb-2" style={{ fontSize: 12, color: COLOR.label }}>
          📊 近 {windowDays} 天预测精度
        </p>
        <div className="flex items-baseline gap-2 flex-wrap">
          <span
            className="font-black tabular-nums"
            style={{
              fontSize: 38,
              color: hitRateColor,
              fontFamily: "'Plus Jakarta Sans', sans-serif",
              lineHeight: 1.05,
              letterSpacing: '-0.02em',
            }}
          >
            {hitRatePct}%
          </span>
        </div>
        <p className="font-medium mt-2 tabular-nums" style={{ fontSize: 12, color: COLOR.label }}>
          {n} 场已结算，命中 {hits} 场
        </p>
      </div>

      {/* 三个关键指标 */}
      <div className="grid grid-cols-3 gap-2">
        <div
          className="rounded-xl p-3 border-2 flex flex-col items-center gap-1"
          style={{ borderColor: hitRateBorder, background: hitRateBg }}
        >
          <span className="font-bold uppercase tracking-wider" style={{ fontSize: 12, color: hitRateColor }}>
            命中率
          </span>
          <span
            className="font-black tabular-nums"
            style={{ fontSize: 24, color: hitRateColor, lineHeight: 1.05, fontFamily: "'Plus Jakarta Sans', sans-serif" }}
          >
            {hitRatePct}%
          </span>
        </div>
        <div
          className="rounded-xl p-3 border flex flex-col items-center gap-1"
          style={{ borderColor: COLOR.neutralBorder, background: COLOR.neutralBg }}
        >
          <span className="font-bold uppercase tracking-wider" style={{ fontSize: 12, color: COLOR.label }}>
            Brier
          </span>
          <span
            className="font-black tabular-nums"
            style={{ fontSize: 24, color: COLOR.label, lineHeight: 1.05, fontFamily: "'Plus Jakarta Sans', sans-serif" }}
          >
            {brierScore != null ? brierScore.toFixed(3) : '—'}
          </span>
        </div>
        <div
          className="rounded-xl p-3 border flex flex-col items-center gap-1"
          style={{ borderColor: COLOR.neutralBorder, background: COLOR.neutralBg }}
        >
          <span className="font-bold uppercase tracking-wider" style={{ fontSize: 12, color: COLOR.label }}>
            命中
          </span>
          <span
            className="font-black tabular-nums"
            style={{ fontSize: 22, color: COLOR.textSoft, lineHeight: 1.05, fontFamily: "'Plus Jakarta Sans', sans-serif" }}
          >
            {hits}<span style={{ fontSize: 13, color: COLOR.label, fontWeight: 700 }}>/{n}</span>
          </span>
        </div>
      </div>

      {/* Equity curve */}
      <EquityHero curve={curve} />
    </section>
  );
}
