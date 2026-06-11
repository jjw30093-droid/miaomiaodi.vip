'use client';

import { ReactNode, useEffect, useRef, useState } from 'react';
import { Sparkles, Microscope } from 'lucide-react';

/**
 * Client-side Tab switcher between Beginner ("新手版") and Pro ("专业版").
 *
 * Behaviour
 * ─────────
 * - 默认 Tab：新手版（抖音引流场景）
 * - 用户选择持久化到 localStorage（key: `report-view`）
 * - 切换不重新请求 API；纯前端 display 切换
 * - 切换后 smooth scroll 到 Tab 顶部
 * - SSR 默认渲染新手版；客户端 hydrate 后根据 localStorage 切换
 */
export default function ReportTabSwitch({
  beginner,
  pro,
}: {
  beginner: ReactNode;
  pro: ReactNode;
}) {
  const [active, setActive] = useState<'beginner' | 'pro'>('pro');
  const anchorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      const saved = localStorage.getItem('report-view');
      if (saved === 'pro' || saved === 'beginner') setActive(saved);
    } catch {}
  }, []);

  const switchTo = (next: 'beginner' | 'pro') => {
    setActive(next);
    try { localStorage.setItem('report-view', next); } catch {}
    requestAnimationFrame(() => {
      anchorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  };

  // expose imperative switch via window for inner CTA buttons
  useEffect(() => {
    (window as any).__switchReportView = switchTo;
    return () => { delete (window as any).__switchReportView; };
  }, []);

  const baseTab =
    'flex items-center justify-center gap-1.5 flex-1 py-2 px-3 rounded-full text-xs font-black tracking-widest transition-all duration-200';
  const activeTab =
    'bg-[#E91E63] text-white shadow-sm dark:bg-primary-neon dark:text-[#06080C]';
  const inactiveTab =
    'text-slate-600 dark:text-white/60 hover:text-slate-900 dark:hover:text-white';

  return (
    <>
      <div ref={anchorRef} className="px-4 pt-4 max-w-2xl mx-auto">
        <div className="flex items-center gap-1 p-1 rounded-full
          bg-white/85 backdrop-blur border border-slate-900/10 shadow-[0_2px_8px_rgba(15,23,42,0.06)]
          dark:bg-white/[0.04] dark:border-white/10 dark:shadow-none">
          <button
            type="button"
            onClick={() => switchTo('beginner')}
            className={`${baseTab} ${active === 'beginner' ? activeTab : inactiveTab}`}
          >
            <Sparkles size={12} />
            <span>新手版</span>
          </button>
          <button
            type="button"
            onClick={() => switchTo('pro')}
            className={`${baseTab} ${active === 'pro' ? activeTab : inactiveTab}`}
          >
            <Microscope size={12} />
            <span>专业版</span>
          </button>
        </div>
      </div>

      <div className={active === 'beginner' ? '' : 'hidden'}>{beginner}</div>
      <div className={active === 'pro' ? '' : 'hidden'}>{pro}</div>
    </>
  );
}

/**
 * Helper for any in-content CTA button to switch tabs.
 * Usage: `<button onClick={switchToProTab}>切到专业版</button>`
 */
export function switchToProTab() {
  if (typeof window !== 'undefined' && (window as any).__switchReportView) {
    (window as any).__switchReportView('pro');
  }
}
