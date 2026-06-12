'use client';

import React, { useEffect, useState } from 'react';
import { useSession } from 'next-auth/react';
import Link from 'next/link';
import Image from 'next/image';
import { usePathname, useSearchParams } from 'next/navigation';
import ThemeToggleButton from '@/components/ThemeToggleButton';
import { useTheme } from '@/components/ThemeProvider';
import { fetchSnapshot } from '@/lib/modelHealth/fetchSnapshot';
import type { ModelSnapshotV2 } from '@/lib/modelHealth/types';
import { MOCK_SNAPSHOT } from '@/lib/modelHealth/mockSnapshot';
import SinglePickHero from '@/components/model/SinglePickHero/SinglePickHero';
import { KpiGridSnapshot } from '@/components/model/KpiGrid';
import RecentSinglePicksTable from '@/components/model/RecentSinglePicksTable/RecentSinglePicksTable';
import ModelMetaFooter from '@/components/model/ModelMetaFooter/ModelMetaFooter';
import { Activity, Cpu, Archive, User } from 'lucide-react';

// 图标用 lucide SVG，不依赖 Google Fonts（国内加载不到字体会裸显英文连字名）
const NAV_ITEMS = [
  { href: '/',                   Icon: Activity, label: '赛事' },
  { href: '/model',              Icon: Cpu,      label: '模型' },
  { href: '/archive',            Icon: Archive,  label: '归档' },
  { href: '/center?tab=profile', Icon: User,     label: '我的' },
];

function Skeleton() {
  return (
    <div
      className="h-32 rounded-2xl animate-pulse border"
      style={{ background: 'var(--v2-bg-muted)', borderColor: 'var(--v2-border)' }}
    />
  );
}

