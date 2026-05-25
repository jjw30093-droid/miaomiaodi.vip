'use client';

import { Flame } from 'lucide-react';

interface Props {
  modelHome?: number | null;     // 0-100
  modelDraw?: number | null;
  modelAway?: number | null;
  marketHome?: number | null;    // 0-100 (vig-normalized fair prob)
  marketDraw?: number | null;
  marketAway?: number | null;
  /** Direction parsed from inference, used to highlight the recommended row.
   *  Accepted values: '主胜' | '客胜' | '平' | '平局' | else (no highlight) */
  recommended?: string | null;
}

type RowKey = 'home' | 'draw' | 'away';

const LABEL: Record<RowKey, string> = {
  home: '主胜',
  draw: '平局',
  away: '客胜',
};

function classifyDirection(rec?: string | null): string | null {
  if (!rec) return null;
  const r = rec.toLowerCase();
  // AH — 先于 WDL 检测，避免"客让"被误识别为"客胜"
  if (rec.includes('主让') || (rec.includes('让') && rec.includes('主'))) return 'ah_home';
  if (rec.includes('客让') || (rec.includes('让') && rec.includes('客'))) return 'ah_away';
  // OU
  if (rec.includes('大球') || r.includes('over')) return 'over';
  if (rec.includes('小球') || r.includes('under')) return 'under';
  // WDL fallback
  if (rec.includes('主胜')) return 'home';
  if (rec.includes('客胜')) return 'away';
  if (rec === '平' || rec === '平局') return 'draw';
  return null;
}

const _AHOY_DIRS = new Set(['ah_home', 'ah_away', 'over', 'under']);

export default function MarketVsModelCard({
  modelHome, modelDraw, modelAway,
  marketHome, marketDraw, marketAway,
  recommended,
}: Props) {
  // If neither side has any data, render nothing (graceful degrade)
  const hasModel  = modelHome != null && modelAway != null;
  const hasMarket = marketHome != null && marketAway != null;
  if (!hasModel || !hasMarket) return null;

  // AH/OU 分析时无市场对比数据 → 不渲染此卡片（后端补充 AH/OU 市场概率后再开放）
  const recDir = classifyDirection(recommended);
  if (recDir !== null && _AHOY_DIRS.has(recDir)) return null;

  const recRow = recDir as RowKey | null;

  const rows: { key: RowKey; market: number; model: number }[] = [
    { key: 'home', market: marketHome ?? 0, model: modelHome ?? 0 },
    { key: 'draw', market: marketDraw ?? 0, model: modelDraw ?? 0 },
    { key: 'away', market: marketAway ?? 0, model: modelAway ?? 0 },
  ];

  // Footer caption based on recommended direction's edge
  const recEdge = recRow
    ? rows.find(r => r.key === recRow)!.model - rows.find(r => r.key === recRow)!.market
    : 0;

  const footerText = recRow
    ? recEdge >= 5
        ? `💡 模型认为市场低估了${LABEL[recRow]}约 ${recEdge.toFixed(1)} 个百分点。这是本场分析${LABEL[recRow]}的核心依据。`
      : recEdge >= 2
        ? `💡 模型对${LABEL[recRow]}相对市场存在 ${recEdge.toFixed(1)}pp 的小幅价值，整体估值较为合理。`
      : recEdge >= 0
        ? `💡 模型与市场对${LABEL[recRow]}估值基本一致（仅差 ${recEdge.toFixed(1)}pp），价值有限。`
      : `💡 模型概率低于市场隐含 ${Math.abs(recEdge).toFixed(1)}pp — 分析结论主要基于其他维度信号。`
    : null;

  return (
    <section className="bg-white/85 backdrop-blur-xl dark:bg-[var(--panel-bg-strong)]
                        border border-slate-900/10 dark:border-[var(--panel-border-strong)]
                        rounded-2xl p-5 overflow-hidden">
      {/* 标题 */}
      <div className="flex items-baseline gap-2 mb-4">
        <span className="text-xs font-black tracking-[0.25em] uppercase text-[#005faf] dark:text-[#00F0FF]">
          📊 市场 vs 模型
        </span>
        <span className="text-xs text-slate-500 dark:text-white/50 tracking-wider">价值在哪里</span>
      </div>

      {/* 表头 */}
      <div className="grid grid-cols-[60px_1fr_1fr_1fr] gap-2 text-xs font-bold tracking-wider uppercase
                      text-slate-500 dark:text-white/40 mb-2 px-1">
        <span></span>
        <span className="text-right">市场价格</span>
        <span className="text-right">模型预测</span>
        <span className="text-right">价值差</span>
      </div>

      {/* 行 */}
      <div className="space-y-1.5">
        {rows.map(({ key, market, model }) => {
          const edge      = model - market;
          const isHot     = edge >= 5;
          const isPos     = edge >= 0;
          const isRec     = key === recRow;

          return (
            <div
              key={key}
              className={`grid grid-cols-[60px_1fr_1fr_1fr] gap-2 items-center px-2 py-2 rounded-lg ${
                isRec
                  ? 'bg-[#E91E63]/10 dark:bg-[#00F0FF]/10 ring-1 ring-[#E91E63]/30 dark:ring-[#00F0FF]/30'
                  : ''
              }`}
            >
              <span className={`text-sm font-black ${
                isRec
                  ? 'text-[#E91E63] dark:text-[#00F0FF]'
                  : 'text-slate-700 dark:text-white/80'
              }`}>{LABEL[key]}</span>
              <span className="text-sm font-bold tabular-nums text-right text-slate-700 dark:text-white/70">
                {market.toFixed(1)}%
              </span>
              <span className="text-sm font-bold tabular-nums text-right text-slate-900 dark:text-white">
                {model.toFixed(1)}%
              </span>
              <span className={`text-sm font-black tabular-nums text-right inline-flex items-center justify-end gap-1 ${
                isPos
                  ? 'text-emerald-600 dark:text-emerald-400'
                  : 'text-slate-400 dark:text-white/40'
              }`}>
                {edge >= 0 ? '+' : ''}{edge.toFixed(1)}%
                {isHot && <Flame size={12} className="text-amber-500 dark:text-amber-400" />}
              </span>
            </div>
          );
        })}
      </div>

      {/* 底部解读 */}
      {footerText && (
        <p className="mt-4 px-3 py-2 rounded-lg bg-amber-50/60 dark:bg-amber-400/10
                      border border-amber-200/50 dark:border-amber-400/20
                      text-[12px] leading-relaxed text-amber-900 dark:text-amber-200">
          {footerText}
        </p>
      )}
    </section>
  );
}
