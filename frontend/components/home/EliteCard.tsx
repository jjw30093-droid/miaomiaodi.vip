'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import Image from 'next/image';

interface EliteCardProps {
  match: {
    competition: string;
    time: string;
    homeTeam: { name: string; icon: string; prob: number; color: string };
    awayTeam: { name: string; icon: string; prob: number; color: string };
    inference: string;
  };
}

export const EliteCard = ({ match }: EliteCardProps) => {
  return (
    <div className="mx-4 glass-panel rounded-2xl p-5 relative overflow-hidden group hover:border-primary-neon/30 transition-all">
      {/* HOT Badge (Diagonal) */}
      <div className="absolute top-0 right-0 overflow-hidden w-20 h-20 pointer-events-none z-20">
        <div className="absolute top-[15px] right-[-30px] bg-gradient-to-r from-red-600 to-orange-500 text-xs font-display font-black text-white px-10 py-1.5 transform rotate-45 shadow-lg uppercase tracking-tighter text-center">
          HOT MATCH
        </div>
      </div>

      {/* Background Subtle Gradient */}
      <div className="absolute inset-0 bg-gradient-to-br from-primary-neon/5 to-secondary-magenta/5 pointer-events-none" />
      
      {/* Header Info */}
      <div className="flex justify-between items-center mb-6 relative z-10">
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 rounded-full bg-slate-900 border border-border-subtle flex items-center justify-center p-1.5 overflow-hidden">
             <Image src="/premier_league.png" width={16} height={16} alt="Competition Logo" className="object-contain" />
          </div>
          <span className="text-xs tracking-wide font-display uppercase font-bold text-text-secondary dark:drop-shadow-[0_0_5px_rgba(0,240,255,0.5)]">
            {match.competition} • {match.time}
          </span>
        </div>
      </div>

      {/* Teams vs */}
      <div className="flex justify-around items-center mb-10 relative z-10">
        <div className="flex flex-col items-center gap-3">
           <div className="w-12 h-12 rounded-full border border-border-subtle shadow-lg overflow-hidden bg-black/20 p-1">
              <Image src={match.homeTeam.icon} width={48} height={48} alt="Home Team Icon" className="object-contain" />
           </div>
           <span className="font-display font-bold text-xs tracking-wide text-text-primary uppercase">
             {match.homeTeam.name}
           </span>
        </div>
        
        <span className="font-display text-lg font-black italic opacity-20 text-text-primary">VS</span>

        <div className="flex flex-col items-center gap-3">
           <div className="w-12 h-12 rounded-full border border-border-subtle shadow-lg overflow-hidden bg-black/20 p-1">
              <Image src={match.awayTeam.icon} width={48} height={48} alt="Away Team Icon" className="object-contain" />
           </div>
           <span className="font-display font-bold text-xs tracking-wide text-text-primary uppercase">
             {match.awayTeam.name}
           </span>
        </div>
      </div>

      {/* Probability Bars (Compact) */}
      <div className="flex items-center gap-6 relative z-10 mb-8 px-6">
        {/* Home Prob */}
        <div className="flex-1 flex flex-col gap-2">
          <div className="flex justify-between items-end">
            <span className="text-xs font-display font-bold text-text-secondary uppercase">HOME</span>
            <span className="text-sm font-display font-black text-primary-neon tracking-tighter italic">
              {match.homeTeam.prob}%
            </span>
          </div>
          <div className="w-full bg-black/20 rounded-full h-2.5 relative overflow-hidden border border-white/5">
             <motion.div 
               initial={{ width: 0 }}
               animate={{ width: `${match.homeTeam.prob}%` }}
               transition={{ duration: 1.2, ease: "easeOut" }}
               className="h-full rounded-full bg-gradient-to-r from-primary-neon/60 to-primary-neon shadow-[0_0_15px_rgba(0,240,255,0.4)]"
             />
          </div>
        </div>

        {/* Away Prob */}
        <div className="flex-1 flex flex-col gap-2">
          <div className="flex justify-between items-end">
            <span className="text-xs font-display font-bold text-text-secondary uppercase">AWAY</span>
            <span className="text-sm font-display font-black text-secondary-magenta tracking-tighter italic">
              {match.awayTeam.prob}%
            </span>
          </div>
          <div className="w-full bg-black/20 rounded-full h-2.5 relative overflow-hidden border border-white/5">
             <motion.div 
               initial={{ width: 0 }}
               animate={{ width: `${match.awayTeam.prob}%` }}
               transition={{ duration: 1.2, ease: "easeOut" }}
               className="h-full rounded-full bg-gradient-to-r from-secondary-magenta/60 to-secondary-magenta shadow-[0_0_15px_rgba(255,0,229,0.4)]"
             />
          </div>
        </div>
      </div>

      {/* AI Inference Footer */}
      <div className="bg-black/20 border-t border-border-subtle pt-3 relative z-10 group-hover:border-primary-neon/20 transition-colors">
         <p className="text-xs leading-relaxed">
            <span className="text-primary-neon font-display font-bold uppercase mr-2 tracking-widest shrink-0">核心推演:</span>
            <span className="text-text-secondary font-display italic font-medium">{match.inference}</span>
         </p>
      </div>

      {/* Decorative corner accents */}
      <div className="absolute top-0 left-0 w-8 h-8 border-t border-l border-primary-neon/30 rounded-tl-2xl" />
      <div className="absolute bottom-0 right-0 w-8 h-8 border-b border-r border-primary-neon/30 rounded-br-2xl" />
    </div>
  );
};
