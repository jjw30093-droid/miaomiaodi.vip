'use client';

import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import { CapsulePill } from '@/components/ui/CapsulePill';
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
    <div className="mx-5 glass-cyber p-6 rounded-cyber relative overflow-hidden border-primary/20">
      {/* Background Gradient */}
      <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-secondary/5 opacity-40 pointer-events-none" />
      
      {/* Header Info */}
      <div className="flex justify-between items-center mb-10 relative z-10">
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 rounded-full bg-slate-800 border border-white/20 flex items-center justify-center p-1">
             <Image src="/premier_league.png" width={16} height={16} alt="PL" />
          </div>
          <span className="text-utility text-[10px] font-bold uppercase tracking-widest opacity-60">
            {match.competition} • {match.time}
          </span>
        </div>
        <CapsulePill variant="primary" className="bg-gradient-to-r from-yellow-500 to-amber-600 border-none shadow-[0_0_15px_rgba(245,158,11,0.4)]">
          HOT
        </CapsulePill>
      </div>

      {/* Teams vs */}
      <div className="flex justify-around items-center mb-12 relative z-10">
        <div className="flex flex-col items-center gap-4">
           <div className="w-16 h-16 glass-cyber rounded-full flex items-center justify-center border-white/10 shadow-lg">
              <Image src={match.homeTeam.icon} width={40} height={40} alt="Home" />
           </div>
           <span className="text-editorial text-xs font-black uppercase tracking-widest whitespace-nowrap">
             {match.homeTeam.name}
           </span>
        </div>
        
        <span className="text-editorial text-2xl font-black italic opacity-30">VS</span>

        <div className="flex flex-col items-center gap-4">
           <div className="w-16 h-16 glass-cyber rounded-full flex items-center justify-center border-white/10 shadow-lg">
              <Image src={match.awayTeam.icon} width={40} height={40} alt="Away" />
           </div>
           <span className="text-editorial text-xs font-black uppercase tracking-widest whitespace-nowrap">
             {match.awayTeam.name}
           </span>
        </div>
      </div>

      {/* Probability Bars */}
      <div className="flex justify-around items-end gap-12 relative z-10 mb-14 px-4 h-64">
        {/* Home Bar */}
        <div className="flex flex-col items-center gap-4 flex-1">
          <span className="text-editorial text-xl font-black text-primary italic">
            {match.homeTeam.prob}%
          </span>
          <div className="w-full bg-white/5 rounded-full h-48 relative overflow-hidden flex items-end shadow-inner border border-white/5">
             <motion.div 
               initial={{ height: 0 }}
               animate={{ height: `${match.homeTeam.prob}%` }}
               transition={{ duration: 1.5, ease: "easeOut", delay: 0.2 }}
               className="w-full rounded-full bg-gradient-to-t from-primary/80 to-primary shadow-[0_0_25px_rgba(143,245,255,0.4)]"
             />
          </div>
          <span className="text-utility text-[9px] font-bold opacity-40 uppercase tracking-[0.2em]">HOME</span>
        </div>

        {/* Away Bar */}
        <div className="flex flex-col items-center gap-4 flex-1">
          <span className="text-editorial text-xl font-black text-secondary italic">
            {match.awayTeam.prob}%
          </span>
          <div className="w-full bg-white/5 rounded-full h-48 relative overflow-hidden flex items-end shadow-inner border border-white/5">
             <motion.div 
               initial={{ height: 0 }}
               animate={{ height: `${match.awayTeam.prob}%` }}
               transition={{ duration: 1.5, ease: "easeOut", delay: 0.4 }}
               className="w-full rounded-full bg-gradient-to-t from-secondary/80 to-secondary shadow-[0_0_25px_rgba(201,124,255,0.4)]"
             />
          </div>
          <span className="text-utility text-[9px] font-bold opacity-40 uppercase tracking-[0.2em]">AWAY</span>
        </div>
      </div>

      {/* AI Inference Footer */}
      <div className="glass-cyber bg-black/20 border-white/10 p-4 rounded-xl relative z-10 group hover:border-primary/40 transition-colors">
         <p className="text-[10px] leading-relaxed">
            <span className="text-primary font-bold font-editorial uppercase mr-2 tracking-widest">AI INFERENCE:</span>
            <span className="text-foreground/70 font-utility font-medium italic">{match.inference}</span>
         </p>
      </div>
    </div>
  );
};
