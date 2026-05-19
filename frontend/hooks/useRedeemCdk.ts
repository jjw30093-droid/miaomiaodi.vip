'use client';

import { useState } from 'react';
import { useSession, signIn } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { apiClient } from '@/lib/apiClient';

interface RedeemState {
  loading: boolean;
  message: { type: 'success' | 'error' | ''; text: string };
}

export function useRedeemCdk() {
  const { data: session } = useSession();
  const router = useRouter();
  const [state, setState] = useState<RedeemState>({
    loading: false,
    message: { type: '', text: '' },
  });

  const redeem = async (code: string) => {
    if (!code.trim()) return;

    const apiToken = (session?.user as any)?.apiToken as string | undefined;
    if (!apiToken) {
      setState({ loading: false, message: { type: 'error', text: '卡密兑换需要微信扫码登录。请先退出当前账号，使用微信扫码重新登录后再兑换。' } });
      return;
    }

    setState({ loading: true, message: { type: '', text: '' } });
    try {
      const res = await apiClient.post<any>('/cdk/redeem', { code }, { token: apiToken });
      setState({ loading: false, message: { type: 'success', text: res.message || '🎉 VIP 已激活！正在刷新权限...' } });

      if (res.token) {
        await signIn('wechat', { api_token: res.token, redirect: false });
      }
      setTimeout(() => { router.refresh(); }, 1200);
    } catch (err: any) {
      setState({ loading: false, message: { type: 'error', text: err.message || '卡密无效或已被使用' } });
    }
  };

  const clearMessage = () => setState(s => ({ ...s, message: { type: '', text: '' } }));

  return { ...state, redeem, clearMessage };
}
