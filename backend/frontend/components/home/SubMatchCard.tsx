'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { Lock, Zap } from 'lucide-react';
import { cn } from '@/lib/utils';
import { CapsulePill } from '@/components/ui/CapsulePill';
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
    <div className={cn("glass-cyber p-5 rounded-cyber relative overflow-hidden h-full flex flex-col group hover:border-primary/30 transition-all", className)}>
      <div className="flex justify-between items-start mb-6">
        <div className="flex items-center gap-2">
           <Zap className="w-3 h-3 text-secondary fill-secondary" />
           <span className="text-utility text-[8px] font-bold uppercase tracking-widest opacity-40">
             {match.competition} • {match.time}
           </span>
        </div>
        {match.isFree && <CapsulePill variant="tertiary" className="text-[8px] py-0.5 px-2 bg-emerald-500/20 border-emerald-500/40 text-emerald-300">FREE</CapsulePill>}
      </div>

      <div className="flex-1 relative">
        {match.isVip ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center z-20 text-center px-4">
            <div className="text-editorial text-4xl font-black text-foreground/10 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 tracking-tighter">
              1:X | 1.X+
            </div>
            <div className="w-12 h-12 glass-cyber rounded-full flex items-center justify-center border-primary/40 shadow-[0_0_15px_rgba(143,245,255,0.2)] mb-3">
               <Lock className="w-5 h-5 text-primary" />
            </div>
            <p className="text-[9px] font-utility font-bold text-foreground/60 leading-tight uppercase tracking-wider mb-4">
               Unlock VIP: Tactical Radar, Shot Map & Final Verdict
            </p>
            <button className="text-[8px] font-editorial font-black bg-gradient-to-r from-primary to-secondary py-1.5 px-4 rounded-full text-black hover:scale-105 active:scale-95 transition-all shadow-lg italic">
               UNLOCK FULL AI REPORT
            </button>
          </div>
        ) : (
          <div className="flex justify-around items-end gap-6 mb-4 mt-2">
            <div className="flex flex-col items-center gap-2">
              <span className="text-editorial text-xs font-black text-primary italic">{match.homeTeam.prob}%</span>
              <div className="w-3 h-16 bg-white/5 rounded-full relative overflow-hidden flex items-end border border-white/5">
                <motion.div initial={{ height: 0 }} animate={{ height: `${match.homeTeam.prob}%` }} transition={{ duration: 1 }} className="w-full rounded-full bg-primary" />
              </div>
              <span className="text-utility text-[7px] font-bold opacity-30 uppercase">HOME</span>
            </div>
            <div className="flex flex-col items-center gap-2">
              <span className="text-editorial text-xs font-black text-secondary italic">{match.awayTeam.prob}%</span>
              <div className="w-3 h-16 bg-white/5 rounded-full relative overflow-hidden flex items-end border border-white/5">
                <motion.div initial={{ height: 0 }} animate={{ height: `${match.awayTeam.prob}%` }} transition={{ duration: 1 }} className="w-full rounded-full bg-secondary" />
              </div>
              <span className="text-utility text-[7px] font-bold opacity-30 uppercase">AWAY</span>
            </div>
          </div>
        )}
        
        {/* Blur overlay for VIP */}
        {match.isVip && <div className="absolute inset-0 backdrop-blur-sm bg-black/5 rounded-lg z-10" />}
      </div>

      <div className={cn("mt-auto pt-4 border-t border-white/5 truncate", match.isVip && "opacity-0")}>
         <p className="text-[8px] flex items-center gap-1">
            <span className="text-primary font-bold font-editorial uppercase tracking-widest shrink-0">AI INFERENCE:</span>
            <span className="text-foreground/40 font-utility truncate">{match.inference}</span>
         </p>
      </div>
    </div>
  );
};
