'use client';
import React, { useState } from 'react';
import useSWR from 'swr';
import Link from 'next/link';
import { LayoutGrid, List, Filter, Trophy } from 'lucide-react';
import { useTheme } from './ThemeProvider';

interface Match {
  id: string;
  homeName: string;
  awayName: string;
  time: string;
  handicap: string;
  ev: number;
  hasReport: boolean;
  isFree?: boolean;
}

const MatchCard = ({ match, isFree = false }: { match: Match; isFree?: boolean }) => {
  return (
    <Link
      href={match.id ? `/report/${match.id}` : '#'}
      className="group flex flex-col glass-premium rounded-[3.5rem] overflow-hidden transition-all duration-500 border border-foreground/5 hover:border-neon/30 hover:shadow-2xl hover:shadow-neon/5 relative"
    >
      {isFree && (
        <div className="absolute top-0 left-0 bg-neon text-white text-[10px] font-black tracking-widest px-4 py-1.5 rounded-br-2xl shadow-lg z-20">
          [FREE]
        </div>
      )}
      <div className="flex items-center px-12 py-10 gap-12 relative z-10">
        {/* 左侧：状态与时间 */}
        <div className="flex flex-col gap-3 w-28 flex-shrink-0 items-center">
          <div className="w-16 h-16 rounded-full border-[3px] flex items-center justify-center font-black text-sm transition-all shadow-sm border-foreground/5 bg-foreground/5 text-up group-hover:border-neon/20">
            76'
          </div>
          <span className="text-[11px] font-black text-foreground/40 font-mono tracking-widest">{match.time}</span>
        </div>

        {/* 左侧：核心比赛信息 */}
        <div className="flex-1">
          <div className="flex items-center gap-12">
            <div className="flex items-center gap-6 flex-1 justify-end">
              <span className="font-black text-2xl tracking-tighter transition-colors text-foreground group-hover:text-neon">{match.homeName}</span>
              <Trophy size={18} className="text-foreground/10" />
            </div>
            <div className="px-6 py-2.5 rounded-2xl border font-black text-2xl min-w-[120px] text-center shadow-inner bg-background/40 border-foreground/5 text-up">
              1 - 1
            </div>
            <div className="flex items-center gap-6 flex-1">
              <span className="font-black text-2xl tracking-tighter transition-colors text-foreground group-hover:text-neon">{match.awayName}</span>
            </div>
          </div>
          <div className="flex justify-center gap-6 mt-8">
            <span className="text-[10px] font-black uppercase tracking-[0.2em] px-4 py-1.5 rounded-xl border border-foreground/5 bg-foreground/5 text-foreground/40">实时指数: {match.handicap}</span>
            <span className="text-[10px] font-black uppercase tracking-[0.2em] px-4 py-1.5 rounded-xl border border-foreground/5 bg-foreground/5 text-foreground/40">SA 分布极低</span>
          </div>
        </div>

        {/* 右侧：EV 预测模块 (Paywall) */}
        <div className={`border rounded-[2.5rem] p-8 min-w-[240px] relative overflow-hidden transition-all duration-500 border-foreground/5 group-hover:border-neon/30 ${isFree ? 'bg-background/80' : 'bg-background/80 backdrop-blur-md'}`}>
          {!isFree && (
            <div className="absolute inset-0 z-30 flex items-center justify-center bg-background/30 backdrop-blur-md">
              <div className="px-4 py-2.5 bg-gradient-to-r from-neon to-blue-600 rounded-xl shadow-lg border border-white/20 text-white text-[10px] font-black uppercase tracking-widest whitespace-nowrap glow-pulse">
                🔒 解锁 PRO，查看本场高价值 EV
              </div>
            </div>
          )}
          
          <div className="absolute top-0 right-0 w-24 h-24 rounded-bl-full pointer-events-none opacity-20 bg-gradient-to-br from-neon to-transparent" />
          <div className={`flex flex-col gap-3 relative z-10 transition-all duration-300 ${!isFree ? 'blur-sm opacity-40 select-none' : ''}`}>
            <span className="text-[9px] font-black text-foreground/40 tracking-widest uppercase opacity-60">Intelligence Prediction</span>
            <div className="text-base font-black text-foreground">主队让 0.5</div>
            <div className="flex items-end justify-between mt-4">
              <div className="flex flex-col gap-1">
                <span className="text-[9px] text-foreground/40 font-black uppercase tracking-widest">指数</span>
                <span className="text-base font-black font-mono tracking-tighter text-foreground/80">1.95</span>
              </div>
              <div className="flex flex-col text-right gap-1">
                <span className="text-[9px] text-foreground/40 font-black uppercase tracking-widest">EV%</span>
                <span className="text-2xl font-black font-mono tracking-tighter text-neon">+{match.ev}%</span>
              </div>
            </div>
          </div>
        </div>

        {/* 右侧：操作 */}
        <div className="flex flex-col justify-center relative z-10">
          <div className="px-8 py-4 font-black text-[10px] uppercase tracking-[0.2em] rounded-2xl shadow-lg transition-all hover:scale-105 active:scale-95 cursor-pointer whitespace-nowrap bg-neon text-white dark:text-black shadow-neon/10">
            打开研报 →
          </div>
        </div>
      </div>
    </Link>
  );
};

