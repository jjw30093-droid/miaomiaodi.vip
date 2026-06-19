'use client';

/**
 * WcAhInfoCard — 世界杯亚盘让球信息卡
 *
 * 显示市场隐含让球幅度，用于辅助理解研报里的推荐方向。
 *
 * 仅在 tournamentType === 'wc' 且有让球数据时渲染（上层门控）。
 */

import React from 'react';

interface WcAhInfoCardProps {
  homeTeamName: string;
  awayTeamName: string;
  /** 让球线（负数 = 主队让球；正数 = 客队让球） */
  line: number;
  /** 让球幅度绝对值 */
  magnitude: number;
  /** 提供报价的书商数量 */
  nBooks: number;
}

export default function WcAhInfoCard({
  homeTeamName,
  awayTeamName,
  line,
  magnitude,
  nBooks,
}: WcAhInfoCardProps) {
  const favoredTeam  = line < 0 ? homeTeamName : awayTeamName;
  const underdogTeam = line < 0 ? awayTeamName : homeTeamName;
  const displayLine  = magnitude.toFixed(2).replace(/\.00$/, '').replace(/0$/, '');

  return (
    <div className="rounded-2xl overflow-hidden
                    bg-white/85 backdrop-blur-xl
                    dark:bg-[#0A1220]
                    border border-slate-900/10
                    dark:border dark:border-primary-neon/20
                    shadow-[0_4px_24px_rgba(15,23,42,0.06)]
                    dark:shadow-none
                    p-4 space-y-2">

      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="text-xs font-black tracking-wide text-[#005faf] dark:text-primary-neon">
          亚盘参考
        </span>
        <span className="text-[10px] bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400
                         px-2 py-0.5 rounded-full">
          市场位置
        </span>
      </div>

      {/* Main content */}
      <div className="flex items-center gap-3">
        <div className="flex-1 text-center">
          <div className="text-xs text-slate-500 dark:text-slate-400 mb-0.5">市场隐含让球</div>
          <div className="text-xl font-black text-slate-800 dark:text-slate-100">
            {favoredTeam} <span className="text-[#005faf] dark:text-primary-neon">-{displayLine}</span>
          </div>
          <div className="text-xs text-slate-400 dark:text-slate-500">
            {nBooks} 家书商中位
          </div>
        </div>
      </div>

      {/* Disclaimer */}
      <div className="text-[10px] text-slate-400 dark:text-slate-500 italic border-t border-slate-100 dark:border-slate-800 pt-2">
        市场让球幅度仅供参考，完整判断以研报正文的推荐方向、过程数据和风险提示为准。
      </div>
    </div>
  );
}
