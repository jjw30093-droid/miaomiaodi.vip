'use client';

import type { BestRecentStat } from '@/types/report';

interface Props {
  stat?: BestRecentStat | null;
}

export default function RecentStatCard({ stat }: Props) {
  if (!stat) return null;

  const losses = stat.total - stat.wins;

  return (
    <section className="rounded-lg border border-slate-200 dark:border-white/15 bg-white dark:bg-slate-950 shadow-sm dark:shadow-none p-5">
      <p className="text-[18px] font-bold text-slate-950 dark:text-white mb-4 border-b border-slate-200 dark:border-white/15 pb-3">
        近{stat.total}场{stat.label}表现
      </p>

      <div className="grid grid-cols-3 gap-2 mb-4">
        <Metric label="命中" value={stat.wins.toString()} />
        <Metric label="未中" value={losses.toString()} />
        <Metric label="命中率" value={`${stat.hitRate.toFixed(1)}%`} />
      </div>

      <div className="flex flex-wrap gap-1.5 mb-4">
        {stat.emojiSequence.map((result, i) => (
          <span
            key={i}
            className={`inline-flex h-7 min-w-7 items-center justify-center rounded border px-2 text-[13px] font-bold ${
              result === 'hit'
                ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-400/30 dark:bg-emerald-400/10 dark:text-emerald-200'
                : 'border-slate-200 bg-slate-50 text-slate-700 dark:border-white/15 dark:bg-slate-900 dark:text-slate-200'
            }`}
          >
            {result === 'hit' ? '中' : '未中'}
          </span>
        ))}
      </div>

      <p className="text-[13px] text-slate-600 dark:text-slate-300 leading-relaxed">
        以上为历史样本表现，不代表未来结果。数据分析仅供参考，不构成投注建议。
      </p>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-200 dark:border-white/15 bg-slate-50 dark:bg-slate-900 px-3 py-2">
      <p className="text-[13px] font-bold text-slate-600 dark:text-slate-300">{label}</p>
      <p className="mt-1 text-[18px] font-black text-slate-950 dark:text-white tabular-nums">{value}</p>
    </div>
  );
}
