'use client';

import { useState, useEffect, useCallback } from 'react';
import { useSession } from 'next-auth/react';
import { apiClient } from '@/lib/apiClient';

interface DeviceSession {
  jti: string;
  device_label: string;
  ip: string;
  created_at: string;
  last_seen_at: string;
  is_current: boolean;
}

function deviceIcon(label: string): string {
  if (label?.includes('iPhone')) return '📱';
  if (label?.includes('iPad')) return '🗒️';
  if (label?.includes('Mac')) return '💻';
  if (label?.includes('Android')) return '📲';
  return '🖥️';
}

interface Props {
  isDark: boolean;
}

export default function DevicesSection({ isDark }: Props) {
  const { data: session } = useSession();
  const apiToken = (session?.user as any)?.apiToken as string | undefined;
  const [sessions, setSessions] = useState<DeviceSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!apiToken) return;
    try {
      const data = await apiClient.get<DeviceSession[]>('/user/sessions', { token: apiToken });
      setSessions(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [apiToken]);

  useEffect(() => { load(); }, [load]);

  const revokeSession = async (jti: string) => {
    if (!apiToken || revoking) return;
    setRevoking(jti);
    try {
      await apiClient.delete(`/user/sessions/${jti}`, { token: apiToken });
      setSessions(s => s.filter(d => d.jti !== jti));
      setMsg('设备已踢出');
      setTimeout(() => setMsg(null), 2000);
    } catch (e: any) {
      setMsg(e.message || '操作失败');
      setTimeout(() => setMsg(null), 2500);
    } finally {
      setRevoking(null);
    }
  };

  if (loading) {
    return <p className="text-[13px] font-bold py-4 text-center animate-pulse"
      style={{ color: isDark ? 'rgba(255,255,255,0.35)' : '#5b3f43' }}>加载中...</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] font-bold" style={{ color: isDark ? 'rgba(255,255,255,0.4)' : '#5b3f43' }}>
        最多同时 2 台设备在线，新设备登录时最早设备将自动下线。
      </p>

      {msg && (
        <div className="text-center py-2 px-4 rounded-xl text-[13px] font-bold"
          style={{ background: isDark ? 'rgba(0,240,255,0.08)' : 'rgba(0,95,175,0.06)', color: isDark ? '#00f0ff' : '#005faf', border: `1px solid ${isDark ? 'rgba(0,240,255,0.2)' : 'rgba(0,95,175,0.15)'}` }}>
          {msg}
        </div>
      )}

      {sessions.length === 0 ? (
        <p className="text-center py-6 text-[15px] font-bold" style={{ color: isDark ? 'rgba(255,255,255,0.3)' : '#5b3f43' }}>
          暂无活跃设备
        </p>
      ) : (
        sessions.map(s => (
          <div key={s.jti} className="flex items-center gap-3 py-3 rounded-2xl px-3"
            style={isDark
              ? { background: s.is_current ? 'rgba(0,240,255,0.05)' : 'transparent', border: `1px solid ${s.is_current ? 'rgba(0,240,255,0.15)' : 'rgba(255,255,255,0.06)'}` }
              : { background: s.is_current ? 'rgba(0,95,175,0.05)' : 'transparent', border: `1px solid ${s.is_current ? 'rgba(0,95,175,0.15)' : 'rgba(25,28,29,0.08)'}` }
            }>
            <span className="text-2xl flex-shrink-0 select-none">{deviceIcon(s.device_label)}</span>
            <div className="flex-1 min-w-0">
              <p className="text-[15px] font-bold truncate" style={{ color: isDark ? '#fff' : '#191c1d' }}>
                {s.device_label || '未知设备'}
              </p>
              <p className="text-[13px] font-bold mt-0.5" style={{ color: isDark ? 'rgba(255,255,255,0.4)' : '#5b3f43' }}>
                {s.ip && <span className="mr-2">{s.ip}</span>}
                {s.last_seen_at?.slice(0, 16).replace('T', ' ')}
              </p>
            </div>
            {s.is_current ? (
              <span className="text-[13px] font-black px-2.5 py-1 rounded-full flex-shrink-0"
                style={{ background: isDark ? 'rgba(0,240,255,0.1)' : 'rgba(0,95,175,0.1)', color: isDark ? '#00f0ff' : '#005faf', border: `1px solid ${isDark ? 'rgba(0,240,255,0.25)' : 'rgba(0,95,175,0.2)'}` }}>
                本机
              </span>
            ) : (
              <button
                onClick={() => revokeSession(s.jti)}
                disabled={revoking === s.jti}
                className="text-[13px] font-bold px-3 py-1.5 rounded-xl flex-shrink-0 transition-all active:scale-95 disabled:opacity-40"
                style={{ background: isDark ? 'rgba(248,113,113,0.1)' : 'rgba(183,0,77,0.06)', color: isDark ? '#f87171' : '#b7004d', border: `1px solid ${isDark ? 'rgba(248,113,113,0.2)' : 'rgba(183,0,77,0.15)'}` }}>
                {revoking === s.jti ? '...' : '踢出'}
              </button>
            )}
          </div>
        ))
      )}
    </div>
  );
}
