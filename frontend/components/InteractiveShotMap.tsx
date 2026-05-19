"use client";
import React, { useState, useMemo, useEffect } from "react";
import { useTheme } from "@/components/ThemeProvider";
import { TeamShotHistory, MatchShotData, Shot } from "@/types/report";
import { Maximize2, X } from "lucide-react";

/* ─── 情景标签中文映射 ─────────────────────────────── */
const SITUATION_LABELS: Record<string, string> = {
  RegularPlay:      "常规进攻",
  FromCorner:       "角球",
  SetPiece:         "定位球",
  FastBreak:        "快速反击",
  FreeKick:         "任意球",
  ThrowInSetPiece:  "界外球",
  Penalty:          "点球",
  IndividualPlay:   "个人突破",
};
const situationLabel = (k: string) => SITUATION_LABELS[k] ?? k;

/* ─── Outcome 颜色 ───────────────────────────────────
   Goal=绿, AttemptSaved=青, Miss=品红, Post=琥珀, 未知=灰 */
const OUTCOME_COLOR_DARK: Record<string, string> = {
  Goal:         "#22c55e",
  AttemptSaved: "#00F0FF",
  Miss:         "#FF00E5",
  Post:         "#f59e0b",
};
const OUTCOME_COLOR_LIGHT: Record<string, string> = {
  Goal:         "#22c55e",
  AttemptSaved: "#1a56db",
  Miss:         "#ef4444",
  Post:         "#f59e0b",
};
const outcomeColor = (o: string, isDark: boolean) =>
  (isDark ? OUTCOME_COLOR_DARK : OUTCOME_COLOR_LIGHT)[o] ?? (isDark ? "#6b7280" : "#374151");
const outcomeChinese: Record<string, string> = {
  Goal:         "进球",
  AttemptSaved: "扑出",
  Miss:         "偏出",
  Post:         "门柱",
};

/* ─── 球场 SVG 尺寸（1 meter = 5 px）─────────────────
   半场：X 从 52.5（中线顶部）到 105（底线/球门线）= 52.5m → 262.5px 高
   宽度：Y 从 0 到 68 = 68m → 340px 宽                              */
const SCALE     = 5;
const VB_W      = 68   * SCALE;   // 340
const VB_H      = 52.5 * SCALE;   // 262.5
const X_OFFSET  = 52.5;           // 半场起始坐标

/** 将数据库坐标转换为 SVG 坐标 */
const toSvgX = (y_coord: number) => y_coord * SCALE;
const toSvgY = (x_coord: number) => (x_coord - X_OFFSET) * SCALE;

/** 根据 xG 计算圆点半径 */
const xgRadius = (xg: number) => Math.min(14, Math.max(4, 4 + xg * 80));

