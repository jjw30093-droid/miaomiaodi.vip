import React from 'react';

export default function AlphaLockOverlay({ 
  children, 
  isLocked 
}: { 
  children: React.ReactNode, 
  isLocked: boolean 
}) {
  if (!isLocked) return <>{children}</>;

  return (
    <div className="grid group min-h-[160px]">
      {/* 模糊内容层: 使用 Grid 堆叠，作为底层高度支撑 */}
      <div className="col-start-1 row-start-1 blur-lg opacity-20 select-none pointer-events-none transition-all duration-500 [mask-image:linear-gradient(to_bottom,black_70%,transparent_100%)]">
        {children}
      </div>
      
      {/* 付费锁 UI 层: 同样位于 col-start-1 row-start-1，叠加在内容层上方 */}
      <div className="col-start-1 row-start-1 z-10 flex flex-col items-center justify-center bg-slate-900/85 backdrop-blur-lg p-4 md:p-6 text-center">
        {/* 锁图标容器 */}
        <div className="w-10 h-10 rounded-full bg-slate-900 border border-cyan-500/20 flex items-center justify-center mb-4 shadow-[0_0_20px_rgba(6,182,212,0.1)]">
          <span className="text-base">🔒</span>
        </div>

        <h4 className="text-xs font-black text-slate-300 tracking-[0.2em] mb-1 uppercase">
          核心模型推演与指数分析已锁定
        </h4>
        <p className="text-xs text-slate-600 font-mono tracking-[0.3em] mb-6 uppercase">
          [ AUTH_REQUIRED :: LEVEL_PRO ]
        </p>

        {/* 机器接口风格大胶囊按钮 (移动端优化) */}
        <button className="w-full max-w-[280px] py-3.5 mt-2 rounded-2xl font-black text-xs uppercase tracking-[0.2em] bg-cyan-500 text-slate-900 shadow-[0_0_20px_rgba(6,182,212,0.4)] active:scale-95 transition-all">
          升级 PRO 解锁
        </button>
      </div>
    </div>
  );
}
