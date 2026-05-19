'use client';

import React, { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { ShotMapData, getVenueData } from '@/hooks/useMatchPayload';

interface Props {
  shotData:      ShotMapData;
  homeTeamName?: string;
  awayTeamName?: string;
}

const ShotMapScatter: React.FC<Props> = ({ shotData, homeTeamName = 'Home', awayTeamName = 'Away' }) => {
  const chartRef = useRef<HTMLDivElement>(null);
  const [selectedTeam, setSelectedTeam] = useState<'home' | 'away'>('home');
  const [view, setView] = useState<'overall' | 'venue_specific'>('overall');
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted || !chartRef.current || !shotData) return;

    const chart = echarts.init(chartRef.current, null, { renderer: 'svg' });

    // 1. 获取当前选定队伍在该视图下的原始射门数据
    const teamPayload = selectedTeam === 'home' ? shotData.home_team : shotData.away_team;
    const rawShots = getVenueData(teamPayload, selectedTeam, view);

    if (rawShots.length === 0) {
      chart.dispose();
      return;
    }

    // 2. 准备渲染数据
    const displayShots = rawShots.map(s => {
      // 保持坐标逻辑：x (深度) 52.5-105, y (宽度) 0-68
      const displayX = Math.max(52.5, s.x);
      return {
        value: [68 - s.y, displayX, s.xg, s.outcome, s.player || 'Player'],
        symbol: s.outcome === 'Goal' 
          ? 'path://M12 .587l3.668 7.568 8.332 1.151-6.064 5.828 1.48 8.279-7.416-3.967-7.417 3.967 1.481-8.279-6.064-5.828 8.332-1.151z' 
          : 'circle',
        symbolSize: Math.max(8, Math.min(22, (s.xg || 0.1) * 85)),
        itemStyle: {
          color: s.outcome === 'Goal' ? '#4ade80' : 'rgba(255, 60, 106, 0.4)',
          borderColor: s.outcome === 'Goal' ? '#fff' : '#ff3c6a',
          borderWidth: 1.5,
          shadowBlur: s.outcome === 'Goal' ? 15 : 0,
          shadowColor: '#4ade80'
        },
        z: s.outcome === 'Goal' ? 10 : 5
      };
    });

    const option: echarts.EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(10, 10, 10, 0.95)',
        borderColor: 'rgba(255, 255, 255, 0.1)',
        padding: 10,
        textStyle: { color: '#f1f1f1', fontSize: 12, fontFamily: 'monospace' },
        formatter: (params: any) => {
          if (!params.data || !params.data.value) return '';
          const [y, x, xg, outcome, player] = params.data.value;
          const statusColor = outcome === 'Goal' ? '#4ade80' : '#ff3c6a';
          return `
            <div style="min-width: 140px;">
              <div style="font-weight: 900; color: ${statusColor}; margin-bottom: 6px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 4px; letter-spacing: 0.1em;">${player.toUpperCase()}</div>
              <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                <span style="color: #888; font-size: 9px;">Expected Goals:</span>
                <span style="font-weight: bold; color: #fff">${xg.toFixed(3)}</span>
              </div>
              <div style="display: flex; justify-content: space-between;">
                <span style="color: #888; font-size: 9px;">Outcome:</span>
                <span style="font-weight: bold; color: #fff; text-transform: uppercase;">${outcome}</span>
              </div>
            </div>
          `;
        }
      },
      xAxis: { type: 'value', min: 0, max: 68, splitLine: { show: false }, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false } },
      yAxis: { type: 'value', min: 52.5, max: 105, splitLine: { show: false }, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false } },
      grid: { top: 20, bottom: 20, left: 20, right: 20, containLabel: false },
      series: [
        {
          type: 'scatter',
          coordinateSystem: 'cartesian2d',
          data: displayShots,
          z: 10,
          emphasis: { itemStyle: { borderWidth: 3, borderColor: '#fff', opacity: 1 } }
        },
        {
          type: 'custom',
          coordinateSystem: 'cartesian2d',
          renderItem: (params: any, api: any) => {
            const getCoord = (pt: [number, number]) => api.coord(pt);
            const optaLineStyle = { stroke: '#00f2ff', lineWidth: 1.5, opacity: 0.5, shadowBlur: 10, shadowColor: 'rgba(0, 242, 255, 0.4)' };
            const lines: any[] = [];
            
            // 1. Boundary & Pitch Markings
            const points = [getCoord([0, 52.5]), getCoord([0, 105]), getCoord([68, 105]), getCoord([68, 52.5])];
            lines.push({ type: 'polyline', shape: { points }, style: optaLineStyle });
            lines.push({ type: 'line', shape: { x1: points[0][0], y1: points[0][1], x2: points[3][0], y2: points[3][1] }, style: optaLineStyle });

            // Penalty Area
            lines.push({ type: 'polyline', shape: { points: [getCoord([13.84, 105]), getCoord([13.84, 88.5]), getCoord([54.16, 88.5]), getCoord([54.16, 105])] }, style: optaLineStyle });
            // Goal Area
            lines.push({ type: 'polyline', shape: { points: [getCoord([24.84, 105]), getCoord([24.84, 99.5]), getCoord([43.16, 99.5]), getCoord([43.16, 105])] }, style: optaLineStyle });
            
            // Penalty Spot & Arc
            const spot = getCoord([34, 94]);
            lines.push({ type: 'circle', shape: { cx: spot[0], cy: spot[1], r: 2.5 }, style: { fill: '#00f2ff', opacity: 0.8 } });
            lines.push({ type: 'arc', shape: { cx: spot[0], cy: spot[1], r: Math.abs(getCoord([43.15, 94])[0] - spot[0]), startAngle: 0.8, endAngle: 2.34 }, style: optaLineStyle });

            // Goal Frame
            const g1 = getCoord([30.34, 105]), g2 = getCoord([37.66, 105]);
            lines.push({ type: 'rect', shape: { x: g1[0], y: g1[1] - 5, width: g2[0] - g1[0], height: 5 }, style: { fill: 'rgba(0, 242, 255, 0.1)', stroke: '#00f2ff', lineWidth: 1 } });

            return { type: 'group', children: lines };
          },
          data: [[34, 75]],
          z: 1
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
  }, [isMounted, shotData, selectedTeam, view]);

  if (!isMounted) return <div className="w-full h-[450px] bg-white/5 animate-pulse rounded-3xl" />;

  return (
    <div className="glass-panel p-8 relative overflow-hidden group">
      <div className="flex flex-col xl:flex-row justify-between items-start xl:items-center gap-6 mb-10 z-10 relative">
        <div className="border-l-4 border-secondary-container/60 pl-5">
          <h3 className="text-xl font-headline font-black italic tracking-tight text-foreground uppercase">
            时政射门分布 <span className="text-secondary-container/80 not-italic opacity-80">(SHOT DISTRIBUTION)</span>
          </h3>
          <p className="text-xs font-bold text-zinc-500 uppercase tracking-widest mt-1.5 opacity-50">Real-time Opta Coordinates v4.0</p>
        </div>

        <div className="flex flex-wrap gap-4 z-20">
          {/* Team Switcher */}
          <div className="inline-flex p-1 bg-surface-dim/40 rounded-2xl border border-white/5 shadow-ghost-border">
            {[ { id: 'home', name: homeTeamName }, { id: 'away', name: awayTeamName } ].map((t) => (
              <button
                key={t.id}
                onClick={() => setSelectedTeam(t.id as any)}
                className={`px-5 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
                  selectedTeam === t.id ? 'bg-secondary-container text-black' : 'text-zinc-500 hover:text-foreground'
                }`}
              >
                {t.name}
              </button>
            ))}
          </div>

          {/* View Switcher */}
          <div className="inline-flex p-1 bg-surface-dim/40 rounded-2xl border border-white/5 shadow-ghost-border">
            <button
              onClick={() => setView('overall')}
              className={`px-5 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
                view === 'overall' ? 'text-primary-container bg-white/5' : 'text-zinc-500 hover:text-foreground'
              }`}
            >
              全部
            </button>
            <button
              onClick={() => setView('venue_specific')}
              className={`px-5 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
                view === 'venue_specific' ? 'text-primary-container bg-white/5' : 'text-zinc-500 hover:text-foreground'
              }`}
            >
              相同主客
            </button>
          </div>
        </div>
      </div>

      <div className="flex justify-center items-center bg-surface-dim/10 rounded-[2.5rem] border border-white/[0.04] p-4 shadow-inner w-full max-w-[500px] aspect-[68/52.5] mx-auto">
        <div ref={chartRef} className="w-full h-full relative z-10" />
      </div>

      <div className="absolute top-4 left-8 flex items-center gap-3">
        <div className="w-2 h-2 rounded-full bg-secondary-container animate-pulse shadow-[0_0_8px_var(--color-secondary-container)]" />
        <span className="text-xs font-bold text-secondary-container/40 uppercase tracking-[0.2em]">Live Data Tracking Active</span>
      </div>
    </div>
  );
};

export default ShotMapScatter;
