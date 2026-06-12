'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Activity, Cpu, Archive, User } from 'lucide-react';

interface Props {
  isDark: boolean;
}

// 图标用 lucide SVG，不依赖 Google Fonts（国内加载不到字体会裸显英文连字名）
const NAV_ITEMS = [
  { href: '/',        Icon: Activity, label: '赛事' },
  { href: '/model',   Icon: Cpu,      label: '模型' },
  { href: '/archive', Icon: Archive,  label: '归档' },
  { href: '/center',  Icon: User,     label: '我的' },
];

export default function BottomNav({ isDark }: Props) {
  const pathname = usePathname();

  if (isDark) {
    return (
      <div className="fixed bottom-0 left-0 right-0 max-w-md mx-auto px-6 pb-6 z-50 pointer-events-none">
        <nav className="bg-[#09090b] border border-zinc-800 rounded-full px-4 py-2 flex justify-between items-center shadow-[0_-4px_20px_rgba(0,0,0,0.5)] pointer-events-auto">
          {NAV_ITEMS.map(item => {
            const isActive = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
            return (
              <Link key={item.href} href={item.href}>
                {isActive ? (
                  <div className="flex flex-col items-center gap-0.5 bg-primary-neon text-white rounded-full px-4 py-1.5">
                    <item.Icon size={18} />
                    <span className="text-[13px] font-bold leading-none">{item.label}</span>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-0.5 text-zinc-400 px-4 py-1.5">
                    <item.Icon size={18} />
                    <span className="text-[13px] font-bold leading-none">{item.label}</span>
                  </div>
                )}
              </Link>
            );
          })}
        </nav>
      </div>
    );
  }

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 bg-white/90 backdrop-blur-[20px] rounded-t-[1.5rem] shadow-[0px_-8px_24px_rgba(25,28,29,0.06)] flex justify-around items-center px-4 pb-6 pt-2">
      {NAV_ITEMS.map(item => {
        const isActive = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`flex flex-col items-center justify-center transition-all active:scale-95 duration-150 ${
              isActive
                ? 'bg-[#b7004d] text-white rounded-full px-5 py-1.5 shadow-md shadow-[#b7004d]/20'
                : 'text-[#005faf] p-2'
            }`}
          >
            <item.Icon size={22} className="mb-0.5" />
            <span className="text-[13px] font-bold leading-none">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
