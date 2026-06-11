'use client';

/**
 * WcProjectedLineupTable
 * 世界杯「预计首发简报」组件
 * 数据来自 wc_predicted_lineup（cc站 Sportmonks 数据）
 * 按主客队分列，显示号码/位置/球员中文名
 * 仅在 tournamentType==='wc' 且 wcPredictedLineup 非空时渲染
 */

interface LineupPlayer {
  team_sportmonks_id?: number;
  player_name?: string;
  player_name_zh?: string;
  jersey_number?: number | null;
  position?: string;
  formation_position?: string | null;
  confidence?: number | null;
}

interface Props {
  wcPredictedLineup: LineupPlayer[] | null | undefined;
  homeTeam: string;
  awayTeam: string;
  homeTeamId?: number | null;
  awayTeamId?: number | null;
}

// 简化位置名称为中文
const POS_ZH: Record<string, string> = {
  G: '门将', GK: '门将', goalkeeper: '门将',
  D: '后卫', CB: '中卫', LB: '左后', RB: '右后', WB: '边后',
  M: '中场', CM: '中场', DM: '后腰', AM: '前腰', LM: '左中', RM: '右中',
  F: '前锋', FW: '前锋', ST: '中锋', LW: '左翼', RW: '右翼', SS: '影锋',
  defender: '后卫', midfielder: '中场', attacker: '前锋',
};

function posZh(pos?: string): string {
  if (!pos) return '—';
  return POS_ZH[pos.toUpperCase()] ?? POS_ZH[pos.toLowerCase()] ?? pos;
}

function playerName(p: LineupPlayer): string {
  return p.player_name_zh || p.player_name || '—';
}

export default function WcProjectedLineupTable({
  wcPredictedLineup,
  homeTeam,
  awayTeam,
  homeTeamId,
  awayTeamId,
}: Props) {
  if (!wcPredictedLineup || wcPredictedLineup.length === 0) return null;

  // 按主客队分组，只取首发 11 人
  let homePlayers: LineupPlayer[];
  let awayPlayers: LineupPlayer[];

  if (homeTeamId && awayTeamId) {
    homePlayers = wcPredictedLineup
      .filter(p => p.team_sportmonks_id === homeTeamId)
      .slice(0, 11);
    awayPlayers = wcPredictedLineup
      .filter(p => p.team_sportmonks_id === awayTeamId)
      .slice(0, 11);
  } else {
    // 若无 team_id，平分 22 人
    homePlayers = wcPredictedLineup.slice(0, 11);
    awayPlayers = wcPredictedLineup.slice(11, 22);
  }

  if (homePlayers.length === 0 && awayPlayers.length === 0) return null;

  const renderTeamTable = (players: LineupPlayer[], teamName: string) => (
    <div className="flex-1 min-w-0">
      <p className="text-xs font-bold text-stone-700 dark:text-zinc-300 mb-2">{teamName}</p>
      {players.length === 0 ? (
        <p className="text-xs text-stone-500 dark:text-zinc-500">阵容待公布</p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-stone-500 dark:text-zinc-500 border-b border-zinc-800">
              <th className="text-left pb-1 pr-2 w-8">#</th>
              <th className="text-left pb-1 pr-2 w-12">位置</th>
              <th className="text-left pb-1">球员</th>
            </tr>
          </thead>
          <tbody>
            {players.map((p, i) => (
              <tr key={i} className="border-b border-zinc-800/50">
                <td className="py-1 pr-2 text-stone-500 dark:text-zinc-500 font-mono">
                  {p.jersey_number ?? '—'}
                </td>
                <td className="py-1 pr-2 text-stone-500 dark:text-zinc-400">{posZh(p.position)}</td>
                <td className="py-1 text-zinc-200">{playerName(p)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );

  return (
    <div className="rounded-xl border border-stone-200 bg-white dark:border-zinc-700/40 dark:bg-zinc-900/60 p-4 mt-4">
      <h3 className="text-sm font-bold text-stone-700 dark:text-zinc-300 mb-3">
        ⚽ 预计首发简报
      </h3>
      <div className="flex gap-4 flex-col sm:flex-row">
        {renderTeamTable(homePlayers, homeTeam)}
        <div className="w-px bg-zinc-800 hidden sm:block" />
        {renderTeamTable(awayPlayers, awayTeam)}
      </div>
      <p className="mt-3 text-[10px] text-stone-500 dark:text-zinc-500">
        首发为赛前预测阵容，以实际出场为准。
      </p>
    </div>
  );
}
