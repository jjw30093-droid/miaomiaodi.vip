'use client';

/**
 * WcRecentStatsCompare — 世界杯近期数据对比（代替空的「原始攻防对比」）
 * 数据来自 wc_recent_compare（cc站 recent_stats_compare 近5/10场均值）
 * 格式：{windows:[5,10], home:{5:{BALL_POSSESSION:{value,n},...},...}, away:{...}}
 */

interface StatWindow {
  [statKey: string]: { value: number; n: number } | undefined;
}
interface WcRecentCompare {
  windows?: number[];
  home?: { [win: string]: StatWindow };
  away?: { [win: string]: StatWindow };
}

// 展示的指标：key → 中文标签（只展示有数据的）
const STAT_LABELS: Record<string, string> = {
  BALL_POSSESSION:   '控球率 %',
  SHOTS_TOTAL:       '总射门',
  SHOTS_ON_TARGET:   '射正',
  BIG_CHANCES_CREATED: '大机会',
  CORNERS:           '角球',
  TACKLES:           '抢断',
  TOTAL_CROSSES:     '传中',
  KEY_PASSES:        '关键传球',
  FOULS:             '犯规',
};

interface Props {
  wcRecentCompare: WcRecentCompare | null | undefined;
  homeTeam: string;
  awayTeam: string;
  defaultWindow?: number;
}

function fmt(v: number | undefined): string {
  if (v == null || isNaN(v)) return '—';
  return v % 1 === 0 ? String(v) : v.toFixed(1);
}

export default function WcRecentStatsCompare({
  wcRecentCompare,
  homeTeam,
  awayTeam,
  defaultWindow = 5,
}: Props) {
  if (!wcRecentCompare) return null;

  const windows = wcRecentCompare.windows ?? [defaultWindow];
  const win = String(windows[0] ?? defaultWindow);
  const homeStats = wcRecentCompare.home?.[win] ?? {};
  const awayStats = wcRecentCompare.away?.[win] ?? {};

  // 只展示双方都有数据或至少一方有数据的指标
  const rows = Object.entries(STAT_LABELS)
    .map(([key, label]) => ({
      key, label,
      home: homeStats[key]?.value,
      away: awayStats[key]?.value,
      n: homeStats[key]?.n ?? awayStats[key]?.n,
    }))
    .filter(r => r.home != null || r.away != null);

  if (rows.length === 0) return null;

  const windowLabel = windows[0] ? `近 ${windows[0]} 场均值` : '近期均值';

  return (
    <div className="rounded-xl border border-zinc-700/40 bg-zinc-900/60 p-4 mt-4">
      <h3 className="text-sm font-bold text-zinc-300 mb-1">
        📊 近期数据对比
      </h3>
      <p className="text-[10px] text-zinc-500 mb-3">{windowLabel}（世界杯预选赛 / 历史大赛）</p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-zinc-400 border-b border-zinc-800">
              <th className="text-left pb-2 pr-3">指标</th>
              <th className="text-right pb-2 pr-3 text-[#baff00]">{homeTeam}</th>
              <th className="text-right pb-2 text-zinc-400">{awayTeam}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.key} className="border-b border-zinc-800/40">
                <td className="py-1.5 pr-3 text-zinc-400">{r.label}</td>
                <td className="py-1.5 pr-3 text-right text-[#baff00] font-mono">{fmt(r.home)}</td>
                <td className="py-1.5 text-right text-zinc-300 font-mono">{fmt(r.away)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
