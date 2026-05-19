"use client";
import React, { useState, useMemo } from "react";
import { TeamShotHistory, MatchShotData, Shot } from "@/types/report";

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
   Goal=绿, AttemptSaved=青, Miss=品红, Blocked=琥珀, 未知=灰 */
const OUTCOME_COLOR: Record<string, string> = {
  Goal:          "#22c55e",
  AttemptSaved:  "#00F0FF",
  Miss:          "#FF00E5",
  Blocked:       "#f59e0b",
};
const outcomeColor = (o: string) => OUTCOME_COLOR[o] ?? "#6b7280";
const outcomeChinese: Record<string, string> = {
  Goal:         "进球",
  AttemptSaved: "扑出",
  Miss:         "偏出",
  Blocked:      "封堵",
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
function PitchLines() {
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
  const arcR   = 9.15 * SCALE;  // 45.75
  const arcCX  = toSvgX(34);
  const arcCY  = toSvgY(94.5);
  // 与禁区顶线 y=paY 的交点
  const arcDy  = arcCY - paY;
  const arcDx  = Math.sqrt(Math.max(0, arcR * arcR - arcDy * arcDy));
  const arcX1  = arcCX - arcDx;
  const arcX2  = arcCX + arcDx;

  // 球门 (Goal): X=105, Y 30.34→37.66
  const goalX1 = toSvgX(30.34);
  const goalX2 = toSvgX(37.66);
  const goalY  = VB_H;

  const strokeStyle = { stroke: "rgba(255,255,255,0.25)", strokeWidth: 1, fill: "none" };

  return (
    <g>
      {/* 边界 */}
      <rect x={0} y={0} width={VB_W} height={VB_H} {...strokeStyle} />
      {/* 中线（顶部虚线提示） */}
      <line x1={0} y1={0} x2={VB_W} y2={0} strokeDasharray="6 4" {...strokeStyle} />
      {/* 禁区 */}
      <rect x={paX} y={paY} width={paW} height={paH} {...strokeStyle} />
      {/* 小禁区 */}
      <rect x={gaX} y={gaY} width={gaW} height={gaH} {...strokeStyle} />
      {/* 罚球点 */}
      <circle cx={spotCX} cy={spotCY} r={2} fill="rgba(255,255,255,0.3)" />
      {/* 罚球弧（只显示禁区外部分） */}
      {arcDx > 0 && (
        <path
          d={`M ${arcX1} ${paY} A ${arcR} ${arcR} 0 0 0 ${arcX2} ${paY}`}
          {...strokeStyle}
        />
      )}
      {/* 球门线（加粗底线） */}
      <line
        x1={goalX1} y1={goalY} x2={goalX2} y2={goalY}
        stroke="#00F0FF" strokeWidth={3} strokeLinecap="round"
      />
      {/* 球门柱（延伸出边界视觉提示） */}
      <line x1={goalX1} y1={goalY} x2={goalX1} y2={goalY + 8}
        stroke="#00F0FF" strokeWidth={2} />
      <line x1={goalX2} y1={goalY} x2={goalX2} y2={goalY + 8}
        stroke="#00F0FF" strokeWidth={2} />
    </g>
  );
}

/* ─── 射门圆点 ───────────────────────────────────── */
function ShotDots({ shots }: { shots: Shot[] }) {
  // 过滤掉半场外的射门（X < 52.5）
  const visible = shots.filter(s => s.x >= X_OFFSET);
  return (
    <g>
      {visible.map((s, i) => {
        const cx = toSvgX(s.y);
        const cy = toSvgY(s.x);
        const r  = xgRadius(s.xg);
        const color = outcomeColor(s.outcome);
        const isGoal = s.outcome === "Goal";
        return (
          <g key={i}>
            {isGoal && (
              <circle cx={cx} cy={cy} r={r + 4}
                fill={color} opacity={0.25} />
            )}
            <circle
              cx={cx} cy={cy} r={r}
              fill={isGoal ? color : "transparent"}
              stroke={color}
              strokeWidth={isGoal ? 0 : 1.5}
              opacity={0.85}
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
        flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full
        text-[11px] font-display font-bold transition-all duration-200
        ${selected
          ? "bg-primary-neon/20 border border-primary-neon text-primary-neon shadow-[0_0_8px_rgba(0,240,255,0.3)]"
          : "bg-gray-100 dark:bg-white/5 border border-gray-200 dark:border-white/10 text-gray-800 dark:text-white/50 hover:border-gray-300 dark:hover:border-white/30 hover:text-gray-900 dark:hover:text-white/80"
        }
      `}
    >
      <span>{label}</span>
      <span className={`
        text-[10px] font-mono px-1.5 py-0.5 rounded-full
        ${selected ? "bg-primary-neon/20 text-primary-neon" : "bg-gray-200 dark:bg-white/10 text-gray-700 dark:text-white/40"}
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
        flex-shrink-0 flex items-center gap-1 px-2.5 py-1 rounded-lg
        text-[10px] font-display font-semibold transition-all duration-200
        ${selected
          ? "bg-secondary-magenta/20 border border-secondary-magenta/60 text-secondary-magenta"
          : "bg-gray-100 dark:bg-white/5 border border-gray-200 dark:border-white/10 text-gray-800 dark:text-white/40 hover:border-gray-300 dark:hover:border-white/25 hover:text-gray-900 dark:hover:text-white/70"
        }
      `}
    >
      {label}
      <span className={`
        font-mono text-[9px] px-1 py-0.5 rounded-full
        ${selected ? "bg-secondary-magenta/20" : "bg-gray-200 dark:bg-white/10"}
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
type Outcome = "ALL" | "Goal" | "AttemptSaved" | "Miss" | "Blocked";

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
  Blocked:      "封堵",
};

export default function InteractiveShotMap({
  homeTeam, awayTeam, homeTeamName, awayTeamName,
}: Props) {
  const [activeTeam, setActiveTeam] = useState<"home" | "away">("home");
  // null = 全部5场聚合
  const [selectedMatchId, setSelectedMatchId] = useState<number | null>(null);
  const [activeSituation, setActiveSituation] = useState<string>("ALL");
  const [activePeriod,    setActivePeriod]    = useState<Period>("ALL");
  const [activeOutcome,   setActiveOutcome]   = useState<Outcome>("ALL");

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

  /* 所有原始射门点（未按情景过滤） */
  const allShots: Shot[] = useMemo(
    () => activeMatches.flatMap(m => m.shots),
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
  const deltaCls  = xgDelta >  0.15 ? "text-emerald-600 dark:text-emerald-400"
                  : xgDelta < -0.15 ? "text-rose-600 dark:text-rose-400"
                  :                   "text-gray-700 dark:text-white/50";

  /* 全部5场总射门数（用于 "全部" pill） */
  const totalShotsAll = teamData.matches.reduce((s, m) => s + m.total_shots, 0);

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
              flex-1 py-2 text-[11px] font-display font-bold tracking-wide transition-all
              ${activeTeam === side
                ? "bg-white dark:bg-white/10 text-gray-900 dark:text-white"
                : "text-gray-700 dark:text-white/40 hover:text-gray-900 dark:hover:text-white/70"
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
            count={m.total_shots}
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
          <span className="text-[11px] text-gray-700 dark:text-white/50 font-display">
            次射门
            {activeSituation !== "ALL" && (
              <span className="ml-1 text-secondary-magenta">
                · {situationLabel(activeSituation)}
              </span>
            )}
          </span>
        </div>
        <div className="flex-1 h-px bg-gray-200 dark:bg-white/10" />
        <span className="text-[10px] text-gray-700 dark:text-white/30 font-mono">{teamLabel}</span>
      </div>

      {/* ── 半场筛选（period）── */}
      <div className="flex gap-1.5">
        {(Object.keys(PERIOD_LABEL) as Period[]).map(p => (
          <button
            key={p}
            onClick={() => setActivePeriod(p)}
            className={`
              flex-1 py-1.5 rounded-lg text-[10px] font-display font-bold tracking-wide transition-all
              ${activePeriod === p
                ? "bg-primary-neon/20 border border-primary-neon/60 text-primary-neon"
                : "bg-gray-100 dark:bg-white/5 border border-gray-200 dark:border-white/10 text-gray-800 dark:text-white/50 hover:border-gray-300 dark:hover:border-white/30"
              }
            `}
          >
            {PERIOD_LABEL[p]}
          </button>
        ))}
      </div>

      {/* ── 结果筛选（outcome）── */}
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
                text-[10px] font-display font-semibold transition-all duration-200
                ${selected
                  ? "bg-secondary-magenta/20 border border-secondary-magenta/60 text-secondary-magenta"
                  : "bg-gray-100 dark:bg-white/5 border border-gray-200 dark:border-white/10 text-gray-800 dark:text-white/40 hover:border-gray-300 dark:hover:border-white/25 hover:text-gray-900 dark:hover:text-white/70"
                }
              `}
            >
              {OUTCOME_LABEL[o]}
              <span className={`font-mono text-[9px] px-1 py-0.5 rounded-full ${selected ? "bg-secondary-magenta/20" : "bg-gray-200 dark:bg-white/10"}`}>
                {cnt}
              </span>
            </button>
          );
        })}
      </div>

      {/* ── 情景筛选 ── */}
      {availableSituations.length > 0 ? (
        <div className="flex gap-1.5 flex-wrap">
          <SituationChip
            label="全部"
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
        <div className="text-[10px] text-gray-600 dark:text-white/25 font-mono">
          · 该场次暂无情景分类数据
        </div>
      )}

      {/* ── 半场球场 SVG ── */}
      <div className="w-full relative rounded-xl overflow-hidden bg-[#0a1a0a]/60 border border-white/10">
        <svg
          viewBox={`0 0 ${VB_W} ${VB_H + 10}`}
          className="w-full h-auto"
          style={{ display: "block" }}
        >
          {/* 草坪纹路 */}
          <defs>
            <pattern id="grass" x="0" y="0" width="20" height="20" patternUnits="userSpaceOnUse">
              <rect width="10" height="20" fill="rgba(0,50,0,0.15)" />
              <rect x="10" width="10" height="20" fill="rgba(0,60,0,0.08)" />
            </pattern>
          </defs>
          <rect width={VB_W} height={VB_H + 10} fill="url(#grass)" />

          {/* 球场线 */}
          <PitchLines />

          {/* 射门点 */}
          <ShotDots shots={displayedShots} />
        </svg>

        {/* 中线标签 */}
        <div className="absolute top-1 left-1/2 -translate-x-1/2 text-[8px] font-mono text-white/20 tracking-widest uppercase">
          中线方向 ↑
        </div>
      </div>

      {/* ── xG 对比卡（当前过滤结果）── */}
      <div className="grid grid-cols-3 gap-2">
        <div className="bg-gray-100 dark:bg-white/5 rounded-xl p-2.5 flex flex-col items-center">
          <span className="text-[9px] font-bold text-gray-700 dark:text-white/50 uppercase tracking-widest mb-0.5">Σ xG</span>
          <span className="text-base font-black font-mono text-sky-700 dark:text-primary-neon">{xgSum.toFixed(2)}</span>
        </div>
        <div className="bg-gray-100 dark:bg-white/5 rounded-xl p-2.5 flex flex-col items-center">
          <span className="text-[9px] font-bold text-gray-700 dark:text-white/50 uppercase tracking-widest mb-0.5">实际进球</span>
          <span className="text-base font-black font-mono text-emerald-600 dark:text-emerald-400">{goalCount}</span>
        </div>
        <div className="bg-gray-100 dark:bg-white/5 rounded-xl p-2.5 flex flex-col items-center">
          <span className="text-[9px] font-bold text-gray-700 dark:text-white/50 uppercase tracking-widest mb-0.5">Δ (实 - 期)</span>
          <span className={`text-base font-black font-mono ${deltaCls}`}>
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
                <circle cx="7" cy="7" r="5" fill={outcomeColor(key)} opacity={0.85} />
              ) : (
                <circle cx="7" cy="7" r="5" fill="transparent"
                  stroke={outcomeColor(key)} strokeWidth={1.5} opacity={0.85} />
              )}
            </svg>
            <span className="text-[10px] text-gray-700 dark:text-white/50 font-display">{label}</span>
          </div>
        ))}
        <div className="flex items-center gap-1.5 ml-2 border-l border-gray-200 dark:border-white/10 pl-3">
          <span className="text-[10px] text-gray-700 dark:text-white/30 font-mono">圆点大小 = xG</span>
        </div>
      </div>

    </div>
  );
}
