'use client';

import React, { useState, useEffect, useRef } from 'react';
import { MessageCircle, Loader2, ShieldAlert, KeyRound, HelpCircle, CheckCircle2, RefreshCw, XCircle } from 'lucide-react';
import { signIn } from 'next-auth/react';
import { useRouter } from 'next/navigation';

type CardStatus = 'loading' | 'pending' | 'confirmed' | 'expired' | 'error';

export const WeChatCodeCard = ({
  onSwitchToPassword,
  onSwitchToSupport,
}: {
  onSwitchToPassword: () => void;
  onSwitchToSupport: () => void;
}) => {
  const router = useRouter();
  const [code, setCode] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [timeLeft, setTimeLeft] = useState(180);
  const [status, setStatus] = useState<CardStatus>('loading');

  const pollRef  = useRef<ReturnType<typeof setInterval> | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearTimers = () => {
    if (pollRef.current)  clearInterval(pollRef.current);
    if (timerRef.current) clearInterval(timerRef.current);
  };

  // ── 生成暗号 ────────────────────────────────────────────────
  const generateCode = async () => {
    clearTimers();
    setStatus('loading');
    setCode(null);
    setSessionId(null);
    setTimeLeft(180);

    try {
      const res = await fetch('/api/v1/auth/wechat/code', { method: 'POST' });
      if (!res.ok) throw new Error('生成失败');
      const data = await res.json();
      setCode(data.code);
      setSessionId(data.session_id);
      setTimeLeft(data.expires_in ?? 180);
      setStatus('pending');
    } catch {
      setStatus('error');
    }
  };

  // 初始化
  useEffect(() => {
    generateCode();
    return clearTimers;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── 倒计时 ─────────────────────────────────────────────────
  useEffect(() => {
    if (status !== 'pending') return;

    timerRef.current = setInterval(() => {
      setTimeLeft(prev => {
        if (prev <= 1) {
          setStatus('expired');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [status]);

  // ── 轮询 ───────────────────────────────────────────────────
  useEffect(() => {
    if (status !== 'pending' || !sessionId) return;

    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/v1/auth/wechat/poll/${sessionId}`);
        if (!res.ok) return;
        const data = await res.json();

        if (data.status === 'confirmed' && data.token) {
          clearTimers();
          setStatus('confirmed');
          // 直接用后端 JWT 完成 NextAuth 登录，不再二次 poll（session 已消耗）
          const result = await signIn('wechat', {
            api_token: data.token,
            redirect:  false,
          });
          if (result?.ok) {
            router.push('/');
          } else {
            setStatus('error');
          }
        } else if (data.status === 'expired') {
          clearTimers();
          setStatus('expired');
        }
      } catch {
        // 网络抖动，下次继续轮询
      }
    }, 2000);

    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, sessionId]);

  const formatTime = (s: number) =>
    `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">

      {/* 主交互区 */}
      <div className="flex flex-col items-center bg-black/40 rounded-2xl p-5 border border-white/5 relative z-10 shadow-inner">

        {/* 图标 */}
        <div className="flex items-center justify-center w-12 h-12 rounded-full bg-[#07C160]/10 border border-[#07C160]/30 mb-3 shadow-[0_0_15px_rgba(7,193,96,0.2)]">
          {status === 'confirmed'
            ? <CheckCircle2 className="text-[#07C160]" size={24} />
            : status === 'error'
              ? <XCircle className="text-red-400" size={24} />
              : <MessageCircle className="text-[#07C160]" size={24} />}
        </div>

        {/* 说明文字 */}
        {(status === 'loading' || status === 'pending') && (
          <p className="text-gray-300 text-sm text-center leading-relaxed mb-4">
            微信搜索并关注公众号<br />
            <span className="text-white font-bold tracking-wider">【足球喵喵弟】</span><br />
            回复下方数字，即可自动登录。
          </p>
        )}

        {/* 暗号展示 */}
        {status === 'loading' && (
          <div className="mb-5 flex items-center justify-center h-16">
            <Loader2 size={32} className="text-primary-neon animate-spin" />
          </div>
        )}

        {status === 'pending' && code && (
          <div className="relative group mb-5">
            <div className="absolute inset-0 bg-primary-neon/20 blur-xl rounded-full group-hover:bg-primary-neon/30 transition-all duration-500" />
            <div className="text-5xl sm:text-6xl font-mono font-black text-primary-neon tracking-[0.3em] pl-[0.3em] drop-shadow-[0_0_20px_rgba(0,240,255,0.8)] relative z-10 select-all">
              {code}
            </div>
          </div>
        )}

        {/* 成功状态 */}
        {status === 'confirmed' && (
          <div className="mb-4 text-center">
            <p className="text-[#07C160] text-lg font-bold">验证成功！</p>
            <p className="text-gray-400 text-sm mt-1 flex items-center gap-1 justify-center">
              <Loader2 size={14} className="animate-spin" /> 正在跳转…
            </p>
          </div>
        )}

        {/* 过期状态 */}
        {status === 'expired' && (
          <div className="mb-4 flex flex-col items-center gap-3">
            <p className="text-secondary-magenta text-sm">暗号已过期</p>
            <button
              onClick={generateCode}
              className="flex items-center gap-2 text-sm text-primary-neon border border-primary-neon/30 px-4 py-2 rounded-full hover:bg-primary-neon/10 active:scale-95 transition-all"
            >
              <RefreshCw size={14} /> 重新获取
            </button>
          </div>
        )}

        {/* 错误状态 */}
        {status === 'error' && (
          <div className="mb-4 flex flex-col items-center gap-3">
            <p className="text-red-400 text-sm">获取失败，请重试</p>
            <button
              onClick={generateCode}
              className="flex items-center gap-2 text-sm text-primary-neon border border-primary-neon/30 px-4 py-2 rounded-full hover:bg-primary-neon/10 active:scale-95 transition-all"
            >
              <RefreshCw size={14} /> 重试
            </button>
          </div>
        )}

        {/* 倒计时提示 */}
        {status === 'pending' && (
          <div className="flex items-center gap-2 text-xs text-secondary-magenta/90 bg-secondary-magenta/10 px-3 py-1.5 rounded-full border border-secondary-magenta/20">
            <ShieldAlert size={14} />
            <span>有效期 <span className="font-mono font-bold">{formatTime(timeLeft)}</span>，请勿泄露</span>
          </div>
        )}
      </div>

      {/* 等待同步指示器 */}
      {status === 'pending' && (
        <div className="mt-6 mb-2 flex flex-col items-center gap-2 relative z-10">
          <div className="relative flex items-center justify-center">
            <Loader2 size={24} className="text-primary-neon animate-spin" />
            <div className="absolute inset-0 bg-primary-neon/30 blur-md rounded-full animate-pulse" />
          </div>
          <p className="text-primary-neon/80 text-xs font-mono animate-pulse tracking-wide">
            等待微信同步验证…
          </p>
        </div>
      )}

      {/* 底部链接 */}
      <div className="flex justify-between items-center mt-6 pt-5 border-t border-white/10 relative z-10">
        <button
          onClick={onSwitchToPassword}
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-white transition-colors font-mono"
        >
          <KeyRound size={14} /> 账号密码登录
        </button>
        <button
          onClick={onSwitchToSupport}
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-white transition-colors font-mono"
        >
          <HelpCircle size={14} /> 遇到问题？
        </button>
      </div>
    </div>
  );
};
