export interface Shot {
  x: number;        // X_Coord (0-105, 105 = goal line)
  y: number;        // Y_Coord (0-68)
  xg: number;       // 预期进球值
  outcome: 'Goal' | 'AttemptSaved' | 'Miss' | 'Blocked' | string;
  situation: string; // RegularPlay | FromCorner | SetPiece | FastBreak | FreeKick | Penalty | ...
  player: string;
  minute?: number;
  period?: string;  // FirstHalf|SecondHalf|FirstHalfExtra|SecondHalfExtra|PenaltyShootout
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
  /** 赛事类型门控：'wc' = 世界杯专用渲染路径；'league' 或 undefined = 联赛 */
  tournament_type?: 'league' | 'wc';
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
  lineup_status?:      'confirmed' | 'predicted' | 'unavailable';
  lineup_confirmed_at?: string | null;
  /** 新手版战绩卡：4 窗口 × 2 类型择优后的最佳组合（None 时前端隐藏整张卡） */
  best_recent_stat?: {
    label:          string;       // "Spread" | "Goals"
    window:         number;       // 5 | 10 | 15 | 20
    wins:           number;
    total:          number;
    hit_rate:       number;       // 50.0 - 100.0
    emoji_sequence: ('hit' | 'miss')[];
  } | null;
  /** 新手版结构化字段（来自 LLM）— 旧研报时为 null */
  beginner_summary?: string | null;
  chart_insights?:   { npxgd?: string; shotmap?: string; lineup_compare?: string; injuries?: string; player_contribution?: string } | null;
  key_variables?:    string[] | null;
  key_risk?:         string | null;
  /** P0：市场隐含概率（vig 已归一化），单位 % */
  market_implied_prob?: { home?: number; draw?: number; away?: number } | null;
  /** WC-only：AH 隐含让球幅度（来自 payload_json.market_implied.ah）*/
  ah_implied?: { line: number; magnitude: number; n_books: number } | null;
  /** WC-only：队伍统计（来自 wc_workflow Agent1 output） */
  wc_team_stats?: { home: Record<string, number | null>; away: Record<string, number | null> } | null;
  /** P0：综合判断卡 — LLM 综合结论段解析后的结构化字段 */
  verdict_summary?: {
    attack_rating?:  { home: number; away: number } | null;
    defense_rating?: { home: number; away: number } | null;
    form_label?:     { home: string; away: string } | null;
    core_logic?:     string | null;
  } | null;
}

// ─────────────────────────────────────────────────────────────
// 新手版战绩卡：从 4 窗口 × 2 类型 = 8 候选中选最优组合
// ─────────────────────────────────────────────────────────────
export interface BestRecentStat {
  label:         string;     // "Spread" | "Goals"
  window:        number;     // 5 | 10 | 15 | 20
  wins:          number;
  total:         number;
  hitRate:       number;     // 50.0 - 100.0
  emojiSequence: ('hit' | 'miss')[];
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
  /** 赛事类型门控：'wc' = 世界杯专用渲染；'league' 或 undefined = 联赛（向下兼容）*/
  tournamentType?: 'league' | 'wc';
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
  /** 首发阵容确认状态（来自爬虫） */
  lineupStatus?:     'confirmed' | 'predicted' | 'unavailable';
  lineupConfirmedAt?: string | null;
  homeIcon?: string | null;
  awayIcon?: string | null;
  /** 新手版战绩卡（Spread/Goals 择优）— null 时前端隐藏整张卡 */
  bestRecentStat?: BestRecentStat | null;
  /** P0：市场隐含概率（vig 归一化） */
  marketImpliedProb?: { home?: number; draw?: number; away?: number } | null;
  /** P0：综合判断卡数据 */
  verdictSummary?: VerdictSummary | null;
  /** P0：来自 LLM json_meta — 关键变量 3 条 */
  keyVariables?: string[] | null;
  /** P0：来自 LLM json_meta — 一句话风险点 */
  keyRisk?: string | null;
  /** 后续 P1：图表解读行 */
  chartInsights?: { npxgd?: string; shotmap?: string; lineupCompare?: string; injuries?: string; playerContribution?: string } | null;
  /** 后续 P0：新手版大白话 */
  beginnerSummary?: string | null;
  /** WC-only：AH 隐含让球幅度（仅信息，无胜率；联赛为 null）*/
  ahImplied?: { line: number; magnitude: number; n_books: number } | null;
  /** WC-only：队伍统计（仅 WC；联赛为 null）*/
  wcTeamStats?: { home: Record<string, number | null>; away: Record<string, number | null> } | null;
  /** WC-only：Sportmonks 第三方模型预测（cc站）*/
  wcCcPredictions?: Record<string, any> | null;
  /** WC-only：预计首发阵容（cc站，22人列表）*/
  wcPredictedLineup?: Array<Record<string, any>> | null;
  /** WC-only：主队近期场次（cc站）*/
  wcHomeRecent?: Array<Record<string, any>> | null;
  /** WC-only：客队近期场次（cc站）*/
  wcAwayRecent?: Array<Record<string, any>> | null;
  /** WC-only：近期对比统计（cc站）*/
  wcRecentCompare?: Record<string, any> | null;
  /** WC-only：历史交锋（cc站）*/
  wcH2h?: Array<Record<string, any>> | null;
  /** P1：长文按 H2 拆段后的 sections — 旧研报无字段时为空 dict */
  markdownSections?: {
    // 新版（AH/OU 导向，2026-04-28+）
    ahAnalysis?:        string;   // 亚盘分析
    ouAnalysis?:        string;   // Goals 进球数分析
    overallComparison?: string;   // 综合战力对比
    // 旧版（WDL 导向，兼容保留）
    powerEvolution?:    string;   // 战力演化分析
    lineupImpact?:      string;   // 阵容影响分析
    tacticalAnalysis?:  string;   // 战术博弈分析
  };
}

// ─────────────────────────────────────────────────────────────
// 综合判断卡（P0）
// ─────────────────────────────────────────────────────────────
export interface VerdictSummary {
  attackRating?:  { home: number; away: number } | null;
  defenseRating?: { home: number; away: number } | null;
  formLabel?:     { home: string; away: string } | null;
  coreLogic?:     string | null;
}
