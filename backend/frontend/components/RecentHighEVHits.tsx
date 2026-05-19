import React from 'react';

// Mock 数据：近期高价值捕获 (硬编码自证数据)
const MOCK_HITS = [
  { 
    id: 1, 
    league: 'A-League', 
    match: '悉尼FC vs 纽卡斯尔喷气机', 
    pick: '主让 0.5', 
    ev: '+5.8%', 
    yield: '1.95', 
    status: '✅ HIT' 
  },
  { 
    id: 2, 
    league: 'J1', 
    match: '神户胜利船 vs 广岛三箭', 
    pick: '进球数 > 2.5', 
    ev: '+4.2%', 
    yield: '1.88', 
    status: '✅ HIT' 
  },
  { 
    id: 3, 
    league: 'EPL', 
    match: '阿森纳 vs 利物浦', 
    pick: '客队 +0.25', 
    ev: '+3.7%', 
    yield: '2.05', 
    status: '✅ HIT' 
  },
  { 
    id: 4, 
    league: 'La Liga', 
    match: '皇家马德里 vs 马德里竞技', 
    pick: '主队独赢', 
    ev: '+6.1%', 
    yield: '2.10', 
    status: '✅ HIT' 
  },
  { 
    id: 5, 
    league: 'Serie A', 
    match: '国际米兰 vs 尤文图斯', 
    pick: '下半场进球', 
    ev: '+4.5%', 
    yield: '1.82', 
    status: '✅ HIT' 
  }
];

export default function RecentHighEVHits() {
  return (
    <div className="w-full h-[400px] flex flex-col bg-slate-800/50 backdrop-blur-md border border-slate-700/50 rounded-2xl overflow-hidden shadow-2xl">
      
      {/* 头部标题区域 */}
      <div className="p-4 border-b border-slate-700/50 bg-slate-800/30 flex flex-col gap-1 shrink-0">
        <h3 className="text-xs font-black uppercase text-[#00f3ff] drop-shadow-[0_0_8px_rgba(0,243,255,0.6)] tracking-widest flex items-center gap-2">
          <span>🔥</span> RECENT HIGH-EV HITS
        </h3>
        <p className="text-[10px] text-slate-400 font-mono tracking-widest uppercase">
          近期高价值捕获明细
        </p>
      </div>

      {/* 滚动列表区域 */}
      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none]">
        {MOCK_HITS.map((hit) => (
          <div 
            key={hit.id} 
            className="flex items-center justify-between p-3 rounded-xl bg-slate-800/40 border border-slate-700/30 transition-all duration-300 hover:bg-slate-700/50 hover:border-slate-600/50 group cursor-default"
          >
            
            {/* 左侧：赛事信息 */}
            <div className="flex flex-col gap-1 w-[40%]">
              <span className="text-[9px] font-black text-slate-500 uppercase tracking-wider">{hit.league}</span>
              <span className="text-xs font-bold text-slate-200 truncate group-hover:text-white transition-colors">
                {hit.match}
              </span>
            </div>

            {/* 中侧：模型决策 */}
            <div className="flex flex-col items-center justify-center flex-1">
              <span className="text-[10px] bg-slate-900/60 text-slate-300 px-3 py-1 rounded-md border border-slate-700/50 whitespace-nowrap font-mono tracking-tighter">
                {hit.pick}
              </span>
            </div>

            {/* 右侧：吸睛数据 */}
            <div className="flex flex-col items-end gap-1 shrink-0">
              <div className="flex gap-2 items-center">
                <span className="text-[10px] font-black tracking-tighter bg-green-500/10 text-green-400 px-2 py-0.5 rounded shadow-[0_0_8px_rgba(74,222,128,0.15)]">
                  EV {hit.ev}
                </span>
                <span className="text-[11px] font-black text-amber-400 italic">
                  @{hit.yield}
                </span>
              </div>
              <span className="text-[10px] font-black text-white drop-shadow-[0_0_4px_rgba(255,255,255,0.4)]">
                {hit.status}
              </span>
            </div>

          </div>
        ))}
      </div>

      {/* 底部促单锚点 (CTA) */}
      <div className="p-4 border-t border-slate-700/50 bg-slate-800/80 backdrop-blur-xl shrink-0">
        <button className="w-full py-3.5 rounded-xl bg-gradient-to-r from-cyan-500 to-purple-600 text-white text-sm font-black tracking-wide shadow-[0_4px_20px_-4px_rgba(6,182,212,0.5)] hover:shadow-[0_6px_25px_-4px_rgba(6,182,212,0.7)] hover:scale-[1.02] active:scale-[0.98] transition-all duration-300 flex items-center justify-center gap-2">
          <span>🔒</span> 获取今日高价值信号 <span className="text-[10px] font-mono opacity-80 uppercase ml-1 block mt-0.5">(Unlock Today's Signals)</span>
        </button>
      </div>

    </div>
  );
}
