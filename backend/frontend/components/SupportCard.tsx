'use client';

import React, { useState } from 'react';
import { ArrowLeft, MessageCircleQuestion, KeyRound, Mail, Send } from 'lucide-react';

interface SupportCardProps {
  onBack: () => void;
}

export const SupportCard: React.FC<SupportCardProps> = ({ onBack }) => {
  const [resetInput, setResetInput] = useState('');

  const handleReset = (e: React.FormEvent) => {
    e.preventDefault();
    // Handle reset logic
    console.log('Reset requested for:', resetInput);
  };

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* Header */}
      <div className="flex items-center mb-4 relative z-10">
        <button 
          onClick={onBack} 
          className="p-1 -ml-1 text-gray-400 hover:text-primary-neon transition-colors rounded-full hover:bg-white/5"
        >
          <ArrowLeft size={20} />
        </button>
      </div>

      {/* Core Interaction Area */}
      <div className="space-y-4 relative z-10">
        
        {/* Section 1: Can't get the code? */}
        <div className="bg-black/40 rounded-xl p-4 border border-white/5 shadow-inner group hover:border-primary-neon/20 transition-colors">
          <div className="flex items-center gap-2 mb-2">
            <MessageCircleQuestion size={16} className="text-primary-neon drop-shadow-[0_0_8px_rgba(0,240,255,0.5)]" />
            <h3 className="text-sm font-bold text-gray-200 tracking-wide font-display uppercase">无法获取暗号？</h3>
          </div>
          <p className="text-[11px] text-gray-400 leading-relaxed font-display">
            请确保在微信搜索公众号 <span className="text-white font-bold tracking-wider">【足球喵喵弟】</span>。关注后，直接回复页面上的 4 位数字暗号即可。
          </p>
        </div>

        {/* Section 2: Forgot Password? */}
        <div className="bg-black/40 rounded-xl p-4 border border-white/5 shadow-inner group hover:border-primary-neon/20 transition-colors">
          <div className="flex items-center gap-2 mb-3">
            <KeyRound size={16} className="text-primary-neon drop-shadow-[0_0_8px_rgba(0,240,255,0.5)]" />
            <h3 className="text-sm font-bold text-gray-200 tracking-wide font-display uppercase">忘记密码？</h3>
          </div>
          <form onSubmit={handleReset} className="flex flex-col gap-2.5">
            <input 
              type="text" 
              value={resetInput}
              onChange={(e) => setResetInput(e.target.value)}
              placeholder="请输入账号或邮箱" 
              className="w-full bg-black/60 border border-white/10 rounded-lg py-3 px-3 text-white placeholder-gray-600 focus:outline-none focus:border-primary-neon/50 focus:ring-1 focus:ring-primary-neon/50 transition-all font-display text-xs shadow-inner" 
              required
            />
            <button 
              type="submit"
              className="w-full relative overflow-hidden rounded-lg bg-gradient-to-r from-primary-neon/20 to-blue-600/20 border border-primary-neon/30 py-3 flex items-center justify-center gap-2 hover:from-primary-neon/40 hover:to-blue-600/40 transition-all duration-300 active:scale-[0.98] shadow-[0_0_15px_rgba(0,240,255,0.1)] hover:shadow-[0_0_20px_rgba(0,240,255,0.2)] group/btn"
            >
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent -translate-x-full group-hover/btn:animate-[shimmer_1.5s_infinite]" />
              <span className="font-display font-bold text-white tracking-widest text-xs drop-shadow-[0_0_5px_rgba(255,255,255,0.5)] uppercase">发送重置指令</span>
              <Send size={12} className="text-primary-neon group-hover/btn:translate-x-1 transition-transform" />
            </button>
          </form>
        </div>

        {/* Section 3: Manual Override */}
        <div className="bg-black/40 rounded-xl p-4 border border-white/5 shadow-inner group hover:border-secondary-magenta/20 transition-colors">
          <div className="flex items-center gap-2 mb-2">
            <Mail size={16} className="text-secondary-magenta drop-shadow-[0_0_8px_rgba(255,0,255,0.5)]" />
            <h3 className="text-sm font-bold text-gray-200 tracking-wide font-display uppercase">人工介入</h3>
          </div>
          <p className="text-[11px] text-gray-400 leading-relaxed font-display">
            如遇系统故障，请发送邮件至 <a href="mailto:support@miaomiaodi.cc" className="text-primary-neon hover:underline">support@miaomiaodi.cc</a>，或在公众号留言『人工』。
          </p>
        </div>

      </div>

      {/* Footer */}
      <div className="flex justify-center items-center mt-8 pt-5 border-t border-white/10 relative z-10">
        <button 
          onClick={onBack} 
          className="text-xs text-gray-500 hover:text-white transition-colors font-display tracking-widest uppercase"
        >
          返回登录节点
        </button>
      </div>
    </div>
  );
};
