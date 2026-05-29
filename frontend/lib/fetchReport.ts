import { ReportData, Shot, CloudReportPayload, MatchTrend, MatchShotData, TeamShotHistory, PostMatchShots } from '@/types/report';
import { unstable_noStore as noStore } from 'next/cache';
import { auth } from '@/lib/auth';
import fs from 'fs';
import path from 'path';

/**
 * 喵弟量化实验室 :: 云端数据适配器 (Cloud Data Adapter)
 * 功能：
 * 1. 跨域获取 AWS 生产环境的静态快照。
 * 2. 对 stringified JSON 进行防御性解析。
 * 3. 映射新老字段 (overall -> last5All, npxg_diff -> npxGD)。
 * 4. 自动将旧格式 shot_map_data (overall/home_only/away_only) 转换为新格式 (matches[])。
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
/**
 * Parse the (post-restructure) Markdown into named H2 sections.
 *  新版（2026-04-28+，AH/OU 导向）：
 *  ## 亚盘分析      → ahAnalysis
 *  ## 进球数分析    → ouAnalysis
 *  ## 综合战力对比  → overallComparison
 *  旧版（WDL 导向，兼容保留）：
 *  ## 战力演化分析  → powerEvolution
 *  ## 阵容影响分析  → lineupImpact
 *  ## 战术博弈分析  → tacticalAnalysis
 *  (## 综合结论 已被后端 strip 进 verdict 卡，不会出现)
 *
 * 旧研报无指定 H2 段时返回空 dict — 调用方应 fallback 渲染原 markdown。
 */
