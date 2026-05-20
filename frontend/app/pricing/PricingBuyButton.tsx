'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useSession } from 'next-auth/react';
import { apiClient } from '@/lib/apiClient';

const LIME = '#baff00';
const RED  = '#ff3d54';

interface PricingBuyButtonProps {
  productId: number;
  productName: string;
  priceYuan: number;
}

export default function PricingBuyButton({ productId, productName, priceYuan }: PricingBuyButtonProps) {
  const router = useRouter();
  const { data: session, status } = useSession();
  const [loading, setLoading] = useState(false);
  const [orderNo, setOrderNo] = useState<string | null>(null);
  const [error, setError] = useState<string>('');

  const handleBuy = async () => {
    if (status === 'loading') return;

    // 未登录 → 跳登录页，登录后回来
    if (!session) {
      router.push('/login?redirect=/pricing');
      return;
    }

    const apiToken = (session.user as any)?.apiToken as string | undefined;
    if (!apiToken) {
      setError('登录态异常，请重新登录');
      return;
    }

    setLoading(true);
    setError('');
    try {
      const res = await apiClient.post<{ order_no: string; amount_yuan: number }>(
        '/orders',
        { product_id: productId },
        { token: apiToken }
      );
      setOrderNo(res.order_no);
    } catch (err: any) {
      const detail: string = err?.message || '购买失败，请稍后重试';
      if (detail.includes('already have a paid order')) {
        setError('您已购买本套餐，请刷新页面');
      } else if (detail.includes('pending order')) {
        setError('已有待支付订单，请联系客服完成支付');
      } else {
        setError(detail);
      }
    } finally {
      setLoading(false);
    }
  };

  if (orderNo) {
    return (
      <div
        className="w-full py-3 px-4 rounded-xl text-sm font-bold text-center"
        style={{
          background: 'rgba(186,255,0,0.08)',
          border: '1px solid rgba(186,255,0,0.2)',
          color: LIME,
        }}
      >
        <div>✅ 订单 {orderNo}</div>
        <div className="text-xs font-normal mt-1" style={{ color: 'rgba(250,250,252,0.6)' }}>
          请联系客服完成支付
        </div>
      </div>
    );
  }

  return (
    <>
      <button
        onClick={handleBuy}
        disabled={loading}
        className="w-full py-3 font-black rounded-xl text-base transition-all active:scale-[0.97] disabled:opacity-50"
        style={{ backgroundColor: LIME, color: '#050610' }}
      >
        {loading ? '处理中...' : `购买 ¥${priceYuan}`}
      </button>
      {error && (
        <div
          className="mt-2 p-2 rounded-lg text-xs font-bold text-center"
          style={{
            background: 'rgba(255,61,84,0.08)',
            border: '1px solid rgba(255,61,84,0.2)',
            color: RED,
          }}
        >
          {error}
        </div>
      )}
    </>
  );
}
