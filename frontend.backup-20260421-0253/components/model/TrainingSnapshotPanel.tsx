'use client';
import { ModelHealthData } from './types';
import { Database, Layers, Clock } from 'lucide-react';

interface Props {
  data: ModelHealthData['latest_training'];
}

export default function TrainingSnapshotPanel({ data }: Props) {
  const trainedAt = data.trained_at
    ? new Date(data.trained_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
    : '—';

  return (
    <div className="glass-panel rounded-2xl border border-white/5 p-5">
      <div className="flex items-center justify-between mb-4">
        <p className="text-[10px] font-black tracking-[0.3em] uppercase text-white/30">训练快照</p>
        <div className="flex gap-1.5">
          {Object.entries(data.model_versions).map(([k, v]) => (
            <span key={k} className="px-2 py-0.5 rounded-full bg-primary-neon/10 border border-primary-neon/20 text-[9px] font-black text-primary-neon uppercase tracking-wider">
              {k.toUpperCase()} {v}
            </span>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-1.5 text-white/30">
            <Database size={10} />
            <span className="text-[9px] font-bold uppercase tracking-wider">样本量</span>
          </div>
          <span className="text-lg font-black font-mono text-white tabular-nums">
            {data.sample_count > 0 ? `${data.sample_count.toLocaleString()}` : '—'}
          </span>
        </div>

        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-1.5 text-white/30">
            <Layers size={10} />
            <span className="text-[9px] font-bold uppercase tracking-wider">特征数</span>
          </div>
          <span className="text-lg font-black font-mono text-primary-neon tabular-nums">
            {data.features_n > 0 ? data.features_n : '—'}
          </span>
        </div>

        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-1.5 text-white/30">
            <Clock size={10} />
            <span className="text-[9px] font-bold uppercase tracking-wider">WDL 准确率</span>
          </div>
          <span className="text-lg font-black font-mono text-emerald-400 tabular-nums">
            {data.accuracy != null ? `${(data.accuracy * 100).toFixed(1)}%` : '—'}
          </span>
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-white/5 flex items-center gap-2">
        <span className="w-1 h-1 rounded-full bg-primary-neon animate-pulse" />
        <span className="text-[9px] text-white/20 font-mono">最近训练 {trainedAt}</span>
      </div>
    </div>
  );
}