/* ─── 球场线条 SVG 组件 ──────────────────────────── */
function PitchLines({ isDark }: { isDark: boolean }) {
  const lc = isDark ? '#ffffff' : '#000000';
  const sw = 1.8;
  const s  = { stroke: lc, strokeWidth: sw, fill: 'none' as const };

  // 禁区 (Penalty Area): X 88.5→105, Y 13.84→54.16
  const paX = toSvgX(13.84);
  const paY = toSvgY(88.5);
  const paW = (54.16 - 13.84) * SCALE;
  const paH = (105   - 88.5)  * SCALE;

  // 小禁区 (Goal Area): X 99.5→105, Y 24.84→43.16
  const gaX = toSvgX(24.84);
  const gaY = toSvgY(99.5);
  const gaW = (43.16 - 24.84) * SCALE;
  const gaH = (105   - 99.5)  * SCALE;

  // 罚球点 (94.5, 34)
  const spotCX = toSvgX(34);
  const spotCY = toSvgY(94.5);

  // 罚球弧 center + radius
  const arcR  = 9.15 * SCALE;
  const arcCX = toSvgX(34);
  const arcCY = toSvgY(94.5);
  const arcDy = arcCY - paY;
  const arcDx = Math.sqrt(Math.max(0, arcR * arcR - arcDy * arcDy));
  const arcX1 = arcCX - arcDx;
  const arcX2 = arcCX + arcDx;

  // 球门 (Goal): Y 30.34→37.66, at bottom of pitch
  const goalX1   = toSvgX(30.34);
  const goalX2   = toSvgX(37.66);
  const goalDepth = 12;

  return (
    <g>
      {/* 外边界 */}
      <rect x={0} y={0} width={VB_W} height={VB_H} {...s} />
      {/* 禁区 */}
      <rect x={paX} y={paY} width={paW} height={paH} {...s} />
      {/* 小禁区 */}
      <rect x={gaX} y={gaY} width={gaW} height={gaH} {...s} />
      {/* 罚球点 */}
      <circle cx={spotCX} cy={spotCY} r={2.5} fill={lc} />
      {/* 罚球弧（禁区外部分） */}
      {arcDx > 0 && (
        <path d={`M ${arcX1} ${paY} A ${arcR} ${arcR} 0 0 1 ${arcX2} ${paY}`} {...s} />
      )}
      {/* 球门框：左柱 / 右柱 / 门后横梁 */}
      <line x1={goalX1} y1={VB_H} x2={goalX1} y2={VB_H + goalDepth} stroke={lc} strokeWidth={sw + 0.7} strokeLinecap="round" />
      <line x1={goalX2} y1={VB_H} x2={goalX2} y2={VB_H + goalDepth} stroke={lc} strokeWidth={sw + 0.7} strokeLinecap="round" />
      <line x1={goalX1} y1={VB_H + goalDepth} x2={goalX2} y2={VB_H + goalDepth} stroke={lc} strokeWidth={sw} strokeLinecap="round" />
    </g>
  );
}

/* ─── 射门圆点（全量渲染，用 opacity transition 丝滑隐显）───
   ★ 多个射门同坐标时聚合显示：单个圆 + 中心数字 + tooltip 列出全部
   典型场景：FotMob 把所有点球都标记在 (94.0, 34.0) 同一坐标，导致 8 个进球重叠成 1 点 */
