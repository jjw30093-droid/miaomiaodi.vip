import Link from 'next/link';
import { Suspense } from 'react';
import nextDynamic from 'next/dynamic';
import { getMatchReport } from '@/lib/fetchReport';
import MarkdownRenderer from '@/components/MarkdownRenderer';
import MatchHeader from '@/components/MatchHeader';
import TacticalRadarChart from '@/components/TacticalRadarChart';
import AIFinalVerdict from '@/components/AIFinalVerdict';
import HalfPitchShotMap from '@/components/HalfPitchShotMap';
import TeamTrendChart from '@/components/TeamTrendChart';
import { BackgroundEffects } from '@/components/BackgroundEffects';
import { ChevronLeft, Info } from 'lucide-react';

const CloudChartSection = nextDynamic(() => import('@/components/CloudChartSection'));

export const dynamic = 'force-dynamic';
export const revalidate = 0;

// 1. 异步内容载体：处理核心数据抓取与渲染
async function ReportContent({ matchId }: { matchId: string }) {
  const report = await getMatchReport(matchId);

  if (!report) {
    return (
      <div className="glass-panel max-w-md w-full p-10 bg-surface-dim/20 text-center backdrop-blur-3xl animate-fade-in shadow-ambient-lift">
        <div className="text-secondary-magenta text-5xl mb-6 opacity-30">⚠️</div>
        <h2 className="text-xl font-headline font-black italic mb-4 tracking-tight uppercase">量化数据流离线</h2>
        <p className="text-zinc-500 text-[10px] mb-8 font-headline font-bold uppercase tracking-widest leading-relaxed opacity-60">
          链路中断 :: 云端同步点无法响应或暂无该场次研报。 <br/>
          请重试或前往 喵弟数据终端 确认。
        </p>
        <Link 
          href="/" 
          className="inline-flex px-8 py-3 rounded-xl bg-white/5 border border-white/5 hover:bg-white/10 transition-all text-[10px] font-headline font-black italic tracking-widest uppercase shadow-ghost-border"
        >
          返回策略中心
        </Link>
      </div>
    );
  }

  // 尝试从标题提取队名 (Fallback)
  let homeTeam = report.homeTeamName;
  let awayTeam = report.awayTeamName;
  
  if (homeTeam === "HOME TEAM" && report.markdownContent) {
    const titleMatch = report.markdownContent.match(/# (.*) vs (.*)/i);
    if (titleMatch) {
      homeTeam = titleMatch[1].trim();
      awayTeam = titleMatch[2].trim();
    }
  }

  return (
    <div className="w-full flex flex-col gap-8 animate-fade-up">
      {/* ── Stitch Header ── */}
      <div className="glass-panel p-4 mb-4 flex items-center justify-between border-white/5">
        <Link href="/" className="flex items-center gap-2 group text-primary-neon/60 hover:text-primary-neon transition-colors">
          <div className="w-8 h-8 rounded-full border border-white/5 flex items-center justify-center bg-white/5 group-hover:-translate-x-1 transition-transform">
            <ChevronLeft size={18} />
          </div>
          <span className="text-[10px] font-black italic tracking-[0.2em] uppercase">BACK TO COMMAND</span>
        </Link>
        
        <div className="flex flex-col items-end">
          <h1 className="text-lg font-black italic tracking-tight text-white/90">
            {homeTeam} <span className="text-primary-neon mx-2">vs</span> {awayTeam}
          </h1>
          <span className="text-[9px] font-black tracking-[0.3em] uppercase text-white/20">QUANT DATA ANALYSIS SNAPSHOT</span>
        </div>
      </div>

      {/* ── Main Command Grid ── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        
        {/* 左列：深度情报 Intelligence (7/12) */}
        <div className="lg:col-span-7 flex flex-col gap-8">
          
          {/* AI 终极裁决 (Hoisted to top) */}
          {report.inference && (
            <div className="animate-fade-in-up">
              <AIFinalVerdict 
                inference={report.inference}
                homeTeamName={homeTeam}
                awayTeamName={awayTeam}
                homeProb={report.homeProb}
                awayProb={report.awayProb}
              />
            </div>
          )}

          {/* 研报正文 */}
          <div className="glass-panel p-6 sm:p-10 border-white/5 relative overflow-hidden">
             <div className="absolute top-0 left-0 w-32 h-32 bg-primary-neon/5 blur-[50px] rounded-full pointer-events-none" />
             <div className="flex items-center gap-3 mb-8 pb-4 border-b border-white/5 relative z-10">
                <div className="w-1.5 h-1.5 rounded-full bg-primary-neon shadow-[0_0_8px_#00F0FF]" />
                <h2 className="text-[11px] font-black tracking-[0.4em] uppercase text-white/40">Neural Analysis Intelligence</h2>
             </div>
             <MarkdownRenderer 
               content={report.markdownContent} 
               homeTeamName={homeTeam}
               awayTeamName={awayTeam}
               fullPitchData={report.fullPitchData}
             />
          </div>
        </div>

        {/* 右列：战术数据 Tactical (5/12) */}
        <div className="lg:col-span-5 flex flex-col gap-8 sticky top-8">
          
          {/* NPxG 历史趋势 */}
          <div className="glass-panel border-white/5 animate-fade-in-right p-6">
            <div className="flex items-center gap-3 mb-6 relative z-10">
                <div className="w-1.5 h-1.5 rounded-full bg-secondary-magenta shadow-[0_0_8px_#FF00E5]" />
                <h2 className="text-[11px] font-black tracking-[0.4em] uppercase text-white/40">Market Potency Trend</h2>
             </div>
             {report.trendData ? (
               <TeamTrendChart 
                 trendData={report.trendData} 
                 homeTeamName={homeTeam} 
                 awayTeamName={awayTeam} 
               />
             ) : (
               <div className="py-20 flex flex-col items-center justify-center text-center opacity-30">
                 <Info className="w-10 h-10 mb-4" />
                 <p className="text-[10px] font-black tracking-widest uppercase">Trend data not synchronized</p>
               </div>
             )}
          </div>

          {/* 进攻穿透图 (Shotmap) */}
          <div className="glass-panel border-white/5 animate-fade-in-right p-6" style={{ animationDelay: '0.2s' }}>
             <div className="flex items-center gap-3 mb-6 relative z-10">
                <div className="w-1.5 h-1.5 rounded-full bg-primary-neon shadow-[0_0_8px_#00F0FF]" />
                <h2 className="text-[11px] font-black tracking-[0.4em] uppercase text-white/40">Incursion Analysis Snapshot</h2>
             </div>
             {report.penetrationData ? (
               <HalfPitchShotMap 
                 penetrationData={report.penetrationData}
                 homeTeamName={homeTeam}
                 awayTeamName={awayTeam}
               />
             ) : (
               <div className="py-20 flex flex-col items-center justify-center text-center opacity-30">
                 <Info className="w-10 h-10 mb-4" />
                 <p className="text-[10px] font-black tracking-widest uppercase">Shot map data in sync queue</p>
               </div>
             )}
          </div>

          {/* 实时同步区 */}
          <div className="glass-panel border-white/10 p-6 bg-primary-neon/[0.02]">
             <CloudChartSection
               matchId={matchId}
               homeTeamName={homeTeam}
               awayTeamName={awayTeam}
             />
          </div>
        </div>
      </div>
    </div>
  );
}

// 2. 页面骨架：提供全屏轴心容器与 Suspense 边界
export default async function ReportPage({ params }: { params: Promise<{ match_id: string }> }) {
  const resolvedParams = await params;
  const matchId = String(resolvedParams.match_id).trim();

  return (
    <main className="relative min-h-screen bg-[#0D0F14] text-white flex flex-col items-center overflow-x-hidden w-full font-body selection:bg-primary-neon/20">
      <BackgroundEffects />

      <div className="relative z-10 w-full max-w-7xl px-5 sm:px-8 lg:px-10 pt-16 pb-20 flex flex-col items-center">
        
        <Suspense fallback={
          <div className="flex flex-col items-center justify-center py-60 gap-8">
            <div className="w-16 h-16 border-2 border-primary-neon/20 border-t-primary-neon rounded-full animate-spin" />
            <p className="text-[11px] font-display font-black text-primary-neon/40 uppercase tracking-[0.5em] animate-pulse">
              NEURAL SYNC :: PROCESSING QUANT DATA
            </p>
          </div>
        }>
          <ReportContent matchId={matchId} />
        </Suspense>

        {/* 底部装饰 */}
        <footer className="mt-24 pt-12 border-t border-white/5 w-full flex justify-between items-center text-[9px] font-headline font-bold text-white/20 uppercase tracking-[0.3em]">
          <span>喵弟量化实验室 :: SYSTEM CORE v6.2.0</span>
          <span>STITCH PROTOCOL SECURED</span>
        </footer>
      </div>
    </main>
  );
}