const fetcher = async (url: string) => {
  const res = await fetch(url);
  if (!res.ok) throw new Error('API Error');
  return res.json();
};

export default function FixtureList() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  
  const { data: matches, error, isLoading } = useSWR<Match[]>('/api/matches', fetcher, {
    revalidateOnFocus: false
  });
  const [filter, setFilter] = useState('全部');

  if (isLoading) return (
    <div className="text-center py-20 font-mono text-[10px] animate-pulse tracking-[0.4em] text-foreground/40">
      ▌ SYNCING QUANTITATIVE MATRIX...
    </div>
  );
  if (error || !matches) return (
    <div className="text-center py-20 font-mono text-[10px] font-black uppercase tracking-[0.5em] text-down">
      Link Fault :: Manual Override Required
    </div>
  );

  return (
    <div className="flex flex-col gap-10">
      {/* 标题与主信息 */}
      <div className="flex flex-col gap-4">
         <div className="flex items-center justify-between">
            <h2 className="text-xl font-black tracking-tighter uppercase italic flex items-center gap-3 text-foreground">
              候选比赛池 <span className="w-2.5 h-2.5 rounded-full animate-pulse bg-neon shadow-[0_0_10px_var(--neon-cyan)] opacity-70"></span>
            </h2>
            <div className="flex items-center gap-4">
               <div className="flex p-1 border rounded-xl bg-foreground/5 border-foreground/5 shadow-sm">
                  <div className="p-1.5 rounded-lg bg-neon/10 text-neon"><LayoutGrid size={16} /></div>
                  <div className="p-1.5 text-foreground/40 hover:text-foreground transition-colors cursor-pointer"><List size={16} /></div>
               </div>
               <button className="flex items-center gap-2 px-6 py-2.5 border rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all bg-foreground/5 border-foreground/5 text-foreground/60 hover:bg-foreground/10">
                  <Filter size={14} /> 筛选器
               </button>
            </div>
         </div>
         <p className="text-[10px] text-foreground/40 font-bold uppercase tracking-widest opacity-60">实时监控盘口走势，捕捉动态高价值模型</p>
      </div>

      {/* 筛选 Tabs */}
      <div className="flex items-center gap-3 px-6 py-4 border rounded-[2rem] w-fit shadow-sm bg-background/60 backdrop-blur-xl border-foreground/5">
         {['全部', '进行中', '高价值', '即将开始'].map((t) => (
           <button 
             key={t}
             onClick={() => setFilter(t)}
             className={`px-8 py-2.5 rounded-2xl text-[10px] font-black uppercase tracking-widest transition-all ${
               filter === t 
                 ? 'bg-neon text-white dark:text-black shadow-lg shadow-neon/20' 
                 : 'text-foreground/40 hover:text-foreground hover:bg-foreground/5'
             }`}
           >
             {t} {t === '全部' && `(${matches.length})`}
           </button>
         ))}
      </div>

      {/* 比赛列表容器 */}
      <div className="grid grid-cols-1 gap-8">
        {matches.map((match) => (
          <MatchCard key={match.id} match={match} isFree={match.isFree ?? false} />
        ))}
      </div>
    </div>
  );
}
