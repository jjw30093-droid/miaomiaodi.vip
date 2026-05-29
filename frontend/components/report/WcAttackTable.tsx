'use client';

/**
 * WcAttackTable — 世界杯原始攻防对比表
 *
 * 数据来自 wc_reports.payload_json（后端烘焙进 wc_team_stats）。
 * BCC 行：48% 覆盖率 → null 时显示"—"，绝对不插值估算。
 *
 * 仅在 tournamentType === 'wc' 时渲染（上层门控）。
 */

import React from 'react';

interface WcTeamStats {
  shots_total?:       number | null;
  shots_on_target?:   number | null;
  inside_box?:        number | null;
  outside_box?:       number | null;
  big_chances?:       number | null;
  dangerous_attacks?: number | null;
  possession_pct?:    number | null;
}

interface WcAttackTableProps {
  homeTeamName: string;
  awayTeamName: string;
  homeStats: WcTeamStats;
  awayStats: WcTeamStats;
}

function fmtVal(val: number | null | undefined, suffix: string = ''): string {
  if (val == null) return '—';
  return `${val}${suffix}`;
}

export default function WcAttackTable({
  homeTeamName,
  awayTeamName,
  homeStats,
  awayStats,
}: WcAttackTableProps) {
  const rows: { label: string; home: string; away: string }[] = [
    {
      label: '总射门',
      home:  fmtVal(homeStats.shots_total),
      away:  fmtVal(awayStats.shots_total),
    },
    {
      label: '射正',
      home:  fmtVal(homeStats.shots_on_target),
      away:  fmtVal(awayStats.shots_on_target),
    },
    {
      label: '禁区内射门',
      home:  fmtVal(homeStats.inside_box),
      away:  fmtVal(awayStats.inside_box),
    },
    {
      label: '禁区外射门',
      home:  fmtVal(homeStats.outside_box),
      away:  fmtVal(awayStats.outside_box),
    },
    // BCC 条件渲染：null → '—（数据未覆盖）'
    {
      label: '大机会',
      home:  homeStats.big_chances != null ? String(homeStats.big_chances) : '—',
      away:  awayStats.big_chances != null ? String(awayStats.big_chances) : '—',
    },
    {
      label: '危险进攻',
      home:  fmtVal(homeStats.dangerous_attacks),
      away:  fmtVal(awayStats.dangerous_attacks),
    },
    {
      label: '控球率',
      home:  fmtVal(homeStats.possession_pct, '%'),
      away:  fmtVal(awayStats.possession_pct, '%'),
    },
  ];

  const hasBcc = homeStats.big_chances != null || awayStats.big_chances != null;

  return (
    <div className="rounded-2xl overflow-hidden
                    bg-white/85 backdrop-blur-xl
                    dark:bg-[#0A1220]
                    border border-slate-900/10
                    dark:border dark:border-[#00F0FF]/20
                    shadow-[0_4px_24px_rgba(15,23,42,0.06)]
                    dark:shadow-[0_0_24px_rgba(0,240,255,0.15)]
                    p-4 space-y-3">

      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs font-black tracking-widest uppercase text-[#005faf] dark:text-[#00F0FF]">
          ⚽ 攻防对比
        </span>
        <span className="text-[10px] text-slate-400 dark:text-slate-500">
          世界杯队伍统计
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-700">
              <th className="py-1.5 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 w-[40%]">
                指标
              </th>
              <th className="py-1.5 text-center text-xs font-bold text-[#005faf] dark:text-[#00F0FF] w-[30%]">
                {homeTeamName}
              </th>
              <th className="py-1.5 text-center text-xs font-bold text-amber-600 dark:text-amber-400 w-[30%]">
                {awayTeamName}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={row.label}
                className={`border-b border-slate-100 dark:border-slate-800
                            ${i % 2 === 0 ? '' : 'bg-slate-50/50 dark:bg-slate-800/20'}`}
              >
                <td className="py-1.5 text-xs text-slate-600 dark:text-slate-400">
                  {row.label}
                  {row.label === '大机会' && !hasBcc && (
                    <span className="ml-1 text-[10px] text-slate-400 dark:text-slate-500">
                      （数据未覆盖）
                    </span>
                  )}
                </td>
                <td className="py-1.5 text-center text-sm font-semibold text-slate-800 dark:text-slate-200">
                  {row.home}
                </td>
                <td className="py-1.5 text-center text-sm font-semibold text-slate-800 dark:text-slate-200">
                  {row.away}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!hasBcc && (
        <p className="text-[10px] text-slate-400 dark:text-slate-500 italic">
          * 大机会（Big Chances Created）数据在世界杯数据集中覆盖率约 48%，未覆盖场次显示 —，不插值估算。
        </p>
      )}
    </div>
  );
}
