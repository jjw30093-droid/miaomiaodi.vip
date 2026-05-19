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

export default function DevicesPanel() {
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
    } finally {
      setRevoking(null);
    }
  };

  if (loading) {
    return <div className="text-center py-12 text-sm" style={{ color: 'rgba(250,250,252,0.3)' }}>加载中...</div>;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="text-xs" style={{ color: 'rgba(250,250,252,0.4)' }}>
        最多同时 2 台设备在线。新设备登录时，最早登录的设备将被自动踢出。
      </div>

      {msg && (
        <div
          className="text-center py-2 px-4 rounded-xl text-sm font-bold"
          style={{ background: 'rgba(0,240,255,0.08)', color: '#00f0ff', border: '1px solid rgba(0,240,255,0.2)' }}
        >
          {msg}
        </div>
      )}

      {sessions.length === 0 ? (
        <div className="text-center py-8 text-sm" style={{ color: 'rgba(250,250,252,0.3)' }}>暂无活跃设备</div>
      ) : (
        sessions.map(s => (
          <div
            key={s.jti}
            className="rounded-2xl p-5 flex items-center gap-4"
            style={{
              background: s.is_current ? 'rgba(0,240,255,0.05)' : '#12161b',
              border: `1px solid ${s.is_current ? 'rgba(0,240,255,0.2)' : 'rgba(255,255,255,0.07)'}`,
            }}
          >
            <div className="text-2xl">
              {s.device_label?.includes('iPhone') ? '📱'
                : s.device_label?.includes('iPad') ? '🗒️'
                : s.device_label?.includes('Mac') ? '💻'
                : s.device_label?.includes('Android') ? '📲'
                : '🖥️'}
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-bold text-sm text-white truncate">{s.device_label || '未知设备'}</div>
              <div className="text-xs mt-0.5" style={{ color: 'rgba(250,250,252,0.4)' }}>
                {s.ip && <span className="mr-2">{s.ip}</span>}
                <span>最近活跃：{s.last_seen_at?.slice(0, 16).replace('T', ' ')}</span>
              </div>
            </div>
            {s.is_current ? (
              <span
                className="text-xs font-black px-2 py-1 rounded-full whitespace-nowrap"
                style={{ background: 'rgba(0,240,255,0.1)', color: '#00f0ff', border: '1px solid rgba(0,240,255,0.3)' }}
              >
                本机
              </span>
            ) : (
              <button
                onClick={() => revokeSession(s.jti)}
                disabled={revoking === s.jti}
                className="text-xs px-3 py-1.5 rounded-xl font-bold transition-all active:scale-95 disabled:opacity-40"
                style={{ background: 'rgba(255,61,84,0.1)', color: '#ff3d54', border: '1px solid rgba(255,61,84,0.2)' }}
              >
                {revoking === s.jti ? '...' : '踢出'}
              </button>
            )}
          </div>
        ))
      )}
    </div>
  );
}