const _MD_SECTION_KEY: Record<string, 'powerEvolution' | 'lineupImpact' | 'tacticalAnalysis' | 'ahAnalysis' | 'ouAnalysis' | 'overallComparison'> = {
  // 新版
  '亚盘分析':     'ahAnalysis',
  '大小球分析':   'ouAnalysis',
  '综合战力对比': 'overallComparison',
  // 旧版兼容
  '战力演化分析': 'powerEvolution',
  '阵容影响分析': 'lineupImpact',
  '战术博弈分析': 'tacticalAnalysis',
};
function parseStructuredMarkdown(md: string | null | undefined): ReportData['markdownSections'] {
  if (!md) return {};
  const out: NonNullable<ReportData['markdownSections']> = {};
  const blocks = md.split(/^## /m).filter(Boolean);
  for (const block of blocks) {
    const nl = block.indexOf('\n');
    if (nl < 0) continue;
    const title = block.slice(0, nl).trim();
    const body = block.slice(nl + 1).trim();
    const key = _MD_SECTION_KEY[title];
    if (key && body) out[key] = body;
  }
  return out;
}

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
    x:         parseFloat(s.x || s.X_Coord || 0),
    y:         parseFloat(s.y || s.Y_Coord || 0),
    xg:        parseFloat(s.xg || s.xG || 0),
    outcome:   s.outcome   || s.Outcome   || '',
    situation: s.situation || s.Situation || '',
    player:    s.player    || s.Player_Name || '',
    minute:    s.minute    || s.Minute     || 0,
    period:    s.period    || s.Period     || '',
  });

  // 4. 空数据判定（修复：第一个条件应读 rawTrend，不是 rawShots）
  const isTrendEmpty =
    (rawTrend.home_team?.overall?.length   || 0) === 0 &&
    (rawTrend.home_team?.home_only?.length || 0) === 0 &&
    (rawTrend.away_team?.overall?.length   || 0) === 0 &&
    (rawTrend.away_team?.away_only?.length || 0) === 0;

  // 4b. 解析新格式 shot_map_data（按场次分组）
  const mapMatchShotData = (raw: any): MatchShotData => ({
    match_id:         raw.match_id   || 0,
    date:             raw.date       || '',
    opponent:         raw.opponent   || '',
    is_home:          !!raw.is_home,
    result:           raw.result     || '',
    total_shots:      raw.total_shots || (raw.shots?.length ?? 0),
    situation_counts: raw.situation_counts || {},
    shots:            (raw.shots || []).map(mapShotItem),
  });

  const mapTeamShotHistory = (raw: any): TeamShotHistory => ({
    team_name: raw.team_name || '',
    matches:   (raw.matches || []).map(mapMatchShotData),
  });

  const isNewShotFormat =
    Array.isArray(rawShots.home_team?.matches) ||
    Array.isArray(rawShots.away_team?.matches);

  const isShotsEmpty = isNewShotFormat
    ? (rawShots.home_team?.matches?.length || 0) === 0 &&
      (rawShots.away_team?.matches?.length || 0) === 0
    : (rawShots.home_team?.overall?.length   || 0) === 0 &&
      (rawShots.home_team?.home_only?.length || 0) === 0 &&
      (rawShots.away_team?.overall?.length   || 0) === 0 &&
      (rawShots.away_team?.away_only?.length || 0) === 0;

  /**
   * 旧格式转新格式：将 overall/home_only/away_only 三个数组合并为两个 synthetic match entry。
   * "综合" = overall（主客场合计）；"主场" / "客场" 分开保留供用户切换。
   * match_id 用负数避免与真实 FotMob ID 冲突。
   */
  const convertOldShotFormat = (raw: any, teamIsHome: boolean): TeamShotHistory => {
    const overall  = (raw?.overall   || []).map(mapShotItem);
    const homeOnly = (raw?.home_only || []).map(mapShotItem);
    const awayOnly = (raw?.away_only || []).map(mapShotItem);
    const matches: MatchShotData[] = [];

    if (overall.length > 0) {
      matches.push({
        match_id:         -1,
        date:             '',
        opponent:         '近5场综合',
        is_home:          teamIsHome,
        result:           '',
        total_shots:      overall.length,
        situation_counts: {},
        shots:            overall,
      });
    }
    if (homeOnly.length > 0 && homeOnly.length !== overall.length) {
      matches.push({
        match_id:         -2,
        date:             '',
        opponent:         '主场场次',
        is_home:          true,
        result:           '',
        total_shots:      homeOnly.length,
        situation_counts: {},
        shots:            homeOnly,
      });
    }
    if (awayOnly.length > 0 && awayOnly.length !== overall.length) {
      matches.push({
        match_id:         -3,
        date:             '',
        opponent:         '客场场次',
        is_home:          false,
        result:           '',
        total_shots:      awayOnly.length,
        situation_counts: {},
        shots:            awayOnly,
      });
    }
    return {
      team_name: raw?.team_name || '',
      matches,
    };
  };

  // 决定最终 shotHistory：新格式直接用，旧格式转换，空则 null
  let shotHistory: ReportData['shotHistory'] = null;
  if (!isShotsEmpty) {
    if (isNewShotFormat) {
      shotHistory = {
        homeTeam: mapTeamShotHistory(rawShots.home_team),
        awayTeam: mapTeamShotHistory(rawShots.away_team),
      };
    } else {
      // 旧格式自动上升为 shotHistory，penetrationData 不再需要
      const converted = {
        homeTeam: convertOldShotFormat(rawShots.home_team, true),
        awayTeam: convertOldShotFormat(rawShots.away_team, false),
      };
      // 仅当至少一支队有 shots 时才设置
      if (converted.homeTeam.matches.length > 0 || converted.awayTeam.matches.length > 0) {
        shotHistory = converted;
      }
    }
  }

  // 5. 组装前端结构
  return {
    matchId:       payload.match_id,
    title:         `QUANT ANALYSIS :: ${payload.home_team} vs ${payload.away_team}`,
    tournamentType: payload.tournament_type === 'wc' ? 'wc' : 'league',
    markdownContent: payload.report_markdown || '',
    createdAt:     new Date().toISOString(),
    homeTeamName:  payload.home_team || 'HOME TEAM',
    awayTeamName:  payload.away_team || 'AWAY TEAM',
    homeProb:      payload.home_prob != null ? Math.round(payload.home_prob) : undefined,
    awayProb:      payload.away_prob != null ? Math.round(payload.away_prob) : undefined,
    drawProb:      payload.draw_prob != null ? Math.round(payload.draw_prob) : undefined,
    matchTime:     payload.match_time || undefined,
    league:        payload.league || undefined,
    inference:     payload.inference || undefined,
    trendData: isTrendEmpty ? null : {
      homeTeam: {
        last5All:      (rawTrend.home_team?.overall  || []).map(mapTrendItem),
        last5HomeAway: (rawTrend.home_team?.home_only || []).map(mapTrendItem),
      },
      awayTeam: {
        last5All:      (rawTrend.away_team?.overall   || []).map(mapTrendItem),
        last5HomeAway: (rawTrend.away_team?.away_only || []).map(mapTrendItem),
      },
    },
    // 新旧格式统一走 shotHistory（旧格式已在上方转换）
    shotHistory,
    // penetrationData 已废弃：全部升级为 shotHistory
    penetrationData: null,
    playerStats:    payload.player_stats    ?? null,
    teamMatchStats: payload.team_match_stats ?? null,
    lineupBrief:    payload.lineup_brief       ?? null,
    lineupImpact:   payload.lineup_impact_data ?? null,
    generatedAt:    payload.updated_at || new Date().toISOString(),
    matchStatus:    payload.match_status   || 'upcoming',
    isGated:        payload.is_gated ?? false,
    lineupStatus:   (payload.lineup_status as ReportData['lineupStatus']) ?? 'predicted',
    lineupConfirmedAt: payload.lineup_confirmed_at ?? null,
    homeIcon: payload.home_icon ?? null,
    awayIcon: payload.away_icon ?? null,
    bestRecentStat: payload.best_recent_stat ? {
      label:         payload.best_recent_stat.label,
      window:        payload.best_recent_stat.window,
      wins:          payload.best_recent_stat.wins,
      total:         payload.best_recent_stat.total,
      hitRate:       payload.best_recent_stat.hit_rate,
      emojiSequence: payload.best_recent_stat.emoji_sequence,
    } : null,
    marketImpliedProb: payload.market_implied_prob ?? null,
    verdictSummary: payload.verdict_summary ? {
      attackRating:  payload.verdict_summary.attack_rating  ?? null,
      defenseRating: payload.verdict_summary.defense_rating ?? null,
      formLabel:     payload.verdict_summary.form_label     ?? null,
      coreLogic:     payload.verdict_summary.core_logic     ?? null,
    } : null,
    keyVariables: payload.key_variables ?? null,
    keyRisk: payload.key_risk ?? null,
    beginnerSummary: payload.beginner_summary ?? null,
    chartInsights: payload.chart_insights ? {
      npxgd:              payload.chart_insights.npxgd,
      shotmap:            payload.chart_insights.shotmap,
      lineupCompare:      payload.chart_insights.lineup_compare,
      injuries:           payload.chart_insights.injuries,
      playerContribution: payload.chart_insights.player_contribution,
    } : null,
    markdownSections: parseStructuredMarkdown(payload.report_markdown),
    ahImplied:   payload.ah_implied    ?? null,
    wcTeamStats: payload.wc_team_stats ?? null,
    postMatchReview: payload.post_match_review ?? null,
    postMatchShots: (() => {
      const raw = payload.post_match_shots;
      if (!raw) return null;
      const mapShot = (s: any): Shot => ({
        x:         parseFloat(s.x || s.X_Coord || 0),
        y:         parseFloat(s.y || s.Y_Coord || 0),
        xg:        parseFloat(s.xg || s.xG || 0),
        outcome:   s.outcome   || s.Outcome   || '',
        situation: s.situation || s.Situation || '',
        player:    s.player    || s.Player_Name || '',
        minute:    s.minute    || s.Minute     || 0,
        period:    s.period    || s.Period     || '',
      });
      return {
        homeTeam: {
          name:  raw.homeTeam?.name || '',
          npxg:  raw.homeTeam?.npxg ?? 0,
          shots: (raw.homeTeam?.shots || []).map(mapShot),
        },
        awayTeam: {
          name:  raw.awayTeam?.name || '',
          npxg:  raw.awayTeam?.npxg ?? 0,
          shots: (raw.awayTeam?.shots || []).map(mapShot),
        },
      } as PostMatchShots;
    })(),
  };
}

