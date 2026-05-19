import { ReportData, Shot, CloudReportPayload, MatchTrend } from '@/types/report';
import { unstable_noStore as noStore } from 'next/cache';

/**
 * 喵弟量化实验室 :: 云端数据适配器 (Cloud Data Adapter)
 * 功能：
 * 1. 跨域获取 AWS 生产环境的静态快照。
 * 2. 对 stringified JSON 进行防御性解析。
 * 3. 映射新老字段 (overall -> last5All, npxg_diff -> npxGD)。
 */

const isServer = typeof window === 'undefined';
const AWS_API_BASE = process.env.NEXT_PUBLIC_AWS_API_URL || 
                     (isServer ? 'http://localhost:8000' : '');

/**
 * 防御性解析器：确保 JSON 损坏时页面不崩溃
 */
function safeParseJSON(jsonStr: string, defaultValue: any) {
  try {
    if (!jsonStr || jsonStr === 'null') return defaultValue;
    if (typeof jsonStr === 'object') return jsonStr; // 已经解析过的情况
    return JSON.parse(jsonStr);
  } catch (e) {
    console.error('>>> [safeParseJSON] Failed to parse:', e);
    return defaultValue;
  }
}

/**
 * 核心适配器：将 AWS 原始 Payload 转换为前端 UI 期望的 ReportData 格式
 */
function adaptCloudPayload(payload: CloudReportPayload): ReportData {
  // 1. 防御性解析趋势图与射门图
  const rawTrend = safeParseJSON(payload.npxg_trend, { home_team: {}, away_team: {} });
  const rawShots = safeParseJSON(payload.shot_map_data, { home_team: {}, away_team: {} });

  // 2. 趋势项字段对齐 (npxg_diff -> npxGD, overall -> last5All)
  const mapTrendItem = (item: any): MatchTrend => ({
    opponent: item.opponent || item.opponent_name || 'Unknown',
    npxGD: parseFloat(item.npxg_diff || item.npxGD || 0),
    isHome: !!item.is_home,
    date: item.date || item.match_date || ''
  });

  // 3. 射门项字段对齐
  const mapShotItem = (s: any): Shot => ({
    x: parseFloat(s.x || s.X_Coord || 0),
    y: parseFloat(s.y || s.Y_Coord || 0),
    xg: parseFloat(s.xg || s.xG || 0),
    outcome: s.outcome || s.Outcome || 'Attempt',
    player: s.player || s.Player_Name || 'Standard Player'
  });

  // 4. 空数据判定逻辑
  const isTrendEmpty = 
    (rawTrend.home_team?.overall?.length || 0) === 0 &&
    (rawTrend.home_team?.home_only?.length || 0) === 0 &&
    (rawTrend.away_team?.overall?.length || 0) === 0 &&
    (rawTrend.away_team?.away_only?.length || 0) === 0;

  const isShotsEmpty = 
    (rawShots.home_team?.overall?.length || 0) === 0 &&
    (rawShots.home_team?.home_only?.length || 0) === 0 &&
    (rawShots.away_team?.overall?.length || 0) === 0 &&
    (rawShots.away_team?.away_only?.length || 0) === 0;

  // 5. 组装前端结构
  return {
    matchId: payload.match_id,
    title: `QUANT ANALYSIS :: ${payload.home_team} vs ${payload.away_team}`,
    markdownContent: payload.report_markdown || '报告内容正在同步中...',
    createdAt: new Date().toISOString(),
    homeTeamName: payload.home_team || "HOME TEAM", 
    awayTeamName: payload.away_team || "AWAY TEAM",
    trendData: isTrendEmpty ? null : {
      homeTeam: {
        last5All: (rawTrend.home_team?.overall || []).map(mapTrendItem),
        last5HomeAway: (rawTrend.home_team?.home_only || []).map(mapTrendItem)
      },
      awayTeam: {
        last5All: (rawTrend.away_team?.overall || []).map(mapTrendItem),
        last5HomeAway: (rawTrend.away_team?.away_only || []).map(mapTrendItem)
      }
    },
    penetrationData: isShotsEmpty ? null : {
      homeTeam: {
        last5All: (rawShots.home_team?.overall || []).map(mapShotItem),
        last5HomeAway: (rawShots.home_team?.home_only || []).map(mapShotItem)
      },
      awayTeam: {
        last5All: (rawShots.away_team?.overall || []).map(mapShotItem),
        last5HomeAway: (rawShots.away_team?.away_only || []).map(mapShotItem)
      }
    },
    generatedAt: payload.updated_at || new Date().toISOString()
  };
}

/**
 * 远程获取赛事研报 (AWS 公开接口)
 */
export async function getMatchReport(matchId: string): Promise<ReportData | null> {
  noStore();
  const url = `${AWS_API_BASE}/api/v1/sync/match_payload/${matchId}`;
  
  console.log(`>>> [getMatchReport] Fetching Cloud Data: ${url}`);
  
  try {
    const res = await fetch(url, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
      // 开启缓存控制或重试逻辑可以在此扩展
      cache: 'no-store'
    });

    if (!res.ok) {
      console.warn(`>>> [getMatchReport] API Error: ${res.status}`);
      return null;
    }

    const payload: CloudReportPayload = await res.json();
    return adaptCloudPayload(payload);

  } catch (error) {
    console.error('>>> [getMatchReport] Critical Fetch Error:', error);
    return null;
  }
}
