'use client';
import { useState } from 'react';
import { ChevronDown } from 'lucide-react';

interface Section {
  title: string;
  content: string;
}

const SECTIONS: Section[] = [
  {
    title: '回测假设',
    content: 'Fixed Stake：每场下注 1 单位，不计复利。Kelly-Half：Kelly 公式计算理论最优仓位，取一半下注，抑制方差。两条曲线均基于 B365 开盘赔率，未考虑滑点与佣金。',
  },
  {
    title: '特征工程',
    content: 'V4 模型使用 52 维特征，涵盖滚动 xG 压迫差值、Elo 评级、场地调整 npxGD、大球赔率隐含概率、休息天数差等。LightGBM 多分类，WDL + OU 双模型独立训练。',
  },
  {
    title: '免责声明',
    content: '所有预测基于历史数据模式，不构成投资建议。足球比赛存在不可预测的随机性，历史回测表现不代表未来收益。请理性看待模型输出，量力而行。',
  },
];

export default function MethodologyAccordion() {
  const [open, setOpen] = useState<number | null>(null);

  return (
    <div className="glass-panel rounded-2xl border border-white/5 overflow-hidden">
      <div className="px-5 pt-4 pb-2 border-b border-white/5">
        <p className="text-xs font-black tracking-[0.3em] uppercase text-white/30">方法论 · Methodology</p>
      </div>
      {SECTIONS.map((s, i) => (
        <div key={i} className="border-b border-white/5 last:border-0">
          <button
            onClick={() => setOpen(open === i ? null : i)}
            className="w-full flex items-center justify-between px-5 py-3.5 text-left hover:bg-white/[0.02] transition-colors"
          >
            <span className="text-xs font-bold text-white/70">{s.title}</span>
            <ChevronDown
              size={14}
              className={`text-white/30 transition-transform ${open === i ? 'rotate-180' : ''}`}
            />
          </button>
          {open === i && (
            <div className="px-5 pb-4">
              <p className="text-xs text-white/40 leading-relaxed font-body">{s.content}</p>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
