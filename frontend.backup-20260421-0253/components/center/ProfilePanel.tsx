'use client';

import { useState, useRef } from 'react';
import { useSession } from 'next-auth/react';
import Image from 'next/image';
import { apiClient } from '@/lib/apiClient';

export default function ProfilePanel({ profile }: { profile: any }) {
  const { data: session, update } = useSession();
  const apiToken = (session?.user as any)?.apiToken as string | undefined;

  const [nickname, setNickname] = useState(profile?.nickname || '足球探索者');
  const [editing, setEditing] = useState(false);
  const [nicknameInput, setNicknameInput] = useState(nickname);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [avatarUrl, setAvatarUrl] = useState<string>(profile?.avatar_url || '');
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const saveNickname = async () => {
    if (!apiToken) return;
    try {
      await apiClient.patch('/nickname', { nickname: nicknameInput }, { token: apiToken });
      setNickname(nicknameInput);
      setEditing(false);
      setMsg({ type: 'ok', text: '昵称已更新' });
      setTimeout(() => setMsg(null), 2000);
    } catch (e: any) {
      setMsg({ type: 'err', text: e.message || '更新失败' });
    }
  };

  const handleAvatarFile = async (file: File) => {
    if (!apiToken) return;
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
      setMsg({ type: 'ok', text: '头像已更新' });
      setTimeout(() => setMsg(null), 2000);
    } catch (e: any) {
      setMsg({ type: 'err', text: e.message || '上传失败' });
    } finally {
      setUploading(false);
    }
  };

  const avatarDisplay = avatarUrl
    ? (avatarUrl.startsWith('/static') ? `http://localhost:8000${avatarUrl}` : avatarUrl)
    : null;

  return (
    <div className="flex flex-col gap-6">
      {/* 头像 */}
      <div className="flex flex-col items-center gap-4">
        <button
          onClick={() => fileRef.current?.click()}
          disabled={uploading}
          className="relative w-24 h-24 rounded-2xl overflow-hidden transition-all active:scale-95"
          style={{ border: '2px solid rgba(191,165,93,0.4)', background: '#12161b' }}
          title="点击更换头像"
        >
          {avatarDisplay ? (
            <Image src={avatarDisplay} alt="avatar" fill className="object-cover" unoptimized />
          ) : (
            <span className="text-4xl flex items-center justify-center w-full h-full">🐱</span>
          )}
          <div
            className="absolute inset-0 flex items-center justify-center opacity-0 hover:opacity-100 transition-opacity"
            style={{ background: 'rgba(0,0,0,0.6)', fontSize: '0.65rem', color: '#BFA55D', fontWeight: 700 }}
          >
            {uploading ? '上传中...' : '换头像'}
          </div>
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) handleAvatarFile(f); }}
        />
        <p className="text-xs" style={{ color: 'rgba(250,250,252,0.35)' }}>点击头像更换（≤2MB）</p>
      </div>

      {/* 昵称 */}
      <div
        className="rounded-2xl p-5 flex flex-col gap-3"
        style={{ background: '#12161b', border: '1px solid rgba(255,255,255,0.07)' }}
      >
        <div className="flex items-center justify-between">
          <span className="text-xs font-bold uppercase tracking-widest" style={{ color: 'rgba(191,165,93,0.8)' }}>昵称</span>
          {!editing && (
            <button
              onClick={() => { setEditing(true); setNicknameInput(nickname); }}
              className="text-xs px-3 py-1 rounded-lg transition-colors"
              style={{ border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(250,250,252,0.5)' }}
            >
              修改
            </button>
          )}
        </div>
        {editing ? (
          <div className="flex gap-2">
            <input
              value={nicknameInput}
              onChange={e => setNicknameInput(e.target.value)}
              maxLength={20}
              className="flex-1 px-3 py-2 rounded-xl text-sm outline-none"
              style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(191,165,93,0.3)', color: '#fff' }}
              autoFocus
            />
            <button
              onClick={saveNickname}
              className="px-4 py-2 rounded-xl text-xs font-black"
              style={{ background: '#BFA55D', color: '#080c1a' }}
            >
              保存
            </button>
            <button
              onClick={() => setEditing(false)}
              className="px-3 py-2 rounded-xl text-xs"
              style={{ border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(250,250,252,0.4)' }}
            >
              取消
            </button>
          </div>
        ) : (
          <span className="text-base font-bold text-white">{nickname}</span>
        )}
      </div>

      {/* 账号信息 */}
      <div
        className="rounded-2xl p-5 flex flex-col gap-3"
        style={{ background: '#12161b', border: '1px solid rgba(255,255,255,0.07)' }}
      >
        <span className="text-xs font-bold uppercase tracking-widest" style={{ color: 'rgba(191,165,93,0.8)' }}>账号信息</span>
        <div className="flex flex-col gap-2 text-sm" style={{ color: 'rgba(250,250,252,0.6)' }}>
          <div className="flex justify-between">
            <span>OpenID 尾号</span>
            <span className="font-mono" style={{ color: 'rgba(0,240,255,0.7)' }}>{profile?.openid_tail || '***'}</span>
          </div>
          <div className="flex justify-between">
            <span>注册日期</span>
            <span>{profile?.created_at?.slice(0, 10) || '—'}</span>
          </div>
          <div className="flex justify-between">
            <span>当前角色</span>
            <span className="font-bold" style={{ color: profile?.role === 'vip' ? '#BFA55D' : 'rgba(250,250,252,0.6)' }}>
              {profile?.role === 'vip' ? '⭐ VIP' : profile?.role === 'admin' ? '🛡️ Admin' : '普通用户'}
            </span>
          </div>
        </div>
      </div>

      {msg && (
        <div
          className="text-center py-2 px-4 rounded-xl text-sm font-bold"
          style={{
            background: msg.type === 'ok' ? 'rgba(191,165,93,0.1)' : 'rgba(255,61,84,0.1)',
            color: msg.type === 'ok' ? '#BFA55D' : '#ff3d54',
            border: `1px solid ${msg.type === 'ok' ? 'rgba(191,165,93,0.3)' : 'rgba(255,61,84,0.3)'}`,
          }}
        >
          {msg.text}
        </div>
      )}
    </div>
  );
}
