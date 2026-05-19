'use client';

import { useEffect, useState, Suspense } from 'react';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { ChevronLeft } from 'lucide-react';
import Image from 'next/image';
import { useTheme } from '@/components/ThemeProvider';
import ThemeToggleButton from '@/components/ThemeToggleButton';
import BottomNav from '@/components/BottomNav';
import HeroVipCard from '@/components/center/HeroVipCard';
import AccountInfoCard from '@/components/center/AccountInfoCard';
import RedeemCdkRow from '@/components/center/RedeemCdkRow';
import DevicesSection from '@/components/center/DevicesSection';
import PreferencesSection from '@/components/center/PreferencesSection';
import LogoutButton from '@/components/center/LogoutButton';
import { apiClient } from '@/lib/apiClient';

function calcRegisteredDays(createdAt: string | null | undefined): number {
  if (!createdAt) return 0;
  return Math.floor((Date.now() - new Date(createdAt).getTime()) / 86400000);
}

function calcVipDaysLeft(expiresAt: string | null | undefined): number {
  if (!expiresAt) return 0;
  const diff = new Date(expiresAt).getTime() - Date.now();
  return diff > 0 ? Math.floor(diff / 86400000) : 0;
}

interface SectionCardProps {
  title: string;
  isDark: boolean;
  children: React.ReactNode;
}

