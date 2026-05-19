'use client';

import React, { useEffect, useState } from 'react';
import { Sun, Moon, Bell } from 'lucide-react';
import { cn } from '@/lib/utils';
import Image from 'next/image';

export const HomeHeader = () => {
  const [isDark, setIsDark] = useState(true);

  // Sync with HTML class
  useEffect(() => {
    const root = window.document.documentElement;
    if (isDark) {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
  }, [isDark]);

  return (
    <header className="px-5 pt-8 pb-4 relative z-20">
      {/* Top Banner Marquee */}
      <div className="flex justify-center mb-6">
        <div className="glass-cyber py-1 px-4 rounded-full flex items-center gap-2 border-primary/30 max-w-fit">
          <div className="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center overflow-hidden border border-primary/20">
             <Image src="/cat_avatar.png" width={32} height={32} alt="Avatar" className="object-cover" />
          </div>
          <span className="text-editorial text-xs font-bold uppercase tracking-wider text-primary">
            Welcome fan of <span className="text-secondary">Football Meow</span>
          </span>
          <button 
            onClick={() => setIsDark(!isDark)}
            className="ml-2 w-6 h-6 flex items-center justify-center hover:scale-110 transition-transform"
          >
            {isDark ? <Sun className="w-4 h-4 text-primary" /> : <Moon className="w-4 h-4 text-foreground" />}
          </button>
        </div>
      </div>

      {/* Main Logo & Title */}
      <div className="flex flex-col items-center gap-2">
        <div className="relative w-32 h-20 mb-2">
             {/* Logo Placeholder - assuming cats + ball logo */}
             <div className="absolute inset-0 flex items-center justify-center">
                <Image src="/logo_cats.png" width={128} height={80} alt="Logo" className="object-contain" />
             </div>
        </div>
        <h1 className="text-editorial text-4xl font-black italic uppercase tracking-tighter text-foreground text-center">
          喵弟数据研究室
        </h1>

      </div>
    </header>
  );
};
