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
//    - h2:         红色左边框
//    - h3:         深灰小标题
//    - blockquote: 淡灰背景卡片
//    - table:      overflow-x-auto 包裹 + 灰色表头
//    - li:         红色圆点
// ─────────────────────────────────────────────────────────────
const MD_COMPONENTS: Record<string, React.FC<any>> = {
  h1: ({ children }) => (
    <h1 className="font-headline italic tracking-tighter text-2xl font-black text-gray-900 mt-4 mb-6 leading-tight">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="font-headline italic tracking-tighter flex items-start gap-2 text-lg font-black text-gray-900 mt-10 mb-4 pl-3 border-l-[3px] border-red-500 leading-tight">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="font-headline italic tracking-tight text-[15px] font-bold text-gray-800 mt-6 mb-3">
      {children}
    </h3>
  ),
  p: ({ children }) => (
    <p className="text-[14px] text-gray-700 leading-[1.75] mb-5 break-words">{children}</p>
  ),
  strong: ({ children }) => (
    <strong className="font-black text-gray-900 bg-red-50 px-0.5 rounded">{children}</strong>
  ),
  em: ({ children }) => (
    <em className="italic text-gray-600">{children}</em>
  ),
  hr: () => <hr className="my-8 border-gray-200" />,

  // Blockquote: 淡灰背景 + 红色左边框，对齐主色
  blockquote: ({ children }) => (
    <blockquote className="my-5 px-5 py-4 bg-gray-50 rounded-r-2xl border-l-[3px] border-red-400/60 text-gray-600 text-[13px] leading-[1.7] not-italic">
      {children}
    </blockquote>
  ),

  // Table: 外层 overflow-x-auto 防止手机端撑爆，-mx-1 贴到白卡边缘
  table: ({ children }) => (
    <div className="overflow-x-auto w-full my-6 rounded-xl border border-gray-200 shadow-sm -mx-1">
      <table className="w-full text-[12px] border-collapse min-w-[280px]">
        {children}
      </table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="bg-gray-50 text-gray-500">{children}</thead>
  ),
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => (
    <tr className="border-b border-gray-100 even:bg-gray-50/50 hover:bg-red-50/30 transition-colors">
      {children}
    </tr>
  ),
  th: ({ children }) => (
    <th className="font-headline px-3 py-2 text-left font-black text-[10px] uppercase tracking-[0.15em] text-gray-500 whitespace-nowrap border-b border-gray-200">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="px-3 py-2.5 text-gray-700 align-middle text-[12px]">{children}</td>
  ),

  // List
  ul: ({ children }) => (
    <ul className="my-4 space-y-2 pl-0 list-none">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="my-4 space-y-2 pl-5 list-decimal">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="flex items-start gap-2.5 text-[14px] text-gray-700 leading-[1.7] break-words">
      <span className="mt-2 w-1.5 h-1.5 rounded-full bg-red-500 shrink-0 shadow-[0_0_6px_rgba(239,68,68,0.4)]" />
      <span>{children}</span>
    </li>
  ),

  // Inline code / code block
  code: ({ inline, children }: any) =>
    inline ? (
      <code className="px-1.5 py-0.5 bg-red-50 rounded text-[12px] font-mono text-red-600">
        {children}
      </code>
    ) : (
      <pre className="my-4 p-4 bg-gray-50 rounded-xl overflow-x-auto text-[12px] font-mono text-gray-700 leading-[1.6]">
        <code>{children}</code>
      </pre>
    ),
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
      <p className="text-xs text-gray-400 mt-1">
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
  /** 点击升级按钮的回调（可选：弹出 CDK 兑换弹窗等） */
  onUpgradeClick?: () => void;
}

export default function ReportMarkdown({
  content,
  onUpgradeClick,
}: ReportMarkdownProps) {
  const { data: session } = useSession();
  const pathname = usePathname();

  const isVip = !!(
    session &&
    (
      (session.user as any)?.role === 'admin' ||
      (session.user as any)?.role === 'vip' ||
      (session.user as any)?.vip_level === 'MONTHLY' ||
      (session.user as any)?.vip_level === 'YEARLY'
    )
  );

  const { publicMd, vipMd, hasVip } = chunkMarkdown(content);

  return (
    <div className="bg-[#FAFAF8] rounded-xl overflow-hidden text-gray-900 font-body">

      {/* ── Public 内容 ── */}
      <div className="px-4 pt-2 pb-4">
        <MarkdownBlock content={publicMd} />
      </div>

      {/* ── VIP 内容 ── */}
      {hasVip && (
        <>
          {/* 分割线：红色渐变 + 胶囊徽章 */}
          <div className="mx-4 my-6 flex items-center gap-3">
            <div className="flex-1 h-px bg-gradient-to-r from-transparent via-red-300/40 to-transparent" />
            {!isVip && (
              <span className="font-headline italic text-[10px] font-black text-red-500/70 uppercase tracking-[0.2em] shrink-0 px-2 py-0.5 border border-red-300/40 rounded-full">
                Pro Only
              </span>
            )}
            <div className="flex-1 h-px bg-gradient-to-r from-transparent via-red-300/40 to-transparent" />
          </div>

          {/* VIP 区块容器 */}
          <div className="relative">
            {/* 内容：非 VIP 时模糊 */}
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

            {/* 遮罩按钮 */}
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
