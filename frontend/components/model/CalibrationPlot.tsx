'use client';
import React from 'react';
import EChartWrapper from '@/components/EChartWrapper';
import { useTheme } from '@/components/ThemeProvider';
import type { CalibrationBin } from '@/lib/modelHealth/types';

function getCSSVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace('#', '').trim();
  if (h.length !== 6) return hex;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

interface Props {
  data: CalibrationBin[];
}

export default function CalibrationPlot({ data }: Props) {
  const { theme } = useTheme();
  void theme;

  const cardStyle: React.CSSProperties = {
    background: 'var(--v2-bg-card)',
    borderColor: 'var(--v2-border)',
  };

  if (!data || data.length === 0) {
    return (
      <div className="rounded-2xl border p-5" style={cardStyle}>
        <p
          className="text-xs font-bold uppercase tracking-wider mb-2"
          style={{ color: 'var(--v2-text-tertiary)' }}
        >
          校准可信度
        </p>
        <p
          className="text-sm font-semibold mb-4"
          style={{ color: 'var(--v2-text-secondary)' }}
        >
          当我说胜率 70%，实际命中了多少？
        </p>
        <div
          className="h-48 flex items-center justify-center text-base font-semibold"
          style={{ color: 'var(--v2-text-tertiary)' }}
        >
          暂无校准数据
        </div>
      </div>
    );
  }

  // Mobile-optimized calibration / reliability diagram:
  //   - Square aspect so 45° diagonal is geometrically correct
  //   - Prominent diagonal y=x (success green, 2px solid) with "完美校准" label
  //   - Dots connected by a thin trend line (sklearn convention)
  //   - Dot size scaled by sqrt(n) for readability; each dot has card-color border for contrast
  //   - Dot color by |predicted - actual|: green if <10%, amber if <20%, red otherwise
  //   - Grid every 20% dashed with --v2-border (visible, not dominating)
  //   - Axis labels 11px semibold mono in --v2-text-secondary
  const accentGreen  = getCSSVar('--v2-accent-success', '#059669');
  const accentAmber  = getCSSVar('--v2-accent-warning', '#D97706');
  const accentDanger = getCSSVar('--v2-accent-danger',  '#DC2626');
  const accentInfo   = getCSSVar('--v2-accent-info',    '#2563EB');
  const borderCol    = getCSSVar('--v2-border',         '#E4E4E7');
  const cardBg       = getCSSVar('--v2-bg-card',        '#FFFFFF');
  const textPri      = getCSSVar('--v2-text-primary',   '#09090B');
  const textSec      = getCSSVar('--v2-text-secondary', '#52525B');
  const textTer      = getCSSVar('--v2-text-tertiary',  '#71717A');

  const errorColor = (err: number): string => {
    if (err < 0.10) return accentGreen;
    if (err < 0.20) return accentAmber;
    return accentDanger;
  };

  // Sort dots by predicted so the connecting line flows left→right
  const sorted = [...data].sort((a, b) => a.predicted - b.predicted);
  const maxN = Math.max(...sorted.map(d => d.n || 1), 1);

  const scatterData = sorted.map(d => {
    const err = Math.abs(d.predicted - d.actual);
    const color = errorColor(err);
    // symbolSize 12–28: sqrt(n/maxN) * 16 + 12
    const size = Math.round(Math.sqrt((d.n || 1) / maxN) * 16 + 12);
    return {
      value: [d.predicted, d.actual, d.n, err],
      symbolSize: size,
      itemStyle: {
        color,
        borderColor: cardBg,
        borderWidth: 2,
        shadowBlur: 6,
        shadowColor: hexToRgba(color, 0.5),
      },
    };
  });

  const lineData = sorted.map(d => [d.predicted, d.actual]);

  const option = {
    backgroundColor: 'transparent',
    animation: true,
    animationDuration: 600,
    animationEasing: 'cubicOut' as const,
    grid: { top: 24, right: 20, bottom: 44, left: 48 },
    tooltip: {
      trigger: 'item' as const,
      confine: true,
      backgroundColor: cardBg,
      borderColor: borderCol,
      borderWidth: 1,
      padding: [10, 12],
      textStyle: { color: textPri, fontSize: 13, fontWeight: 600 },
      formatter: (p: any) => {
        const d = p.data?.value ?? p.data;
        if (!Array.isArray(d)) return '';
        const [pred, actual, n, err] = d as [number, number, number, number];
        const diff = actual - pred;
        const status =
          err < 0.05
            ? { text: '校准良好', color: accentGreen }
            : diff > 0
              ? { text: '保守 · 实际更准', color: accentInfo }
              : { text: '过度自信', color: accentDanger };
        return `
          <div style="font-size:12px;color:${textTer};font-weight:700;margin-bottom:4px">
            预测 ${(pred * 100).toFixed(0)}% → 实际 ${(actual * 100).toFixed(0)}%
          </div>
          <div style="display:flex;align-items:center;gap:8px;margin-top:2px">
            <span style="color:${textSec};font-size:12px;font-weight:600">样本</span>
            <span style="color:${textPri};font-weight:800;font-family:monospace;font-size:14px">${n} 场</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px;margin-top:2px">
            <span style="color:${textSec};font-size:12px;font-weight:600">偏差</span>
            <span style="color:${errorColor(err)};font-weight:800;font-family:monospace;font-size:14px">
              ${diff >= 0 ? '+' : ''}${(diff * 100).toFixed(1)}%
            </span>
          </div>
          <div style="margin-top:6px;padding-top:6px;border-top:1px dashed ${borderCol};font-size:12px;font-weight:700;color:${status.color}">
            ${status.text}
          </div>
        `;
      },
    },
    xAxis: {
      type: 'value' as const,
      min: 0,
      max: 1,
      interval: 0.2,
      name: '预测概率',
      nameLocation: 'middle' as const,
      nameGap: 28,
      nameTextStyle: { color: textTer, fontSize: 12, fontWeight: 700 },
      axisLabel: {
        color: textSec,
        fontSize: 12,
        fontWeight: 600,
        fontFamily: 'monospace',
        formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
        margin: 8,
      },
      splitLine: { lineStyle: { color: borderCol, type: 'dashed' as const, opacity: 0.5 } },
      axisLine: { lineStyle: { color: borderCol } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      min: 0,
      max: 1,
      interval: 0.2,
      name: '实际命中',
      nameLocation: 'middle' as const,
      nameGap: 34,
      nameTextStyle: { color: textTer, fontSize: 12, fontWeight: 700 },
      axisLabel: {
        color: textSec,
        fontSize: 12,
        fontWeight: 600,
        fontFamily: 'monospace',
        formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
        margin: 8,
      },
      splitLine: { lineStyle: { color: borderCol, type: 'dashed' as const, opacity: 0.5 } },
      axisLine: { lineStyle: { color: borderCol } },
      axisTick: { show: false },
    },
    series: [
      // Diagonal y=x reference line — prominent
      {
        name: '完美校准',
        type: 'line' as const,
        data: [[0, 0], [1, 1]],
        showSymbol: false,
        silent: true,
        z: 1,
        lineStyle: {
          color: textTer,
          width: 1.5,
          type: 'dashed' as const,
          opacity: 0.9,
        },
        endLabel: {
          show: true,
          formatter: '完美校准',
          color: textTer,
          fontSize: 12,
          fontWeight: 700,
          backgroundColor: cardBg,
          padding: [3, 6],
          borderRadius: 4,
          borderColor: borderCol,
          borderWidth: 1,
          offset: [-52, -4],
        },
      },
      // Trend line connecting actual bins
      {
        name: '模型曲线',
        type: 'line' as const,
        data: lineData,
        showSymbol: false,
        silent: true,
        z: 2,
        smooth: 0.3,
        lineStyle: {
          color: accentInfo,
          width: 1.5,
          opacity: 0.4,
        },
      },
      // Scatter bins
      {
        name: '样本分箱',
        type: 'scatter' as const,
        data: scatterData,
        z: 3,
        emphasis: {
          scale: 1.15,
          itemStyle: { borderWidth: 3 },
        },
      },
    ],
  };

  return (
    <div className="rounded-2xl border p-5 flex flex-col gap-3" style={cardStyle}>
      <div className="flex flex-col gap-1">
        <div className="flex items-baseline justify-between gap-2 flex-wrap">
          <p
            className="text-xs font-bold uppercase tracking-wider"
            style={{ color: 'var(--v2-text-tertiary)' }}
          >
            校准可信度
          </p>
          <span
            className="text-sm font-semibold font-mono"
            style={{ color: 'var(--v2-text-tertiary)' }}
          >
            散点越近对角线 = 越准
          </span>
        </div>
        <p className="text-sm font-semibold" style={{ color: 'var(--v2-text-secondary)' }}>
          当我说胜率 70%，实际命中了多少？
        </p>
      </div>

      {/* Color legend */}
      <div className="flex items-center gap-3 flex-wrap">
        <LegendDot color="var(--v2-accent-success)" label="偏差 < 10%" />
        <LegendDot color="var(--v2-accent-warning)" label="10–20%" />
        <LegendDot color="var(--v2-accent-danger)"  label="> 20%" />
        <span
          className="ml-auto text-xs font-bold uppercase tracking-wider"
          style={{ color: 'var(--v2-text-tertiary)' }}
        >
          圆越大 · 样本越多
        </span>
      </div>

      <div className="aspect-square max-h-80 w-full">
        <EChartWrapper option={option} style={{ width: '100%', height: '100%', minHeight: '260px' }} />
      </div>
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className="inline-block rounded-full"
        style={{ width: 10, height: 10, background: color, boxShadow: `0 0 6px ${color}` }}
      />
      <span
        className="text-sm font-semibold font-mono"
        style={{ color: 'var(--v2-text-secondary)' }}
      >
        {label}
      </span>
    </div>
  );
}
