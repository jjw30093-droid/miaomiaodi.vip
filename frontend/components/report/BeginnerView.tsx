'use client';

import { ChevronRight } from 'lucide-react';
import { MatchTimeDisplay } from '@/components/MatchTimeDisplay';
import { switchToProTab } from './ReportTabSwitch';
import { translateLeague } from '@/lib/leagueNames';
import { translateTeamsInText } from '@/lib/teamNames';
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
  confidence: string | null;
  direction:  string;
  odds:       string;
  pickProb:   number | null;   // 预测方向的模型概率（非 WDL 三分布）
} {
  if (!inf) return { confidence: null, direction: '', odds: '', pickProb: null };
  const confMatch = inf.match(/【([^】]+)】/);
  const confidence = confMatch?.[1] ?? null;
  const rest = inf.replace(/【[^】]+】/, '').trim();
  // @ 前的完整方向标签（与 GlassPickBlock 一致）。不能再 split(/\s+/)[0] 截首词，
  // 否则 "2.25 小球" 这类带空格的大小球方向会被截成 "2.25"，丢掉 小球/大球。
  const direction = rest.split('@')[0].trim();
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

function formatConfidence(confidence: string | null): string {
  if (!confidence) return '—';
  const raw = confidence.toUpperCase();
  if (raw === 'HIGH') return '高';
  if (raw === 'MEDIUM' || raw === 'MID') return '中';
  if (raw === 'LOW') return '谨慎';
  return confidence.replace(/把握/g, '');
}

// AH/OU 预测类型判断（与 GlassPickBlock.getPickType 保持同步）
function getPickType(text: string | null | undefined): 'AH' | 'OU' | 'WDL' {
  if (!text) return 'WDL';
  const r = text.toLowerCase();
  if (r.includes('让') || r.includes('ah') || r.includes('handicap') || r.includes('覆盖')) return 'AH';
  if (r.includes('大球') || r.includes('小球') || r.includes('over') || r.includes('under') || r.includes('≤') || r.includes('≥')) return 'OU';
  return 'WDL';
}

// ── Helpers ────────────────────────────────────────────────────────────────
const formLabel = (r: FormResult) => r === 'W' ? '胜' : r === 'L' ? '负' : '平';
const CARD = 'rounded-lg border border-slate-200 dark:border-white/15 bg-white dark:bg-slate-950 shadow-sm dark:shadow-none';

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
  const pickLabel    = translateTeamsInText(parsed.direction);
  const pickType     = getPickType(inference);
  const strengthLabel = formatConfidence(parsed.confidence);
  const pickTypeLabel = pickType === 'AH' ? '让球方向' : pickType === 'OU' ? '进球数方向' : '赛果方向';
  const hasProbs     = homeProb != null && awayProb != null;
  const dProb        = hasProbs
    ? (drawProb ?? Math.max(0, Math.round(100 - (homeProb as number) - (awayProb as number))))
    : null;
  // OU/AH 横条：从 inference 里的 pickProb 推导出双边数值
  const overProb: number | null = pickType === 'OU' && parsed.pickProb != null
    ? +(parsed.direction.includes('大球') ? parsed.pickProb : 100 - parsed.pickProb).toFixed(1)
    : null;
  const isAhHomeDirection = parsed.direction.includes('主让') || parsed.direction.includes('主受') || parsed.direction.includes('主队');
  const isAhAwayDirection = parsed.direction.includes('客让') || parsed.direction.includes('客受') || parsed.direction.includes('客队');
  const ahHomeCover: number | null = pickType === 'AH' && parsed.pickProb != null
    ? +(isAhHomeDirection ? parsed.pickProb : 100 - parsed.pickProb).toFixed(1)
    : null;

  // 一句话解读 fallback
  const oneLiner = beginnerSummary?.trim()
    ? beginnerSummary
    : (parsed.direction
        ? `本场推荐方向：${pickLabel}${parsed.odds ? `，参考价格 @${parsed.odds}` : ''}${parsed.confidence ? `，推荐强度：${strengthLabel}` : ''}。`
        : '本场分析数据准备中…');

  return (
    <div className="px-4 pt-4 pb-10 max-w-2xl mx-auto flex flex-col gap-4 overflow-x-hidden">

      {/* ─── ① 对阵卡 + 双方近5场战绩 ─────────────────────────────── */}
      <section className={`${CARD} p-5`}>
        <div className="flex items-start justify-between gap-3 mb-5">
          <div className="text-[15px] font-bold text-slate-800 dark:text-slate-100">
            {league ? translateLeague(league) : '比赛研报'}
          </div>
          {matchTime && (
            <div className="text-right text-[14px] font-bold text-slate-700 dark:text-slate-200">
              <MatchTimeDisplay utcStr={matchTime} />
            </div>
          )}
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)_36px_minmax(0,1fr)] items-center gap-3">
          <TeamBlock name={homeTeam} icon={homeIcon} />
          <div className="text-center text-[15px] font-bold text-slate-500 dark:text-slate-300">vs</div>
          <TeamBlock name={awayTeam} icon={awayIcon} />
        </div>

        {(homeRecentForm?.length || awayRecentForm?.length) ? (
          <div className="grid grid-cols-2 gap-3 pt-4 border-t border-slate-200 dark:border-white/15 mt-5">
            <FormColumn label={homeTeam} form={homeRecentForm ?? []} />
            <FormColumn label={awayTeam} form={awayRecentForm ?? []} />
          </div>
        ) : null}
      </section>

      {/* ─── ② 推荐方向（首屏视觉重心）────────────────────────────── */}
      {parsed.direction ? (
        <section className="rounded-lg border-2 border-slate-900 dark:border-white bg-white dark:bg-slate-950 shadow-sm p-5">
          <div className="flex items-start justify-between gap-3 border-b border-slate-200 dark:border-white/15 pb-3">
            <div>
              <p className="text-[16px] font-bold text-slate-950 dark:text-white">推荐方向</p>
              <p className="mt-1 text-[13px] font-bold text-slate-600 dark:text-slate-300">{pickTypeLabel}</p>
            </div>
            {pipelineStatus === 'FINAL_REPORT_READY' && (
              <span className="text-[13px] font-bold text-emerald-700 dark:text-emerald-300">
                已定稿
              </span>
            )}
          </div>

          <div className="pt-4">
            <div className="text-[36px] font-black text-slate-950 dark:text-white leading-tight break-words">
              {pickLabel}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3">
              {parsed.odds && (
                <div className="rounded-md bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-white/15 px-3 py-2">
                  <p className="text-[13px] font-bold text-slate-600 dark:text-slate-300">参考价格</p>
                  <p className="mt-1 text-[18px] font-black text-slate-950 dark:text-white">@{parsed.odds}</p>
                </div>
              )}
              <div className="rounded-md bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-white/15 px-3 py-2">
                <p className="text-[13px] font-bold text-slate-600 dark:text-slate-300">推荐强度</p>
                <p className="mt-1 text-[18px] font-black text-slate-950 dark:text-white">{strengthLabel}</p>
              </div>
              {recentHitRate14d != null && (
                <div className="rounded-md bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-white/15 px-3 py-2 col-span-2">
                  <p className="text-[13px] font-bold text-slate-600 dark:text-slate-300">
                    近14天同类样本
                    {recentHitRate14dN != null ? `（${recentHitRate14dN}场）` : ''}
                  </p>
                  <p className="mt-1 text-[18px] font-black text-slate-950 dark:text-white">
                    {recentHitRate14d.toFixed(1)}%
                  </p>
                </div>
              )}
            </div>
            <p className="mt-4 text-[17px] leading-[1.75] text-slate-950 dark:text-white">
              {oneLiner}
            </p>
          </div>
        </section>
      ) : (
        <section className={`${CARD} p-5 text-center`}>
          <p className="text-[16px] font-bold text-slate-700 dark:text-slate-200">分析数据准备中</p>
        </section>
      )}

      {/* ─── ③ 概率横条图（AH/OU/WDL 动态切换）───────────────────── */}
      {(pickType === 'WDL' ? hasProbs : parsed.pickProb != null) && (
        <section className={`${CARD} p-5`}>
          <p className="text-[18px] font-bold text-slate-950 dark:text-white mb-4 border-b border-slate-200 dark:border-white/15 pb-3">
            {pickType === 'AH' ? '让球概率参考' : pickType === 'OU' ? '进球数概率参考' : '三种结果概率'}
          </p>
          <div className="space-y-3">
            {pickType === 'OU' ? (
              <>
                <ProbBar label="大球" value={overProb as number}
                  highlight={parsed.direction.includes('大球')} />
                <ProbBar label="小球" value={+((100 - (overProb as number)).toFixed(1))}
                  highlight={parsed.direction.includes('小球')} />
              </>
            ) : pickType === 'AH' ? (
              <>
                <ProbBar label="主队方向" value={ahHomeCover as number}
                  highlight={isAhHomeDirection} />
                <ProbBar label="客队方向" value={+((100 - (ahHomeCover as number)).toFixed(1))}
                  highlight={isAhAwayDirection} />
              </>
            ) : (
              <>
                <ProbBar label="主胜" value={homeProb as number}
                  highlight={parsed.direction.includes('主胜')} />
                <ProbBar label="平局" value={dProb as number}
                  highlight={parsed.direction === '平局' || parsed.direction === '平'} />
                <ProbBar label="客胜" value={awayProb as number}
                  highlight={parsed.direction.includes('客胜')} />
              </>
            )}
          </div>
        </section>
      )}

      {/* ─── ④ 近期战绩卡 ─────────────────── */}
      <RecentStatCard stat={bestRecentStat} />

      {/* ─── ⑤ 切换到专业版 CTA ───────────────────────────────── */}
      <button
        type="button"
        onClick={switchToProTab}
        className={`${CARD} group flex w-full items-center justify-between gap-4 p-5 text-left active:scale-[0.99] transition-transform`}>
        <div className="min-w-0">
          <p className="text-[17px] font-bold text-slate-950 dark:text-white">查看完整研报</p>
          <p className="text-[14px] text-slate-700 dark:text-slate-200 mt-1">盘口变化、过程数据、风险点都在完整研报里。</p>
        </div>
        <ChevronRight size={24} className="text-slate-700 dark:text-slate-200 group-hover:translate-x-1 transition-transform flex-shrink-0" />
      </button>

    </div>
  );
}

