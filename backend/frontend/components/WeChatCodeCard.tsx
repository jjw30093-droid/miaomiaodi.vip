'use client';

import React, { useState, useEffect } from 'react';
import { MessageCircle, Loader2, ShieldAlert, KeyRound, HelpCircle } from 'lucide-react';

export const WeChatCodeCard = ({ onSwitchToPassword, onSwitchToSupport }: { onSwitchToPassword: () => void, onSwitchToSupport: () => void }) => {
  const [secretCode, setSecretCode] = useState('7592');
  const [timeLeft, setTimeLeft] = useState(300);

  useEffect(() => {
    if (timeLeft <= 0) return;
    const timer = setInterval(() => setTimeLeft(prev => prev - 1), 1000);
    return () => clearInterval(timer);
  }, [timeLeft]);

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* Core Interaction Area */}
      <div className="flex flex-col items-center bg-black/40 rounded-2xl p-5 border border-white/5 relative z-10 shadow-inner">
        
        {/* WeChat Icon */}
        <div className="flex items-center justify-center w-12 h-12 rounded-full bg-[#07C160]/10 border border-[#07C160]/30 mb-3 shadow-[0_0_15px_rgba(7,193,96,0.2)]">
          <MessageCircle className="text-[#07C160]" size={24} />
        </div>
        
        <p className="text-gray-300 text-sm text-center leading-relaxed mb-4">
          微信搜索并关注公众号 <br/>
          <span className="text-white font-bold tracking-wider">[足球喵喵弟]</span><br/>
          发送下方暗号，即可自动同步并登录。
        </p>

        {/* The Code */}
        <div className="relative group mb-5">
          <div className="absolute inset-0 bg-primary-neon/20 blur-xl rounded-full group-hover:bg-primary-neon/30 transition-all duration-500" />
          <div className="text-5xl sm:text-6xl font-display font-black text-primary-neon tracking-[0.2em] ml-[0.2em] drop-shadow-[0_0_20px_rgba(0,240,255,0.8)] relative z-10">
            {secretCode}
          </div>
        </div>

        {/* Warning Text */}
        <div className="flex items-center gap-2 text-xs text-secondary-magenta/90 bg-secondary-magenta/10 px-3 py-1.5 rounded-full border border-secondary-magenta/20">
          <ShieldAlert size={14} />
          <span>暗号将在 <span className="font-mono font-bold">{formatTime(timeLeft)}</span> 后失效，请勿泄露。</span>
        </div>
      </div>

      {/* Status Area */}
      <div className="mt-6 mb-2 flex flex-col items-center justify-center gap-2 relative z-10">
        <div className="relative flex items-center justify-center">
          <Loader2 size={24} className="text-primary-neon animate-spin" />
          <div className="absolute inset-0 bg-primary-neon/30 blur-md rounded-full animate-pulse" />
        </div>
        <p className="text-primary-neon/80 text-xs font-mono animate-pulse tracking-wide">
          正在等待微信同步...
        </p>
      </div>

      {/* Footer Links */}
      <div className="flex justify-between items-center mt-6 pt-5 border-t border-white/10 relative z-10">
        <button 
          onClick={onSwitchToPassword}
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-white transition-colors font-mono"
        >
          <KeyRound size={14} />
          账号密码登录
        </button>
        <button 
          onClick={onSwitchToSupport}
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-white transition-colors font-mono"
        >
          <HelpCircle size={14} />
          遇到问题？
        </button>
      </div>
    </div>
  );
};
