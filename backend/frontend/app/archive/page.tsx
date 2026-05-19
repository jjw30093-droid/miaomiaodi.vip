'use client';
import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { Archive, ChevronLeft, Trophy, Star } from 'lucide-react';

interface ArchivedMatch {
  id: string; league: string; time: string; createdAt: string;
  homeTeam: { name: string; icon: string };
  awayTeam: { name: string; icon: string };
  status: string; inference: string;
}

export default function ArchivePage() {
  const [data, setData]       = useState<ArchivedMatch[]>([]);
  const [total, setTotal]     = useState(0);
  const [page, setPage]       = useState(1);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res  = await fetch(`/api/v1/reports/archive?page=${page}&per_page=20`,
                                 { cache: 'no-store' });
        const json = await res.json();
        setData(json.data || []);
        setTotal(json.total || 0);
      } catch (e) { console.error(e); }
      finally { setLoading(false); }
    })();
  }, [page]);

  const grouped = data.reduce((acc, m) => {
    const month = m.createdAt
      ? new Date(m.createdAt).toLocaleDateString('zh-CN',
          { year: 'numeric', month: 'long' })
      : '历史记录';
    (acc[month] ??= []).push(m);
    return acc;
  }, {} as Record<string, ArchivedMatch[]>);

  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="max-w-md mx-auto px-6 pt-12 pb-32">

        <Link href="/"
          className="flex items-center gap-2 text-zinc-500 hover:text-primary-container
                     transition-colors mb-8 text-xs font-black italic tracking-widest uppercase">
          <ChevronLeft className="w-4 h-4" />返回首页
        </Link>

        <div className="flex items-center gap-4 mb-10">
          <div className="w-10 h-10 rounded-full bg-primary-container/10 flex items-center
                          justify-center border border-primary-container/20">
            <Archive className="w-5 h-5 text-primary-container" />
          </div>
          <div>
            <h1 className="text-2xl font-headline font-black italic tracking-tighter">
              研报归档库
            </h1>
            <p className="text-[10px] text-zinc-500 tracking-widest uppercase mt-0.5">
              {total} 份历史研报 · 归档后免费公开
            </p>
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
              <span className="text-[10px] font-black italic tracking-widest
                               text-primary-container uppercase">{month}</span>
              <div className="flex-1 h-[1px] bg-white/5" />
              <span className="text-[9px] text-zinc-600">{matches.length} 场</span>
            </div>
            <div className="flex flex-col gap-3">
              {matches.map(m => (
                <Link key={m.id} href={`/report/${m.id}`}
                  className="glass-panel p-4 flex items-center gap-4
                             hover:bg-white/[0.04] transition-colors active:scale-[0.98]">
                  <div className="flex items-center gap-2 shrink-0">
                    <img src={m.homeTeam.icon} className="w-6 h-6 object-contain"
                         alt={m.homeTeam.name} onError={e => (e.currentTarget.style.display='none')} />
                    <span className="text-[8px] text-zinc-600 font-bold">VS</span>
                    <img src={m.awayTeam.icon} className="w-6 h-6 object-contain"
                         alt={m.awayTeam.name} onError={e => (e.currentTarget.style.display='none')} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-bold truncate">
                      {m.homeTeam.name} vs {m.awayTeam.name}
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <Trophy className="w-3 h-3 text-zinc-600 shrink-0" />
                      <span className="text-[9px] text-zinc-500 truncate">{m.league}</span>
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    <span className="text-[9px] text-zinc-600">{m.time}</span>
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
            <p className="text-[10px] tracking-widest mt-2 uppercase">比赛结束 24h 后自动归档</p>
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
    </main>
  );
}
