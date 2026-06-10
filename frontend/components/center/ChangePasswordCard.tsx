'use client';

import { useState } from 'react';
import { apiClient } from '@/lib/apiClient';

interface Props {
  isDark: boolean;
  apiToken: string | undefined;
}

export default function ChangePasswordCard({ isDark, apiToken }: Props) {
  const [oldPwd, setOldPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [confirmPwd, setConfirmPwd] = useState('');
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const rules = newPwd.length >= 6 && /[a-z]/.test(newPwd) && /[A-Z]/.test(newPwd);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMsg(null);
    if (newPwd !== confirmPwd) { setMsg({ type: 'err', text: '两次输入的新密码不一致' }); return; }
    if (newPwd === oldPwd) { setMsg({ type: 'err', text: '新密码不能与原密码相同' }); return; }
    if (!rules) { setMsg({ type: 'err', text: '密码需至少6位，且包含大写和小写字母' }); return; }
    if (!apiToken) { setMsg({ type: 'err', text: '未登录，请刷新页面' }); return; }

    setLoading(true);
    try {
      await (apiClient as any).post('/user/password', { old_password: oldPwd, new_password: newPwd }, { token: apiToken });
      setMsg({ type: 'ok', text: '密码修改成功！下次登录请使用新密码。' });
      setOldPwd(''); setNewPwd(''); setConfirmPwd('');
    } catch (err: any) {
      const detail = err?.message || '修改失败';
      setMsg({ type: 'err', text: detail.includes('401') || detail.includes('原密码') ? '原密码错误' : detail });
    } finally {
      setLoading(false);
    }
  };

  const inputCls = `w-full rounded-xl px-4 py-2.5 text-sm font-bold outline-none transition-all ${
    isDark
      ? 'bg-white/5 border border-white/10 text-white placeholder:text-white/30 focus:border-primary-neon/50'
      : 'bg-[#f2f4f5] border border-transparent text-[#191c1d] placeholder:text-[#5b3f43]/40 focus:border-[#005faf]/40'
  }`;

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <input type="password" className={inputCls} placeholder="原密码" value={oldPwd} onChange={e => setOldPwd(e.target.value)} autoComplete="current-password" required />
      <input type="password" className={inputCls} placeholder="新密码（≥6位，含大小写字母）" value={newPwd} onChange={e => setNewPwd(e.target.value)} autoComplete="new-password" required />
      <input type="password" className={inputCls} placeholder="确认新密码" value={confirmPwd} onChange={e => setConfirmPwd(e.target.value)} autoComplete="new-password" required />

      {newPwd.length > 0 && (
        <p className={`text-xs font-bold ${rules ? 'text-emerald-500' : isDark ? 'text-white/40' : 'text-[#5b3f43]'}`}>
          {rules ? '✅ 密码符合要求' : '需要：≥6位 · 含小写字母 · 含大写字母'}
        </p>
      )}

      {msg && (
        <p className={`text-xs font-bold rounded-lg p-2.5 ${msg.type === 'ok' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-red-500/10 text-red-400'}`}>
          {msg.type === 'ok' ? '✅ ' : '❌ '}{msg.text}
        </p>
      )}

      <button type="submit" disabled={loading}
        className={`w-full py-3 rounded-xl font-black text-sm transition-all active:scale-[0.98] disabled:opacity-50 ${
          isDark ? 'bg-[#E91E63]/90 text-white hover:bg-[#E91E63]' : 'bg-[#b7004d] text-white hover:bg-[#900040]'
        }`}>
        {loading ? '修改中...' : '更新密码'}
      </button>
    </form>
  );
}
