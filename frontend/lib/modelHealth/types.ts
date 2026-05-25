export interface SinglePickWindow {
  window_days: number;
  n_settled: number;
  hits: number;
  hit_rate: number | null;
  roi: number | null;
  visible: boolean;
}

export interface EquityCurvePoint {
  date: string;
  value: number;
}

export interface DirectionTrendPoint {
  date: string;
  acc: number | null;
  n: number;
}

export interface DirectionTrendCurrent {
  acc: number | null;
  hidden: boolean;
  reason: string | null;
}

export interface DirectionTrend {
  wdl: DirectionTrendPoint[];
  ou: DirectionTrendPoint[];
  ah: DirectionTrendPoint[];
  current: {
    wdl: DirectionTrendCurrent;
    ou: DirectionTrendCurrent;
    ah: DirectionTrendCurrent;
  };
}

export interface CalibrationBin {
  bin_center: number;
  predicted: number;
  actual: number;
  n: number;
}

export interface RecentPick {
  match_id: number;
  date: string;
  home: string;
  away: string;
  market: string;
  pick: string | null;
  odds: number | null;
  outcome: 'hit' | 'miss' | 'pending';
  pnl: number | null;
}

export interface TrainingMeta {
  trained_at?: string | null;
  n_samples?: number;
  features?: string[];
  model_versions?: Record<string, string>;
  sample_count?: number;
  features_n?: number;
  accuracy?: number | null;
  auc?: number | null;
  brier?: number | null;
}

export interface DriftStatus {
  status: 'ok' | 'adjusting' | 'unknown';
  adjusting_days: number;
}

export interface BestShowcaseWindow {
  window_days: number;
  n_settled: number;
  hits: number;
  hit_rate: number | null;
  roi: number | null;
  market: string;        // 'all' | 'ou' | 'ah' | 'ou_ah'
  market_label: string;  // '全部' | 'Goals' | 'Spread' | 'Goals+Spread'
}

export interface ModelSnapshotV2 {
  snapshot_date: string | null;
  generated_at: string | null;
  degraded: boolean;
  cold_start?: boolean;
  total_settled?: number;
  single_pick: {
    w7: SinglePickWindow;
    w14: SinglePickWindow;
    w30: SinglePickWindow;
    equity_curve: EquityCurvePoint[];
    best?: BestShowcaseWindow;
    best_equity_curve?: EquityCurvePoint[];
  };
  direction_trend: DirectionTrend | null;
  calibration: CalibrationBin[];
  recent_picks: RecentPick[];
  training_meta: TrainingMeta;
  drift: DriftStatus;
}
