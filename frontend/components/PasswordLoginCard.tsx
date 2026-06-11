'use client';

import React, { useState, useEffect } from 'react';
import { signIn } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { User, Lock, Eye, EyeOff, ArrowRight, MessageCircle } from 'lucide-react';

interface PasswordLoginCardProps {
  onSwitchToCode: () => void;
  onSwitchToSupport: () => void;
}

export const PasswordLoginCard: React.FC<PasswordLoginCardProps> = ({ onSwitchToCode, onSwitchToSupport }) => {
  const [showPassword, setShowPassword] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [callbackUrl, setCallbackUrl] = useState('/');

  const router = useRouter();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setCallbackUrl(params.get('callbackUrl') || '/');
  }, []);

  const handlePasswordLogin = async (e: React.FormEvent) => {
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
        const msg = result.error;
        if (msg.includes('待管理员审核')) {
          setError('账号待管理员审核，请耐心等待');
        } else if (msg.includes('已被拒绝')) {
          setError('注册申请已被拒绝，如有疑问请联系管理员');
        } else if (msg === 'CredentialsSignin' || msg.includes('用户名或密码')) {
          setError('用户名或密码错误，请重新输入');
        } else {
          setError(msg);
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
      <form onSubmit={handlePasswordLogin} className="flex flex-col gap-4 relative z-10 mt-1">
        
        {error && (
          <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-rose-500 text-xs font-bold text-center animate-shake">
            {error}
          </div>
        )}

        <div className="space-y-1">
          <label className="text-xs font-mono uppercase tracking-wider ml-1 text-stone-500 dark:text-zinc-400">极客 ID / 用户名</label>
          <div className="relative group">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-stone-400 dark:text-zinc-500 group-focus-within:text-primary-neon transition-colors">
              <User size={18} />
            </div>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-white dark:bg-zinc-800 border border-stone-200 dark:border-zinc-700 rounded-xl py-3 pl-11 pr-4 text-stone-900 dark:text-white font-bold placeholder-stone-400 dark:placeholder-zinc-500 focus:outline-none focus:border-primary-neon/50 focus:ring-1 focus:ring-primary-neon/50 transition-all font-mono text-sm"
              placeholder="请输入账号"
              required
            />
          </div>
        </div>

        <div className="space-y-1">
          <label className="text-xs font-mono uppercase tracking-wider ml-1 text-stone-500 dark:text-zinc-400">密码</label>
          <div className="relative group">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-stone-400 dark:text-zinc-500 group-focus-within:text-primary-neon transition-colors">
              <Lock size={18} />
            </div>
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-white dark:bg-zinc-800 border border-stone-200 dark:border-zinc-700 rounded-xl py-3 pl-11 pr-12 text-stone-900 dark:text-white font-bold placeholder-stone-400 dark:placeholder-zinc-500 focus:outline-none focus:border-primary-neon/50 focus:ring-1 focus:ring-primary-neon/50 transition-all font-mono text-sm"
              placeholder="••••••••"
              required
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute inset-y-0 right-0 pr-4 flex items-center text-stone-400 dark:text-zinc-500 hover:text-primary-neon transition-colors"
            >
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="mt-2 w-full rounded-xl bg-primary-neon hover:bg-red-700 text-white p-3.5 flex items-center justify-center gap-2 transition-colors active:scale-[0.98] shadow-md disabled:opacity-50 font-semibold"
        >
          <span className="font-display font-bold tracking-widest uppercase text-sm">
            {loading ? '建立连接中...' : '建立连接'}
          </span>
          {!loading && <ArrowRight size={16} className="group-hover:translate-x-1 transition-transform" />}
        </button>
      </form>

      {/* Footer Links */}
      <div className="flex justify-between items-center mt-6 pt-5 border-t border-stone-200 dark:border-zinc-700 relative z-10">
        <button
          type="button"
          onClick={onSwitchToSupport}
          className="flex items-center gap-1.5 text-xs text-stone-500 dark:text-zinc-500 hover:text-stone-900 dark:hover:text-white transition-colors font-mono"
        >
          忘记密码？
        </button>
        {process.env.NEXT_PUBLIC_ENABLE_WECHAT_LOGIN === 'true' && (
          <button
            type="button"
            onClick={onSwitchToCode}
            className="flex items-center gap-1.5 text-xs text-stone-500 dark:text-zinc-500 hover:text-primary-neon transition-colors font-mono"
          >
            <MessageCircle size={14} />
            返回微信登录
          </button>
        )}
      </div>
    </div>
  );
};
