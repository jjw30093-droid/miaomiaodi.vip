import { getMatchReport } from '@/lib/fetchReport';
import ContactAdminPanel from '@/components/ContactAdminPanel';
import Link from 'next/link';
import Image from 'next/image';
import { ChevronLeft } from 'lucide-react';

/**
 * WcGuestPreview — 世界杯比赛详情页（游客版）
 * 展示：比赛头部 + beginner_summary 预览摘要 + 联系管理员面板
 * 数据来源：/api/v1/wc/match_payload/{matchId}（GUEST 返回 is_gated=true，含 preview_content/beginner_summary）
 */
export default async function WcGuestPreview({ matchId }: { matchId: string }) {
  // 服务端拉取（无 token → GUEST payload）
  const report = await getMatchReport(matchId);

  const homeTeam = report?.homeTeamName ?? '主队';
  const awayTeam = report?.awayTeamName ?? '客队';
  const homeIcon = (report as any)?.homeIcon as string | null | undefined;
  const awayIcon = (report as any)?.awayIcon as string | null | undefined;
  const matchTime = report?.matchTime
    ? new Date(report.matchTime).toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
        timeZone: 'Asia/Shanghai',
      })
    : '';

  // 预览摘要：beginnerSummary（大白话，游客友好）
  const previewText = report?.beginnerSummary ?? null;

  return (
    <>
      {/* 导航栏 */}
      <header className="sticky top-0 z-40 bg-[var(--header-bg)] backdrop-blur-md border-b border-[var(--header-border)] px-4 py-3 flex items-center gap-3">
        <Link
          href="/"
          className="p-2 -ml-2 text-slate-400 dark:text-white hover:text-[var(--primary-neon)] transition-colors flex-shrink-0 group"
        >
          <ChevronLeft size={22} className="group-hover:-translate-x-0.5 transition-transform" />
        </Link>
        <div className="flex flex-col min-w-0 flex-1">
          <span className="text-xs font-bold tracking-wider text-[var(--primary-neon)] uppercase">
            WORLD CUP 2026 · ANALYSIS
          </span>
          <span className="text-sm font-black text-slate-800 dark:text-white leading-tight">
            世界杯研报
          </span>
        </div>
      </header>

      <div className="max-w-xl mx-auto px-4 py-6 flex flex-col gap-4">
        {/* 比赛头部 */}
        <div className="rounded-2xl border border-zinc-700/40 bg-zinc-900/60 p-5">
          <p className="text-xs text-zinc-400 mb-3 text-center">
            世界杯 · {matchTime ? matchTime + ' (北京时间)' : '赛前'}
          </p>
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1 text-center flex flex-col items-center gap-2">
              {homeIcon ? (
                <Image src={homeIcon} alt={homeTeam} width={48} height={48} unoptimized className="rounded-full" />
              ) : (
                <div className="w-12 h-12 rounded-full bg-zinc-800" />
              )}
              <p className="text-base font-black text-white break-words">{homeTeam}</p>
            </div>
            <div className="text-zinc-500 text-sm font-mono shrink-0">VS</div>
            <div className="flex-1 text-center flex flex-col items-center gap-2">
              {awayIcon ? (
                <Image src={awayIcon} alt={awayTeam} width={48} height={48} unoptimized className="rounded-full" />
              ) : (
                <div className="w-12 h-12 rounded-full bg-zinc-800" />
              )}
              <p className="text-base font-black text-white break-words">{awayTeam}</p>
            </div>
          </div>
        </div>

        {/* 预览摘要 */}
        {previewText && (
          <div className="rounded-2xl border border-zinc-700/40 bg-zinc-900/60 p-5">
            <p className="text-xs font-bold text-[var(--primary-neon)] mb-2 uppercase tracking-wider">
              研报摘要
            </p>
            <p className="text-sm text-zinc-300 leading-relaxed">{previewText}</p>
            {/* 模糊遮罩暗示更多内容 */}
            <div className="mt-3 h-12 bg-gradient-to-b from-transparent to-zinc-900/80 rounded-b-lg flex items-end justify-center pb-2">
              <span className="text-xs text-zinc-500">完整分析需开通账号</span>
            </div>
          </div>
        )}

        {/* 锁定内容提示 */}
        <div className="rounded-xl border border-zinc-700/30 bg-zinc-900/40 p-4">
          <p className="text-xs text-zinc-400 text-center leading-relaxed">
            🔒 完整内容包括：推荐方向 · 市场共识概率 · 算法模型对标 · 预计首发阵容 · 近期表现
          </p>
        </div>

        {/* 联系管理员面板 */}
        <ContactAdminPanel />

        {/* 已有账号 */}
        <div className="text-center">
          <Link
            href={`/login?next=${encodeURIComponent('/report/' + matchId)}`}
            className="text-xs text-zinc-500 hover:text-[var(--primary-neon)] transition-colors"
          >
            已有账号？登录查看完整研报 →
          </Link>
        </div>
      </div>
    </>
  );
}
