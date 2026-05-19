'use client';

import React from 'react';
import ReactECharts from 'echarts-for-react';

interface EChartWrapperProps {
  option: any;
  style?: React.CSSProperties;
  className?: string;
  theme?: string | object;
}

export default function EChartWrapper({ option, style, className = '', theme = 'light' }: EChartWrapperProps) {
  const [isMounted, setIsMounted] = React.useState(false);

  React.useEffect(() => {
    setIsMounted(true);
  }, []);

  if (!isMounted) {
    return (
      <div 
        className={`w-full h-[300px] md:h-[400px] ${className} bg-white/5 animate-pulse rounded-2xl flex items-center justify-center border border-white/5`} 
        style={style}
      >
        <div className="w-8 h-8 rounded-full border-2 border-cyan-500/20 border-t-cyan-500 animate-spin" />
      </div>
    );
  }

  // A generic wrapper for ECharts to ensure responsiveness and proper client-side rendering
  return (
    <div className={`w-full h-full ${className}`}>
      <ReactECharts
        option={option}
        style={{ height: '100%', width: '100%', minHeight: '300px', ...style }}
        theme={theme}
        notMerge={true}
        lazyUpdate={true}
        opts={{ renderer: 'svg' }} // Use SVG renderer for sharper display and better performance on simple charts
      />
    </div>
  );
}
