import React from 'react';
import { TrendingUp } from 'lucide-react';
import { PostMatchShots } from '@/types/report';

/**
 * PostMatchCompareCard (D1 — 赛前预测 vs 赛后实际)
 *
 * 对齐 Vite MatchDetails.tsx:1071–1191 的设计意图：
 *   在赛后区最顶部渲染一条"赛前三档概率 + 赛后真实比分 + npxG 对比"卡片，
 *   让 VIP 用户一眼看到模型是否命中。
 *
 * 仅在 matchStatus === 'finished' 且概率齐全时显示。父组件已做 gating。
 *
 * 浅色模式对比度策略：
 *   - `text-white` 比分字样在浅色渲染 1:1 透明 → 改 `text-gray-900 dark:text-white`
 *   - `bg-black/5` 块底在白底玻璃上不可见 → 改 `bg-gray-100 dark:bg-white/5`
 */

interface Props {
  homeProb: number | null;
  drawProb: number | null;
  awayProb: number | null;
  homeTeamName: string;
  awayTeamName: string;
  postMatchShots?: PostMatchShots | null;
}

export default function PostMatchCompareCard({
  homeProb, drawProb, awayProb,
  homeTeamName, awayTeamName,
  postMatchShots,
}: Props) {
  if (homeProb == null || awayProb == null) return null;
  const d = drawProb ?? Math.max(0, Math.round(100 - homeProb - awayProb));

  // 计算赛后总 xG（由 postMatchShots 派生）
  const homeXg = postMatchShots?.homeTeam?.npxg ?? null;
  const awayXg = postMatchShots?.awayTeam?.npxg ?? null;
  const hasShots = homeXg != null && awayXg != null;

  // 真实比分从 shots 派生（Goal count）
  const homeGoals = postMatchShots?.homeTeam?.shots?.filter(s => s.outcome === 'Goal').length ?? null;
  const awayGoals = postMatchShots?.awayTeam?.shots?.filter(s => s.outcome === 'Goal').length ?? null;
  const hasScore  = homeGoals != null && awayGoals != null;

  // 命中判定：若比分确定，取最大概率方向与实际结果比
  let hit: 'correct' | 'wrong' | 'unknown' = 'unknown';
  if (hasScore) {
    const actual = homeGoals! > awayGoals! ? 'home' : awayGoals! > homeGoals! ? 'away' : 'draw';
    const pick = homeProb >= awayProb && homeProb >= d ? 'home'
               : awayProb >= d ? 'away' : 'draw';
    hit = pick === actual ? 'correct' : 'wrong';
  }

  const hitBadge = hit === 'correct'
    ? { text: '✓ 模型命中', cls: 'bg-emerald-50 dark:bg-emerald-500/10 border-emerald-400/40 text-emerald-700 dark:text-emerald-400' }
    : hit === 'wrong'
      ? { text: '✗ 模型偏离', cls: 'bg-rose-50 dark:bg-rose-500/10 border-rose-400/40 text-rose-700 dark:text-rose-400' }
      : null;

  return (
    <div className="glass-panel border border-border-subtle rounded-2xl p-5 overflow-hidden relative">
      {/* 光晕 */}
      <div className="absolute -top-10 right-0 w-32 h-32 rounded-full blur-3xl bg-yellow-400/10 pointer-events-none" />

      <div className="flex items-center justify-between mb-4 relative z-10">
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 shadow-[0_0_6px_#FACC15]" />
          <span className="text-sm font-black tracking-[0.3em] uppercase text-gray-800 dark:text-white flex items-center gap-1.5">
            <TrendingUp size={12} />
            赛前预测 vs 赛后实际
          </span>
        </div>
        {hitBadge && (
          <span className={`text-xs font-black px-2 py-0.5 rounded-full border ${hitBadge.cls}`}>
            {hitBadge.text}
          </span>
        )}
      </div>

      {/* 赛前三档概率 */}
      <div className="grid grid-cols-3 gap-2 mb-4 relative z-10">
        <div className="flex flex-col items-center bg-gray-100 dark:bg-white/5 rounded-xl p-3">
          <span className="text-xs text-gray-700 dark:text-white uppercase mb-1 tracking-widest font-bold">主胜</span>
          <span className="text-2xl font-black text-[color:var(--prob-home)] dark:text-[#00F0FF]">
            {homeProb.toFixed(1)}<span className="text-xs font-bold text-slate-600 dark:text-white">%</span>
          </span>
        </div>
        <div className="flex flex-col items-center bg-gray-100 dark:bg-white/5 rounded-xl p-3">
          <span className="text-xs text-gray-700 dark:text-white uppercase mb-1 tracking-widest font-bold">平局</span>
          <span className="text-2xl font-black text-slate-800 dark:text-white">
            {d.toFixed(1)}<span className="text-xs font-bold text-slate-600 dark:text-white">%</span>
          </span>
        </div>
        <div className="flex flex-col items-center bg-gray-100 dark:bg-white/5 rounded-xl p-3">
          <span className="text-xs text-gray-700 dark:text-white uppercase mb-1 tracking-widest font-bold">客胜</span>
          <span className="text-2xl font-black text-[color:var(--prob-away)] dark:text-[#FF00E5]">
            {awayProb.toFixed(1)}<span className="text-xs font-bold text-slate-600 dark:text-white">%</span>
          </span>
        </div>
      </div>

      {/* 赛后实际比分 + xG */}
      {(hasScore || hasShots) && (
        <div className="relative z-10 flex items-center justify-between gap-3 bg-gray-100 dark:bg-white/5 rounded-xl p-3">
          <div className="flex flex-col items-center flex-1 min-w-0">
            <span className="text-xs text-gray-700 dark:text-white uppercase tracking-widest mb-1 truncate w-full text-center font-bold">
              {homeTeamName}
            </span>
            <span className="text-2xl font-black font-mono text-[color:var(--primary-neon)] dark:text-[#00F0FF]">
              {hasScore ? homeGoals : '—'}
            </span>
            {hasShots && (
              <span className="text-xs font-mono text-gray-700 dark:text-white mt-0.5">
                xG {homeXg!.toFixed(2)}
              </span>
            )}
          </div>
          <span className="text-slate-700 dark:text-white text-xl font-black">:</span>
          <div className="flex flex-col items-center flex-1 min-w-0">
            <span className="text-xs text-gray-700 dark:text-white uppercase tracking-widest mb-1 truncate w-full text-center font-bold">
              {awayTeamName}
            </span>
            <span className="text-2xl font-black font-mono text-[color:var(--secondary-magenta)] dark:text-[#FF00E5]">
              {hasScore ? awayGoals : '—'}
            </span>
            {hasShots && (
              <span className="text-xs font-mono text-gray-700 dark:text-white mt-0.5">
                xG {awayXg!.toFixed(2)}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
