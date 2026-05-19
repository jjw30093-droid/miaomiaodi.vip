'use client';
import React from 'react';
import { ModelHealthData } from './types';
import EChartWrapper from '@/components/EChartWrapper';

interface Props {
  data: ModelHealthData['calibration'];
}

export default function CalibrationPlot({ data }: Props) {
  if (!data || data.length === 0) {
    return (
      <div className="glass-panel rounded-2xl border border-white/5 p-5">
        <p className="text-[10px] font-black tracking-[0.3em] uppercase text-white/30 mb-3">校准可信度</p>
        <div className="h-40 flex items-center justify-center text-white/20 text-xs">暂无校准数据</div>
      </div>
    );
  }

  const option = {
    backgroundColor: 'transparent',
    grid: { top: 30, right: 20, bottom: 40, left: 50 },
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(5,8,20,0.95)',
      borderColor: 'rgba(0,240,255,0.2)',
      textStyle: { color: '#fff', fontFamily: 'monospace', fontSize: 11 },
      formatter: (p: any) => {
        const d = p.data;
        return `预测: ${(d[0] * 100).toFixed(0)}%<br/>实际: ${(d[1] * 100).toFixed(0)}%<br/>样本: ${d[2]}`;
      },
    },
    xAxis: {
      type: 'value',
      min: 0,
      max: 1,
      name: '预测概率',
      nameTextStyle: { color: 'rgba(255,255,255,0.3)', fontSize: 10, fontFamily: 'monospace' },
      axisLabel: { color: 'rgba(255,255,255,0.3)', fontSize: 9, fontFamily: 'monospace',
        formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)', type: 'dashed' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 1,
      name: '实际命中',
      nameTextStyle: { color: 'rgba(255,255,255,0.3)', fontSize: 10, fontFamily: 'monospace' },
      axisLabel: { color: 'rgba(255,255,255,0.3)', fontSize: 9, fontFamily: 'monospace',
        formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)', type: 'dashed' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      // Perfect calibration diagonal
      {
        type: 'line',
        data: [[0, 0], [1, 1]],
        lineStyle: { color: 'rgba(255,255,255,0.1)', type: 'dashed', width: 1 },
        symbol: 'none',
        silent: true,
        z: 1,
      },
      // Actual calibration scatter
      {
        type: 'scatter',
        data: data.map(d => [d.predicted, d.actual, d.n]),
        symbolSize: (val: number[]) => Math.max(8, Math.min(24, val[2] * 1.5)),
        itemStyle: {
          color: '#00F0FF',
          opacity: 0.85,
          shadowBlur: 12,
          shadowColor: 'rgba(0,240,255,0.4)',
        },
        z: 2,
      },
    ],
  };

  return (
    <div className="glass-panel rounded-2xl border border-white/5 p-5">
      <div className="flex items-center justify-between mb-3">
        <p className="text-[10px] font-black tracking-[0.3em] uppercase text-white/30">校准可信度</p>
        <span className="text-[9px] text-white/20 font-mono">散点越近对角线 = 越准确</span>
      </div>
      <div className="h-52">
        <EChartWrapper option={option} style={{ minHeight: '200px' }} />
      </div>
    </div>
  );
}
