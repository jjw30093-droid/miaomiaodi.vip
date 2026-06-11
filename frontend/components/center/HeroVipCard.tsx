'use client';

import { useState, useRef, useEffect } from 'react';
import Image from 'next/image';
import { apiClient } from '@/lib/apiClient';

function calcVipInfo(expiresAt: string | null | undefined): {
  daysLeft: number; label: string; isActive: boolean;
} {
  if (!expiresAt) return { daysLeft: 0, label: '未开通 VIP', isActive: false };
  const diff = new Date(expiresAt).getTime() - Date.now();
  if (diff <= 0) return { daysLeft: 0, label: '已到期', isActive: false };
  const days = Math.floor(diff / 86400000);
  return { daysLeft: days, label: `${days} 天`, isActive: true };
}

interface Props {
  profile: any;
  isDark: boolean;
  apiToken: string | undefined;
  onProfileUpdate?: (updated: any) => void;
}

export default function HeroVipCard({ profile, isDark, apiToken, onProfileUpdate }: Props) {
  const [nickname, setNickname] = useState(profile?.nickname || '足球探索者');
  const [editing, setEditing] = useState(false);
  const [nicknameInput, setNicknameInput] = useState(nickname);
  const [avatarUrl, setAvatarUrl] = useState<string>(profile?.avatar_url || '');
  const [uploading, setUploading] = useState(false);

  // 13.1: profile 异步到达时同步 state
  useEffect(() => {
    if (profile?.nickname) setNickname(profile.nickname);
  }, [profile?.nickname]);
  useEffect(() => {
    if (profile?.avatar_url !== undefined) setAvatarUrl(profile.avatar_url || '');
  }, [profile?.avatar_url]);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const vip = calcVipInfo(profile?.vip_expires_at);
  const role = profile?.role || 'user';

  const roleLabel = role === 'admin' ? '🛡️ Admin' : role === 'vip' ? '⭐ VIP' : '普通用户';
  const roleColor = isDark
    ? (role === 'admin' ? '#D4AF37' : role === 'vip' ? '#D4AF37' : 'rgba(255,255,255,0.4)')
    : (role === 'admin' ? 'var(--primary-neon)' : role === 'vip' ? '#A16207' : '#5b3f43');
  const roleBg = isDark
    ? (role === 'admin' ? 'rgba(212,175,55,0.1)' : role === 'vip' ? 'rgba(212,175,55,0.1)' : 'rgba(255,255,255,0.06)')
    : (role === 'admin' ? 'rgba(200,16,46,0.08)' : role === 'vip' ? 'rgba(161,98,7,0.08)' : 'rgba(91,63,67,0.08)');
  const roleBorder = isDark
    ? (role === 'admin' ? 'rgba(212,175,55,0.3)' : role === 'vip' ? 'rgba(212,175,55,0.3)' : 'rgba(255,255,255,0.1)')
    : (role === 'admin' ? 'rgba(200,16,46,0.2)' : role === 'vip' ? 'rgba(161,98,7,0.2)' : 'rgba(91,63,67,0.15)');

  const vipColor = vip.isActive ? (isDark ? '#D4AF37' : '#A16207') : (isDark ? '#f87171' : 'var(--primary-neon)');
  const vipGlow = vip.isActive
    ? (isDark ? 'drop-shadow(0 0 24px rgba(212,175,55,0.35))' : 'none')
    : (isDark ? 'drop-shadow(0 0 20px rgba(248,113,113,0.3))' : 'none');

  // 13.5: /static/ 由 nginx 反代到 FastAPI，直接用相对路径
  const avatarDisplay = avatarUrl || null;

  const saveNickname = async () => {
    if (!apiToken) return;
    try {
      const res = await fetch('/api/v1/user/nickname', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiToken}` },
        body: JSON.stringify({ nickname: nicknameInput }),
      });
      const text = await res.text();
      console.log('[saveNickname]', res.status, text);
      if (!res.ok) {
        let detail = text;
        try { detail = JSON.parse(text).detail || text; } catch {}
        throw new Error(`${res.status}: ${detail}`);
      }
      setNickname(nicknameInput);
      setEditing(false);
      showMsg('ok', '昵称已更新');
    } catch (e: any) {
      showMsg('err', e.message || '更新失败');
    }
  };

  const handleAvatarFile = async (file: File) => {
    if (!apiToken) return;
    // 13.4: 超过 2MB 时 nginx 会返回 HTML，导致 res.json() 报错
    if (file.size > 2 * 1024 * 1024) {
      showMsg('err', '文件尺寸需小于 2MB');
      return;
    }
    setUploading(true);
    setMsg(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch('/api/v1/user/avatar', {
        method: 'POST',
        headers: { Authorization: `Bearer ${apiToken}` },
        body: form,
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || '上传失败');
      }
      const data = await res.json();
      setAvatarUrl(data.avatar_url);
      showMsg('ok', '头像已更新');
    } catch (e: any) {
      showMsg('err', e.message || '上传失败');
    } finally {
      setUploading(false);
    }
  };

  const showMsg = (type: 'ok' | 'err', text: string) => {
    setMsg({ type, text });
    setTimeout(() => setMsg(null), 2500);
  };

  const cardStyle = isDark
    ? { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', backdropFilter: 'blur(24px)' }
    : { background: '#fff', boxShadow: '0px 12px 32px rgba(25,28,29,0.07)' };

  return (
    <div className="rounded-3xl p-6 relative overflow-hidden" style={cardStyle}>
      {/* VIP glow backdrop */}
      {vip.isActive && isDark && (
        <div className="absolute inset-0 pointer-events-none"
          style={{ background: 'radial-gradient(ellipse at 50% 120%, rgba(212,175,55,0.06) 0%, transparent 70%)' }} />
      )}

      {/* Avatar + Nickname row */}
      <div className="flex items-center gap-4 mb-6 relative">
        <button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          className="relative w-16 h-16 rounded-2xl overflow-hidden flex-shrink-0 active:scale-95 transition-all"
          style={{ border: isDark ? '2px solid rgba(255,255,255,0.12)' : '2px solid rgba(200,16,46,0.2)', background: isDark ? '#12161b' : '#f5f0ed' }}
          title="点击更换头像"
        >
          {avatarDisplay ? (
            <Image src={avatarDisplay} alt="avatar" fill className="object-cover" unoptimized />
          ) : (
            <span className="text-3xl flex items-center justify-center w-full h-full select-none">🐱</span>
          )}
          <div className="absolute inset-0 flex items-center justify-center opacity-0 hover:opacity-100 transition-opacity"
            style={{ background: 'rgba(0,0,0,0.55)', fontSize: '0.6rem', color: '#fff', fontWeight: 700 }}>
            {uploading ? '上传中' : '换头像'}
          </div>
        </button>
        <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) handleAvatarFile(f); }} />

        <div className="flex-1 min-w-0">
          {editing ? (
            <div className="flex gap-2 items-center">
              <input
                value={nicknameInput}
                onChange={e => setNicknameInput(e.target.value)}
                maxLength={20}
                className="flex-1 min-w-0 px-3 py-2 rounded-xl text-[15px] font-bold outline-none"
                style={{
                  background: isDark ? 'rgba(255,255,255,0.07)' : '#f5f0ed',
                  border: isDark ? '1px solid rgba(255,255,255,0.15)' : '1px solid rgba(200,16,46,0.2)',
                  color: isDark ? '#fff' : '#191c1d',
                }}
                autoFocus
                onKeyDown={e => { if (e.key === 'Enter') saveNickname(); if (e.key === 'Escape') setEditing(false); }}
              />
              <button
                type="button"
                onPointerDown={e => e.preventDefault()}
                onClick={saveNickname}
                className="px-3 py-2 rounded-xl text-[13px] font-black"
                style={{ background: 'var(--primary-neon)', color: '#fff' }}>保存</button>
              <button type="button" onPointerDown={e => e.preventDefault()} onClick={() => setEditing(false)} className="px-3 py-2 rounded-xl text-[13px] font-bold"
                style={{ border: isDark ? '1px solid rgba(255,255,255,0.12)' : '1px solid rgba(25,28,29,0.15)', color: isDark ? 'rgba(255,255,255,0.5)' : '#5b3f43' }}>取消</button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-[22px] font-black tracking-tight truncate"
                style={{ color: isDark ? '#fff' : '#191c1d', fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                {nickname}
              </span>
              <button onClick={() => { setEditing(true); setNicknameInput(nickname); }}
                className="flex-shrink-0 text-[13px] font-bold px-2 py-0.5 rounded-lg transition-all active:scale-95"
                style={{ border: isDark ? '1px solid rgba(255,255,255,0.12)' : '1px solid rgba(25,28,29,0.15)', color: isDark ? 'rgba(255,255,255,0.4)' : '#5b3f43' }}>
                修改
              </button>
            </div>
          )}
          {/* Role badge */}
          <div className="mt-2">
            <span className="text-[13px] font-bold px-2.5 py-0.5 rounded-full"
              style={{ background: roleBg, border: `1px solid ${roleBorder}`, color: roleColor }}>
              {roleLabel}
            </span>
          </div>
        </div>
      </div>

      {/* VIP countdown block */}
      {process.env.NEXT_PUBLIC_ENABLE_VIP_DISPLAY === 'true' && (
        <div className="rounded-2xl p-4 mb-5"
          style={isDark
            ? { background: vip.isActive ? 'rgba(212,175,55,0.06)' : 'rgba(255,255,255,0.04)', border: `1px solid ${vip.isActive ? 'rgba(212,175,55,0.2)' : 'rgba(255,255,255,0.07)'}` }
            : { background: vip.isActive ? 'rgba(161,98,7,0.05)' : 'rgba(25,28,29,0.04)', border: `1px solid ${vip.isActive ? 'rgba(161,98,7,0.18)' : 'rgba(25,28,29,0.08)'}` }
          }
        >
          {vip.isActive ? (
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-[13px] font-bold uppercase tracking-widest mb-1"
                  style={{ color: isDark ? 'rgba(255,255,255,0.45)' : '#5b3f43' }}>VIP 剩余</p>
                <p className="font-black italic tracking-tight leading-none"
                  style={{ fontSize: 40, color: vipColor, filter: vipGlow, fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                  {vip.label}
                </p>
                {profile?.vip_expires_at && (
                  <p className="text-[13px] font-bold mt-1" style={{ color: isDark ? 'rgba(255,255,255,0.4)' : '#5b3f43' }}>
                    到期：{new Date(profile.vip_expires_at).toLocaleDateString('zh-CN')}
                  </p>
                )}
              </div>
              <div className="text-5xl select-none">✅</div>
            </div>
          ) : (
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-[15px] font-bold" style={{ color: isDark ? 'rgba(255,255,255,0.5)' : '#5b3f43' }}>
                  {vip.label === '已到期' ? 'VIP 已到期，续费后继续使用' : '未开通 VIP，购买卡密后激活'}
                </p>
              </div>
              <div className="text-4xl select-none">{vip.label === '已到期' ? '⏰' : '🔒'}</div>
            </div>
          )}
        </div>
      )}

      {/* CTA buttons */}
      {process.env.NEXT_PUBLIC_ENABLE_VIP_DISPLAY === 'true' && (
        <div className="flex gap-3">
          <button
            onClick={() => document.getElementById('redeem-cdk-row')?.scrollIntoView({ behavior: 'smooth' })}
            className="flex-1 h-11 rounded-2xl font-black text-[15px] italic tracking-tight transition-all active:scale-[0.97]"
            style={isDark
              ? { background: 'linear-gradient(135deg, #D4AF37 0%, #A16207 100%)', color: '#fff', boxShadow: '0 4px 20px rgba(212,175,55,0.35)' }
              : { background: 'var(--primary-neon)', color: '#fff', boxShadow: '0 4px 16px rgba(200,16,46,0.25)' }
            }>
            {vip.isActive ? '续费 VIP' : '开通 VIP'}
          </button>
          <button
            onClick={() => document.getElementById('redeem-cdk-row')?.scrollIntoView({ behavior: 'smooth' })}
            className="flex-1 h-11 rounded-2xl font-black text-[15px] italic tracking-tight transition-all active:scale-[0.97]"
            style={isDark
              ? { background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)', color: '#fff' }
              : { background: '#fff', border: '1px solid rgba(200,16,46,0.25)', color: 'var(--primary-neon)' }
            }
          >
            兑换 CDK →
          </button>
        </div>
      )}

      {msg && (
        <div className="mt-4 text-center py-2 px-4 rounded-xl text-[13px] font-bold"
          style={{
            background: msg.type === 'ok' ? (isDark ? 'rgba(74,222,128,0.1)' : 'rgba(15,118,110,0.08)') : (isDark ? 'rgba(248,113,113,0.1)' : 'rgba(200,16,46,0.08)'),
            border: `1px solid ${msg.type === 'ok' ? (isDark ? 'rgba(74,222,128,0.25)' : 'rgba(15,118,110,0.2)') : (isDark ? 'rgba(248,113,113,0.25)' : 'rgba(200,16,46,0.2)')}`,
            color: msg.type === 'ok' ? (isDark ? '#4ade80' : '#0f766e') : (isDark ? '#f87171' : 'var(--primary-neon)'),
          }}>
          {msg.text}
        </div>
      )}
    </div>
  );
}
