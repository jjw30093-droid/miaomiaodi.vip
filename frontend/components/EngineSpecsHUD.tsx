import React from 'react';

export default function EngineSpecsHUD() {
  return (
    <div className="w-full bg-slate-900/80 border-y border-cyan-500/20 py-2.5 backdrop-blur-md">
      <div className="max-w-4xl mx-auto px-4 flex flex-wrap items-center justify-between gap-y-2">
        <div className="flex items-center gap-6">
          {/* 品牌引擎标识 */}
          <div className="flex items-center gap-2">
             <span className="text-xs font-mono tracking-[0.2em] text-slate-500 uppercase">CORE:</span>
             <span className="text-xs font-mono tracking-[0.3em] text-white uppercase font-black drop-shadow-[0_0_8px_rgba(255,255,255,0.5)]">
               MIAODI QUANT LABS
             </span>
          </div>

          <div className="h-3 w-px bg-slate-800" />

          {/* 引擎技术栈 */}
          <div className="flex items-center gap-2">
             <span className="text-xs font-mono tracking-[0.2em] text-slate-500 uppercase">ENGINE:</span>
             <span className="text-xs font-mono tracking-[0.1em] text-cyan-500/80 uppercase">
               GEMINI 3.1 PRO + LIGHTGBM
             </span>
          </div>
        </div>

        <div className="flex items-center gap-6">
          {/* 数据湖参数 */}
          <div className="flex items-center gap-2">
             <span className="text-xs font-mono tracking-[0.2em] text-slate-500 uppercase">DATA LAKE:</span>
             <span className="text-xs font-mono tracking-[0.1em] text-cyan-500/80 uppercase">
               85+ LEAGUES / 4.2TB
             </span>
          </div>

          <div className="h-3 w-px bg-slate-800" />

          {/* 延迟参数 */}
          <div className="flex items-center gap-2">
             <span className="text-xs font-mono tracking-[0.2em] text-slate-500 uppercase">LATENCY:</span>
             <span className="text-xs font-mono tracking-[0.1em] text-cyan-500/80 uppercase">
               12ms
             </span>
          </div>
        </div>
      </div>
    </div>
  );
}
