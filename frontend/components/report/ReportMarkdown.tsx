'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useSession } from 'next-auth/react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { chunkMarkdown } from '@/lib/markdownChunker';

// ─────────────────────────────────────────────────────────────
// 1. Custom Markdown Renderers
// ─────────────────────────────────────────────────────────────
const MD_COMPONENTS: Record<string, React.FC<any>> = {
  h1: ({ children }) => (
    <h1 style={{ fontStyle: 'normal' }} className="font-headline tracking-tight text-2xl font-black text-slate-950 dark:text-white mt-4 mb-6 leading-tight">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 style={{ fontStyle: 'normal' }} className="font-headline tracking-tight text-xl font-black text-slate-950 dark:text-white mt-9 mb-4 pl-3 border-l-2 border-slate-900 dark:border-white leading-snug">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 style={{ fontStyle: 'normal' }} className="font-headline text-lg font-bold text-slate-950 dark:text-white mt-6 mb-2.5">
      {children}
    </h3>
  ),
  p: ({ children }) => (
    <p className="text-[18px] text-slate-950 dark:text-white leading-[1.85] mb-7 break-words">{children}</p>
  ),
  strong: ({ children }) => (
    <strong className="font-bold text-slate-950 dark:text-white">{children}</strong>
  ),
  em: ({ children }) => (
    <em className="italic text-slate-950 dark:text-white">{children}</em>
  ),
  hr: () => <hr className="my-4 border-slate-200 dark:border-white/10" />,

  blockquote: ({ children }) => (
    <blockquote className="my-6 px-4 py-3 bg-slate-50 dark:bg-slate-900 rounded-r-xl border-l-2 border-slate-900 dark:border-white text-slate-950 dark:text-white text-[18px] leading-[1.85] not-italic">
      {children}
    </blockquote>
  ),

  table: ({ children }) => (
    <div className="overflow-x-auto w-full my-6 rounded-xl border border-slate-200 dark:border-white/10 -mx-1">
      <table className="w-full text-[16px] border-collapse min-w-[280px]">
        {children}
      </table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="bg-slate-100 dark:bg-slate-900 text-slate-950 dark:text-white">{children}</thead>
  ),
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => (
    <tr className="border-b border-slate-100 dark:border-white/15 even:bg-slate-50 dark:even:bg-slate-900">
      {children}
    </tr>
  ),
  th: ({ children }) => (
    <th className="px-3 py-2.5 text-left font-bold text-[15px] tracking-wide text-slate-950 dark:text-white whitespace-nowrap border-b border-slate-200 dark:border-white/15">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="px-3 py-3 text-slate-950 dark:text-white align-middle text-[16px] font-medium tabular-nums">{children}</td>
  ),

  ul: ({ children }) => (
    <ul className="my-4 space-y-2 pl-0 list-none">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="my-4 space-y-2 pl-5 list-decimal">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="flex items-start gap-2.5 text-[18px] text-slate-950 dark:text-white leading-[1.85] break-words">
      <span className="mt-2.5 w-1.5 h-1.5 rounded-full bg-slate-900 dark:bg-white shrink-0" />
      <span>{children}</span>
    </li>
  ),

  // v10+: `inline` prop removed. Block code: pre wraps code. Inline code: no pre wrapper.
  pre: ({ children }: any) => (
    <pre className="my-4 p-4 bg-slate-50 dark:bg-slate-900 rounded-xl overflow-x-auto text-[14px] font-mono text-slate-950 dark:text-white leading-[1.7]">
      {children}
    </pre>
  ),
  code: ({ children, className }: any) => {
    const isBlock = className?.startsWith('language-');
    if (isBlock) {
      return <code className={className}>{children}</code>;
    }
    return (
      <code className="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-900 rounded text-[14px] font-mono text-slate-950 dark:text-white">
        {children}
      </code>
    );
  },
};

