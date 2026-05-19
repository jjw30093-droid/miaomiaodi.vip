"use client";

import React from 'react';
import dynamic from 'next/dynamic';
import { useTheme } from '@/components/ThemeProvider';

/* 粒子完全跳过 SSR，杜绝 Math.random() hydration 不一致 */
const Particles = dynamic(() => import('./Particles'), { ssr: false });

export const BackgroundEffects = () => {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  // Light mode: mix-blend-multiply makes colored blobs visible on white background
  // Dark mode:  mix-blend-screen adds color luminosity to dark background
  const blend = isDark ? 'mix-blend-screen' : 'mix-blend-multiply';

  return (
    <>
      {/* Noise Texture */}
      <div className="fixed inset-0 bg-noise pointer-events-none z-0" />

      {/* Gradient Blobs */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
        <div className={`absolute top-[-10%] left-[-20%] w-[150vw] h-[150vw] md:w-[80vw] md:h-[80vw] ${isDark ? 'bg-blue-700/25' : 'bg-blue-400/12'} blur-[90px] md:blur-[120px] rounded-full ${blend} animate-float-slow`} />
        <div className={`absolute top-[20%] right-[-30%] w-[120vw] h-[120vw] md:w-[70vw] md:h-[70vw] ${isDark ? 'bg-primary-neon/20' : 'bg-sky-400/10'} blur-[80px] md:blur-[100px] rounded-full ${blend} animate-float-slower`} />
        <div className={`absolute bottom-[-10%] left-[-10%] w-[140vw] h-[140vw] md:w-[90vw] md:h-[90vw] ${isDark ? 'bg-secondary-magenta/15' : 'bg-rose-400/10'} blur-[90px] md:blur-[130px] rounded-full ${blend} animate-float-slow`} style={{ animationDelay: '-5s' }} />
        <div className={`absolute top-[35%] right-[5%] w-[100vw] h-[100vw] md:w-[60vw] md:h-[60vw] ${isDark ? 'bg-purple-700/25' : 'bg-amber-300/16'} blur-[80px] md:blur-[120px] rounded-full ${blend} animate-float-slower`} style={{ animationDelay: '-10s' }} />
        {!isDark && (
          <div className="absolute top-[25%] left-[30%] w-[80vw] h-[80vw] md:w-[45vw] md:h-[45vw] bg-yellow-200/18 blur-[100px] md:blur-[140px] rounded-full mix-blend-multiply animate-float-slow" style={{ animationDelay: '-8s' }} />
        )}
      </div>

      {/* Radar Sweep */}
      <div className={`fixed inset-0 overflow-hidden pointer-events-none z-0 flex items-center justify-center ${isDark ? 'opacity-30' : 'opacity-15'}`}>
        <div className="w-[200vw] h-[200vw] md:w-[100vw] md:h-[100vw] rounded-full border border-primary-neon/10 animate-pulse-glow" />
        <div className="absolute w-[150vw] h-[150vw] md:w-[75vw] md:h-[75vw] rounded-full border border-secondary-magenta/10 animate-pulse-glow" style={{ animationDelay: '-1.5s' }} />
        <div className="absolute w-[100vw] h-[100vw] md:w-[50vw] md:h-[50vw] rounded-full border border-blue-500/10 animate-pulse-glow" style={{ animationDelay: '-2.5s' }} />
        <div className="absolute w-[200vw] h-[200vw] md:w-[100vw] md:h-[100vw] rounded-full animate-radar-spin">
          <div className="w-1/2 h-1/2 bg-gradient-to-tr from-transparent via-primary-neon/5 to-primary-neon/20 origin-bottom-right rounded-tl-full" />
        </div>
      </div>

      {/* Floating Particles — ssr:false，完全不参与服务端渲染 */}
      <Particles />

      {/* Data Streams */}
      <div className={`fixed inset-0 overflow-hidden pointer-events-none z-0 ${isDark ? 'opacity-60' : 'opacity-40'}`}>
        <div className="absolute left-[15%] top-0 w-[1px] h-32 bg-gradient-to-b from-transparent via-primary-neon to-transparent animate-data-stream" style={{ animationDuration: '4s', animationDelay: '0s' }} />
        <div className="absolute left-[35%] top-0 w-[2px] h-48 bg-gradient-to-b from-transparent via-secondary-magenta to-transparent animate-data-stream" style={{ animationDuration: '5.5s', animationDelay: '1.2s' }} />
        <div className="absolute left-[65%] top-0 w-[1px] h-24 bg-gradient-to-b from-transparent via-primary-neon to-transparent animate-data-stream" style={{ animationDuration: '3.5s', animationDelay: '2.5s' }} />
        <div className="absolute left-[85%] top-0 w-[2px] h-40 bg-gradient-to-b from-transparent via-blue-500 to-transparent animate-data-stream" style={{ animationDuration: '6s', animationDelay: '0.8s' }} />
      </div>

      {/* Grid — multiply on light keeps lines visible; screen on dark adds glow */}
      <div className={`fixed inset-0 bg-grid-pattern pointer-events-none z-0 ${isDark ? 'opacity-40 mix-blend-screen' : 'opacity-20 mix-blend-multiply'}`} />

      {/* Scan Line */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-0">
        <div className="w-full h-[2px] bg-primary-neon/50 shadow-[0_0_20px_rgba(0,240,255,1),0_0_40px_rgba(0,240,255,0.5)] animate-scan" />
      </div>

      {/* Vignette — dark mode only (would invert light background if shown on white) */}
      {isDark && (
        <div className="fixed inset-0 bg-[radial-gradient(ellipse_at_center,transparent_0%,#020513_100%)] pointer-events-none opacity-60 z-0" />
      )}
    </>
  );
};
