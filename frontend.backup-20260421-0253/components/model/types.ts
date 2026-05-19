export interface EquityPoint {
  date: string;
  value: number;
}

export interface EquityStrategy {
  name: string;
  color: string;
  points: EquityPoint[];
}

export interface EquityBlock {
  strategies: EquityStrategy[];
  sharpe: number;
  max_drawdown: number;
}

export interface ModelHealthData {
  latest_training: {
    trained_at: string | null;
    sample_count: number;
    accuracy: number | null;
    auc: number | null;
    brier: number | null;
    features_n: number;
    model_versions: { wdl: string; ou: string; ah: string };
  };
  rolling: {
    window: number;
    wdl_accuracy: number | null;
    ou_accuracy: number | null;
    ah_accuracy: number | null;
    ah_sample_n: number;
    brier_wdl: number | null;
    brier_ou: number | null;
    total_matches: number;
    drift_alert: boolean;
  };
  equity: {
    fixed: EquityBlock;
    kelly_half: EquityBlock;
    updated_at: string;
  };
  recent_picks: Array<{
    match_id: string;
    date: string;
    home: string;
    away: string;
    pick: string | null;
    odds: number | null;
    outcome: 'hit' | 'miss' | 'pending';
    pnl: number;
  }>;
  calibration: Array<{
    bin_center: number;
    predicted: number;
    actual: number;
    n: number;
  }>;
}