// ─────────────────────────────────────────────────────────────
// 2. Inner block — pure renderer, no state
// ─────────────────────────────────────────────────────────────
function MarkdownBlock({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={MD_COMPONENTS}
    >
      {content}
    </ReactMarkdown>
  );
}

// ─────────────────────────────────────────────────────────────
// 3. VIP 遮罩
// ─────────────────────────────────────────────────────────────
function VipPaywall({
  isLoggedIn,
  onUpgradeClick,
  callbackUrl,
}: {
  isLoggedIn: boolean;
  onUpgradeClick?: () => void;
  callbackUrl: string;
}) {
  return (
    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 px-6 text-center pointer-events-auto">
      {isLoggedIn ? (
        <button
          onClick={onUpgradeClick}
          className="bg-red-500 hover:bg-red-600 active:scale-95 text-white font-black px-7 py-4 rounded-2xl text-sm shadow-xl shadow-red-500/25 transition-all"
        >
          💎 升级 Pro 查看核心模型推演
        </button>
      ) : (
        <Link
          href={`/login?callbackUrl=${encodeURIComponent(callbackUrl)}`}
          className="bg-red-500 hover:bg-red-600 active:scale-95 text-white font-black px-7 py-4 rounded-2xl text-sm shadow-xl shadow-red-500/25 transition-all inline-block"
        >
          🔒 登录后查看核心模型推演
        </Link>
      )}
      <p className="text-xs text-slate-500 dark:text-white mt-1">
        包含：市场交易价值 · 战术损耗评估 · 模型最终结论
      </p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// 4. 主导出组件
// ─────────────────────────────────────────────────────────────
interface ReportMarkdownProps {
  content: string;
  onUpgradeClick?: () => void;
}

export default function ReportMarkdown({
  content,
  onUpgradeClick,
}: ReportMarkdownProps) {
  const { data: session } = useSession();
  const pathname = usePathname();

  const isVip = process.env.NEXT_PUBLIC_ENABLE_VIP_DISPLAY === 'true'
    ? !!(
        session &&
        (
          (session.user as any)?.role === 'admin' ||
          (session.user as any)?.role === 'vip' ||
          (session.user as any)?.vip_level === 'MONTHLY' ||
          (session.user as any)?.vip_level === 'YEARLY'
        )
      )
    : !!session;

  const { publicMd, vipMd, hasVip } = chunkMarkdown(content);

  return (
    <div className="bg-white dark:bg-transparent rounded-xl overflow-hidden text-slate-950 dark:text-white font-body">

      {/* ── Public 内容 ── */}
      {publicMd.trim() && (
        <div className="px-4 pt-2 pb-4">
          <MarkdownBlock content={publicMd} />
        </div>
      )}

      {/* ── VIP 内容 ── */}
      {hasVip && (
        <>
          <div className="mx-4 my-6 flex items-center gap-3">
            <div className="flex-1 h-px bg-gradient-to-r from-transparent via-slate-300/60 dark:via-red-300/40 to-transparent" />
            {!isVip && (
              <span className="font-headline text-xs font-black text-[color:var(--primary-neon)] dark:text-red-500/70 tracking-wide shrink-0 px-2 py-0.5 border border-[color:var(--primary-neon)]/40 dark:border-red-300/40 rounded-full">
                会员专享
              </span>
            )}
            <div className="flex-1 h-px bg-gradient-to-r from-transparent via-slate-300/60 dark:via-red-300/40 to-transparent" />
          </div>

          <div className="relative">
            <div
              className="px-4 pb-5"
              style={
                !isVip
                  ? {
                      filter: 'blur(5px)',
                      userSelect: 'none',
                      WebkitUserSelect: 'none',
                      pointerEvents: 'none',
                    }
                  : undefined
              }
              aria-hidden={!isVip || undefined}
            >
              <MarkdownBlock content={vipMd} />
            </div>

            {!isVip && (
              <VipPaywall
                isLoggedIn={!!session}
                onUpgradeClick={onUpgradeClick}
                callbackUrl={pathname}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