export default function ModelPageV2() {
  const { data: session, status } = useSession();
  const token = (session?.user as any)?.apiToken as string | undefined;
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const isMock = searchParams?.get('mock') === '1';
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  // 主题感知配色（替代未定义的 v2 token）
  const NAV_ACTIVE_BG    = isDark ? '#10B981' : '#0F766E';   // 浅色用深绿，深色用亮绿
  const NAV_ACTIVE_TEXT  = '#FFFFFF';
  const NAV_INACTIVE_TEXT = isDark ? '#94A3B8' : '#475569';
  const PRIMARY_BTN_BG   = isDark ? '#10B981' : '#0F766E';
  const PAGE_BG          = isDark ? '#0B1220' : '#F8FAFC';
  const PAGE_TEXT        = isDark ? '#F1F5F9' : '#0F172A';
  const HEADER_BG        = isDark ? 'rgba(15, 23, 42, 0.85)' : 'rgba(255, 255, 255, 0.85)';
  const NAV_BG           = isDark ? 'rgba(15, 23, 42, 0.95)' : 'rgba(255, 255, 255, 0.95)';
  const BORDER           = isDark ? '#334155' : '#E2E8F0';

  const [snap, setSnap] = useState<ModelSnapshotV2 | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    console.info('[model_page_v2_view]', { ts: new Date().toISOString() });
  }, []);

  useEffect(() => {
    if (isMock) {
      console.info('[model_page_v2_mock] using hardcoded snapshot');
      setSnap(MOCK_SNAPSHOT);
      setLoading(false);
      return;
    }
    if (status === 'loading') return;
    if (!token) { setLoading(false); return; }
    fetchSnapshot(token)
      .then(data => { setSnap(data); setLoading(false); })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err);
        console.info('[model_page_v2_error]', { msg, degraded: true, ts: new Date().toISOString() });
        setError(true);
        setLoading(false);
      });
  }, [token, status, isMock]);

  return (
    <div
      className="min-h-screen font-sans pb-32"
      style={{ background: PAGE_BG, color: PAGE_TEXT }}
    >
      {/* Header */}
      <header
        className="fixed top-0 inset-x-0 z-50 backdrop-blur-xl border-b"
        style={{ background: HEADER_BG, borderColor: BORDER }}
      >
        <div className="max-w-md mx-auto flex justify-between items-center px-4 h-14">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full overflow-hidden flex-shrink-0">
              <Image src="/logo_meow.jpg" alt="Avatar" width={36} height={36} className="w-full h-full object-cover" />
            </div>
            <span
              className="text-lg font-extrabold tracking-tight"
              style={{ color: PAGE_TEXT, fontFamily: "'Plus Jakarta Sans', sans-serif" }}
            >
              模型业绩
            </span>
          </div>
          <ThemeToggleButton />
        </div>
      </header>

      <main className="relative pt-20 px-4 max-w-md mx-auto flex flex-col gap-4">
        {/* Mock mode banner */}
        {isMock && (
          <div
            className="px-4 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider border"
            style={{
              background: 'color-mix(in srgb, var(--v2-accent-warning) 15%, transparent)',
              borderColor: 'color-mix(in srgb, var(--v2-accent-warning) 40%, transparent)',
              color: 'var(--v2-accent-warning)',
            }}
          >
            🧪 MOCK 模式 · 假数据仅用于调试 UI · 上线前移除 ?mock=1
          </div>
        )}

        {/* Degraded / error banner */}
        {(error || snap?.degraded) && (
          <div
            className="px-4 py-2.5 rounded-xl text-sm font-semibold border"
            style={{
              background: 'color-mix(in srgb, var(--v2-accent-warning) 10%, transparent)',
              borderColor: 'color-mix(in srgb, var(--v2-accent-warning) 30%, transparent)',
              color: 'var(--v2-accent-warning)',
            }}
          >
            {error ? '⚠ 快照恢复中，请稍候刷新' : '⚠ 数据暂用实时聚合（快照恢复中）'}
          </div>
        )}

        {/* No token / not logged in */}
        {!loading && !token && !isMock && (
          <div
            className="rounded-2xl p-8 text-center border"
            style={{ background: 'var(--v2-bg-card)', borderColor: 'var(--v2-border)' }}
          >
            <p className="text-base font-semibold mb-3" style={{ color: 'var(--v2-text-secondary)' }}>
              登录后查看模型数据
            </p>
            <Link
              href="/login"
              className="inline-block px-5 py-2 rounded-full text-sm font-bold"
              style={{ background: PRIMARY_BTN_BG, color: '#fff' }}
            >
              前往登录
            </Link>
          </div>
        )}

        {/* 6 sections */}
        {(token || isMock) && (
          <>
            {snap ? <SinglePickHero snap={snap} /> : <Skeleton />}
            {snap ? <KpiGridSnapshot snap={snap} /> : <Skeleton />}
            {snap ? <RecentSinglePicksTable picks={snap.recent_picks ?? []} /> : <Skeleton />}
            {snap && <ModelMetaFooter meta={snap.training_meta} drift={snap.drift} />}
          </>
        )}
      </main>

      {/* Bottom Nav */}
      <nav
        className="fixed bottom-0 inset-x-0 z-50 backdrop-blur-xl border-t pt-2 pb-6"
        style={{ background: NAV_BG, borderColor: BORDER }}
      >
        <div className="max-w-md mx-auto flex justify-around items-center px-4">
          {NAV_ITEMS.map(item => {
            const isActive = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href.split('?')[0]);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex flex-col items-center justify-center transition-all active:scale-95 duration-150 min-h-[44px] ${
                  isActive ? 'rounded-full px-5 py-1.5' : 'p-2'
                }`}
                style={
                  isActive
                    ? { background: NAV_ACTIVE_BG, color: NAV_ACTIVE_TEXT }
                    : { color: NAV_INACTIVE_TEXT }
                }
              >
                <item.Icon size={22} className="mb-0.5" />
                <span className="text-xs font-bold leading-none">{item.label}</span>
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
