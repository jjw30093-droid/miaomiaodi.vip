'use client';

import React, { useState } from 'react';
import type { LineupImpact, LineupImpactPlayer, LineupImpactTeam } from '@/types/report';

interface Props {
  lineupImpact: LineupImpact;
  homeTeamName: string;
  awayTeamName: string;
}

/* ─── 位置 Token 颜色映射（只用 Tailwind token，不 hardcode hex） ─── */
const POSITION_STYLE: Record<string, { border: string; text: string }> = {
  GK: { border: 'border-[color:var(--color-primary-gold)]',     text: 'text-[color:var(--color-primary-gold)]' },
  DF: { border: 'border-[color:var(--color-primary-neon)]',     text: 'text-[color:var(--color-primary-neon)]' },
  MF: { border: 'border-[color:var(--color-secondary-magenta)]', text: 'text-[color:var(--color-secondary-magenta)]' },
  FW: { border: 'border-[color:var(--color-accent-gold)]',      text: 'text-[color:var(--color-accent-gold)]' },
};

/* ─── 状态角标 ─── */
const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  injured:   { label: '伤停', cls: 'bg-rose-500/20 text-rose-400 border-rose-500/40' },
  suspended: { label: '停赛', cls: 'bg-amber-500/20 text-amber-400 border-amber-500/40' },
};

/* ─── 水平条形图 ─── */
function HBar({
  score,
  variant,
  dimmed = false,
}: {
  score: number | null;
  variant: 'offense' | 'defense';
  dimmed?: boolean;
}) {
  // null score = no historical data → render a grey N/A placeholder bar
  if (score === null) {
    return (
      <div className="h-1.5 rounded-full bg-slate-200 dark:bg-white/5 overflow-hidden relative">
        <span className="absolute inset-0 flex items-center justify-start pl-1 text-xs font-mono text-slate-400 dark:text-white leading-none select-none">
          N/A
        </span>
      </div>
    );
  }

  const isOffense = variant === 'offense';
  const gradient = isOffense
    ? 'bg-gradient-to-r from-[color:var(--color-primary-neon)]/50 to-[color:var(--color-primary-neon)]'
    : 'bg-gradient-to-r from-[color:var(--color-secondary-magenta)]/50 to-[color:var(--color-secondary-magenta)]';
  const glow = isOffense
    ? 'shadow-[0_0_8px_rgba(0,240,255,0.5)]'
    : 'shadow-[0_0_8px_rgba(255,0,229,0.5)]';

  return (
    <div className={`h-1.5 rounded-full bg-slate-200 dark:bg-white/5 overflow-hidden ${dimmed ? 'opacity-30' : ''}`}>
      <div
        className={`h-full rounded-full ${gradient} ${dimmed ? '' : glow} transition-[width] duration-700`}
        style={{ width: `${Math.min(100, Math.max(0, score)).toFixed(1)}%` }}
      />
    </div>
  );
}

