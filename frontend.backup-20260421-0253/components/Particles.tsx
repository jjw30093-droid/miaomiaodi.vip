"use client";
/* 纯客户端粒子组件 — 通过 dynamic({ ssr: false }) 引入，完全不参与 SSR */
import React from 'react';

export default function Particles() {
  return (
    <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
      {[...Array(15)].map((_, i) => (
        <div
          key={i}
          className="absolute w-1 h-1 bg-primary-neon rounded-full shadow-[0_0_5px_rgba(0,240,255,0.8)] animate-float-particle"
          style={{
            left:              `${Math.random() * 100}%`,
            bottom:            `-${Math.random() * 20}%`,
            animationDuration: `${10 + Math.random() * 15}s`,
            animationDelay:    `${Math.random() * 5}s`,
            opacity:            0.2 + Math.random() * 0.5,
          }}
        />
      ))}
      {[...Array(10)].map((_, i) => (
        <div
          key={`m-${i}`}
          className="absolute w-1.5 h-1.5 bg-secondary-magenta rounded-full shadow-[0_0_8px_rgba(255,0,229,0.8)] animate-float-particle"
          style={{
            left:              `${Math.random() * 100}%`,
            bottom:            `-${Math.random() * 20}%`,
            animationDuration: `${12 + Math.random() * 18}s`,
            animationDelay:    `${Math.random() * 7}s`,
            opacity:            0.1 + Math.random() * 0.4,
          }}
        />
      ))}
    </div>
  );
}
