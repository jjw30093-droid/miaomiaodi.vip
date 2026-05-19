'use client';

import { useState, useMemo } from 'react';
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
  GK: { label: 'GK', color: 'text-yellow-400',            group: 'Goalkeeper'     },
  DF: { label: 'DF', color: 'text-sky-400',                group: 'Defensive Wall' },
  MF: { label: 'MF', color: 'text-[#00dbe9]',             group: 'Engine Room'    },
  FW: { label: 'FW', color: 'text-secondary-container',   group: 'Forward Unit'   },
};
const POS_ORDER = ['GK', 'DF', 'MF', 'FW'];

// ── Helpers ───────────────────────────────────────────────────────────────────
function ratingColor(r: number): string {
  if (r >= 7.5) return 'text-emerald-400';
  if (r >= 6.5) return 'text-white';
  if (r >= 5.0) return 'text-slate-400';
  return 'text-error';
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
      <div className="p-5 border-b border-white/5 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 bg-white/[0.03]">
        <div className="flex items-center gap-3">
          <BarChart3 size={18} className="text-primary-container" />
          <h3 className="font-headline italic font-bold text-sm tracking-[0.15em] uppercase text-white/90">
            Squad Contribution Matrix
          </h3>
          {/* legend */}
          <div className="hidden sm:flex items-center gap-4 ml-2">
            <div className="flex items-center gap-1.5 text-[9px] text-slate-400 font-label uppercase tracking-widest">
              <div className="w-2 h-2 rounded-full bg-yellow-400" />
              Goals
            </div>
            <div className="flex items-center gap-1.5 text-[9px] text-slate-400 font-label uppercase tracking-widest">
              <div className="w-2 h-2 rounded-full bg-slate-300" />
              Assists
            </div>
          </div>
        </div>

        {/* Home / Away tab — shows team name */}
        <div className="flex gap-1 p-1 bg-surface-container-lowest rounded-xl border border-white/5 self-start sm:self-auto">
          {(['home', 'away'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-5 py-1.5 rounded-lg font-headline font-bold text-[10px] uppercase tracking-widest transition-all ${
                activeTab === tab
                  ? 'bg-primary-container text-on-primary-container'
                  : 'text-slate-500 hover:text-white'
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
          <p className="text-[10px] font-headline uppercase tracking-[0.25em] text-slate-400">球员数据同步中</p>
          <p className="text-[9px] text-slate-600">赛后数据处理完成后自动更新</p>
        </div>
      )}

      {/* ── Table ── */}
      {!noData && <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse min-w-[680px]">
          <thead>
            <tr className="bg-surface-container-low/50 text-[10px] font-headline uppercase tracking-[0.2em] text-slate-500 border-b border-white/5">
              <th className="py-4 px-5 w-10">#</th>
              <th className="py-4 px-2">Player Name</th>
              <th className="py-4 px-2">POS</th>
              <th className="py-4 px-2">MIN</th>
              <th className="py-4 px-2">Rating</th>
              <th className="py-4 px-2 text-center">G / A</th>
              <th className="py-4 px-2 w-44">xG Intensity</th>
            </tr>
          </thead>
          <tbody className="font-mono text-sm">
            {POS_ORDER.map(pos => {
              const group = grouped[pos];
              if (!group || group.length === 0) return null;
              const cfg = POS_CONFIG[pos];
              return (
                <>
                  {/* position group header */}
                  <tr key={`group-${pos}`} className="bg-white/[0.02]">
                    <td colSpan={7} className="py-2 px-5 text-[10px] font-headline font-bold uppercase tracking-[0.25em] text-primary-container/50 border-b border-white/5">
                      {cfg.group}
                    </td>
                  </tr>

                  {group.map((p, i) => {
                    const sub    = subLabel(p.minutes);
                    const barPct = maxXG > 0 ? Math.round((p.xg / maxXG) * 100) : 0;
                    return (
                      <tr
                        key={`${p.player_id}-${i}`}
                        className={`hover:bg-white/5 transition-colors border-b border-white/5 group ${p.minutes < 45 ? 'opacity-50' : ''}`}
                      >
                        {/* shirt # */}
                        <td className="py-3 px-5 text-slate-500 text-[11px]">
                          {String(p.shirt).padStart(2, '0') || '—'}
                        </td>

                        {/* name + captain + sub label */}
                        <td className="py-3 px-2">
                          <div className="flex items-center gap-1.5">
                            <span className="font-body font-bold text-white group-hover:text-primary-container transition-colors text-[13px]">
                              {p.name}
                            </span>
                            {p.is_captain && (
                              <span className="text-[9px] font-headline font-bold text-yellow-400/80 border border-yellow-400/30 rounded px-1 py-px">
                                C
                              </span>
                            )}
                            {sub && (
                              <span className="text-[9px] font-mono text-slate-500">{sub}</span>
                            )}
                          </div>
                        </td>

                        {/* position badge */}
                        <td className={`py-3 px-2 text-[10px] font-headline font-bold ${cfg.color}`}>
                          {cfg.label}
                        </td>

                        {/* minutes */}
                        <td className="py-3 px-2 text-slate-400 text-[12px]">{p.minutes}'</td>

                        {/* rating */}
                        <td className={`py-3 px-2 font-bold text-[13px] ${ratingColor(p.rating)}`}>
                          {p.rating > 0 ? p.rating.toFixed(1) : '—'}
                        </td>

                        {/* G / A badges */}
                        <td className="py-3 px-2">
                          <div className="flex justify-center gap-1">
                            {p.goals > 0 && (
                              <span className="w-5 h-5 flex items-center justify-center rounded-full bg-yellow-400 text-black text-[10px] font-bold">
                                {p.goals}
                              </span>
                            )}
                            {p.assists > 0 && (
                              <span className="w-5 h-5 flex items-center justify-center rounded-full bg-slate-300 text-black text-[10px] font-bold">
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
                            <div className="flex-1 h-1 bg-white/10 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-primary-container shadow-[0_0_8px_#00f0ff] rounded-full transition-all duration-500"
                                style={{ width: `${barPct}%` }}
                              />
                            </div>
                            <span className="text-[10px] text-slate-400 w-8 text-right shrink-0">
                              {p.xg > 0 ? p.xg.toFixed(2) : '—'}
                            </span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </>
              );
            })}
          </tbody>
        </table>
      </div>}

      {/* ── 3 stat cards ── */}
      {!noData && hasStats && (
        <div className="grid grid-cols-3 border-t border-white/5">
          {[
            {
              icon:  <Target size={32} className="text-primary-container mb-2" />,
              label: 'Field Dominance',
              value: stats.possession ? `${stats.possession}%` : '—',
              sub:   'Possession',
            },
            {
              icon:  <Activity size={32} className="text-secondary-container mb-2" />,
              label: 'Attack Intensity',
              value: stats.shot_accuracy ? `${stats.shot_accuracy}%` : '—',
              sub:   `${stats.shots_on_target ?? 0} / ${stats.total_shots ?? 0} on target`,
            },
            {
              icon:  <TrendingUp size={32} className="text-primary-container mb-2" />,
              label: 'Expected Goals',
              value: stats.xg ? stats.xg.toFixed(2) : '—',
              sub:   `${stats.big_chances ?? 0} big chances`,
            },
          ].map((card, i) => (
            <div
              key={i}
              className={`p-5 flex flex-col items-center justify-center text-center bg-white/[0.01] ${i < 2 ? 'border-r border-white/5' : ''}`}
            >
              {card.icon}
              <span className="text-[9px] font-headline uppercase tracking-[0.25em] text-slate-500 mb-1">
                {card.label}
              </span>
              <span className="text-2xl font-headline italic font-bold text-white">
                {card.value}
              </span>
              <span className="text-[9px] text-slate-600 mt-0.5">{card.sub}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
