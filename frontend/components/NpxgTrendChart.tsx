'use client';

import React, { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { NpxgTrend, getVenueData } from '@/hooks/useMatchPayload';
import { useTheme } from '@/components/ThemeProvider';

interface Props {
  npxgData:      NpxgTrend;
  homeTeamName?: string;
  awayTeamName?: string;
}

const NpxgTrendChart: React.FC<Props> = ({ npxgData, homeTeamName = 'Home', awayTeamName = 'Away' }) => {
  const chartRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<'overall' | 'venue_specific'>('overall');
  const [isMounted, setIsMounted] = useState(false);
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted || !chartRef.current || !npxgData) return;

    const chart = echarts.init(chartRef.current, null, { renderer: 'svg' });

    // Theme-aware palette
    const axisLabelColor  = isDark ? '#ffffff'  : '#374151';
    const axisLineColor   = isDark ? 'rgba(255,255,255,0.1)'   : 'rgba(0,0,0,0.1)';
    const splitLineColor  = isDark ? 'rgba(255,255,255,0.05)'  : 'rgba(0,0,0,0.07)';
    const legendTextColor = isDark ? '#ffffff'   : '#374151';
    const legendInactive  = isDark ? 'rgba(255,255,255,0.15)'  : 'rgba(0,0,0,0.2)';
    const tooltipBg       = isDark ? 'rgba(8,10,16,0.97)'      : 'rgba(255,255,255,0.97)';
    const tooltipBorder   = isDark ? 'rgba(255,255,255,0.08)'  : 'rgba(0,0,0,0.12)';
    const tooltipTextClr  = isDark ? '#ddd'                    : '#111827';
    const homeColor       = isDark ? '#00F0FF'                 : '#0047B3';
    const awayColor       = isDark ? '#FF00E5'                 : '#B0147A';
    const homeShadow      = isDark ? 'rgba(0,240,255,0.8)'     : 'transparent';
    const awayShadow      = isDark ? 'rgba(255,0,229,0.8)'     : 'transparent';
    const homeShadowLine  = isDark ? 'rgba(0,240,255,0.5)'     : 'transparent';
    const awayShadowLine  = isDark ? 'rgba(255,0,229,0.5)'     : 'transparent';
    const homeAreaStart   = isDark ? 'rgba(0,240,255,0.18)'    : 'rgba(0,112,255,0.08)';
    const awayAreaStart   = isDark ? 'rgba(255,0,229,0.12)'    : 'rgba(219,39,119,0.08)';
    const shadowBlurPt    = isDark ? 12 : 0;
    const shadowBlurLine  = isDark ? 10 : 0;

    // 1. 获取视图数据
    const homeSeriesData = getVenueData(npxgData.home_team, 'home', view);
    const awaySeriesData = getVenueData(npxgData.away_team, 'away', view);

    // 2. 检查空数据
    if (homeSeriesData.length === 0 && awaySeriesData.length === 0) {
      chart.dispose();
      return;
    }

    // 3. 准备 X 轴标签（对手名）- 保持“最旧在前，最新在后”的阅读习惯（数组通常返回最新在前，需要逆序展示）
    // 注意：如果我们期望 G1 是最久远的，G5 是最近的，则需要 reverse
    const renderHome = [...homeSeriesData].reverse();
    const renderAway = [...awaySeriesData].reverse();
    const xAxisLabels = renderHome.map((entry, i) => `G${i + 1}`);

    const option: echarts.EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        confine: true,
        backgroundColor: tooltipBg,
        borderColor: tooltipBorder,
        borderWidth: 1,
        padding: [12, 16],
        textStyle: { color: tooltipTextClr, fontSize: 12, fontFamily: 'monospace' },
        extraCssText: 'box-shadow: 0 8px 32px rgba(0,0,0,0.2); backdrop-filter: blur(12px); width: 210px;',
        // Smart positioning: right-of-cursor by default, flip left when near right edge, clamp to bounds
        position: (point: number[], _params: any, _dom: any, _rect: any, size: any) => {
          const [x, y]               = point;
          const [contentW, contentH] = size.contentSize as [number, number];
          const [viewW, viewH]       = size.viewSize    as [number, number];
          const gap = 14;

          // Prefer right; flip left if overflowing right edge
          let left = x + gap;
          if (left + contentW > viewW - gap) {
            left = x - contentW - gap;
          }
          // Hard clamp: never go outside chart area
          left = Math.max(4, Math.min(left, viewW - contentW - 4));

          // Vertical: center on cursor, clamped
          let top = y - contentH / 2;
          top = Math.max(4, Math.min(top, viewH - contentH - 4));

          return [left, top];
        },
        formatter: (params: any) => {
          const idx = params[0]?.dataIndex ?? 0;
          const homeEntry = renderHome[idx];
          const awayEntry = renderAway[idx];
          const dateStr = homeEntry?.date ? homeEntry.date.slice(5) : '';  // "MM-DD"
          // Truncate team name to fit in fixed-width tooltip
          const truncate = (s: string, n: number) => s.length > n ? s.slice(0, n) + '…' : s;
          let res = `<div style="margin-bottom:8px;border-bottom:1px solid rgba(255,255,255,0.08);padding-bottom:6px;">
            <span style="font-size:9px;letter-spacing:0.15em;color:#ffffff;text-transform:uppercase;">NPXGD${dateStr ? ' · ' + dateStr : ''}</span>
          </div>`;
          params.forEach((p: any) => {
            const isHome = p.seriesName === homeTeamName;
            const entry  = isHome ? homeEntry : awayEntry;
            const opp    = truncate(entry?.opponent || '—', 12);
            const name   = truncate(p.seriesName, 11);
            const val: number = p.value ?? 0;
            const arrow = val > 0 ? '▲' : val < 0 ? '▼' : '—';
            const arrowColor  = val > 0 ? '#4ade80' : val < 0 ? '#f87171' : '#ffffff';
            const valColor    = val > 0 ? '#4ade80' : val < 0 ? '#f87171' : '#fff';
            // Two-row layout: name+opponent on first line, value on second
            res += `<div style="margin-bottom:7px;padding-left:4px;border-left:3px solid ${p.color};">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:6px;">
                <span style="color:${p.color};font-weight:700;font-size:10px;white-space:nowrap;">${name}</span>
                <span style="display:flex;align-items:center;gap:4px;margin-left:auto;">
                  <span style="color:${arrowColor};font-size:10px;">${arrow}</span>
                  <span style="color:${valColor};font-weight:800;font-size:13px;">${val.toFixed(2)}</span>
                </span>
              </div>
              <div style="color:${isDark ? '#ffffff' : 'rgba(0,0,0,0.5)'};font-size:9px;font-weight:700;margin-top:1px;">vs ${opp}</div>
            </div>`;
          });
          return res;
        }
      },
      legend: {
        data: [homeTeamName, awayTeamName],
        textStyle: { color: legendTextColor, fontSize: 12, fontWeight: isDark ? 800 : 'bold' },
        inactiveColor: legendInactive,
        selectedMode: 'multiple',
        icon: 'roundRect',
        itemWidth: 16,
        itemHeight: 4,
        bottom: 8,
      },
      grid: {
        top: '15%',
        left: '5%',
        right: '5%',
        bottom: '20%',
        containLabel: true
      },
      xAxis: {
        type: 'category',
        data: xAxisLabels,
        axisLine: { lineStyle: { color: axisLineColor } },
        axisLabel: { color: axisLabelColor, fontSize: 12, fontWeight: 'bold' },
        splitLine: { show: false }
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        splitLine: { lineStyle: { color: splitLineColor, type: 'dashed' } },
        axisLabel: { color: axisLabelColor, fontSize: 12 }
      },
      series: [
        {
          name: homeTeamName,
          type: 'line',
          smooth: 0.4,
          data: renderHome.map(m => m.npxg_diff),
          symbolSize: 9,
          showSymbol: true,
          animationDuration: 1500,
          animationEasing: 'cubicOut' as const,
          itemStyle: {
            color: homeColor,
            borderColor: homeColor,
            borderWidth: 2,
            shadowBlur: shadowBlurPt,
            shadowColor: homeShadow,
          },
          lineStyle: { width: 2.5, shadowBlur: shadowBlurLine, shadowColor: homeShadowLine },
          emphasis: {
            scale: 1.4,
            itemStyle: { shadowBlur: isDark ? 20 : 0, shadowColor: isDark ? 'rgba(0,240,255,1)' : 'transparent' },
          },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: homeAreaStart },
              { offset: 1, color: 'transparent' }
            ])
          }
        },
        {
          name: awayTeamName,
          type: 'line',
          smooth: 0.4,
          data: renderAway.map(m => m.npxg_diff),
          symbolSize: 9,
          showSymbol: true,
          animationDuration: 1500,
          animationEasing: 'cubicOut' as const,
          itemStyle: {
            color: awayColor,
            borderColor: awayColor,
            borderWidth: 2,
            shadowBlur: shadowBlurPt,
            shadowColor: awayShadow,
          },
          lineStyle: { width: 2.5, shadowBlur: shadowBlurLine, shadowColor: awayShadowLine },
          emphasis: {
            scale: 1.4,
            itemStyle: { shadowBlur: isDark ? 20 : 0, shadowColor: isDark ? 'rgba(255,0,229,1)' : 'transparent' },
          },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: awayAreaStart },
              { offset: 1, color: 'transparent' }
            ])
          }
        }
      ]
    };

    chart.setOption(option);

    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.dispose();
    };
  }, [isMounted, npxgData, view, homeTeamName, awayTeamName, isDark]);

  if (!isMounted) return <div className="w-full h-[350px] bg-slate-200 dark:bg-white/5 animate-pulse rounded-3xl" />;

  return (
    <div className="relative overflow-hidden">
      {/* HUD Header */}
      <div className="flex flex-col gap-4 mb-8 z-10 relative">
        <div className="border-l-4 border-[color:var(--color-primary-container)]/30 pl-4">
          <h3 className="text-xl font-headline font-black italic tracking-wider text-[#191c1d] dark:text-white uppercase">
            战力演化分析 <span className="text-[#005faf] dark:text-[#3B82F6] not-italic opacity-90">(NPXGD TREND)</span>
          </h3>
          <p className="text-xs font-bold text-zinc-500 dark:opacity-50 uppercase tracking-[0.3em] mt-1.5">量化战力指数 v2.1</p>
        </div>

        {/* View Toggle */}
        <div className="flex p-1 bg-surface-dim/40 rounded-2xl border border-slate-200 dark:border-white/5 self-start">
          <button
            onClick={() => setView('overall')}
            className={`px-5 py-1.5 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
              view === 'overall'
                ? 'bg-primary-container text-black shadow-[0_0_20px_rgba(0,240,255,0.3)]'
                : 'text-zinc-500 hover:text-foreground'
            }`}
          >
            近 5 场全部
          </button>
          <button
            onClick={() => setView('venue_specific')}
            className={`px-5 py-1.5 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
              view === 'venue_specific'
                ? 'bg-primary-container text-black shadow-[0_0_20px_rgba(0,240,255,0.3)]'
                : 'text-zinc-500 hover:text-foreground'
            }`}
          >
            相同主客场
          </button>
        </div>
      </div>

      <div ref={chartRef} className="w-full h-[350px] relative z-10" />

      {/* Decorative HUD Elements */}
      <div className="absolute top-4 right-8 text-xs font-mono text-slate-300 dark:text-primary-container/20 tracking-tighter uppercase whitespace-pre leading-none pointer-events-none">
        01010101_LIVE_FEED
        LATENCY_12MS
        ENCRYPTED_SYNC
      </div>
    </div>
  );
};

export default NpxgTrendChart;