/**
 * 远程获取赛事研报 (AWS 公开接口)
 */
export async function getMatchReport(matchId: string): Promise<ReportData | null> {
  noStore();

  // ── Dev fixture bypass ────────────────────────────────────────────────────
  // 当 DEV_FIXTURE_MATCH_ID 与请求 matchId 一致时，直接读本地 JSON，绕过网络和鉴权。
  if (process.env.NODE_ENV === 'development') {
    const fixturePath = path.join(process.cwd(), 'fixtures', `report_${matchId}.json`);
    if (fs.existsSync(fixturePath)) {
      console.log(`>>> [getMatchReport] DEV: Loading fixture from ${fixturePath}`);
      const raw = JSON.parse(fs.readFileSync(fixturePath, 'utf-8'));
      return adaptCloudPayload(raw as CloudReportPayload);
    }
  }
  // ─────────────────────────────────────────────────────────────────────────

  // WC 专用端点（硬隔离：wc_ 前缀走 /wc/ 路径，联赛走原 /sync/ 路径）
  const isWc = matchId.startsWith('wc_');
  const url = isWc
    ? `${AWS_API_BASE}/api/v1/wc/match_payload/${matchId}`
    : `${AWS_API_BASE}/api/v1/sync/match_payload/${matchId}`;

  // 读取 NextAuth session，取出存储的 FastAPI JWT（微信登录后写入）
  // 如果没有 apiToken（普通用户/匿名），FastAPI 按 GUEST 返回受限数据，
  // 付费场研报 null → Next.js 层渲染 PaywallOverlay，行为正确。
  const session = await auth();
  const apiToken = (session?.user as any)?.apiToken as string | undefined;

  console.log(`>>> [getMatchReport] Fetching Cloud Data: ${url} | hasToken=${!!apiToken}`);

  try {
    const res = await fetch(url, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        ...(apiToken ? { 'Authorization': `Bearer ${apiToken}` } : {}),
      },
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
