'use client';

import type { BestRecentStat } from '@/types/report';

interface Props {
  stat?: BestRecentStat | null;
}

/**
 * 新手版战绩卡 — 展示 4 窗口 × 2 类型 = 8 候选中命中率最高的组合。
 *
 * 渲染规则：
 *   - stat == null  → 整个组件返回 null（页面这块直接消失）
 *   - 标题：📊 近{N}场{label}推荐表现
 *   - 数据行：{wins} 中 {total - wins} 负 · 命中率 {hitRate}%
 *   - emoji 序列：✅ 命中 / ❌ 未中（最近的在左）
 *   - 合规小字：模型历史，不代表未来
 */
export default function RecentStatCard({ stat }: Props) {
  if (!stat) return null;

  const losses = stat.total - stat.wins;

  return (
    <section className="bg-white/85 backdrop-blur-xl dark:bg-[var(--panel-bg-strong)]
                        border border-slate-900/10 dark:border-[var(--panel-border-strong)]
                        rounded-2xl p-5">
      {/* 标题 */}
      <p className="text-xs font-black tracking-[0.25em] uppercase text-slate-700 dark:text-white/80 mb-3">
        📊 近{stat.total}场{stat.label}推荐表现
      </p>

      {/* 数据行 */}
      <p className="text-[15px] font-bold text-slate-900 dark:text-white mb-3">
        <span className="text-emerald-600 dark:text-emerald-400 tabular-nums">{stat.wins}</span>
        <span className="text-slate-500 dark:text-white/50"> 中 </span>
        <span className="text-rose-600 dark:text-rose-400 tabular-nums">{losses}</span>
        <span className="text-slate-500 dark:text-white/50"> 负 · 命中率 </span>
        <span className="text-emerald-600 dark:text-emerald-400 tabular-nums">
          {stat.hitRate.toFixed(1)}%
        </span>
      </p>

      {/* emoji 序列（最近的在左） */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {stat.emojiSequence.map((result, i) => (
          <span key={i} className="text-[18px] leading-none">
            {result === 'hit' ? '✅' : '❌'}
          </span>
        ))}
      </div>

      {/* 合规小字 */}
      <p className="text-xs text-slate-500 dark:text-white/40 leading-relaxed">
        以上为模型历史表现，不代表未来结果。数据分析仅供参考，不构成投注建议。
      </p>
    </section>
  );
}
