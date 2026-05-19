'use client';

import React, { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts';
import { RadarDimensions } from '@/types/report';

interface Props {
  radarData: {
    home: RadarDimensions;
    away: RadarDimensions;
  };
  homeTeamName: string;
  awayTeamName: string;
}

const TacticalRadarChart: React.FC<Props> = ({ radarData, homeTeamName, awayTeamName }) => {
  const chartRef = useRef<HTMLDivElement>(null);
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!isMounted || !chartRef.current || !radarData) return;

    const chart = echarts.init(chartRef.current, null, { renderer: 'svg' });

    const option: echarts.EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(16, 20, 26, 0.95)',
        borderColor: 'rgba(255, 255, 255, 0.1)',
        padding: 12,
        textStyle: { color: '#ddd', fontSize: 12, fontFamily: 'var(--font-body)' }
      },
      legend: {
        bottom: 5,
        icon: 'circle',
        itemWidth: 8,
        itemHeight: 8,
        textStyle: { color: 'rgba(255,255,255,0.5)', fontSize: 12, fontWeight: 700, padding: [2, 0, 0, 0] },
        data: [homeTeamName, awayTeamName]
      },
      radar: {
        shape: 'polygon',
        indicator: [
          { name: '进攻性', max: 100 },
          { name: '防御力', max: 100 },
          { name: '控制力', max: 100 },
          { name: '压迫指数', max: 100 },
          { name: '穿透性', max: 100 },
          { name: '状态表现', max: 100 }
        ],
        center: ['50%', '50%'],
        radius: '65%',
        axisName: {
          color: 'rgba(255,255,255,0.7)',
          fontSize: 12,
          fontWeight: 900,
          fontFamily: 'var(--font-headline)',
          fontStyle: 'italic'
        },
        splitArea: {
          areaStyle: {
            color: ['rgba(0,240,255,0.03)', 'rgba(0,240,255,0.06)'],
          }
        },
        axisLine: {
          lineStyle: {
            color: 'rgba(0,240,255,0.15)'
          }
        },
        splitLine: {
          lineStyle: {
            color: 'rgba(0,240,255,0.1)'
          }
        }
      },
      series: [
        {
          type: 'radar',
          symbol: 'none',
          data: [
            {
              value: [
                radarData.home.attack,
                radarData.home.defense,
                radarData.home.possession,
                radarData.home.pressing,
                radarData.home.penetration,
                radarData.home.form
              ],
              name: homeTeamName,
              lineStyle: { color: '#00F0FF', width: 2 },
              areaStyle: { color: 'rgba(0,240,255,0.2)' },
              itemStyle: { color: '#00F0FF' }
            },
            {
              value: [
                radarData.away.attack,
                radarData.away.defense,
                radarData.away.possession,
                radarData.away.pressing,
                radarData.away.penetration,
                radarData.away.form
              ],
              name: awayTeamName,
              lineStyle: { color: '#FF00E5', width: 2 },
              areaStyle: { color: 'rgba(255,0,229,0.15)' },
              itemStyle: { color: '#FF00E5' }
            }
          ]
        }
      ]
    };

    chart.setOption(option);

    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);

    const timer = setTimeout(() => chart.resize(), 100);

    return () => {
      window.removeEventListener('resize', handleResize);
      clearTimeout(timer);
      chart.dispose();
    };
  }, [isMounted, radarData, homeTeamName, awayTeamName]);

  if (!isMounted) return <div className="w-full h-[320px] md:h-[400px] bg-white/5 animate-pulse rounded-[2rem]" />;

  return (
    <div className="glass-panel p-8 relative overflow-hidden group transition-all hover:bg-white/[0.04]">
      {/* 装饰性网格背景 - 增强 HUD 感 */}
      <div 
        className="absolute inset-0 opacity-[0.03] pointer-events-none" 
        style={{ 
          backgroundImage: 'radial-gradient(circle, #fff 1px, transparent 1px)', 
          backgroundSize: '24px 24px' 
        }} 
      />

      <div className="z-10 relative">
        <div className="mb-6">
          <h3 className="text-sm font-headline font-black italic tracking-[0.25em] text-foreground uppercase flex items-center gap-3">
            <span className="w-1 h-5 bg-gradient-to-b from-primary-container to-secondary-container rounded-full" />
            战术维度分析雷达 (Tactical Analysis)
          </h3>
          <p className="text-xs font-bold text-zinc-500 uppercase tracking-widest mt-1.5 opacity-60">
            核心表现指标 :: 六维量化评价体系
          </p>
        </div>

        <div ref={chartRef} className="w-full h-[320px] md:h-[400px]" />
      </div>
    </div>
  );
};

export default TacticalRadarChart;
