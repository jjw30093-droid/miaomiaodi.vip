'use client';
import React from 'react';
import useSWR from 'swr';
import { apiClient } from '@/lib/apiClient';
import EChartWrapper from './EChartWrapper';
import { TrendingUp, Activity, Zap } from 'lucide-react';
import { useTheme } from './ThemeProvider';

const UP = '#10b981'; 
const NEON = '#06b6d4';

const fetcher = async (matchId: string) => {
  try {
    const [quant, market] = await Promise.all([
      apiClient.get<any>(`/quant/${matchId}`),
      apiClient.get<any>(`/market/${matchId}`)
    ]);
    return { quant, market };
  } catch {
    return {
      quant: { winRate: { won: 68, lost: 32 } },
      market: { roi: [5, 12, 18, 14, 25, 22, 31] }
    };
  }
};

export default function Dashboard({ matchId = '4965737' }: { matchId?: string }) {
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const [isMounted, setIsMounted] = React.useState(false);

  React.useEffect(() => {
    setIsMounted(true);
  }, []);
  
  const { data, isLoading } = useSWR(
    `dashboard-${matchId}-${theme}`, () => fetcher(matchId), { revalidateOnFocus: false }
  );

  if (!isMounted || isLoading) return (
    <div className="text-center py-20 font-mono text-[10px] animate-pulse tracking-[0.4em] text-foreground/40">
      ▌ CALCULATING QUANTITATIVE MATRIX...
    </div>
  );
  if (!data) return null;

  const AXIS = {
    axisLine:  { show: false },
    axisLabel: { 
      color: '#fff', 
      fontFamily: 'monospace', 
      fontSize: 10, 
      fontWeight: 900,
      textShadowBlur: 8,
      textShadowColor: 'rgba(255, 255, 255, 0.6)'
    },
    splitLine: { lineStyle: { color: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)', type: 'dashed' as const } },
  };

  const winRateOption = {
    backgroundColor: 'transparent',
    series: [{
      type: 'pie',
      radius: ['65%', '85%'],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 4, borderColor: isDark ? '#05070a' : '#fff', borderWidth: 3 },
      label: {
        show: true, position: 'center',
        formatter: () => `{v|68}\n{t|WIN RATE}`,
        rich: {
          v: { fontSize: 32, fontWeight: 900, color: isDark ? UP : '#4f46e5', fontFamily: 'monospace' },
          t: { fontSize: 8, color: isDark ? '#64748b' : '#94a3b8', fontWeight: 900, padding: [10, 0, 0, 0] }
        }
      },
      data: [
        { value: 68, itemStyle: { color: isDark ? UP : '#4f46e5', shadowBlur: 10, shadowColor: isDark ? UP : 'rgba(79,70,229,0.2)' } },
        { value: 32, itemStyle: { color: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)' } },
      ],
    }],
  };

  const roi = data.market?.roi || [5, 12, 18, 14, 25, 22, 31];
  const roiOption = {
    backgroundColor: 'transparent',
    tooltip: { 
      trigger: 'axis', 
      backgroundColor: isDark ? 'rgba(15, 23, 42, 0.9)' : 'rgba(255, 255, 255, 0.95)', 
      textStyle: { color: isDark ? '#f1f5f9' : '#0f172a' },
      borderColor: isDark ? 'transparent' : '#e2e8f0',
      borderWidth: 1,
      shadowColor: 'rgba(0,0,0,0.05)',
      shadowBlur: 10
    },
    grid: { left: '3%', right: '3%', top: '10%', bottom: '5%', containLabel: true },
    xAxis: { type: 'category', data: ['03-20','03-21','03-22','03-23','03-24','03-25','03-26'], ...AXIS },
    yAxis: { type: 'value', axisLabel: { ...AXIS.axisLabel }, splitLine: AXIS.splitLine, axisLine: { show: false } },
    series: [{
      data: roi, type: 'line', smooth: 0.5, symbol: 'none',
      lineStyle: { width: 4, color: isDark ? UP : '#4f46e5' },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: isDark ? 'rgba(0, 244, 188, 0.15)' : 'rgba(79, 70, 229, 0.1)' }, { offset: 1, color: 'rgba(255, 255, 255, 0)' }],
        },
      },
    }],
  };

  return (
    <div className="flex flex-col gap-10">
      <div className="flex items-center justify-between">
         <h2 className="text-xl font-black tracking-tighter uppercase italic flex items-center gap-4 text-foreground">
           我的看板 <span className="font-normal text-xs not-italic text-neon/60">Personal Dashboard V2</span>
         </h2>
         <div className="flex gap-4">
            <span className="px-4 py-1.5 rounded-full text-[10px] font-black tracking-widest uppercase border border-neon/20 bg-neon/10 text-neon transition-all">全量 (25)</span>
         </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-10">
        <div className="xl:col-span-8 glass-premium rounded-[3rem] p-10 relative overflow-hidden group">
           <div className="flex justify-between items-start mb-10">
              <div className="flex flex-col gap-2">
                 <span className="text-[10px] font-black text-foreground/40 tracking-[0.2em] uppercase">Yield Performance</span>
                 <div className="flex items-center gap-3">
                    <span className="text-4xl font-black text-foreground">+31.2%</span>
                    <span className="text-[10px] px-3 py-1 rounded-xl font-black tracking-widest bg-up/10 text-up">+4.5% TODAY</span>
                 </div>
              </div>
              <div className="flex gap-2">
                 <div className="w-10 h-10 rounded-xl flex items-center justify-center transition-colors border border-foreground/5 bg-foreground/5 text-foreground/40 hover:text-neon"><Zap size={16} /></div>
              </div>
           </div>
           <div className="h-[400px] md:h-[500px] relative"><EChartWrapper option={roiOption} /></div>
        </div>

        <div className="xl:col-span-4 flex flex-col gap-10">
           <div className="glass-premium rounded-[3rem] p-10 flex-1 flex flex-col justify-center items-center gap-10 group">
              <div className="w-52 h-52 flex-shrink-0"><EChartWrapper option={winRateOption} /></div>
              <div className="flex items-center gap-12 text-center">
                 <div className="flex flex-col">
                    <span className="text-[9px] font-black text-foreground/40 tracking-widest uppercase mb-1">Signals</span>
                    <span className="text-2xl font-black text-foreground">1.5K+</span>
                 </div>
                 <div className="flex flex-col border-l border-foreground/10 pl-12">
                    <span className="text-[9px] font-black text-foreground/40 tracking-widest uppercase mb-1">Confidence</span>
                    <span className="text-2xl font-black text-neon">82%</span>
                 </div>
              </div>
           </div>

           <div className="grid grid-cols-2 gap-10">
              <QuickStat label="Y-23" labelSub="当日盈利" value="Profit" color="text-up" />
              <QuickStat label="-0.23%" labelSub="当前ROI" value="ROI Meter" color="text-down" />
           </div>
        </div>
      </div>
    </div>
  );
}

const QuickStat = ({ label, labelSub, value, color }: any) => (
  <div className="glass-premium rounded-[2.5rem] p-8 flex flex-col justify-between hover:scale-[1.05] transition-all cursor-crosshair group h-40">
     <div className="flex justify-between items-start mb-4">
        <div className={`text-sm font-black ${color}`}>{label}</div>
        <div className="p-2 rounded-lg border border-foreground/5 bg-foreground/5 text-foreground/20 group-hover:text-neon"><TrendingUp size={14} /></div>
     </div>
     <div className="flex flex-col">
        <div className="text-[9px] font-black tracking-widest uppercase mb-1 text-foreground/40">{labelSub}</div>
        <div className="text-[10px] font-black text-foreground/20 uppercase tracking-widest opacity-40">{value}</div>
     </div>
  </div>
);
