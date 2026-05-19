'use client';

import React, { useState, useMemo } from 'react';
import { BarChart3, Target, Activity, TrendingUp } from 'lucide-react';

// ── Types ────────────────────────────────────────────────────────────────────
interface Player {
  player_id:       string;
  name:            string;
  shirt:           string | number;
  position:        'GK' | 'DF' | 'MF' | 'FW';
  minutes:         number;
  rating:          number;
  goals:           number;
  assists:         number;
  xg:              number;
  shots_on_target: number;
  is_captain:      boolean;
}

interface TeamMatchStats {
  possession:      number;
  xg:              number;
  total_shots:     number;
  shots_on_target: number;
  shot_accuracy:   number;
  big_chances:     number;
  corners:         number;
  yellow_cards:    number;
}

interface PlayerStatsPayload {
  home_team: Player[];
  away_team: Player[];
}

interface TeamStatsPayload {
  home_team: TeamMatchStats;
  away_team: TeamMatchStats;
}

interface Props {
  playerStats?:  PlayerStatsPayload;
  teamStats?:    TeamStatsPayload;
  homeTeamName: string;
  awayTeamName: string;
}

// ── Position config ───────────────────────────────────────────────────────────
const POS_CONFIG: Record<string, { label: string; color: string; group: string }> = {
  GK: { label: 'GK', color: 'text-yellow-600 dark:text-yellow-400',                group: '门将'     },
  DF: { label: 'DF', color: 'text-sky-700 dark:text-sky-400',                      group: '后防线'   },
  MF: { label: 'MF', color: 'text-[color:var(--primary-neon)] dark:text-[#00dbe9]', group: '中场核心' },
  FW: { label: 'FW', color: 'text-[color:var(--secondary-magenta)] dark:text-secondary-container', group: '前锋单元' },
};
const POS_ORDER = ['GK', 'DF', 'MF', 'FW'];

// ── Helpers ───────────────────────────────────────────────────────────────────
function ratingColor(r: number): string {
  if (r >= 7.5) return 'text-emerald-600 dark:text-emerald-400';
  if (r >= 6.5) return 'text-slate-900 dark:text-white';
  if (r >= 5.0) return 'text-slate-600 dark:text-white';
  return 'text-red-600 dark:text-error';
}

function subLabel(minutes: number): string | null {
  if (minutes === 90 || minutes === 0) return null;
  return `↓${minutes}'`;
}

