'use client';

import { useState } from 'react';
import { useRedeemCdk } from '@/hooks/useRedeemCdk';

interface Props {
  isDark: boolean;
}

export default function RedeemCdkRow({ isDark }: Props) {
  if (process.env.NEXT_PUBLIC_ENABLE_CDK !== 'true') return null;
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState('');
  const { loading, message, redeem, clearMessage } = useRedeemCdk();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    clearMessage();
    await redeem(code);
    if (!loading) setCode('');
  };

  return (
    <div id="redeem-cdk-row">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-1 py-0.5 transition-all active:scale-[0.99]"
      >
        <span className="text-[15px] font-bold" style={{ color: isDark ? '#fff' : '#191c1d' }}>
          兑换 CDK 激活码
        </span>
        <span className="text-[13px] font-bold transition-transform duration-200"
          style={{ color: isDark ? 'rgba(255,255,255,0.35)' : '#5b3f43', transform: open ? 'rotate(90deg)' : 'none' }}>
          ›
        </span>
      </button>

      {open && (
        <form onSubmit={handleSubmit} className="flex flex-col gap-3 mt-3">
          <input
            type="text"
            placeholder="请输入 VIP 激活码"
            value={code}
            onChange={e => setCode(e.target.value.toUpperCase())}
            maxLength={20}
            className="w-full px-4 py-3 rounded-2xl text-[15px] font-mono font-bold tracking-widest uppercase outline-none transition-all"
            style={{
              background: isDark ? 'rgba(255,255,255,0.06)' : '#f5f0ed',
              border: isDark ? '1px solid rgba(255,255,255,0.12)' : '1px solid rgba(25,28,29,0.12)',
              color: isDark ? '#fff' : '#191c1d',
              caretColor: isDark ? '#E91E63' : '#b7004d',
            }}
          />
          {message.text && (
            <div className="px-4 py-3 rounded-xl text-[13px] font-bold"
              style={{
                background: message.type === 'success' ? (isDark ? 'rgba(74,222,128,0.08)' : 'rgba(15,118,110,0.07)') : (isDark ? 'rgba(248,113,113,0.08)' : 'rgba(183,0,77,0.07)'),
                border: `1px solid ${message.type === 'success' ? (isDark ? 'rgba(74,222,128,0.2)' : 'rgba(15,118,110,0.18)') : (isDark ? 'rgba(248,113,113,0.2)' : 'rgba(183,0,77,0.18)')}`,
                color: message.type === 'success' ? (isDark ? '#4ade80' : '#0f766e') : (isDark ? '#f87171' : '#b7004d'),
              }}>
              {message.text}
            </div>
          )}
          <button
            type="submit"
            disabled={loading || !code.trim()}
            className="w-full py-3.5 rounded-2xl font-black text-[15px] italic tracking-tight transition-all active:scale-[0.97] disabled:opacity-40"
            style={isDark
              ? { background: 'linear-gradient(135deg, #E91E63 0%, #FF00E5 100%)', color: '#fff' }
              : { background: '#b7004d', color: '#fff' }
            }
          >
            {loading ? '验证中...' : '立即兑换'}
          </button>
        </form>
      )}
    </div>
  );
}
