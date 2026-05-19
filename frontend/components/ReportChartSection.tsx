"use client";

import dynamic from 'next/dynamic';
import { ShotMapData } from '@/types/report';

// 1. 在客户端组件内部使用 ssr: false，确保 ECharts 仅在浏览器端初始化
const ShotMapChart = dynamic(() => import('@/components/ShotMapChart'), { 
  ssr: false,
  loading: () => (
    <div className="h-[500px] w-full bg-white/5 border border-white/10 rounded-[2.5rem] animate-pulse flex flex-col items-center justify-center gap-4">
      <div className="w-10 h-10 border-2 border-dashed border-cyan-500/30 rounded-full animate-spin" />
      <span className="text-xs font-mono text-cyan-500/50 uppercase tracking-[0.3em]">
        Initializing Spatial Engine...
      </span>
    </div>
  )
});

interface Props {
  shotMapData: ShotMapData;
}

/**
 * 客户端包装组件：解决 Server Component 中无法使用 ssr: false 的架构冲突
 */
export default function ReportChartSection({ shotMapData }: Props) {
  return (
    <div className="w-full">
      <ShotMapChart shotMapData={shotMapData} />
    </div>
  );
}
