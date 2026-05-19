'use client';

import React, { useEffect, useState } from 'react';
import EChartWrapper from './EChartWrapper';
import { TrendingUp, Activity } from 'lucide-react';

// ── 类型 ──────────────────────────────────────────────────────────────
interface DataPoint { date: string; cumPnl: number }
interface StrategyMeta { label: string; total_bets: number; final_pnl: number }
interface EquityCurvesData {
  generated_at: string;
  period: { start: string; end: string };
  strategies: Record<string, DataPoint[]>;
  meta: Record<string, StrategyMeta>;
}

// 策略颜色 & 标签配置
const STRATEGY_CONFIG: Record<string, { color: string; glow: string; tag: string }> = {
  '量化节奏策略': { color: '#00f0ff', glow: 'rgba(0,240,255,0.3)', tag: 'WDL' },
  '大球动能策略': { color: '#a78bfa', glow: 'rgba(167,139,250,0.3)', tag: 'OU'  },
  '综合价值策略': { color: '#34d399', glow: 'rgba(52,211,153,0.3)',  tag: '综合' },
};

// ── 单条策略图表 ──────────────────────────────────────────────────────
function SingleEquityChart({
  name, data, color, glow,
}: { name: string; data: DataPoint[]; color: string; glow: string }) {
  if (!data || data.length === 0) return null;

  const dates  = data.map(d => d.date);
  const values = data.map(d => d.cumPnl);
  const finalPnl = values[values.length - 1];
  const isPos = finalPnl >= 0;

  const option = {
    backgroundColor: 'transparent',
    grid: { top: 8, right: 8, bottom: 28, left: 48, containLabel: false },
    xAxis: {
      type: 'category',
      data: dates,
      show: true,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        show: true,
        color: 'rgba(255,255,255,0.25)',
        fontSize: 12,
        interval: Math.floor(dates.length / 4),
        formatter: (v: string) => v.slice(5), // 只显示 MM-DD
      },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: 'rgba(255,255,255,0.25)',
        fontSize: 12,
        formatter: (v: number) => v >= 1000 ? `${(v/1000).toFixed(0)}k` : String(v),
      },
      splitLine: {
        lineStyle: { color: 'rgba(255,255,255,0.05)', type: 'dashed' },
      },
    },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(10,15,30,0.95)',
      borderColor: color,
      borderWidth: 1,
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (params: any[]) => {
        const p = params[0];
        const sign = p.value >= 0 ? '+' : '';
        return `${p.name}<br/>累计盈亏: <b style="color:${color}">${sign}¥${p.value.toLocaleString()}</b>`;
      },
    },
    series: [{
      type: 'line',
      data: values,
      smooth: 0.3,
      symbol: 'none',
      lineStyle: { color, width: 2 },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: glow },
            { offset: 1, color: 'rgba(0,0,0,0)' },
          ],
        },
      },
      markLine: {
        silent: true,
        symbol: 'none',
        data: [{ yAxis: 0, lineStyle: { color: 'rgba(255,255,255,0.15)', type: 'solid', width: 1 } }],
      },
    }],
  };

  return (
    <div className="relative h-[140px] w-full">
      <EChartWrapper option={option} style={{ height: '140px' }} />
    </div>
  );
}

// ── 主组件 ────────────────────────────────────────────────────────────
export default function StrategyEquityChart() {
  const [data, setData]       = useState<EquityCurvesData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(false);

  useEffect(() => {
    fetch('/api/v1/strategies/equity_curves')
      .then(r => { if (!r.ok) throw new Error('no data'); return r.json(); })
      .then(d => { setData(d); setLoading(false); })
      .catch(() => { setError(true); setLoading(false); });
  }, []);

  if (loading) return (
    <div className="mx-4 my-3 rounded-2xl bg-white/5 border border-white/10 p-5 animate-pulse h-40" />
  );
  if (error || !data) return null;

  const strategyNames = Object.keys(data.strategies);

  return (
    <div className="mx-4 my-3">
      {/* 标题 */}
      <div className="flex items-center gap-2 mb-3 px-1">
        <TrendingUp size={15} className="text-cyan-400" />
        <span className="text-xs font-bold text-white/70 tracking-widest uppercase">策略权益曲线</span>
        <span className="text-xs text-white/30 ml-auto">
          {data.period.start.slice(5)} → {data.period.end.slice(5)}  OOS 验证
        </span>
      </div>

      {/* 策略卡片列表 */}
      <div className="space-y-3">
        {strategyNames.map(name => {
          const cfg     = STRATEGY_CONFIG[name] ?? { color: '#ffffff', glow: 'rgba(255,255,255,0.2)', tag: '' };
          const series  = data.strategies[name];
          const finalPnl = series?.length ? series[series.length - 1].cumPnl : 0;
          const isPos   = finalPnl >= 0;
          const meta    = data.meta[name];

          return (
            <div
              key={name}
              className="rounded-2xl bg-[#0a0f1a] border border-white/10 overflow-hidden"
              style={{ boxShadow: `0 0 20px ${cfg.glow}` }}
            >
              {/* 卡片头 */}
              <div className="flex items-center justify-between px-4 pt-3 pb-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-white">{name}</span>
                  <span
                    className="text-xs px-2 py-0.5 rounded-full font-bold"
                    style={{ background: `${cfg.glow}`, color: cfg.color, border: `1px solid ${cfg.color}40` }}
                  >
                    {cfg.tag}
                  </span>
                </div>
                <div className="text-right">
                  <div
                    className="text-sm font-bold"
                    style={{ color: isPos ? cfg.color : '#f87171' }}
                  >
                    {isPos ? '+' : ''}¥{finalPnl.toLocaleString()}
                  </div>
                  <div className="text-xs text-white/30">{meta?.total_bets ?? '--'} 注</div>
                </div>
              </div>

              {/* 图表区 */}
              <div className="px-1 pb-2">
                <SingleEquityChart
                  name={name}
                  data={series}
                  color={cfg.color}
                  glow={cfg.glow}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* 免责声明 */}
      <p className="text-xs text-white/20 text-center mt-2 px-2">
        以上为 OOS 严格时序回测结果，不构成投资建议。历史表现不代表未来收益。
      </p>
    </div>
  );
}
