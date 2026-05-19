'use client';
import React from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';
import EChartWrapper from '@/components/EChartWrapper';
import { useTheme } from '@/components/ThemeProvider';
import type { EquityCurvePoint } from '@/lib/modelHealth/types';

// New interface: single curve from snapshot
interface CurveProps {
  curve: EquityCurvePoint[];
}

// Legacy interface: old /health equity block (ModelDashboard compat)
interface LegacyProps {
  equity: any;
  updatedAt: string;
}

type Props = CurveProps | LegacyProps;

function isCurveProps(p: Props): p is CurveProps {
  return 'curve' in p;
}

function legacyToCurve(equity: any): EquityCurvePoint[] {
  const fixed = equity?.fixed ?? equity;
  const composite = fixed?.strategies?.find((s: any) => s.name === '合成') ?? fixed?.strategies?.[0];
  return composite?.points ?? [];
}

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace('#', '').trim();
  if (h.length !== 6) return hex;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function buildOption(curve: EquityCurvePoint[], isUp: boolean, isDark: boolean) {
  // 主题感知配色：浅色用深字，深色用浅字
  const lineColor  = isUp ? '#10B981' : '#DC2626';
  const textPri    = isDark ? '#F1F5F9' : '#0F172A';   // 主文本
  const baseColor  = isDark ? '#CBD5E1' : '#475569';   // 次文本
  const borderCol  = isDark ? '#475569' : '#94A3B8';   // 网格/边框（提升对比，能在深色背景上看见虚线）
  const cardBg     = isDark ? '#0F172A' : '#FFFFFF';
  const tooltipBg  = isDark ? '#1E293B' : cardBg;
  const tooltipTxt = textPri;

  const dates  = curve.map(p => p.date);
  const values = curve.map(p => p.value);

  // Auto-scale Y axis with 10% padding around min(0, data) .. max(0, data)
  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  const rangeLo = Math.min(dataMin, 0);
  const rangeHi = Math.max(dataMax, 0);
  const pad     = Math.max((rangeHi - rangeLo) * 0.12, 0.5);
  const yMin    = +(rangeLo - pad).toFixed(2);
  const yMax    = +(rangeHi + pad).toFixed(2);

  return {
    backgroundColor: 'transparent',
    animation: true,
    animationDuration: 600,
    animationEasing: 'cubicOut' as const,
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
      padding: [8, 12],
      textStyle: { color: tooltipTxt, fontSize: 13, fontWeight: 600 },
      formatter: (params: any[]) => {
        const p = params[0];
        const v = Number(p.value);
        const sign = v >= 0 ? '+' : '';
        return `
          <div style="font-size:12px;color:${baseColor};font-weight:600;margin-bottom:2px">${p.axisValue}</div>
          <div style="font-size:15px;color:${lineColor};font-weight:900;font-family:monospace">${sign}${v.toFixed(2)} 单位</div>
        `;
      },
    },
    grid: { top: 20, right: 20, bottom: 30, left: 52 },
    xAxis: {
      type: 'category' as const,
      data: dates,
      boundaryGap: false,
      axisLabel: {
        color: textPri,
        fontSize: 12,
        fontWeight: 700,
        fontFamily: 'monospace',
        formatter: (v: string) => v.slice(5).replace('-', '/'),
        // 5 个均匀分布的标签：起、25%、50%、75%、终
        interval: (idx: number) => {
          const total = dates.length;
          if (total <= 5) return true;
          const positions = [0, Math.floor(total * 0.25), Math.floor(total * 0.5), Math.floor(total * 0.75), total - 1];
          return positions.includes(idx);
        },
        showMinLabel: true,
        showMaxLabel: true,
        margin: 12,
      },
      axisLine: { lineStyle: { color: textPri, width: 1 } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value' as const,
      min: yMin,
      max: yMax,
      splitNumber: 4,
      axisLabel: {
        color: textPri,
        fontSize: 12,
        fontWeight: 700,
        fontFamily: 'monospace',
        formatter: (v: number) => (v >= 0 ? '+' : '') + v.toFixed(1),
        margin: 10,
      },
      splitLine: {
        lineStyle: { color: borderCol, type: 'dashed' as const, opacity: 0.7 },
      },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        name: '单推净值',
        type: 'line' as const,
        data: values,
        smooth: 0.3,
        showSymbol: false,
        sampling: 'lttb' as const,
        connectNulls: true,
        lineStyle: { color: lineColor, width: 3, cap: 'round' as const, join: 'round' as const },
        emphasis: { focus: 'series' as const, lineStyle: { width: 3 } },
        areaStyle: {
          color: {
            type: 'linear' as const,
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0,    color: hexToRgba(lineColor, 0.32) },
              { offset: 0.6,  color: hexToRgba(lineColor, 0.08) },
              { offset: 1,    color: hexToRgba(lineColor, 0.00) },
            ],
          },
        },
        itemStyle: { color: lineColor },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [{
            yAxis: 0,
            lineStyle: { color: textPri, type: 'dashed' as const, width: 1.5, opacity: 0.9 },
            label: {
              show: true,
              formatter: '盈亏平衡',
              color: textPri,
              fontSize: 12,
              fontWeight: 800,
              position: 'insideStartTop' as const,
              padding: [3, 6],
              backgroundColor: cardBg,
              borderColor: textPri,
              borderWidth: 1,
              borderRadius: 4,
            },
          }],
        },
        markPoint: {
          symbol: 'circle',
          symbolSize: 10,
          data: [{
            coord: [dates.length - 1, values[values.length - 1]],
            itemStyle: { color: lineColor, borderColor: cardBg, borderWidth: 2, shadowColor: hexToRgba(lineColor, 0.5), shadowBlur: 8 },
            label: { show: false },
          }],
        },
      },
    ],
  };
}

