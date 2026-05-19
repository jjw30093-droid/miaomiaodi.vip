'use client';
import Link from 'next/link';
import { useSession, signOut } from 'next-auth/react';

const TEAL = '#00ffc3';

export default function Navbar() {
  const { data: session } = useSession();

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
              <>
                <span className="text-xs font-mono text-slate-500 hidden sm:block">{session.user.name}</span>
                <button
                  onClick={() => signOut()}
                  className="text-xs font-semibold text-slate-400 px-3 py-1.5 rounded-lg hover:text-slate-200 transition-colors"
                  style={{ border: '1px solid rgba(255,255,255,0.10)' }}
                >
                  退出
                </button>
              </>
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
