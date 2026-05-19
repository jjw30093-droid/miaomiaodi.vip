'use client';

import { useEffect, useState, Suspense } from 'react';
import { useSession } from 'next-auth/react';
import { useSearchParams, useRouter } from 'next/navigation';
import Navbar from '@/components/Navbar';
import ProfilePanel from '@/components/center/ProfilePanel';
import VipPanel from '@/components/center/VipPanel';
import DevicesPanel from '@/components/center/DevicesPanel';
import PreferencesPanel from '@/components/center/PreferencesPanel';
import { apiClient } from '@/lib/apiClient';

type Tab = 'profile' | 'vip' | 'devices' | 'prefs';

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'profile', label: '个人信息', icon: '👤' },
  { id: 'vip',     label: 'VIP',      icon: '⭐' },
  { id: 'devices', label: '设备',     icon: '📱' },
  { id: 'prefs',   label: '偏好',     icon: '⚙️' },
];

function CenterContent() {
  const { data: session, status } = useSession();
  const searchParams = useSearchParams();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>((searchParams.get('tab') as Tab) || 'profile');
  const [profile, setProfile] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const apiToken = (session?.user as any)?.apiToken as string | undefined;

  useEffect(() => {
    if (status === 'unauthenticated') {
      router.push('/login?callbackUrl=/center');
    }
  }, [status, router]);

  useEffect(() => {
    if (!apiToken) return;
    apiClient.get<any>('/user/me', { token: apiToken })
      .then(setProfile)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [apiToken]);

  if (status === 'loading' || loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-sm animate-pulse" style={{ color: 'rgba(250,250,252,0.3)' }}>加载中...</div>
      </div>
    );
  }

  if (!session) return null;

  return (
    <div
      className="min-h-screen"
      style={{ background: '#0D0F14' }}
    >
      <Navbar />

      <div className="pt-16 pb-24 px-4 max-w-lg mx-auto">
        {/* Header */}
        <div className="py-6 text-center">
          <h1 className="text-2xl font-black text-white">个人中心</h1>
          <p className="text-xs mt-1" style={{ color: 'rgba(250,250,252,0.35)' }}>
            {(session.user as any)?.name || profile?.nickname || '足球探索者'}
          </p>
        </div>

        {/* Tab bar */}
        <div
          className="flex gap-1 p-1 rounded-2xl mb-6"
          style={{ background: '#12161b', border: '1px solid rgba(255,255,255,0.07)' }}
        >
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => { setTab(t.id); router.replace(`/center?tab=${t.id}`, { scroll: false }); }}
              className="flex-1 py-2.5 rounded-xl text-xs font-bold transition-all flex flex-col items-center gap-0.5"
              style={{
                background: tab === t.id ? 'rgba(191,165,93,0.15)' : 'transparent',
                color: tab === t.id ? '#BFA55D' : 'rgba(250,250,252,0.4)',
                border: tab === t.id ? '1px solid rgba(191,165,93,0.3)' : '1px solid transparent',
              }}
            >
              <span>{t.icon}</span>
              <span>{t.label}</span>
            </button>
          ))}
        </div>

        {/* Panel content */}
        <div>
          {tab === 'profile' && <ProfilePanel profile={profile} />}
          {tab === 'vip'     && <VipPanel     profile={profile} />}
          {tab === 'devices' && <DevicesPanel />}
          {tab === 'prefs'   && (
            <PreferencesPanel
              initialPrefs={profile?.preferences || { theme: 'dark', notify_lineup: true, notify_postmatch: false }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

export default function CenterPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-sm animate-pulse" style={{ color: 'rgba(250,250,252,0.3)' }}>加载中...</div>
      </div>
    }>
      <CenterContent />
    </Suspense>
  );
}
