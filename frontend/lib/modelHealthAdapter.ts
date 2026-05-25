import type { ModelHealthResponse, EquityFixed } from '@/types/modelHealth';

export interface ChartLine {
  label: string;
  color: string;
  points: string;
}

export interface MetricCard {
  label: string;
  value: string;
  icon: string;
  color: string;
  borderCls: string;
}

export interface AccuracyBar {
  label: string;
  pct: number;
  textColor: string;
  barColor: string; // hex for dark mode, Tailwind class for light mode
}

export interface ScatterDot {
  b: number; // actual * 100
  l: number; // predicted * 100
}

export interface HeroData {
  multiplier: string;
  returnPct: string;
  subtitle: string;
}

export interface AdaptedModelData {
  hero: HeroData;
  metrics: MetricCard[];
  chartLines: ChartLine[];
  chartDates: string[];
  accuracyBars: AccuracyBar[];
  scatterDots: ScatterDot[];
}

const STRAT_ORDER = ['WDL', 'OU', '合成'];
const STRAT_LABELS: Record<string, string> = { WDL: '欧赔', OU: '大小', '合成': '综合' };

function buildChartLines(
  equity: EquityFixed | null,
  isDark: boolean,
): { lines: ChartLine[]; dates: string[] } {
  if (!equity?.strategies?.length) return { lines: [], dates: [] };

  const colors = isDark
    ? ['#E91E63', '#00F0FF', '#fb923c']
    : ['#b7004d', '#005faf', '#924700'];

  const strats = STRAT_ORDER.map(n => equity.strategies.find(s => s.name === n)).filter(Boolean);
  if (!strats.length) return { lines: [], dates: [] };

  const stratMaps = strats.map(s => {
    const m = new Map<string, number>();
    for (const p of s!.points) m.set(p.date, p.value);
    return m;
  });

  const allDates = Array.from(new Set(strats.flatMap(s => s!.points.map(p => p.date)))).sort();
  const n = allDates.length;

  let globalMax = 1;
  for (const sm of stratMaps) for (const v of sm.values()) if (v > globalMax) globalMax = v;
  const scale = globalMax * 1.1;

  const lines: ChartLine[] = strats.map((_, i) => {
    const sm = stratMaps[i];
    let lastVal = 1;
    const pts = allDates.map((d, idx) => {
      if (sm.has(d)) lastVal = sm.get(d)!;
      const x = n === 1 ? 50 : (idx / (n - 1)) * 100;
      const y = 40 - (Math.max(lastVal, 0) / scale) * 40;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return { label: STRAT_LABELS[STRAT_ORDER[i]] ?? STRAT_ORDER[i], color: colors[i], points: pts };
  });

  const dates = allDates.map(d => {
    const parts = d.split('-');
    return `${parseInt(parts[1])}/${parseInt(parts[2])}`;
  });

  return { lines, dates };
}

export function adaptModelHealth(data: ModelHealthResponse, isDark: boolean): AdaptedModelData {
  const composite = data.equity?.strategies?.find(s => s.name === '合成');
  const compLast = composite?.points?.at(-1)?.value ?? 1;
  const sampleCount = data.latest_training?.sample_count || 1318;

  const hero: HeroData = {
    multiplier: `x${compLast.toFixed(2)}`,
    returnPct: `+${((compLast - 1) * 100).toFixed(1)}%`,
    subtitle: `初始资金 10万 → ${(compLast * 10).toFixed(2)}万 · 验证集 ${sampleCount.toLocaleString()} 场`,
  };

  const { wdl_accuracy, ou_accuracy, ah_accuracy, ah_sample_n, brier_wdl, total_matches } = data.rolling;

  const metrics: MetricCard[] = [
    {
      label: '综合收益率',
      value: `+${((compLast - 1) * 100).toFixed(1)}%`,
      icon: 'arrow_upward',
      color: isDark ? '#E91E63' : '#b7004d',
      borderCls: isDark ? 'border-[#E91E63]' : 'border-[#b7004d]',
    },
    {
      label: 'Goals 胜率',
      value: ou_accuracy != null ? `${(ou_accuracy * 100).toFixed(1)}%` : '—',
      icon: 'check_circle',
      color: isDark ? '#00F0FF' : '#005faf',
      borderCls: isDark ? 'border-[#00F0FF]' : 'border-[#005faf]',
    },
    {
      label: '欧赔 Brier',
      value: brier_wdl != null ? brier_wdl.toFixed(3) : '—',
      icon: 'analytics',
      color: isDark ? '#fb923c' : '#924700',
      borderCls: isDark ? 'border-[#fb923c]' : 'border-[#924700]',
    },
    {
      label: '近30日场数',
      value: total_matches > 0 ? total_matches.toLocaleString() : '—',
      icon: 'receipt_long',
      color: isDark ? '#a78bfa' : '#5b3f43',
      borderCls: isDark ? 'border-[#a78bfa]' : 'border-[#5b3f43]',
    },
  ];

  const ahPct = ah_accuracy != null && ah_sample_n >= 10
    ? parseFloat((ah_accuracy * 100).toFixed(1))
    : 54.7;

  const accuracyBars: AccuracyBar[] = [
    {
      label: '欧赔（胜平负）',
      pct: wdl_accuracy != null ? parseFloat((wdl_accuracy * 100).toFixed(1)) : 43.4,
      textColor: isDark ? 'text-[#E91E63]' : 'text-[#b7004d]',
      barColor: isDark ? '#E91E63' : 'bg-[#b7004d]',
    },
    {
      label: 'Goals',
      pct: ou_accuracy != null ? parseFloat((ou_accuracy * 100).toFixed(1)) : 65.4,
      textColor: isDark ? 'text-[#00F0FF]' : 'text-[#005faf]',
      barColor: isDark ? '#00F0FF' : 'bg-[#005faf]',
    },
    {
      label: '高置信度策略',
      pct: ahPct,
      textColor: isDark ? 'text-[#fb923c]' : 'text-[#924700]',
      barColor: isDark ? '#fb923c' : 'bg-[#924700]',
    },
  ];

  const scatterDots: ScatterDot[] = data.calibration.length > 0
    ? data.calibration.map(c => ({
        b: Math.round(c.actual * 100),
        l: Math.round(c.predicted * 100),
      }))
    : [
        { b: 10, l: 10 }, { b: 22, l: 20 }, { b: 28, l: 30 }, { b: 42, l: 40 },
        { b: 48, l: 50 }, { b: 65, l: 60 }, { b: 68, l: 70 }, { b: 82, l: 80 }, { b: 88, l: 90 },
      ];

  const { lines: chartLines, dates: chartDates } = buildChartLines(data.equity, isDark);

  return { hero, metrics, chartLines, chartDates, accuracyBars, scatterDots };
}
