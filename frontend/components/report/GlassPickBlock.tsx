'use client';

import React from 'react';
import { AlertTriangle } from 'lucide-react';
import { translateTeam } from '@/lib/teamNames';

interface ParsedInference {
  confidence: string;
  label: string;
  odds: string;
  prob: string;
  wdl: [string, string, string];
}

function parseInference(inf: string): ParsedInference {
  const confMatch = inf.match(/【([^】]+)】/);
  const confidence = confMatch?.[1] ?? '';
  const rest = inf.replace(/【[^】]+】/, '').trim();
  const oddsMatch = rest.match(/@([\d.]+)/);
  const probMatch = rest.match(/([\d.]+)%/);
  const wdlMatch  = inf.match(/\(([\d.]+)%\/([\d.]+)%\/([\d.]+)%\)/);
  const labelRaw  = rest.split('@')[0].trim();
  return {
    confidence,
    label: labelRaw,
    odds: oddsMatch?.[1] ?? '',
    prob: probMatch?.[1] ?? '',
    wdl:  wdlMatch ? [wdlMatch[1], wdlMatch[2], wdlMatch[3]] : ['—', '—', '—'],
  };
}

const STARS_FOR_CONF: Record<string, number> = {
  '高把握': 5, '中高把握': 4, '中把握': 3, '低把握': 2,
  'HIGH': 5, 'MID': 3, 'LOW': 2, 'SKIP': 1,
};

export function getPickType(inf: string): 'AH' | 'OU' | 'WDL' {
  if (inf.includes('让') || inf.includes('覆盖') || inf.toLowerCase().includes('ah') || inf.toLowerCase().includes('handicap')) return 'AH';
  if (inf.includes('大球') || inf.includes('小球') || inf.includes('≤') || inf.includes('≥') || inf.toLowerCase().includes('over') || inf.toLowerCase().includes('under')) return 'OU';
  return 'WDL';
}

type RowKey = 'home' | 'draw' | 'away';

const ROW_LABEL: Record<RowKey, string> = { home: '主胜', draw: '平局', away: '客胜' };

function classifyDirection(rec?: string | null): string | null {
  if (!rec) return null;
  const r = rec.toLowerCase();
  if (rec.includes('主让') || (rec.includes('让') && rec.includes('主'))) return 'ah_home';
  if (rec.includes('客让') || (rec.includes('让') && rec.includes('客'))) return 'ah_away';
  if (rec.includes('大球') || r.includes('over')) return 'over';
  if (rec.includes('小球') || r.includes('under')) return 'under';
  if (rec.includes('主胜')) return 'home';
  if (rec.includes('客胜')) return 'away';
  if (rec === '平' || rec === '平局') return 'draw';
  return null;
}

const _AHOY_DIRS = new Set(['ah_home', 'ah_away', 'over', 'under']);

interface Props {
  inference: string;
  coreLogic?: string | null;
  keyRisk?: string | null;
  modelHome?: number | null;
  modelDraw?: number | null;
  modelAway?: number | null;
  marketHome?: number | null;
  marketDraw?: number | null;
  marketAway?: number | null;
}

