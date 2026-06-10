'use client';

import { Star, ChevronRight } from 'lucide-react';
import { MatchTimeDisplay } from '@/components/MatchTimeDisplay';
import { switchToProTab } from './ReportTabSwitch';
import { translateLeague } from '@/lib/leagueNames';
import { translateTeam } from '@/lib/teamNames';
import RecentStatCard from './RecentStatCard';
import type { BestRecentStat } from '@/types/report';

// ── Types ──────────────────────────────────────────────────────────────────
export type FormResult = 'W' | 'D' | 'L';

interface Props {
  matchId:               string;
  homeTeam:              string;
  awayTeam:              string;
  league?:               string;
  matchTime?:            string;
  homeIcon?:             string | null;
  awayIcon?:             string | null;
  homeProb?:             number | null;
  awayProb?:             number | null;
  drawProb?:             number | null;
  inference?:            string;          // raw inference string '【HIGH】主胜 @1.91 75.1%...'
  beginnerSummary?:      string | null;   // LLM-generated 大白话一句话
  // Mock-friendly fields (后续接入真实数据)
  homeRecentForm?:       FormResult[] | null;     // 主队近5场 ['W','W','D','W','L']
  awayRecentForm?:       FormResult[] | null;     // 客队近5场
  recentHitRate14d?:     number | null;           // 0-100, 71.4 (TODO: 后端接入)
  recentHitRate14dN?:    number | null;           // 14 (样本数)
  pipelineStatus?:       string | null;           // 'FINAL_REPORT_READY' → 显示 T-30 徽章
  /** 模块⑤战绩卡：4 窗口 × 2 类型择优后的最佳组合（None 时整张卡隐藏） */
  bestRecentStat?:       BestRecentStat | null;
}

// ── inference parsing ──────────────────────────────────────────────────────
// '【HIGH】主胜 @1.91 75.1%  (75.1%/18.6%/6.3%)'
function parseInference(inf?: string): {
  confidence: 'HIGH' | 'MEDIUM' | 'LOW' | null;
  direction:  string;
  odds:       string;
  pickProb:   number | null;   // 预测方向的模型概率（非 WDL 三分布）
} {
  if (!inf) return { confidence: null, direction: '', odds: '', pickProb: null };
  const confMatch = inf.match(/【(HIGH|MEDIUM|LOW)】/i);
  const confidence = (confMatch?.[1]?.toUpperCase() as 'HIGH' | 'MEDIUM' | 'LOW') ?? null;
  const rest = inf.replace(/【[^】]+】/, '').trim();
  const direction = rest.split('@')[0].trim().split(/\s+/)[0] ?? '';
  const oddsMatch = rest.match(/@\s*([\d.]+)/);
  // pickProb：去掉所有括号内容后取第一个 X%，避免 WDL 括号 (H%/D%/A%) 和 OU 括号 (>X) 干扰
  const noParens = rest.replace(/\([^)]+\)/g, '');
  const probMatch = noParens.match(/([\d.]+)%/);
  return {
    confidence,
    direction,
    odds: oddsMatch ? oddsMatch[1] : '',
    pickProb: probMatch ? parseFloat(probMatch[1]) : null,
  };
}
const STARS_FROM_CONF: Record<'HIGH' | 'MEDIUM' | 'LOW', number> = { HIGH: 5, MEDIUM: 3, LOW: 2 };

// AH/OU 预测类型判断（与 GlassPickBlock.getPickType 保持同步）
function getPickType(text: string | null | undefined): 'AH' | 'OU' | 'WDL' {
  if (!text) return 'WDL';
  const r = text.toLowerCase();
  if (r.includes('让') || r.includes('ah') || r.includes('handicap') || r.includes('覆盖')) return 'AH';
  if (r.includes('大球') || r.includes('小球') || r.includes('over') || r.includes('under') || r.includes('≤') || r.includes('≥')) return 'OU';
  return 'WDL';
}

// ── Helpers ────────────────────────────────────────────────────────────────
const formEmoji = (r: FormResult) => r === 'W' ? '✅' : r === 'L' ? '❌' : '🟰';

