'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Lock, User, ArrowRight, ArrowLeft, Check, X } from 'lucide-react';
import { useTheme } from '@/components/ThemeProvider';
import ThemeToggleButton from '@/components/ThemeToggleButton';

/** 简单的设备指纹（用于反多账号滥用，非精确识别） */
function getDeviceFingerprint(): string {
  if (typeof window === 'undefined') return '';
  const parts = [
    navigator.userAgent,
    navigator.language,
    `${screen.width}x${screen.height}`,
    String(screen.colorDepth),
    String(new Date().getTimezoneOffset()),
    String(navigator.hardwareConcurrency ?? 0),
    navigator.platform ?? '',
  ].join('|');
  let h = 0;
  for (let i = 0; i < parts.length; i++) {
    h = Math.imul(31, h) + parts.charCodeAt(i) | 0;
  }
  return Math.abs(h).toString(16).padStart(8, '0');
}

function validateUsername(name: string): string | null {
  const trimmed = name.trim();
  if (trimmed.length < 2) return '用户名不能少于 2 个字符';
  if (trimmed.length > 32) return '用户名不能超过 32 个字符';
  if (trimmed !== name) return '用户名首尾不能有空格';
  return null;
}

function validatePassword(pwd: string): string | null {
  if (pwd.length < 6) return '密码至少 6 位';
  if (!/[a-z]/.test(pwd)) return '密码必须包含小写字母';
  if (!/[A-Z]/.test(pwd)) return '密码必须包含大写字母';
  return null;
}

