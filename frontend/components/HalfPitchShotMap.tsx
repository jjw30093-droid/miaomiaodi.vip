'use client';

import React, { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { AggregatedShotMap } from '@/types/report';

interface Props {
  penetrationData: {
    homeTeam: AggregatedShotMap;
    awayTeam: AggregatedShotMap;
  };
  homeTeamName: string;
  awayTeamName: string;
}

/**
 * Opta-Level Vertical Half-Pitch Shot Map (Chief Data Scientist Ed.)
 * 
 * Coordinate Logic:
 * - X (Depth): 0-105 (105 is Opponent Goal Line). Mapped to Chart yAxis.
 * - Y (Width): 0-68 (0 Left, 68 Right). Mapped to Chart xAxis.
 * - Focus: Attacking Third [45, 105] (Show center circle)
 */
const HalfPitchShotMap: React.FC<Props> = ({ penetrationData, homeTeamName, awayTeamName }) => {
  const chartRef = useRef<HTMLDivElement>(null);
  const [selectedTeam, setSelectedTeam] = useState<'home' | 'away'>('home');
  const [selectedScope, setSelectedScope] = useState<'all' | 'homeAway'>('all');
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted || !chartRef.current || !penetrationData) return;

    const chart = echarts.init(chartRef.current, null, { renderer: 'svg' });
    
    const teamData = (selectedTeam === 'home') ? penetrationData.homeTeam : penetrationData.awayTeam;
    const rawShots = (selectedScope === 'all') ? teamData.last5All : teamData.last5HomeAway;

    // Layering: Goals on top
    const sortedShots = [...rawShots].sort((a, b) => {
      if (a.outcome === 'Goal' && b.outcome !== 'Goal') return 1;
      if (a.outcome !== 'Goal' && b.outcome === 'Goal') return -1;
      return (a.xg || 0) - (b.xg || 0);
    });

    const shotData = sortedShots.map(s => {
      // 核心业务逻辑：中线截断 (Midline Clipping)
      // 如果射门坐标在自家半场 (x < 52.5)，则强制对齐到中线
      const displayX = Math.max(52.5, s.x);
      
      return {
        // 坐标映射逻辑：
        // 1. xAxis (横向/宽度): 0-68. 数据 s.y 通常是 0-68
        // 2. yAxis (纵向/深度): 52.5-105. 映射到 displayX
        value: [68 - s.y, displayX, s.xg, s.outcome, s.player || 'Standard Player'],
        symbol: s.outcome === 'Goal' 
          ? 'path://M12 .587l3.668 7.568 8.332 1.151-6.064 5.828 1.48 8.279-7.416-3.967-7.417 3.967 1.481-8.279-6.064-5.828 8.332-1.151z' 
          : 'circle',
        symbolSize: s.outcome === 'Goal' ? 22 : 10,
        itemStyle: {
          color: s.outcome === 'Goal' ? '#4ade80' : 'transparent',
          borderColor: s.outcome === 'Goal' ? '#fff' : '#ff3c6a',
          borderWidth: 2,
          shadowBlur: s.outcome === 'Goal' ? 15 : 0,
          opacity: 1
        },
        z: s.outcome === 'Goal' ? 1000 : 100,
        emphasis: {
          itemStyle: {
            color: s.outcome === 'Goal' ? '#22c55e' : '#fff',
            opacity: 1,
            borderWidth: 3
          }
        }
      };
    });

    const option: echarts.EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(15, 23, 42, 0.95)',
        borderColor: 'rgba(255, 255, 255, 0.1)',
        borderWidth: 1,
        padding: 12,
        textStyle: { color: '#f8fafc', fontSize: 12, fontFamily: 'monospace' },
        formatter: (params: any) => {
          if (!params.data || !params.data.value || !Array.isArray(params.data.value)) return '';
          const [y, x, xg, outcome, player] = params.data.value;
          const statusColor = outcome === 'Goal' ? '#4ade80' : '#ff3c6a';
          return `
            <div style="min-width: 150px;">
              <div style="font-weight: 800; color: ${statusColor}; margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 6px; letter-spacing: 0.05em;">${player.toUpperCase()}</div>
              <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                <span style="color: #64748b; font-size: 9px;">期望进球 (xG):</span>
                <span style="font-weight: bold; color: #fff">${xg.toFixed(3)}</span>
              </div>
              <div style="display: flex; justify-content: space-between;">
                <span style="color: #64748b; font-size: 9px;">结果:</span>
                <span style="font-weight: bold; color: #fff; text-transform: uppercase;">${outcome === 'Goal' ? '进球' : '未进门'}</span>
              </div>
            </div>
          `;
        }
      },
      xAxis: {
        type: 'value',
        min: 0,
        max: 68,
        splitLine: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false }
      },
      yAxis: {
        type: 'value',
        min: 52.5, 
        max: 105,
        splitLine: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false }
      },
      grid: {
        top: 40,
        bottom: 40,
        left: 40,
        right: 40,
        containLabel: false
      },
      series: [
        {
          type: 'scatter',
          coordinateSystem: 'cartesian2d',
          data: shotData,
          z: 10
        },
        {
          type: 'custom',
          coordinateSystem: 'cartesian2d',
          renderItem: (params: any, api: any) => {
            const getCoord = (pt: [number, number]) => api.coord(pt);
            
            const optaLineStyle = { 
              stroke: '#00f2ff', 
              lineWidth: 1.5, 
              opacity: 0.7, 
              shadowBlur: 8,
              shadowColor: 'rgba(0, 242, 255, 0.4)'
            };
            
            const lines: any[] = [];
            
            // 1. Boundary (68x52.5 attacking half)
            const bl = getCoord([0, 52.5]), tl = getCoord([0, 105]), tr = getCoord([68, 105]), br = getCoord([68, 52.5]);
            lines.push({ type: 'polyline', shape: { points: [bl, tl, tr, br] }, style: optaLineStyle });

            // Halfway Line
            lines.push({ type: 'line', shape: { x1: bl[0], y1: bl[1], x2: br[0], y2: br[1] }, style: { ...optaLineStyle, opacity: 0.8 } });
 
            const centerSpot = getCoord([34, 52.5]);
            const rPx = Math.abs(getCoord([34 + 9.15, 52.5])[0] - centerSpot[0]);
            lines.push({
              type: 'arc',
              shape: { cx: centerSpot[0], cy: centerSpot[1], r: rPx, startAngle: Math.PI, endAngle: 0, clockwise: true },
              style: { ...optaLineStyle, fill: 'transparent', opacity: 0.3 }
            });

            // 2. Penalty Area
            const pAreaPoints = [
              getCoord([13.84, 105]), getCoord([13.84, 88.5]), getCoord([54.16, 88.5]), getCoord([54.16, 105])
            ];
            lines.push({ type: 'polyline', shape: { points: pAreaPoints }, style: optaLineStyle });
  
            // 3. Goal Area
            const sAreaPoints = [
              getCoord([24.84, 105]), getCoord([24.84, 99.5]), getCoord([43.16, 99.5]), getCoord([43.16, 105])
            ];
            lines.push({ type: 'polyline', shape: { points: sAreaPoints }, style: optaLineStyle });
  
            // 4. Penalty Arc
            const arcCenter = getCoord([34, 94]);
            lines.push({
              type: 'arc',
              shape: { cx: arcCenter[0], cy: arcCenter[1], r: Math.abs(getCoord([43.15, 94])[0] - arcCenter[0]), startAngle: 0.8, endAngle: 2.34 },
              style: optaLineStyle
            });
 
            // 5. Goal Frame
            const g1 = getCoord([30.34, 105]), g2 = getCoord([37.66, 105]), g3 = getCoord([30.34, 107]), g4 = getCoord([37.66, 107]);
            lines.push({
              type: 'rect',
              shape: { x: g1[0], y: g3[1], width: g2[0] - g1[0], height: g1[1] - g3[1] },
              style: { fill: 'rgba(79, 255, 255, 0.2)', stroke: '#4fffff', lineWidth: 2, shadowBlur: 15, shadowColor: '#4fffff' }
            });
  
            // 6. Penalty Spot
            const spot = getCoord([34, 94]);
            lines.push({ 
              type: 'circle', 
              shape: { cx: spot[0], cy: spot[1], r: 2.5 }, 
              style: { fill: '#4fffff', opacity: 0.8 } 
            });
  
            return { type: 'group', children: lines };
          },
          data: [[34, 75]], // Important range
          z: 1
        }
      ]
    };

    if (rawShots.length === 0) {
      chart.dispose();
      return;
    }

    chart.setOption(option, true);

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
  }, [isMounted, penetrationData, selectedTeam, selectedScope]);

  if (!isMounted) return <div className="w-full h-[400px] md:h-[500px] bg-white/5 animate-pulse rounded-[2.5rem]" />;

  return (
    <div className="glass-panel p-8 lg:p-12 relative overflow-hidden transition-all hover:bg-white/[0.02]">
      {/* 装饰性氛围光 */}
      <div className="absolute top-0 right-0 w-[600px] h-[600px] bg-primary-container/5 blur-[120px] -mr-64 -mt-64 pointer-events-none" />
      
      <div className="flex flex-col xl:flex-row justify-between items-start xl:items-center gap-8 mb-12 relative z-10">
        <div className="flex flex-col border-l-4 border-primary-container/60 pl-6">
          <h3 className="text-3xl font-headline font-black italic tracking-tighter uppercase leading-none text-foreground">
            进攻穿透分析<span className="text-primary-container not-italic opacity-80"> (PENETRATION)</span>
          </h3>
          <p className="text-xs text-zinc-500 font-headline font-bold mt-3 tracking-[0.4em] uppercase opacity-90">
            攻方三区综合表现分析 | 已整合 {
              (selectedTeam === 'home' 
                ? (selectedScope === 'all' ? (penetrationData?.homeTeam?.last5All?.length ?? 0) : (penetrationData?.homeTeam?.last5HomeAway?.length ?? 0))
                : (selectedScope === 'all' ? (penetrationData?.awayTeam?.last5All?.length ?? 0) : (penetrationData?.awayTeam?.last5HomeAway?.length ?? 0))
              )
            } 次射门样本
          </p>
        </div>

        <div className="flex flex-wrap gap-4">
          <div className="inline-flex p-1 bg-surface-dim/40 rounded-2xl border border-white/5 shadow-ghost-border">
            {[
              { id: 'home', name: homeTeamName },
              { id: 'away', name: awayTeamName }
            ].map((team) => (
              <button
                key={team.id}
                onClick={() => setSelectedTeam(team.id as any)}
                className={`px-6 py-2.5 rounded-xl text-xs font-headline font-black uppercase tracking-widest transition-all duration-300 ${
                  selectedTeam === team.id 
                    ? 'bg-primary-container text-black shadow-[0_0_20px_rgba(0,240,255,0.3)] scale-105' 
                    : 'text-zinc-500 hover:text-foreground'
                }`}
              >
                {team.name}
              </button>
            ))}
          </div>

          <div className="inline-flex p-1 bg-surface-dim/40 rounded-2xl border border-white/5 shadow-ghost-border">
            <button
              onClick={() => setSelectedScope('all')}
              className={`px-6 py-2.5 rounded-xl text-xs font-headline font-black uppercase tracking-widest transition-all duration-300 ${
                selectedScope === 'all' ? 'text-primary-container bg-white/5' : 'text-zinc-500 hover:text-foreground'
              }`}
            >
              全部赛事 (近5场)
            </button>
            <button
              onClick={() => setSelectedScope('homeAway')}
              className={`px-6 py-2.5 rounded-xl text-xs font-headline font-black uppercase tracking-widest transition-all duration-300 ${
                selectedScope === 'homeAway' ? 'text-primary-container bg-white/5' : 'text-zinc-500 hover:text-foreground'
              }`}
            >
              相同主客场
            </button>
          </div>
        </div>
      </div>

      <div className="flex justify-center items-center bg-surface-dim/20 rounded-[3rem] border border-white/[0.04] p-6 shadow-inner w-full aspect-[68/52.5] max-h-[600px] mx-auto">
        <div ref={chartRef} className="w-full h-full relative z-10" />
      </div>

      <div className="mt-10 flex flex-wrap justify-center gap-x-12 gap-y-6">
        <div className="flex items-center gap-4">
          <div className="w-3 h-3 rounded-full bg-secondary-container/20 border border-secondary-container/40 shadow-[0_0_10px_var(--color-secondary-container)]" />
          <span className="text-xs font-headline font-bold text-zinc-500 uppercase tracking-widest">普通射门</span>
        </div>
        <div className="flex items-center gap-4">
          <svg className="w-4 h-4 text-primary-container drop-shadow-[0_0_8px_var(--color-primary-container)]" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 .587l3.668 7.568 8.332 1.151-6.064 5.828 1.48 8.279-7.416-3.967-7.417 3.967 1.481-8.279-6.064-5.828 8.332-1.151z"/>
          </svg>
          <span className="text-xs font-headline font-bold text-zinc-500 uppercase tracking-widest">进球 / 高价值机会</span>
        </div>
        <div className="absolute bottom-6 right-10 text-xs font-headline font-bold text-zinc-500/30 tracking-[0.5em] uppercase animate-pulse">
          空间感知系统 SPATIAL INTEL v6.2 (已校准)
        </div>
      </div>
    </div>
  );
};

export default HalfPitchShotMap;
