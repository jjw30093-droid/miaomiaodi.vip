'use client';

import { useEffect, useState } from 'react';
import { signOut } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { SESSION_REVOKED_EVENT } from '@/lib/apiClient';

export default function SessionRevokedProvider() {
  const [show, setShow] = useState(false);
  const router = useRouter();

  useEffect(() => {
    const handler = () => setShow(true);
    window.addEventListener(SESSION_REVOKED_EVENT, handler);
    return () => window.removeEventListener(SESSION_REVOKED_EVENT, handler);
  }, []);

  if (!show) return null;

  const handleConfirm = async () => {
    setShow(false);
    await signOut({ redirect: false });
    router.push('/login?reason=revoked');
  };

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center p-6"
      style={{ background: 'rgba(5,6,16,0.85)', backdropFilter: 'blur(12px)' }}
    >
      <div
        className="w-full max-w-sm rounded-[2rem] p-8 text-center flex flex-col items-center gap-5"
        style={{
          background: '#0d0f14',
          border: '1px solid rgba(255,80,80,0.25)',
          boxShadow: '0 0 60px rgba(255,0,60,0.15)',
        }}
      >
        <div
          className="w-16 h-16 rounded-2xl flex items-center justify-center text-3xl"
          style={{ background: 'rgba(255,61,84,0.1)', border: '1px solid rgba(255,61,84,0.3)' }}
        >
          📵
        </div>
        <h3 className="text-xl font-black text-white">账号已在其他设备登录</h3>
        <p className="text-sm leading-relaxed" style={{ color: 'rgba(250,250,252,0.5)' }}>
          您的账号在另一台设备上完成了登录，当前会话已失效。
          <br />请重新登录以继续使用。
        </p>
        <button
          onClick={handleConfirm}
          className="w-full py-4 rounded-xl font-black text-base transition-all active:scale-[0.97]"
          style={{ background: '#ff3d54', color: '#fff' }}
        >
          我知道了，去重新登录
        </button>
      </div>
    </div>
  );
}
