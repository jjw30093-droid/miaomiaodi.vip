'use client';

/**
 * ModelTabContent
 * ───────────────
 * The model-page visual content (equity chart, KPI grid, accuracy bars,
 * calibration scatter) extracted as a standalone component so it can be
 * embedded in the homepage model-tab WITHOUT a full-page wrapper.
 *
 * Used by:
 *   - app/page.tsx  → homepage model tab  (replaces <ModelDashboard />)
 *   - app/model/page.tsx → /model route   (wrapped inside full-page layout)
 */

import React, { useEffect, useState } from 'react';
import { useSession } from 'next-auth/react';
import { useTheme } from '@/components/ThemeProvider';
import { apiClient } from '@/lib/apiClient';
import type { ModelHealthResponse } from '@/types/modelHealth';
import { adaptModelHealth } from '@/lib/modelHealthAdapter';

export default function ModelTabContent() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const { data: session } = useSession();
  const apiToken = (session?.user as any)?.apiToken as string | undefined;

  const [apiData, setApiData] = useState<ModelHealthResponse | null>(null);
  const [isDemo, setIsDemo] = useState(true);

  useEffect(() => {
    if (!apiToken) return;
    apiClient.get<ModelHealthResponse>('/model/health', { token: apiToken })
      .then(data => { setApiData(data); setIsDemo(false); })
      .catch(() => {});
  }, [apiToken]);

  // ── Fallback data ──────────────────────────────────────────────────────────
  const fallbackMetrics = [
    { label: '综合收益率',   value: '+470.7%', icon: 'arrow_upward', color: '#b7004d', borderCls: 'border-[#b7004d]' },
    { label: '进球数精度',   value: '65.4%',   icon: 'check_circle', color: '#005faf', borderCls: 'border-[#005faf]' },
    { label: '欧赔 RPS',    value: '0.128',   icon: 'analytics',    color: '#924700', borderCls: 'border-[#924700]' },
    { label: '验证期投注数', value: '1,620',   icon: 'receipt_long', color: '#5b3f43', borderCls: 'border-[#5b3f43]' },
  ];
  const fallbackMetricsDark = [
    { ...fallbackMetrics[0], color: '#E91E63', borderCls: 'border-[#E91E63]' },
    { ...fallbackMetrics[1], color: '#00F0FF', borderCls: 'border-[#00F0FF]' },
    { ...fallbackMetrics[2], color: '#fb923c', borderCls: 'border-[#fb923c]' },
    { ...fallbackMetrics[3], color: '#a78bfa', borderCls: 'border-[#a78bfa]' },
  ];

  const fallbackAccuracyBars = [
    { label: '欧赔（胜平负）', pct: 43.4, textColor: 'text-[#b7004d]', barColor: 'bg-[#b7004d]' },
    { label: '进球数',         pct: 65.4, textColor: 'text-[#005faf]', barColor: 'bg-[#005faf]' },
    { label: '高置信度策略',   pct: 54.7, textColor: 'text-[#924700]', barColor: 'bg-[#924700]' },
  ];
  const fallbackAccuracyBarsDark = [
    { ...fallbackAccuracyBars[0], textColor: 'text-[#E91E63]', barColor: '#E91E63' },
    { ...fallbackAccuracyBars[1], textColor: 'text-[#00F0FF]',  barColor: '#00F0FF' },
    { ...fallbackAccuracyBars[2], textColor: 'text-[#fb923c]',  barColor: '#fb923c' },
  ];

  const fallbackChartLines = [
    { label: '欧赔', color: '#b7004d', points: '0,36.9 16.7,18.7 33.3,27.9 50,20.9 66.7,17.0 83.3,2.8 100,2.8' },
    { label: '大小', color: '#005faf', points: '0,36.9 16.7,26.5 33.3,29.6 50,29.6 66.7,29.6 83.3,29.6 100,29.6' },
    { label: '综合', color: '#924700', points: '0,36.9 16.7,24.1 33.3,28.7 50,25.2 66.7,23.3 83.3,16.2 100,16.2' },
  ];
  const fallbackChartLinesDark = [
    { ...fallbackChartLines[0], color: '#E91E63' },
    { ...fallbackChartLines[1], color: '#00F0FF' },
    { ...fallbackChartLines[2], color: '#fb923c' },
  ];
  const fallbackChartDates = ['4/6', '4/12', '4/13', '4/14', '4/15', '4/16', '4/17'];

  const fallbackScatterDots = [
    { b: 10, l: 10 }, { b: 22, l: 20 }, { b: 28, l: 30 }, { b: 42, l: 40 },
    { b: 48, l: 50 }, { b: 65, l: 60 }, { b: 68, l: 70 }, { b: 82, l: 80 }, { b: 88, l: 90 },
  ];

  // ── Active data (adapter or fallback) ─────────────────────────────────────
  const adapted = apiData ? adaptModelHealth(apiData, isDark) : null;

  const activeMetrics      = adapted?.metrics      ?? (isDark ? fallbackMetricsDark      : fallbackMetrics);
  const activeAccuracyBars = adapted?.accuracyBars ?? (isDark ? fallbackAccuracyBarsDark : fallbackAccuracyBars);
  const activeScatterDots  = adapted?.scatterDots  ?? fallbackScatterDots;
  const activeChartLines   = (adapted?.chartLines?.length ? adapted.chartLines : null) ?? (isDark ? fallbackChartLinesDark : fallbackChartLines);
  const activeChartDates   = adapted?.chartDates?.length ? adapted.chartDates : fallbackChartDates;
  const heroMultiplier     = adapted?.hero.multiplier ?? 'x5.71';
  const heroReturnPct      = adapted?.hero.returnPct  ?? '+470.7%';
  const heroSubtitle       = adapted?.hero.subtitle   ?? '初始资金 10万 → 57.07万 · 验证集 1,318 场';

  // ── DARK ─────────────────────────────────────────────────────────────────
  if (isDark) {
    return (
      <div className="flex flex-col gap-4">

        {/* 量化策略回测 Hero Card */}
        <section className="bg-white/5 border border-white/10 backdrop-blur-md rounded-xl p-5">
          <div className="flex justify-between items-start mb-3">
            <div>
              <h2 className="font-bold text-zinc-300 text-xs tracking-widest uppercase mb-1">量化策略回测</h2>
              <div className="flex items-baseline gap-2">
                <span className="font-extrabold text-5xl text-white tracking-tighter" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                  {heroMultiplier}
                </span>
                <span className="text-[#E91E63] font-bold flex items-center bg-[#E91E63]/15 border border-[#E91E63]/30 px-2 py-0.5 rounded-md text-sm">
                  <span className="material-symbols-outlined text-[16px] mr-1">trending_up</span>
                  {heroReturnPct}
                </span>
              </div>
              <p className="text-sm text-zinc-300 mt-1">{heroSubtitle}</p>
            </div>
            <div className="flex flex-col items-end gap-2">
              {isDemo && (
                <span className="text-xs font-bold px-2 py-0.5 rounded-full border border-white/15 text-white/40">
                  示例数据 · 登录查看实时
                </span>
              )}
              <div className="bg-white/10 p-2 rounded-lg flex-shrink-0">
                <span className="material-symbols-outlined text-[#00F0FF]">monitoring</span>
              </div>
            </div>
          </div>
          {/* Legend */}
          <div className="flex gap-4 mb-2">
            {activeChartLines.map(l => (
              <div key={l.label} className="flex items-center gap-1.5">
                <div className="w-5 h-0.5 rounded-full" style={{ backgroundColor: l.color }} />
                <span className="text-xs font-bold text-zinc-300">{l.label}</span>
              </div>
            ))}
          </div>
          {/* Chart */}
          <div className="h-28 w-full relative border-b border-white/10 pb-1 mb-6">
            <svg className="absolute inset-0 w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 40">
              <line x1="0" y1="13" x2="100" y2="13" stroke="rgba(255,255,255,0.07)" strokeWidth="0.5" strokeDasharray="2" />
              <line x1="0" y1="26" x2="100" y2="26" stroke="rgba(255,255,255,0.07)" strokeWidth="0.5" strokeDasharray="2" />
              {activeChartLines.map(l => (
                <polyline key={l.label} points={l.points} fill="none" stroke={l.color}
                  strokeWidth="1.5" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
              ))}
            </svg>
            <div className="absolute -bottom-5 left-0 right-0 flex justify-between text-xs text-zinc-400 font-bold">
              {activeChartDates.map(d => <span key={d}>{d}</span>)}
            </div>
          </div>
        </section>

        {/* KPI 2×2 Grid */}
        <section className="grid grid-cols-2 gap-3">
          {activeMetrics.map(m => (
            <div key={m.label} className={`bg-white/5 border border-white/10 backdrop-blur-md rounded-xl p-4 border-l-4 ${m.borderCls}`}>
              <p className="text-xs font-medium text-zinc-300 mb-1">{m.label}</p>
              <div className="flex items-end justify-between">
                <span className="font-bold text-2xl text-white" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>{m.value}</span>
                <span className="material-symbols-outlined text-sm mb-1" style={{ color: m.color, fontVariationSettings: "'FILL' 1" }}>{m.icon}</span>
              </div>
            </div>
          ))}
        </section>

        {/* 模型胜率对比 */}
        <section className="bg-white/5 border border-white/10 backdrop-blur-md rounded-xl p-5">
          <h3 className="font-bold text-base mb-4 text-white" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>模型胜率对比</h3>
          <div className="space-y-4">
            {activeAccuracyBars.map(b => (
              <div key={b.label}>
                <div className="flex justify-between text-sm mb-1.5">
                  <span className="text-zinc-300 font-medium">{b.label}</span>
                  <span className={`font-bold ${b.textColor}`}>{b.pct}%</span>
                </div>
                <div className="w-full bg-white/10 rounded-full h-2">
                  <div className="h-2 rounded-full" style={{ width: `${b.pct}%`, backgroundColor: b.barColor, boxShadow: `0 0 10px ${b.barColor}80` }} />
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* 模型校准 */}
        <section className="bg-white/5 border border-white/10 backdrop-blur-md rounded-xl p-5">
          <div className="flex justify-between items-center mb-3">
            <h3 className="font-bold text-base text-white" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>模型校准</h3>
            <span className="material-symbols-outlined text-zinc-400">scatter_plot</span>
          </div>
          <svg viewBox="0 0 100 100" className="w-full h-48 bg-black/30 rounded-lg border border-white/5" preserveAspectRatio="xMidYMid meet">
            <defs>
              <filter id="dot-glow-tab" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="1.2" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
            </defs>
            <line x1="5" y1="95" x2="95" y2="5" stroke="rgba(255,255,255,0.2)" strokeDasharray="3" strokeWidth="0.8" />
            {activeScatterDots.map((d, i) => (
              <circle key={i} cx={d.l} cy={100 - d.b} r="2.5" fill="#E91E63" opacity="0.9" filter="url(#dot-glow-tab)" />
            ))}
            <text x="93" y="99" textAnchor="end" fontSize="6" fill="rgba(255,255,255,0.45)">预测概率</text>
            <text x="7" y="8" textAnchor="start" fontSize="6" fill="rgba(255,255,255,0.45)">实际概率</text>
          </svg>
        </section>

      </div>
    );
  }

  // ── LIGHT ────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col gap-4">

      {/* 量化策略回测 Hero Card */}
      <section className="bg-white rounded-xl p-5 shadow-[0_1px_4px_rgba(25,28,29,0.08)]">
        <div className="flex justify-between items-start mb-3">
          <div>
            <h2 className="font-bold text-[#5b3f43] text-[13px] tracking-widest uppercase mb-1">量化策略回测</h2>
            <div className="flex items-baseline gap-2">
              <span className="font-extrabold text-5xl text-[#191c1d] tracking-tighter" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                {heroMultiplier}
              </span>
              <span className="text-[#b7004d] font-bold flex items-center bg-[#ffd9de] px-2 py-0.5 rounded-md text-sm">
                <span className="material-symbols-outlined text-[16px] mr-1">trending_up</span>
                {heroReturnPct}
              </span>
            </div>
            <p className="text-[15px] text-[#5b3f43] mt-1">{heroSubtitle}</p>
          </div>
          <div className="flex flex-col items-end gap-2">
            {isDemo && (
              <span className="text-xs font-bold px-2 py-0.5 rounded-full border border-[#5b3f43]/20 text-[#5b3f43]/60">
                示例数据 · 登录查看实时
              </span>
            )}
            <div className="bg-[#eceeef] p-2 rounded-lg flex-shrink-0">
              <span className="material-symbols-outlined text-[#005faf]">monitoring</span>
            </div>
          </div>
        </div>
        {/* Legend */}
        <div className="flex gap-4 mb-2">
          {activeChartLines.map(l => (
            <div key={l.label} className="flex items-center gap-1.5">
              <div className="w-5 h-0.5 rounded-full" style={{ backgroundColor: l.color }} />
              <span className="text-[13px] font-bold text-[#5b3f43]">{l.label}</span>
            </div>
          ))}
        </div>
        {/* Chart */}
        <div className="h-28 w-full relative border-b border-[#e1e3e4] pb-1 mb-6">
          <svg className="absolute inset-0 w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 40">
            {activeChartLines.map(l => (
              <polyline key={l.label} points={l.points} fill="none" stroke={l.color}
                strokeWidth="1.5" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
            ))}
          </svg>
          <div className="absolute -bottom-5 left-0 right-0 flex justify-between text-[13px] text-[#5b3f43]">
            {activeChartDates.map(d => <span key={d}>{d}</span>)}
          </div>
        </div>
      </section>

      {/* KPI 2×2 Grid */}
      <section className="grid grid-cols-2 gap-3">
        {activeMetrics.map(m => (
          <div key={m.label} className={`bg-white rounded-xl p-4 shadow-[0_1px_4px_rgba(25,28,29,0.08)] border-l-4 ${m.borderCls}`}>
            <p className="text-[13px] font-medium text-[#5b3f43] mb-1">{m.label}</p>
            <div className="flex items-end justify-between">
              <span className="font-bold text-2xl text-[#191c1d]" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>{m.value}</span>
              <span className="material-symbols-outlined text-sm mb-1" style={{ color: m.color, fontVariationSettings: "'FILL' 1" }}>{m.icon}</span>
            </div>
          </div>
        ))}
      </section>

      {/* 模型胜率对比 */}
      <section className="bg-white rounded-xl p-5 shadow-[0_1px_4px_rgba(25,28,29,0.08)]">
        <h3 className="font-bold text-base mb-4 text-[#191c1d]" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>模型胜率对比</h3>
        <div className="space-y-4">
          {activeAccuracyBars.map(b => (
            <div key={b.label}>
              <div className="flex justify-between text-[15px] mb-1.5">
                <span className="text-[#5b3f43] font-medium">{b.label}</span>
                <span className={`font-bold ${b.textColor}`}>{b.pct}%</span>
              </div>
              <div className="w-full bg-[#e6e8e9] rounded-full h-2">
                <div className={`${b.barColor} h-2 rounded-full`} style={{ width: `${b.pct}%` }} />
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 模型校准 */}
      <section className="bg-white rounded-xl p-5 shadow-[0_1px_4px_rgba(25,28,29,0.08)]">
        <div className="flex justify-between items-center mb-3">
          <h3 className="font-bold text-base text-[#191c1d]" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>模型校准</h3>
          <span className="material-symbols-outlined text-[#5b3f43]">scatter_plot</span>
        </div>
        <svg viewBox="0 0 100 100" className="w-full h-48 bg-[#f2f4f5] rounded-lg" preserveAspectRatio="xMidYMid meet">
          <line x1="5" y1="95" x2="95" y2="5" stroke="#e4bdc2" strokeDasharray="3" strokeWidth="0.8" />
          {activeScatterDots.map((d, i) => (
            <circle key={i} cx={d.l} cy={100 - d.b} r="2" fill="#b7004d" />
          ))}
          <text x="93" y="99" textAnchor="end" fontSize="7" fill="#5b3f43">预测概率</text>
          <text x="7" y="8" textAnchor="start" fontSize="7" fill="#5b3f43">实际概率</text>
        </svg>
      </section>

    </div>
  );
}
