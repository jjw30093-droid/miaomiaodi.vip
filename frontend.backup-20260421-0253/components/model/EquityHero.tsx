'use client';
import React, { useState } from 'react';
import { ModelHealthData, EquityBlock } from './types';
import EChartWrapper from '@/components/EChartWrapper';
import { TrendingUp, TrendingDown } from 'lucide-react';

interface Props {
  equity: ModelHealthData['equity'];
  updatedAt: string;
}

type StakeMode = 'fixed' | 'kelly_half';

const STRATEGY_COLORS: Record<string, string> = {
  WDL:  '#00F0FF',
  OU:   '#FF00E5',
  '合成': '#00ffb7',
};

function buildOption(block: EquityBlock | undefined) {
  if (!block || !block.strategies || block.strategies.length === 0) return {};

  const dates = block.strategies[0]?.points.map(p => p.date) ?? [];

  const series = block.strategies.map(s => ({
    name: s.name,
    type: 'line',
    data: s.points.map(p => p.value),
    smooth: true,
    symbol: 'none',
    lineStyle: { color: s.color, width: 2 },
    areaStyle: {
      color: {
        type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [
          { offset: 0, color: s.color + '30' },
          { offset: 1, color: s.color + '00' },
        ],
      },
    },
    itemStyle: { color: s.color },
    emphasis: { scale: false },
  }));

  return {
    backgroundColor: 'transparent',
    animation: true,
    animationDuration: 800,
    animationEasing: 'cubicOut',
    legend: {
      top: 0,
      right: 0,
      textStyle: { color: 'rgba(255,255,255,0.5)', fontFamily: 'Space Grotesk', fontSize: 10, fontWeight: 900 },
      icon: 'circle',
      itemWidth: 8,
      itemHeight: 8,
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(5,8,20,0.95)',
      borderColor: 'rgba(0,240,255,0.2)',
      borderWidth: 1,
      textStyle: { color: '#fff', fontFamily: 'monospace', fontSize: 11 },
      formatter: (params: any[]) => {
        const date = params[0]?.axisValue ?? '';
        const lines = params.map(p =>
          `<span style="color:${p.color}">●</span> ${p.seriesName}: <b>${Number(p.value).toFixed(3)}</b>`
        ).join('<br/>');
        return `<div style="font-size:10px;margin-bottom:4px;color:rgba(255,255,255,0.4)">${date}</div>${lines}`;
      },
    },
    dataZoom: [
      {
        type: 'inside',
        start: 0,
        end: 100,
      },
      {
        type: 'slider',
        bottom: 0,
        height: 20,
        borderColor: 'transparent',
        backgroundColor: 'rgba(255,255,255,0.03)',
        fillerColor: 'rgba(0,240,255,0.08)',
        handleStyle: { color: '#00F0FF', borderColor: '#00F0FF' },
        textStyle: { color: 'rgba(255,255,255,0.3)', fontSize: 9 },
        moveHandleStyle: { color: '#00F0FF' },
        emphasis: { handleStyle: { color: '#00F0FF' } },
      },
    ],
    grid: { top: 32, right: 16, bottom: 52, left: 56 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: {
        color: 'rgba(255,255,255,0.25)',
        fontSize: 9,
        fontFamily: 'monospace',
        formatter: (v: string) => v.slice(5), // MM-DD
        interval: Math.max(0, Math.floor(dates.length / 6) - 1),
      },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        color: 'rgba(255,255,255,0.3)',
        fontSize: 9,
        fontFamily: 'monospace',
        formatter: (v: number) => v.toFixed(2),
      },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)', type: 'dashed' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series,
  };
}

export default function EquityHero({ equity, updatedAt }: Props) {
  const [mode, setMode] = useState<StakeMode>('fixed');

  const block = equity?.[mode];
  const comb  = block?.strategies?.find(s => s.name === '合成');
  const finalVal = comb?.points?.at(-1)?.value ?? null;
  const startVal = 1.0;
  const pct = finalVal != null ? ((finalVal - startVal) / startVal * 100) : null;
  const isUp = pct != null && pct >= 0;

  const updatedStr = updatedAt
    ? new Date(updatedAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
    : '—';

  return (
    <div className="glass-panel rounded-3xl border border-white/5 p-5 mb-4">
      {/* Header row */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-black font-mono tabular-nums text-white">
              {finalVal != null ? `×${finalVal.toFixed(2)}` : '—'}
            </span>
            {pct != null && (
              <div className={`flex items-center gap-1 text-sm font-black ${isUp ? 'text-emerald-400' : 'text-rose-400'}`}>
                {isUp ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                {isUp ? '+' : ''}{pct.toFixed(1)}%
              </div>
            )}
          </div>
          <p className="text-[9px] text-white/20 font-mono mt-0.5">起始 ×1.00 → 当前 (合成策略)</p>
        </div>

        <div className="flex flex-col items-end gap-2">
          {/* Stake mode toggle */}
          <div className="flex bg-white/5 rounded-full p-0.5 border border-white/10">
            {(['fixed', 'kelly_half'] as StakeMode[]).map(m => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`px-3 py-1 rounded-full text-[9px] font-black uppercase tracking-wider transition-all ${
                  mode === m
                    ? 'bg-primary-neon/20 text-primary-neon border border-primary-neon/30'
                    : 'text-white/30 hover:text-white/60'
                }`}
              >
                {m === 'fixed' ? '平注' : 'Kelly½'}
              </button>
            ))}
          </div>
          <span className="text-[8px] text-white/15 font-mono">更新 {updatedStr}</span>
        </div>
      </div>

      {/* Stats row */}
      {block && (
        <div className="flex gap-4 mb-4 text-xs font-mono">
          <div>
            <span className="text-white/25 text-[9px]">Sharpe </span>
            <span className="text-primary-neon font-black">{block.sharpe?.toFixed(2) ?? '—'}</span>
          </div>
          <div>
            <span className="text-white/25 text-[9px]">MaxDD </span>
            <span className="text-rose-400 font-black">
              {block.max_drawdown != null ? `${(block.max_drawdown * 100).toFixed(1)}%` : '—'}
            </span>
          </div>
        </div>
      )}

      {/* Chart */}
      <div className="h-52">
        <EChartWrapper option={buildOption(block)} style={{ minHeight: '200px' }} />
      </div>
    </div>
  );
}
