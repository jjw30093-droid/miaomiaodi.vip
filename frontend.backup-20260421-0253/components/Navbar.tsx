'use client';
import { useState, useRef, useEffect } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { useSession, signOut } from 'next-auth/react';
import { useRouter } from 'next/navigation';

const TEAL = '#00ffc3';

export default function Navbar() {
  const { data: session } = useSession();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Click outside to close
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    if (menuOpen) document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [menuOpen]);

  const avatarUrl = (session?.user as any)?.avatarUrl as string | undefined;
  const isVip = (session?.user as any)?.role === 'vip';

  const avatarSrc = avatarUrl
    ? (avatarUrl.startsWith('/static') ? `http://localhost:8000${avatarUrl}` : avatarUrl)
    : null;

  return (
    <nav
      className="fixed top-0 left-0 right-0 z-50 flex justify-center"
      style={{
        background: 'rgba(8, 12, 26, 0.60)',
        backdropFilter: 'blur(20px) saturate(150%)',
        WebkitBackdropFilter: 'blur(20px) saturate(150%)',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}
    >
      <div className="w-full max-w-7xl px-5 sm:px-8 lg:px-10">
        <div className="flex justify-between items-center h-16">

          {/* Brand */}
          <Link href="/" className="flex items-center gap-2 tracking-tight">
            <span className="text-2xl">⚽</span>
            <span className="hidden sm:block">
              <span className="text-white font-black text-xl tracking-tight">喵弟</span>
              <span
                className="ml-1.5 text-lg font-medium"
                style={{ color: TEAL, textShadow: '0 0 10px rgba(0,255,195,0.3)' }}
              >
                量化实验室
              </span>
            </span>
          </Link>

          {/* Nav links */}
          <div className="hidden md:flex items-center gap-8">
            {[['/', '主页'], ['/about', '功能介绍']].map(([href, label]) => (
              <Link
                key={href}
                href={href}
                className="text-sm font-medium text-slate-400 hover:text-slate-100 transition-colors"
              >
                {label}
              </Link>
            ))}
          </div>

          {/* Auth area */}
          <div className="flex items-center gap-3">
            {session?.user ? (
              <div className="relative" ref={menuRef}>
                {/* 头像按钮 */}
                <button
                  onClick={() => setMenuOpen(v => !v)}
                  className="flex items-center gap-2 transition-all active:scale-95"
                >
                  <div
                    className="relative w-9 h-9 rounded-xl overflow-hidden flex-shrink-0"
                    style={{
                      border: isVip
                        ? '2px solid rgba(191,165,93,0.6)'
                        : '2px solid rgba(0,255,195,0.3)',
                    }}
                  >
                    {avatarSrc ? (
                      <Image src={avatarSrc} alt="avatar" fill className="object-cover" unoptimized />
                    ) : (
                      <span className="flex items-center justify-center w-full h-full text-base" style={{ background: '#12161b' }}>
                        🐱
                      </span>
                    )}
                  </div>
                  {isVip && (
                    <span
                      className="hidden sm:block text-xs font-black px-2 py-0.5 rounded-full"
                      style={{ background: 'rgba(191,165,93,0.15)', color: '#BFA55D', border: '1px solid rgba(191,165,93,0.3)' }}
                    >
                      VIP
                    </span>
                  )}
                  {!isVip && (
                    <span className="hidden sm:block text-xs font-mono text-slate-500">
                      {session.user.name}
                    </span>
                  )}
                </button>

                {/* 下拉菜单（click-toggle，移动端友好）*/}
                {menuOpen && (
                  <div
                    className="absolute right-0 top-12 w-44 rounded-2xl overflow-hidden z-50"
                    style={{
                      background: '#0d0f14',
                      border: '1px solid rgba(255,255,255,0.1)',
                      boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
                    }}
                  >
                    <Link
                      href="/center?tab=profile"
                      onClick={() => setMenuOpen(false)}
                      className="flex items-center gap-3 px-4 py-3 text-sm transition-colors hover:bg-white/5"
                      style={{ color: 'rgba(250,250,252,0.8)' }}
                    >
                      <span>👤</span> 个人中心
                    </Link>
                    <Link
                      href="/center?tab=vip"
                      onClick={() => setMenuOpen(false)}
                      className="flex items-center gap-3 px-4 py-3 text-sm transition-colors hover:bg-white/5"
                      style={{ color: 'rgba(250,250,252,0.8)' }}
                    >
                      <span>⭐</span> VIP 状态
                    </Link>
                    <div style={{ borderTop: '1px solid rgba(255,255,255,0.07)' }} />
                    <button
                      onClick={() => { setMenuOpen(false); signOut(); }}
                      className="w-full flex items-center gap-3 px-4 py-3 text-sm transition-colors hover:bg-white/5"
                      style={{ color: 'rgba(255,80,80,0.8)' }}
                    >
                      <span>🚪</span> 退出登录
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <>
                <Link
                  href="/login"
                  className="text-sm font-medium text-slate-400 hover:text-slate-100 transition-colors px-3 py-1.5"
                >
                  登录
                </Link>
                <Link
                  href="/login?tab=register"
                  className="text-xs font-black px-5 py-2.5 rounded-lg text-[#080c1a] transition-all active:scale-[0.97] hover:scale-[1.02]"
                  style={{
                    background: TEAL,
                    boxShadow: '0 0 20px rgba(0,255,195,0.35)',
                  }}
                >
                  免费试用 →
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
