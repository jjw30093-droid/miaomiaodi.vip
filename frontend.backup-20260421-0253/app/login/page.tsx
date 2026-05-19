'use client';

export const dynamic = 'force-dynamic';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { signIn } from 'next-auth/react';
import { ArrowLeft } from 'lucide-react';
import { BackgroundEffects } from '@/components/BackgroundEffects';
import { WeChatCodeCard } from '@/components/WeChatCodeCard';
import { PasswordLoginCard } from '@/components/PasswordLoginCard';
import { SupportCard } from '@/components/SupportCard';

export default function LoginPage() {
  const [viewState, setViewState] = useState<'code' | 'password' | 'support'>('code');
  const [prevState, setPrevState] = useState<'code' | 'password'>('code');
  const [tokenLoginStatus, setTokenLoginStatus] = useState<string>('');
  const router = useRouter();

  // 支持 ?token=<api_token> 直接登录（管理员测试用途）
  // 用 window.location.search 避免 useSearchParams 的 SSR prerender 问题
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
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

  const handleGoToSupport = () => {
    if (viewState === 'code' || viewState === 'password') {
      setPrevState(viewState);
    }
    setViewState('support');
  };

  // 如果有 ?token= 参数，显示简洁的状态页
  if (tokenLoginStatus) {
    return (
      <div className="relative min-h-screen bg-gradient-to-br from-slate-950 via-surface-dim to-black overflow-hidden font-sans flex items-center justify-center p-4">
        <BackgroundEffects />
        <div className="relative z-10 text-center space-y-4">
          <div className="w-8 h-8 border-2 border-primary-neon/40 border-t-primary-neon rounded-full animate-spin mx-auto" />
          <p className="text-sm text-white/60 tracking-widest">{tokenLoginStatus}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative min-h-screen bg-gradient-to-br from-slate-950 via-surface-dim to-black overflow-hidden font-sans flex items-center justify-center p-4">
      <BackgroundEffects />
      
      <div className="relative z-10 w-full max-w-md">
        {/* Glassmorphism Card */}
        <div className="glass-panel rounded-3xl p-6 shadow-[0_0_40px_rgba(0,240,255,0.15)] border border-primary-neon/30 relative overflow-hidden backdrop-blur-xl bg-glass-bg transition-all duration-500">
          
          {/* Return to Home Button */}
          {viewState !== 'support' && (
            <Link
              href="/"
              className="absolute top-4 left-4 sm:top-5 sm:left-5 z-50 flex items-center justify-center p-2 rounded-full text-text-secondary hover:text-primary-neon hover:bg-glass-bg transition-all duration-300 group"
            >
              <ArrowLeft size={20} className="group-hover:-translate-x-1 transition-transform duration-300" />
            </Link>
          )}

          {/* Decorative corner accents */}
          <div className="absolute top-0 left-0 w-12 h-12 border-t-2 border-l-2 border-primary-neon/50 rounded-tl-3xl font-display" />
          <div className="absolute bottom-0 right-0 w-12 h-12 border-b-2 border-r-2 border-primary-neon/50 rounded-br-3xl font-display" />
          
          {/* Ambient inner glow */}
          <div className="absolute top-0 right-0 w-32 h-32 bg-primary-neon/5 blur-[50px] rounded-full pointer-events-none" />

          {/* Header (Hidden in Support Mode to save space) */}
          {viewState !== 'support' && (
            <div className="flex flex-col items-center justify-center mb-6 text-center relative z-10">
              <div className="relative w-20 h-20 flex-shrink-0">
                <div className="absolute inset-0 bg-primary-neon/20 rounded-full blur-md animate-pulse-glow" />
                <img 
                  src="/logo_meow.jpg"
                  alt="Logo" 
                  className="w-full h-full object-contain drop-shadow-[0_0_15px_rgba(0,240,255,0.8)] relative z-10 mix-blend-screen"
                />
              </div>
            </div>
          )}

          {/* Dynamic Content */}
          {viewState === 'code' && (
            <WeChatCodeCard 
              onSwitchToPassword={() => setViewState('password')} 
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
            <SupportCard 
              onBack={() => setViewState(prevState)} 
            />
          )}

          {/* Register Link */}
          {viewState !== 'support' && (
            <div className="mt-6 text-center relative z-10">
              <p className="text-xs text-text-secondary font-display uppercase tracking-widest">
                还没有账号？{' '}
                <Link href="/register" className="text-secondary-magenta hover:text-pink-400 transition-colors font-bold">
                  注册新账号
                </Link>
              </p>
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
