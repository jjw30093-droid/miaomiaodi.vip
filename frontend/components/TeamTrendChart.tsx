'use client';

import React, { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { TrendPayload } from '@/types/report';

interface Props {
  trendData: TrendPayload;
  homeTeamName: string;
  awayTeamName: string;
}

const TeamTrendChart: React.FC<Props> = ({ trendData, homeTeamName, awayTeamName }) => {
  const chartRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<'all' | 'homeAway'>('all');
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted || !chartRef.current || !trendData) return;

    // Use SVG renderer for better mobile/Retina support
    const chart = echarts.init(chartRef.current, null, { renderer: 'svg' });
    
    // 获取当前视图下的数据
    const homeData = view === 'all' ? trendData.homeTeam.last5All : trendData.homeTeam.last5HomeAway;
    const awayData = view === 'all' ? trendData.awayTeam.last5All : trendData.awayTeam.last5HomeAway;

    // 格式化 X 轴 (使用通用 G1-G5 序号)
    const xAxisLabels = homeData.map((_, i) => `G${i+1}`);

    const option: echarts.EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(10, 10, 10, 0.95)',
        borderColor: 'rgba(255, 255, 255, 0.1)',
        padding: 12,
        textStyle: { color: '#ddd', fontSize: 12 },
        formatter: (params: any) => {
          let res = `<div style="font-family:monospace;margin-bottom:8px;border-bottom:1px solid rgba(255,255,255,0.1);padding-bottom:4px">Match Performance Index</div>`;
          params.forEach((p: any) => {
            const isHomeSeries = p.seriesName === homeTeamName;
            const matchData = isHomeSeries ? homeData[p.dataIndex] : awayData[p.dataIndex];
            const opponentLabel = matchData?.opponent ?? '—';
            res += `<div style="display:flex;justify-content:space-between;gap:16px;margin-bottom:4px">
              <span style="color:${p.color}">${p.seriesName} <span style="color:#666;font-size:10px">(vs ${opponentLabel})</span></span>
              <span style="color:#fff;font-weight:bold">${p.value.toFixed(2)}</span>
            </div>`;
          });
          return res;
        }
      },
      legend: {
        data: [homeTeamName, awayTeamName],
        textStyle: { color: '#ccc', fontSize: 12 },
        bottom: 0
      },
      grid: {
        top: '15%',
        left: '5%',
        right: '5%',
        bottom: '15%',
        containLabel: true
      },
      xAxis: {
        type: 'category',
        data: xAxisLabels,
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
        axisLabel: { 
          color: '#fff', 
          fontSize: 12, 
          fontWeight: 900,
          textShadowBlur: 8,
          textShadowColor: 'rgba(255, 255, 255, 0.6)'
        },
        splitLine: { show: false }
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)', type: 'dashed' } },
        axisLabel: { 
          color: '#fff',
          fontWeight: 900,
          textShadowBlur: 8,
          textShadowColor: 'rgba(255, 255, 255, 0.6)'
        }
      },
      series: [
        {
          name: homeTeamName,
          type: 'line',
          smooth: true,
          data: homeData.map(m => m.npxGD ?? (m as any).npxg_diff ?? 0),
          symbolSize: 8,
          itemStyle: { color: '#06b6d4' },
          lineStyle: { 
            width: 3, 
            shadowBlur: 10, 
            shadowColor: 'rgba(6, 182, 212, 0.5)' 
          },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(6,182,212,0.2)' },
              { offset: 1, color: 'transparent' }
            ])
          }
        },
        {
          name: awayTeamName,
          type: 'line',
          smooth: true,
          data: awayData.map(m => m.npxGD ?? (m as any).npxg_diff ?? 0),
          symbolSize: 8,
          itemStyle: { color: '#a78bfa' },
          lineStyle: { 
            width: 3, 
            shadowBlur: 10, 
            shadowColor: 'rgba(167, 139, 250, 0.5)' 
          },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(167,139,250,0.15)' },
              { offset: 1, color: 'transparent' }
            ])
          }
        }
      ]
    };

    if (homeData.length === 0 && awayData.length === 0) {
      chart.dispose();
      return;
    }

    chart.setOption(option);

    // Initial resize to pick up container dimensions
    const timer = setTimeout(() => {
      chart.resize();
    }, 200);

    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      clearTimeout(timer);
      window.removeEventListener('resize', handleResize);
      chart.dispose();
    };
  }, [isMounted, trendData, view, homeTeamName, awayTeamName]);

  if (!isMounted) return <div className="w-full h-[320px] md:h-[400px] bg-white/5 animate-pulse rounded-[2.5rem]" />;

  return (
    <div className="glass-panel p-8 relative overflow-hidden group transition-all hover:bg-white/[0.04]">
      {/* 装饰性网格背景 - 增强 HUD 感 */}
      <div className="absolute inset-0 opacity-[0.03] pointer-events-none" style={{ backgroundImage: 'radial-gradient(circle, #fff 1px, transparent 1px)', backgroundSize: '24px 24px' }} />

      {/* Header & Toggle */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 mb-10 z-10 relative">
        <div>
          <h3 className="text-sm font-headline font-black italic tracking-[0.25em] text-foreground uppercase flex items-center gap-3">
            <span className="w-1 h-5 bg-gradient-to-b from-primary-container to-secondary-container rounded-full" />
            预期进球（除点球）差值
          </h3>
          <p className="text-xs font-bold text-zinc-500 uppercase tracking-widest mt-1.5 opacity-60">npxGD :: Historical Performance Index</p>
        </div>

        {/* 精美切换器 - 遵循 No-line 规则 */}
        <div className="flex p-1 bg-surface-dim/40 rounded-2xl border border-white/5 shadow-ghost-border self-center md:self-auto">
          <button
            onClick={() => setView('all')}
            className={`px-6 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
              view === 'all' 
                ? 'bg-primary-container text-black shadow-[0_0_20px_rgba(0,240,255,0.3)]' 
                : 'text-zinc-500 hover:text-foreground'
            }`}
          >
            近 5 场全部
          </button>
          <button
            onClick={() => setView('homeAway')}
            className={`px-6 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
              view === 'homeAway' 
                ? 'bg-primary-container text-black shadow-[0_0_20px_rgba(0,240,255,0.3)]' 
                : 'text-zinc-500 hover:text-foreground'
            }`}
          >
            相同主客场
          </button>
        </div>
      </div>

      {/* Chart Container */}
      <div ref={chartRef} className="w-full h-[320px] md:h-[400px] relative z-10" />
    </div>
  );
};

export default TeamTrendChart;
