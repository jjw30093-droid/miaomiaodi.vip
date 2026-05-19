'use client';
/**
 * useMatchPayload.ts
 * SWR 数据获取层：从 /api/v1/sync/match_payload/{match_id} 拉取
 * 图表复合 Payload，统一处理 JSON.parse 与 Loading/Error 状态。
 *
 * API 约定：
 *   npxg_trend   → JSON 字符串，结构: { home_team, away_team }
 *   shot_map_data → JSON 字符串，结构: { home_team, away_team }
 *
 * 各队数据键：
 *   overall    — 近5场所有赛事
 *   home_only  — 主队的主场近5场
 *   away_only  — 客队的客场近5场
 */

import useSWR from 'swr';

// ── 类型定义 ─────────────────────────────────

export interface NpxgEntry {
  opponent:   string;
  npxg_diff:  number;
}

export interface NpxgTeamData {
  overall:        NpxgEntry[];
  home_only?:     NpxgEntry[];   // 主队同主客场
  away_only?:     NpxgEntry[];   // 客队同主客场
  venue_specific?: NpxgEntry[]; // 通用别名兼容
}

export interface NpxgTrend {
  home_team: NpxgTeamData;
  away_team: NpxgTeamData;
}

export interface ShotEntry {
  x:        number;   // Opta 坐标 0-105
  y:        number;   // Opta 坐标 0-68
  xg:       number;   // 预期进球值
  outcome:  string;   // 'Goal' | 'Saved' | 'Off Target' | 'Blocked'
  player?:  string;
}

export interface ShotTeamData {
  overall:        ShotEntry[];
  home_only?:     ShotEntry[];
  away_only?:     ShotEntry[];
  venue_specific?: ShotEntry[];
}

export interface ShotMapData {
  home_team: ShotTeamData;
  away_team: ShotTeamData;
}

export interface MatchPayloadResponse {
  match_id:        string;
  report_markdown: string;
  npxg_trend:      NpxgTrend;
  shot_map_data:   ShotMapData;
  updated_at:      string;
}

// ── 工具函数 ─────────────────────────────────

/** 透明地处理 string / object 两种情况，防御性解析 */
function parseIfString<T>(value: T | string | null | undefined, fallback: T): T {
  if (value == null) return fallback;
  if (typeof value === 'string') {
    try { return JSON.parse(value) as T; }
    catch { return fallback; }
  }
  return value as T;
}

const EMPTY_TREND: NpxgTrend = {
  home_team: { overall: [] },
  away_team: { overall: [] },
};

const EMPTY_SHOT: ShotMapData = {
  home_team: { overall: [] },
  away_team: { overall: [] },
};

/** 获取特定视图的队伍数据（总况 or 同主客场） */
export function getVenueData<T>(
  teamData: { overall: T[]; home_only?: T[]; away_only?: T[]; venue_specific?: T[] } | undefined,
  venue: 'home' | 'away',
  view: 'overall' | 'venue_specific',
): T[] {
  if (!teamData) return [];
  if (view === 'overall') return teamData.overall ?? [];
  // venue_specific: 优先 home_only/away_only，其次通用 venue_specific 键
  if (venue === 'home') return teamData.home_only ?? teamData.venue_specific ?? teamData.overall ?? [];
  return teamData.away_only ?? teamData.venue_specific ?? teamData.overall ?? [];
}

// ── SWR Fetcher ───────────────────────────────

const fetcher = async (url: string): Promise<MatchPayloadResponse> => {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status}`);
    (err as any).status = res.status;
    throw err;
  }
  const raw = await res.json();
  // 统一 parse — API 可能返回字符串或对象
  return {
    ...raw,
    npxg_trend:    parseIfString<NpxgTrend>(raw.npxg_trend,    EMPTY_TREND),
    shot_map_data: parseIfString<ShotMapData>(raw.shot_map_data, EMPTY_SHOT),
  };
};

// ── Hook ────────────────────────────────────

export function useMatchPayload(matchId: string | null | undefined) {
  const key = matchId ? `/api/v1/sync/match_payload/${matchId}` : null;

  const { data, error, isLoading } = useSWR<MatchPayloadResponse>(key, fetcher, {
    revalidateOnFocus:    false,
    revalidateOnReconnect: false,
    dedupingInterval:     60_000,   // 1 分钟内不重复请求
    shouldRetryOnError:   false,    // 404 就是没有，不重试
  });

  const hasData = !!data && (
    (data.npxg_trend?.home_team?.overall?.length ?? 0) > 0 ||
    (data.shot_map_data?.home_team?.overall?.length ?? 0) > 0
  );

  return {
    payload:   data ?? null,
    isLoading,
    isError:   !!error,
    errorStatus: (error as any)?.status as number | undefined,
    hasData,
  };
}
