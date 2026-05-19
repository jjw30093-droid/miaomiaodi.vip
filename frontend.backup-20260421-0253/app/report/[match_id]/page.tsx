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
import { BackgroundEffects } from '@/components/BackgroundEffects';
import {
  ChevronLeft, Lock, BarChart2, Crosshair, TrendingUp, Star, Activity, FileText,
} from 'lucide-react';
import { MatchTimeDisplay } from '@/components/MatchTimeDisplay';

const PlayerContributionTable = nextDynamic(() => import('@/components/PlayerContributionTable'));
const TeamTrendChart           = nextDynamic(() => import('@/components/TeamTrendChart'));

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
    <div className="glass-panel max-w-md w-full p-10 text-center backdrop-blur-3xl animate-fade-in shadow-ambient-lift border border-white/10 rounded-3xl">
      <div className="w-16 h-16 rounded-full bg-primary-neon/10 border border-primary-neon/30 flex items-center justify-center mx-auto mb-6">
        <Lock size={28} className="text-primary-neon" />
      </div>
      <h2 className="text-xl font-black italic mb-3 tracking-tight">登录后查看研报</h2>
      <p className="text-zinc-500 text-xs mb-8 leading-relaxed">
        注册账号免费获得每日精选场次完整分析<br />
        包含射门分布图、npxG 趋势及球员贡献矩阵
      </p>
      <div className="flex flex-col gap-3">
        <Link
          href={`/login?from=/report/${matchId}`}
          className="block w-full py-3 rounded-xl bg-primary-neon/10 border border-primary-neon/40 text-primary-neon text-sm font-black tracking-widest hover:bg-primary-neon/20 transition-all"
        >
          登录账号
        </Link>
        <Link
          href="/register"
          className="block w-full py-3 rounded-xl bg-white/5 border border-white/10 text-white/60 text-sm font-black tracking-widest hover:bg-white/10 transition-all"
        >
          免费注册
        </Link>
        <Link href="/" className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors mt-2">
          返回首页
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
      <span className="text-[11px] font-black tracking-[0.3em] uppercase text-white/40 flex items-center gap-1.5">
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
      <span className="text-[10px] font-black text-green-400 tracking-widest uppercase">
        今日免费场次 · 完整内容开放
      </span>
    </div>
  );
}

