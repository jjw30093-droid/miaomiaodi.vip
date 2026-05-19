'use client';
import { useEffect, useRef } from 'react';
import { ModelHealthData, EquityBlock } from './types';

interface Props {
  rolling: ModelHealthData['rolling'];
  equity: EquityBlock;
  training: ModelHealthData['latest_training'];
}

function CountUp({ target, decimals = 1, suffix = '' }: { target: number; decimals?: number; suffix?: string }) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const start = 0;
    const duration = 600;
    const startTime = performance.now();

    const step = (now: number) => {
      const elapsed = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - elapsed, 3); // ease-out cubic
      const value = start + (target - start) * eased;
      if (ref.current) ref.current.textContent = value.toFixed(decimals) + suffix;
      if (elapsed < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }, [target, decimals, suffix]);

  return <span ref={ref}>—</span>;
}

interface KpiCardProps {
  label: string;
  value: number | null;
  decimals?: number;
  suffix?: string;
  color?: string;
  sublabel?: string;
}

function KpiCard({ label, value, decimals = 1, suffix = '', color = 'text-white', sublabel }: KpiCardProps) {
  return (
    <div className="glass-panel rounded-2xl border border-white/5 p-4 flex flex-col gap-1.5 hover:-translate-y-[2px] transition-transform cursor-default group">
      <span className="text-[9px] font-black tracking-[0.25em] uppercase text-white/30">{label}</span>
      <span className={`text-xl font-black font-mono tabular-nums ${color} group-hover:drop-shadow-[0_0_12px_currentColor] transition-all`}>
        {value != null
          ? <CountUp target={value} decimals={decimals} suffix={suffix} />
          : <span className="text-white/20">—</span>}
      </span>
      {sublabel && <span className="text-[8px] text-white/20 font-mono">{sublabel}</span>}
    </div>
  );
}

export default function KpiGrid({ rolling, equity, training }: Props) {
  const sharpe   = equity?.sharpe ?? null;
  const maxdd    = equity?.max_drawdown != null ? Math.abs(equity.max_drawdown) * 100 : null;
  const wdlAcc   = rolling.wdl_accuracy != null ? rolling.wdl_accuracy * 100 : null;
  const ouAcc    = rolling.ou_accuracy  != null ? rolling.ou_accuracy  * 100 : null;
  const brierWdl = rolling.brier_wdl    != null ? rolling.brier_wdl : null;
  const brierOu  = rolling.brier_ou     != null ? rolling.brier_ou  : null;
  const samples  = training.sample_count ?? null;
  const ahAcc    = rolling.ah_accuracy  != null ? rolling.ah_accuracy * 100 : null;
  const ahN      = rolling.ah_sample_n ?? 0;

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3">
        <KpiCard
          label="夏普比率"
          value={sharpe}
          decimals={2}
          color="text-primary-neon"
          sublabel="年化，固定仓位"
        />
        <KpiCard
          label="最大回撤"
          value={maxdd}
          decimals={1}
          suffix="%"
          color="text-rose-400"
          sublabel="峰值至谷底"
        />
        <KpiCard
          label="WDL 准确率"
          value={wdlAcc}
          decimals={1}
          suffix="%"
          color="text-emerald-400"
          sublabel={`近 ${rolling.window}d · ${rolling.total_matches} 场`}
        />
        <KpiCard
          label="OU 准确率"
          value={ouAcc}
          decimals={1}
          suffix="%"
          color={ouAcc != null && ouAcc < 50 ? 'text-rose-400' : 'text-[#FF00E5]'}
          sublabel={`近 ${rolling.window}d 滚动`}
        />
        <KpiCard
          label="WDL Brier"
          value={brierWdl}
          decimals={3}
          color="text-white/80"
          sublabel="越低越准 · 理想值 <0.20"
        />
        <KpiCard
          label="OU Brier"
          value={brierOu}
          decimals={3}
          color={brierOu != null && brierOu > 0.25 ? 'text-amber-400' : 'text-white/80'}
          sublabel="越低越准 · 理想值 <0.20"
        />
      </div>

      {/* AH + Training row */}
      <div className="grid grid-cols-2 gap-3">
        <div className="glass-panel rounded-2xl border border-white/5 p-4 flex flex-col gap-1.5">
          <span className="text-[9px] font-black tracking-[0.25em] uppercase text-white/30">AH 亚盘准确率</span>
          {ahAcc != null ? (
            <span className="text-xl font-black font-mono tabular-nums text-emerald-400">
              <CountUp target={ahAcc} decimals={1} suffix="%" />
            </span>
          ) : (
            <span className="text-xl font-black font-mono text-white/20">—</span>
          )}
          <span className="text-[8px] text-white/20 font-mono">
            {ahN < 10 ? `样本仅 ${ahN} 场，待积累` : `${ahN} 场 · 近 30d`}
          </span>
        </div>
        <KpiCard
          label="训练样本"
          value={samples}
          decimals={0}
          color="text-white/60"
          sublabel={`${training.features_n} 维特征`}
        />
      </div>
    </div>
  );
}
