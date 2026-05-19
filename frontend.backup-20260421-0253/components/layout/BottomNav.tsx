'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Heart, History, Star, User } from 'lucide-react';
import { cn } from '@/lib/utils';

const NAV_ITEMS = [
  { id: 'matches',  label: 'Matches',  icon: Heart,   href: '/' },
  { id: 'history',  label: 'History',  icon: History, href: '/archive' },
  { id: 'vip',      label: 'VIP',      icon: Star,    href: '/center?tab=vip' },
  { id: 'me',       label: '我的',     icon: User,    href: '/center?tab=profile' },
];

export const BottomNav = () => {
  const pathname = usePathname();

  const getActive = (href: string) => {
    if (href === '/') return pathname === '/';
    return pathname.startsWith(href.split('?')[0]);
  };

  return (
    <div className="fixed bottom-10 left-1/2 -translate-x-1/2 z-50 w-[90%] max-w-sm">
      <div className="glass-cyber bg-black/40 border-primary/20 rounded-full py-3 px-6 flex justify-between items-center shadow-2xl backdrop-blur-xl">
        {NAV_ITEMS.map((item) => {
          const isActive = getActive(item.href);
          return (
            <Link
              key={item.id}
              href={item.href}
              className={cn(
                "flex flex-col items-center gap-1 transition-all duration-300",
                isActive ? "text-primary scale-110" : "text-foreground/40 hover:text-foreground/60"
              )}
            >
              <item.icon className={cn("w-5 h-5", isActive && "fill-primary/20")} />
              <span className="text-[10px] font-editorial font-bold uppercase tracking-wider">
                {item.label}
              </span>
            </Link>
          );
        })}
      </div>
    </div>
  );
};
