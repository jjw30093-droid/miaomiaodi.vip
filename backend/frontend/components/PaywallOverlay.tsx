'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useSession } from 'next-auth/react';
import { apiClient } from '@/lib/apiClient';

const LIME   = '#baff00';
const RED    = '#ff3d54';
const BG     = 'rgba(5, 6, 16, 0.82)';
const BORDER = 'rgba(255,255,255,0.08)';

export default function PaywallOverlay() {
  const pathname = usePathname();
  const router = useRouter();
  const { data: session } = useSession();
  
  const [showCDKModal, setShowCDKModal] = useState(false);
  const [cdkCode, setCdkCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState({ type: '', text: '' });

  const trackEvent = (eventName: string, metadata: any = {}) => {
    console.log(`[Tracking] ${eventName}`, metadata);
    const apiHost = window.location.hostname;
    fetch(`http://${apiHost}:8000/api/v1/track`, {
      method: 'POST',
      body: JSON.stringify({ event: eventName, timestamp: Date.now(), ...metadata })
    }).catch(() => {});
  };

  const handleRedeem = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!cdkCode.trim()) return;
    trackEvent('cdk_submit_attempt', { code_length: cdkCode.length });
    setLoading(true);
    setMessage({ type: '', text: '' });
    try {
      const res = await apiClient.post<any>('/redeem', {
        cdk_code: cdkCode,
        username: session?.user?.name || 'anonymous'
      });
      setMessage({ type: 'success', text: res.message || '核销成功！' });
      trackEvent('cdk_redeem_success', { username: session?.user?.name || 'anonymous' });
      setTimeout(() => { router.refresh(); }, 1400);
    } catch (err: any) {
      setMessage({ type: 'error', text: err.message || '卡密无效或已被使用' });
    } finally {
      setLoading(false);
    }
  };

  /* ── 未登录 Paywall ── */
  if (!session) {
    return (
      <div className="absolute inset-x-0 bottom-0 h-[80%] flex flex-col items-center justify-end pb-20 z-20">
        {/* 渐变遮罩：从深蓝黑渐变透明 */}
        <div
          className="absolute inset-0"
          style={{
            background: 'linear-gradient(to top, #050610 35%, rgba(5,6,16,0.92) 60%, transparent 100%)',
            backdropFilter: 'blur(6px)',
          }}
        />
        <div className="relative z-30 w-full max-w-lg mx-auto px-6">
          <div
            className="p-10 rounded-[2.5rem] flex flex-col items-center text-center"
            style={{
              background: BG,
              border: `1px solid ${BORDER}`,
              boxShadow: '0 32px 80px rgba(0,0,0,0.7), inset 0 1px 0 rgba(255,255,255,0.05)',
              backdropFilter: 'blur(32px)',
            }}
          >
            <div
              className="w-16 h-16 rounded-2xl flex items-center justify-center mb-6 text-3xl"
              style={{
                background: 'rgba(186,255,0,0.08)',
                border: '1px solid rgba(186,255,0,0.2)',
              }}
            >
              🔒
            </div>
            <h3 className="text-2xl font-black mb-3" style={{ color: '#ffffff' }}>登录后解锁分析</h3>
            <p className="mb-8 text-sm leading-relaxed" style={{ color: 'rgba(250,250,252,0.5)' }}>
              实验室成员可查看完整{' '}
              <span style={{ color: '#ffffff', fontWeight: 700 }}>xG 分布图</span>{' '}
              与{' '}
              <span style={{ color: '#ffffff', fontWeight: 700 }}>深度盘口结论</span>。
            </p>
            <Link
              href={`/login?callbackUrl=${encodeURIComponent(pathname)}`}
              className="w-full py-4 font-black rounded-xl text-base transition-all active:scale-[0.98]"
              style={{
                backgroundColor: LIME,
                color: '#050610',
                boxShadow: `0 0 24px rgba(186,255,0,0.35)`,
              }}
            >
              登 录 激 活
            </Link>
          </div>
        </div>
      </div>
    );
  }

  /* ── 已登录但配额耗尽 Paywall ── */
  return (
    <div className="absolute inset-x-0 bottom-0 h-[85%] flex flex-col items-center justify-center z-40">
      {/* 渐变遮罩 */}
      <div
        className="absolute inset-0"
        style={{
          background: 'linear-gradient(to top, #050610 15%, rgba(5,6,16,0.9) 50%, rgba(5,6,16,0.6) 100%)',
          backdropFilter: 'blur(16px)',
        }}
      />

      {!showCDKModal ? (
        /* ── 初始 Paywall 提示 ── */
        <div className="relative z-50 text-center space-y-6 max-w-md px-6">
          <span
            className="inline-block px-4 py-1 rounded-full text-xs font-black uppercase tracking-widest animate-pulse"
            style={{
              backgroundColor: 'rgba(255,61,84,0.1)',
              border: `1px solid ${RED}`,
              color: RED,
            }}
          >
            QUOTA EXHAUSTED
          </span>
          <h2 className="text-3xl font-black leading-tight" style={{ color: '#ffffff' }}>
            免费额度已用完
            <br />
            <span style={{ color: 'rgba(250,250,252,0.6)', fontWeight: 500, fontSize: '1.1rem' }}>
              需使用卡密解锁研报
            </span>
          </h2>
          <button
            onClick={() => setShowCDKModal(true)}
            className="w-full py-4 font-black rounded-xl text-lg transition-all animate-breathe active:scale-[0.97]"
            style={{
              backgroundColor: LIME,
              color: '#050610',
            }}
          >
            立即激活 / 兑换卡密 →
          </button>
        </div>
      ) : (
        /* ── CDK 兑换弹窗 ── */
        <div className="relative z-50 w-full max-w-3xl mx-auto px-5">
          <div
            className="overflow-hidden rounded-[2rem] flex flex-col md:flex-row min-h-[420px] relative"
            style={{
              background: BG,
              backdropFilter: 'blur(36px) saturate(140%)',
              border: `1px solid ${BORDER}`,
              boxShadow: '0 40px 120px rgba(0,0,0,0.85), inset 0 1px 0 rgba(255,255,255,0.06)',
            }}
          >
            {/* 关闭按钮 */}
            <button
              onClick={() => setShowCDKModal(false)}
              className="absolute top-5 right-5 font-black text-xl z-10 transition-colors"
              style={{ color: 'rgba(250,250,252,0.3)' }}
            >
              ✕
            </button>

            {/* 左：扫码加 V */}
            <div
              className="md:w-[45%] p-10 flex flex-col items-center justify-center cursor-pointer"
              style={{ borderRight: '1px solid rgba(255,255,255,0.06)' }}
              onClick={() => trackEvent('view_wechat_qr', { source: 'paywall_left_panel' })}
            >
              {/* 二维码占位框 */}
              <div
                className="w-44 h-44 rounded-2xl flex items-center justify-center mb-6 text-xs font-bold text-center transition-all hover:scale-105"
                style={{
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid rgba(255,255,255,0.10)',
                  color: 'rgba(250,250,252,0.3)',
                }}
              >
                WeChat QR
                <br />Placeholder
              </div>
              <h4 className="text-lg font-black mb-1" style={{ color: '#ffffff' }}>添加主理人微信</h4>
              <p className="text-xs text-center leading-relaxed" style={{ color: 'rgba(250,250,252,0.4)' }}>
                扫描二维码获取专享权限
                <br />或单场研报兑换卡密
              </p>
            </div>

            {/* 右：卡密激活 */}
            <div className="md:flex-1 p-10 flex flex-col justify-center">
              <h4 className="text-xl font-black mb-1" style={{ color: '#ffffff' }}>使用卡密兑换</h4>
              <p className="text-xs mb-7" style={{ color: 'rgba(250,250,252,0.4)' }}>
                输入 10 位 CDK 码立即解锁本文
              </p>

              <form onSubmit={handleRedeem} className="space-y-4">
                <input
                  type="text"
                  placeholder="请输入您的激活码/CDK"
                  value={cdkCode}
                  onChange={e => setCdkCode(e.target.value.toUpperCase())}
                  maxLength={10}
                  className="w-full px-5 py-4 rounded-xl text-sm font-black tracking-widest uppercase transition-all outline-none"
                  style={{
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.10)',
                    color: '#ffffff',
                    caretColor: LIME,
                  }}
                  onFocus={e => (e.currentTarget.style.borderColor = 'rgba(186,255,0,0.35)')}
                  onBlur={e => (e.currentTarget.style.borderColor = 'rgba(255,255,255,0.10)')}
                />

                {message.text && (
                  <div
                    className="p-3 rounded-xl text-xs font-bold"
                    style={{
                      backgroundColor:
                        message.type === 'success'
                          ? 'rgba(186,255,0,0.08)'
                          : 'rgba(255,61,84,0.08)',
                      border: `1px solid ${message.type === 'success' ? 'rgba(186,255,0,0.2)' : 'rgba(255,61,84,0.2)'}`,
                      color: message.type === 'success' ? LIME : RED,
                    }}
                  >
                    {message.text}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={loading || !cdkCode}
                  className="w-full py-4 font-black rounded-xl text-base transition-all animate-breathe active:scale-[0.97] disabled:opacity-40"
                  style={{
                    backgroundColor: LIME,
                    color: '#050610',
                  }}
                >
                  {loading ? '正在验证...' : '立 即 解 锁'}
                </button>
              </form>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
