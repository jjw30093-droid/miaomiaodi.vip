'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { Lock, Zap } from 'lucide-react';
import { cn } from '@/lib/utils';
import Image from 'next/image';

interface SubMatchCardProps {
  match: {
    competition: string;
    time: string;
    homeTeam: { name: string; prob: number };
    awayTeam: { name: string; prob: number };
    isVip?: boolean;
    isFree?: boolean;
    inference: string;
  };
  className?: string;
}

export const SubMatchCard = ({ match, className }: SubMatchCardProps) => {
  return (
    <div className={cn("glass-panel rounded-2xl p-4 relative overflow-hidden h-full flex flex-col group hover:border-primary-neon/30 transition-all", className)}>
      {/* HOT Badge (Diagonal) - Optional for SubMatchCard if needed */}
      {!match.isFree && !match.isVip && (
        <div className="absolute top-0 right-0 overflow-hidden w-16 h-16 pointer-events-none">
          <div className="absolute top-[10px] right-[-25px] bg-gradient-to-r from-red-600 to-orange-500 text-xs font-bold text-white px-8 py-1 transform rotate-45 shadow-lg uppercase tracking-tighter">
            PRO
          </div>
        </div>
      )}

      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-2">
           <Zap className="w-3 h-3 text-primary-neon animate-pulse" />
           <span className="text-xs tracking-wide font-display uppercase font-bold text-text-secondary dark:drop-shadow-[0_0_5px_rgba(0,240,255,0.5)]">
             {match.competition} • {match.time}
           </span>
        </div>
        {match.isFree && (
          <span className="text-xs font-display font-black bg-emerald-500/20 border border-emerald-500/40 text-emerald-400 px-2 py-0.5 rounded-full">
            FREE
          </span>
        )}
      </div>

      <div className="flex-1 relative">
        {match.isVip ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center z-20 text-center px-4">
            <div className="text-display text-2xl font-black text-text-primary/10 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 tracking-tighter uppercase italic">
              VIP ANALYSIS
            </div>
            <div className="w-10 h-10 glass-panel rounded-full flex items-center justify-center border-primary-neon/40 shadow-[0_0_15px_rgba(0,240,255,0.2)] mb-2">
               <Lock size={16} className="text-yellow-500 drop-shadow-[0_0_5px_rgba(234,179,8,0.5)]" />
            </div>
            <p className="text-xs font-display font-bold text-text-secondary leading-tight uppercase tracking-wider mb-3">
               已锁定深度数据报告
            </p>
            <button className="text-xs font-display font-black bg-gradient-to-r from-primary-neon to-blue-600 py-1.5 px-4 rounded-full text-white hover:scale-105 active:scale-95 transition-all shadow-lg italic uppercase tracking-wider">
               解密完整研报
            </button>
          </div>
        ) : (
          <div className="flex justify-around items-end gap-6 mb-4 mt-2">
            <div className="flex flex-col items-center gap-2">
              <span className="font-display font-bold text-xs tracking-wide text-primary-neon">{match.homeTeam.prob}%</span>
              <div className="w-2.5 h-14 bg-black/20 rounded-full relative overflow-hidden flex items-end border border-white/5">
                <motion.div initial={{ height: 0 }} animate={{ height: `${match.homeTeam.prob}%` }} transition={{ duration: 1 }} className="w-full rounded-full bg-primary-neon shadow-[0_0_8px_rgba(0,240,255,0.6)]" />
              </div>
              <span className="font-display font-bold text-xs tracking-wide text-text-secondary uppercase">H</span>
            </div>
            <div className="flex flex-col items-center gap-2">
              <span className="font-display font-bold text-xs tracking-wide text-secondary-magenta">{match.awayTeam.prob}%</span>
              <div className="w-2.5 h-14 bg-black/20 rounded-full relative overflow-hidden flex items-end border border-white/5">
                <motion.div initial={{ height: 0 }} animate={{ height: `${match.awayTeam.prob}%` }} transition={{ duration: 1 }} className="w-full rounded-full bg-secondary-magenta shadow-[0_0_8px_rgba(255,0,229,0.6)]" />
              </div>
              <span className="font-display font-bold text-xs tracking-wide text-text-secondary uppercase">A</span>
            </div>
          </div>
        )}
        
        {/* Blur overlay for VIP */}
        {match.isVip && <div className="absolute inset-0 backdrop-blur-md bg-black/10 rounded-lg z-10" />}
      </div>

      <div className={cn("mt-auto pt-3 border-t border-border-subtle truncate", match.isVip && "opacity-0")}>
         <p className="text-xs flex items-center gap-1">
            <span className="text-primary-neon font-bold font-display uppercase tracking-widest shrink-0">核心推演:</span>
            <span className="text-text-secondary truncate">{match.inference}</span>
         </p>
      </div>
    </div>
  );
};
