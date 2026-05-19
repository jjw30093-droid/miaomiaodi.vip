'use client';

interface Props {
  text?: string | null;
}

/**
 * 图表下方的轻量"模型解读"行 — 一句话、italic、低饱和度，不抢图。
 * text 为空时整行不渲染（graceful degrade）。
 */
export default function InsightLine({ text }: Props) {
  if (!text || !text.trim()) return null;
  return (
    <div className="mt-2 px-3 py-2 rounded-lg
                    bg-slate-100/70 dark:bg-white/[0.04]
                    border border-slate-200/70 dark:border-white/8
                    text-[13px] italic text-slate-700 dark:text-white/70 leading-relaxed">
      💡 {text}
    </div>
  );
}
