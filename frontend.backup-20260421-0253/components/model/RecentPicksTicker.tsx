'use client';
import { ModelHealthData } from './types';
import { useRouter } from 'next/navigation';

interface Props {
  picks: ModelHealthData['recent_picks'];
}

const OUTCOME_STYLES = {
  hit:     'bg-emerald-500/20 border-emerald-500/40 text-emerald-400',
  miss:    'bg-rose-500/20 border-rose-500/40 text-rose-400',
  pending: 'bg-white/5 border-white/10 text-white/40',
};

const OUTCOME_LABEL = {
  hit:     '命中',
  miss:    '踩空',
  pending: '待定',
};

const PICK_LABEL: Record<string, string> = {
  home: '主胜',
  away: '客胜',
  draw: '平局',
  over: '大球',
  under: '小球',
};

export default function RecentPicksTicker({ picks }: Props) {
  const router = useRouter();

  if (!picks || picks.length === 0) {
    return (
      <div className="glass-panel rounded-2xl border border-white/5 p-5">
        <p className="text-[10px] font-black tracking-[0.3em] uppercase text-white/30 mb-3">近期命中记录</p>
        <p className="text-xs text-white/20 font-mono text-center py-4">暂无记录</p>
      </div>
    );
  }

  return (
    <div className="glass-panel rounded-2xl border border-white/5 p-5">
      <div className="flex items-center justify-between mb-3">
        <p className="text-[10px] font-black tracking-[0.3em] uppercase text-white/30">近期命中记录</p>
        <span className="text-[9px] text-white/20 font-mono">最近 14 天 · {picks.length} 场</span>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-2 scrollbar-none" style={{ scrollbarWidth: 'none' }}>
        {picks.map((pick, i) => (
          <button
            key={i}
            onClick={() => pick.match_id && router.push(`/report/${pick.match_id}`)}
            className={`flex-shrink-0 flex flex-col gap-1 px-3 py-2 rounded-xl border transition-all hover:scale-[1.03] ${OUTCOME_STYLES[pick.outcome]}`}
          >
            <div className="flex items-center gap-1.5">
              <span className="text-[9px] font-black uppercase tracking-wider whitespace-nowrap">
                {OUTCOME_LABEL[pick.outcome]}
              </span>
              {pick.pick && (
                <span className="text-[8px] font-bold opacity-70 whitespace-nowrap">
                  {PICK_LABEL[pick.pick] ?? pick.pick}
                </span>
              )}
            </div>
            <span className="text-[9px] font-mono whitespace-nowrap opacity-60">
              {pick.home?.split(' ')[0]} vs {pick.away?.split(' ')[0]}
            </span>
            {pick.odds && (
              <span className="text-[8px] font-mono opacity-50">@{pick.odds.toFixed(2)}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
