'use client';
import React from 'react';
import EChartWrapper from '@/components/EChartWrapper';
import { useTheme } from '@/components/ThemeProvider';
import type { DirectionTrend } from '@/lib/modelHealth/types';

interface Props {
  data: DirectionTrend;
  currentHidden: { wdl: boolean; ou: boolean; ah: boolean };
}

function getCSSVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

type SeriesKey = 'wdl' | 'ou' | 'ah';
const LABEL_MAP: Record<SeriesKey, { short: string; full: string }> = {
  wdl: { short: 'WDL', full: '胜平负' },
  ou:  { short: 'O/U', full: '大小球' },
  ah:  { short: 'AH',  full: '亚盘' },
};
const KEYS: SeriesKey[] = ['wdl', 'ou', 'ah'];

function buildOption(data: DirectionTrend, hidden: Props['currentHidden']) {
  // Mobile-optimized 3-series rolling accuracy:
  //   - No native ECharts legend (replaced with HTML chips outside)
  //   - Prominent 50% baseline as ground truth; line thicker, label bold
  //   - Active series: width 2.6 solid; hidden series: width 1.5 dashed + low opacity
  //   - Y-axis forced to 30/50/75 split (3 meaningful labels only)
  //   - X-axis: first + last date only on mobile
  //   - Touch tooltip with 3-series breakdown
  const colors = {
    wdl: getCSSVar('--chart-wdl', '#E91E63'),
    ou:  getCSSVar('--chart-ou',  '#00F0FF'),
    ah:  getCSSVar('--chart-ah',  '#fb923c'),
  };
  const baseColor  = getCSSVar('--v2-text-tertiary', '#71717A');
  const borderCol  = getCSSVar('--v2-border',        '#E4E4E7');
  const cardBg     = getCSSVar('--v2-bg-card',       '#FFFFFF');
  const textPri    = getCSSVar('--v2-text-primary',  '#09090B');
  const tooltipBg  = getCSSVar('--chart-tooltip-bg', cardBg);
  const tooltipTxt = getCSSVar('--chart-tooltip-text', textPri);

  const dates = data.wdl.map(p => p.date);

  const makeSeries = (key: SeriesKey) => {
    const isHidden = hidden[key];
    return {
      name: LABEL_MAP[key].short,
      type: 'line' as const,
      data: data[key].map(p => p.acc != null ? parseFloat((p.acc * 100).toFixed(1)) : null),
      smooth: 0.3,
      showSymbol: false,
      sampling: 'lttb' as const,
      connectNulls: false,
      z: isHidden ? 1 : 2,
      lineStyle: {
        color: colors[key],
        width: isHidden ? 1.5 : 2.6,
        type: (isHidden ? 'dashed' : 'solid') as 'dashed' | 'solid',
        cap: 'round' as const,
        join: 'round' as const,
        opacity: isHidden ? 0.4 : 1,
      },
      itemStyle: { color: colors[key] },
      emphasis: { focus: 'series' as const, lineStyle: { width: isHidden ? 1.5 : 3 } },
    };
  };

  return {
    backgroundColor: 'transparent',
    animation: true,
    animationDuration: 600,
    animationEasing: 'cubicOut' as const,
    legend: { show: false },
    tooltip: {
      trigger: 'axis' as const,
      confine: true,
      axisPointer: {
        type: 'line' as const,
        lineStyle: { color: borderCol, width: 1, type: 'dashed' as const },
        label: { show: false },
      },
      backgroundColor: tooltipBg,
      borderColor: borderCol,
      borderWidth: 1,
      padding: [10, 12],
      textStyle: { color: tooltipTxt, fontSize: 13, fontWeight: 600 },
      formatter: (params: any[]) => {
        const d = params[0]?.axisValue ?? '';
        const rows = params
          .filter(p => p.value != null)
          .map(p => `
            <div style="display:flex;align-items:center;gap:6px;margin-top:3px">
              <span style="width:10px;height:3px;background:${p.color};border-radius:2px"></span>
              <span style="color:${baseColor};font-weight:600;font-size:12px;flex:1">${p.seriesName}</span>
              <span style="color:${tooltipTxt};font-weight:800;font-family:monospace;font-size:14px">${p.value}%</span>
            </div>
          `)
          .join('');
        return `
          <div style="font-size:12px;color:${baseColor};font-weight:700;margin-bottom:2px">${d}</div>
          ${rows}
        `;
      },
    },
    grid: { top: 12, right: 16, bottom: 28, left: 44 },
    xAxis: {
      type: 'category' as const,
      data: dates,
      boundaryGap: false,
      axisLabel: {
        color: baseColor,
        fontSize: 12,
        fontWeight: 600,
        fontFamily: 'monospace',
        formatter: (v: string) => v.slice(5).replace('-', '/'),
        interval: (idx: number) => idx === 0 || idx === dates.length - 1,
        showMinLabel: true,
        showMaxLabel: true,
        margin: 10,
      },
      axisLine: { lineStyle: { color: borderCol } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      min: 30,
      max: 75,
      interval: 15, // 30 / 45 / 60 / 75
      axisLabel: {
        color: baseColor,
        fontSize: 12,
        fontWeight: 600,
        fontFamily: 'monospace',
        formatter: (v: number) => `${v}%`,
        margin: 8,
        // Only render 30, 50, 75 for clarity
        showMinLabel: true,
        showMaxLabel: true,
      },
      splitLine: {
        lineStyle: { color: borderCol, type: 'dashed' as const, opacity: 0.4 },
      },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        ...makeSeries('wdl'),
        markLine: {
          silent: true,
          symbol: 'none',
          data: [{
            yAxis: 50,
            lineStyle: {
              color: baseColor,
              type: 'solid' as const,
              width: 1.2,
              opacity: 0.6,
            },
            label: {
              show: true,
              formatter: '50% 基准',
              color: baseColor,
              fontSize: 12,
              fontWeight: 700,
              backgroundColor: cardBg,
              padding: [2, 5],
              borderRadius: 3,
              position: 'insideEndTop' as const,
            },
          }],
        },
      },
      makeSeries('ou'),
      makeSeries('ah'),
    ],
  };
}

