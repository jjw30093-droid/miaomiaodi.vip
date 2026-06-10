/**
 * MatchCardGated — 未登录访客（GUEST 档）专用比赛卡片
 *
 * 仅显示：联赛 + 时间（顶部） + 队徽 + 队名 + VS（主体）
 * 不显示：概率、分析摘要、UPCOMING/ARCHIVE 标签、置顶/免费角标
 * 点击行为：跳转 /login?next=/report/<matchId>
 *
 * 渲染条件：后端返回 display_category === 'GATED' 时
 * （由 backend/report_router.py:get_latest_reports() 三档脱敏决定）
 */
'use client';
import { useRouter } from 'next/navigation';
import Image from 'next/image';
import { translateLeague } from '@/lib/leagueNames';

interface Props {
  matchId: string;
  homeName: string;
  homeIcon: string | null;
  awayName: string;
  awayIcon: string | null;
  time: string;       // ISO UTC string
  league: string;
}

export default function MatchCardGated({
  matchId,
  homeName,
  homeIcon,
  awayName,
  awayIcon,
  time,
  league,
}: Props) {
  const router = useRouter();
  const displayTime = time
    ? new Date(time).toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
    : '';

  // 世界杯场次：直接进详情页（展示预览 + 联系管理员），不跳登录
  const handleClick = () => {
    if (matchId.startsWith('wc_')) {
      router.push('/report/' + matchId);
    } else {
      router.push('/login?next=' + encodeURIComponent('/report/' + matchId));
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className="w-full bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl p-4 active:scale-[0.99] transition-transform text-left"
    >
      {/* 顶部：联赛 + 时间 */}
      <div className="flex items-center justify-between mb-3 text-xs text-zinc-500 dark:text-zinc-400">
        <span className="truncate max-w-[60%]">{translateLeague(league)}</span>
        <span className="font-mono">{displayTime}</span>
      </div>

      {/* 主体：队徽 + 队名 + VS */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex flex-col items-center flex-1 min-w-0">
          {homeIcon ? (
            <Image
              src={homeIcon}
              alt={homeName}
              width={48}
              height={48}
              className="rounded-full object-contain"
              unoptimized
            />
          ) : (
            <div className="w-12 h-12 rounded-full bg-zinc-100 dark:bg-zinc-800" />
          )}
          <div className="mt-2 text-sm font-bold text-zinc-900 dark:text-white truncate w-full text-center">
            {homeName}
          </div>
        </div>

        <div className="text-zinc-400 dark:text-zinc-600 text-xs font-mono">
          VS
        </div>

        <div className="flex flex-col items-center flex-1 min-w-0">
          {awayIcon ? (
            <Image
              src={awayIcon}
              alt={awayName}
              width={48}
              height={48}
              className="rounded-full object-contain"
              unoptimized
            />
          ) : (
            <div className="w-12 h-12 rounded-full bg-zinc-100 dark:bg-zinc-800" />
          )}
          <div className="mt-2 text-sm font-bold text-zinc-900 dark:text-white truncate w-full text-center">
            {awayName}
          </div>
        </div>
      </div>
    </button>
  );
}
