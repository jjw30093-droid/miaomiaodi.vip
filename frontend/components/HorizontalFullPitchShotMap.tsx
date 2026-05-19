'use client';

import React, { useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import { Shot } from '@/types/report';

interface HorizontalFullPitchShotMapProps {
  homeTeamName: string;
  awayTeamName: string;
  homeTeamShots: Shot[];
  awayTeamShots: Shot[];
}

/**
 * Premium Horizontal Full-Pitch Shot Map (Opta Calibrated)
 * 
 * Grid System (Full Pitch):
 * - X Axis: 0 to 100 (0: Left Goal Line, 50: Halfway, 100: Right Goal Line)
 * - Y Axis: 0 to 100 (0: Bottom Side, 50: Center, 100: Top Side)
 * 
 * Opta Data (Single Half attacking right):
 * - Depth (X): 0-100 (100 is opponent goal line)
 * - Width (Y): 0-100 (50 is center)
 */
const HorizontalFullPitchShotMap: React.FC<HorizontalFullPitchShotMapProps> = ({
  homeTeamName,
  awayTeamName,
  homeTeamShots,
  awayTeamShots
}) => {
  const options = useMemo(() => {
    // 1. Home Team attacks RIGHT (towards X=100)
    // 强制硬编码：[shot.x, shot.y]
    const transformedHome = homeTeamShots.map(s => ({
      ...s,
      X_map: s.x, 
      Y_map: s.y
    }));

    // 2. Away Team attacks LEFT (towards X=0)
    // 强制硬编码：[100 - shot.x, 100 - shot.y]
    const transformedAway = awayTeamShots.map(s => ({
      ...s,
      X_map: 100 - s.x,
      Y_map: 100 - s.y
    }));

    const allData = [
      ...transformedHome.map(s => {
        return {
          // 主队 (Home): x 保持, Y 根据防守原点向上 [s.x, 68 - s.y]
          value: [s.x, 68 - s.y, s.xg, s.outcome, 'home', s.player],
          itemStyle: {
            color: s.outcome === 'Goal' ? '#00ff88' : '#7c3aed',
            shadowBlur: 10,
            shadowColor: s.outcome === 'Goal' ? '#00ff88' : '#7c3aed'
          },
          symbol: s.outcome === 'Goal' ? 'path://M12 .587l3.668 7.568 8.332 1.151-6.064 5.828 1.48 8.279-7.416-3.967-7.417 3.967 1.481-8.279-6.064-5.828 8.332-1.151z' : 'circle',
          symbolSize: s.outcome === 'Goal' ? 18 : 8
        };
      }),
      ...transformedAway.map(s => {
        return {
          // 客队 (Away): 全面镜像 [105 - s.x, s.y]
          value: [105 - s.x, s.y, s.xg, s.outcome, 'away', s.player],
          itemStyle: {
            color: s.outcome === 'Goal' ? '#00ff88' : '#ff3366',
            shadowBlur: 10,
            shadowColor: s.outcome === 'Goal' ? '#00ff88' : '#ff3366'
          },
          symbol: s.outcome === 'Goal' ? 'path://M12 .587l3.668 7.568 8.332 1.151-6.064 5.828 1.48 8.279-7.416-3.967-7.417 3.967 1.481-8.279-6.064-5.828 8.332-1.151z' : 'circle',
          symbolSize: s.outcome === 'Goal' ? 18 : 8
        };
      })
    ];

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(10, 20, 35, 0.95)',
        borderColor: '#00f3ff',
        textStyle: { color: '#fff' },
        formatter: (params: any) => {
          const [x, y, xg, outcome, side, player] = params.value || [];
          if (xg === undefined) return '';
          const team = side === 'home' ? homeTeamName : awayTeamName;
          return `
            <div style="font-weight: bold; color: #00f3ff; margin-bottom: 4px;">${team}</div>
            <div style="font-size: 11px; color: #fff; margin-bottom: 2px;">球员 Player: ${player || '未知'}</div>
            <div style="font-size: 11px;">结果 Outcome: ${outcome === 'Goal' ? '进球' : '未进门'}</div>
            <div style="font-size: 11px;">期望进球 xG: ${xg.toFixed(3)}</div>
          `;
        }
      },
      grid: {
        top: '6%',
        bottom: '6%',
        left: '4%',
        right: '4%',
        containLabel: false
      },
      xAxis: {
        type: 'value',
        min: 0,
        max: 105,
        show: false
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 68,
        show: false
      },
      series: [
        {
          type: 'scatter',
          data: allData,
          coordinateSystem: 'cartesian2d',
          zlevel: 10,
          animation: false
        },
        {
          type: 'custom',
          coordinateSystem: 'cartesian2d',
          renderItem: (params: any, api: any) => {
            const getCoord = (pt: [number, number]) => api.coord(pt);
            
            const optaLineStyle = { 
              stroke: '#00f3ff', 
              lineWidth: 1.5, 
              opacity: 0.3,
              shadowBlur: 5,
              shadowColor: '#00f3ff'
            };
            
            const elements: any[] = [];
            
            // 1. Pitch Boundary (X 0-105, Y 0-68)
            const pts = [
                getCoord([0, 0]), getCoord([105, 0]), 
                getCoord([105, 68]), getCoord([0, 68]), 
                getCoord([0, 0])
            ];
            elements.push({
              type: 'polyline',
              shape: { points: pts },
              style: { ...optaLineStyle, fill: 'rgba(0, 243, 255, 0.02)' }
            });

            // 2. Halfway Line
            const m1 = getCoord([52.5, 0]), m2 = getCoord([52.5, 68]);
            elements.push({ type: 'line', shape: { x1: m1[0], y1: m1[1], x2: m2[0], y2: m2[1] }, style: optaLineStyle });

            // 3. Center Circle (radius: 9.15m)
            const center = getCoord([52.5, 34]);
            const rPx = Math.abs(getCoord([61.65, 34])[0] - center[0]);
            elements.push({ type: 'circle', shape: { cx: center[0], cy: center[1], r: rPx }, style: { ...optaLineStyle, fill: 'transparent' } });

            // 4. Penalty Areas (16.5m depth, 40.32m width -> Y: 13.84 to 54.16)
            // Right Box (X 88.5-105)
            const rgb_pts = [getCoord([88.5, 13.84]), getCoord([105, 13.84]), getCoord([105, 54.16]), getCoord([88.5, 54.16]), getCoord([88.5, 13.84])];
            elements.push({ type: 'polyline', shape: { points: rgb_pts }, style: optaLineStyle });
            
            // Left Box (X 0-16.5)
            const lgb_pts = [getCoord([16.5, 13.84]), getCoord([0, 13.84]), getCoord([0, 54.16]), getCoord([16.5, 54.16]), getCoord([16.5, 13.84])];
            elements.push({ type: 'polyline', shape: { points: lgb_pts }, style: optaLineStyle });

            // 5. Goal Areas (5.5m depth, 18.32m width -> Y: 24.84 to 43.16)
            // Right Small Box (X 99.5-105)
            const rsb_pts = [getCoord([99.5, 24.84]), getCoord([105, 24.84]), getCoord([105, 43.16]), getCoord([99.5, 43.16]), getCoord([99.5, 24.84])];
            elements.push({ type: 'polyline', shape: { points: rsb_pts }, style: optaLineStyle });
            
            // Left Small Box (X 0-5.5)
            const lsb_pts = [getCoord([5.5, 24.84]), getCoord([0, 24.84]), getCoord([0, 43.16]), getCoord([5.5, 43.16]), getCoord([5.5, 24.84])];
            elements.push({ type: 'polyline', shape: { points: lsb_pts }, style: optaLineStyle });

            // 6. Goals (7.32m width -> Y: 30.34 to 37.66)
            const rgl = getCoord([105, 30.34]), rgr = getCoord([105, 37.66]), rgt = getCoord([107, 30.34]), rgb = getCoord([107, 37.66]);
            elements.push({
              type: 'rect',
              shape: { x: rgl[0], y: rgt[1], width: rgt[0]-rgl[0], height: rgb[1]-rgt[1] },
              style: { fill: 'rgba(0, 243, 255, 0.1)', stroke: '#00f3ff', opacity: 0.6 }
            });
            
            const lgl = getCoord([0, 30.34]), lgr = getCoord([0, 37.66]), lgt = getCoord([-2, 30.34]), lgb = getCoord([-2, 37.66]);
            elements.push({
              type: 'rect',
              shape: { x: lgt[0], y: lgt[1], width: lgl[0]-lgt[0], height: lgb[1]-lgt[1] },
              style: { fill: 'rgba(0, 243, 255, 0.1)', stroke: '#00f3ff', opacity: 0.6 }
            });

            // 7. Penalty Spots (X 11 and 94, Y 34)
            const rspot = getCoord([94, 34]), lspot = getCoord([11, 34]);
            elements.push({ type: 'circle', shape: { cx: rspot[0], cy: rspot[1], r: 3 }, style: { fill: '#00f3ff', opacity: 0.5 } });
            elements.push({ type: 'circle', shape: { cx: lspot[0], cy: lspot[1], r: 3 }, style: { fill: '#00f3ff', opacity: 0.5 } });


            return { type: 'group', children: elements };
          },
          data: [[0, 0]],
          z: 1
        }
      ]
    };
  }, [homeTeamShots, awayTeamShots, homeTeamName, awayTeamName]);

  return (
    <div className="glass-panel overflow-hidden transition-all hover:bg-white/[0.02] relative aspect-[16/10] w-full">
      {/* 装饰性氛围光 */}
      <div className="absolute top-0 right-0 w-[400px] h-[400px] bg-primary-container/5 blur-[100px] -mr-32 -mt-32 pointer-events-none" />

      <div className="absolute top-6 left-8 flex items-center gap-4 z-20">
        <div className="w-1.5 h-8 bg-gradient-to-b from-primary-container to-secondary-container rounded-full shadow-[0_0_15px_var(--color-primary-container)]"></div>
        <div>
          <h3 className="text-foreground font-headline font-black text-xl tracking-tighter uppercase italic">
            全场射门<span className="text-primary-container">分布分析</span> (SHOTS)
          </h3>
          <p className="text-xs text-zinc-500 font-headline font-bold tracking-[0.3em] uppercase opacity-60">赛后空间数据度量 :: POST-MATCH SPATIAL</p>
        </div>
      </div>
      
      <div className="absolute top-8 right-8 flex gap-8 text-xs items-center z-20 font-headline font-bold tracking-widest">
        <div className="flex items-center gap-2 text-zinc-500">
          <span className="w-2 h-2 rounded-full bg-primary-container shadow-[0_0_8px_var(--color-primary-container)]"></span>
          <span>{homeTeamName.toUpperCase()}</span>
        </div>
        <div className="flex items-center gap-2 text-zinc-500">
          <span className="w-2 h-2 rounded-full bg-secondary-container shadow-[0_0_8px_var(--color-secondary-container)]"></span>
          <span>{awayTeamName.toUpperCase()}</span>
        </div>
        <div className="flex items-center gap-2 text-primary-container">
          <span className="w-4 h-4 text-center leading-none text-lg">★</span>
          <span>进球 GOAL</span>
        </div>
      </div>

      <div className="absolute inset-0 z-10 p-8 pt-20 pb-12">
        <ReactECharts 
          option={options} 
          style={{ height: '100%', width: '100%' }}
          opts={{ renderer: 'svg' }}
        />
      </div>
      
      {/* Watermark/Footer */}
      <div className="absolute bottom-6 left-10 right-10 flex justify-between items-end z-20 pointer-events-none opacity-40">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-primary-container font-headline font-bold tracking-widest uppercase">已集成 Opta 映射系统 (Integrated)</span>
          <span className="text-xs text-zinc-500 font-headline font-bold tracking-[0.4em]">喵弟量化实验室 :: 空间定位系统 v6.2</span>
        </div>
        <div className="text-xs text-zinc-500 font-headline font-bold tracking-widest uppercase">
          [ 物理规格 105 x 68 ] :: 已校准
        </div>
      </div>
    </div>
  );
};

export default HorizontalFullPitchShotMap;
