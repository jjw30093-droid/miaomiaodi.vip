'use client';

import { ReactNode, useEffect, useRef, useState } from 'react';

/**
 * Client-side Tab switcher between concise and full report views.
 *
 * Behaviour
 * ─────────
 * - 默认 Tab：专业版（付费用户默认阅读完整研报）
 * - 用户选择持久化到 localStorage（key: `report-view`）
 * - 切换不重新请求 API；纯前端 display 切换
 * - 切换后 smooth scroll 到 Tab 顶部
 * - SSR 默认渲染专业版；客户端 hydrate 后根据 localStorage 切换
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
    'flex items-center justify-center flex-1 py-2.5 px-3 rounded-md text-[15px] font-bold transition-colors';
  const activeTab =
    'bg-slate-900 text-white dark:bg-white dark:text-slate-950';
  const inactiveTab =
    'text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800';

  return (
    <>
      <div ref={anchorRef} className="px-4 pt-3 max-w-2xl mx-auto">
        <div className="flex items-center gap-1 p-1 rounded-lg
          bg-white border border-slate-200 shadow-sm
          dark:bg-slate-900 dark:border-slate-700">
          <button
            type="button"
            onClick={() => switchTo('beginner')}
            className={`${baseTab} ${active === 'beginner' ? activeTab : inactiveTab}`}
          >
            <span>简明版</span>
          </button>
          <button
            type="button"
            onClick={() => switchTo('pro')}
            className={`${baseTab} ${active === 'pro' ? activeTab : inactiveTab}`}
          >
            <span>完整研报</span>
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
