'use client';
import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { useSession } from 'next-auth/react';
import { Archive, ChevronLeft, Trophy, ChevronDown, Filter, X } from 'lucide-react';
import Footer from '@/components/layout/Footer';
import { translateLeague } from '@/lib/leagueNames';

interface ArchivedMatch {
  id: string; league: string; time: string; createdAt: string;
  homeTeam: { name: string; icon: string };
  awayTeam: { name: string; icon: string };
  status: string; inference: string;
}

export default function ArchivePage() {
  const { data: session, status } = useSession();
  const apiToken = (session?.user as any)?.apiToken as string | undefined;

  const [data, setData]                   = useState<ArchivedMatch[]>([]);
  const [total, setTotal]                 = useState(0);
  const [page, setPage]                   = useState(1);
  const [loading, setLoading]             = useState(true);
  // leagueFilter 存"展示名"（如"J联赛"），未翻译的就是英文原名
  // 提交后端时再展开成对应的英文变体（用 leagueGroups 反查）
  const [leagueFilter, setLeagueFilter]   = useState<string>('');
  const [startDate, setStartDate]         = useState<string>('');
  const [endDate, setEndDate]             = useState<string>('');
  const [availableLeagues, setAvailableLeagues] = useState<string[]>([]);
  const [showLeagueDropdown, setShowLeagueDropdown] = useState(false);

  // 按"展示名" dedupe：J. League 100 Year Vision League East/West 都映射到"J联赛"
  const leagueGroups = React.useMemo(() => {
    const groups: Record<string, string[]> = {};
    availableLeagues.forEach(en => {
      const display = translateLeague(en);
      (groups[display] ||= []).push(en);
    });
    return groups;  // { "J联赛": ["...East", "...West"], "英超": ["Premier League"], "J. LEAGUE": ["J. LEAGUE"] }
  }, [availableLeagues]);

  const dedupedLeagueOptions = React.useMemo(
    () => Object.keys(leagueGroups).sort(),
    [leagueGroups]
  );

  // 一次性拉取全量联赛列表（用于下拉选择器）
  useEffect(() => {
    if (status === 'loading' || !apiToken) return;
    fetch('/api/v1/reports/archive/leagues', {
      headers: { Authorization: `Bearer ${apiToken}` },
    })
      .then(r => r.ok ? r.json() : [])
      .then(setAvailableLeagues)
      .catch(() => {});
  }, [apiToken, status]);

  // 筛选条件变化时回到第 1 页
  useEffect(() => {
    setPage(1);
  }, [leagueFilter, startDate, endDate]);

  // 主数据请求：page / 筛选条件任意变化时重新拉取
  useEffect(() => {
    if (status === 'loading') return;
    (async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams({ page: String(page), per_page: '20' });
        if (leagueFilter) {
          // leagueFilter 是"展示名"，提交时展开成所有对应的英文变体（逗号分隔）
          const variants = leagueGroups[leagueFilter] || [leagueFilter];
          params.append('league', variants.join(','));
        }
        if (startDate)    params.append('start_date', startDate);
        if (endDate)      params.append('end_date', endDate);

        const res = await fetch(`/api/v1/reports/archive?${params.toString()}`, {
          cache: 'no-store',
          headers: apiToken ? { Authorization: `Bearer ${apiToken}` } : undefined,
        });
        if (!res.ok) { setData([]); setTotal(0); return; }
        const json = await res.json();
        setData(json.data || []);   // 后端已按 match_time DESC 排序
        setTotal(json.total || 0);
      } catch (e) { console.error(e); }
      finally { setLoading(false); }
    })();
  }, [page, apiToken, status, leagueFilter, startDate, endDate, leagueGroups]);

  const hasDateFilter = startDate || endDate;

  // 按开赛月份分组（后端已排序，直接 reduce）
  const grouped = data.reduce((acc, m) => {
    const month = m.time
      ? new Date(m.time).toLocaleDateString('zh-CN', { year: 'numeric', month: 'long' })
      : '历史记录';
    (acc[month] ??= []).push(m);
    return acc;
  }, {} as Record<string, ArchivedMatch[]>);

  return (
    <main className="min-h-screen bg-[var(--color-background)] text-[var(--color-foreground)]">
      <div className="max-w-md mx-auto px-6 pt-12 pb-32">

        <Link href="/"
          className="flex items-center gap-2 text-zinc-500 hover:text-primary-container
                     transition-colors mb-8 text-xs font-black italic tracking-widest uppercase">
          <ChevronLeft className="w-4 h-4" />返回首页
        </Link>

        <div className="flex items-center gap-4 mb-6">
          <div className="w-10 h-10 rounded-full bg-primary-container/10 flex items-center
                          justify-center border border-primary-container/20">
            <Archive className="w-5 h-5 text-primary-container" />
          </div>
          <div>
            <h1 className="text-2xl font-headline font-black italic tracking-tighter">
              研报归档库
            </h1>
            <p className="text-xs text-zinc-500 tracking-widest uppercase mt-0.5">
              {total} 份历史研报 · 归档后免费公开
            </p>
          </div>
        </div>

        {/* ── 筛选工具栏 ── */}
        <div className="mb-8 flex flex-col gap-3">

          {/* 联赛筛选 */}
          <div className="relative flex justify-end">
            <button
              onClick={() => setShowLeagueDropdown(v => !v)}
              className={`flex items-center gap-1.5 px-4 py-2 rounded-full text-xs font-bold transition-all border ${
                leagueFilter
                  ? 'bg-primary-container/10 border-primary-container text-primary-container'
                  : 'bg-black/5 dark:bg-white/5 border-black/10 dark:border-white/10 text-zinc-500 dark:text-zinc-400'
              }`}
            >
              <Filter size={10} />
              <span className="max-w-[140px] truncate">{leagueFilter || '联赛筛选'}</span>
              <ChevronDown size={10} />
            </button>
            {showLeagueDropdown && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setShowLeagueDropdown(false)} />
                <div className="absolute top-full mt-2 right-0 z-50 bg-white dark:bg-zinc-900 border border-black/10 dark:border-white/10
                                rounded-2xl py-2 min-w-[160px] max-h-64 overflow-y-auto shadow-2xl">
                  <button
                    onClick={() => { setLeagueFilter(''); setShowLeagueDropdown(false); }}
                    className={`w-full text-left px-4 py-2 text-xs font-bold transition-colors ${
                      !leagueFilter ? 'text-primary-container' : 'text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white'
                    }`}
                  >
                    全部联赛
                  </button>
                  {dedupedLeagueOptions.map(displayName => (
                    <button
                      key={displayName}
                      onClick={() => { setLeagueFilter(displayName); setShowLeagueDropdown(false); }}
                      className={`w-full text-left px-4 py-2 text-xs font-bold transition-colors ${
                        leagueFilter === displayName ? 'text-primary-container' : 'text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-white'
                      }`}
                    >
                      {displayName}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* 日期筛选 */}
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={startDate}
              onChange={e => setStartDate(e.target.value)}
              className="flex-1 min-w-0 bg-black/5 dark:bg-white/5 border border-black/10 dark:border-white/10 rounded-full
                         px-3 py-2 text-xs font-bold text-zinc-600 dark:text-zinc-400
                         focus:outline-none focus:border-primary-container/50
                         transition-colors"
              placeholder="开始日期"
            />
            <span className="text-zinc-600 text-xs shrink-0">至</span>
            <input
              type="date"
              value={endDate}
              onChange={e => setEndDate(e.target.value)}
              className="flex-1 min-w-0 bg-black/5 dark:bg-white/5 border border-black/10 dark:border-white/10 rounded-full
                         px-3 py-2 text-xs font-bold text-zinc-600 dark:text-zinc-400
                         focus:outline-none focus:border-primary-container/50
                         transition-colors"
              placeholder="结束日期"
            />
            {hasDateFilter && (
              <button
                onClick={() => { setStartDate(''); setEndDate(''); }}
                className="shrink-0 flex items-center justify-center w-6 h-6 rounded-full
                           bg-black/5 dark:bg-white/5 border border-black/10 dark:border-white/10 text-zinc-500 hover:text-zinc-900 dark:hover:text-white
                           transition-colors"
                title="清除日期"
              >
                <X size={10} />
              </button>
            )}
          </div>
        </div>

        {loading && (
          <div className="flex justify-center py-20">
            <div className="w-8 h-8 border-2 border-dashed border-primary-container/30
                            rounded-full animate-spin" />
          </div>
        )}

        {!loading && Object.entries(grouped).map(([month, matches]) => (
          <div key={month} className="mb-8">
            <div className="flex items-center gap-3 mb-4">
              <span className="text-xs font-black italic tracking-widest
                               text-primary-container uppercase">{month}</span>
              <div className="flex-1 h-[1px] bg-white/5" />
              <span className="text-xs text-zinc-600">{matches.length} 场</span>
            </div>
            <div className="flex flex-col gap-3">
              {matches.map(m => (
                <Link key={m.id} href={`/report/${m.id}`}
                  className="glass-panel p-4 flex items-center gap-4
                             hover:bg-white/[0.04] transition-colors active:scale-[0.98]">
                  <div className="flex items-center gap-2 shrink-0">
                    <img src={m.homeTeam.icon} className="w-6 h-6 object-contain"
                         alt={m.homeTeam.name} onError={e => (e.currentTarget.style.display='none')} />
                    <span className="text-xs text-zinc-600 font-bold">VS</span>
                    <img src={m.awayTeam.icon} className="w-6 h-6 object-contain"
                         alt={m.awayTeam.name} onError={e => (e.currentTarget.style.display='none')} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-bold truncate">
                      {m.homeTeam.name} vs {m.awayTeam.name}
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <Trophy className="w-3 h-3 text-zinc-600 shrink-0" />
                      <span className="text-xs text-zinc-500 truncate">{translateLeague(m.league)}</span>
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    <span className="text-xs text-zinc-600">{m.time}</span>
                    {m.status === 'REVIEW_GENERATED' && (
                      <span className="text-[7px] font-black italic text-purple-400
                                       border border-purple-400/30 rounded-full px-1.5 py-0.5">
                        含复盘
                      </span>
                    )}
                    <span className="text-[7px] font-black italic text-green-500/60
                                     border border-green-500/20 rounded-full px-1.5 py-0.5">
                      免费
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        ))}

        {!loading && data.length === 0 && (
          <div className="text-center py-20 opacity-40">
            <Archive className="w-12 h-12 mx-auto mb-4 text-zinc-600" />
            <p className="text-sm font-bold">暂无归档记录</p>
            <p className="text-xs tracking-widest mt-2 uppercase">比赛结束 24h 后自动归档</p>
          </div>
        )}

        {total > 20 && (
          <div className="flex justify-center gap-4 mt-8">
            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
              className="px-4 py-2 glass-panel text-xs font-bold
                         disabled:opacity-30 hover:bg-white/[0.04]">上一页</button>
            <span className="flex items-center text-xs text-zinc-500">
              {page} / {Math.ceil(total / 20)}
            </span>
            <button onClick={() => setPage(p => p + 1)}
              disabled={page >= Math.ceil(total / 20)}
              className="px-4 py-2 glass-panel text-xs font-bold
                         disabled:opacity-30 hover:bg-white/[0.04]">下一页</button>
          </div>
        )}
      </div>
      <Footer />
    </main>
  );
}