function SectionCard({ title, isDark, children }: SectionCardProps) {
  return (
    <div className="rounded-3xl overflow-hidden"
      style={isDark
        ? { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', backdropFilter: 'blur(24px)' }
        : { background: '#fff', boxShadow: '0 1px 4px rgba(25,28,29,0.08)' }
      }>
      <div className="px-5 py-4 border-b"
        style={{ borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(25,28,29,0.08)' }}>
        <h2 className="text-[17px] font-black italic tracking-tight"
          style={{ color: isDark ? '#fff' : '#191c1d', fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
          {title}
        </h2>
      </div>
      <div className="px-5 py-4">
        {children}
      </div>
    </div>
  );
}

function MenuRow({ label, right, onClick, isDark, children, noBorder }: {
  label: string; right?: React.ReactNode; onClick?: () => void;
  isDark: boolean; children?: React.ReactNode; noBorder?: boolean;
}) {
  return (
    <div className={noBorder ? '' : 'border-b'} style={{ borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(25,28,29,0.08)' }}>
      <div
        className={`flex items-center justify-between py-3.5 ${onClick ? 'cursor-pointer active:opacity-70 transition-opacity' : ''}`}
        onClick={onClick}
      >
        <span className="text-[15px] font-bold" style={{ color: isDark ? '#fff' : '#191c1d' }}>{label}</span>
        <span className="text-[13px] font-bold" style={{ color: isDark ? 'rgba(255,255,255,0.35)' : '#5b3f43' }}>
          {right ?? '›'}
        </span>
      </div>
      {children && <div className="pb-4">{children}</div>}
    </div>
  );
}

function CenterContent() {
  const { data: session, status } = useSession();
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const router = useRouter();
  const [profile, setProfile] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const apiToken = (session?.user as any)?.apiToken as string | undefined;

  useEffect(() => {
    if (status === 'unauthenticated') router.push('/login?callbackUrl=/center');
  }, [status, router]);

  useEffect(() => {
    if (status === 'loading') return;
    if (!apiToken) { setLoading(false); return; }
    apiClient.get<any>('/user/me', { token: apiToken })
      .then(data => {
        console.log('[center] /user/me ok:', data?.nickname, data?.role);
        setProfile(data);
      })
      .catch(err => {
        console.warn('[center] /user/me failed:', err?.message);
        // fallback: synthesize from session so name/role still display
        setProfile({
          nickname:      (session?.user as any)?.name      || '',
          avatar_url:    (session?.user as any)?.avatarUrl || '',
          role:          (session?.user as any)?.role      || 'user',
          vip_expires_at:(session?.user as any)?.vipExpiresAt || null,
        });
      })
      .finally(() => setLoading(false));
  }, [apiToken, status, session]);

  if (status === 'loading' || loading) {
    return (
      <div className="flex items-center justify-center min-h-screen"
        style={{ background: isDark ? '#06080C' : 'var(--color-background)' }}>
        <p className="text-[15px] font-bold animate-pulse"
          style={{ color: isDark ? 'rgba(255,255,255,0.45)' : '#5b3f43' }}>加载中...</p>
      </div>
    );
  }

  if (!session) return null;

  const registeredDays = calcRegisteredDays(profile?.created_at);
  const vipDaysLeft = calcVipDaysLeft(profile?.vip_expires_at);
  const onlineDevices = 1; // from sessions API not loaded here, default 1
  const initialPrefs = profile?.preferences || { theme: 'dark', notify_lineup: true, notify_postmatch: false };

  const statCards = [
    { label: '注册天数', value: registeredDays, unit: '天', color: isDark ? '#00F0FF' : '#005faf' },
    { label: '在线设备', value: onlineDevices, unit: '台', color: isDark ? '#E91E63' : '#b7004d' },
  ];

  return (
    <div suppressHydrationWarning
      className={`min-h-screen pb-36 overflow-x-hidden ${isDark ? 'bg-[#06080C]' : ''}`}
      style={isDark ? {} : { background: 'var(--color-background)' }}>

      {/* Sticky Header */}
      <header suppressHydrationWarning
        className="fixed top-0 w-full z-50 flex justify-between items-center px-5 py-3"
        style={isDark
          ? { background: 'rgba(6,8,12,0.9)', backdropFilter: 'blur(24px)', borderBottom: '1px solid rgba(255,255,255,0.05)' }
          : { background: 'var(--color-background)', borderBottom: '1px solid rgba(0,0,0,0.08)' }
        }
      >
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.back()}
            className="w-8 h-8 flex items-center justify-center rounded-full transition-all active:scale-90 flex-shrink-0"
            style={isDark
              ? { background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.1)' }
              : { background: 'rgba(25,28,29,0.06)', border: '1px solid rgba(25,28,29,0.1)' }
            }
            aria-label="返回上一页"
          >
            <ChevronLeft size={18} style={{ color: isDark ? '#fff' : '#191c1d' }} />
          </button>
          <Image
            src="/logo_meow.jpg"
            alt="喵弟数据研究室 Logo"
            width={36}
            height={36}
            className="rounded-full object-contain flex-shrink-0"
            priority
          />
          <div className="flex flex-col leading-none">
            <h1 className="font-black text-[15px] tracking-tight"
              style={{ color: isDark ? '#fff' : '#191c1d', fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
              喵弟数据研究室
            </h1>
            <p className="text-[13px] font-bold tracking-widest"
              style={{ color: isDark ? 'rgba(255,255,255,0.4)' : '#5b3f43' }}>
              miaomiaodi.cc
            </p>
          </div>
        </div>
        <ThemeToggleButton />
      </header>

      {/* Page content */}
      <div className="max-w-md mx-auto px-4 pt-20 flex flex-col gap-4">

        {/* Hero VIP Card */}
        <HeroVipCard profile={profile} isDark={isDark} apiToken={apiToken} />

        {/* Quick Stats 3 cols */}
        <div className="grid grid-cols-3 gap-3">
          {statCards.map(card => (
            <div key={card.label} className="rounded-2xl p-4 flex flex-col gap-1"
              style={isDark
                ? { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }
                : { background: '#fff', boxShadow: '0 1px 4px rgba(25,28,29,0.08)', borderLeft: `3px solid ${card.color}` }
              }>
              <p className="text-[13px] font-bold uppercase tracking-wider"
                style={{ color: isDark ? 'rgba(255,255,255,0.4)' : '#5b3f43' }}>
                {card.label}
              </p>
              <p className="text-[22px] font-black leading-tight"
                style={{ color: card.color, fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                {card.value}
              </p>
              <p className="text-[13px] font-bold" style={{ color: isDark ? 'rgba(255,255,255,0.35)' : '#5b3f43' }}>
                {card.unit}
              </p>
            </div>
          ))}
        </div>

        {/* 账户信息 */}
        <SectionCard title="账户信息" isDark={isDark}>
          <AccountInfoCard profile={profile} isDark={isDark} />
        </SectionCard>

        {/* 订阅 */}
        <SectionCard title="订阅" isDark={isDark}>
          <div className="flex flex-col gap-1">
            <div className="pb-3 border-b" style={{ borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(25,28,29,0.08)' }}>
              <RedeemCdkRow isDark={isDark} />
            </div>
            <MenuRow label="订阅套餐" isDark={isDark} right={
              <span className="text-[13px] font-bold px-2 py-0.5 rounded-full"
                style={{ background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(25,28,29,0.06)', color: isDark ? 'rgba(255,255,255,0.35)' : '#5b3f43' }}>
                即将上线
              </span>
            } noBorder={true} />
          </div>
        </SectionCard>

        {/* 设备与安全 */}
        <SectionCard title="设备与安全" isDark={isDark}>
          <DevicesSection isDark={isDark} />
        </SectionCard>

        {/* 偏好设置 */}
        <SectionCard title="偏好设置" isDark={isDark}>
          <PreferencesSection initialPrefs={initialPrefs} isDark={isDark} />
        </SectionCard>

        {/* 支持 */}
        <SectionCard title="支持" isDark={isDark}>
          <div className="flex flex-col divide-y" style={{ '--tw-divide-opacity': 1 } as any}>
            <MenuRow label="帮助中心" isDark={isDark} onClick={() => router.push('/help')} />
            <MenuRow label="意见反馈" isDark={isDark}
              right={<span className="text-[13px] font-bold" style={{ color: isDark ? 'rgba(255,255,255,0.35)' : '#5b3f43' }}>邮件 ›</span>}
              onClick={() => window.open('mailto:support@miaomiaodi.cc')} />
            <MenuRow label="关于喵弟" isDark={isDark}
              right={<span className="text-[13px] font-bold font-mono" style={{ color: isDark ? 'rgba(255,255,255,0.35)' : '#5b3f43' }}>v1.0 © 2026</span>}
              noBorder={true} />
          </div>
        </SectionCard>

        {/* Logout */}
        <LogoutButton isDark={isDark} />

        {/* Footer */}
        <p className="text-center text-[13px] font-bold pb-4"
          style={{ color: isDark ? 'rgba(255,255,255,0.2)' : '#5b3f43' }}>
          喵弟数据研究室 · miaomiaodi.cc · v1.0
        </p>
      </div>

      <BottomNav isDark={isDark} />
    </div>
  );
}

export default function CenterPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-[15px] font-bold animate-pulse" style={{ color: 'rgba(255,255,255,0.4)' }}>加载中...</p>
      </div>
    }>
      <CenterContent />
    </Suspense>
  );
}
