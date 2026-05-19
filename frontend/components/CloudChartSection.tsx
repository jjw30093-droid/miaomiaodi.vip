'use client';

import React from 'react';
import dynamic from 'next/dynamic';
import { useMatchPayload } from '@/hooks/useMatchPayload';

const NpxgTrendChart = dynamic(() => import('./NpxgTrendChart'), { ssr: false });
const ShotMapScatter = dynamic(() => import('./ShotMapScatter'), { ssr: false });

interface Props {
  matchId: string;
  homeTeamName?: string;
  awayTeamName?: string;
}

/**
 * 喵弟量化实验室 :: 云端图表同步区 (Client Boundary)
 * 职责：
 * 1. 负责通过 SWR 发起异步请求。
 * 2. 处理 Loading 骨架屏与 Error 静默。
 * 3. 协调云端推送的趋势图与散点图渲染。
 */
export default function CloudChartSection({ matchId, homeTeamName, awayTeamName }: Props) {
  // 发起 SWR 请求
  const { payload, isLoading, hasData } = useMatchPayload(matchId);

  // 1. 加载中状态：显示酷炫的骨架屏
  if (isLoading) {
    return (
      <div className="w-full flex flex-col gap-12 animate-pulse">
        <div className="w-full h-80 bg-white/5 rounded-[2.5rem] border border-white/5" />
        <div className="w-full h-[500px] bg-white/5 rounded-[2.5rem] border border-white/5" />
      </div>
    );
  }

  // 2. 如果无数据或 404：该区域完全不渲染（静默不干扰原始报文）
  if (!hasData || !payload) {
    return null;
  }

  // 3. 数据就绪：渲染实时云端图表
  // 兼容新旧两种格式：新格式用 matches[]，旧格式用 overall[]
  const showTrend = ((payload.npxg_trend?.home_team?.overall?.length ?? 0) > 0) ||
                   ((payload.npxg_trend?.away_team?.overall?.length ?? 0) > 0);

  // 新格式 shot_map_data 使用 matches[] 而非 overall[]，此时由 InteractiveShotMap 负责渲染，这里跳过
  const showShots = ((payload.shot_map_data?.home_team?.overall?.length ?? 0) > 0) ||
                   ((payload.shot_map_data?.away_team?.overall?.length ?? 0) > 0);

  return (
    <div className="w-full flex flex-col gap-16 mt-12 mb-24 animate-fade-in">
      {/* 视觉分割线 */}
      <div className="flex items-center gap-6 opacity-20">
        <div className="h-px flex-1 bg-gradient-to-r from-transparent via-primary-container to-transparent" />
        <span className="text-xs font-headline font-black italic tracking-[0.5em] text-primary-container uppercase whitespace-nowrap">Cloud Sync Data stream v2.0</span>
        <div className="h-px flex-1 bg-gradient-to-r from-transparent via-primary-container to-transparent" />
      </div>

      {/* 趋势图 */}
      {showTrend && (
        <NpxgTrendChart
          npxgData={payload.npxg_trend}
          homeTeamName={homeTeamName}
          awayTeamName={awayTeamName}
        />
      )}

      {/* 散点图 */}
      {showShots && (
        <ShotMapScatter
          shotData={payload.shot_map_data}
          homeTeamName={homeTeamName}
          awayTeamName={awayTeamName}
        />
      )}

      {/* 云端标签装饰 */}
      <div className="self-center flex items-center gap-4 px-6 py-2 rounded-full bg-primary-container/10 border border-primary-container/20">
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary-container opacity-75"></span>
          <span className="relative inline-flex rounded-full h-2 w-2 bg-primary-container"></span>
        </span>
        <span className="text-xs font-headline font-black italic tracking-[0.2em] text-primary-container uppercase">
          Synced with Quant-Lab Mainframe
        </span>
      </div>
    </div>
  );
}