export default function GlassPickBlock({
  inference,
  coreLogic,
  keyRisk,
  modelHome, modelDraw, modelAway,
  marketHome, marketDraw, marketAway,
}: Props) {
  const { confidence, label, odds } = parseInference(inference);
  const pickType = getPickType(inference);
  const stars = STARS_FOR_CONF[confidence] ?? 3;
  const strengthLabel =
    stars >= 5 ? '高' :
    stars >= 4 ? '中高' :
    stars >= 3 ? '中' : '谨慎';

  // Market mini-table: only for WDL when both model and market probs are present
  const recDir = classifyDirection(label || inference);
  const isWdl = pickType === 'WDL';
  const hasModel  = modelHome != null && modelAway != null;
  const hasMarket = marketHome != null && marketAway != null;
  const showMiniTable = isWdl && hasModel && hasMarket && recDir !== null && !_AHOY_DIRS.has(recDir);
  const recRow = showMiniTable ? recDir as RowKey : null;

  const rows: { key: RowKey; market: number; model: number }[] = showMiniTable ? [
    { key: 'home', market: marketHome ?? 0, model: modelHome ?? 0 },
    { key: 'draw', market: marketDraw ?? 0, model: modelDraw ?? 0 },
    { key: 'away', market: marketAway ?? 0, model: modelAway ?? 0 },
  ] : [];

  const recRowData = rows.find(r => r.key === recRow);
  const actualEdge = recRowData ? recRowData.model - recRowData.market : 0;

  const footerText = recRow
    ? actualEdge >= 5
        ? `模型认为市场低估了${ROW_LABEL[recRow]}约 ${actualEdge.toFixed(1)} 个百分点`
      : actualEdge >= 2
        ? `模型对${ROW_LABEL[recRow]}相对市场存在 ${actualEdge.toFixed(1)}pp 的小幅价值`
      : actualEdge >= 0
        ? `模型与市场对${ROW_LABEL[recRow]}估值基本一致（差 ${actualEdge.toFixed(1)}pp）`
      : `模型概率低于市场隐含 ${Math.abs(actualEdge).toFixed(1)}pp`
    : null;

  return (
    <div className="rounded-lg overflow-hidden relative
                    bg-white dark:bg-slate-950
                    border border-slate-200 dark:border-white/15
                    shadow-sm dark:shadow-none
                    p-4 space-y-4">

      {/* Recommendation header */}
      <div className="flex items-center justify-between border-b border-slate-200 dark:border-white/15 pb-3">
        <span className="text-[15px] font-bold text-slate-900 dark:text-white">
          推荐方向
        </span>
        <span className="text-[13px] font-bold text-slate-700 dark:text-slate-200">
          推荐强度：{strengthLabel}
        </span>
      </div>

      {/* Main pick */}
      <div>
        <p className="text-[34px] sm:text-4xl font-black leading-tight tracking-tight
                      text-slate-950 dark:text-white">
          {(() => {
            const [team, ...rest] = label.split(/\s+/);
            return [translateTeam(team), ...rest].filter(Boolean).join(' ') || '—';
          })()}
        </p>
        {odds && (
          <p className="text-[18px] font-bold mt-2 text-slate-800 dark:text-slate-100">
            参考价格：@{odds}
          </p>
        )}
      </div>

      {/* coreLogic — one-line rationale */}
      {coreLogic && (
        <p className="text-[17px] text-slate-900 dark:text-white leading-[1.75]">
          {coreLogic}
        </p>
      )}

      {/* Market mini-table (WDL only when market data exists) */}
      {showMiniTable && (
        <div className="rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-white/15 overflow-hidden">
          {/* Header */}
          <div className="grid grid-cols-[52px_1fr_1fr_1fr] gap-1 px-3 py-2 text-[13px] font-bold text-slate-700 dark:text-slate-200 border-b border-slate-200 dark:border-white/15">
            <span></span>
            <span className="text-right">市场</span>
            <span className="text-right">模型</span>
            <span className="text-right">差值</span>
          </div>
          {/* Rows */}
          {rows.map(({ key, market, model }) => {
            const edge  = model - market;
            const isPos = edge >= 0;
            const isRec = key === recRow;
            return (
              <div
                key={key}
                className={`grid grid-cols-[52px_1fr_1fr_1fr] gap-1 items-center px-3 py-2.5 text-[15px] ${
                  isRec
                    ? 'bg-slate-200 dark:bg-white/10'
                    : ''
                }`}
              >
                <span className={`font-bold ${isRec ? 'text-slate-950 dark:text-white' : 'text-slate-700 dark:text-slate-200'}`}>
                  {ROW_LABEL[key]}
                </span>
                <span className="tabular-nums text-right text-slate-800 dark:text-slate-100">{market.toFixed(1)}%</span>
                <span className="tabular-nums text-right text-slate-900 dark:text-white font-bold">{model.toFixed(1)}%</span>
                <span className={`tabular-nums text-right font-bold inline-flex items-center justify-end gap-0.5 ${
                  isPos ? 'text-emerald-700 dark:text-emerald-300' : 'text-slate-700 dark:text-slate-200'
                }`}>
                  {edge >= 0 ? '+' : ''}{edge.toFixed(1)}%
                </span>
              </div>
            );
          })}
          {/* Footer */}
          {footerText && (
            <div className="px-3 py-2.5 border-t border-slate-200 dark:border-white/15
                            text-[15px] text-slate-900 dark:text-white leading-relaxed">
              {footerText}
            </div>
          )}
        </div>
      )}

      {/* Key risk */}
      {keyRisk && (
        <div className="flex items-start gap-2.5 pt-3 border-t border-slate-200 dark:border-white/15">
          <AlertTriangle size={16} className="text-amber-700 dark:text-amber-300 flex-shrink-0 mt-1" />
          <p className="text-[16px] text-slate-900 dark:text-white leading-relaxed">{keyRisk}</p>
        </div>
      )}
    </div>
  );
}
