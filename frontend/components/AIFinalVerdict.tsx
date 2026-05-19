'use client';

import React from 'react';

interface Props {
  inference: string;
  homeTeamName: string;
  awayTeamName: string;
  homeProb?: number;
  awayProb?: number;
}

const AIFinalVerdict: React.FC<Props> = ({ 
  inference, 
  homeProb = 50, 
  awayProb = 50 
}) => {
  const diff = Math.abs(homeProb - awayProb);
  
  let verdict = "多平局倾向";
  let verdictColor = "text-secondary-container";
  let verdictShadow = "drop-shadow-[0_0_30px_rgba(255,0,229,0.4)]";

  if (diff >= 15) {
    verdict = homeProb > awayProb ? "主胜" : "客胜";
    verdictColor = "text-primary-container";
    verdictShadow = "drop-shadow-[0_0_30px_rgba(0,240,255,0.5)]";
  }

  // Risk Level Logic
  let riskLevel = "高";
  let riskColor = "bg-red-500/20 border-red-500/30 text-red-400";
  
  if (diff > 20) {
    riskLevel = "低";
    riskColor = "bg-green-500/20 border-green-500/30 text-green-400";
  } else if (diff >= 10) {
    riskLevel = "中";
    riskColor = "bg-yellow-500/20 border-yellow-500/30 text-yellow-400";
  }

  // Regex highlighting for UPPERCASE words
  const renderInference = (text: string) => {
    const parts = text.split(/([A-Z]{2,}(?:\s[A-Z]{2,})*)/g);
    return parts.map((part, i) => {
      if (part.match(/[A-Z]{2,}(?:\s[A-Z]{2,})*/)) {
        return (
          <strong key={i} className="text-primary-container font-black italic tracking-tight">
            {part}
          </strong>
        );
      }
      return part;
    });
  };

  return (
    <div className="glass-panel p-8 relative overflow-hidden group border border-white/10 shadow-ambient-lift">
      {/* 底部微光叠加 */}
      <div className="absolute inset-0 bg-primary-container/[0.03] pointer-events-none" />
      
      {/* 装饰性背景文字 */}
      <div className="absolute -bottom-6 -right-6 text-9xl font-black italic text-white/[0.02] select-none pointer-events-none tracking-tighter">
        VERDICT 裁决
      </div>

      <div className="relative z-10">
        {/* 标题行 */}
        <div className="flex justify-between items-center mb-8">
          <div className="flex items-center gap-3">
            <span className="text-lg">🧠</span>
            <h3 className="text-xs font-headline font-black italic tracking-[0.4em] text-foreground/60 uppercase">
              AI 最终裁决 :: 决策导向 (Decision Engine)
            </h3>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono font-bold text-primary-container/40 uppercase tracking-widest">系统状态稳定 Stable</span>
            <span className="w-2 h-2 rounded-full bg-primary-container shadow-[0_0_10px_var(--color-primary-container)] animate-pulse" />
          </div>
        </div>

        {/* 主裁决展示 */}
        <div className="mb-10 text-center md:text-left">
          <h2 className={`text-6xl md:text-7xl font-headline font-black italic tracking-tighter uppercase ${verdictColor} ${verdictShadow} animate-fade-in`}>
            {verdict}
          </h2>
          <div className="flex flex-wrap items-center justify-center md:justify-start gap-3 mt-6">
            {/* Confidence Chip */}
            <div className="bg-green-500/20 border border-green-500/30 text-green-400 text-xs font-headline font-black italic px-4 py-1.5 rounded-full tracking-widest uppercase flex items-center gap-2">
              <span className="w-1 h-1 rounded-full bg-green-400 animate-pulse" />
              AI 信心指数: {Math.max(homeProb, awayProb)}%
            </div>
            {/* Risk Level Chip */}
            <div className={`${riskColor} border text-xs font-headline font-black italic px-4 py-1.5 rounded-full tracking-widest uppercase`}>
              风险等级 Risk Level: {riskLevel}
            </div>
          </div>
        </div>

        {/* Inference 正文段落 */}
        <div className="mt-8 pt-8 border-t border-white/5 relative">
          <div className="absolute -top-3 left-4 px-3 bg-background text-xs font-headline font-black italic tracking-widest text-zinc-500 uppercase">
            战术偏移深度解析 (Tactical Shift)
          </div>
          <p className="text-sm font-body leading-relaxed text-zinc-400 max-w-3xl">
            {renderInference(inference)}
          </p>
        </div>
      </div>
    </div>
  );
};

export default AIFinalVerdict;
