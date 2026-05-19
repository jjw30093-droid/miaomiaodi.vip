'use client';

import { useState } from 'react';
import { useRedeemCdk } from '@/hooks/useRedeemCdk';

function formatCountdown(expiresAt: string | null | undefined): string {
  if (!expiresAt) return '未开通';
  const diff = new Date(expiresAt).getTime() - Date.now();
  if (diff <= 0) return '已到期';
  const days = Math.floor(diff / 86400000);
  const hours = Math.floor((diff % 86400000) / 3600000);
  if (days > 0) return `${days} 天 ${hours} 小时`;
  return `${hours} 小时`;
}

export default function VipPanel({ profile }: { profile: any }) {
  const [cdkCode, setCdkCode] = useState('');
  const { loading, message, redeem, clearMessage } = useRedeemCdk();
  const isVip = profile?.role === 'vip';
  const expiresAt = profile?.vip_expires_at;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    clearMessage();
    await redeem(cdkCode);
    if (!loading) setCdkCode('');
  };

  return (
    <div className="flex flex-col gap-6">
      {/* VIP 状态卡 */}
      <div
        className="rounded-2xl p-6"
        style={{
          background: isVip
            ? 'linear-gradient(135deg, rgba(191,165,93,0.15) 0%, rgba(13,15,20,0.9) 100%)'
            : '#12161b',
          border: `1px solid ${isVip ? 'rgba(191,165,93,0.4)' : 'rgba(255,255,255,0.07)'}`,
        }}
      >
        <div className="flex items-center gap-3 mb-4">
          <span className="text-3xl">{isVip ? '⭐' : '🔒'}</span>
          <div>
            <div className="font-black text-lg" style={{ color: isVip ? '#BFA55D' : 'rgba(250,250,252,0.4)' }}>
              {isVip ? 'VIP 会员' : '普通用户'}
            </div>
            {isVip && expiresAt && (
              <div className="text-xs" style={{ color: 'rgba(250,250,252,0.5)' }}>
                到期：{new Date(expiresAt).toLocaleDateString('zh-CN')}
              </div>
            )}
          </div>
        </div>

        {isVip ? (
          <div
            className="rounded-xl p-4 text-center"
            style={{ background: 'rgba(191,165,93,0.08)', border: '1px solid rgba(191,165,93,0.15)' }}
          >
            <div className="text-2xl font-black" style={{ color: '#BFA55D' }}>
              {formatCountdown(expiresAt)}
            </div>
            <div className="text-xs mt-1" style={{ color: 'rgba(250,250,252,0.4)' }}>剩余有效时长</div>
          </div>
        ) : (
          <div className="text-sm" style={{ color: 'rgba(250,250,252,0.4)' }}>
            购买 VIP 周卡或月卡后使用卡密激活，即可解锁全部深度研报。
          </div>
        )}
      </div>

      {/* CDK 兑换 */}
      <div
        className="rounded-2xl p-5 flex flex-col gap-4"
        style={{ background: '#12161b', border: '1px solid rgba(255,255,255,0.07)' }}
      >
        <span className="text-xs font-bold uppercase tracking-widest" style={{ color: 'rgba(191,165,93,0.8)' }}>
          兑换卡密
        </span>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <input
            type="text"
            placeholder="请输入 VIP 激活码"
            value={cdkCode}
            onChange={e => setCdkCode(e.target.value.toUpperCase())}
            maxLength={20}
            className="w-full px-4 py-3 rounded-xl text-sm font-mono tracking-widest uppercase outline-none transition-all"
            style={{
              background: 'rgba(255,255,255,0.05)',
              border: '1px solid rgba(255,255,255,0.10)',
              color: '#fff',
              caretColor: '#BFA55D',
            }}
          />
          {message.text && (
            <div
              className="px-4 py-3 rounded-xl text-sm font-bold"
              style={{
                background: message.type === 'success' ? 'rgba(191,165,93,0.08)' : 'rgba(255,61,84,0.08)',
                border: `1px solid ${message.type === 'success' ? 'rgba(191,165,93,0.2)' : 'rgba(255,61,84,0.2)'}`,
                color: message.type === 'success' ? '#BFA55D' : '#ff3d54',
              }}
            >
              {message.text}
            </div>
          )}
          <button
            type="submit"
            disabled={loading || !cdkCode.trim()}
            className="w-full py-4 rounded-xl font-black text-base transition-all active:scale-[0.97] disabled:opacity-40"
            style={{ background: '#BFA55D', color: '#080c1a' }}
          >
            {loading ? '验证中...' : '立即兑换'}
          </button>
        </form>
      </div>
    </div>
  );
}
