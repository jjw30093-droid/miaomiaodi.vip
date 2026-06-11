'use client';

import { Star } from 'lucide-react';
import type { VerdictSummary } from '@/types/report';

interface Props {
  homeTeam:        string;
  awayTeam:        string;
  verdictSummary?: VerdictSummary | null;
  keyVariables?:   string[] | null;
  /** unused — kept for call-site compat during transition */
  keyRisk?:        string | null;
  pickDirection?:  string | null;
  pickOdds?:       string | null;
  confidenceStars?: number | null;
}

/**
 * 关键论据卡 — 能力星级对比 + 关键变量 3 条。
 * 全部缺失 → 整张卡返回 null。
 */
export default function ModelVerdictCard({
  homeTeam, awayTeam,
  verdictSummary,
  keyVariables,
}: Props) {
  const attack  = verdictSummary?.attackRating;
  const defense = verdictSummary?.defenseRating;
  const form    = verdictSummary?.formLabel;
  const variables = (keyVariables ?? []).filter(v => v && v.trim());

  const hasRatings = !!(attack || defense || form);
  const hasVariables = variables.length > 0;

  if (!hasRatings && !hasVariables) return null;

  return (
    <section className="bg-white/90 dark:bg-[var(--panel-bg-strong)]
                        border border-slate-900/10 dark:border-white/[0.08]
                        rounded-2xl overflow-hidden
                        shadow-[0_1px_4px_rgba(15,23,42,0.05)] dark:shadow-none">

      {/* 标题 */}
      <div className="px-5 pt-5 pb-3">
        <p className="text-xs font-black tracking-[0.25em] uppercase text-[#005faf] dark:text-[#00F0FF]">
          🔑 关键论据
        </p>
      </div>

      {/* ─── ① 能力对比 ─── */}
      {hasRatings && (
        <div className="px-5 pb-5 border-t border-slate-200/60 dark:border-white/5 pt-4">
          <div className="grid grid-cols-[80px_1fr_1fr] gap-3 items-center">
            <span className="text-xs font-bold tracking-widest uppercase text-slate-500 dark:text-white/40"></span>
            <span className="text-sm font-black text-center text-slate-900 dark:text-white truncate">{homeTeam}</span>
            <span className="text-sm font-black text-center text-slate-900 dark:text-white truncate">{awayTeam}</span>

            {attack && (
              <>
                <span className="text-sm font-bold text-slate-700 dark:text-white/70">进攻面</span>
                <StarRow value={attack.home} />
                <StarRow value={attack.away} />
              </>
            )}
            {defense && (
              <>
                <span className="text-sm font-bold text-slate-700 dark:text-white/70">防守面</span>
                <StarRow value={defense.home} />
                <StarRow value={defense.away} />
              </>
            )}
            {form && (
              <>
                <span className="text-sm font-bold text-slate-700 dark:text-white/70">状态面</span>
                <FormBadge label={form.home} />
                <FormBadge label={form.away} />
              </>
            )}
          </div>
        </div>
      )}

      {/* ─── ② 关键变量 ─── */}
      {hasVariables && (
        <div className="px-5 py-4 border-t border-slate-200/60 dark:border-white/5">
          <p className="text-xs font-black tracking-[0.25em] uppercase text-slate-700 dark:text-white/80 mb-3">
            🔑 关键变量
          </p>
          <ul className="space-y-2">
            {variables.slice(0, 3).map((v, i) => (
              <li key={i} className="flex items-start gap-2 text-[15px] text-slate-700 dark:text-white/85 leading-relaxed">
                <span className="text-[#E91E63] dark:text-[#00F0FF] flex-shrink-0 mt-1">•</span>
                <span>{v}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

    </section>
  );
}

// ── Subcomponents ──────────────────────────────────────────────

function StarRow({ value }: { value: number }) {
  return (
    <div className="flex items-center justify-center gap-0.5">
      {[1, 2, 3, 4, 5].map(i => (
        <Star
          key={i}
          size={11}
          className={i <= value ? 'fill-[#FFB800] text-[#FFB800]' : 'text-slate-300 dark:text-white/15'}
        />
      ))}
    </div>
  );
}

function FormBadge({ label }: { label: string }) {
  // Color-code by label keywords
  const tone =
    /连胜|上升/.test(label) ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' :
    /连败|低迷/.test(label) ? 'bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300' :
    'bg-slate-100 text-slate-700 dark:bg-white/8 dark:text-white/70';

  return (
    <div className="flex justify-center">
      <span className={`text-xs font-black tracking-wider px-2.5 py-0.5 rounded-full ${tone}`}>
        {label}
      </span>
    </div>
  );
}