export default function RegisterPage() {
  const router = useRouter();
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [nickname, setNickname] = useState('');
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string; loginHint?: boolean } | null>(null);

  const pwdOk = validatePassword(password) === null;
  const pwdHasLower = /[a-z]/.test(password);
  const pwdHasUpper = /[A-Z]/.test(password);
  const pwdLengthOk = password.length >= 6;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMsg(null);

    const unameErr = validateUsername(username);
    if (unameErr) { setMsg({ type: 'error', text: unameErr }); return; }

    const pwdErr = validatePassword(password);
    if (pwdErr) { setMsg({ type: 'error', text: pwdErr }); return; }

    if (password !== confirmPassword) {
      setMsg({ type: 'error', text: '两次密码不一致' });
      return;
    }

    setLoading(true);
    try {
      const deviceId = getDeviceFingerprint();
      const res = await fetch('/api/v1/auth/register', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          username,
          password,
          nickname: nickname.trim() || username,
          device_id: deviceId,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        setMsg({ type: 'success', text: '注册成功！2 秒后跳转登录页...' });
        setTimeout(() => router.push('/login'), 2000);
      } else {
        const detail: string = data.detail || '注册失败，请稍后重试';
        const isDeviceConflict = detail.includes('该设备已注册');
        setMsg({ type: 'error', text: isDeviceConflict ? '检测到该设备已有账号，请直接登录。' : detail, loginHint: isDeviceConflict });
      }
    } catch {
      setMsg({ type: 'error', text: '连接失败，请稍后重试' });
    } finally {
      setLoading(false);
    }
  };

  const inputCls = `w-full rounded-xl py-3 pl-11 pr-4 text-sm font-bold placeholder-gray-500 focus:outline-none transition-all ${
    isDark
      ? 'bg-zinc-800 border border-zinc-700 text-white focus:border-[#E91E63]/50 focus:ring-1 focus:ring-[#E91E63]/50'
      : 'bg-[#f2f4f5] border border-[#e0dcd9] text-[#191c1d] focus:border-[#b7004d]/50 focus:ring-1 focus:ring-[#b7004d]/50'
  }`;

  return (
    <div
      className="relative min-h-screen overflow-hidden font-sans flex flex-col"
      style={{ background: isDark ? '#09090b' : 'radial-gradient(ellipse at top, #f2f4f5 0%, #f8fafb 100%)' }}
    >
      <header
        className="w-full z-50 flex items-center justify-between px-5 py-4"
        style={{
          background: isDark ? 'rgba(9,9,11,0.8)' : 'rgba(255,255,255,0.8)',
          backdropFilter: 'blur(12px)',
          boxShadow: isDark ? 'none' : '0px 4px 16px rgba(25,28,29,0.06)',
        }}
      >
        <div className="flex items-center gap-3">
          <Link href="/login" className={`flex items-center justify-center w-9 h-9 rounded-full transition-colors ${isDark ? 'hover:bg-white/10' : 'hover:bg-[#f2f4f5]'}`}>
            <ArrowLeft size={18} className={isDark ? 'text-zinc-300' : 'text-[#191c1d]'} />
          </Link>
          <h1 className="text-lg font-black tracking-tighter" style={{ color: isDark ? '#E91E63' : '#b7004d', fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
            注册账号
          </h1>
        </div>
        <ThemeToggleButton />
      </header>

      <main className="flex-1 flex flex-col justify-center items-center px-5 py-10">
        <div
          className="w-full max-w-md rounded-[1.5rem] relative overflow-hidden p-7"
          style={{
            background: isDark ? '#18181b' : '#fff',
            border: isDark ? '1px solid rgba(255,255,255,0.08)' : 'none',
            boxShadow: isDark ? '0px 24px 48px rgba(0,0,0,0.4)' : '0px 12px 32px rgba(25,28,29,0.08)',
          }}
        >
          <div className="mb-6">
            <h2 className="text-2xl font-bold mb-1" style={{ color: isDark ? '#fff' : '#191c1d', fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
              创建账号
            </h2>
            <p className="text-sm" style={{ color: isDark ? '#a1a1aa' : '#5b3f43' }}>
              填写信息后即可登录，注册完全免费
            </p>
          </div>

          {msg && (
            <div
              className="mb-4 p-3 rounded-xl text-sm font-bold text-center"
              style={{
                background: msg.type === 'success' ? 'rgba(74,222,128,0.08)' : 'rgba(239,68,68,0.08)',
                border: `1px solid ${msg.type === 'success' ? 'rgba(74,222,128,0.3)' : 'rgba(239,68,68,0.3)'}`,
                color: msg.type === 'success' ? (isDark ? '#4ade80' : '#0f766e') : '#ef4444',
              }}
            >
              {msg.text}
              {msg.loginHint && (
                <div className="mt-2">
                  <Link
                    href="/login"
                    className="inline-block px-4 py-1.5 rounded-lg text-xs font-black transition-all active:scale-95"
                    style={{ background: isDark ? '#E91E63' : '#b7004d', color: '#fff' }}
                  >
                    前往登录 →
                  </Link>
                </div>
              )}
            </div>
          )}

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {/* 用户名 */}
            <div className="space-y-1">
              <label className="text-xs font-bold uppercase tracking-wider ml-1" style={{ color: isDark ? '#a1a1aa' : '#5b3f43' }}>用户名</label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none" style={{ color: '#6b7280' }}>
                  <User size={18} />
                </div>
                <input
                  type="text"
                  required
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  className={inputCls}
                  placeholder="至少 2 个字符"
                />
              </div>
            </div>

            {/* 昵称（可选） */}
            <div className="space-y-1">
              <label className="text-xs font-bold uppercase tracking-wider ml-1" style={{ color: isDark ? '#a1a1aa' : '#5b3f43' }}>昵称（可选）</label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none" style={{ color: '#6b7280' }}>
                  <User size={18} />
                </div>
                <input
                  type="text"
                  value={nickname}
                  onChange={e => setNickname(e.target.value)}
                  className={inputCls}
                  placeholder="留空则使用用户名"
                />
              </div>
            </div>

            {/* 密码 */}
            <div className="space-y-1">
              <label className="text-xs font-bold uppercase tracking-wider ml-1" style={{ color: isDark ? '#a1a1aa' : '#5b3f43' }}>密码</label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none" style={{ color: '#6b7280' }}>
                  <Lock size={18} />
                </div>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  className={inputCls}
                  placeholder="至少 6 位，含大小写字母"
                />
              </div>
              {password && (
                <div className="mt-1 flex flex-col gap-0.5 ml-1">
                  {[
                    { ok: pwdLengthOk, label: '至少 6 位' },
                    { ok: pwdHasLower, label: '含小写字母' },
                    { ok: pwdHasUpper, label: '含大写字母' },
                  ].map(({ ok, label }) => (
                    <span key={label} className="flex items-center gap-1 text-xs" style={{ color: ok ? '#4ade80' : '#f87171' }}>
                      {ok ? <Check size={11} /> : <X size={11} />} {label}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* 确认密码 */}
            <div className="space-y-1">
              <label className="text-xs font-bold uppercase tracking-wider ml-1" style={{ color: isDark ? '#a1a1aa' : '#5b3f43' }}>确认密码</label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none" style={{ color: '#6b7280' }}>
                  <Lock size={18} />
                </div>
                <input
                  type="password"
                  required
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                  className={inputCls}
                  placeholder="再次输入密码"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="mt-2 w-full rounded-xl p-3.5 flex items-center justify-center gap-2 font-black text-sm uppercase tracking-widest transition-all active:scale-[0.98] disabled:opacity-50"
              style={{
                background: isDark
                  ? 'linear-gradient(135deg, #E91E63 0%, #FF00E5 100%)'
                  : '#b7004d',
                color: '#fff',
              }}
            >
              {loading ? '注册中...' : '立即注册'}
              {!loading && <ArrowRight size={16} />}
            </button>
          </form>

          <div className="mt-6 text-center">
            <p className="text-xs" style={{ color: isDark ? '#71717a' : '#5b3f43' }}>
              已有账号？{' '}
              <Link href="/login" className="font-bold hover:opacity-80" style={{ color: isDark ? '#E91E63' : '#b7004d' }}>
                返回登录
              </Link>
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
