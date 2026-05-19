'use client';
import { useEffect, useRef } from 'react';
import { ModelHealthData, EquityBlock } from './types';
import type { ModelSnapshotV2, SinglePickWindow } from '@/lib/modelHealth/types';
import { SAMPLE_FLOOR, WINDOWS } from '@/lib/modelHealth/constants';
import { formatPct, formatROI } from '@/lib/modelHealth/formatters';

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
      <span className="text-xs font-black tracking-[0.25em] uppercase text-white/30">{label}</span>
      <span className={`text-xl font-black font-mono tabular-nums ${color} group-hover:drop-shadow-[0_0_12px_currentColor] transition-all`}>
        {value != null
          ? <CountUp target={value} decimals={decimals} suffix={suffix} />
          : <span className="text-white/20">—</span>}
      </span>
      {sublabel && <span className="text-xs text-white/20 font-mono">{sublabel}</span>}
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
          <span className="text-xs font-black tracking-[0.25em] uppercase text-white/30">AH 亚盘准确率</span>
          {ahAcc != null ? (
            <span className="text-xl font-black font-mono tabular-nums text-emerald-400">
              <CountUp target={ahAcc} decimals={1} suffix="%" />
            </span>
          ) : (
            <span className="text-xl font-black font-mono text-white/20">—</span>
          )}
          <span className="text-xs text-white/20 font-mono">
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

// ── V2 Snapshot KPI Grid ──────────────────────────────────────────────────────

interface SnapshotWindowCardProps {
  window: SinglePickWindow;
  adjustingDays?: number;
}

const V2_CARD_STYLE: React.CSSProperties = {
  background: 'var(--v2-bg-card)',
  borderColor: 'var(--v2-border)',
  color: 'var(--v2-text-primary)',
};

function SnapshotWindowCard({ window: w, adjustingDays = 0 }: SnapshotWindowCardProps) {
  const hitRatePct = w.hit_rate != null ? w.hit_rate * 100 : null;
  const roiStr = formatROI(w.roi);
  const isRoiPositive = w.roi != null && w.roi > 0;
  const isHitGood = hitRatePct != null && hitRatePct >= 50;
  const hitColor = isHitGood ? 'var(--v2-accent-success)' : 'var(--v2-text-tertiary)';
  const roiColor = isRoiPositive ? 'var(--v2-accent-success)' : 'var(--v2-text-tertiary)';

  return (
    <div
      className="rounded-2xl border p-4 flex flex-col gap-1.5"
      style={V2_CARD_STYLE}
    >
      <span
        className="text-xs font-bold uppercase tracking-wider"
        style={{ color: 'var(--v2-text-tertiary)' }}
      >
        近 {w.window_days} 天
      </span>
      <span
        className="text-2xl font-black italic font-mono tabular-nums"
        style={{ color: 'var(--v2-text-primary)' }}
      >
        {w.hits}/{w.n_settled}
      </span>
      <div className="flex items-center gap-2 flex-wrap">
        {hitRatePct != null && (
          <span
            className="text-sm font-semibold font-mono tabular-nums"
            style={{ color: hitColor }}
          >
            {hitRatePct.toFixed(1)}%
          </span>
        )}
        <span
          className="text-sm font-semibold font-mono tabular-nums"
          style={{ color: roiColor }}
        >
          ROI {roiStr}
        </span>
      </div>
    </div>
  );
}

export function KpiGridSnapshot({ snap }: { snap: ModelSnapshotV2 }) {
  const { single_pick, total_settled = 0, cold_start, drift } = snap;
  const adjustingDays = drift?.adjusting_days ?? 0;

  if (cold_start || total_settled < SAMPLE_FLOOR) {
    return (
      <div
        className="rounded-2xl border p-6 text-center"
        style={V2_CARD_STYLE}
      >
        <p className="text-base font-semibold" style={{ color: 'var(--v2-text-secondary)' }}>
          模型训练中，样本积累至 {SAMPLE_FLOOR} 场后展示
        </p>
        <p className="text-sm font-semibold font-mono mt-2" style={{ color: 'var(--v2-text-tertiary)' }}>
          当前 {total_settled} 场
        </p>
      </div>
    );
  }

  const windows: SinglePickWindow[] = [
    single_pick.w7,
    single_pick.w14,
    single_pick.w30,
  ];

  return (
    <div className="grid grid-cols-3 gap-3">
      {windows.map(w => (
        <SnapshotWindowCard key={w.window_days} window={w} adjustingDays={adjustingDays} />
      ))}
    </div>
  );
}