function ShotDots({
  allShots,
  displayedSet,
  isDark,
}: {
  allShots: Shot[];
  displayedSet: Set<Shot>;
  isDark: boolean;
}) {
  // 过滤掉半场外的射门（X < 52.5）
  // 同时过滤掉点球大战（PenaltyShootout）— J联赛本赛季打平直接互射点球，
  // FotMob 把点球大战的射门和正常比赛点球混在 fact_shotmap 里都标 Situation=Penalty 坐标 (94,34)，
  // 不剔除会导致进球数虚高、(94,34) 点球点严重重叠。
  const inHalf = useMemo(
    () => allShots.filter(s => s.x >= X_OFFSET && s.period !== 'PenaltyShootout'),
    [allShots]
  );

  // 把当前可见射门按坐标 (x.toFixed(2), y.toFixed(2)) 分组
  // 注意：只对当前可见的射门聚类，被过滤掉的不参与聚合
  const visibleClusters = useMemo(() => {
    const groups: Record<string, Shot[]> = {};
    inHalf.forEach(s => {
      if (!displayedSet.has(s)) return;
      const key = `${s.x.toFixed(2)},${s.y.toFixed(2)}`;
      (groups[key] ||= []).push(s);
    });
    return Object.entries(groups)
      .filter(([, shots]) => shots.length > 1)
      .map(([key, shots]) => ({ key, shots }));
  }, [inHalf, displayedSet]);

  // 已加入聚合的射门集合：这些射门个体不再单独渲染
  const clusteredShots = useMemo(() => {
    const set = new Set<Shot>();
    visibleClusters.forEach(c => c.shots.forEach(s => set.add(s)));
    return set;
  }, [visibleClusters]);

  return (
    <g>
      {/* ① 单点射门：原样渲染（含被过滤掉的，opacity=0） */}
      {inHalf.map((s, i) => {
        const cx = toSvgX(s.y);
        const cy = toSvgY(s.x);
        const r  = xgRadius(s.xg);
        const color = outcomeColor(s.outcome, isDark);
        const isGoal = s.outcome === "Goal";
        // 隐藏条件：被结果/情景/半场过滤掉，或已被聚合替代
        const isVisible = displayedSet.has(s) && !clusteredShots.has(s);
        return (
          <g
            key={`shot-${i}`}
            style={{
              opacity: isVisible ? 1 : 0,
              transition: 'opacity 300ms ease',
            }}
          >
            <circle
              cx={cx} cy={cy} r={r}
              fill={isGoal ? color : "transparent"}
              stroke={isGoal ? (isDark ? "#0F172A" : "#15803d") : color}
              strokeWidth={isGoal ? 1 : 1.5}
              opacity={isGoal ? 1 : 0.85}
            >
              <title>
                {s.player ? `${s.player} ` : ""}
                {outcomeChinese[s.outcome] ?? s.outcome}
                {s.xg > 0 ? ` xG:${s.xg.toFixed(2)}` : ""}
                {s.minute ? ` ${s.minute}'` : ""}
              </title>
            </circle>
          </g>
        );
      })}

      {/* ② 聚合点：≥2 个同坐标射门，画一个加大圆 + 中心数字 */}
      {visibleClusters.map(c => {
        const first = c.shots[0];
        const cx = toSvgX(first.y);
        const cy = toSvgY(first.x);
        const cnt = c.shots.length;
        const goals  = c.shots.filter(s => s.outcome === "Goal").length;
        const isAllGoals = goals === cnt;
        // 主色：全是进球用绿；混合用列表第一个 outcome
        const dominantOutcome = isAllGoals ? "Goal" : first.outcome;
        const color = outcomeColor(dominantOutcome, isDark);
        // 半径：基础 8 + sqrt(N) * 3，封顶 22 防止盖到禁区线外
        const r = Math.min(22, 8 + Math.sqrt(cnt) * 3);
        // 数字字号：占圆直径约 70%，最小 9 最大 16
        const fontSize = Math.max(9, Math.min(16, r * 1.1));

        // tooltip：列出每个射门的简要信息（最多 6 条避免太长）
        const tipLines = c.shots.slice(0, 6).map(s => {
          const parts = [
            s.player || "",
            outcomeChinese[s.outcome] ?? s.outcome,
            s.minute ? `${s.minute}'` : "",
          ].filter(Boolean);
          return parts.join(" ");
        });
        const tipExtra = c.shots.length > 6 ? `\n…还有 ${c.shots.length - 6} 条` : "";
        const situationTag = first.situation === "Penalty" ? "（点球点）" : "";

        return (
          <g
            key={`cluster-${c.key}`}
            style={{
              opacity: 1,
              transition: 'opacity 300ms ease',
            }}
          >
            <circle
              cx={cx} cy={cy} r={r}
              fill={isAllGoals ? color : (isDark ? "rgba(0,0,0,0.85)" : "rgba(255,255,255,0.95)")}
              stroke={isAllGoals ? (isDark ? "#0F172A" : "#15803d") : color}
              strokeWidth={2}
              opacity={1}
            />
            <text
              x={cx} y={cy}
              textAnchor="middle"
              dominantBaseline="central"
              fontSize={fontSize}
              fontWeight={900}
              fill={isAllGoals ? (isDark ? "#0F172A" : "#ffffff") : color}
              style={{ pointerEvents: 'none', fontFamily: 'monospace' }}
            >
              {cnt}
            </text>
            <title>
              {`${cnt} 次同位置射门${situationTag}${goals > 0 ? `（${goals} 球进）` : ""}\n` + tipLines.join("\n") + tipExtra}
            </title>
          </g>
        );
      })}
    </g>
  );
}

/* ─── 场次选择器 Pill ────────────────────────────── */
function MatchPill({
  label, count, selected, onClick,
}: { label: string; count: number; selected: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`
        flex-shrink-0 flex items-center gap-2 px-4 py-2 rounded-full
        text-sm font-display font-bold transition-all duration-200
        ${selected
          ? "bg-primary-neon/20 border border-primary-neon text-primary-neon shadow-[0_0_8px_rgba(0,240,255,0.3)]"
          : "bg-gray-100 dark:bg-white/5 border border-gray-200 dark:border-white/10 text-gray-800 dark:text-white hover:border-gray-300 dark:hover:border-white/30 hover:text-gray-900 dark:hover:text-white/80"
        }
      `}
    >
      <span>{label}</span>
      <span className={`
        text-xs font-mono px-1.5 py-0.5 rounded-full
        ${selected ? "bg-primary-neon/20 text-primary-neon" : "bg-gray-200 dark:bg-white/10 text-gray-800 dark:text-white"}
      `}>
        {count}
      </span>
    </button>
  );
}

