import React from 'react';
import Image from 'next/image';

interface MatchHeaderProps {
  title: string;
  homeTeam: string;
  awayTeam: string;
  homeScore?: number;
  awayScore?: number;
  createdAt: string;
  homeProb?: number;
  awayProb?: number;
}

const CONDITIONS = [
  { icon: '🌧', label: '天气条件', value: '小雨 (影响 -5%)' },
  { icon: '🟡', label: '裁判尺度', value: '偏严 (吃牌风险高)' },
  { icon: '🌱', label: '场地情况', value: '湿滑' },
];

const MatchHeader: React.FC<MatchHeaderProps> = ({ 
  title, 
  homeTeam, 
  awayTeam, 
  createdAt, 
  homeProb = 50, 
  awayProb = 50 
}) => {
  const formattedDate = new Date(createdAt).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  }).replace(/\//g, '-');

  return (
    <div className="w-full flex flex-col gap-4">
      {/* 1. 顶部标题栏 */}
      <div className="glass-panel px-6 py-4 flex items-center justify-between border border-white/10 shadow-ambient-lift">
        <div className="flex items-center gap-4">
          <div className="relative w-8 h-8 rounded-lg overflow-hidden border border-white/10">
            <Image 
              src="/logo_meow.jpg" 
              alt="Meow Logo" 
              fill 
              className="object-cover"
            />
          </div>
          <h1 className="text-sm font-headline font-black italic tracking-wider text-foreground/80">
            喵弟数据研究室 · <span className="text-primary-container">核心研报</span>
          </h1>
        </div>
        <div className="flex items-center gap-3 opacity-40">
          <span className="w-1.5 h-1.5 rounded-full bg-primary-container animate-pulse" />
          <span className="text-[10px] font-mono font-bold tracking-widest">{formattedDate}</span>
        </div>
      </div>

      {/* 2. 双概率 Pill 卡片 */}
      <div className="grid grid-cols-2 gap-3 mt-2">
        {/* 主队胜率 Pill */}
        <div className="glass-panel relative overflow-hidden p-6 flex flex-col items-center justify-center border border-cyan-400/20 bg-gradient-to-t from-cyan-500/30 to-cyan-400/10 group hover:from-cyan-500/40 transition-all duration-500">
          <div className="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-20 transition-opacity">
            <div className="text-4xl font-black italic tracking-tighter">HOME</div>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-5xl font-headline font-black italic text-primary-container drop-shadow-[0_0_15px_rgba(0,240,255,0.3)]">
              {homeProb}
            </span>
            <span className="text-xl font-headline font-black italic text-primary-container/60">%</span>
          </div>
          <div className="mt-2 text-[10px] font-headline font-black italic tracking-[0.3em] uppercase text-primary-container/80">
            主胜概率 WIN-PROB
          </div>
          <div className="mt-4 text-xs font-headline font-bold tracking-widest opacity-60">
            {(homeTeam || '').toUpperCase()}
          </div>
        </div>

        {/* 客队胜率 Pill */}
        <div className="glass-panel relative overflow-hidden p-6 flex flex-col items-center justify-center border border-purple-400/20 bg-gradient-to-t from-purple-500/30 to-purple-400/10 group hover:from-purple-500/40 transition-all duration-500">
          <div className="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-20 transition-opacity">
            <div className="text-4xl font-black italic tracking-tighter">AWAY</div>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-5xl font-headline font-black italic text-secondary-container drop-shadow-[0_0_15px_rgba(255,0,229,0.3)]">
              {awayProb}
            </span>
            <span className="text-xl font-headline font-black italic text-secondary-container/60">%</span>
          </div>
          <div className="mt-2 text-[10px] font-headline font-black italic tracking-[0.3em] uppercase text-secondary-container/80">
            客胜概率 WIN-PROB
          </div>
          <div className="mt-4 text-xs font-headline font-bold tracking-widest opacity-60">
            {(awayTeam || '').toUpperCase()}
          </div>
        </div>
      </div>

      {/* 3. 场地条件 Chips */}
      <div className="flex gap-3 mt-2">
        {CONDITIONS.map((cond, idx) => (
          <div key={idx} className="flex-1 glass-panel !rounded-2xl p-4 flex flex-col gap-1 border border-white/5 hover:bg-white/[0.04] transition-colors">
            <div className="flex items-center gap-2">
              <span className="text-sm">{cond.icon}</span>
              <span className="text-[9px] font-headline font-black italic uppercase tracking-widest text-zinc-500">
                {cond.label}
              </span>
            </div>
            <div className="text-[11px] font-headline font-bold text-foreground/90 mt-1">
              {cond.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default MatchHeader;