// ────────────────────────────────────────────────────────────────────────────
export default function BeginnerView({
  matchId, homeTeam, awayTeam, league, matchTime,
  homeIcon, awayIcon,
  homeProb, awayProb, drawProb,
  inference, beginnerSummary,
  homeRecentForm, awayRecentForm,
  recentHitRate14d, recentHitRate14dN,
  pipelineStatus,
  bestRecentStat,
}: Props) {
  const parsed       = parseInference(inference);
  const pickLabel    = translateTeam(parsed.direction);
  const pickType     = getPickType(inference);
  const stars        = parsed.confidence ? STARS_FROM_CONF[parsed.confidence] : 0;
  const hasProbs     = homeProb != null && awayProb != null;
  const dProb        = hasProbs
    ? (drawProb ?? Math.max(0, Math.round(100 - (homeProb as number) - (awayProb as number))))
    : null;
  // OU/AH 横条：从 inference 里的 pickProb 推导出双边数值
  const overProb: number | null = pickType === 'OU' && parsed.pickProb != null
    ? +(parsed.direction.includes('大球') ? parsed.pickProb : 100 - parsed.pickProb).toFixed(1)
    : null;
  const ahHomeCover: number | null = pickType === 'AH' && parsed.pickProb != null
    ? +(parsed.direction.includes('主让') ? parsed.pickProb : 100 - parsed.pickProb).toFixed(1)
    : null;

  // 一句话解读 fallback
  const oneLiner = beginnerSummary?.trim()
    ? beginnerSummary
    : (parsed.direction
        ? `本场预测方向：${pickLabel}${parsed.odds ? `，市场价格 @${parsed.odds}` : ''}${stars ? `，信心 ${stars}星` : ''}。`
        : '本场分析数据准备中…');

  return (
    <div className="px-4 pt-4 pb-10 max-w-2xl mx-auto flex flex-col gap-4 overflow-x-hidden">

      {/* ─── ① 对阵卡 + 双方近5场战绩 ─────────────────────────────── */}
      <section className="bg-white/85 backdrop-blur-xl dark:bg-[var(--panel-bg-strong)]
                          border border-slate-900/10 dark:border-[var(--panel-border-strong)]
                          rounded-3xl p-5 text-center space-y-3
                          shadow-[0_4px_24px_rgba(15,23,42,0.06)] dark:shadow-[var(--panel-shadow-strong)]">
        {league && (
          <span className="inline-block text-xs font-bold tracking-[0.15em] uppercase px-3 py-1 rounded-full
                           bg-slate-900 text-white
                           dark:bg-white/[0.06] dark:text-white dark:border dark:border-white/15">
            {translateLeague(league)}
            {matchTime && <span className="ml-2 opacity-70 normal-case tracking-wider">· <MatchTimeDisplay utcStr={matchTime} /></span>}
          </span>
        )}
        <div className="flex items-center justify-center gap-3">
          {homeIcon && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={homeIcon} alt={homeTeam} width={44} height={44}
              className="object-contain flex-shrink-0 ring-1 ring-black/8 rounded-full bg-white p-0.5" />
          )}
          <h2 className="text-xl font-black text-slate-900 dark:text-white leading-tight">
            {homeTeam}
            <span className="mx-2 text-sm font-semibold text-slate-500 dark:text-white/60">vs</span>
            {awayTeam}
          </h2>
          {awayIcon && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={awayIcon} alt={awayTeam} width={44} height={44}
              className="object-contain flex-shrink-0 ring-1 ring-black/8 rounded-full bg-white p-0.5" />
          )}
        </div>

        {(homeRecentForm?.length || awayRecentForm?.length) ? (
          <div className="grid grid-cols-2 gap-3 pt-2 border-t border-slate-900/8 dark:border-white/8 mt-3">
            <FormColumn label={homeTeam} form={homeRecentForm ?? []} />
            <FormColumn label={awayTeam} form={awayRecentForm ?? []} />
          </div>
        ) : null}
      </section>

      {/* ─── ② 🎯 分析卡（首屏视觉重心）────────────────────────────── */}
      {parsed.direction ? (
        <section className="relative overflow-hidden rounded-3xl p-6
          bg-gradient-to-br from-[#E91E63]/8 via-white to-white
          dark:from-[#00F0FF]/8 dark:via-[#06080C] dark:to-[#06080C]
          border-2 border-[#E91E63]/30 dark:border-[#00F0FF]/30
          shadow-[0_8px_32px_rgba(233,30,99,0.12)] dark:shadow-[0_0_32px_rgba(0,240,255,0.12)]">
          <div className="absolute -top-16 -right-16 w-44 h-44 rounded-full bg-[#E91E63]/10 dark:bg-[#00F0FF]/10 blur-3xl pointer-events-none" />

          <div className="relative flex items-center justify-between gap-2 mb-3">
            <div className="flex items-center gap-2">
              <span className="text-xs font-black tracking-[0.25em] uppercase
                               text-[#E91E63] dark:text-[#00F0FF]">🎯 模型分析</span>
              <span className="text-xs font-bold px-1.5 py-0.5 rounded-full
                               bg-[#E91E63]/10 text-[#E91E63] dark:bg-[#00F0FF]/10 dark:text-[#00F0FF]
                               border border-[#E91E63]/20 dark:border-[#00F0FF]/20">
                {pickType === 'AH' ? '亚盘' : pickType === 'OU' ? '进球数' : '赛果'}
              </span>
            </div>
            {pipelineStatus === 'FINAL_REPORT_READY' && (
              <span className="inline-flex items-center gap-1 text-xs font-black tracking-widest uppercase
                               px-2 py-0.5 rounded-full
                               bg-emerald-500/15 text-emerald-700 border border-emerald-500/30
                               dark:bg-emerald-400/10 dark:text-emerald-300 dark:border-emerald-400/30">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                T-30 闭盘定稿
              </span>
            )}
          </div>

          <div className="relative flex items-end justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[32px] sm:text-4xl font-black tracking-tighter text-slate-900 dark:text-white leading-none">
                {pickLabel}
              </div>
              {parsed.odds && (
                <div className="flex items-baseline gap-1.5 mt-2.5">
                  <span className="text-xs font-bold text-slate-500 dark:text-white/50 uppercase tracking-widest">参考市场价格</span>
                  <span className="text-[18px] font-black text-[#E91E63] dark:text-[#00F0FF]">
                    @{parsed.odds}
                  </span>
                </div>
              )}
            </div>
            <div className="flex flex-col items-end gap-1.5 flex-shrink-0">
              {stars > 0 && (
                <div className="flex items-center gap-0.5">
                  {[1, 2, 3, 4, 5].map(i => (
                    <Star key={i} size={14}
                      className={i <= stars ? 'fill-[#FFB800] text-[#FFB800]' : 'text-slate-300 dark:text-white/15'} />
                  ))}
                </div>
              )}
              {(recentHitRate14d != null) && (
                <div className="text-right">
                  <span className="text-xs font-bold text-slate-500 dark:text-white/50 tracking-wider mr-1">近14天命中率</span>
                  <span className="text-[14px] font-black text-slate-900 dark:text-white tabular-nums">
                    {recentHitRate14d.toFixed(1)}%
                  </span>
                </div>
              )}
            </div>
          </div>
        </section>
      ) : (
        <section className="rounded-3xl p-6 text-center
                            bg-white/60 dark:bg-white/[0.03]
                            border border-slate-200 dark:border-white/10">
          <p className="text-sm font-bold text-slate-600 dark:text-white/60">模型分析数据准备中…</p>
        </section>
      )}

      {/* ─── ③ 概率横条图（AH/OU/WDL 动态切换）───────────────────── */}
      {(pickType === 'WDL' ? hasProbs : parsed.pickProb != null) && (
        <section className="bg-white/85 backdrop-blur-xl dark:bg-[var(--panel-bg-strong)]
                            border border-slate-900/10 dark:border-[var(--panel-border-strong)]
                            rounded-2xl p-5">
          <p className="text-xs font-black tracking-[0.25em] uppercase text-slate-700 dark:text-white/80 mb-4">
            {pickType === 'AH' ? '📊 亚盘覆盖概率' : pickType === 'OU' ? '📊 进球数概率' : '📊 三种结果概率'}
          </p>
          <div className="space-y-3">
            {pickType === 'OU' ? (
              <>
                <ProbBar label="大球" value={overProb as number}
                  activeClass="bg-[#005faf] dark:bg-[#00F0FF]"
                  activeText="text-[#005faf] dark:text-[#00F0FF]"
                  highlight={parsed.direction.includes('大球')} />
                <ProbBar label="小球" value={+((100 - (overProb as number)).toFixed(1))}
                  activeClass="bg-[#b7004d] dark:bg-[#FF00E5]"
                  activeText="text-[#b7004d] dark:text-[#FF00E5]"
                  highlight={parsed.direction.includes('小球')} />
              </>
            ) : pickType === 'AH' ? (
              <>
                <ProbBar label="主队覆盖" value={ahHomeCover as number}
                  activeClass="bg-[#005faf] dark:bg-[#00F0FF]"
                  activeText="text-[#005faf] dark:text-[#00F0FF]"
                  highlight={parsed.direction.includes('主让')} />
                <ProbBar label="客队覆盖" value={+((100 - (ahHomeCover as number)).toFixed(1))}
                  activeClass="bg-[#b7004d] dark:bg-[#FF00E5]"
                  activeText="text-[#b7004d] dark:text-[#FF00E5]"
                  highlight={parsed.direction.includes('客让')} />
              </>
            ) : (
              <>
                <ProbBar label="主胜" value={homeProb as number}
                  activeClass="bg-[#005faf] dark:bg-[#00F0FF]"
                  activeText="text-[#005faf] dark:text-[#00F0FF]"
                  highlight={parsed.direction.includes('主胜')} />
                <ProbBar label="平局" value={dProb as number}
                  activeClass="bg-slate-500 dark:bg-white/50"
                  activeText="text-slate-700 dark:text-white"
                  highlight={parsed.direction === '平局' || parsed.direction === '平'} />
                <ProbBar label="客胜" value={awayProb as number}
                  activeClass="bg-[#b7004d] dark:bg-[#FF00E5]"
                  activeText="text-[#b7004d] dark:text-[#FF00E5]"
                  highlight={parsed.direction.includes('客胜')} />
              </>
            )}
          </div>
        </section>
      )}

      {/* ─── ④ 💡 一句话解读 ────────────────────────────────────── */}
      <section className="bg-gradient-to-br from-amber-50 to-white
                          dark:from-amber-500/5 dark:to-transparent
                          border border-amber-200/60 dark:border-amber-400/20
                          rounded-2xl p-4">
        <div className="flex items-start gap-2.5">
          <span className="text-lg leading-none mt-0.5">💡</span>
          <p className="flex-1 text-[15px] leading-relaxed text-slate-800 dark:text-white/90">{oneLiner}</p>
        </div>
      </section>

      {/* ─── ⑤ 📊 近期战绩卡（Spread/进球数择优）─────────────────── */}
      <RecentStatCard stat={bestRecentStat} />

      {/* ─── ⑥ → 切换到专业版 CTA ───────────────────────────────── */}
      <button
        type="button"
        onClick={switchToProTab}
        className="group flex items-center justify-between p-5 rounded-2xl text-left
                   bg-gradient-to-r from-slate-900 to-slate-800 text-white
                   dark:from-[#00F0FF]/10 dark:to-[#00F0FF]/5 dark:border dark:border-[#00F0FF]/30
                   shadow-[0_4px_16px_rgba(15,23,42,0.18)] dark:shadow-none
                   active:scale-[0.99] transition-transform">
        <div className="min-w-0">
          <p className="text-xs font-black tracking-[0.3em] uppercase text-white/50 dark:text-[#00F0FF]/70 mb-1">想看完整数据分析？</p>
          <p className="text-base font-black text-white dark:text-[#00F0FF]">查看专业版</p>
          <p className="text-xs text-white/60 dark:text-white/50 mt-0.5">射门图 · 阵容对比 · 球员矩阵 · 深度研报</p>
        </div>
        <ChevronRight size={28} className="text-white/70 dark:text-[#00F0FF]/70 group-hover:translate-x-1 transition-transform flex-shrink-0" />
      </button>

    </div>
  );
}

// ── Subcomponents ──────────────────────────────────────────────────────────

function FormColumn({ label, form }: { label: string; form: FormResult[] }) {
  if (!form.length) {
    return (
      <div className="text-center">
        <p className="text-xs text-slate-500 dark:text-white/40 mb-1.5 truncate">{label}</p>
        <p className="text-xs text-slate-400 dark:text-white/30">近期战绩待同步</p>
      </div>
    );
  }
  return (
    <div className="text-center">
      <p className="text-xs font-bold text-slate-500 dark:text-white/50 mb-1.5 truncate uppercase tracking-wider">{label} · 近5场</p>
      <div className="flex items-center justify-center gap-1 text-[16px] leading-none">
        {form.map((r, i) => <span key={i}>{formEmoji(r)}</span>)}
      </div>
    </div>
  );
}

function ProbBar({
  label, value, activeClass, activeText, highlight,
}: { label: string; value: number; activeClass: string; activeText: string; highlight?: boolean }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className={`text-sm font-black ${highlight ? activeText : 'text-slate-700 dark:text-white/70'}`}>
          {label}
          {highlight && (
            <span className="ml-2 text-xs font-black tracking-widest px-1.5 py-0.5 rounded-full
                             bg-[#E91E63]/15 text-[#E91E63] dark:bg-[#00F0FF]/15 dark:text-[#00F0FF] uppercase">
              最优
            </span>
          )}
        </span>
        <span className={`text-sm font-black tabular-nums ${activeText}`}>{value.toFixed(1)}%</span>
      </div>
      <div className="h-2.5 w-full rounded-full overflow-hidden bg-slate-200 dark:bg-white/8">
        <div
          className={`h-full rounded-full ${highlight ? activeClass : 'bg-slate-300 dark:bg-white/15'} transition-all duration-700`}
          style={{ width: `${Math.min(100, value)}%` }}
        />
      </div>
    </div>
  );
}
