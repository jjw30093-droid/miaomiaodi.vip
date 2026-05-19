export interface Shot {
  x: number;      // 0-100 坐标
  y: number;      // 0-100 坐标
  xg: number;     // 预期进球值
  outcome: 'Goal' | 'Saved' | 'Off Target' | 'Blocked' | string;
  player: string;
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

export interface CloudReportPayload {
  match_id: string;
  report_markdown: string;
  npxg_trend: string;       // JSON stringified: {"home_team": {"overall": [...], "home_only": [...]}, "away_team": {...}}
  shot_map_data: string;    // JSON stringified: {"home_team": {"overall": [...], "home_only": [...]}, "away_team": {...}}
  home_team?:   string;
  away_team?:   string;
  home_icon?:   string;
  away_icon?:   string;
  match_time?:  string;
  league?:      string;
  updated_at?:  string;
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
  inference?: string;
  radarData?: {
    home: RadarDimensions;
    away: RadarDimensions;
  };
  trendData?: TrendPayload | null;
  penetrationData?: {
    homeTeam: AggregatedShotMap;
    awayTeam: AggregatedShotMap;
  } | null;
  fullPitchData?: {
    homeTeamShots: Shot[];
    awayTeamShots: Shot[];
  } | null;
  generatedAt?: string;
}
