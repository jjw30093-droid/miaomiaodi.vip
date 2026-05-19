'use client';

import { useState, ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';

interface Props {
  title:        string;
  defaultOpen?: boolean;
  /** 副标题（小字，hint 用），可选 */
  hint?:        string;
  children:     ReactNode;
}

/**
 * 通用折叠卡 — 标题点击展开/收起。
 * 默认折叠（defaultOpen=false），用于"次级专业内容"避免过早暴露给新手。
 */
export default function CollapsibleSection({ title, hint, defaultOpen = false, children }: Props) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-2xl overflow-hidden
                    bg-white/85 backdrop-blur-xl dark:bg-[var(--panel-bg-strong)]
                    border border-slate-900/10 dark:border-[var(--panel-border-strong)]
                    shadow-[0_2px_8px_rgba(15,23,42,0.04)] dark:shadow-[var(--panel-shadow-strong)]">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full px-5 py-3.5 flex items-center justify-between gap-2
                   text-left transition-colors
                   hover:bg-slate-50/60 dark:hover:bg-white/[0.03]"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <ChevronRight
            size={16}
            className={`text-slate-500 dark:text-white/40 transition-transform duration-200 flex-shrink-0
                       ${open ? 'rotate-90' : ''}`}
          />
          <span className="text-sm font-black text-slate-900 dark:text-white truncate">{title}</span>
          {hint && <span className="text-xs text-slate-500 dark:text-white/40 truncate">· {hint}</span>}
        </div>
        <span className="text-xs font-bold uppercase tracking-widest
                         text-slate-500 dark:text-white/40 flex-shrink-0">
          {open ? '收起' : '展开'}
        </span>
      </button>
      {open && (
        <div className="border-t border-slate-200/60 dark:border-white/5 px-5 py-4">
          {children}
        </div>
      )}
    </div>
  );
}
