'use client';

import React, { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import { ShotMapData, Shot } from '@/types/report';

interface Props {
  shotMapData: ShotMapData;
}

const ShotMapChart: React.FC<Props> = ({ shotMapData }) => {
  const chartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!chartRef.current || !shotMapData) return;

    // 初始化 ECharts
    const chart = echarts.init(chartRef.current, null, { renderer: 'canvas' });

    // 处理坐标：如果需要的话（例如，镜像主客队坐标以在球场两侧分别展示）
    // 此处假设后端已经按照球场分布处理好 x/y (0-100)
    
    const formatShotData = (shots: Shot[]) => {
      return shots.map(s => ({
        name: s.player,
        value: [s.x, s.y, s.xg, s.outcome],
        itemStyle: s.outcome === 'Goal' ? {
          color: '#d8ff00',
          shadowBlur: 15,
          shadowColor: '#d8ff00'
        } : {}
      }));
    };

    const option: echarts.EChartsOption = {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(3, 4, 12, 0.9)',
        borderColor: 'rgba(255, 255, 255, 0.1)',
        textStyle: { color: '#fafafc' },
        formatter: (params: any) => {
          const [x, y, xg, outcome] = params.value;
          const player = params.name;
          return `
            <div style="font-family: inherit; padding: 4px;">
              <div style="font-weight: bold; margin-bottom: 4px; color: #fff;">${player}</div>
              <div style="display: flex; gap: 8px; font-size: 12px; color: #9ca3af;">
                <span>xG: <span style="color: #d8ff00;">${xg}</span></span>
                <span>Result: <span style="color: #fff;">${outcome}</span></span>
              </div>
            </div>
          `;
        }
      },
      grid: {
        left: '5%',
        right: '5%',
        top: '10%',
        bottom: '10%',
        containLabel: false
      },
      xAxis: {
        type: 'value',
        min: 0,
        max: 100,
        splitLine: { lineStyle: { color: 'rgba(6, 182, 212, 0.05)' } },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false }
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        splitLine: { lineStyle: { color: 'rgba(6, 182, 212, 0.05)' } },
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false }
      },
      series: [
        {
          name: shotMapData.homeTeamName,
          type: 'scatter',
          data: formatShotData(shotMapData.homeTeamShots),
          symbol: (value: any) => value[3] === 'Goal' ? 'star' : 'circle',
          symbolSize: (value: any) => value[2] * 40 + 8,
          itemStyle: {
            color: '#06b6d4',
            opacity: 0.8
          },
          emphasis: {
            itemStyle: { opacity: 1, shadowBlur: 10, shadowColor: '#06b6d4' }
          }
        },
        {
          name: shotMapData.awayTeamName,
          type: 'scatter',
          data: formatShotData(shotMapData.awayTeamShots),
          symbol: (value: any) => value[3] === 'Goal' ? 'star' : 'circle',
          symbolSize: (value: any) => value[2] * 40 + 8,
          itemStyle: {
            color: '#a78bfa',
            opacity: 0.8
          },
          emphasis: {
            itemStyle: { opacity: 1, shadowBlur: 10, shadowColor: '#a78bfa' }
          }
        }
      ],
      // 模拟足球场线框
      graphic: [
        {
          type: 'group',
          left: 'center',
          top: 'center',
          children: [
            // 中心圆
            {
              type: 'circle',
              shape: { r: 50 },
              style: { fill: 'none', stroke: 'rgba(255, 255, 255, 0.05)', lineWidth: 1 },
              left: 'center',
              top: 'center'
            },
            // 中心线
            {
              type: 'line',
              shape: { x1: 0, y1: -250, x2: 0, y2: 250 },
              style: { stroke: 'rgba(255, 255, 255, 0.05)', lineWidth: 1 },
              left: 'center'
            }
          ]
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
  }, [shotMapData]);

  if (!shotMapData) return null;

  return (
    <div className="relative glass bg-white/5 backdrop-blur-md border border-white/10 rounded-[2.5rem] p-6 shadow-[0_0_20px_rgba(0,100,255,0.05)] overflow-hidden">
      {/* 标题 */}
      <div className="flex justify-between items-center mb-6 px-4">
        <div className="flex items-center gap-3">
          <div className="w-1.5 h-6 bg-cyan-500 rounded-full" />
          <span className="text-xs font-mono font-bold tracking-[0.2em] text-cyan-500 uppercase">
            Spatial Shot Distribution
          </span>
        </div>
        <div className="flex gap-4 text-xs font-mono font-bold text-gray-500 uppercase tracking-widest">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-cyan-500" />
            {shotMapData.homeTeamName}
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-purple-400" />
            {shotMapData.awayTeamName}
          </div>
        </div>
      </div>
      
      {/* 图表容器 */}
      <div ref={chartRef} className="w-full h-[400px]" />
      
      {/* 水印 */}
      <div className="absolute bottom-6 right-8 opacity-20 flex items-center gap-2">
        <span className="text-xs font-mono tracking-[0.3em] uppercase text-white pointer-events-none">
          Quantum Engine Data Stream
        </span>
      </div>
    </div>
  );
};

export default ShotMapChart;
