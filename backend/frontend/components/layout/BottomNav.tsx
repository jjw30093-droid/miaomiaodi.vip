'use client';

import React, { useState } from 'react';
import { LayoutGrid, Heart, History, User } from 'lucide-react';
import { cn } from '@/lib/utils';

const NAV_ITEMS = [
  { id: 'matches', label: 'Matches', icon: Heart },
  { id: 'history', label: 'AI History', icon: History },
  { id: 'vip', label: 'VIP', icon: LayoutGrid },
];

export const BottomNav = () => {
  const [active, setActive] = useState('matches');

  return (
    <div className="fixed bottom-10 left-1/2 -translate-x-1/2 z-50 w-[90%] max-w-sm">
      <div className="glass-cyber bg-black/40 border-primary/20 rounded-full py-3 px-6 flex justify-between items-center shadow-2xl backdrop-blur-xl">
        {NAV_ITEMS.map((item) => {
          const isActive = active === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActive(item.id)}
              className={cn(
                "flex flex-col items-center gap-1 transition-all duration-300",
                isActive ? "text-primary scale-110" : "text-foreground/40 hover:text-foreground/60"
              )}
            >
              <item.icon className={cn("w-5 h-5", isActive && "fill-primary/20")} />
              <span className="text-[10px] font-editorial font-bold uppercase tracking-wider">
                {item.label}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
};
