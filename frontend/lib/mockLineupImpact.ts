/**
 * @deprecated 2026-04-28. page.tsx 已切换为 report.lineupImpact 真实数据 + graceful degradation。
 * getMockLineupImpact 无其他引用，Safe to delete after 2026-05-15.
 *
 * mockLineupImpact.ts — 首发/伤停攻防贡献 Mock 数据工厂
 *
 * ⚠️ 临时文件：后端 Python 脚本（FotMob 爬虫）接入后：
 *   1. 删除此文件
 *   2. 将 page.tsx 中 `getMockLineupImpact(...)` 替换为 `report.lineupImpact`
 */
import type { LineupImpact, LineupImpactPlayer } from '@/types/report';

// NOTE: offenseScore / defenseScore are now 0-100 integers (backend rank-based min-max).
// Three players intentionally have null scores to exercise the N/A grey bar UI path.
const STARTERS: LineupImpactPlayer[] = [
  { name: 'Raya',        position: 'GK', shirt: 22, status: 'starter', offenseScore: 12,   defenseScore: 82,   hasData: { offense: true,  defense: true  } },
  { name: 'White',       position: 'DF', shirt: 4,  status: 'starter', offenseScore: 41,   defenseScore: 74,   hasData: { offense: true,  defense: true  } },
  { name: 'Saliba',      position: 'DF', shirt: 12, status: 'starter', offenseScore: null, defenseScore: 91,   hasData: { offense: false, defense: true  } }, // ← N/A test: no ATK data
  { name: 'Gabriel',     position: 'DF', shirt: 6,  status: 'starter', offenseScore: 28,   defenseScore: 87,   hasData: { offense: true,  defense: true  } },
  { name: 'Timber',      position: 'DF', shirt: 2,  status: 'starter', offenseScore: 55,   defenseScore: null, hasData: { offense: true,  defense: false } }, // ← N/A test: no DEF data
  { name: 'Partey',      position: 'MF', shirt: 5,  status: 'starter', offenseScore: 48,   defenseScore: 76,   hasData: { offense: true,  defense: true  } },
  { name: 'Rice',        position: 'MF', shirt: 41, status: 'starter', offenseScore: 52,   defenseScore: 83,   hasData: { offense: true,  defense: true  } },
  { name: 'Ødegaard',   position: 'MF', shirt: 8,  status: 'starter', offenseScore: 87,   defenseScore: 55,   hasData: { offense: true,  defense: true  } },
  { name: 'Saka',        position: 'FW', shirt: 7,  status: 'starter', offenseScore: 93,   defenseScore: 44,   hasData: { offense: true,  defense: true  } },
  { name: 'Havertz',     position: 'FW', shirt: 29, status: 'starter', offenseScore: null, defenseScore: null, hasData: { offense: false, defense: false } }, // ← N/A test: no data at all
  { name: 'Martinelli',  position: 'FW', shirt: 11, status: 'starter', offenseScore: 78,   defenseScore: 39,   hasData: { offense: true,  defense: true  } },
];

const ABSENTEES: LineupImpactPlayer[] = [
  { name: 'Zinchenko', position: 'DF', shirt: 35, status: 'injured',   offenseScore: 45, defenseScore: 61, hasData: { offense: true, defense: true }, injuryNote: '肌肉拉伤' },
  { name: 'Jesus',     position: 'FW', shirt: 9,  status: 'injured',   offenseScore: 66, defenseScore: 33, hasData: { offense: true, defense: true }, injuryNote: '膝盖手术恢复中' },
  { name: 'Tomiyasu',  position: 'DF', shirt: 18, status: 'suspended', offenseScore: 32, defenseScore: 58, hasData: { offense: true, defense: true }, injuryNote: '累积黄牌停赛' },
];

const AWAY_STARTERS: LineupImpactPlayer[] = [
  { name: 'Flekken',    position: 'GK', shirt: 1,  status: 'starter', offenseScore: 9,  defenseScore: 79, hasData: { offense: true, defense: true } },
  { name: 'Dunk',       position: 'DF', shirt: 5,  status: 'starter', offenseScore: 18, defenseScore: 85, hasData: { offense: true, defense: true } },
  { name: 'van Hecke',  position: 'DF', shirt: 4,  status: 'starter', offenseScore: 21, defenseScore: 78, hasData: { offense: true, defense: true } },
  { name: 'Igor',       position: 'DF', shirt: 14, status: 'starter', offenseScore: 33, defenseScore: 72, hasData: { offense: true, defense: true } },
  { name: 'Estupiñán',  position: 'DF', shirt: 3,  status: 'starter', offenseScore: 49, defenseScore: 65, hasData: { offense: true, defense: true } },
  { name: 'Gross',      position: 'MF', shirt: 13, status: 'starter', offenseScore: 61, defenseScore: 67, hasData: { offense: true, defense: true } },
  { name: 'Gilmour',    position: 'MF', shirt: 8,  status: 'starter', offenseScore: 44, defenseScore: 71, hasData: { offense: true, defense: true } },
  { name: 'Minteh',     position: 'MF', shirt: 15, status: 'starter', offenseScore: 73, defenseScore: 42, hasData: { offense: true, defense: true } },
  { name: 'Adingra',    position: 'FW', shirt: 29, status: 'starter', offenseScore: 68, defenseScore: 35, hasData: { offense: true, defense: true } },
  { name: 'Welbeck',    position: 'FW', shirt: 18, status: 'starter', offenseScore: 58, defenseScore: 31, hasData: { offense: true, defense: true } },
  { name: 'João Pedro', position: 'FW', shirt: 9,  status: 'starter', offenseScore: 75, defenseScore: 28, hasData: { offense: true, defense: true } },
];

const AWAY_ABSENTEES: LineupImpactPlayer[] = [
  { name: 'Moder',    position: 'MF', shirt: 23, status: 'injured',   offenseScore: 52, defenseScore: 59, hasData: { offense: true, defense: true }, injuryNote: '十字韧带撕裂' },
  { name: 'Ferguson', position: 'FW', shirt: 24, status: 'injured',   offenseScore: 64, defenseScore: 27, hasData: { offense: true, defense: true }, injuryNote: '脚踝扭伤' },
];

export function getMockLineupImpact(
  homeTeamName: string,
  awayTeamName: string,
): LineupImpact {
  return {
    homeTeam: {
      teamName:  homeTeamName,
      starters:  STARTERS,
      absentees: ABSENTEES,
    },
    awayTeam: {
      teamName:  awayTeamName,
      starters:  AWAY_STARTERS,
      absentees: AWAY_ABSENTEES,
    },
  };
}
