'use client';

import { Star, AlertTriangle } from 'lucide-react';
import type { VerdictSummary } from '@/types/report';

interface Props {
  homeTeam:        string;
  awayTeam:        string;
  /** From verdict_summary (LLM 综合结论 解析) */
  verdictSummary?: VerdictSummary | null;
  /** From report_store.key_variables (LLM json_meta) */
  keyVariables?:   string[] | null;
  /** From report_store.key_risk (LLM json_meta) */
  keyRisk?:        string | null;
  /** Final pick from inference */
  pickDirection?:  string | null;
  pickOdds?:       string | null;
  /** 1-5; from picked_confidence HIGH→5 / MID→3 / LOW→2 */
  confidenceStars?: number | null;
}

/**
 * Pro 版收口卡 — 整个研报最后的"为什么这样推荐"四段式总结。
 * 每段独立 graceful degrade：缺数据则不渲染该段，但其他段保留。
 * 全部缺失 → 整张卡返回 null。
 */
export default function ModelVerdictCard({
  homeTeam, awayTeam,
  verdictSummary,
  keyVariables, keyRisk,
  pickDirection, pickOdds, confidenceStars,
}: Props) {
  const attack  = verdictSummary?.attackRating;
  const defense = verdictSummary?.defenseRating;
  const form    = verdictSummary?.formLabel;
  const variables = (keyVariables ?? []).filter(v => v && v.trim());

  const hasRatings = !!(attack || defense || form);
  const hasVariables = variables.length > 0;
  const hasPick = !!pickDirection;
  const hasRisk = !!keyRisk;

  if (!hasRatings && !hasVariables && !hasPick && !hasRisk) return null;

  return (
    <section className="bg-white/85 backdrop-blur-xl dark:bg-[var(--panel-bg-strong)]
                        border border-slate-900/10 dark:border-[var(--panel-border-strong)]
                        rounded-3xl overflow-hidden">

      {/* 标题 */}
      <div className="px-5 pt-5 pb-3">
        <p className="text-xs font-black tracking-[0.25em] uppercase text-[#005faf] dark:text-[#00F0FF]">
          🧠 模型综合判断
        </p>
      </div>

      {/* ─── ① 能力对比 ─── */}
      {hasRatings && (
        <div className="px-5 pb-5 border-t border-slate-200/60 dark:border-white/5 pt-4">
          <div className="grid grid-cols-[80px_1fr_1fr] gap-3 items-center">
            <span className="text-xs font-bold tracking-widest uppercase text-slate-500 dark:text-white/40"></span>
            <span className="text-sm font-black text-center text-slate-900 dark:text-xs dark:text-white truncate">{homeTeam}</span>
            <span className="text-sm font-black text-center text-slate-900 dark:text-xs dark:text-white truncate">{awayTeam}</span>

            {attack && (
              <>
                <span className="text-sm font-black text-slate-900 dark:text-xs dark:font-bold dark:text-white/70">进攻面</span>
                <StarRow value={attack.home} />
                <StarRow value={attack.away} />
              </>
            )}
            {defense && (
              <>
                <span className="text-sm font-black text-slate-900 dark:text-xs dark:font-bold dark:text-white/70">防守面</span>
                <StarRow value={defense.home} />
                <StarRow value={defense.away} />
              </>
            )}
            {form && (
              <>
                <span className="text-sm font-black text-slate-900 dark:text-xs dark:font-bold dark:text-white/70">状态面</span>
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
              <li key={i} className="flex items-start gap-2 text-[13px] text-slate-700 dark:text-white/85 leading-relaxed">
                <span className="text-[#E91E63] dark:text-[#00F0FF] flex-shrink-0 mt-1">•</span>
                <span>{v}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ─── ③ 最终结论 ─── */}
      {hasPick && (
        <div className="px-5 py-4 border-t border-slate-200/60 dark:border-white/5
                        bg-gradient-to-br from-[#E91E63]/8 via-transparent to-transparent
                        dark:from-[#00F0FF]/6">
          <p className="text-xs font-black tracking-[0.25em] uppercase text-slate-700 dark:text-white/80 mb-2">
            🎯 最终结论
          </p>
          <div className="flex items-baseline justify-between gap-3">
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-black tracking-tight text-slate-900 dark:text-white">
                {pickDirection}
              </span>
              {pickOdds && (
                <span className="text-base font-bold text-[#E91E63] dark:text-[#00F0FF]">
                  @{pickOdds}
                </span>
              )}
            </div>
            {confidenceStars != null && confidenceStars > 0 && (
              <div className="flex items-center gap-1">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-white/50">信心</span>
                {[1, 2, 3, 4, 5].map(i => (
                  <Star
                    key={i}
                    size={14}
                    className={i <= confidenceStars ? 'fill-[#FFB800] text-[#FFB800]' : 'text-slate-300 dark:text-white/15'}
                  />
                ))}
              </div>
            )}
          </div>
          {verdictSummary?.coreLogic && (
            <p className="mt-2 text-[12px] text-slate-600 dark:text-white/60 leading-relaxed">
              {verdictSummary.coreLogic}
            </p>
          )}
        </div>
      )}

      {/* ─── ④ 关键风险 ─── */}
      {hasRisk && (
        <div className="px-5 py-4 border-t border-slate-200/60 dark:border-white/5
                        bg-amber-50/60 dark:bg-amber-400/8">
          <div className="flex items-start gap-2.5">
            <AlertTriangle size={14} className="text-amber-600 dark:text-amber-400 flex-shrink-0 mt-0.5" />
            <div className="min-w-0">
              <p className="text-xs font-black tracking-[0.25em] uppercase text-amber-700 dark:text-amber-300 mb-1">
                关键风险
              </p>
              <p className="text-[13px] text-slate-800 dark:text-white/85 leading-relaxed">{keyRisk}</p>
            </div>
          </div>
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
