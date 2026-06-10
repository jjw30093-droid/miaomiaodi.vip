'use client';

export const dynamic = 'force-dynamic';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { signIn } from 'next-auth/react';
import { ArrowLeft } from 'lucide-react';
import { WeChatCodeCard } from '@/components/WeChatCodeCard';
import { PasswordLoginCard } from '@/components/PasswordLoginCard';
import { SupportCard } from '@/components/SupportCard';
import { useTheme } from '@/components/ThemeProvider';
import ThemeToggleButton from '@/components/ThemeToggleButton';

const _enableWechat = process.env.NEXT_PUBLIC_ENABLE_WECHAT_LOGIN === 'true';

export default function LoginPage() {
  // 微信关闭时默认展示密码登录；微信开启时默认展示微信
  const [viewState, setViewState] = useState<'code' | 'password' | 'support'>(_enableWechat ? 'code' : 'password');
  const [prevState, setPrevState] = useState<'code' | 'password'>(_enableWechat ? 'code' : 'password');
  const [tokenLoginStatus, setTokenLoginStatus] = useState<string>('');
  // 账密 tab 可见性：ENV flag 默认 false；?dev=1 可在运行时强制显示（供运营测试）
  const [showPasswordTab, setShowPasswordTab] = useState(
    process.env.NEXT_PUBLIC_ENABLE_PASSWORD_LOGIN === 'true'
  );
  const router = useRouter();
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  // 支持 ?token=<api_token> 直接登录（管理员测试用途）
  // ?dev=1 强制显示账密 tab（供运营在生产环境临时测试，不写入任何持久化）
  // 用 window.location.search 避免 useSearchParams 的 SSR prerender 问题
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);

    // dev 模式：强制显示账密 tab
    if (params.get('dev') === '1') {
      setShowPasswordTab(true);
    }

    const token = params.get('token');
    if (!token) return;
    setTokenLoginStatus('正在验证身份...');
    signIn('wechat', { api_token: token, redirect: false })
      .then((res) => {
        if (res?.error) {
          setTokenLoginStatus('Token 无效或已过期');
        } else {
          setTokenLoginStatus('登录成功，正在跳转...');
          const callbackUrl = params.get('callbackUrl') || '/';
          router.replace(callbackUrl);
        }
      })
      .catch(() => setTokenLoginStatus('登录失败，请重试'));
  }, []);

  // 若账密 tab 被隐藏时用户已在 password 视图，强制回到 code
  useEffect(() => {
    if (!showPasswordTab && viewState === 'password') {
      setViewState('code');
    }
  }, [showPasswordTab]);

  const handleGoToSupport = () => {
    if (viewState === 'code' || viewState === 'password') {
      setPrevState(viewState);
    }
    setViewState('support');
  };

  // 如果有 ?token= 参数，显示简洁的状态页
  if (tokenLoginStatus) {
    return (
      <div suppressHydrationWarning className={`relative min-h-screen overflow-hidden font-sans flex items-center justify-center p-4 ${isDark ? 'bg-[#09090b]' : 'bg-[#f8fafb]'}`}>
        <div className="relative z-10 text-center space-y-4">
          <div suppressHydrationWarning className={`w-8 h-8 border-2 rounded-full animate-spin mx-auto ${isDark ? 'border-[#E91E63]/40 border-t-[#E91E63]' : 'border-[#b7004d]/30 border-t-[#b7004d]'}`} />
          <p suppressHydrationWarning className={`text-sm tracking-widest ${isDark ? 'text-zinc-400' : 'text-[#5b3f43]'}`}>{tokenLoginStatus}</p>
        </div>
      </div>
    );
  }

  if (!isDark) {
    // ── Stitch Light Mode Login ─────────────────────────────────────
    return (
      <div className="relative min-h-screen overflow-hidden font-sans flex flex-col" style={{ background: 'radial-gradient(ellipse at top, #f2f4f5 0%, #f8fafb 100%)' }}>
        {/* Top App Bar */}
        <header className="bg-white/80 backdrop-blur-lg w-full z-50 flex items-center justify-between px-5 py-4 shadow-[0px_4px_16px_rgba(25,28,29,0.06)]">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center justify-center w-9 h-9 rounded-full hover:bg-[#f2f4f5] transition-colors">
              <ArrowLeft size={18} className="text-[#191c1d]" />
            </Link>
            <h1 className="text-lg font-black text-[#b7004d] tracking-tighter" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
              喵弟数据研究室
            </h1>
          </div>
          <ThemeToggleButton />
        </header>

        {/* Main */}
        <main className="flex-1 flex flex-col justify-center items-center px-5 py-10">
          <div className="w-full max-w-md bg-white rounded-[1.5rem] shadow-[0px_12px_32px_rgba(25,28,29,0.08)] relative overflow-hidden p-7">
            {/* Background ghost icon */}
            <div className="absolute -top-8 -right-8 opacity-5 pointer-events-none">
              <span className="material-symbols-outlined text-[10rem] text-[#b7004d]" style={{ fontVariationSettings: "'FILL' 1" }}>science</span>
            </div>

            {/* Header text */}
            {viewState !== 'support' && (
              <div className="mb-6 relative z-10">
                <h2 className="text-2xl font-bold text-[#191c1d] mb-1" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>登录</h2>
                <p className="text-sm text-[#5b3f43]">访问精准数据和量化预测模型</p>
              </div>
            )}

            {/* Switch tabs — 仅当微信登录启用且 showPasswordTab=true 时渲染 */}
            {viewState !== 'support' && _enableWechat && showPasswordTab && (
              <div className="flex gap-1 bg-[#f2f4f5] rounded-full p-1 mb-6 relative z-10">
                <button
                  onClick={() => setViewState('code')}
                  className={`flex-1 py-2 rounded-full text-sm font-bold transition-all ${viewState === 'code' ? 'bg-white text-[#191c1d] shadow-sm' : 'text-[#5b3f43]'}`}
                >
                  微信扫码
                </button>
                <button
                  onClick={() => setViewState('password')}
                  className={`flex-1 py-2 rounded-full text-sm font-bold transition-all ${viewState === 'password' ? 'bg-white text-[#191c1d] shadow-sm' : 'text-[#5b3f43]'}`}
                >
                  密码登录
                </button>
              </div>
            )}

            {/* Dynamic content */}
            <div className="relative z-10">
              {_enableWechat && viewState === 'code' && (
                <WeChatCodeCard
                  onSwitchToPassword={showPasswordTab ? () => setViewState('password') : undefined}
                  onSwitchToSupport={handleGoToSupport}
                />
              )}
              {viewState === 'password' && (
                <PasswordLoginCard
                  onSwitchToCode={() => setViewState('code')}
                  onSwitchToSupport={handleGoToSupport}
                />
              )}
              {viewState === 'support' && (
                <SupportCard onBack={() => setViewState(prevState)} />
              )}
            </div>

          </div>
        </main>

        {/* Footer */}
        <footer className="py-6 text-center text-[#5b3f43] text-xs">
          <p>© 2024 喵弟数据研究室</p>
        </footer>
      </div>
    );
  }

  // ── Dark Mode Login (Stitch _3) ─────────────────────────────────────────────
  return (
    <div className="relative min-h-screen overflow-hidden font-sans flex flex-col justify-center items-center p-6 bg-[#09090b]">
      {/* Radial gradient overlays */}
      <div
        className="absolute inset-0 z-0 pointer-events-none"
        style={{ background: 'radial-gradient(circle at top right, rgba(233,30,99,0.05), transparent 50%), radial-gradient(circle at bottom left, rgba(0,95,175,0.05), transparent 50%)' }}
      />

      {/* Back button top-left */}
      <div className="absolute top-4 left-4 z-20">
        <Link href="/" className="w-9 h-9 flex items-center justify-center rounded-full bg-white/10 border border-white/15 backdrop-blur-md hover:bg-white/20 active:scale-95 transition-all shadow-md">
          <ArrowLeft size={18} className="text-zinc-300" />
        </Link>
      </div>

      {/* ThemeToggleButton top-right */}
      <div className="absolute top-4 right-4 z-20">
        <ThemeToggleButton />
      </div>

      <main className="w-full max-w-md z-10 relative">
        {/* Logo + title */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-zinc-900 border border-zinc-800 shadow-[0px_12px_32px_rgba(0,0,0,0.5)] mb-6">
            <span
              className="material-symbols-outlined text-3xl text-[#E91E63]"
              style={{ fontVariationSettings: "'FILL' 1" }}
            >
              pets
            </span>
          </div>
          <h1
            className="text-3xl font-bold tracking-tight text-zinc-50 mb-2"
            style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}
          >
            欢迎回来
          </h1>
          <p className="text-sm text-zinc-400">欢迎回到喵弟数据研究室</p>
        </div>

        {/* Form Card */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-8 shadow-[0px_24px_48px_rgba(0,0,0,0.4)]">
          {/* Tab switcher — 仅当微信登录启用且 showPasswordTab=true 时渲染 */}
          {viewState !== 'support' && _enableWechat && showPasswordTab && (
            <div className="flex gap-1 bg-zinc-950 rounded-full p-1 mb-6">
              <button
                onClick={() => setViewState('code')}
                className={`flex-1 py-2 rounded-full text-sm font-bold transition-all ${viewState === 'code' ? 'bg-[#E91E63] text-white' : 'text-zinc-400'}`}
              >
                微信扫码
              </button>
              <button
                onClick={() => setViewState('password')}
                className={`flex-1 py-2 rounded-full text-sm font-bold transition-all ${viewState === 'password' ? 'bg-[#E91E63] text-white' : 'text-zinc-400'}`}
              >
                密码登录
              </button>
            </div>
          )}

          {/* Dynamic content */}
          {_enableWechat && viewState === 'code' && (
            <WeChatCodeCard
              onSwitchToPassword={showPasswordTab ? () => setViewState('password') : undefined}
              onSwitchToSupport={handleGoToSupport}
            />
          )}
          {viewState === 'password' && (
            <PasswordLoginCard
              onSwitchToCode={() => setViewState('code')}
              onSwitchToSupport={handleGoToSupport}
            />
          )}
          {viewState === 'support' && (
            <SupportCard onBack={() => setViewState(prevState)} />
          )}

        </div>
      </main>
    </div>
  );
}
