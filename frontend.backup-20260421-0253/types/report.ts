export interface Shot {
  x: number;        // X_Coord (0-105, 105 = goal line)
  y: number;        // Y_Coord (0-68)
  xg: number;       // 预期进球值
  outcome: 'Goal' | 'AttemptSaved' | 'Miss' | 'Blocked' | string;
  situation: string; // RegularPlay | FromCorner | SetPiece | FastBreak | FreeKick | Penalty | ...
  player: string;
  minute?: number;
}

/** 单场比赛的射门数据（含对阵信息和分情景统计） */
export interface MatchShotData {
  match_id:         number;
  date:             string;   // "2026-04-06"
  opponent:         string;
  is_home:          boolean;
  result:           string;   // "2-1"
  total_shots:      number;
  situation_counts: Record<string, number>;  // { "RegularPlay": 10, "FromCorner": 3 }
  shots:            Shot[];
}

/** 一支队近 5 场的射门历史（按场次分组） */
export interface TeamShotHistory {
  team_name: string;
  matches:   MatchShotData[];
}

export interface ShotMapData {
  homeTeamName: string;
  awayTeamName: string;
  homeTeamShots: Shot[];
  awayTeamShots: Shot[];
}

export interface MatchTrend {
  opponent: string;
  npxGD: number;
  isHome: boolean;
  date: string;
}

export interface TeamTrendData {
  last5All: MatchTrend[];
  last5HomeAway: MatchTrend[];
}

export interface TrendPayload {
  homeTeam: TeamTrendData;
  awayTeam: TeamTrendData;
}

export interface AggregatedShotMap {
  last5All: Shot[];
  last5HomeAway: Shot[];
}

export interface RadarDimensions {
  attack: number;        // roll_5_npxGD 归一化
  defense: number;       // roll_5_team_goals_prevented 归一化
  possession: number;    // roll_5_field_tilt * 100
  pressing: number;      // 100 / roll_5_ppda（越小越强，取倒数）
  penetration: number;   // roll_5_golden_zone_ratio * 100
  form: number;          // 近5场 npxGD 均值归一化（0-100映射）
}

export interface PlayerStat {
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

export interface TeamMatchStats {
  possession:      number;
  xg:              number;
  total_shots:     number;
  shots_on_target: number;
  shot_accuracy:   number;
  big_chances:     number;
  corners:         number;
  yellow_cards:    number;
}

/** 赛后射门分布（单场真实数据，来自 fact_shotmap） */
export interface PostMatchTeamShots {
  name:   string;
  npxg:   number;
  shots:  Shot[];
}

export interface PostMatchShots {
  homeTeam: PostMatchTeamShots;
  awayTeam: PostMatchTeamShots;
}

export interface CloudReportPayload {
  match_id: string;
  report_markdown: string;
  lineup_brief?: string | null;   // 预计首发+伤停简报（Markdown 格式，公开区）
  npxg_trend: string;       // JSON stringified
  shot_map_data: string;    // JSON stringified
  player_stats?: {
    home_team: PlayerStat[];
    away_team: PlayerStat[];
  };
  team_match_stats?: {
    home_team: TeamMatchStats;
    away_team: TeamMatchStats;
  };
  home_team?:        string;
  away_team?:        string;
  home_icon?:        string;
  away_icon?:        string;
  match_time?:       string;
  league?:           string;
  updated_at?:       string;
  home_prob?:        number;
  away_prob?:        number;
  draw_prob?:        number;
  inference?:        string;
  is_gated?:         boolean;
  is_free?:          boolean;
  match_status?:       string;
  post_match_review?:  string | null;
  post_match_shots?:   PostMatchShots | null;
  /** 后端归一化后的首发/伤停阵容数据（LineupImpact JSON，公开字段，无 VIP gate） */
  lineup_impact_data?: LineupImpact | null;
}

// ─────────────────────────────────────────────────────────────
// LineupImpact — 首发/伤停阵容攻防贡献（结构化接口）
//
// offenseScore / defenseScore：0-100 整数（后端 team rank-based min-max 归一化）
//   null  → 无历史数据（43.2% 空置率场景），前端渲染灰色 N/A 兜底条
//   0-100 → 有数据，hasData.offense / hasData.defense = true
// ─────────────────────────────────────────────────────────────
export type LineupStatus = 'starter' | 'bench' | 'injured' | 'suspended';

export interface LineupImpactPlayer {
  name:         string;
  position:     'GK' | 'DF' | 'MF' | 'FW';
  shirt?:       number | string;
  status:       LineupStatus;
  /** 0-100 整数，无历史数据时为 null */
  offenseScore: number | null;
  /** 0-100 整数，无历史数据时为 null */
  defenseScore: number | null;
  /** 精细粒度 hasData 标志，null score 时 offense/defense 均为 false */
  hasData?:     { offense: boolean; defense: boolean };
  /** 仅 status=injured/suspended 时使用 */
  injuryNote?:  string;
}

export interface LineupImpactTeam {
  teamName:  string;
  starters:  LineupImpactPlayer[];
  absentees: LineupImpactPlayer[];
}

export interface LineupImpact {
  homeTeam: LineupImpactTeam;
  awayTeam: LineupImpactTeam;
  /** 后端元数据：数据覆盖率、归一化方法等 */
  meta?: {
    dataCoverage:        number;
    normalizationMethod: string;
    generatedAt:         string;
    error?:              string;
  };
}

export interface ReportData {
  matchId: string;
  title: string;
  markdownContent: string;
  createdAt: string;
  homeTeamName: string;
  awayTeamName: string;
  homeScore?: number;
  awayScore?: number;
  homeProb?: number;
  awayProb?: number;
  drawProb?: number;
  matchTime?: string;
  league?: string;
  inference?: string;
  radarData?: {
    home: RadarDimensions;
    away: RadarDimensions;
  };
  trendData?: TrendPayload | null;
  /** 新格式：按场次分组的交互式射门数据 */
  shotHistory?: {
    homeTeam: TeamShotHistory;
    awayTeam: TeamShotHistory;
  } | null;
  /** 旧格式兼容（保留供已有组件过渡） */
  penetrationData?: {
    homeTeam: AggregatedShotMap;
    awayTeam: AggregatedShotMap;
  } | null;
  fullPitchData?: {
    homeTeamShots: Shot[];
    awayTeamShots: Shot[];
  } | null;
  playerStats?: {
    home_team: PlayerStat[];
    away_team: PlayerStat[];
  } | null;
  teamMatchStats?: {
    home_team: TeamMatchStats;
    away_team: TeamMatchStats;
  } | null;
  lineupBrief?:      string | null;   // 预计首发+伤停简报（公开区，Markdown 字符串，兜底用）
  /** 结构化首发/伤停攻防贡献数据（后端 Python 脚本下发后替换 lineupBrief） */
  lineupImpact?:     LineupImpact | null;
  generatedAt?:      string;
  matchStatus?:      string;
  postMatchReview?:  string | null;
  postMatchShots?:   PostMatchShots | null;
  /** true = 后端已有研报但权限不足（非"数据未同步"） */
  isGated?:          boolean;
}
