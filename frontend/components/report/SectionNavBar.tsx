'use client';

interface Props {
  /** 是否赛后（决定是否显示 #review 锚点） */
  hasReview?: boolean;
}

/**
 * 章节锚点导航条 — 不 sticky，仅作为决策摘要区与数据论据区之间的桥梁。
 * 点击后 smooth scroll 到对应章节（依赖 globals.css 的 scroll-margin-top 避免被 header 遮挡）。
 */
export default function SectionNavBar({ hasReview }: Props) {
  const sections: { id: string; icon: string; label: string }[] = [
    { id: 'data',    icon: '📊', label: '数据' },
    { id: 'lineup',  icon: '👥', label: '阵容' },
    { id: 'tactics', icon: '📝', label: '深度' },
  ];
  if (hasReview) sections.push({ id: 'review', icon: '🏁', label: '赛后' });

  const handleClick = (e: React.MouseEvent<HTMLAnchorElement>, id: string) => {
    e.preventDefault();
    const target = document.getElementById(id);
    if (!target) return;
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <nav className="grid gap-2 px-1 py-1 rounded-2xl
                    bg-white/85 backdrop-blur dark:bg-white/[0.03]
                    border border-slate-900/10 dark:border-white/8
                    shadow-[0_2px_8px_rgba(15,23,42,0.04)] dark:shadow-none"
         style={{ gridTemplateColumns: `repeat(${sections.length}, minmax(0, 1fr))` }}>
      {sections.map(s => (
        <a
          key={s.id}
          href={`#${s.id}`}
          onClick={(e) => handleClick(e, s.id)}
          className="flex flex-col items-center justify-center gap-0.5 py-2 rounded-xl
                     hover:bg-slate-100/80 dark:hover:bg-white/[0.06]
                     active:scale-95 transition-all"
        >
          <span className="text-base leading-none">{s.icon}</span>
          <span className="text-xs font-black tracking-widest uppercase text-slate-700 dark:text-white/70">{s.label}</span>
        </a>
      ))}
    </nav>
  );
}
