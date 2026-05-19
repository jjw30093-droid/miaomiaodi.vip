'use client';

import React from 'react';
import { Star } from 'lucide-react';

/**
 * GlassPickBlock (C1 — 核心推荐玻璃块)
 *
 * 从 Vite `MatchDetails.tsx:24–47, 99–162` 移植。
 * 将 inference 字符串解析为 confidence / label / odds / prob / WDL，
 * 按 CONF_CONFIG 四档（高把握 / 中高把握 / 中把握 / 低把握）渲染带星级 + 荧光
 * 光晕 + 数据格的玻璃块。
 *
 * 期望 inference 格式（由后端 aws_pusher._build_structured_inference 产出）：
 *   【<高把握|中高把握|中把握|低把握>】<label> @<odds> <prob>% (<W>%/<D>%/<L>%)
 *
 * 解析失败时所有字段回落到占位 "—"，仍可渲染但视觉降级。
 *
 * 浅色模式修正（Phase 4 对比度体检）：
 *   - 所有 `text-gray-{5,6,7}00` 在浅色下会 < 3:1 对比度，统一提到 `text-gray-900`
 *   - `bg-black/5` 数据格底在白底玻璃上不可见，改为 `bg-gray-100 dark:bg-white/5`
 */

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
    wdl:  wdlMatch
      ? [wdlMatch[1], wdlMatch[2], wdlMatch[3]]
      : ['—', '—', '—'],
  };
}

interface ConfCfg {
  stars: number;
  color: string;
  glow:  string;
  badge: string;
}

const CONF_CONFIG: Record<string, ConfCfg> = {
  '高把握': {
    stars: 4,
    color: 'text-emerald-700 dark:text-[#00ffb7]',
    glow:  'shadow-[0_0_30px_rgba(0,255,183,0.5)]',
    badge: 'bg-emerald-50 dark:bg-[#00ffb7]/10 border-emerald-300 dark:border-[#00ffb7]/30 text-emerald-700 dark:text-[#00ffb7]',
  },
  '中高把握': {
    stars: 4,
    color: 'text-emerald-700 dark:text-[#00ffb7]',
    glow:  'shadow-[0_0_30px_rgba(0,255,183,0.4)]',
    badge: 'bg-emerald-50 dark:bg-[#00ffb7]/10 border-emerald-300 dark:border-[#00ffb7]/30 text-emerald-700 dark:text-[#00ffb7]',
  },
  '中把握': {
    stars: 3,
    color: 'text-sky-700 dark:text-primary-neon',
    glow:  'shadow-[0_0_20px_rgba(0,240,255,0.4)]',
    badge: 'bg-sky-50 dark:bg-primary-neon/10 border-sky-300 dark:border-primary-neon/30 text-sky-700 dark:text-primary-neon',
  },
  '低把握': {
    stars: 2,
    color: 'text-yellow-700 dark:text-yellow-400',
    glow:  'shadow-[0_0_15px_rgba(250,204,21,0.3)]',
    badge: 'bg-yellow-50 dark:bg-yellow-400/10 border-yellow-300 dark:border-yellow-400/30 text-yellow-700 dark:text-yellow-400',
  },
};

export default function GlassPickBlock({ inference }: { inference: string }) {
  const { confidence, label, odds, prob, wdl } = parseInference(inference);
  const cfg = CONF_CONFIG[confidence] ?? CONF_CONFIG['中把握'];
  const stars = cfg.stars;

  return (
    <div
      className={`relative rounded-2xl p-5 overflow-hidden
                  glass-panel bg-glass-bg border border-border-subtle ${cfg.glow}
                  transition-all duration-500`}
    >
      {/* 背景光晕 */}
      <div className="absolute -top-10 -right-10 w-40 h-40 rounded-full blur-3xl bg-[#00ffb7]/10 pointer-events-none" />
      <div className="absolute -bottom-8 -left-8 w-32 h-32 rounded-full blur-2xl bg-primary-neon/5 pointer-events-none" />

      {/* 顶部：把握度标签 + 星级 */}
      <div className="flex items-center justify-between mb-3 relative z-10">
        <span className={`text-[10px] font-black tracking-[0.3em] uppercase border px-2.5 py-1 rounded-full ${cfg.badge}`}>
          💎 核心推荐
        </span>
        <div className="flex gap-0.5">
          {[...Array(4)].map((_, i) => (
            <Star
              key={i}
              size={10}
              className={
                i < stars
                  ? 'text-emerald-500 dark:text-[#00ffb7] fill-emerald-500 dark:fill-[#00ffb7]'
                  : 'text-gray-300 dark:text-white/15'
              }
            />
          ))}
        </div>
      </div>

      {/* 主推方向 */}
      <div className="relative z-10 mb-3">
        <p className="text-[11px] text-gray-900 dark:text-white/65 uppercase tracking-wider mb-1 font-mono">
          推荐方向
        </p>
        <div className="flex items-baseline gap-3 flex-wrap">
          <span
            className={`text-3xl font-black tracking-tight ${cfg.color} dark:[text-shadow:0_0_15px_currentColor,_0_0_30px_currentColor]`}
          >
            {label || '—'}
          </span>
          {odds && (
            <span className="text-lg font-black text-gray-900 dark:text-white/60">
              @{odds}
            </span>
          )}
        </div>
      </div>

      {/* 数据行：ML 概率 + WDL */}
      <div className="relative z-10 grid grid-cols-2 gap-3">
        <div className="bg-gray-100 dark:bg-white/5 rounded-xl p-3">
          <p className="text-[9px] font-bold text-gray-900 dark:text-white/75 uppercase tracking-wider mb-1">
            模型覆盖率
          </p>
          <p className={`text-xl font-black ${cfg.color}`}>
            {prob ? `${prob}%` : '—'}
          </p>
        </div>
        <div className="bg-gray-100 dark:bg-white/5 rounded-xl p-3">
          <p className="text-[9px] font-bold text-gray-900 dark:text-white/75 uppercase tracking-wider mb-1">
            胜平负 WDL
          </p>
          <p className="text-sm font-mono font-bold text-gray-900 dark:text-white/70">
            {wdl[0]}% / {wdl[1]}% / {wdl[2]}%
          </p>
        </div>
      </div>

      {/* 把握度文字 */}
      {confidence && (
        <div className="relative z-10 mt-3 flex items-center gap-2">
          <span className={`border px-2 py-0.5 rounded-full text-[9px] font-black ${cfg.badge}`}>
            {confidence}
          </span>
        </div>
      )}
    </div>
  );
}
