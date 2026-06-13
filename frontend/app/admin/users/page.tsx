'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';

interface User {
  id: number;
  username: string;
  nickname: string;
  role: string;
  disabled: number;
  created_at: string;
  auth_source: string;
}

interface Unlock {
  match_id: string;
  unlock_source: string;
  unlocked_at: string;
  expires_at: string | null;
}

interface WcMatch {
  match_id: string;
  home_team: string;
  away_team: string;
  starting_at: string;
  has_report: boolean;
}

function genPassword(): string {
  const lower = 'abcdefghjkmnpqrstuvwxyz';
  const upper = 'ABCDEFGHJKMNPQRSTUVWXYZ';
  const digits = '23456789';
  const all = lower + upper + digits;
  let pwd = lower[Math.floor(Math.random() * lower.length)]
    + upper[Math.floor(Math.random() * upper.length)]
    + digits[Math.floor(Math.random() * digits.length)];
  for (let i = 0; i < 5; i++) pwd += all[Math.floor(Math.random() * all.length)];
  return pwd.split('').sort(() => Math.random() - 0.5).join('');
}

export default function AdminUsersPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const superAdmin = process.env.NEXT_PUBLIC_SUPER_ADMIN_USER;

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [nickname, setNickname] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');
  const [newCred, setNewCred] = useState<{ username: string; password: string } | null>(null);
  const [copied, setCopied] = useState(false);

  const [users, setUsers] = useState<User[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);

  const [resetTarget, setResetTarget] = useState<User | null>(null);
  const [resetPwd, setResetPwd] = useState('');
  const [resetting, setResetting] = useState(false);
  const [resetResult, setResetResult] = useState<{ username: string; password: string } | null>(null);

  const [actionMsg, setActionMsg] = useState('');

  // 研报授权弹窗
  const [unlockTarget, setUnlockTarget] = useState<User | null>(null);
  const [unlocks, setUnlocks] = useState<Unlock[]>([]);
  const [wcMatches, setWcMatches] = useState<WcMatch[]>([]);
  const [unlockLoading, setUnlockLoading] = useState(false);
  const [grantingId, setGrantingId] = useState<string | null>(null);

  useEffect(() => {
    if (status === 'unauthenticated' || (status === 'authenticated' && (session?.user as any)?.name !== superAdmin)) {
      router.replace('/');
    }
  }, [status, session, router, superAdmin]);

  const fetchUsers = useCallback(async () => {
    setLoadingUsers(true);
    try {
      const res = await fetch('/api/v1/admin/users');
      if (res.ok) setUsers(await res.json());
    } finally {
      setLoadingUsers(false);
    }
  }, []);

  useEffect(() => {
    if (status === 'authenticated' && (session?.user as any)?.name === superAdmin) {
      fetchUsers();
    }
  }, [status, session, superAdmin, fetchUsers]);

  if (status === 'loading' || (session?.user as any)?.name !== superAdmin) {
    return <div className="min-h-screen flex items-center justify-center text-sm text-slate-500">Loading...</div>;
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    setCreateError('');
    setNewCred(null);
    try {
      const res = await fetch('/api/v1/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password, nickname: nickname.trim() || undefined }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || '建号失败');
      setNewCred({ username: username.trim(), password });
      setUsername('');
      setPassword('');
      setNickname('');
      fetchUsers();
    } catch (err: any) {
      setCreateError(err.message);
    } finally {
      setCreating(false);
    }
  };

  const copyTalk = (u: string, p: string) => {
    const text = `你好！你的喵弟数据研究室账号已开通：\n账号：${u}\n密码：${p}\n登录地址：https://miaomiaodi.vip\n请登录后尽快前往「我的」修改初始密码。`;
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  const handleDisable = async (user: User) => {
    const newDisabled = user.disabled ? 0 : 1;
    const label = newDisabled ? '停用' : '启用';
    if (!confirm(`确认${label}用户「${user.username}」？${newDisabled ? '该用户将立即被踢下线。' : ''}`)) return;
    const res = await fetch(`/api/v1/admin/users/${user.id}/disable`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ disabled: newDisabled }),
    });
    const data = await res.json();
    setActionMsg(res.ok ? `已${label}用户「${user.username}」` : (data.detail || '操作失败'));
    fetchUsers();
  };

  const handleDelete = async (user: User) => {
    if (!confirm(`确认永久删除用户「${user.username}」？此操作不可恢复。`)) return;
    const res = await fetch(`/api/v1/admin/users/${user.id}`, { method: 'DELETE' });
    const data = await res.json();
    setActionMsg(res.ok ? `已删除用户「${user.username}」` : (data.detail || '删除失败'));
    fetchUsers();
  };

  const apiToken = (session?.user as any)?.apiToken as string | undefined;

  const _authHeaders = (extra?: Record<string, string>) => ({
    ...(apiToken ? { 'Authorization': `Bearer ${apiToken}` } : {}),
    ...extra,
  });

  const openUnlock = async (user: User) => {
    setUnlockTarget(user);
    setUnlockLoading(true);
    const [ul, wm] = await Promise.all([
      fetch(`/api/v1/admin/users/${user.id}/unlocks`, { headers: _authHeaders() }).then(r => r.json()).catch(() => []),
      fetch('/api/v1/admin/wc-matches').then(r => r.json()).catch(() => []),
    ]);
    setUnlocks(Array.isArray(ul) ? ul : []);
    setWcMatches(Array.isArray(wm) ? wm : []);
    setUnlockLoading(false);
  };

  const handleGrant = async (matchId: string) => {
    if (!unlockTarget) return;
    setGrantingId(matchId);
    const res = await fetch(`/api/v1/admin/users/${unlockTarget.id}/unlocks`, {
      method: 'POST',
      headers: _authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ match_id: matchId }),
    });
    if (res.ok) {
      const ul = await fetch(`/api/v1/admin/users/${unlockTarget.id}/unlocks`, { headers: _authHeaders() }).then(r => r.json()).catch(() => []);
      setUnlocks(Array.isArray(ul) ? ul : []);
    }
    setGrantingId(null);
  };

  const handleRevoke = async (matchId: string) => {
    if (!unlockTarget) return;
    if (!confirm(`确认撤销「${unlockTarget.username}」对 ${matchId} 的研报授权？`)) return;
    await fetch(`/api/v1/admin/users/${unlockTarget.id}/unlocks/${matchId}`, { method: 'DELETE', headers: _authHeaders() });
    const ul = await fetch(`/api/v1/admin/users/${unlockTarget.id}/unlocks`, { headers: _authHeaders() }).then(r => r.json()).catch(() => []);
    setUnlocks(Array.isArray(ul) ? ul : []);
  };

  const openReset = (user: User) => {
    setResetTarget(user);
    setResetPwd(genPassword());
    setResetResult(null);
  };

  const handleReset = async () => {
    if (!resetTarget) return;
    setResetting(true);
    const res = await fetch(`/api/v1/admin/users/${resetTarget.id}/reset-password`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_password: resetPwd }),
    });
    const data = await res.json();
    if (res.ok) {
      setResetResult({ username: resetTarget.username, password: resetPwd });
    } else {
      setActionMsg(data.detail || '重置失败');
      setResetTarget(null);
    }
    setResetting(false);
  };

  const inputCls = "w-full bg-white border border-slate-200 rounded-xl px-4 py-2 font-mono text-slate-900 focus:ring-2 focus:ring-indigo-500 outline-none text-sm";
  const btnCls = (color: string) => `text-xs font-bold px-3 py-1.5 rounded-lg ${color} transition-colors`;

  return (
    <div className="min-h-screen bg-slate-50 p-4 sm:p-6 flex flex-col gap-4 max-w-2xl mx-auto pt-10">
      <div className="glass p-5 rounded-3xl shadow-lg bg-white/80 border border-white">
        <div className="flex items-center gap-3 mb-5">
          <div className="w-10 h-10 bg-slate-900 rounded-xl flex items-center justify-center text-white text-lg">👤</div>
          <div>
            <h1 className="text-xl font-black text-slate-900">用户管理</h1>
            <p className="text-xs text-slate-500">开通账号 · 重置密码 · 停用 · 删除</p>
          </div>
        </div>

        <form onSubmit={handleCreate} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-bold text-slate-500 uppercase block mb-1">用户名</label>
              <input className={inputCls} value={username} onChange={e => setUsername(e.target.value)} placeholder="登录用，≥2位" required />
            </div>
            <div>
              <label className="text-xs font-bold text-slate-500 uppercase block mb-1">昵称（可选）</label>
              <input className={inputCls} value={nickname} onChange={e => setNickname(e.target.value)} placeholder="显示名" />
            </div>
          </div>
          <div>
            <label className="text-xs font-bold text-slate-500 uppercase block mb-1">初始密码</label>
            <div className="flex gap-2">
              <input className={inputCls} value={password} onChange={e => setPassword(e.target.value)} placeholder="≥6位，含大小写" required />
              <button type="button" onClick={() => setPassword(genPassword())}
                className="shrink-0 text-xs font-bold px-3 py-2 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 transition-colors">
                随机
              </button>
            </div>
          </div>
          {createError && <p className="text-red-500 text-sm bg-red-50 rounded-lg p-2 border border-red-100">{createError}</p>}
          <button type="submit" disabled={creating}
            className="w-full py-3 bg-indigo-600 text-white font-black rounded-xl shadow-lg shadow-indigo-200 active:scale-[0.98] transition-all disabled:opacity-50">
            {creating ? '开通中...' : '开通账号 ⚡'}
          </button>
        </form>
      </div>

      {newCred && (
        <div className="glass p-5 rounded-3xl shadow-lg bg-emerald-50/80 border border-emerald-200 animate-in slide-in-from-bottom-4">
          <p className="text-sm font-black text-emerald-800 mb-2">✅ 账号已开通</p>
          <div className="font-mono text-sm text-slate-800 bg-white rounded-xl p-3 border border-emerald-100 mb-3">
            <p>账号：<span className="font-bold">{newCred.username}</span></p>
            <p>密码：<span className="font-bold">{newCred.password}</span></p>
          </div>
          <button onClick={() => copyTalk(newCred.username, newCred.password)}
            className="w-full py-2.5 font-bold rounded-xl bg-emerald-600 text-white text-sm active:scale-[0.98] transition-all">
            {copied ? '✅ 已复制话术！' : '复制开通话术（发微信用）'}
          </button>
        </div>
      )}

      {actionMsg && (
        <div className="text-sm text-center font-bold text-indigo-600 bg-indigo-50 rounded-xl p-3 border border-indigo-100">
          {actionMsg}
          <button onClick={() => setActionMsg('')} className="ml-2 text-indigo-400 text-xs">✕</button>
        </div>
      )}

      {resetTarget && (
        <div className="glass p-5 rounded-3xl shadow-lg bg-amber-50/80 border border-amber-200">
          <p className="text-sm font-black text-amber-800 mb-3">🔑 重置「{resetTarget.username}」的密码</p>
          {resetResult ? (
            <>
              <div className="font-mono text-sm text-slate-800 bg-white rounded-xl p-3 border border-amber-100 mb-3">
                <p>账号：<span className="font-bold">{resetResult.username}</span></p>
                <p>新密码：<span className="font-bold">{resetResult.password}</span></p>
              </div>
              <button onClick={() => copyTalk(resetResult.username, resetResult.password)}
                className="w-full py-2.5 font-bold rounded-xl bg-amber-600 text-white text-sm mb-2 active:scale-[0.98] transition-all">
                {copied ? '✅ 已复制！' : '复制话术'}
              </button>
              <button onClick={() => setResetTarget(null)} className="w-full text-xs text-slate-500 py-1">关闭</button>
            </>
          ) : (
            <>
              <div className="flex gap-2 mb-3">
                <input className={inputCls} value={resetPwd} onChange={e => setResetPwd(e.target.value)} />
                <button type="button" onClick={() => setResetPwd(genPassword())}
                  className="shrink-0 text-xs font-bold px-3 rounded-xl bg-amber-100 hover:bg-amber-200 text-amber-800 transition-colors">
                  随机
                </button>
              </div>
              <div className="flex gap-2">
                <button onClick={handleReset} disabled={resetting}
                  className="flex-1 py-2.5 font-bold rounded-xl bg-amber-600 text-white text-sm disabled:opacity-50">
                  {resetting ? '重置中...' : '确认重置'}
                </button>
                <button onClick={() => setResetTarget(null)} className="px-4 font-bold text-sm rounded-xl bg-slate-100 text-slate-700">取消</button>
              </div>
            </>
          )}
        </div>
      )}

      <div className="glass p-5 rounded-3xl shadow-lg bg-white/80 border border-white">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-black text-slate-900 uppercase">全部用户 ({users.filter(u => u.auth_source === 'username').length})</h2>
          <button onClick={fetchUsers} className="text-xs font-bold text-indigo-600 bg-indigo-50 px-3 py-1.5 rounded-lg hover:bg-indigo-100">刷新</button>
        </div>
        {loadingUsers ? (
          <p className="text-sm text-slate-400 text-center py-4">加载中...</p>
        ) : (
          <div className="space-y-2 max-h-[60vh] overflow-y-auto pr-1">
            {users.filter(u => u.auth_source === 'username').map(u => (
              <div key={u.id} className={`flex items-center justify-between p-3 rounded-xl border text-sm ${u.disabled ? 'bg-red-50 border-red-100' : 'bg-white border-slate-100'}`}>
                <div className="min-w-0">
                  <p className="font-bold text-slate-800 truncate">{u.username}</p>
                  <p className="text-xs text-slate-400">{u.nickname} · {u.disabled ? '🔴 已停用' : '🟢 正常'} · {u.created_at?.slice(0, 10)}</p>
                </div>
                <div className="flex gap-1.5 shrink-0 ml-2">
                  <button onClick={() => openUnlock(u)} className={btnCls('bg-indigo-50 text-indigo-700 hover:bg-indigo-100')}>研报授权</button>
                  <button onClick={() => openReset(u)} className={btnCls('bg-amber-50 text-amber-700 hover:bg-amber-100')}>重置密码</button>
                  <button onClick={() => handleDisable(u)} className={btnCls(u.disabled ? 'bg-green-50 text-green-700 hover:bg-green-100' : 'bg-slate-100 text-slate-600 hover:bg-slate-200')}>
                    {u.disabled ? '启用' : '停用'}
                  </button>
                  <button onClick={() => handleDelete(u)} className={btnCls('bg-red-50 text-red-600 hover:bg-red-100')}>删除</button>
                </div>
              </div>
            ))}
            {users.filter(u => u.auth_source === 'username').length === 0 && (
              <p className="text-sm text-slate-400 text-center py-4">暂无用户名注册用户</p>
            )}
          </div>
        )}
      </div>
      {/* 研报授权弹窗 */}
      {unlockTarget && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4" onClick={() => setUnlockTarget(null)}>
          <div className="bg-white rounded-3xl shadow-2xl w-full max-w-md max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="p-5 border-b border-slate-100 flex items-center justify-between">
              <div>
                <p className="font-black text-slate-900">研报授权</p>
                <p className="text-xs text-slate-500">用户：{unlockTarget.username}</p>
              </div>
              <button onClick={() => setUnlockTarget(null)} className="text-slate-400 hover:text-slate-600 text-lg">✕</button>
            </div>

            {unlockLoading ? (
              <p className="text-sm text-slate-400 text-center py-8">加载中...</p>
            ) : (
              <div className="p-4 flex flex-col gap-4">
                {/* 已授权列表 */}
                <div>
                  <p className="text-xs font-bold text-slate-500 uppercase mb-2">已授权场次（{unlocks.length}）</p>
                  {unlocks.length === 0 ? (
                    <p className="text-xs text-slate-400 text-center py-3 bg-slate-50 rounded-xl">暂无授权</p>
                  ) : (
                    <div className="space-y-1.5">
                      {unlocks.map(u => (
                        <div key={u.match_id} className="flex items-center justify-between bg-indigo-50 rounded-xl px-3 py-2">
                          <div>
                            <p className="text-xs font-mono font-bold text-indigo-800">{u.match_id}</p>
                            <p className="text-xs text-slate-500">{u.unlock_source} · {u.unlocked_at?.slice(0, 10)}</p>
                          </div>
                          <button onClick={() => handleRevoke(u.match_id)} className="text-xs font-bold text-red-500 hover:text-red-700 shrink-0 ml-2">撤销</button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* 可授权场次 */}
                <div>
                  <p className="text-xs font-bold text-slate-500 uppercase mb-2">近期 WC 场次（点击授权）</p>
                  {wcMatches.length === 0 ? (
                    <p className="text-xs text-slate-400 text-center py-3 bg-slate-50 rounded-xl">近 7 天内暂无 WC 场次</p>
                  ) : wcMatches.filter(m => m.has_report).length === 0 ? (
                    <p className="text-xs text-slate-400 text-center py-3 bg-slate-50 rounded-xl">场次已就绪，研报尚未生成，暂不可授权</p>
                  ) : (
                    <div className="space-y-1.5">
                      {wcMatches.filter(m => m.has_report).map(m => {
                        const alreadyGranted = unlocks.some(u => u.match_id === m.match_id);
                        return (
                          <div key={m.match_id} className={`flex items-center justify-between rounded-xl px-3 py-2 ${alreadyGranted ? 'bg-green-50' : 'bg-slate-50'}`}>
                            <div>
                              <p className="text-xs font-bold text-slate-800">{m.home_team} vs {m.away_team}</p>
                              <p className="text-xs text-slate-500">{m.starting_at?.slice(0, 10)} · {m.match_id}</p>
                            </div>
                            {alreadyGranted ? (
                              <span className="text-xs text-green-600 font-bold shrink-0 ml-2">已授权</span>
                            ) : (
                              <button
                                onClick={() => handleGrant(m.match_id)}
                                disabled={grantingId === m.match_id}
                                className="text-xs font-bold text-indigo-600 hover:text-indigo-800 shrink-0 ml-2 disabled:opacity-40"
                              >
                                {grantingId === m.match_id ? '授权中...' : '授权'}
                              </button>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
