'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkUnwrapImages from 'remark-unwrap-images';
import HorizontalFullPitchShotMap from './HorizontalFullPitchShotMap';
import { Shot } from '@/types/report';

interface Props {
  content: string;
  homeTeamName?: string;
  awayTeamName?: string;
  fullPitchData?: {
    homeTeamShots: Shot[];
    awayTeamShots: Shot[];
  } | null;
}

export default function MarkdownRenderer({ content, homeTeamName, awayTeamName, fullPitchData }: Props) {
  return (
    <article className="prose prose-zinc max-w-none 
      prose-headings:font-headline prose-headings:italic prose-headings:tracking-tighter
      prose-h1:text-primary-container prose-h1:text-4xl prose-h1:mb-10 prose-h1:font-black
      prose-h2:text-foreground prose-h2:mt-12 prose-h2:mb-6 prose-h2:pb-4 prose-h2:border-b prose-h2:border-white/5
      prose-h3:text-foreground prose-h3:mt-8 prose-h3:mb-4 prose-h3:font-bold
      prose-p:text-foreground/80 prose-p:font-body prose-p:leading-relaxed prose-p:mb-6 prose-p:text-[15px]
      prose-strong:text-foreground prose-strong:font-bold
      prose-ul:list-none prose-ul:pl-0
      prose-li:relative prose-li:pl-6 prose-li:mb-3 prose-li:text-foreground/80
      prose-hr:border-white/5
      prose-blockquote:border-l-4 prose-blockquote:border-primary-container/40 prose-blockquote:bg-surface-dim/40 prose-blockquote:py-1 prose-blockquote:px-6 prose-blockquote:rounded-r-3xl prose-blockquote:italic prose-blockquote:text-foreground/70
    ">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkUnwrapImages]}
        components={{
          // 自定义列表点样式
          li: ({ node, ...props }) => (
            <li {...props} className="relative pl-6 mb-3 before:content-[''] before:absolute before:left-0 before:top-[0.7em] before:w-1.5 before:h-1.5 before:bg-primary-container before:rounded-full before:shadow-[0_0_10px_var(--color-primary-container)]" />
          ),
          // 表格容器：横向滚动 + 紧凑边距
          table: ({ node, ...props }) => (
            <div className="overflow-x-auto -mx-1 my-3 not-prose">
              <table className="w-full text-[11px] border-collapse" {...props} />
            </div>
          ),
          thead: ({ node, ...props }) => (
            <thead className="border-b border-white/10" {...props} />
          ),
          th: ({ node, ...props }) => (
            <th className="py-2 px-3 text-left font-black text-white/60 dark:text-white/60 text-gray-700 uppercase tracking-wider text-[9px]" {...props} />
          ),
          tr: ({ node, ...props }) => (
            <tr className="border-b border-white/5 hover:bg-white/[0.03] transition-colors" {...props} />
          ),
          // td: 第一列标签色，其余 monospace；bold 内容高亮绿色
          td: ({ node, children, ...props }) => (
            <td className="py-2 px-3 text-gray-700 dark:text-white/70 font-mono text-[11px]" {...props}>
              {children}
            </td>
          ),
          // bold 文本 → 绿色高亮（价值正向方向 / 命中统计）
          strong: ({ node, ...props }) => (
            <strong className="text-emerald-600 dark:text-[#00ffb7] font-bold not-italic" {...props} />
          ),
          // 图片路径防御与展示装饰器
          img: ({ node, src, alt, ...props }) => {
            const imgSrc = typeof src === 'string' ? src : '';
            const imgAlt = typeof alt === 'string' ? alt : '';
            
            // 拦截核心：如果是复盘射门分布图，且有真实数据，则渲染动态组件
            if (imgAlt.includes('射门地图') && fullPitchData) {
              return (
                <div className="my-16">
                  <HorizontalFullPitchShotMap 
                    homeTeamName={homeTeamName || 'Home'}
                    awayTeamName={awayTeamName || 'Away'}
                    homeTeamShots={fullPitchData.homeTeamShots}
                    awayTeamShots={fullPitchData.awayTeamShots}
                  />
                  <p className="mt-4 text-center text-[10px] text-zinc-500 font-headline font-bold tracking-[0.3em] uppercase opacity-60">
                    交互式空间分析 :: 基于 Opta 引擎全校准数据
                  </p>
                </div>
              );
            }

            const isLocalPath = imgSrc.startsWith('file:///');
            
            return (
              <div className="my-12 p-3 glass-panel overflow-hidden shadow-ambient-lift transition-transform hover:scale-[1.005]">
                <div className="relative aspect-video bg-surface-dim/80 rounded-2xl flex items-center justify-center overflow-hidden">
                  {isLocalPath ? (
                    <div className="flex flex-col items-center justify-center text-zinc-500 p-8 text-center">
                      <span className="text-5xl mb-6 opacity-30">📊</span>
                      <p className="text-sm font-headline font-black italic text-foreground mb-2">{alt || '数据可视化分析'}</p>
                      <p className="text-[10px] tracking-[0.3em] uppercase opacity-40 font-bold">正在校准数据流 Calibrating...</p>
                    </div>
                  ) : (
                    <img 
                      src={src} 
                      alt={alt} 
                      className="w-full h-full object-cover m-0 rounded-2xl" 
                      loading="lazy"
                      {...props} 
                    />
                  )}
                  {/* 顶级量化水印 */}
                  <div className="absolute bottom-5 right-5 glass-panel !rounded-full px-4 py-1.5 flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-primary-container animate-pulse" />
                    <span className="text-[9px] text-foreground/90 font-headline font-black italic tracking-[0.2em] uppercase">
                      喵弟量化实验室 MIAODI QUANT
                    </span>
                  </div>
                </div>
                {alt && (
                  <div className="mt-4 px-4 flex items-center gap-3">
                    <div className="h-[1px] flex-grow bg-white/5" />
                    <p className="text-[10px] text-zinc-500 font-headline font-bold tracking-widest italic uppercase opacity-60">图表 FIG: {alt}</p>
                    <div className="h-[1px] flex-grow bg-white/5" />
                  </div>
                )}
              </div>
            );
          }
        }}
      >
        {content}
      </ReactMarkdown>
    </article>
  );
}