/* ─── 球员行（首发） ─── */
function StarterRow({ p }: { p: LineupImpactPlayer }) {
  const pos = POSITION_STYLE[p.position] ?? POSITION_STYLE.DF;
  return (
    <div className="py-1.5 border-b border-slate-200 dark:border-white/5 last:border-0">
      {/* 位置徽章 + 名字 */}
      <div className="flex items-center gap-1 mb-1 min-w-0">
        <span className={`text-xs font-black font-mono tracking-widest uppercase border px-1.5 py-0.5 rounded shrink-0 ${pos.border} ${pos.text}`}>
          {p.position}
        </span>
        <p className="text-sm font-bold text-slate-900 dark:text-white truncate leading-tight break-words">{p.name}</p>
      </div>
      {/* ATK / DEF 条形图 */}
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-[color:var(--color-primary-neon)] w-7 shrink-0">进攻</span>
          <div className="flex-1"><HBar score={p.offenseScore} variant="offense" /></div>
          <span className="text-xs font-mono text-slate-700 dark:text-white w-6 text-right shrink-0">
            {p.offenseScore !== null ? p.offenseScore : '—'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-[color:var(--color-secondary-magenta)] w-7 shrink-0">防守</span>
          <div className="flex-1"><HBar score={p.defenseScore} variant="defense" /></div>
          <span className="text-xs font-mono text-slate-700 dark:text-white w-6 text-right shrink-0">
            {p.defenseScore !== null ? p.defenseScore : '—'}
          </span>
        </div>
      </div>
    </div>
  );
}

/* ─── 球员行（伤停） ─── */
function AbsenteeRow({ p }: { p: LineupImpactPlayer }) {
  const pos = POSITION_STYLE[p.position] ?? POSITION_STYLE.DF;
  const badge = STATUS_BADGE[p.status];
  return (
    <div className="py-1.5 border-b border-slate-200 dark:border-white/5 last:border-0">
      <div className="flex items-center gap-1 mb-0.5 min-w-0 flex-wrap">
        <span className={`text-xs font-black font-mono tracking-widest uppercase border px-1.5 py-0.5 rounded shrink-0 ${pos.border} ${pos.text}`}>
          {p.position}
        </span>
        <p className="text-sm font-bold text-slate-500 dark:text-white truncate leading-tight flex-1 min-w-0 break-words">{p.name}</p>
        {badge && (
          <span className={`text-xs font-mono px-1.5 py-0.5 rounded border shrink-0 ${badge.cls}`}>{badge.label}</span>
        )}
      </div>
      {p.injuryNote && (
        <p className="text-xs text-slate-700 dark:text-white mb-0.5">{p.injuryNote}</p>
      )}
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-slate-500 dark:text-white w-7 shrink-0">进攻</span>
          <div className="flex-1"><HBar score={p.offenseScore} variant="offense" dimmed /></div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-slate-500 dark:text-white w-7 shrink-0">防守</span>
          <div className="flex-1"><HBar score={p.defenseScore} variant="defense" dimmed /></div>
        </div>
      </div>
    </div>
  );
}

/* ─── 单队面板 ─── */
function TeamPanel({ team }: { team: LineupImpactTeam }) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  return (
    <div className="flex flex-col gap-2">
      {/* 队名 + 计数 pills */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <h4 className="text-sm font-headline font-black italic tracking-wider text-slate-900 dark:text-white uppercase">
          {team.teamName}
        </h4>
        <span className="text-xs font-mono px-1.5 py-0.5 rounded-full bg-[color:var(--color-primary-neon)]/10 border border-[color:var(--color-primary-neon)]/30 text-[color:var(--color-primary-neon)]">
          {team.starters.length}人
        </span>
        {team.absentees.length > 0 && (
          <span className="text-xs font-mono px-1.5 py-0.5 rounded-full bg-rose-100 dark:bg-rose-500/10 border border-rose-300 dark:border-rose-500/30 text-rose-700 dark:text-rose-400">
            缺{team.absentees.length}
          </span>
        )}
      </div>

      {/* 图例 */}
      <div className="flex items-center gap-2 text-xs font-mono text-slate-700 dark:text-white">
        <span className="flex items-center gap-1">
          <span className="inline-block w-4 h-1 rounded-full bg-[color:var(--color-primary-neon)]/60" />
          进攻
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-4 h-1 rounded-full bg-[color:var(--color-secondary-magenta)]/60" />
          防守
        </span>
      </div>

      {/* 首发列表 */}
      <div>
        {team.starters.map((p, i) => (
          <StarterRow key={`${p.name}-${i}`} p={p} />
        ))}
      </div>

      {/* 伤停/停赛区块 */}
      {team.absentees.length > 0 && (
        <div className="mt-1 rounded-lg border-l-2 border-rose-500/40 bg-rose-100 dark:bg-rose-950/20 px-2 py-1.5">
          <button
            onClick={() => setShowAdvanced(v => !v)}
            className="w-full flex items-center justify-between text-xs font-mono text-rose-700 dark:text-rose-400/80 mb-2"
          >
            <span className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" />
              缺阵情况 ({team.absentees.length} 人)
            </span>
            <span>{showAdvanced ? '▲' : '▼'}</span>
          </button>
          {showAdvanced && (
            <div>
              {team.absentees.map((p, i) => (
                <AbsenteeRow key={`${p.name}-${i}`} p={p} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ─── 主组件 ─── */
export default function LineupImpactTable({
  lineupImpact,
  homeTeamName,
  awayTeamName,
}: Props) {
  return (
    <div className="p-5 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <span className="w-2 h-2 rounded-full bg-[color:var(--color-accent-gold)] shadow-[0_0_8px_var(--color-accent-gold)]" />
        <h3 className="text-sm font-black font-mono uppercase tracking-[0.25em] text-slate-900 dark:text-white">
          阵容攻防影响分析
        </h3>
        <span className="text-sm font-mono text-slate-700 dark:text-white ml-auto">进攻 / 防守 贡献</span>
      </div>

      {/* 两队始终并排 */}
      <div className="grid grid-cols-2 gap-x-3">
        <TeamPanel team={{ ...lineupImpact.homeTeam, teamName: homeTeamName }} />
        <div className="col-span-0 hidden" />
        <TeamPanel team={{ ...lineupImpact.awayTeam, teamName: awayTeamName }} />
      </div>
    </div>
  );
}
