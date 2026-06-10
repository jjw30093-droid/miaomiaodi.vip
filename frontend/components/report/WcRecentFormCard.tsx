'use client';

/**
 * WcRecentFormCard
 * 世界杯「近期表现」卡片
 * 数据来自 wc_home_recent / wc_away_recent（cc站）
 * 各取最近 5 场，条件渲染：数据为空则不渲染
 */

interface RecentFixture {
  match_label?: string;
  starting_at?: string;
  state_short_name?: string;
  stage?: string | null;
  result_info?: string | null;
  [key: string]: any;
}

interface Props {
  wcHomeRecent: RecentFixture[] | null | undefined;
  wcAwayRecent: RecentFixture[] | null | undefined;
  homeTeam: string;
  awayTeam: string;
}

function formatDate(dt?: string): string {
  if (!dt) return '—';
  try {
    return new Date(dt).toLocaleDateString('zh-CN', {
      month: '2-digit', day: '2-digit', year: '2-digit',
    });
  } catch {
    return dt.slice(0, 10);
  }
}

// 简化比赛结果 info 文字
function shortResult(info?: string | null, label?: string, side?: 'home' | 'away'): { text: string; color: string } {
  if (!info && !label) return { text: '—', color: 'text-zinc-500' };
  const i = (info || '').toLowerCase();
  // 尝试从 label 或 result_info 判断胜平负
  if (i.includes('won') || i.includes('win')) return { text: '胜', color: 'text-green-400' };
  if (i.includes('draw') || i.includes('tied')) return { text: '平', color: 'text-yellow-400' };
  if (i.includes('lost') || i.includes('loss')) return { text: '负', color: 'text-red-400' };
  return { text: '—', color: 'text-zinc-500' };
}

function RecentList({ matches, teamName }: { matches: RecentFixture[]; teamName: string }) {
  if (matches.length === 0) return (
    <div>
      <p className="text-xs font-bold text-zinc-300 mb-1">{teamName}</p>
      <p className="text-xs text-zinc-500">暂无近期赛事数据</p>
    </div>
  );

  // 判断是否是历史大赛（2022 及更早）
  const newestDate = matches[0]?.starting_at || '';
  const isHistorical = newestDate < '2024-01-01';

  return (
    <div className="flex-1 min-w-0">
      <p className="text-xs font-bold text-zinc-300 mb-1">{teamName}</p>
      {isHistorical && (
        <p className="text-[10px] text-zinc-500 mb-1.5">
          ※ 以下为历史大赛战绩（本届未参加常规预选赛）
        </p>
      )}
      <div className="space-y-0.5">
        {matches.slice(0, 5).map((m, i) => {
          const res = shortResult(m.result_info, m.match_label);
          return (
            <div key={i} className="flex items-center gap-2 text-xs">
              <span className="text-zinc-500 font-mono w-14 shrink-0">
                {formatDate(m.starting_at)}
              </span>
              <span className={`w-4 shrink-0 font-bold ${res.color}`}>{res.text}</span>
              <span className="text-zinc-400 truncate">{m.match_label || '—'}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function WcRecentFormCard({
  wcHomeRecent,
  wcAwayRecent,
  homeTeam,
  awayTeam,
}: Props) {
  const home = wcHomeRecent || [];
  const away = wcAwayRecent || [];

  if (home.length === 0 && away.length === 0) return null;

  return (
    <div className="rounded-xl border border-zinc-700/40 bg-zinc-900/60 p-4 mt-4">
      <h3 className="text-sm font-bold text-zinc-300 mb-3">
        📋 近期表现
      </h3>
      <div className="flex gap-4 flex-col sm:flex-row">
        <RecentList matches={home} teamName={homeTeam} />
        <div className="w-px bg-zinc-800 hidden sm:block" />
        <RecentList matches={away} teamName={awayTeam} />
      </div>
    </div>
  );
}
