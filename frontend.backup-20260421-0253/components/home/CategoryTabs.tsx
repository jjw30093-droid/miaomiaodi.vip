'use client';

import React, { useState } from 'react';
import { cn } from '@/lib/utils';

const CATEGORIES = ["Today", "Tomorrow", "EPL", "La Liga", "Serie A", "Bundesliga", "Ligue 1"];

export const CategoryTabs = () => {
  const [active, setActive] = useState("Today");

  return (
    <div className="w-full overflow-x-auto no-scrollbar px-5 py-4 scroll-smooth">
      <div className="flex gap-4 min-w-max">
        {CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={() => setActive(cat)}
            className={cn(
              "px-6 py-2 rounded-full text-xs font-bold font-editorial uppercase tracking-widest transition-all duration-300",
              active === cat 
                ? "glass-cyber bg-primary/20 border-primary text-primary" 
                : "glass-cyber bg-transparent border-white/5 text-foreground/40 hover:text-foreground hover:bg-white/5"
            )}
          >
            {cat}
          </button>
        ))}
      </div>
    </div>
  );
};
