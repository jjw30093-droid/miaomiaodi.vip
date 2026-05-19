'use client';

import React, { useState } from 'react';
import { signIn } from 'next-auth/react';
import { useRouter, useSearchParams } from 'next/navigation';
import { User, Lock, Eye, EyeOff, ArrowRight, MessageCircle } from 'lucide-react';

interface PasswordLoginCardProps {
  onSwitchToCode: () => void;
  onSwitchToSupport: () => void;
}

export const PasswordLoginCard: React.FC<PasswordLoginCardProps> = ({ onSwitchToCode, onSwitchToSupport }) => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get('callbackUrl') || '/';

  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    
    try {
      const result = await signIn('credentials', {
        redirect: false,
        username,
        password,
        callbackUrl,
      });
      
      if (result?.error) {
        if (result.error === 'CredentialsSignin') {
          setError('用户名或密码错误，请假装输入 admin/admin');
        } else {
          setError(result.error);
        }
      } else if (result?.ok) {
        router.push(callbackUrl);
        router.refresh();
      }
    } catch (err) {
      setError('连接实验室节点失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
      <form onSubmit={handleSubmit} className="space-y-5 relative z-10">
        
        {error && (
          <div className="p-3.5 bg-rose-500/10 border border-rose-500/30 rounded-xl text-rose-500 text-xs font-bold text-center animate-shake">
            {error}
          </div>
        )}

        <div className="space-y-1">
          <label className="text-xs font-display font-bold text-gray-400 uppercase tracking-widest ml-1">身份识别码 / Email</label>
          <div className="relative group">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-gray-500 group-focus-within:text-primary-neon transition-colors">
              <User size={18} />
            </div>
            <input 
              type="text" 
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-black/40 border border-white/10 rounded-xl py-3.5 pl-11 pr-4 text-white placeholder-gray-600 focus:outline-none focus:border-primary-neon/50 focus:ring-1 focus:ring-primary-neon/50 transition-all font-display text-sm shadow-inner" 
              placeholder="请输入账号" 
              required
            />
          </div>
        </div>
        
        <div className="space-y-1">
          <label className="text-xs font-display font-bold text-gray-400 uppercase tracking-widest ml-1">进入密码</label>
          <div className="relative group">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-gray-500 group-focus-within:text-primary-neon transition-colors">
              <Lock size={18} />
            </div>
            <input 
              type={showPassword ? "text" : "password"} 
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-black/40 border border-white/10 rounded-xl py-3.5 pl-11 pr-12 text-white placeholder-gray-600 focus:outline-none focus:border-primary-neon/50 focus:ring-1 focus:ring-primary-neon/50 transition-all font-display text-sm shadow-inner" 
              placeholder="••••••••" 
              required
            />
            <button 
              type="button" 
              onClick={() => setShowPassword(!showPassword)} 
              className="absolute inset-y-0 right-0 pr-4 flex items-center text-gray-500 hover:text-primary-neon transition-colors"
            >
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
        </div>

        <button 
          type="submit" 
          disabled={loading}
          className="mt-2 w-full relative group overflow-hidden rounded-xl bg-gradient-to-r from-primary-neon/20 to-blue-600/20 border border-primary-neon/30 p-4 flex items-center justify-center gap-2 hover:from-primary-neon/40 hover:to-blue-600/40 transition-all duration-300 active:scale-[0.98] shadow-[0_0_20px_rgba(0,240,255,0.1)] hover:shadow-[0_0_30px_rgba(0,240,255,0.2)] disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent -translate-x-full group-hover:animate-[shimmer_1.5s_infinite]" />
          <span className="font-display font-bold text-white tracking-[0.2em] uppercase text-sm drop-shadow-[0_0_5px_rgba(255,255,255,0.5)]">
            {loading ? '同步验证中...' : '建立连接'}
          </span>
          {!loading && <ArrowRight size={16} className="text-primary-neon group-hover:translate-x-1 transition-transform" />}
        </button>
      </form>

      {/* Footer Links */}
      <div className="flex justify-between items-center mt-6 pt-5 border-t border-white/10 relative z-10">
        <button 
          type="button"
          onClick={onSwitchToSupport}
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-white transition-colors font-display tracking-widest"
        >
          忘记密码？
        </button>
        <button 
          type="button"
          onClick={onSwitchToCode} 
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-primary-neon transition-colors font-display tracking-widest"
        >
          <MessageCircle size={14} />
          返回微信登录
        </button>
      </div>
    </div>
  );
};