// ── Main component ────────────────────────────────────────────────────────────
export default function PlayerContributionTable({
  playerStats,
  teamStats,
  homeTeamName,
  awayTeamName,
}: Props) {
  const [activeTab, setActiveTab] = useState<'home' | 'away'>('home');

  const players = activeTab === 'home' ? (playerStats?.home_team ?? []) : (playerStats?.away_team ?? []);
  const stats   = activeTab === 'home' ? (teamStats?.home_team   ?? {} as TeamMatchStats) : (teamStats?.away_team ?? {} as TeamMatchStats);

  const maxXG = useMemo(() => Math.max(...players.map(p => p.xg), 0.01), [players]);

  const grouped = useMemo(() => {
    const map: Record<string, Player[]> = {};
    POS_ORDER.forEach(pos => { map[pos] = []; });
    players.forEach(p => {
      const key = POS_ORDER.includes(p.position) ? p.position : 'MF';
      map[key].push(p);
    });
    return map;
  }, [players]);

  const noData = !playerStats || (players.length === 0 && !stats.possession);
  const hasStats = !!(stats.possession || stats.xg || stats.shot_accuracy);

  return (
    <div className="glass-panel rounded-xl overflow-hidden shadow-[0_20px_50px_rgba(0,0,0,0.5)]">

      {/* ── Header ── */}
      <div className="p-5 border-b border-slate-200 dark:border-white/5 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 bg-slate-50/50 dark:bg-white/[0.03]">
        <div className="flex items-center gap-3">
          <BarChart3 size={18} className="text-primary-container" />
          <h3 className="font-headline italic font-bold text-sm tracking-[0.15em] uppercase text-slate-900 dark:text-white">
            阵容贡献矩阵
          </h3>
          {/* legend */}
          <div className="hidden sm:flex items-center gap-4 ml-2">
            <div className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-white font-label uppercase tracking-widest">
              <div className="w-2 h-2 rounded-full bg-yellow-400" />
              进球
            </div>
            <div className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-white font-label uppercase tracking-widest">
              <div className="w-2 h-2 rounded-full bg-slate-300" />
              助攻
            </div>
          </div>
        </div>

        {/* Home / Away tab — shows team name */}
        <div className="flex gap-1 p-1 bg-slate-100 dark:bg-surface-container-lowest rounded-xl border border-slate-200 dark:border-white/5 self-start sm:self-auto">
          {(['home', 'away'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-5 py-1.5 rounded-lg font-headline font-bold text-xs uppercase tracking-widest transition-all ${
                activeTab === tab
                  ? 'bg-primary-container text-on-primary-container'
                  : 'text-slate-700 hover:text-slate-900 dark:text-white dark:hover:text-white'
              }`}
            >
              {tab === 'home' ? homeTeamName : awayTeamName}
            </button>
          ))}
        </div>
      </div>

      {/* ── No data state ── */}
      {noData && (
        <div className="py-16 flex flex-col items-center justify-center text-center gap-3 opacity-40">
          <BarChart3 size={36} className="text-primary-container" />
          <p className="text-xs font-headline uppercase tracking-[0.25em] text-slate-600">球员数据同步中</p>
          <p className="text-xs text-slate-500">赛后数据处理完成后自动更新</p>
        </div>
      )}

      {/* ── Table ── */}
      {!noData && <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse min-w-[680px]">
          <thead>
            <tr className="bg-slate-50 dark:bg-surface-container-low/50 text-xs font-headline uppercase tracking-[0.2em] text-slate-700 dark:text-white border-b border-slate-200 dark:border-white/5">
              <th className="py-4 px-5 w-10">#</th>
              <th className="py-4 px-2">球员</th>
              <th className="py-4 px-2">位置</th>
              <th className="py-4 px-2">上场</th>
              <th className="py-4 px-2">评分</th>
              <th className="py-4 px-2 text-center">进/助</th>
              <th className="py-4 px-2 w-44">xG 强度</th>
            </tr>
          </thead>
          <tbody className="font-mono text-sm">
            {POS_ORDER.map(pos => {
              const group = grouped[pos];
              if (!group || group.length === 0) return null;
              const cfg = POS_CONFIG[pos];
              return (
                <React.Fragment key={pos}>
                  {/* position group header */}
                  <tr className="bg-slate-50/70 dark:bg-white/[0.02]">
                    <td colSpan={7} className="py-2 px-5 text-xs font-headline font-bold uppercase tracking-[0.25em] text-slate-500 dark:text-primary-container/50 border-b border-slate-100 dark:border-white/5">
                      {cfg.group}
                    </td>
                  </tr>

                  {group.map((p, i) => {
                    const sub    = subLabel(p.minutes);
                    const barPct = maxXG > 0 ? Math.round((p.xg / maxXG) * 100) : 0;
                    return (
                      <tr
                        key={`${p.player_id}-${i}`}
                        className={`hover:bg-slate-50 dark:hover:bg-white/5 transition-colors border-b border-slate-100 dark:border-white/5 group ${p.minutes < 45 ? 'opacity-50' : ''}`}
                      >
                        {/* shirt # */}
                        <td className="py-3 px-5 text-slate-500 text-xs">
                          {String(p.shirt).padStart(2, '0') || '—'}
                        </td>

                        {/* name + captain + sub label */}
                        <td className="py-3 px-2">
                          <div className="flex items-center gap-1.5">
                            <span className="font-body font-bold text-slate-900 dark:text-white group-hover:text-[color:var(--primary-neon)] dark:group-hover:text-primary-container transition-colors text-sm">
                              {p.name}
                            </span>
                            {p.is_captain && (
                              <span className="text-xs font-headline font-bold text-yellow-700 dark:text-yellow-400/80 border border-yellow-600/30 dark:border-yellow-400/30 rounded px-1 py-px">
                                C
                              </span>
                            )}
                            {sub && (
                              <span className="text-xs font-mono text-slate-500">{sub}</span>
                            )}
                          </div>
                        </td>

                        {/* position badge */}
                        <td className={`py-3 px-2 text-xs font-headline font-bold ${cfg.color}`}>
                          {cfg.label}
                        </td>

                        {/* minutes */}
                        <td className="py-3 px-2 text-slate-600 text-xs">{p.minutes}'</td>

                        {/* rating */}
                        <td className={`py-3 px-2 font-bold text-sm ${ratingColor(p.rating)}`}>
                          {p.rating > 0 ? p.rating.toFixed(1) : '—'}
                        </td>

                        {/* G / A badges */}
                        <td className="py-3 px-2">
                          <div className="flex justify-center gap-1">
                            {p.goals > 0 && (
                              <span className="w-5 h-5 flex items-center justify-center rounded-full bg-yellow-400 text-black text-xs font-bold">
                                {p.goals}
                              </span>
                            )}
                            {p.assists > 0 && (
                              <span className="w-5 h-5 flex items-center justify-center rounded-full bg-slate-300 text-black text-xs font-bold">
                                {p.assists}
                              </span>
                            )}
                            {p.goals === 0 && p.assists === 0 && (
                              <span className="text-slate-700 text-xs">—</span>
                            )}
                          </div>
                        </td>

                        {/* xG intensity bar */}
                        <td className="py-3 px-2">
                          <div className="flex items-center gap-3">
                            <div className="flex-1 h-1 bg-slate-200 dark:bg-white/10 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-primary-container shadow-[0_0_8px_#00f0ff] rounded-full transition-all duration-500"
                                style={{ width: `${barPct}%` }}
                              />
                            </div>
                            <span className="text-xs text-slate-600 dark:text-white w-8 text-right shrink-0">
                              {p.xg > 0 ? p.xg.toFixed(2) : '—'}
                            </span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>}

      {/* ── 3 stat cards ── */}
      {!noData && hasStats && (
        <div className="grid grid-cols-3 border-t border-slate-200 dark:border-white/5">
          {[
            {
              icon:  <Target size={32} className="text-primary-container mb-2" />,
              label: '控球主导',
              value: stats.possession ? `${stats.possession}%` : '—',
              sub:   '控球率',
            },
            {
              icon:  <Activity size={32} className="text-secondary-container mb-2" />,
              label: '射门强度',
              value: stats.shot_accuracy ? `${stats.shot_accuracy}%` : '—',
              sub:   `${stats.shots_on_target ?? 0} / ${stats.total_shots ?? 0} 射正`,
            },
            {
              icon:  <TrendingUp size={32} className="text-primary-container mb-2" />,
              label: '预期进球',
              value: stats.xg ? stats.xg.toFixed(2) : '—',
              sub:   `${stats.big_chances ?? 0} 大机会`,
            },
          ].map((card, i) => (
            <div
              key={i}
              className={`p-5 flex flex-col items-center justify-center text-center bg-slate-50/30 dark:bg-white/[0.01] ${i < 2 ? 'border-r border-slate-200 dark:border-white/5' : ''}`}
            >
              {card.icon}
              <span className="text-xs font-headline uppercase tracking-[0.25em] text-slate-600 dark:text-white mb-1">
                {card.label}
              </span>
              <span className="text-2xl font-headline italic font-bold text-slate-900 dark:text-white">
                {card.value}
              </span>
              <span className="text-xs text-slate-600 dark:text-slate-600 mt-0.5">{card.sub}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