/* ─── 情景筛选 Chip ──────────────────────────────── */
function SituationChip({
  label, count, selected, onClick,
}: { label: string; count: number; selected: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`
        flex-shrink-0 flex items-center gap-1.5 px-3 py-2 rounded-lg
        text-xs font-display font-bold transition-all duration-200
        ${selected
          ? "bg-secondary-magenta/20 border border-secondary-magenta/60 text-secondary-magenta"
          : "bg-gray-100 dark:bg-white/5 border border-gray-200 dark:border-white/10 text-gray-800 dark:text-white hover:border-gray-300 dark:hover:border-white/30 hover:text-gray-900 dark:hover:text-white"
        }
      `}
    >
      {label}
      <span className={`
        font-mono text-xs px-1.5 py-0.5 rounded-full
        ${selected ? "bg-secondary-magenta/20 text-secondary-magenta" : "bg-gray-200 dark:bg-white/10 text-gray-800 dark:text-white"}
      `}>
        {count}
      </span>
    </button>
  );
}

/* ─── 主组件 ─────────────────────────────────────── */
interface Props {
  homeTeam: TeamShotHistory;
  awayTeam: TeamShotHistory;
  homeTeamName: string;
  awayTeamName: string;
}

type Period  = "ALL" | "FIRST" | "SECOND";
type Outcome = "ALL" | "Goal" | "AttemptSaved" | "Miss" | "Post";

const PERIOD_LABEL: Record<Period, string> = {
  ALL:    "全场",
  FIRST:  "上半场",
  SECOND: "下半场",
};
const OUTCOME_LABEL: Record<Outcome, string> = {
  ALL:          "全部",
  Goal:         "进球",
  AttemptSaved: "扑出",
  Miss:         "偏出",
  Post:         "门柱",
};

