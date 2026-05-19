'use client';

import React, { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { NpxgTrend, getVenueData } from '@/hooks/useMatchPayload';

interface Props {
  npxgData:      NpxgTrend;
  homeTeamName?: string;
  awayTeamName?: string;
}

const NpxgTrendChart: React.FC<Props> = ({ npxgData, homeTeamName = 'Home', awayTeamName = 'Away' }) => {
  const chartRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<'overall' | 'venue_specific'>('overall');
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted || !chartRef.current || !npxgData) return;

    const chart = echarts.init(chartRef.current, null, { renderer: 'svg' });

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
        backgroundColor: 'rgba(10, 10, 10, 0.95)',
        borderColor: 'rgba(255, 255, 255, 0.1)',
        padding: 12,
        textStyle: { color: '#ddd', fontSize: 11, fontFamily: 'monospace' },
        formatter: (params: any) => {
          let res = `<div style="margin-bottom:8px;border-bottom:1px solid rgba(255,255,255,0.1);padding-bottom:4px;font-weight:bold">npxGD REAL-TIME TREND</div>`;
          params.forEach((p: any) => {
            const isHome = p.seriesName === homeTeamName;
            const entry = isHome ? renderHome[p.dataIndex] : renderAway[p.dataIndex];
            const opponent = entry?.opponent || 'Unknown';
            res += `<div style="display:flex;justify-content:space-between;gap:20px;margin-bottom:4px">
              <span style="color:${p.color}">${p.seriesName} <span style="opacity:0.5;font-size:10px">(vs ${opponent})</span></span>
              <span style="color:#fff;font-weight:bold">${p.value.toFixed(2)}</span>
            </div>`;
          });
          return res;
        }
      },
      legend: {
        data: [homeTeamName, awayTeamName],
        textStyle: { color: '#ccc', fontSize: 10, fontWeight: 'bold' },
        bottom: 10
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
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
        axisLabel: { color: '#888', fontSize: 10, fontWeight: 'bold' },
        splitLine: { show: false }
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)', type: 'dashed' } },
        axisLabel: { color: '#888', fontSize: 10 }
      },
      series: [
        {
          name: homeTeamName,
          type: 'line',
          smooth: true,
          data: renderHome.map(m => m.npxg_diff),
          symbolSize: 8,
          itemStyle: { color: '#00F0FF' },
          lineStyle: { width: 3, shadowBlur: 10, shadowColor: 'rgba(0, 240, 255, 0.5)' },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(0, 240, 255, 0.15)' },
              { offset: 1, color: 'transparent' }
            ])
          }
        },
        {
          name: awayTeamName,
          type: 'line',
          smooth: true,
          data: renderAway.map(m => m.npxg_diff),
          symbolSize: 8,
          itemStyle: { color: '#FF00E5' },
          lineStyle: { width: 3, shadowBlur: 10, shadowColor: 'rgba(255, 0, 229, 0.5)' },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(255, 0, 229, 0.1)' },
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
  }, [isMounted, npxgData, view, homeTeamName, awayTeamName]);

  if (!isMounted) return <div className="w-full h-[350px] bg-white/5 animate-pulse rounded-3xl" />;

  return (
    <div className="glass-panel p-8 relative overflow-hidden group">
      {/* HUD Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 mb-10 z-10 relative">
        <div className="border-l-4 border-primary-container/40 pl-5">
          <h3 className="text-xl font-headline font-black italic tracking-wider text-foreground uppercase">
            战力演化分析 <span className="text-primary-container/60 not-italic opacity-80">(NPXGD TREND)</span>
          </h3>
          <p className="text-[9px] font-bold text-zinc-500 uppercase tracking-[0.3em] mt-1.5 opacity-50">Quantitative Performance Index v2.1</p>
        </div>

        {/* View Toggle */}
        <div className="flex p-1 bg-surface-dim/40 rounded-2xl border border-white/5 shadow-ghost-border">
          <button
            onClick={() => setView('overall')}
            className={`px-6 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest transition-all ${
              view === 'overall' 
                ? 'bg-primary-container text-black shadow-[0_0_20px_rgba(0,240,255,0.3)]' 
                : 'text-zinc-500 hover:text-foreground'
            }`}
          >
            近 5 场全部
          </button>
          <button
            onClick={() => setView('venue_specific')}
            className={`px-6 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest transition-all ${
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
      <div className="absolute top-4 right-8 text-[8px] font-mono text-primary-container/20 tracking-tighter uppercase whitespace-pre leading-none pointer-events-none">
        01010101_LIVE_FEED
        LATENCY_12MS
        ENCRYPTED_SYNC
      </div>
    </div>
  );
};

export default NpxgTrendChart;
