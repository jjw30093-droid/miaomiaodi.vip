'use client';
import { ModelHealthData } from './types';
import EChartWrapper from '@/components/EChartWrapper';

interface Props {
  rolling: ModelHealthData['rolling'];
}

export default function RollingAccuracyChart({ rolling }: Props) {
  const wdl = rolling.wdl_accuracy != null ? (rolling.wdl_accuracy * 100).toFixed(1) : null;
  const ou  = rolling.ou_accuracy  != null ? (rolling.ou_accuracy  * 100).toFixed(1) : null;
  // Only show AH when sample >= 10 (API already nulls it below threshold)
  const ah  = rolling.ah_accuracy  != null ? (rolling.ah_accuracy  * 100).toFixed(1) : null;

  const categories = ['WDL 胜平负', 'OU 大小球', 'AH 亚盘'].filter((_, i) => [wdl, ou, ah][i] !== null);
  const values     = [wdl, ou, ah].filter((v) => v !== null) as string[];
  const colors     = ['#00F0FF', '#FF00E5', '#00ffb7'];

  const option = {
    backgroundColor: 'transparent',
    grid: { top: 20, right: 20, bottom: 36, left: 60 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(5,8,20,0.95)',
      borderColor: 'rgba(0,240,255,0.2)',
      textStyle: { color: '#fff', fontFamily: 'monospace', fontSize: 11 },
      formatter: (params: any[]) =>
        params.map(p => `${p.name}: <b>${p.value}%</b>`).join('<br/>'),
    },
    xAxis: {
      type: 'category',
      data: categories,
      axisLabel: { color: 'rgba(255,255,255,0.4)', fontSize: 10, fontFamily: 'Space Grotesk' },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      min: 40,
      max: 70,
      axisLabel: { color: 'rgba(255,255,255,0.3)', fontSize: 9, fontFamily: 'monospace',
        formatter: (v: number) => `${v}%` },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.03)', type: 'dashed' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        type: 'bar',
        data: values.map((v, i) => ({
          value: parseFloat(v),
          itemStyle: {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: colors[i] },
                { offset: 1, color: colors[i] + '33' },
              ],
            },
            borderRadius: [6, 6, 0, 0],
            shadowBlur: 16,
            shadowColor: colors[i] + '55',
          },
        })),
        barWidth: '40%',
        label: {
          show: true,
          position: 'top',
          color: '#fff',
          fontFamily: 'monospace',
          fontSize: 11,
          fontWeight: 900,
          formatter: '{c}%',
        },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [{ yAxis: 50, label: { show: true, formatter: '随机线 50%', color: 'rgba(255,255,255,0.2)', fontSize: 9 },
            lineStyle: { color: 'rgba(255,255,255,0.1)', type: 'dashed', width: 1 } }],
        },
      },
    ],
  };

  return (
    <div className="glass-panel rounded-2xl border border-white/5 p-5">
      <div className="flex items-center justify-between mb-3">
        <p className="text-[10px] font-black tracking-[0.3em] uppercase text-white/30">滚动准确率</p>
        <span className="text-[9px] text-white/20 font-mono">
          近 {rolling.window}d · {rolling.total_matches} 场
          {rolling.drift_alert && <span className="text-amber-400 ml-1">⚠ 准确率低于随机线</span>}
          {rolling.ah_sample_n < 10 && <span className="ml-1 opacity-50">· AH 样本不足暂隐</span>}
        </span>
      </div>
      <div className="h-44">
        <EChartWrapper option={option} style={{ minHeight: '170px' }} />
      </div>
    </div>
  );
}
