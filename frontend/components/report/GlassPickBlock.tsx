'use client';

import React from 'react';
import { Star } from 'lucide-react';

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
  const labelRaw  = rest.split('@')[0].trim().split(/\s+/)[0] ?? '';
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
};

function getPickType(inf: string): 'AH' | 'OU' | 'WDL' {
  if (inf.includes('让') || inf.includes('覆盖') || inf.toLowerCase().includes('ah') || inf.toLowerCase().includes('handicap')) return 'AH';
  if (inf.includes('大球') || inf.includes('小球') || inf.includes('≤') || inf.includes('≥') || inf.toLowerCase().includes('over') || inf.toLowerCase().includes('under')) return 'OU';
  return 'WDL';
}

export default function GlassPickBlock({ inference }: { inference: string }) {
  const { confidence, label, odds, prob, wdl } = parseInference(inference);
  const pickType = getPickType(inference);
  const stars = STARS_FOR_CONF[confidence] ?? 3;

  return (
    <div className="rounded-2xl overflow-hidden relative
                    bg-white/85 backdrop-blur-xl
                    dark:bg-[#0A1220]
                    border border-slate-900/10 dark:border dark:border-[#00F0FF]/25
                    border-l-4 border-l-[#005faf]
                    dark:border-l-[3px] dark:border-l-[#00F0FF]
                    shadow-[0_4px_24px_rgba(15,23,42,0.06)]
                    dark:shadow-[0_0_28px_rgba(0,240,255,0.22)]
                    p-4 space-y-3">

      {/* Badge + Stars */}
      <div className="flex items-center justify-between">
        <span className="text-xs font-black tracking-[0.1em] px-2.5 py-1 rounded-full
                         bg-[#005faf] text-white
                         dark:bg-[#00F0FF] dark:text-[#06080C] dark:border-0
                         dark:shadow-[0_0_12px_rgba(0,240,255,0.5)]">
          核心推荐
        </span>
        <div className="flex gap-0.5">
          {[...Array(5)].map((_, i) => (
            <Star
              key={i}
              size={12}
              className={i < stars
                ? 'text-amber-500 fill-amber-500 dark:text-[#FFB800] dark:fill-[#FFB800] dark:drop-shadow-[0_0_4px_rgba(255,184,0,0.6)]'
                : 'text-slate-300 dark:text-white/20'
              }
            />
          ))}
        </div>
      </div>

      {/* Main pick — 深色模式 cyan 霓虹光晕 */}
      <div>
        <p className="text-4xl font-black leading-tight tracking-tight
                      text-slate-900
                      dark:text-[#00F0FF]
                      dark:[text-shadow:0_0_18px_rgba(0,240,255,0.55),0_0_4px_rgba(0,240,255,0.8)]">
          {label || '—'}
        </p>
        {odds && (
          <p className="text-2xl font-black mt-1
                        text-[#005faf]
                        dark:text-[#00F0FF]
                        dark:[text-shadow:0_0_10px_rgba(0,240,255,0.45)]">
            @{odds}
          </p>
        )}
      </div>

      {/* Data rows */}
      <div className="rounded-xl bg-slate-50 dark:bg-black/30 border border-slate-200 dark:border-white/10
                      divide-y divide-slate-100 dark:divide-white/10">
        <div className="flex items-center justify-between px-3 py-2.5">
          <span className="text-sm text-slate-700 dark:text-white/70 font-semibold">模型覆盖率</span>
          <span className="text-sm font-black text-slate-900 dark:text-white tabular-nums">
            {prob ? `${prob}%` : '—'}
          </span>
        </div>
        <div className="flex items-center justify-between px-3 py-2.5">
          <span className="text-sm text-slate-700 dark:text-white/70 font-semibold">
            {pickType === 'AH' ? '亚盘覆盖率' : pickType === 'OU' ? '大球/小球概率' : '胜/平/负概率'}
          </span>
          <span className="text-sm font-black tabular-nums">
            <span className="text-[#005faf] dark:text-[#00F0FF]">{wdl[0]}%</span>
            <span className="text-slate-400 dark:text-white/30 mx-1">/</span>
            <span className="text-slate-900 dark:text-white">{wdl[1]}%</span>
            <span className="text-slate-400 dark:text-white/30 mx-1">/</span>
            <span className="text-[color:var(--secondary-magenta)] dark:text-[#FF00E5]">{wdl[2]}%</span>
          </span>
        </div>
      </div>
    </div>
  );
}
