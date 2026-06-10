import Link from 'next/link';
import { Suspense } from 'react';
import nextDynamic from 'next/dynamic';
import { auth } from '@/lib/auth';
import { getMatchReport } from '@/lib/fetchReport';
import ReportMarkdown from '@/components/report/ReportMarkdown';
import MarkdownRenderer from '@/components/MarkdownRenderer';
import InteractiveShotMapClient from '@/components/InteractiveShotMapClient';
import PaywallOverlay from '@/components/PaywallOverlay';
import GlassPickBlock from '@/components/report/GlassPickBlock';
import PostMatchCompareCard from '@/components/report/PostMatchCompareCard';
import ReportTabSwitch from '@/components/report/ReportTabSwitch';
import BeginnerView, { type FormResult } from '@/components/report/BeginnerView';
import MarketVsModelCard from '@/components/report/MarketVsModelCard';
import ModelVerdictCard from '@/components/report/ModelVerdictCard';
import SectionNavBar from '@/components/report/SectionNavBar';
import InsightLine from '@/components/report/InsightLine';
import CollapsibleSection from '@/components/common/CollapsibleSection';
import { BackgroundEffects } from '@/components/BackgroundEffects';
import Footer from '@/components/layout/Footer';
// WC-only components（仅在 tournamentType==='wc' 时渲染，联赛路径零影响）
import WcRecentStatsCompare from '@/components/report/WcRecentStatsCompare';
import WcAhInfoCard from '@/components/report/WcAhInfoCard';
import WcModelPredictionsCard from '@/components/report/WcModelPredictionsCard';
import WcProjectedLineupTable from '@/components/report/WcProjectedLineupTable';
import WcRecentFormCard from '@/components/report/WcRecentFormCard';
// WC 游客预览页（无需登录，展示摘要 + 联系管理员）
import ContactAdminPanel from '@/components/ContactAdminPanel';
import {
  ChevronLeft, Lock, BarChart2, Crosshair, TrendingUp, Star, Activity, FileText,
} from 'lucide-react';
import { MatchTimeDisplay } from '@/components/MatchTimeDisplay';
import ThemeToggleButton from '@/components/ThemeToggleButton';
import { translateLeague } from '@/lib/leagueNames';
import { translateTeam } from '@/lib/teamNames';

const PlayerContributionTable = nextDynamic(() => import('@/components/PlayerContributionTable'));
const NpxgTrendChart    = nextDynamic(() => import('@/components/NpxgTrendChart'));
const LineupImpactTable = nextDynamic(() => import('@/components/report/LineupImpactTable'));

// ─── TrendPayload → NpxgTrend adapter（不改 NpxgTrendChart Props，兼容 CloudChartSection）─
import type { TrendPayload } from '@/types/report';
import type { NpxgTrend }    from '@/hooks/useMatchPayload';
function adaptTrend(trend: TrendPayload | null | undefined): NpxgTrend | null {
  if (!trend) return null;
  const mapEntries = (entries: TrendPayload['homeTeam']['last5All']) =>
    entries.map(e => ({ opponent: e.opponent, npxg_diff: e.npxGD, is_home: e.isHome, date: e.date }));
  return {
    home_team: {
      overall:   mapEntries(trend.homeTeam.last5All),
      home_only: mapEntries(trend.homeTeam.last5HomeAway),
    },
    away_team: {
      overall:   mapEntries(trend.awayTeam.last5All),
      away_only: mapEntries(trend.awayTeam.last5HomeAway),
    },
  };
}


export const dynamic   = 'force-dynamic';
export const revalidate = 0;

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

type AccessLevel = 'anonymous' | 'registered' | 'vip';

// ─────────────────────────────────────────────────────────────────────────────
// Small presentational components
// ─────────────────────────────────────────────────────────────────────────────

function LoginPrompt({ matchId }: { matchId: string }) {
  return (
    <div className="max-w-sm w-full flex flex-col gap-4">
      <ContactAdminPanel />
      <div className="text-center">
        <Link
          href={`/login?next=/report/${matchId}`}
          className="text-xs text-zinc-400 hover:text-primary-neon transition-colors"
        >
          已有账号？点此登录 →
        </Link>
      </div>
    </div>
  );
}

