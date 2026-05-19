'use client';

import React, { useState } from 'react';
import AlphaLockOverlay from './AlphaLockOverlay';
import EngineSpecsHUD from './EngineSpecsHUD';

type MatchStatus = 'LIVE' | 'FINISHED' | 'UPCOMING' | 'SOON';

interface Report {
  id: number;
  league: string;
  home: string;
  away: string;
  time: string;
  tags: string[];
  lockedCoreData: string;
  isFree: boolean;
  status: MatchStatus;
  liveMinute?: string;
  score?: string;
}

const MOCK_REPORTS: Report[] = [
  {
    id: 1,
    league: 'A-League',
    home: '悉尼FC',
    away: '纽卡斯尔喷气机',
    time: '2026-03-24 16:30',
    tags: ['NPxG Delta: +0.8', '高价值方向捕获'],
    lockedCoreData: '模型推演显示主队在进攻三区的空间剥夺优势极高，结合实时走线，当前市场指数存在明显的介入价值。',
    isFree: false,
    status: 'LIVE',
    liveMinute: "75'",
    score: '2 - 1'
  },
  {
    id: 2,
    league: 'J1 League',
    home: '神户胜利船',
    away: '广岛三箭',
    time: '2026-03-25 18:00',
    tags: ['系统拟合完成', '空间压制显著'],
    lockedCoreData: '进球期望偏离度达 1.2，客队防守模型呈现崩溃迹象，高价值方向指向主场大逆转。',
    isFree: true,
    status: 'SOON',
  },
  {
    id: 3,
    league: 'Premier League',
    home: '阿森纳',
    away: '利物浦',
    time: '2026-03-26 23:30',
    tags: ['EV 模型确认', '市场资金分歧'],
    lockedCoreData: '强强对话中，主队防线容错率较低，市场指数目前偏离了真实的攻守转换效率比，建议关注动态指数的临场修正。',
    isFree: false,
    status: 'UPCOMING',
  },
  {
    id: 4,
    league: 'La Liga',
    home: '皇家马德里',
    away: '马德里竞技',
    time: '2026-03-23 03:00',
    tags: ['历史回溯核准', '预期总利得收敛'],
    lockedCoreData: '本场比赛的最终数据完全符合赛前高价值方向的模型推演，客队的防守密度有效限制了主队的高位逼抢。',
    isFree: false,
    status: 'FINISHED',
    score: '1 - 1'
  }
];