export default function EquityHero(props: Props) {
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const curve = isCurveProps(props) ? props.curve : legacyToCurve(props.equity);
  const lastVal = curve.at(-1)?.value ?? null;
  const pct = lastVal;
  const isUp = pct != null && pct >= 0;

  const cardStyle: React.CSSProperties = {
    background: isDark ? '#0F172A' : '#FFFFFF',
    borderColor: isDark ? '#334155' : '#E2E8F0',
  };

  if (!curve.length) {
    return (
      <div
        className="rounded-2xl border p-4 h-48 flex items-center justify-center text-base font-semibold"
        style={{ ...cardStyle, color: isDark ? '#94A3B8' : '#64748B' }}
      >
        暂无净值数据
      </div>
    );
  }

  // chip 背景：浅色用更深的绿/红，与卡片背景对比更强；深色用鲜亮版
  const pctColor = isUp
    ? (isDark ? '#10B981' : '#047857')
    : (isDark ? '#DC2626' : '#991B1B');
  const numColor = isUp ? (isDark ? '#34D399' : '#047857') : (isDark ? '#F87171' : '#B91C1C');
  const labelColor = isDark ? '#94A3B8' : '#64748B';

  return (
    <div className="rounded-2xl border p-4 flex flex-col gap-3" style={cardStyle}>
      <div className="flex items-baseline gap-3 flex-wrap">
        <span
          className="text-3xl font-black italic font-mono tabular-nums"
          style={{ color: numColor }}
        >
          {lastVal != null ? `${lastVal >= 0 ? '+' : ''}${lastVal.toFixed(2)}` : '—'}
        </span>
        {pct != null && (
          <div
            className="flex items-center gap-1 font-black italic font-mono tabular-nums px-2 py-0.5 rounded"
            style={{ fontSize: 13, color: '#fff', background: pctColor }}
          >
            {isUp ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
            单位
          </div>
        )}
        <span
          className="font-bold uppercase tracking-wider ml-auto"
          style={{ fontSize: 12, color: labelColor }}
        >
          单推累计盈亏
        </span>
      </div>
      <div className="h-48">
        <EChartWrapper option={buildOption(curve, isUp, isDark)} style={{ minHeight: '180px' }} />
      </div>
    </div>
  );
}