/** 分区标题行 */
function SectionLabel({
  icon,
  label,
  accentClass = 'bg-primary-neon shadow-[0_0_6px_#00F0FF]',
  badge,
}: {
  icon?: React.ReactNode;
  label: string;
  accentClass?: string;
  badge?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2.5 mb-4">
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${accentClass}`} />
      <span className="text-xs font-black tracking-[0.3em] uppercase text-slate-500
                       dark:text-base dark:font-black dark:tracking-[0.35em] dark:italic dark:text-white
                       flex items-center gap-1.5">
        {icon}
        {label}
      </span>
      {badge && <span className="ml-auto">{badge}</span>}
    </div>
  );
}

function FreeMatchBanner() {
  return (
    <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-green-500/10 border border-green-500/20 w-fit">
      <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
      <span className="text-xs font-black text-green-400 tracking-widest uppercase">
        今日免费场次 · 完整内容开放
      </span>
    </div>
  );
}

function PostMatchPlaceholder({ title, icon }: { title: string; icon: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-yellow-500/30 bg-yellow-500/[0.06] p-8
                    flex flex-col items-center justify-center gap-3 text-center">
      <div className="text-yellow-600 dark:text-yellow-400">{icon}</div>
      <p className="text-xs font-black tracking-[0.3em] uppercase text-yellow-700 dark:text-yellow-400">
        {title}
      </p>
      <p className="text-sm font-semibold text-slate-700 dark:text-white">
        赛后数据同步中 · 比赛结束后自动解锁
      </p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main report content (async Server Component)
// ─────────────────────────────────────────────────────────────────────────────

async function ReportContent({
  matchId,
  accessLevel,
  isFreeMatch,
}: {
  matchId: string;
  accessLevel: AccessLevel;
  isFreeMatch: boolean;
}) {
  const report = await getMatchReport(matchId);

  if (!report) {
    return (
      <>
        {/* ── Header (error state) ──────────────────────────────────────────── */}
        <header className="sticky top-0 z-40 bg-[var(--header-bg)] backdrop-blur-md border-b border-[var(--header-border)] px-4 py-3 flex items-center gap-3">
          <Link href="/" className="p-2 -ml-2 text-slate-400 dark:text-white hover:text-primary-neon transition-colors flex-shrink-0">
            <ChevronLeft size={22} />
          </Link>
          <span className="text-xs font-bold tracking-wider text-primary-neon uppercase">
            QUANT ANALYSIS · FOOTBALL
          </span>
          <div className="ml-auto"><ThemeToggleButton /></div>
        </header>
        <div className="flex flex-col items-center justify-center py-32 px-6 text-center">
          <div className="text-secondary-magenta text-5xl mb-6 opacity-30">⚠️</div>
          <h2 className="text-xl font-black italic mb-4 tracking-tight uppercase">量化数据流离线</h2>
          <p className="text-white/40 text-xs mb-8 leading-relaxed">
            数据同步失败 · 请稍后重试或前往首页
          </p>
          <Link href="/" className="px-8 py-3 rounded-xl bg-white/5 border border-white/10 text-sm font-black tracking-widest hover:bg-white/10 transition-all">
            返回首页
          </Link>
        </div>
      </>
    );
  }

  // ── Team names ─────────────────────────────────────────────────────────────
  let homeTeam = translateTeam(report.homeTeamName);
  let awayTeam = translateTeam(report.awayTeamName);
  if (homeTeam === 'HOME TEAM' && report.markdownContent) {
    const m = report.markdownContent.match(/# (.*) vs (.*)/i);
    if (m) { homeTeam = translateTeam(m[1].trim()); awayTeam = translateTeam(m[2].trim()); }
  }
  // 研报正文内英文球队名替换为中文
  if (report.markdownContent) {
    const rawHome = report.homeTeamName;
    const rawAway = report.awayTeamName;
    if (rawHome && rawHome !== homeTeam) {
      report.markdownContent = report.markdownContent.split(rawHome).join(homeTeam);
    }
    if (rawAway && rawAway !== awayTeam) {
      report.markdownContent = report.markdownContent.split(rawAway).join(awayTeam);
    }
  }

  // ── Tournament type ────────────────────────────────────────────────────────
  const isWc = report.tournamentType === 'wc';

  // ── Access rules ───────────────────────────────────────────────────────────
  const showCharts    = accessLevel !== 'anonymous';
  const hasFullAccess = accessLevel !== 'anonymous';
  const isGated       = false;
  const matchStatus: 'upcoming' | 'finished' =
    report.matchStatus === 'finished' ? 'finished' : 'upcoming';
  // 时间兜底：比赛开球 2.5h 后，即便 match_status 尚未被 archiver 更新也视为已结束
  const matchEndedByTime = (() => {
    if (!report.matchTime) return false;
    const kickoff = new Date(report.matchTime);
    return Date.now() > kickoff.getTime() + 2.5 * 60 * 60 * 1000;
  })();
  const matchEnded = matchStatus === 'finished' || matchEndedByTime;
  const isVip      = accessLevel === 'vip';
  const showPostMatch = isVip && matchEnded;

  // ── Probability ────────────────────────────────────────────────────────────
  const hasProbs = report.homeProb != null && report.awayProb != null;
  const probHome = hasProbs ? report.homeProb! : null;
  const probAway = hasProbs ? report.awayProb! : null;
  const probDraw = hasProbs
    ? (report.drawProb ?? Math.max(0, Math.round(100 - probHome! - probAway!)))
    : null;

  // ── System Verdict ─────────────────────────────────────────────────────────
  const verdict =
    probHome != null && probAway != null
      ? probHome > probAway + 10 ? 'HOME DOMINANCE'
      : probAway > probHome + 10 ? 'AWAY DOMINANCE'
      : 'CONTESTED MATCH'
      : 'AWAITING DATA';

  // Derive 系统预判 display text from inference when available (consistent with 核心结论)
  const verdictDisplay = (() => {
    if (report.inference) {
      const rest = report.inference.replace(/【[^】]+】/, '').trim();
      const label = rest.split('@')[0].trim().split(/\s+/)[0];
      if (label) return label;
    }
    return verdict === 'HOME DOMINANCE' ? '主队优势'
      : verdict === 'AWAY DOMINANCE' ? '客队优势'
      : verdict === 'CONTESTED MATCH' ? '势均力敌'
      : '等待数据';
  })();

  // ─────────────────────────────────────────────────────────────────────────
  // MOCK 数据：仅保留尚未对接的字段（双方近5场战绩、一句话解读、模块②14d命中率）
  // 模块⑤战绩卡已切换为后端真实数据 report.bestRecentStat
  // TODO: 接入 home_recent_form / away_recent_form / beginner_summary
  // ─────────────────────────────────────────────────────────────────────────
  const MOCK_BEGINNER = {
    beginnerSummary: '主队近5个主场全胜对手0进球，客队连续3轮没破门，模型主胜信心拉满。',
    homeRecentForm:  ['W','W','D','W','L'] as FormResult[],
    awayRecentForm:  ['L','W','W','L','W'] as FormResult[],
    recentHitRate14d: 71.4,
    recentHitRate14dN: 14,
    pipelineStatus: 'FINAL_REPORT_READY',
  };

  // ─── Beginner subtree ────────────────────────────────────────────────────
  const beginnerSubtree = (
    <BeginnerView
      matchId={matchId}
      homeTeam={homeTeam}
      awayTeam={awayTeam}
      league={translateLeague(report.league)}
      matchTime={report.matchTime}
      homeIcon={report.homeIcon}
      awayIcon={report.awayIcon}
      homeProb={report.homeProb}
      awayProb={report.awayProb}
      drawProb={report.drawProb}
      inference={report.inference}
      beginnerSummary={MOCK_BEGINNER.beginnerSummary}
      homeRecentForm={MOCK_BEGINNER.homeRecentForm}
      awayRecentForm={MOCK_BEGINNER.awayRecentForm}
      recentHitRate14d={MOCK_BEGINNER.recentHitRate14d}
      recentHitRate14dN={MOCK_BEGINNER.recentHitRate14dN}
      pipelineStatus={MOCK_BEGINNER.pipelineStatus}
      bestRecentStat={report.bestRecentStat}
    />
  );

  // ─── Pro subtree ─────────────────────────────────────────────────────────
  const proSubtree = (
    <>
      {/* ── 单列漏斗容器 ─────────────────────────────────────────────────── */}
      <div className="px-4 py-5 max-w-2xl mx-auto flex flex-col gap-5 pb-28 overflow-x-hidden">

        {/* ── 2. 赛事头部（概率 + AI 分析） ──────────────────────────────── */}
        <section className="space-y-4">

          {/* ① 队名卡：浅色独立白卡 / 深色融入面板 */}
          <div className="bg-white/85 backdrop-blur-xl dark:bg-[var(--panel-bg-strong)] border border-slate-900/10 dark:border-[var(--panel-border-strong)] rounded-3xl p-5 text-center space-y-2 shadow-[0_4px_24px_rgba(15,23,42,0.06)] dark:shadow-[var(--panel-shadow-strong)]">
            <span className="inline-block text-xs font-bold tracking-[0.15em] uppercase px-3 py-1 rounded-full
                             bg-slate-900 text-white
                             dark:bg-white/[0.06] dark:text-white dark:border dark:border-white/15">
              {translateLeague(report.league) || 'Football'}
            </span>
            {/* 队徽 + 队名行 */}
            <div className="flex items-center justify-center gap-3">
              {report.homeIcon && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={report.homeIcon} alt={homeTeam} width={44} height={44} className="object-contain flex-shrink-0 ring-1 ring-black/8 rounded-full bg-white p-0.5" />
              )}
              <h2 className="text-2xl font-black text-slate-900 dark:text-white leading-tight">
                {homeTeam} <span className="text-base font-semibold text-slate-600 dark:text-white">vs</span> {awayTeam}
              </h2>
              {report.awayIcon && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={report.awayIcon} alt={awayTeam} width={44} height={44} className="object-contain flex-shrink-0 ring-1 ring-black/8 rounded-full bg-white p-0.5" />
              )}
            </div>
            <p className="text-xs text-slate-700 dark:text-white tracking-wider">
              <MatchTimeDisplay utcStr={report.matchTime} />
            </p>
          </div>

          {/* ② 核心结论 GlassPickBlock（原 ③ 上移；WDL 三列大数字已删除，被市场对比卡吞并） */}
          {report.inference && (
            hasFullAccess ? (
              <GlassPickBlock inference={report.inference} />
            ) : (
              <div className="flex items-start gap-2 bg-[#E91E63]/5 border border-[#E91E63]/20 rounded-xl px-4 py-3">
                <TrendingUp size={14} className="text-[#E91E63] flex-shrink-0 mt-0.5" />
                <p className="text-xs text-[#E91E63]/80 leading-relaxed">{report.inference}</p>
              </div>
            )
          )}

          {/* 匿名/未登录用户：保留概率锁定提示 */}
          {!hasProbs && (
            <div className="flex items-center justify-center gap-2 py-3 rounded-xl bg-white dark:bg-white/5 border border-slate-200 dark:border-white/5">
              <Lock size={14} className="text-slate-600 dark:text-white" />
              <span className="text-xs text-slate-700 dark:text-white tracking-widest">概率数据仅对登录用户开放</span>
            </div>
          )}

          {/* ③ 市场 vs 模型 — 价值差对比 */}
          {hasFullAccess && (
            <MarketVsModelCard
              modelHome={report.homeProb}
              modelDraw={report.drawProb}
              modelAway={report.awayProb}
              marketHome={report.marketImpliedProb?.home}
              marketDraw={report.marketImpliedProb?.draw}
              marketAway={report.marketImpliedProb?.away}
              recommended={verdictDisplay}
            />
          )}

          {/* ④ 模型综合判断（WC 不渲染：verdictSummary=null 且 keyVariables 由 AI 正文覆盖）*/}
          {hasFullAccess && !isWc && (
            <ModelVerdictCard
              homeTeam={homeTeam}
              awayTeam={awayTeam}
              verdictSummary={report.verdictSummary}
              keyVariables={report.keyVariables}
              keyRisk={report.keyRisk}
              /* finalPick 三参数留 null：避免与上面 GlassPickBlock 重复展示分析结论 */
              pickDirection={null}
              pickOdds={null}
              confidenceStars={null}
            />
          )}

          {/* ⑤ 章节锚点导航条 — 摘要区与论据区的分隔 */}
          {hasFullAccess && <SectionNavBar hasReview={matchEnded && isVip} />}
        </section>

        {/* 免费场标签 */}
        {isFreeMatch && <FreeMatchBanner />}

        {/* ── 3. 数据论据区（注册用户）────────────────────────────────────── */}
        {showCharts && (
          <section id="data" className="flex flex-col gap-5">
            {/* Block A · npxGD 趋势图（联赛专用，WC 无此数据直接跳过）*/}
            {!isWc && (
            <div className="bg-[var(--panel-bg-strong)] backdrop-blur-xl border border-[var(--panel-border-strong)] rounded-2xl p-5 overflow-hidden shadow-[var(--panel-shadow-strong)]">
              <SectionLabel
                icon={<TrendingUp size={11} />}
                label="战力演化趋势 · NPXGD"
                accentClass="bg-secondary-magenta shadow-[0_0_6px_#FF00E5]"
              />
              {report.trendData && adaptTrend(report.trendData) ? (
                <div className="w-full overflow-x-hidden">
                  <NpxgTrendChart
                    npxgData={adaptTrend(report.trendData)!}
                    homeTeamName={homeTeam}
                    awayTeamName={awayTeam}
                  />
                </div>
              ) : (
                <div className="py-12 flex flex-col items-center justify-center text-slate-600 dark:text-white">
                  <TrendingUp size={28} className="mb-2" />
                  <p className="text-xs tracking-widest uppercase">趋势数据尚未同步</p>
                </div>
              )}
              <InsightLine text={report.chartInsights?.npxgd} />
              {report.markdownSections?.powerEvolution && hasFullAccess && (
                <div className="mt-3 pt-3 border-t border-slate-200/60 dark:border-white/8">
                  <ReportMarkdown content={report.markdownSections.powerEvolution} />
                </div>
              )}
            </div>
            )}

            {/* Block B · 射门渗透（联赛）或 WC 攻防统计表 */}
            {!isWc && (
              <div className="bg-[var(--panel-bg-strong)] backdrop-blur-xl border border-[var(--panel-border-strong)] rounded-2xl p-5 overflow-hidden shadow-[var(--panel-shadow-strong)]">
                <SectionLabel
                  icon={<Crosshair size={11} />}
                  label="射门渗透分析 · 近5场"
                  accentClass="bg-primary-neon shadow-[0_0_6px_#00F0FF]"
                />
                {report.shotHistory ? (
                  <div className="w-full overflow-x-hidden">
                    <InteractiveShotMapClient
                      homeTeam={report.shotHistory.homeTeam}
                      awayTeam={report.shotHistory.awayTeam}
                      homeTeamName={homeTeam}
                      awayTeamName={awayTeam}
                    />
                  </div>
                ) : (
                  <div className="py-12 flex flex-col items-center justify-center text-slate-600 dark:text-white">
                    <Crosshair size={28} className="mb-2" />
                    <p className="text-xs tracking-widest uppercase">射门数据尚未同步</p>
                  </div>
                )}
                <InsightLine text={report.chartInsights?.shotmap} />
              </div>
            )}

            {/* Block B-WC · 近期数据对比（替代空的「原始攻防对比」，使用近5/10场均值）*/}
            {isWc && (
              <WcRecentStatsCompare
                wcRecentCompare={(report as any).wcRecentCompare}
                homeTeam={homeTeam}
                awayTeam={awayTeam}
              />
            )}

            {/* Block B-WC-AH · 亚盘让球信息卡（仅幅度，无胜率）*/}
            {isWc && (() => {
              const ahData = (report as any).ahImplied;
              if (!ahData || ahData.magnitude == null) return null;
              return (
                <WcAhInfoCard
                  homeTeamName={homeTeam}
                  awayTeamName={awayTeam}
                  line={ahData.line}
                  magnitude={ahData.magnitude}
                  nBooks={ahData.n_books ?? 0}
                />
              );
            })()}

            {/* Block B-WC-MODEL · 模型预测对标（第三方 Sportmonks 模型 vs 市场共识）*/}
            {isWc && (
              <WcModelPredictionsCard
                wcCcPredictions={(report as any).wcCcPredictions}
                marketHomeProb={report.homeProb}
                marketDrawProb={report.drawProb}
                marketAwayProb={report.awayProb}
                homeTeam={homeTeam}
                awayTeam={awayTeam}
              />
            )}

            {/* Block B-WC-LINEUP · 预计首发简报 */}
            {isWc && (
              <WcProjectedLineupTable
                wcPredictedLineup={(report as any).wcPredictedLineup}
                homeTeam={homeTeam}
                awayTeam={awayTeam}
              />
            )}

            {/* Block B-WC-RECENT · 近期表现 */}
            {isWc && (
              <WcRecentFormCard
                wcHomeRecent={(report as any).wcHomeRecent}
                wcAwayRecent={(report as any).wcAwayRecent}
                homeTeam={homeTeam}
                awayTeam={awayTeam}
              />
            )}
          </section>
        )}

        {/* ── 4. 阵容章节（注册用户，联赛专用；WC 无球员级数据）──────────── */}
        {showCharts && report.lineupImpact && !isWc && (
          <section id="lineup" className="flex flex-col gap-5">
            {/* Block E · 阵容攻防贡献表（LineupImpactTable 是唯一入口） */}
            <div className="bg-[var(--panel-bg-strong)] border border-[var(--panel-border-strong)] rounded-2xl overflow-hidden shadow-[var(--panel-shadow-strong)]">
              <div className="px-5 pt-5">
                <SectionLabel
                  icon={<Activity size={11} />}
                  label={
                    report.lineupStatus === 'confirmed' ? '阵容攻防影响分析'
                    : report.lineupStatus === 'unavailable' ? '首发待定'
                    : '预测首发 · 攻防影响分析'
                  }
                  accentClass={
                    report.lineupStatus === 'confirmed'
                      ? 'bg-[#00F0FF] shadow-[0_0_6px_#00F0FF]'
                      : 'bg-green-400 shadow-[0_0_6px_#4ade80]'
                  }
                  badge={
                    report.lineupStatus === 'confirmed' && report.lineupConfirmedAt ? (
                      <span className="text-xs font-black px-2 py-0.5 rounded-full border
                                       bg-[#00F0FF]/10 text-[#00F0FF] border-[#00F0FF]/40">
                        ✅ 已确认 · {new Date(report.lineupConfirmedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    ) : report.lineupStatus !== 'confirmed' ? (
                      <span className="text-xs font-black px-2 py-0.5 rounded-full border
                                       bg-slate-900 text-white border-slate-700
                                       dark:bg-white/5 dark:text-white dark:border-white/20">
                        📋 预测
                      </span>
                    ) : undefined
                  }
                />
              </div>
              <LineupImpactTable
                lineupImpact={report.lineupImpact}
                homeTeamName={homeTeam}
                awayTeamName={awayTeam}
              />
            </div>

            {/* 阵容影响 LLM 解读段（拆段嵌入） */}
            {report.markdownSections?.lineupImpact && hasFullAccess && (
              <div className="bg-[var(--panel-bg-strong)] backdrop-blur-xl border border-[var(--panel-border-strong)] rounded-2xl p-5 overflow-hidden shadow-[var(--panel-shadow-strong)]">
                <ReportMarkdown content={report.markdownSections.lineupImpact} />
              </div>
            )}

            {/* 球员贡献矩阵（默认折叠 — 次级专业内容） */}
            {hasFullAccess && (
              <CollapsibleSection
                title="22 名球员详细评分"
                hint="专业用户可展开查看"
                defaultOpen={false}
              >
                <PlayerContributionTable
                  playerStats={report.playerStats ?? undefined}
                  teamStats={report.teamMatchStats ?? undefined}
                  homeTeamName={homeTeam}
                  awayTeamName={awayTeam}
                />
                <InsightLine text={report.chartInsights?.playerContribution} />
              </CollapsibleSection>
            )}
          </section>
        )}

        {/* ── 5. 战术深度章节 ─────────────────────────────────────────────── */}
        <section id="tactics" className="flex flex-col gap-5">
          {(report.markdownSections?.ahAnalysis || report.markdownSections?.ouAnalysis || report.markdownSections?.overallComparison) ? (
            // 新格式（AH/OU 导向研报，2026-04-28+）
            <>
              {report.markdownSections?.ahAnalysis && (
                <div className="bg-[var(--panel-bg-strong)] backdrop-blur-xl border border-[var(--panel-border-strong)] rounded-2xl p-5 relative overflow-hidden shadow-[var(--panel-shadow-strong)]">
                  <SectionLabel icon={<BarChart2 size={11} />} label="亚盘深度分析 · AI" />
                  <ReportMarkdown content={report.markdownSections.ahAnalysis} />
                </div>
              )}
              {report.markdownSections?.ouAnalysis && (
                <div className="bg-[var(--panel-bg-strong)] backdrop-blur-xl border border-[var(--panel-border-strong)] rounded-2xl p-5 relative overflow-hidden shadow-[var(--panel-shadow-strong)]">
                  <SectionLabel icon={<BarChart2 size={11} />} label="进球数深度分析 · AI" />
                  <ReportMarkdown content={report.markdownSections.ouAnalysis} />
                </div>
              )}
              {report.markdownSections?.overallComparison && (
                <div className="bg-[var(--panel-bg-strong)] backdrop-blur-xl border border-[var(--panel-border-strong)] rounded-2xl p-5 relative overflow-hidden shadow-[var(--panel-shadow-strong)]">
                  <SectionLabel icon={<BarChart2 size={11} />} label="综合战力对比 · AI" />
                  <ReportMarkdown content={report.markdownSections.overallComparison} />
                </div>
              )}
            </>
          ) : report.markdownSections?.tacticalAnalysis ? (
            // 旧格式：拆段后渲染 战术博弈分析 段
            <div className="bg-[var(--panel-bg-strong)] backdrop-blur-xl border border-[var(--panel-border-strong)] rounded-2xl p-5 relative overflow-hidden shadow-[var(--panel-shadow-strong)]">
              <SectionLabel icon={<BarChart2 size={11} />} label="战术博弈分析 · AI" />
              <ReportMarkdown content={report.markdownSections.tacticalAnalysis} />
            </div>
          ) : !report.markdownContent || report.markdownContent.startsWith('报告内容正在同步中') ? (
            <div className="bg-[var(--panel-bg-strong)] backdrop-blur-xl border border-[var(--panel-border-strong)] rounded-2xl p-5 relative overflow-hidden shadow-[var(--panel-shadow-strong)]">
              <SectionLabel icon={<BarChart2 size={11} />} label="AI 神经分析 · 赛前结论" />
              <PostMatchPlaceholder title="Report · Generating" icon={<FileText size={26} />} />
            </div>
          ) : (
            // Fallback：旧研报无结构化 H2 段，整段渲染原始长文
            <div className="bg-[var(--panel-bg-strong)] backdrop-blur-xl border border-[var(--panel-border-strong)] rounded-2xl p-5 relative overflow-hidden shadow-[var(--panel-shadow-strong)]">
              <SectionLabel icon={<BarChart2 size={11} />} label="AI 神经分析 · 赛前结论" />
              <ReportMarkdown content={report.markdownContent} />
            </div>
          )}
        </section>

        {/* ── 6. 赛后复盘区（仅赛后渲染，赛前完全跳过 DOM）─────────────────── */}
        {matchEnded && (
          <section id="review" className="flex flex-col gap-4">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-yellow-500/10 border border-yellow-500/20 w-fit">
              <span className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
              <span className="text-xs font-black text-yellow-700 dark:text-yellow-400 tracking-widest uppercase">
                赛后复盘 · VIP 专属
              </span>
            </div>

            {/* 非 VIP 引导卡 */}
            {!isVip && (
              <div className="bg-[var(--panel-bg-strong)] backdrop-blur-xl border border-yellow-500/20 rounded-2xl p-6 flex flex-col items-center gap-3 text-center shadow-[var(--panel-shadow-strong)]">
                <Lock size={24} className="text-yellow-400/60" />
                <p className="text-sm font-black text-slate-900 dark:text-white">赛后量化复盘 · 仅 VIP 可见</p>
                <p className="text-xs text-slate-600 dark:text-white font-mono">包含模型回测、实际期望进球对比、AI 审计报告</p>
                <Link href="/login" className="mt-1 px-4 py-2 rounded-full bg-yellow-400/10 border border-yellow-400/30 text-yellow-700 dark:text-yellow-400 text-xs font-black tracking-widest hover:bg-yellow-400/20 transition-all">
                  联系管理员开通 →
                </Link>
              </div>
            )}

            {/* VIP 专属内容块 */}
            {isVip && (
              <>
                {/* D1 — 赛前预测 vs 赛后实际对比卡 */}
                <PostMatchCompareCard
                  homeProb={probHome}
                  drawProb={probDraw}
                  awayProb={probAway}
                  homeTeamName={homeTeam}
                  awayTeamName={awayTeam}
                  postMatchShots={report.postMatchShots}
                />

                <div className="bg-[var(--panel-bg-strong)] backdrop-blur-xl border border-[var(--panel-border-strong)] rounded-2xl p-5 overflow-hidden shadow-[var(--panel-shadow-strong)]">
                  <SectionLabel
                    icon={<Crosshair size={11} />}
                    label="赛后射门分布 · 真实赛场数据"
                    accentClass="bg-yellow-400 shadow-[0_0_6px_#FACC15]"
                  />
                  {report.postMatchShots ? (
                    <div className="w-full overflow-x-hidden">
                      <InteractiveShotMapClient
                        homeTeam={{
                          team_name: report.postMatchShots.homeTeam.name || homeTeam,
                          matches: [{
                            match_id:         0,
                            date:             '',
                            opponent:         awayTeam,
                            is_home:          true,
                            result:           '',
                            total_shots:      report.postMatchShots.homeTeam.shots.length,
                            situation_counts: {},
                            shots:            report.postMatchShots.homeTeam.shots,
                          }],
                        }}
                        awayTeam={{
                          team_name: report.postMatchShots.awayTeam.name || awayTeam,
                          matches: [{
                            match_id:         0,
                            date:             '',
                            opponent:         homeTeam,
                            is_home:          false,
                            result:           '',
                            total_shots:      report.postMatchShots.awayTeam.shots.length,
                            situation_counts: {},
                            shots:            report.postMatchShots.awayTeam.shots,
                          }],
                        }}
                        homeTeamName={homeTeam}
                        awayTeamName={awayTeam}
                      />
                    </div>
                  ) : (
                    <PostMatchPlaceholder
                      title="Post-Match Shot Map · Syncing"
                      icon={<Crosshair size={26} />}
                    />
                  )}
                </div>

                {/* 球员贡献矩阵已迁移到 #lineup 章节（CollapsibleSection 折叠展示） */}

                <div className="bg-[var(--panel-bg-strong)] backdrop-blur-xl border border-[var(--panel-border-strong)] rounded-2xl p-5 relative overflow-hidden shadow-[var(--panel-shadow-strong)]">
                  <div className="absolute top-0 left-0 w-40 h-40 bg-yellow-400/5 blur-[60px] rounded-full pointer-events-none" />
                  <SectionLabel
                    icon={<BarChart2 size={11} />}
                    label="赛后量化复盘 · AI 审计"
                    accentClass="bg-yellow-400 shadow-[0_0_6px_#FACC15]"
                  />
                  {report.postMatchReview ? (
                    <MarkdownRenderer content={report.postMatchReview} />
                  ) : (
                    <PostMatchPlaceholder
                      title="Post-Match Review · 预计 10:30 CST 自动生成"
                      icon={<BarChart2 size={26} />}
                    />
                  )}
                </div>
              </>
            )}
          </section>
        )}

        {/* 底部 ModelVerdictCard 已前置至决策摘要区（line ~360），此处删除避免重复 */}

      </div>

      {/* ── 底部固定栏 ────────────────────────────────────────────────────── */}
      <div className="fixed bottom-0 left-0 right-0 bg-[var(--header-bg)] backdrop-blur-xl border-t border-[var(--header-border)] px-4 pt-3 pb-6 z-50">
        <div className="max-w-2xl mx-auto flex items-center justify-between gap-4">
          <div className="min-w-0">
            <span className="block text-[#005faf] dark:text-[#3B82F6] text-xs font-black uppercase tracking-wider mb-0.5">
              系统预判
            </span>
            <span className="text-slate-900 dark:text-white font-black text-base uppercase tracking-tight truncate block">
              {verdictDisplay}
            </span>
          </div>
          {accessLevel !== 'vip' && (
            <Link
              href="/register"
              className="flex-shrink-0 flex items-center gap-1.5 px-5 py-2.5 rounded-xl text-sm font-bold
                         bg-gradient-to-r from-red-600 to-rose-500 text-white
                         dark:bg-none dark:bg-white dark:text-black dark:from-white dark:to-white
                         shadow-[0_0_15px_rgba(239,68,68,0.4)] dark:shadow-none
                         hover:shadow-[0_0_25px_rgba(239,68,68,0.6)] dark:hover:bg-white/90
                         active:scale-95 transition-all"
            >
              <Star size={14} />
              解锁 VIP
            </Link>
          )}
        </div>
      </div>
    </>
  );

  // ─── Final layout: header + tab-switched body ────────────────────────────
  return (
    <>
      <header className="sticky top-0 z-40 bg-[var(--header-bg)] backdrop-blur-md border-b border-[var(--header-border)] px-4 py-3 flex items-center justify-between">
        <Link href="/" className="p-2 -ml-2 text-slate-500 dark:text-white hover:text-[#E91E63] transition-colors flex-shrink-0">
          <ChevronLeft size={22} />
        </Link>
        <h1 className="text-base font-black text-slate-900 dark:text-white tracking-tight">赛事研报</h1>
        <ThemeToggleButton />
      </header>

      <ReportTabSwitch beginner={beginnerSubtree} pro={proSubtree} />
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Page entry
// ─────────────────────────────────────────────────────────────────────────────

export default async function ReportPage({
  params,
}: {
  params: Promise<{ match_id: string }>;
}) {
  const resolvedParams = await params;
  const matchId = String(resolvedParams.match_id).trim();

  // ── Auth ───────────────────────────────────────────────────────────────────
  // Dev mode: if a fixture file exists for this match, bypass auth entirely.
  let accessLevel: AccessLevel;
  if (process.env.NODE_ENV === 'development') {
    const { existsSync } = await import('fs');
    const { join } = await import('path');
    const fixturePath = join(process.cwd(), 'fixtures', `report_${matchId}.json`);
    if (existsSync(fixturePath)) {
      accessLevel = 'vip';
    } else {
      const session = await auth();
      accessLevel = !session?.user ? 'anonymous' : 'vip';
    }
  } else {
    const session = await auth();
    accessLevel = !session?.user ? 'anonymous' : 'vip';
  }

  // ── Daily free match ───────────────────────────────────────────────────────
  let isFreeMatch = false;
  try {
    const API_BASE = process.env.FASTAPI_URL || 'http://localhost:8000';
    const res = await fetch(`${API_BASE}/api/v1/reports/daily_free_id`, { cache: 'no-store' });
    if (res.ok) {
      const data = await res.json();
      isFreeMatch = String(data.free_match_id) === String(matchId);
    }
  } catch (e) {
    console.warn('[ReportPage] Could not fetch daily free id:', e);
  }

  return (
    <main className="relative min-h-screen bg-[var(--color-background)] text-[var(--color-foreground)] overflow-x-hidden w-full font-body selection:bg-primary-neon/20">

      <div className="relative z-10 w-full">

        {accessLevel === 'anonymous' ? (
          <>
            {/* 所有游客统一：联系管理员二维码 + 登录链接 */}
            <header className="sticky top-0 z-40 bg-[var(--header-bg)] backdrop-blur-md border-b border-[var(--header-border)] px-4 py-3 flex items-center gap-3">
              <Link href="/" className="p-2 -ml-2 text-slate-400 dark:text-white hover:text-primary-neon transition-colors flex-shrink-0 group">
                <ChevronLeft size={22} className="group-hover:-translate-x-0.5 transition-transform" />
              </Link>
              <div className="flex flex-col min-w-0 flex-1">
                <span className="text-xs font-bold tracking-wider text-primary-neon uppercase">
                  QUANT ANALYSIS · FOOTBALL
                </span>
                <span className="text-sm font-black text-slate-800 dark:text-white leading-tight">比赛研报</span>
              </div>
              <ThemeToggleButton />
            </header>
            <div className="flex flex-col items-center justify-center py-16 px-4">
              <LoginPrompt matchId={matchId} />
            </div>
          </>
        ) : (
          <Suspense
            fallback={
              <div className="flex flex-col">
                {/* 加载中保留一个通用导航栏 */}
                <header className="sticky top-0 z-40 bg-[var(--header-bg)] backdrop-blur-md border-b border-[var(--header-border)] px-4 py-3 flex items-center gap-3">
                  <Link href="/" className="p-2 -ml-2 text-slate-400 dark:text-white hover:text-primary-neon transition-colors flex-shrink-0">
                    <ChevronLeft size={22} />
                  </Link>
                  <div className="flex flex-col min-w-0 flex-1">
                    <span className="text-xs font-bold tracking-wider text-primary-neon uppercase">
                      QUANT ANALYSIS · FOOTBALL
                    </span>
                    <span className="text-sm font-black text-slate-800 dark:text-white leading-tight">比赛研报</span>
                  </div>
                  <ThemeToggleButton />
                </header>
                <div className="flex flex-col items-center justify-center py-60 gap-8">
                  <Activity size={40} className="text-primary-neon animate-spin" />
                  <p className="text-xs font-black text-primary-neon/40 uppercase tracking-[0.5em] animate-pulse">
                    NEURAL SYNC :: PROCESSING QUANT DATA
                  </p>
                </div>
              </div>
            }
          >
            <ReportContent
              matchId={matchId}
              accessLevel={accessLevel}
              isFreeMatch={isFreeMatch}
            />
          </Suspense>
        )}

        {/* 免责声明 */}
        <div className="mt-8 mb-4 mx-auto w-full max-w-2xl px-4">
          <div className="px-4 py-3 border border-slate-300 dark:border-white/10 rounded-lg bg-slate-50/50 dark:bg-white/[0.02]">
            <p className="text-xs text-slate-600 dark:text-white/60 leading-relaxed">
              ⚠️ 免责声明：本页面所有内容（包括但不限于 AI 分析、概率预测、市场价格分析）均基于历史数据和统计模型生成，
              仅供数据分析参考，<span className="font-bold">绝不构成任何形式的投注、博彩或理财建议</span>。模型存在固有误差，过往表现不代表未来结果。
              使用本站内容所产生的任何后果由用户自行承担。
              <Link href="/terms#disclaimer" className="text-[#005faf] dark:text-primary-neon hover:underline ml-1">完整条款 →</Link>
            </p>
          </div>
        </div>

        <footer className="mt-12 pt-8 border-t border-slate-200 dark:border-white/5 w-full max-w-2xl mx-auto px-4 flex justify-between items-center text-xs font-bold text-slate-600 dark:text-white uppercase tracking-[0.3em]">
          <span>喵弟量化实验室 :: SYSTEM CORE v6.2.0</span>
          <span>STITCH PROTOCOL SECURED</span>
        </footer>
        <Footer />
      </div>
    </main>
  );
}
