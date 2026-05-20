'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useSession, signIn } from 'next-auth/react';
import { apiClient } from '@/lib/apiClient';

const LIME   = '#baff00';
const RED    = '#ff3d54';
const BG     = 'rgba(5, 6, 16, 0.82)';
const BORDER = 'rgba(255,255,255,0.08)';

const TEMP_PRICE_CNY = 29.9; // TODO Day 2: 接入 report_store.price_cny 字段

const _enableCdk    = process.env.NEXT_PUBLIC_ENABLE_CDK === 'true';
const _enableWechat = process.env.NEXT_PUBLIC_ENABLE_WECHAT_LOGIN === 'true';

type PaywallAccessLevel = 'guest' | 'registered' | 'unlocked' | 'vip';
type PaywallUnlockReason = 'free_match' | 'vip' | 'single_unlock' | null;

interface PaywallOverlayProps {
  accessLevel?: PaywallAccessLevel;
  unlockReason?: PaywallUnlockReason;
  matchId?: string | number;
}

export default function PaywallOverlay({
  accessLevel,
  unlockReason,
  matchId,
}: PaywallOverlayProps = {}) {
  const pathname = usePathname();
  const router = useRouter();
  const { data: session } = useSession();
  
  const [showCDKModal, setShowCDKModal] = useState(false);
  const [cdkCode, setCdkCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState({ type: '', text: '' });

  const [buyLoading, setBuyLoading] = useState(false);
  const [buyMsg, setBuyMsg] = useState<{ type: string; text: string }>({ type: '', text: '' });
  const [orderNo, setOrderNo] = useState<string | null>(null);

  // Bug 4: 拉取当前用户在当前 match 的 pending 订单（若存在），用于显示"我已支付，刷新状态"卡片
  const [pendingOrder, setPendingOrder] = useState<{
    order_no: string;
    product_name: string;
    amount_yuan: number;
    expires_at: string;
    seconds_left: number;
  } | null>(null);
  const [secondsLeft, setSecondsLeft] = useState<number>(0);

  // mount 后 + accessLevel 变化时拉一次 pending order（仅 registered 用户）
  useEffect(() => {
    if (accessLevel !== 'registered' || !matchId) return;
    const apiToken = (session?.user as any)?.apiToken as string | undefined;
    if (!apiToken) return;

    let cancelled = false;
    (async () => {
      try {
        const res = await apiClient.get<{
          pending_order: {
            order_no: string;
            product_name: string;
            amount_yuan: number;
            expires_at: string;
            seconds_left: number;
          } | null;
        }>('/orders/pending', {
          params: { match_id: String(matchId) },
          token: apiToken,
        });
        if (!cancelled && res.pending_order) {
          setPendingOrder(res.pending_order);
          setSecondsLeft(res.pending_order.seconds_left);
        }
      } catch {
        // 静默忽略：拉取失败不影响购买按钮渲染
      }
    })();

    return () => { cancelled = true; };
  }, [accessLevel, matchId, session]);

  // 客户端倒计时：每秒递减，到 0 自动清掉 pendingOrder（回到原购买按钮）
  useEffect(() => {
    if (!pendingOrder || secondsLeft <= 0) return;
    const id = setInterval(() => {
      setSecondsLeft((s) => {
        if (s <= 1) {
          setPendingOrder(null);
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [pendingOrder, secondsLeft]);

  const trackEvent = (eventName: string, metadata: any = {}) => {
    fetch('/api/v1/track', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event: eventName, timestamp: Date.now(), ...metadata })
    }).catch(() => {});
  };

  const handleRedeem = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!cdkCode.trim()) return;

    // CDK 兑换需要 WeChat JWT（apiToken）；
    // credentials 登录账号无 apiToken，后端无法识别身份。
    const apiToken = (session?.user as any)?.apiToken as string | undefined;
    if (!apiToken) {
      setMessage({
        type: 'error',
        text: '卡密兑换需要微信扫码登录。请先退出当前账号，使用微信扫码重新登录后再兑换。',
      });
      return;
    }

    trackEvent('cdk_submit_attempt', { code_length: cdkCode.length });
    setLoading(true);
    setMessage({ type: '', text: '' });
    try {
      // 调新接口 /cdk/redeem，携带正确字段名 {code} 和 JWT
      const res = await apiClient.post<any>('/cdk/redeem', { code: cdkCode }, { token: apiToken });
      setMessage({ type: 'success', text: res.message || '🎉 VIP 已激活！正在刷新权限...' });
      trackEvent('cdk_redeem_success', { user_id: (session?.user as any)?.id });

      // 后端返回重签的新 JWT，用它重新登录以刷新 session 中的 VIP 状态
      if (res.token) {
        await signIn('wechat', { api_token: res.token, redirect: false });
      }
      setTimeout(() => { router.refresh(); }, 1200);
    } catch (err: any) {
      setMessage({ type: 'error', text: err.message || '卡密无效或已被使用' });
    } finally {
      setLoading(false);
    }
  };

  const handleBuyMatch = async () => {
    const apiToken = (session?.user as any)?.apiToken as string | undefined;
    if (!apiToken) {
      setBuyMsg({ type: 'error', text: '请先使用微信扫码登录后再购买' });
      return;
    }
    if (!matchId) {
      setBuyMsg({ type: 'error', text: '无法识别比赛 ID，请刷新后重试' });
      return;
    }
    setBuyLoading(true);
    setBuyMsg({ type: '', text: '' });
    try {
      const productsRes = await apiClient.get<{
        products: Array<{ id: number; sku: string; price_yuan: number; name: string }>;
      }>('/products', { params: { type: 'single_match' } });
      const products = productsRes.products || [];
      const product =
        products.find((p) => p.sku === 'single_match_std') || products[0];
      if (!product) {
        setBuyMsg({ type: 'error', text: '暂无可购买的产品，请联系客服' });
        return;
      }
      const orderRes = await apiClient.post<{
        order_no: string;
        amount_yuan: number;
        product_name: string;
      }>(
        '/orders',
        { product_id: product.id, match_id: String(matchId) },
        { token: apiToken }
      );
      setOrderNo(orderRes.order_no);
      setBuyMsg({ type: 'success', text: `订单已创建（¥${orderRes.amount_yuan}），请联系客服完成支付` });
    } catch (err: any) {
      const detail: string = err?.message || '购买失败，请稍后重试';
      if (detail.includes('already have a paid order')) {
        setBuyMsg({ type: 'error', text: '您已购买本场研报，请刷新页面' });
      } else if (detail.includes('pending order')) {
        setBuyMsg({ type: 'error', text: '已有待支付订单，请联系客服完成支付' });
      } else {
        setBuyMsg({ type: 'error', text: detail });
      }
    } finally {
      setBuyLoading(false);
    }
  };

  /* ── guest Paywall：未登录 ── */
  if (accessLevel === 'guest' || (!accessLevel && !session)) {
    const redirectTarget = matchId ? `/report/${matchId}` : pathname;
    return (
      <div className="absolute inset-x-0 bottom-0 h-[80%] flex flex-col items-center justify-end pb-20 z-20">
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
            <h3 className="text-2xl font-black mb-3" style={{ color: '#ffffff' }}>登录后查看完整研报</h3>
            <p className="mb-8 text-sm leading-relaxed" style={{ color: 'rgba(250,250,252,0.5)' }}>
              注册账号即可解锁研报预览，购买后查看完整内容
            </p>
            <Link
              href={`/login?redirect=${encodeURIComponent(redirectTarget)}`}
              className="w-full py-4 font-black rounded-xl text-base transition-all active:scale-[0.98] mb-3"
              style={{
                backgroundColor: LIME,
                color: '#050610',
                boxShadow: `0 0 24px rgba(186,255,0,0.35)`,
              }}
            >
              立 即 登 录
            </Link>
            <Link
              href="/register"
              className="w-full py-3 font-black rounded-xl text-sm transition-all active:scale-[0.98]"
              style={{
                background: 'rgba(255,255,255,0.06)',
                border: `1px solid ${BORDER}`,
                color: 'rgba(250,250,252,0.7)',
              }}
            >
              注册新账号
            </Link>
          </div>
        </div>
      </div>
    );
  }

  /* ── registered Paywall：已登录但无 VIP / unlock ── */
  if (accessLevel === 'registered') {
    return (
      <div className="absolute inset-x-0 bottom-0 h-[85%] flex flex-col items-center justify-center z-40">
        <div
          className="absolute inset-0"
          style={{
            background: 'linear-gradient(to top, #050610 15%, rgba(5,6,16,0.9) 50%, rgba(5,6,16,0.6) 100%)',
            backdropFilter: 'blur(16px)',
          }}
        />
        <div className="relative z-50 text-center space-y-5 max-w-md px-6 w-full">
          <span
            className="inline-block px-4 py-1 rounded-full text-xs font-black uppercase tracking-widest"
            style={{
              backgroundColor: 'rgba(255,61,84,0.1)',
              border: `1px solid ${RED}`,
              color: RED,
            }}
          >
            PREMIUM CONTENT
          </span>
          <h2 className="text-3xl font-black leading-tight" style={{ color: '#ffffff' }}>
            解锁完整研报
            <br />
            <span style={{ color: 'rgba(250,250,252,0.6)', fontWeight: 500, fontSize: '1.1rem' }}>
              购买本场单场研报，或开通 VIP 查看全部内容
            </span>
          </h2>
          {pendingOrder ? (
            // 优先级 1：检测到历史 pending 订单 → 显示订单号 + 金额 + 倒计时 + 刷新按钮
            <div
              className="w-full py-4 px-4 rounded-xl text-sm font-bold text-center leading-relaxed"
              style={{
                backgroundColor: 'rgba(186,255,0,0.08)',
                border: '1px solid rgba(186,255,0,0.2)',
                color: LIME,
              }}
            >
              <div className="mb-1">⏳ 待支付订单 {pendingOrder.order_no}</div>
              <div className="text-xs font-normal mb-3" style={{ color: 'rgba(250,250,252,0.7)' }}>
                ¥{pendingOrder.amount_yuan} · 剩 {Math.floor(secondsLeft / 60)}分{secondsLeft % 60}秒过期
              </div>
              <button
                onClick={() => router.refresh()}
                className="w-full py-2 font-black rounded-lg text-xs transition-all active:scale-[0.97]"
                style={{
                  background: 'rgba(186,255,0,0.15)',
                  border: '1px solid rgba(186,255,0,0.35)',
                  color: LIME,
                }}
              >
                我已支付，刷新状态
              </button>
            </div>
          ) : orderNo ? (
            // 优先级 2：用户刚下单成功 → 显示订单号 + 联系客服文案（保留原行为）
            <div
              className="w-full py-4 rounded-xl text-sm font-bold text-center leading-relaxed"
              style={{
                backgroundColor: 'rgba(186,255,0,0.08)',
                border: '1px solid rgba(186,255,0,0.2)',
                color: LIME,
              }}
            >
              ✅ 订单 {orderNo} 已创建
              <br />
              <span className="text-xs font-normal" style={{ color: 'rgba(250,250,252,0.6)' }}>
                请联系客服完成支付以解锁研报
              </span>
            </div>
          ) : (
            // 优先级 3：无待支付订单 → 显示购买按钮
            <button
              onClick={handleBuyMatch}
              disabled={buyLoading}
              className="block w-full py-4 font-black rounded-xl text-lg transition-all active:scale-[0.97] disabled:opacity-50"
              style={{ backgroundColor: LIME, color: '#050610' }}
            >
              {buyLoading ? '处理中...' : `购买本场 ¥${TEMP_PRICE_CNY}`}
            </button>
          )}
          {buyMsg.text && (
            <div
              className="p-3 rounded-xl text-xs font-bold"
              style={{
                backgroundColor: buyMsg.type === 'success' ? 'rgba(186,255,0,0.08)' : 'rgba(255,61,84,0.08)',
                border: `1px solid ${buyMsg.type === 'success' ? 'rgba(186,255,0,0.2)' : 'rgba(255,61,84,0.2)'}`,
                color: buyMsg.type === 'success' ? LIME : RED,
              }}
            >
              {buyMsg.text}
            </div>
          )}
          <div className="flex gap-3">
            <Link
              href="/center"
              className="flex-1 py-3 font-black rounded-xl text-sm transition-all active:scale-[0.97]"
              style={{
                background: 'rgba(255,255,255,0.06)',
                border: `1px solid ${BORDER}`,
                color: 'rgba(250,250,252,0.8)',
              }}
            >
              开通 VIP
            </Link>
            <Link
              href="/center?tab=cdk"
              className="flex-1 py-3 font-black rounded-xl text-sm transition-all active:scale-[0.97]"
              style={{
                background: 'rgba(255,255,255,0.06)',
                border: `1px solid ${BORDER}`,
                color: 'rgba(250,250,252,0.8)',
              }}
            >
              使用兑换码
            </Link>
          </div>
        </div>
      </div>
    );
  }

  /* ── 兜底（unlocked/vip 理论上不应出现在 isGated=true 路径）── */
  if (accessLevel === 'unlocked' || accessLevel === 'vip') return null;

  /* ── 旧路径兼容：已登录但配额耗尽 Paywall（CDK 关闭时不显示）── */
  if (!_enableCdk) return null;

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
            style={{ backgroundColor: LIME, color: '#050610' }}
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
            <button
              onClick={() => setShowCDKModal(false)}
              className="absolute top-5 right-5 font-black text-xl z-10 transition-colors"
              style={{ color: 'rgba(250,250,252,0.3)' }}
            >
              ✕
            </button>

            {/* 左：扫码加 V（仅微信登录启用时显示）*/}
            {_enableWechat && (
              <div
                className="md:w-[45%] p-10 flex flex-col items-center justify-center cursor-pointer"
                style={{ borderRight: '1px solid rgba(255,255,255,0.06)' }}
                onClick={() => trackEvent('view_wechat_qr', { source: 'paywall_left_panel' })}
              >
                <img
                  src="/images/wechat-qr.jpg"
                  alt="主理人微信二维码"
                  className="w-44 h-44 rounded-2xl object-cover mb-6 transition-all hover:scale-105"
                  style={{ border: '1px solid rgba(255,255,255,0.10)' }}
                />
                <h4 className="text-lg font-black mb-1" style={{ color: '#ffffff' }}>添加主理人微信</h4>
                <p className="text-xs text-center leading-relaxed" style={{ color: 'rgba(250,250,252,0.4)' }}>
                  扫描二维码获取专享权限
                  <br />或单场研报兑换卡密
                </p>
              </div>
            )}

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
                      backgroundColor: message.type === 'success' ? 'rgba(186,255,0,0.08)' : 'rgba(255,61,84,0.08)',
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
                  style={{ backgroundColor: LIME, color: '#050610' }}
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