export default function InteractiveShotMap({
  homeTeam, awayTeam, homeTeamName, awayTeamName,
}: Props) {
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const [activeTeam, setActiveTeam] = useState<"home" | "away">("home");
  // null = 全部5场聚合
  const [selectedMatchId, setSelectedMatchId] = useState<number | null>(null);
  const [activeSituation, setActiveSituation] = useState<string>("ALL");
  const [activePeriod,    setActivePeriod]    = useState<Period>("ALL");
  const [activeOutcome,   setActiveOutcome]   = useState<Outcome>("ALL");
  /** 高级筛选（情景+半场）默认折叠 */
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [isZoomed, setIsZoomed] = useState(false);

  // 放大模态：ESC 关闭 + 锁定 body 滚动
  useEffect(() => {
    if (!isZoomed) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setIsZoomed(false); };
    window.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [isZoomed]);

  const teamData = activeTeam === "home" ? homeTeam : awayTeam;
  const teamLabel = activeTeam === "home" ? homeTeamName : awayTeamName;

  /* 切换队伍时重置选项 */
  const handleTeamSwitch = (team: "home" | "away") => {
    setActiveTeam(team);
    setSelectedMatchId(null);
    setActiveSituation("ALL");
    setActivePeriod("ALL");
    setActiveOutcome("ALL");
  };

  /* 当前选中场次的数据 */
  const activeMatches: MatchShotData[] = useMemo(() => {
    if (selectedMatchId === null) return teamData.matches;
    return teamData.matches.filter(m => m.match_id === selectedMatchId);
  }, [teamData, selectedMatchId]);

  /* 所有原始射门点（未按情景过滤）— 自动剔除点球大战（PenaltyShootout） */
  const allShots: Shot[] = useMemo(
    () => activeMatches.flatMap(m => m.shots).filter(s => s.period !== 'PenaltyShootout'),
    [activeMatches]
  );

  /* 统计当前场次选择下，各情景的数量 */
  const situationTotals: Record<string, number> = useMemo(() => {
    const acc: Record<string, number> = {};
    allShots.forEach(s => {
      if (s.situation) acc[s.situation] = (acc[s.situation] || 0) + 1;
    });
    return acc;
  }, [allShots]);

  /* 有效情景列表（有数据的才显示） */
  const availableSituations = Object.entries(situationTotals)
    .sort((a, b) => b[1] - a[1])
    .map(([k]) => k);

  /* 最终渲染的射门（按 情景 × 半场 × 结果 三维过滤） */
  const displayedShots: Shot[] = useMemo(() => {
    return allShots.filter(s => {
      if (activeSituation !== "ALL" && s.situation !== activeSituation) return false;
      if (activeOutcome   !== "ALL" && s.outcome   !== activeOutcome)   return false;
      if (activePeriod !== "ALL") {
        const m = s.minute ?? 0;
        if (activePeriod === "FIRST"  && m >  45) return false;
        if (activePeriod === "SECOND" && m <= 45) return false;
      }
      return true;
    });
  }, [allShots, activeSituation, activeOutcome, activePeriod]);

  /* xG 对比卡：当前过滤结果的 Σxg 与 实际进球数 */
  const xgSum     = displayedShots.reduce((acc, s) => acc + (s.xg || 0), 0);
  const goalCount = displayedShots.filter(s => s.outcome === "Goal").length;
  const xgDelta   = goalCount - xgSum;
  const deltaCls  = xgDelta >  0.15 ? "text-[color:var(--color-primary-neon)]"
                  : xgDelta < -0.15 ? "text-rose-600 dark:text-rose-400"
                  :                   "text-slate-600 dark:text-white";

  /* 可见射门的引用集合（用于 opacity 动效，引用比较） */
  const displayedSet = useMemo<Set<Shot>>(() => new Set(displayedShots), [displayedShots]);

  /* 全部5场总射门数（用于 "全部" pill）— 同样剔除点球大战 */
  const totalShotsAll = useMemo(
    () => teamData.matches.flatMap(m => m.shots).filter(s => s.period !== 'PenaltyShootout').length,
    [teamData]
  );

  /* 格式化日期显示 */
  const fmtDate = (d: string) => {
    if (!d) return "";
    const parts = d.split("-");
    return parts.length >= 3 ? `${parts[1]}/${parts[2]}` : d;
  };

  return (
    <div className="flex flex-col gap-4 w-full">

      {/* ── 队伍切换 ── */}
      <div className="flex rounded-xl overflow-hidden border border-gray-200 dark:border-white/10 bg-gray-100 dark:bg-white/5">
        {(["home", "away"] as const).map(side => (
          <button
            key={side}
            onClick={() => handleTeamSwitch(side)}
            className={`
              flex-1 py-2 text-xs font-display font-bold tracking-wide transition-all
              ${activeTeam === side
                ? "bg-white dark:bg-white/10 text-gray-900 dark:text-white"
                : "text-gray-700 dark:text-white hover:text-gray-900 dark:hover:text-white"
              }
            `}
          >
            {side === "home" ? homeTeamName : awayTeamName}
          </button>
        ))}
      </div>

      {/* ── 场次选择器 ── */}
      <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-none">
        {/* 全部5场 */}
        <MatchPill
          label="全部5场"
          count={totalShotsAll}
          selected={selectedMatchId === null}
          onClick={() => { setSelectedMatchId(null); setActiveSituation("ALL"); }}
        />
        {teamData.matches.map(m => (
          <MatchPill
            key={m.match_id}
            label={`${m.is_home ? "主" : "客"}vs ${m.opponent || "?"} ${fmtDate(m.date)}`}
            // 排除点球大战：m.total_shots 含点球大战，这里按实际可视射门数重算
            count={m.shots.filter(s => s.period !== 'PenaltyShootout').length}
            selected={selectedMatchId === m.match_id}
            onClick={() => { setSelectedMatchId(m.match_id); setActiveSituation("ALL"); }}
          />
        ))}
      </div>

      {/* ── 射门计数徽章 ── */}
      <div className="flex items-center gap-3">
        <div className="flex items-baseline gap-1.5">
          <span className="text-2xl font-display font-black text-primary-neon drop-shadow-[0_0_8px_rgba(0,240,255,0.6)]">
            {displayedShots.length}
          </span>
          <span className="text-xs text-slate-700 dark:text-white font-display">
            次射门
            {activeSituation !== "ALL" && (
              <span className="ml-1 text-secondary-magenta">
                · {situationLabel(activeSituation)}
              </span>
            )}
          </span>
        </div>
        <div className="flex-1 h-px bg-gray-200 dark:bg-white/10" />
        <span className="text-sm font-black text-slate-900 dark:text-white">{teamLabel}</span>
      </div>

      {/* ── 结果筛选（outcome）── 主要筛选，常驻展示 */}
      <div className="flex gap-1.5 flex-wrap">
        {(Object.keys(OUTCOME_LABEL) as Outcome[]).map(o => {
          const selected = activeOutcome === o;
          const cnt = o === "ALL"
            ? allShots.length
            : allShots.filter(s => s.outcome === o).length;
          return (
            <button
              key={o}
              onClick={() => setActiveOutcome(o)}
              className={`
                flex-shrink-0 flex items-center gap-1 px-2.5 py-1 rounded-lg
                text-xs font-display font-semibold transition-all duration-200
                ${selected
                  ? "bg-secondary-magenta/20 border border-secondary-magenta/60 text-secondary-magenta"
                  : "bg-gray-100 dark:bg-white/5 border border-gray-200 dark:border-white/10 text-gray-800 dark:text-white hover:border-gray-300 dark:hover:border-white/25 hover:text-gray-900 dark:hover:text-white"
                }
              `}
            >
              {OUTCOME_LABEL[o]}
              <span className={`font-mono text-xs px-1 py-0.5 rounded-full ${selected ? "bg-secondary-magenta/20 text-secondary-magenta" : "bg-gray-200 dark:bg-white/10 text-gray-800 dark:text-white"}`}>
                {cnt}
              </span>
            </button>
          );
        })}
      </div>

      {/* ── 高级筛选（半场 + 情景）── 默认折叠 */}
      <div>
        <button
          onClick={() => setShowAdvanced(v => !v)}
          className="flex items-center gap-2 text-xs font-mono text-slate-600 dark:text-white hover:text-slate-800 dark:hover:text-white transition-colors"
        >
          <span className="text-xs">{showAdvanced ? '▲' : '▼'}</span>
          高级筛选
          {(activePeriod !== "ALL" || activeSituation !== "ALL") && (
            <span className="px-1.5 py-0.5 rounded-full bg-primary-neon/20 text-[color:var(--color-primary-neon)] text-xs">已启用</span>
          )}
        </button>

        {showAdvanced && (
          <div className="mt-3 flex flex-col gap-3">
            {/* 半场筛选 */}
            <div className="flex gap-1.5">
              {(Object.keys(PERIOD_LABEL) as Period[]).map(p => (
                <button
                  key={p}
                  onClick={() => setActivePeriod(p)}
                  className={`
                    flex-1 py-1.5 rounded-lg text-xs font-display font-bold tracking-wide transition-all
                    ${activePeriod === p
                      ? "bg-primary-neon/20 border border-primary-neon/60 text-primary-neon"
                      : "bg-gray-100 dark:bg-white/5 border border-gray-200 dark:border-white/10 text-gray-800 dark:text-white hover:border-gray-300 dark:hover:border-white/30"
                    }
                  `}
                >
                  {PERIOD_LABEL[p]}
                </button>
              ))}
            </div>

            {/* 情景筛选 */}
            {availableSituations.length > 0 ? (
              <div className="flex gap-1.5 flex-wrap">
                <SituationChip
                  label="全部情景"
                  count={allShots.length}
                  selected={activeSituation === "ALL"}
                  onClick={() => setActiveSituation("ALL")}
                />
                {availableSituations.map(sit => (
                  <SituationChip
                    key={sit}
                    label={situationLabel(sit)}
                    count={situationTotals[sit]}
                    selected={activeSituation === sit}
                    onClick={() => setActiveSituation(sit)}
                  />
                ))}
              </div>
            ) : (
              <div className="text-xs text-slate-700 dark:text-white font-mono">
                · 该场次暂无情景分类数据
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── 半场球场 SVG ── */}
      <div className="w-full relative rounded-xl overflow-hidden bg-white dark:bg-black border border-slate-200 dark:border-white/10">
        <svg
          viewBox={`0 0 ${VB_W} ${VB_H + 14}`}
          className="w-full h-auto"
          style={{ display: "block" }}
        >
          {/* 纯色底 */}
          <rect width={VB_W} height={VB_H + 14} fill={isDark ? '#000000' : '#ffffff'} />

          {/* 球场线 */}
          <PitchLines isDark={isDark} />

          {/* 射门点（全量，opacity 动效） */}
          <ShotDots allShots={allShots} displayedSet={displayedSet} isDark={isDark} />
        </svg>

        {/* 中线标签 */}
        <div className="absolute top-1 left-1/2 -translate-x-1/2 text-xs font-mono text-slate-400 dark:text-slate-500 tracking-widest uppercase">
          中线方向 ↑
        </div>

        {/* 放大按钮 */}
        <button
          type="button"
          onClick={() => setIsZoomed(true)}
          aria-label="放大查看射门图"
          className="absolute top-2 right-2 flex items-center gap-1 px-2 py-1 rounded-full
                     bg-white/90 dark:bg-black/70 backdrop-blur-sm
                     border border-slate-300 dark:border-white/20
                     text-slate-700 dark:text-white
                     active:scale-95 transition-transform
                     shadow-sm hover:bg-white dark:hover:bg-black/90"
        >
          <Maximize2 size={12} />
          <span className="text-xs font-bold">放大</span>
        </button>
      </div>

      {/* ── xG 对比卡 HUD ── */}
      <div className="grid grid-cols-3 gap-3 border-t border-slate-100 dark:border-white/5 pt-3">
        <div className="flex flex-col items-center gap-0.5">
          <span className="text-xs font-mono text-slate-700 dark:text-white uppercase tracking-[0.2em]">Σ xG</span>
          <span className="text-lg font-black font-mono text-[color:var(--color-primary-neon)] dark:drop-shadow-[0_0_8px_rgba(0,240,255,0.6)]">
            {xgSum.toFixed(2)}
          </span>
        </div>
        <div className="flex flex-col items-center gap-0.5 border-x border-slate-200 dark:border-white/5">
          <span className="text-xs font-mono text-slate-700 dark:text-white uppercase tracking-[0.2em]">GOALS</span>
          <span className="text-lg font-black font-mono text-emerald-600 dark:text-emerald-400 dark:drop-shadow-[0_0_8px_rgba(74,222,128,0.5)]">
            {goalCount}
          </span>
        </div>
        <div className="flex flex-col items-center gap-0.5">
          <span className="text-xs font-mono text-slate-700 dark:text-white uppercase tracking-[0.2em]">Δ</span>
          <span className={`text-lg font-black font-mono ${deltaCls}`}>
            {xgDelta > 0 ? "+" : ""}{xgDelta.toFixed(2)}
          </span>
        </div>
      </div>

      {/* ── 图例 ── */}
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 justify-center">
        {Object.entries(outcomeChinese).map(([key, label]) => (
          <div key={key} className="flex items-center gap-1.5">
            <svg width="14" height="14">
              {key === "Goal" ? (
                <circle cx="7" cy="7" r="5" fill={outcomeColor(key, isDark)} opacity={0.85} />
              ) : (
                <circle cx="7" cy="7" r="5" fill="transparent"
                  stroke={outcomeColor(key, isDark)} strokeWidth={1.5} opacity={0.85} />
              )}
            </svg>
            <span className="text-xs text-gray-700 dark:text-white font-display">{label}</span>
          </div>
        ))}
        <div className="flex items-center gap-1.5 ml-2 border-l border-gray-200 dark:border-white/10 pl-3">
          <span className="text-xs text-slate-700 dark:text-white font-mono">圆点大小 = xG</span>
        </div>
      </div>

      {/* ── 放大模态：手机竖屏下旋转球场撑满屏幕 ── */}
      {isZoomed && (
        <div
          className="fixed inset-0 z-[100] flex flex-col
                     bg-[var(--color-background)]"
          onClick={() => setIsZoomed(false)}
        >
          {/* 顶栏 */}
          <div
            className="flex items-center justify-between px-4 py-3
                       border-b border-slate-200 dark:border-white/10"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-baseline gap-2 min-w-0">
              <span className="text-sm font-black text-slate-900 dark:text-white truncate">
                {activeTeam === 'home' ? homeTeamName : awayTeamName}
              </span>
              <span className="text-xs font-mono text-slate-500 dark:text-white/60 flex-shrink-0">
                · {displayedShots.length} 次 · Σ xG {xgSum.toFixed(2)}
              </span>
            </div>
            <button
              type="button"
              onClick={() => setIsZoomed(false)}
              aria-label="关闭"
              className="flex items-center justify-center w-9 h-9 rounded-full
                         bg-slate-100 dark:bg-white/10
                         text-slate-700 dark:text-white
                         hover:bg-slate-200 dark:hover:bg-white/20
                         active:scale-95 transition-all flex-shrink-0 ml-2"
            >
              <X size={18} />
            </button>
          </div>

          {/* 球场撑满中间区域：
              · viewBox 裁剪到攻区（30 130 280 146.5），aspect = 280/146.5 ≈ 1.91
              · 通过 SVG 内部坐标变换"翻转"成竖向（球门朝下、中线朝上），不再用 CSS rotate
              · 翻转后 aspect = 146.5/280 ≈ 0.523，正好竖屏铺满 */}
          <div
            className="flex-1 flex items-center justify-center p-2 overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            <svg
              viewBox="0 0 146.5 280"
              className="block"
              preserveAspectRatio="xMidYMid meet"
              style={{ width: '100%', height: '100%', maxWidth: 'min(100%, calc(100vh * 0.523))' }}
            >
              {/* 把整张半场旋转 90° 嵌进竖向 viewBox：
                  原坐标: x=30..310, y=130..276.5 (攻区裁剪)
                  目标坐标: 0..146.5 (新 X) × 0..280 (新 Y)
                  变换：translate(146.5, 0) rotate(90)  → 等价于 (oldX, oldY) → (146.5 - oldY_offset, oldX_offset)
                  实际我们要把"原 SVG 的 30..310 横向"放到竖向 0..280
                  最简单：直接 translate + rotate 应用到内容 group
              */}
              <g transform="translate(146.5 0) rotate(90) translate(-30 -130)">
                <rect x="30" y="130" width="280" height="146.5" fill={isDark ? '#000000' : '#ffffff'} />
                <PitchLines isDark={isDark} />
                <ShotDots allShots={allShots} displayedSet={displayedSet} isDark={isDark} />
              </g>
            </svg>
          </div>


          {/* 底栏：图例 + 关闭提示 */}
          <div
            className="px-4 py-3 border-t border-slate-200 dark:border-white/10"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex flex-wrap gap-x-3 gap-y-1.5 justify-center mb-1.5">
              {Object.entries(outcomeChinese).map(([key, label]) => (
                <div key={key} className="flex items-center gap-1">
                  <svg width="12" height="12">
                    {key === "Goal" ? (
                      <circle cx="6" cy="6" r="4.5" fill={outcomeColor(key, isDark)} opacity={0.9} />
                    ) : (
                      <circle cx="6" cy="6" r="4.5" fill="transparent"
                        stroke={outcomeColor(key, isDark)} strokeWidth={1.5} opacity={0.9} />
                    )}
                  </svg>
                  <span className="text-xs text-slate-700 dark:text-white font-display">{label}</span>
                </div>
              ))}
              <span className="text-xs text-slate-500 dark:text-white/50 font-mono ml-2 border-l border-slate-200 dark:border-white/15 pl-2">
                圆点 = xG
              </span>
            </div>
            <p className="text-center text-xs font-mono text-slate-500 dark:text-white/40">
              点击外部 / 按 ESC 关闭
            </p>
          </div>
        </div>
      )}

    </div>
  );
}
