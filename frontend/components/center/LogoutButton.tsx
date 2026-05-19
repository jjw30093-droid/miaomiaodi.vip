'use client';

import { signOut } from 'next-auth/react';

interface Props {
  isDark: boolean;
}

export default function LogoutButton({ isDark }: Props) {
  return (
    <button
      onClick={() => signOut({ callbackUrl: '/login' })}
      className="w-full h-12 rounded-full font-black text-[15px] italic tracking-tight transition-all active:scale-[0.97]"
      style={isDark ? {
        background: 'rgba(248,113,113,0.08)',
        border: '1px solid rgba(248,113,113,0.35)',
        color: '#f87171',
      } : {
        background: '#fff',
        border: '1px solid rgba(183,0,77,0.35)',
        color: '#b7004d',
      }}
      onMouseEnter={e => {
        if (isDark) (e.currentTarget as HTMLButtonElement).style.background = 'rgba(248,113,113,0.15)';
        else (e.currentTarget as HTMLButtonElement).style.background = '#ffd9de';
      }}
      onMouseLeave={e => {
        if (isDark) (e.currentTarget as HTMLButtonElement).style.background = 'rgba(248,113,113,0.08)';
        else (e.currentTarget as HTMLButtonElement).style.background = '#fff';
      }}
    >
      退出登录
    </button>
  );
}