// ── Subcomponents ──────────────────────────────────────────────────────────

function TeamBlock({ name, icon }: { name: string; icon?: string | null }) {
  return (
    <div className="min-w-0 flex flex-col items-center gap-2 text-center">
      {icon && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={icon}
          alt={name}
          width={48}
          height={48}
          className="h-12 w-12 object-contain flex-shrink-0 rounded-full bg-white p-1 ring-1 ring-slate-200"
        />
      )}
      <p className="max-w-full text-[20px] font-black leading-tight text-slate-950 dark:text-white break-words">
        {name}
      </p>
    </div>
  );
}

function FormColumn({ label, form }: { label: string; form: FormResult[] }) {
  if (!form.length) {
    return (
      <div className="text-center">
        <p className="text-[13px] font-bold text-slate-700 dark:text-slate-200 mb-1.5 truncate">{label}</p>
        <p className="text-[13px] text-slate-500 dark:text-slate-300">近期战绩待同步</p>
      </div>
    );
  }
  return (
    <div className="text-center">
      <p className="text-[13px] font-bold text-slate-700 dark:text-slate-200 mb-2 truncate">{label} · 近5场</p>
      <div className="flex items-center justify-center gap-1">
        {form.map((r, i) => (
          <span
            key={i}
            className="inline-flex h-7 w-7 items-center justify-center rounded border border-slate-200 dark:border-white/15 bg-slate-50 dark:bg-slate-900 text-[13px] font-bold text-slate-900 dark:text-white"
          >
            {formLabel(r)}
          </span>
        ))}
      </div>
    </div>
  );
}

function ProbBar({
  label, value, highlight,
}: { label: string; value: number; highlight?: boolean }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[15px] font-bold text-slate-900 dark:text-white">
          {label}
          {highlight && (
            <span className="ml-2 text-[13px] font-bold px-2 py-0.5 rounded bg-slate-900 text-white dark:bg-white dark:text-slate-950">
              推荐
            </span>
          )}
        </span>
        <span className="text-[15px] font-black tabular-nums text-slate-950 dark:text-white">{value.toFixed(1)}%</span>
      </div>
      <div className="h-3 w-full rounded-full overflow-hidden bg-slate-200 dark:bg-slate-800">
        <div
          className={`h-full rounded-full ${highlight ? 'bg-slate-900 dark:bg-white' : 'bg-slate-400 dark:bg-slate-500'} transition-all duration-700`}
          style={{ width: `${Math.min(100, value)}%` }}
        />
      </div>
    </div>
  );
}
