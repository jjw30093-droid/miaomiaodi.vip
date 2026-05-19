import type { ModelSnapshotV2, DirectionTrendPoint, EquityCurvePoint, CalibrationBin, RecentPick } from './types';

// ── deterministic pseudo-random (seeded LCG) ─────────────────────────────────
function seededRng(seed: number) {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) & 0xffffffff;
    return (s >>> 0) / 0xffffffff;
  };
}

// ── date helpers ──────────────────────────────────────────────────────────────
function addDays(base: string, n: number): string {
  const d = new Date(base);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

const START = '2026-03-25';

// ── equity curve: 30 points, 1.00 → ~1.12 with realistic ups/downs ───────────
const equityCurve: EquityCurvePoint[] = (() => {
  const rng = seededRng(42);
  const pts: EquityCurvePoint[] = [];
  let v = 1.0;
  for (let i = 0; i < 30; i++) {
    v = parseFloat((v + (rng() - 0.42) * 0.025).toFixed(4));
    if (v < 0.88) v = 0.88;
    pts.push({ date: addDays(START, i), value: v });
  }
  // nudge last value up to ~1.12 for a positive Hero display
  pts[pts.length - 1].value = 1.118;
  return pts;
})();

// ── direction trend: 30 points each, acc 0.45-0.60 ───────────────────────────
function makeTrend(seed: number, bias: number): DirectionTrendPoint[] {
  const rng = seededRng(seed);
  return Array.from({ length: 30 }, (_, i) => ({
    date: addDays(START, i),
    acc: parseFloat((0.45 + bias + rng() * 0.15).toFixed(3)),
    n: 18 + Math.floor(rng() * 14),
  }));
}

// ── calibration: 10 bins 0.05→0.95 ───────────────────────────────────────────
const calibration: CalibrationBin[] = [
  { bin_center: 0.05, predicted: 0.05, actual: 0.06, n: 22 },
  { bin_center: 0.15, predicted: 0.15, actual: 0.13, n: 45 },
  { bin_center: 0.25, predicted: 0.25, actual: 0.27, n: 63 },
  { bin_center: 0.35, predicted: 0.35, actual: 0.33, n: 81 },
  { bin_center: 0.45, predicted: 0.45, actual: 0.46, n: 97 },
  { bin_center: 0.55, predicted: 0.55, actual: 0.53, n: 88 },
  { bin_center: 0.65, predicted: 0.65, actual: 0.67, n: 72 },
  { bin_center: 0.75, predicted: 0.75, actual: 0.72, n: 54 },
  { bin_center: 0.85, predicted: 0.85, actual: 0.88, n: 31 },
  { bin_center: 0.95, predicted: 0.95, actual: 0.93, n: 12 },
];

// ── recent picks: 15 rows, mixed outcomes ─────────────────────────────────────
const TEAMS = ['曼城', '阿森纳', '利物浦', '切尔西', '热刺', '纽卡斯尔', '埃弗顿', '莱斯特', '维拉', '布伦特福德'];
const MARKETS = ['wdl', 'ou', 'ah'] as const;
const OUTCOMES: RecentPick['outcome'][] = ['hit', 'miss', 'hit', 'hit', 'miss', 'pending', 'hit', 'miss', 'hit', 'hit', 'miss', 'hit', 'pending', 'hit', 'miss'];
const rngPicks = seededRng(99);

const recentPicks: RecentPick[] = Array.from({ length: 15 }, (_, i) => {
  const outcome = OUTCOMES[i];
  const odds = parseFloat((1.80 + rngPicks() * 1.4).toFixed(2));
  const pnl = outcome === 'pending' ? null : outcome === 'hit' ? parseFloat(((odds - 1) * 1000).toFixed(0)) / 10000 : -0.1;
  const market = MARKETS[i % 3];
  const pick = market === 'wdl' ? ['H', 'D', 'A'][i % 3] : market === 'ou' ? (i % 2 === 0 ? 'Over' : 'Under') : `AH${i % 2 === 0 ? '+0.5' : '-0.5'}`;
  return {
    match_id: 10000 + i,
    date: addDays('2026-04-09', i),
    home: TEAMS[i % 10],
    away: TEAMS[(i + 3) % 10],
    market,
    pick,
    odds,
    outcome,
    pnl,
  };
});

// ── assembled snapshot ────────────────────────────────────────────────────────
export const MOCK_SNAPSHOT: ModelSnapshotV2 = {
  snapshot_date: '2026-04-23',
  generated_at: '2026-04-23T05:01:00Z',
  degraded: false,
  cold_start: false,
  total_settled: 6590,

  single_pick: {
    w7: {
      window_days: 7,
      n_settled: 11,
      hits: 4,
      hit_rate: 0.364,
      roi: -0.08,
      visible: false,   // ← "模型调整中" state
    },
    w14: {
      window_days: 14,
      n_settled: 23,
      hits: 13,
      hit_rate: 0.565,
      roi: 0.112,
      visible: true,
    },
    w30: {
      window_days: 30,
      n_settled: 47,
      hits: 27,
      hit_rate: 0.574,
      roi: 0.183,
      visible: true,
    },
    equity_curve: equityCurve,
  },

  direction_trend: {
    wdl: makeTrend(11, 0.04),
    ou:  makeTrend(22, 0.00),   // lower range → triggers hidden
    ah:  makeTrend(33, 0.06),
    current: {
      wdl: { acc: 0.558, hidden: false, reason: null },
      ou:  { acc: 0.421, hidden: true,  reason: 'OU<51%(42.1%)' },  // ← "恢复中"
      ah:  { acc: 0.571, hidden: false, reason: null },
    },
  },

  calibration,

  recent_picks: recentPicks,

  training_meta: {
    trained_at: '2026-04-17T04:09:00Z',
    sample_count: 6590,
    accuracy: 0.576,
    features_n: 52,
    model_versions: { wdl: 'v4', ou: 'v4', ah: 'v1' },
  },

  drift: {
    status: 'adjusting',
    adjusting_days: 2,
  },
};