function LegendChip({
  seriesKey,
  color,
  hidden,
}: {
  seriesKey: SeriesKey;
  color: string;
  hidden: boolean;
}) {
  const { short } = LABEL_MAP[seriesKey];
  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5 rounded-full border"
      style={{
        background: hidden
          ? 'color-mix(in srgb, var(--v2-accent-warning) 8%, transparent)'
          : 'var(--v2-bg-muted)',
        borderColor: hidden
          ? 'color-mix(in srgb, var(--v2-accent-warning) 35%, transparent)'
          : 'var(--v2-border)',
      }}
    >
      <span
        className="inline-block rounded-full flex-shrink-0"
        style={{
          width: 10,
          height: 10,
          background: color,
          boxShadow: hidden ? 'none' : `0 0 6px ${color}80`,
          opacity: hidden ? 0.5 : 1,
        }}
      />
      <span
        className="text-base font-bold font-mono leading-none"
        style={{ color: hidden ? 'var(--v2-text-tertiary)' : 'var(--v2-text-primary)' }}
      >
        {short}
      </span>
      {hidden && (
        <span
          className="text-xs font-bold uppercase tracking-wider leading-none"
          style={{ color: 'var(--v2-accent-warning)' }}
        >
          恢复
        </span>
      )}
    </div>
  );
}

export default function RollingAccuracyChart({ data, currentHidden }: Props) {
  const { theme } = useTheme();
  void theme;

  const chartColors = {
    wdl: getCSSVar('--chart-wdl', '#E91E63'),
    ou:  getCSSVar('--chart-ou',  '#00F0FF'),
    ah:  getCSSVar('--chart-ah',  '#fb923c'),
  };

  return (
    <div
      className="rounded-2xl border p-5 flex flex-col gap-3"
      style={{ background: 'var(--v2-bg-card)', borderColor: 'var(--v2-border)' }}
    >
      {/* Header */}
      <div className="flex flex-col gap-1">
        <div className="flex items-baseline justify-between gap-2 flex-wrap">
          <p
            className="text-xs font-bold uppercase tracking-wider"
            style={{ color: 'var(--v2-text-tertiary)' }}
          >
            方向趋势
          </p>
          <span
            className="text-sm font-semibold font-mono"
            style={{ color: 'var(--v2-text-tertiary)' }}
          >
            近 30 天 · 基准 50%
          </span>
        </div>
        <p className="text-sm font-semibold" style={{ color: 'var(--v2-text-secondary)' }}>
          胜平负 · 大小球 · 亚盘 三市场滚动命中率
        </p>
      </div>

      {/* Legend chips (replaces native ECharts legend) */}
      <div className="flex items-center gap-2 flex-wrap">
        {KEYS.map(k => (
          <LegendChip
            key={k}
            seriesKey={k}
            color={chartColors[k]}
            hidden={currentHidden[k]}
          />
        ))}
      </div>

      {/* Chart */}
      <div className="h-52">
        <EChartWrapper option={buildOption(data, currentHidden)} style={{ minHeight: '200px' }} />
      </div>
    </div>
  );
}
