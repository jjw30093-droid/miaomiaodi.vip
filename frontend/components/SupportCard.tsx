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
          className="p-1 -ml-1 text-stone-400 dark:text-zinc-500 hover:text-primary-neon transition-colors rounded-full hover:bg-stone-100 dark:hover:bg-zinc-800"
        >
          <ArrowLeft size={20} />
        </button>
      </div>

      {/* Core Interaction Area */}
      <div className="space-y-4 relative z-10">
        
        {/* Section 1: Can't get the code? */}
        <div className="bg-stone-50 dark:bg-zinc-800 rounded-xl p-4 border border-stone-200 dark:border-zinc-700 group hover:border-primary-neon/30 transition-colors">
          <div className="flex items-center gap-2 mb-2">
            <MessageCircleQuestion size={16} className="text-primary-neon" />
            <h3 className="text-sm font-bold text-stone-900 dark:text-white tracking-wide">无法获取暗号？</h3>
          </div>
          <p className="text-xs font-bold text-stone-600 dark:text-zinc-300 leading-relaxed">
            请确保在微信搜一搜中准确搜索公众号<span className="font-bold tracking-wider text-stone-900 dark:text-white">【足球喵喵弟】</span>。关注后，直接在对话框回复页面上的 4 位数字即可。
          </p>
        </div>

        {/* Section 2: Forgot Password? */}
        <div className="bg-stone-50 dark:bg-zinc-800 rounded-xl p-4 border border-stone-200 dark:border-zinc-700 group hover:border-primary-neon/30 transition-colors">
          <div className="flex items-center gap-2 mb-3">
            <KeyRound size={16} className="text-primary-neon" />
            <h3 className="text-sm font-bold text-stone-900 dark:text-white tracking-wide">忘记密码？</h3>
          </div>
          <form onSubmit={handleReset} className="flex flex-col gap-2.5">
            <input
              type="text"
              value={resetInput}
              onChange={(e) => setResetInput(e.target.value)}
              placeholder="请输入您的 Geek ID 或绑定的邮箱"
              className="w-full bg-white dark:bg-zinc-900 border border-stone-200 dark:border-zinc-600 rounded-lg py-2.5 px-3 text-stone-900 dark:text-white font-bold placeholder-stone-400 dark:placeholder-zinc-500 focus:outline-none focus:border-primary-neon/50 focus:ring-1 focus:ring-primary-neon/50 transition-all font-mono text-xs"
              required
            />
            <button
              type="submit"
              className="w-full rounded-lg bg-primary-neon hover:bg-red-700 text-white py-2.5 flex items-center justify-center gap-2 transition-colors active:scale-[0.98] shadow-sm font-semibold"
            >
              <span className="font-display font-bold tracking-widest text-xs">发送重置指令</span>
              <Send size={12} className="group-hover/btn:translate-x-1 transition-transform" />
            </button>
          </form>
        </div>

        {/* Section 3: Manual Override */}
        <div className="bg-stone-50 dark:bg-zinc-800 rounded-xl p-4 border border-stone-200 dark:border-zinc-700 group hover:border-[var(--secondary-magenta)]/20 transition-colors">
          <div className="flex items-center gap-2 mb-2">
            <Mail size={16} className="text-[var(--secondary-magenta)]" />
            <h3 className="text-sm font-bold text-stone-900 dark:text-white tracking-wide">人工介入</h3>
          </div>
          <p className="text-xs font-bold text-stone-600 dark:text-zinc-300 leading-relaxed">
            如遇系统故障，请发送邮件至 <a href="mailto:support@miaomiaodi.vip" className="text-primary-neon hover:underline font-mono font-bold">support@miaomiaodi.vip</a>，或在公众号留言『人工』。
          </p>
        </div>

      </div>

      {/* Footer */}
      <div className="flex justify-center items-center mt-6 pt-5 border-t border-stone-200 dark:border-zinc-700 relative z-10">
        <button
          onClick={onBack}
          className="text-xs text-stone-500 dark:text-zinc-500 hover:text-stone-900 dark:hover:text-white transition-colors font-mono tracking-widest"
        >
          返回登录节点
        </button>
      </div>
    </div>
  );
};