export default function ReportFeed() {
  const [activeDate, setActiveDate] = useState('今 日');
  const [activeStatus, setActiveStatus] = useState('全部');

  const filteredReports = MOCK_REPORTS.filter(report => {
    if (activeStatus === '全部') return true;
    if (activeStatus === '🟢 进行中' && report.status === 'LIVE') return true;
    if (activeStatus === '🟡 即将开赛' && report.status === 'SOON') return true;
    if (activeStatus === '未开赛' && report.status === 'UPCOMING') return true;
    if (activeStatus === '已完赛' && report.status === 'FINISHED') return true;
    return false;
  });

  return (
    <div className="w-full max-w-4xl mx-auto px-4 py-8 flex flex-col gap-6">
      
      {/* Feed 头部标题区 */}
      <div className="flex flex-col gap-2 mb-4 border-b border-slate-800 pb-6 mt-4">
        <h2 className="text-2xl md:text-3xl font-black text-white tracking-tighter uppercase italic flex items-center gap-3">
          QUANTITATIVE <span className="text-cyan-400 not-italic">FEED</span>
        </h2>
        <p className="text-[10px] font-mono text-slate-500 tracking-[0.3em] uppercase">
          实时量化资讯流 · 模型推演追踪
        </p>
      </div>

      <EngineSpecsHUD />

      {/* ── 双轨筛选控制台 ── */}
      <div className="flex flex-col gap-4 mt-2">
        {/* 顶层时间轴 */}
        <div className="flex items-center gap-6 px-2 border-b border-slate-800/50 pb-3">
          {['昨 日', '今 日', '明 日'].map(date => (
            <button
              key={date}
              onClick={() => setActiveDate(date)}
              className={`text-xs font-bold tracking-widest transition-all ${
                activeDate === date 
                  ? 'text-cyan-400 drop-shadow-[0_0_8px_rgba(6,182,212,0.8)] border-b-2 border-cyan-400 -mb-[14px] pb-3' 
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {date}
            </button>
          ))}
        </div>

        {/* 次层状态栏与工具栏 */}
        <div className="flex items-center justify-between mt-2">
          <div className="flex items-center gap-2 overflow-x-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none] pb-1">
            {['全部', '🟢 进行中', '🟡 即将开赛', '未开赛', '已完赛'].map(status => (
              <button
                key={status}
                onClick={() => setActiveStatus(status)}
                className={`flex-shrink-0 px-4 py-1.5 rounded-full text-[10px] font-black tracking-widest transition-all border ${
                  activeStatus === status
                    ? 'bg-slate-800 border-cyan-500/50 text-cyan-400 shadow-[0_0_15px_rgba(6,182,212,0.15)]'
                    : 'bg-slate-900/50 border-slate-800 text-slate-400 hover:border-slate-700 hover:text-slate-200'
                }`}
              >
                {status}
              </button>
            ))}
          </div>
          <button className="flex-shrink-0 px-4 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700 text-[10px] font-mono tracking-widest text-slate-300 hover:border-cyan-500/40 transition-all flex items-center gap-2">
            联赛筛选 ▽
          </button>
        </div>
      </div>

      {/* 研报列表流 */}
      <div className="flex flex-col gap-6 mt-4">
        {filteredReports.map(report => {
           // 状态判定：卡片边框与透明度逻辑
           let cardWrapperClasses = "group backdrop-blur-md bg-slate-900/60 border rounded-xl overflow-hidden transition-all duration-300 active:scale-[0.98] ease-out ";
           
           if (report.status === 'LIVE') {
              cardWrapperClasses += "border-emerald-500/30 hover:border-emerald-400/60 shadow-[0_0_20px_rgba(16,185,129,0.15)]";
           } else if (report.status === 'FINISHED') {
              cardWrapperClasses += "border-slate-700/50 hover:border-slate-600 opacity-70";
           } else {
              cardWrapperClasses += "border-cyan-500/20 hover:border-cyan-400/50 shadow-[0_0_25px_rgba(6,182,212,0.15)]";
           }

           // 时间区域 UI (渲染为闭包)
           const renderTime = () => {
              if (report.status === 'LIVE') {
                 return (
                    <span className="text-xs font-mono text-emerald-400 tracking-wider flex items-center gap-1.5 font-bold">
                       <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                       {report.liveMinute}
                    </span>
                 );
              } else if (report.status === 'SOON') {
                 return <span className="text-xs font-mono text-amber-400 tracking-wider font-bold animate-pulse">{report.time}</span>;
              } else if (report.status === 'FINISHED') {
                 return <span className="text-xs font-mono text-slate-500 tracking-wider font-bold">[ FT ]</span>;
              }
              return <span className="text-xs font-mono text-slate-500 tracking-wider">{report.time}</span>;
           };

           // 对阵中间区域 UI (渲染为闭包)
           const renderMiddle = () => {
              if (report.status === 'LIVE') {
                 return <span className="text-2xl font-black text-emerald-400 tracking-tighter mx-4 drop-shadow-[0_0_10px_rgba(16,185,129,0.5)]">{report.score}</span>;
              } else if (report.status === 'FINISHED') {
                 return <span className="text-2xl font-black text-slate-300 tracking-tighter mx-4">{report.score}</span>;
              }
              return <span className="text-slate-600 font-light mx-4 text-sm font-bold uppercase tracking-widest">vs</span>;
           };

           return (
              <div key={report.id} className={cardWrapperClasses}>
                <div className="p-6 md:p-8 flex flex-col md:flex-row md:items-center justify-between gap-6 border-b border-slate-800/50 hover:bg-slate-800/10 transition-colors cursor-default group">
                  <div className="flex flex-col gap-3 flex-1">
                    <div className="flex items-center gap-3">
                      <span className="px-2 py-0.5 bg-slate-800 text-cyan-400 text-[9px] font-black uppercase tracking-widest rounded border border-slate-700">
                        {report.league}
                      </span>
                      {renderTime()}
                    </div>
                    
                    <h3 className="text-lg md:text-xl font-bold flex items-center transition-colors duration-300 text-slate-200">
                      <span className="group-hover:text-cyan-400 transition-colors flex-1 text-right">{report.home}</span>
                      {renderMiddle()}
                      <span className="group-hover:text-cyan-400 transition-colors flex-1 text-left">{report.away}</span>
                    </h3>

                    <div className="flex items-center gap-2 overflow-x-auto snap-x snap-mandatory [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none] pb-1 -mx-2 px-2 mt-4">
                      {report.tags.map((tag, idx) => (
                        <span 
                          key={idx} 
                          className="snap-center shrink-0 text-[10px] font-bold text-slate-400 bg-slate-800/50 px-2 py-1 rounded border border-slate-700/50 flex items-center gap-1.5 shadow-inner"
                        >
                          <span className="w-1 h-1 rounded-full bg-cyan-500/50"></span>
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* 交互引导按钮 */}
                  <div className="shrink-0 flex w-full md:w-auto items-center border-t md:border-t-0 md:border-l border-slate-800 pt-4 md:pt-0 md:pl-6 mt-4 md:mt-0 justify-center">
                    <button className="flex w-full md:w-auto justify-center text-[10px] font-black uppercase tracking-widest text-slate-300 hover:text-cyan-400 px-6 py-3 rounded-lg bg-slate-800/50 border border-slate-700 hover:border-cyan-500/30 transition-all duration-300 group-hover:bg-slate-800 shadow-[0_0_15px_rgba(0,0,0,0.2)]">
                      [ 阅读量化推演 → ]
                    </button>
                  </div>
                </div>

                {/* 模型核心推演区: 使用已完善的无截断 AlphaLockOverlay */}
                <AlphaLockOverlay isLocked={!report.isFree}>
                  <div className="p-6 md:px-8 bg-slate-900/50">
                    <h4 className="text-[10px] font-black uppercase text-cyan-500/70 tracking-widest mb-2 flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse"></span>
                      模型核心推演
                    </h4>
                    <p className="text-sm text-slate-300 leading-relaxed font-light">
                      {report.lockedCoreData}
                    </p>
                  </div>
                </AlphaLockOverlay>
                
              </div>
           );
        })}
      </div>
      
    </div>
  );
}
