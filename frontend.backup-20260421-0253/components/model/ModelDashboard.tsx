'use client';
import React from 'react';
import useSWR from 'swr';
import { useSession } from 'next-auth/react';
import Link from 'next/link';
import { Lock, Cpu } from 'lucide-react';
import { ModelHealthData } from './types';
import EquityHero from './EquityHero';
import KpiGrid from './KpiGrid';
import RollingAccuracyChart from './RollingAccuracyChart';
import CalibrationPlot from './CalibrationPlot';
import RecentPicksTicker from './RecentPicksTicker';
import TrainingSnapshotPanel from './TrainingSnapshotPanel';
import MethodologyAccordion from './MethodologyAccordion';

// ── Auth-aware fetcher ────────────────────────────────────────────────────

function makeModelFetcher(token: string | null) {
  return async (url: string): Promise<ModelHealthData> => {
    const headers: HeadersInit = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(url, { headers, cache: 'no-store' });
    if (!res.ok) throw new Error(`${res.status}`);
    return res.json();
  };
}

// ── Login gate (GUEST view) ───────────────────────────────────────────────

function ModelLoginGate() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center gap-6">
      <div className="relative">
        <div className="absolute inset-0 bg-primary-neon/10 blur-2xl rounded-full scale-150" />
        <div className="relative glass-panel rounded-3xl p-6 border border-white/10">
          <Lock size={32} className="text-primary-neon/60 mx-auto mb-3" />
          <Cpu size={20} className="text-primary-neon/30 mx-auto" />
        </div>
      </div>
      <div>
        <p className="font-display italic font-black text-lg tracking-tight text-white mb-1">
          模型性能审计 · 登录可见
        </p>
        <p className="text-xs text-white/30 font-body leading-relaxed max-w-[220px] mx-auto">
          注册账号即可访问完整量化回测数据、准确率审计与净值曲线
        </p>
      </div>
      <div className="flex gap-3">
        <Link
          href="/login"
          className="px-6 py-2.5 rounded-full bg-primary-neon/15 border border-primary-neon/30 text-primary-neon text-xs font-black tracking-widest hover:bg-primary-neon/25 transition-all"
        >
          登录
        </Link>
        <Link
          href="/login?tab=register"
          className="px-6 py-2.5 rounded-full bg-white/5 border border-white/10 text-white/60 text-xs font-black tracking-widest hover:bg-white/10 transition-all"
        >
          免费注册
        </Link>
      </div>
    </div>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────────

function ModelSkeleton() {
  return (
    <div className="flex flex-col gap-4 animate-pulse">
      <div className="h-64 rounded-3xl bg-white/[0.03] border border-white/5" />
      <div className="grid grid-cols-2 gap-3">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="h-20 rounded-2xl bg-white/[0.03] border border-white/5" />
        ))}
      </div>
      <div className="h-44 rounded-2xl bg-white/[0.03] border border-white/5" />
      <div className="h-52 rounded-2xl bg-white/[0.03] border border-white/5" />
      <div className="h-24 rounded-2xl bg-white/[0.03] border border-white/5" />
    </div>
  );
}

// ── Main dashboard ────────────────────────────────────────────────────────

export default function ModelDashboard() {
  const { data: session } = useSession();
  const isLoggedIn = !!session?.user;
  const apiToken   = (session?.user as any)?.apiToken as string | undefined;

  const { data, error, isLoading } = useSWR<ModelHealthData>(
    isLoggedIn ? '/api/v1/model/health' : null,
    makeModelFetcher(apiToken ?? null),
    {
      refreshInterval:       60_000,
      revalidateOnFocus:     false,
      shouldRetryOnError:    false,
    }
  );

  if (!isLoggedIn) return <ModelLoginGate />;
  if (isLoading)   return <ModelSkeleton />;

  if (error || !data) {
    return (
      <div className="text-center py-16 text-white/30 text-xs font-mono">
        数据加载失败，请稍后重试
      </div>
    );
  }

  const updatedAt = data.equity?.updated_at ?? '';
  const fixedBlock = data.equity?.fixed;

  return (
    <div className="flex flex-col gap-4 animate-in fade-in slide-in-from-bottom-5 duration-500">
      {/* Status pill */}
      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/5 self-start">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
        <span className="text-[9px] font-black tracking-[0.2em] uppercase text-white/40">
          模型健康 · 已更新{updatedAt ? ' ' + new Date(updatedAt).toLocaleDateString('zh-CN') : ''}
        </span>
      </div>

      {/* Main equity curve */}
      <EquityHero equity={data.equity} updatedAt={updatedAt} />

      {/* KPI grid */}
      <KpiGrid rolling={data.rolling} equity={fixedBlock} training={data.latest_training} />

      {/* Rolling accuracy */}
      <RollingAccuracyChart rolling={data.rolling} />

      {/* Calibration plot */}
      <CalibrationPlot data={data.calibration} />

      {/* Recent picks ticker */}
      <RecentPicksTicker picks={data.recent_picks} />

      {/* Training snapshot + methodology */}
      <TrainingSnapshotPanel data={data.latest_training} />
      <MethodologyAccordion />
    </div>
  );
}