function PostMatchPlaceholder({ title, icon }: { title: string; icon: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-yellow-500/10 bg-yellow-500/[0.03] p-8
                    flex flex-col items-center justify-center gap-3 text-center opacity-50">
      <div className="text-yellow-400/50">{icon}</div>
      <p className="text-[10px] font-black tracking-[0.3em] uppercase text-yellow-400/50">{title}</p>
      <p className="text-[9px] text-white/20">赛后数据同步中 · 比赛结束后自动解锁</p>
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
        <header className="sticky top-0 z-40 bg-[#0D0F14]/80 backdrop-blur-md border-b border-white/5 px-4 py-3 flex items-center gap-3">
          <Link href="/" className="p-2 -ml-2 text-white/40 hover:text-primary-neon transition-colors flex-shrink-0">
            <ChevronLeft size={22} />
          </Link>
          <span className="text-[9px] font-bold tracking-wider text-primary-neon uppercase">
            QUANT ANALYSIS · FOOTBALL
          </span>
        </header>
        <div className="flex flex-col items-center justify-center py-32 px-6 text-center">
          <div className="text-secondary-magenta text-5xl mb-6 opacity-30">⚠️</div>
          <h2 className="text-xl font-black italic mb-4 tracking-tight uppercase">量化数据流离线</h2>
          <p className="text-zinc-500 text-xs mb-8 leading-relaxed opacity-60">
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
  let homeTeam = report.homeTeamName;
  let awayTeam = report.awayTeamName;
  if (homeTeam === 'HOME TEAM' && report.markdownContent) {
    const m = report.markdownContent.match(/# (.*) vs (.*)/i);
    if (m) { homeTeam = m[1].trim(); awayTeam = m[2].trim(); }
  }

  // ── Access rules ───────────────────────────────────────────────────────────
  const showCharts    = accessLevel !== 'anonymous';
  const hasFullAccess = accessLevel === 'vip' || (isFreeMatch && accessLevel !== 'anonymous');
  const isGated       = !hasFullAccess;
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

  return (
    <>
      {/* ── 1. Sticky 顶部导航栏 ─────────────────────────────────────────── */}
      <header className="sticky top-0 z-40 bg-[#0D0F14]/80 backdrop-blur-md border-b border-white/5 px-4 py-3 flex items-center gap-3">
        <Link
          href="/"
          className="p-2 -ml-2 text-white/40 hover:text-primary-neon transition-colors flex-shrink-0 group"
        >
          <ChevronLeft size={22} className="group-hover:-translate-x-0.5 transition-transform" />
        </Link>
        <div className="flex flex-col min-w-0">
          <span className="text-[9px] font-bold tracking-wider text-primary-neon uppercase truncate">
            QUANT ANALYSIS · {report.league || 'FOOTBALL'}
          </span>
          <h1 className="text-base font-black text-white/90 truncate leading-tight">
            {homeTeam} <span className="text-primary-neon">vs</span> {awayTeam}
          </h1>
        </div>
      </header>

      {/* ── 单列漏斗容器 ─────────────────────────────────────────────────── */}
      <div className="px-4 py-5 max-w-2xl mx-auto flex flex-col gap-5 pb-28 overflow-x-hidden">

        {/* ── 2. 赛事头部（概率 + AI 推荐） ──────────────────────────────── */}
        <section className="glass-panel border border-white/5 rounded-3xl p-5 space-y-4">

          {/* Home vs Away */}
          <div className="flex items-center justify-between">
            <div className="text-center flex-1">
              <p className="text-[10px] text-white/30 uppercase tracking-widest mb-0.5">Home</p>
              <p className="font-black text-sm text-white/90 truncate">{homeTeam}</p>
            </div>
            <div className="flex flex-col items-center px-4">
              <span className="text-[9px] font-bold text-white/20 tracking-widest uppercase">
                <MatchTimeDisplay utcStr={report.matchTime} />
              </span>
              <span className="text-xs font-black text-white/40 mt-0.5">VS</span>
            </div>
            <div className="text-center flex-1">
              <p className="text-[10px] text-white/30 uppercase tracking-widest mb-0.5">Away</p>
              <p className="font-black text-sm text-white/90 truncate">{awayTeam}</p>
            </div>
          </div>

          {/* 胜率分布 */}
          {hasProbs ? (
            <div className="grid grid-cols-3 gap-2">
              {[
                { label: '主胜', val: probHome! },
                { label: '平局', val: probDraw! },
                { label: '客胜', val: probAway! },
              ].map(({ label, val }) => (
                <div key={label} className="flex flex-col items-center bg-white/5 rounded-xl p-3">
                  <span className="text-[9px] text-white/30 uppercase mb-1">{label}</span>
                  <span className="text-xl font-black text-primary-neon">
                    {val.toFixed(1)}<span className="text-xs font-bold text-white/40">%</span>
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center justify-center gap-2 py-3 rounded-xl bg-white/5 border border-white/5">
              <Lock size={14} className="text-white/30" />
              <span className="text-[10px] text-white/30 tracking-widest">概率数据仅对登录用户开放</span>
            </div>
          )}

          {/* AI 推荐摘要：hasFullAccess → GlassPickBlock（核心推荐玻璃块）
              否则 → 简版 inference 告警框作为 teaser */}
          {report.inference && (
            hasFullAccess ? (
              <GlassPickBlock inference={report.inference} />
            ) : (
              <div className="flex items-start gap-2 bg-primary-neon/5 border border-primary-neon/20 rounded-xl px-4 py-3">
                <TrendingUp size={14} className="text-primary-neon flex-shrink-0 mt-0.5" />
                <p className="text-xs text-primary-neon/80 leading-relaxed">{report.inference}</p>
              </div>
            )
          )}
        </section>

        {/* 免费场标签 */}
        {isFreeMatch && <FreeMatchBanner />}

        {/* ── 3. 注册用户区（图表）────────────────────────────────────────── */}
        {showCharts && (
          <>
            {/* Block A · npxGD 趋势图 */}
            <div className="glass-panel border border-white/5 rounded-2xl p-5 overflow-hidden">
              <SectionLabel
                icon={<TrendingUp size={11} />}
                label="Market Potency Trend · npxGD"
                accentClass="bg-secondary-magenta shadow-[0_0_6px_#FF00E5]"
              />
              {report.trendData ? (
                <div className="w-full overflow-x-hidden">
                  <TeamTrendChart
                    trendData={report.trendData}
                    homeTeamName={homeTeam}
                    awayTeamName={awayTeam}
                  />
                </div>
              ) : (
                <div className="py-12 flex flex-col items-center justify-center text-white/20">
                  <TrendingUp size={28} className="mb-2" />
                  <p className="text-[10px] tracking-widest uppercase">Trend data not synced</p>
                </div>
              )}
            </div>

            {/* Block B · 赛前射门分布图 */}
            <div className="glass-panel border border-white/5 rounded-2xl p-5 overflow-hidden">
              <SectionLabel
                icon={<Crosshair size={11} />}
                label="Incursion Analysis · Last 5 Matches"
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
                <div className="py-12 flex flex-col items-center justify-center text-white/20">
                  <Crosshair size={28} className="mb-2" />
                  <p className="text-[10px] tracking-widest uppercase">Shot data not synced</p>
                </div>
              )}
            </div>

            {/* Block C · 球员贡献统计表 */}
            <div className="w-full overflow-x-hidden">
              <PlayerContributionTable
                playerStats={report.playerStats ?? undefined}
                teamStats={report.teamMatchStats ?? undefined}
                homeTeamName={homeTeam}
                awayTeamName={awayTeam}
              />
            </div>

            {/* Block D · 预计首发 & 伤停简报（公开区） */}
            {report.lineupBrief && (
              <div className="glass-panel border border-white/5 rounded-2xl p-5 overflow-hidden">
                <SectionLabel
                  icon={<Activity size={11} />}
                  label="Confirmed Lineup · Absence Report"
                  accentClass="bg-green-400 shadow-[0_0_6px_#4ade80]"
                />
                <div className="w-full overflow-x-hidden">
                  <MarkdownRenderer content={report.lineupBrief} />
                </div>
              </div>
            )}
          </>
        )}

        {/* ── 4. VIP 核心研报区 ─────────────────────────────────────────── */}
        <div className="glass-panel border border-white/5 rounded-2xl p-5 relative overflow-hidden">
          <div className="absolute top-0 left-0 w-40 h-40 bg-primary-neon/5 blur-[60px] rounded-full pointer-events-none" />
          <SectionLabel
            icon={<BarChart2 size={11} />}
            label="Neural Analysis Intelligence · Pre-match Verdict"
            badge={
              isGated ? (
                <span className="flex items-center gap-1 text-red-400 text-[9px] font-mono border border-red-500/30 px-2 py-0.5 rounded-full bg-red-500/5">
                  <Lock size={9} /> VIP 专属
                </span>
              ) : undefined
            }
          />
          {!report.markdownContent || report.markdownContent.startsWith('报告内容正在同步中') ? (
            // 后端尚未生成报告：统一显示占位卡
            <PostMatchPlaceholder
              title="Report · Generating"
              icon={<FileText size={26} />}
            />
          ) : accessLevel === 'anonymous' ? (
            // Tier 1：匿名 → 截断 Paywall
            <PaywallOverlay />
          ) : (
            // Tier 2 (registered) + Tier 3 (vip/admin) 都走 ReportMarkdown
            // 内部 useSession + isVip 自行决定 VIP 分块是否模糊
            <ReportMarkdown content={report.markdownContent} />
          )}
        </div>

        {/* ── 5. 赛后复盘区 ───────────────────────────────────────────────── */}
        {/* 比赛已结束时始终渲染此区，VIP 看内容，非 VIP 看引导 */}
        {matchEnded && (
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-yellow-500/10 border border-yellow-500/20 w-fit">
              <span className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
              <span className="text-[10px] font-black text-yellow-400 tracking-widest uppercase">
                赛后复盘 · VIP 专属
              </span>
            </div>

            {/* 非 VIP 引导卡 */}
            {!isVip && (
              <div className="glass-panel border border-yellow-500/20 rounded-2xl p-6 flex flex-col items-center gap-3 text-center">
                <Lock size={24} className="text-yellow-400/60" />
                <p className="text-sm font-black text-white/60">赛后量化复盘 · 仅 VIP 可见</p>
                <p className="text-[11px] text-white/30 font-mono">包含模型回测、实际期望进球对比、AI 审计报告</p>
                <Link href="/pricing" className="mt-1 px-4 py-2 rounded-full bg-yellow-400/10 border border-yellow-400/30 text-yellow-400 text-[11px] font-black tracking-widest hover:bg-yellow-400/20 transition-all">
                  升级 VIP →
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

                <div className="glass-panel border border-white/5 rounded-2xl p-5 overflow-hidden">
                  <SectionLabel
                    icon={<Crosshair size={11} />}
                    label="Post-Match Shot Distribution · Real Match Data"
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

                <div className="glass-panel border border-white/5 rounded-2xl p-5 relative overflow-hidden">
                  <div className="absolute top-0 left-0 w-40 h-40 bg-yellow-400/5 blur-[60px] rounded-full pointer-events-none" />
                  <SectionLabel
                    icon={<BarChart2 size={11} />}
                    label="Post-Match Quantitative Debrief · AI Audit"
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
          </div>
        )}

      </div>

      {/* ── 底部固定栏 ────────────────────────────────────────────────────── */}
      <div className="fixed bottom-0 left-0 right-0 bg-[#0D0F14]/95 backdrop-blur-xl border-t border-white/10 px-4 pt-3 pb-6 z-50">
        <div className="max-w-2xl mx-auto flex items-center justify-between gap-4">
          <div className="min-w-0">
            <span className="block text-primary-neon text-[9px] font-bold uppercase tracking-wider mb-0.5">
              System Verdict
            </span>
            <span className="text-white font-black text-base uppercase tracking-tight truncate block">
              {verdict}
            </span>
          </div>
          {accessLevel !== 'vip' && (
            <Link
              href="/register"
              className="flex-shrink-0 flex items-center gap-1.5 px-5 py-2.5 rounded-xl text-sm font-bold
                         bg-gradient-to-r from-red-600 to-rose-500 text-white
                         shadow-[0_0_15px_rgba(239,68,68,0.4)]
                         hover:shadow-[0_0_25px_rgba(239,68,68,0.6)]
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
  const session = await auth();
  const role = (session?.user as any)?.role as string | undefined;
  const accessLevel: AccessLevel =
    !session?.user ? 'anonymous'
    : role === 'vip' || role === 'admin' ? 'vip'
    : 'registered';

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
    <main className="relative min-h-screen bg-[#0D0F14] text-white overflow-x-hidden w-full font-body selection:bg-primary-neon/20">
      <BackgroundEffects />

      <div className="relative z-10 w-full">

        {accessLevel === 'anonymous' ? (
          <>
            {/* 匿名用户：显示简单导航栏 + 登录提示 */}
            <header className="sticky top-0 z-40 bg-[#0D0F14]/80 backdrop-blur-md border-b border-white/5 px-4 py-3 flex items-center gap-3">
              <Link href="/" className="p-2 -ml-2 text-white/40 hover:text-primary-neon transition-colors flex-shrink-0 group">
                <ChevronLeft size={22} className="group-hover:-translate-x-0.5 transition-transform" />
              </Link>
              <div className="flex flex-col min-w-0">
                <span className="text-[9px] font-bold tracking-wider text-primary-neon uppercase">
                  QUANT ANALYSIS · FOOTBALL
                </span>
                <span className="text-sm font-black text-white/70 leading-tight">比赛研报</span>
              </div>
            </header>
            <div className="flex flex-col items-center justify-center py-32 px-4">
              <LoginPrompt matchId={matchId} />
            </div>
          </>
        ) : (
          <Suspense
            fallback={
              <div className="flex flex-col">
                {/* 加载中保留一个通用导航栏 */}
                <header className="sticky top-0 z-40 bg-[#0D0F14]/80 backdrop-blur-md border-b border-white/5 px-4 py-3 flex items-center gap-3">
                  <Link href="/" className="p-2 -ml-2 text-white/40 hover:text-primary-neon transition-colors flex-shrink-0">
                    <ChevronLeft size={22} />
                  </Link>
                  <div className="flex flex-col min-w-0">
                    <span className="text-[9px] font-bold tracking-wider text-primary-neon uppercase">
                      QUANT ANALYSIS · FOOTBALL
                    </span>
                    <span className="text-sm font-black text-white/70 leading-tight">比赛研报</span>
                  </div>
                </header>
                <div className="flex flex-col items-center justify-center py-60 gap-8">
                  <Activity size={40} className="text-primary-neon animate-spin" />
                  <p className="text-[11px] font-black text-primary-neon/40 uppercase tracking-[0.5em] animate-pulse">
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

        <footer className="mt-12 pt-8 border-t border-white/5 w-full max-w-2xl mx-auto px-4 flex justify-between items-center text-[9px] font-bold text-white/20 uppercase tracking-[0.3em]">
          <span>喵弟量化实验室 :: SYSTEM CORE v6.2.0</span>
          <span>STITCH PROTOCOL SECURED</span>
        </footer>
      </div>
    </main>
  );
}
