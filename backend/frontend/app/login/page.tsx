'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { BackgroundEffects } from '@/components/BackgroundEffects';
import { WeChatCodeCard } from '@/components/WeChatCodeCard';
import { PasswordLoginCard } from '@/components/PasswordLoginCard';
import { SupportCard } from '@/components/SupportCard';

export default function LoginPage() {
  const [viewState, setViewState] = useState<'code' | 'password' | 'support'>('code');
  const [prevState, setPrevState] = useState<'code' | 'password'>('code');

  const handleGoToSupport = () => {
    if (viewState === 'code' || viewState === 'password') {
      setPrevState(viewState);
    }
    setViewState('support');
  };

  return (
    <div className="relative min-h-screen bg-gradient-to-br from-slate-950 via-[#060918] to-black overflow-hidden font-sans flex items-center justify-center p-4">
      <BackgroundEffects />
      
      <div className="relative z-10 w-full max-w-md">
        <div className="glass-panel rounded-3xl p-6 sm:p-8 shadow-[0_0_40px_rgba(0,240,255,0.15)] border border-primary-neon/30 relative overflow-hidden backdrop-blur-xl bg-white/5 transition-all duration-500">
          
          {/* Return to Home Button - ArrowLeft 返回 */}
          <Link
            href="/"
            className="absolute top-4 left-4 sm:top-5 sm:left-5 z-50 flex items-center justify-center p-2 rounded-full text-gray-400 hover:text-primary-neon hover:bg-white/5 transition-all duration-300 group"
          >
            <ArrowLeft size={20} className="group-hover:-translate-x-1 transition-transform duration-300" />
          </Link>

          {/* Decorative corner accents */}
          <div className="absolute top-0 left-0 w-12 h-12 border-t-2 border-l-2 border-primary-neon/50 rounded-tl-3xl" />
          <div className="absolute bottom-0 right-0 w-12 h-12 border-b-2 border-r-2 border-primary-neon/50 rounded-br-3xl" />
          
          {/* Ambient inner glow */}
          <div className="absolute top-0 right-0 w-32 h-32 bg-primary-neon/5 blur-[50px] rounded-full pointer-events-none" />

          {/* Logo Header (Hidden in Support Mode) */}
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
            <div className="mt-6 text-center">
              <p className="text-xs text-gray-500 font-display">
                还没有账号？{' '}
                <Link href="/register" className="text-secondary-magenta hover:text-pink-400 transition-colors font-bold tracking-wide">
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
