import React from 'react';
import { CyberCard } from '@/components/ui/CyberCard';
import { CyberButton } from '@/components/ui/CyberButton';
import { CapsulePill } from '@/components/ui/CapsulePill';
import { CyberFeed } from '@/components/layout/CyberFeed';
import { Activity, BarChart3, Database, Sparkle } from 'lucide-react';

export default function CyberUIDemo() {
  return (
    <main className="min-h-screen bg-surface-base text-foreground selection:bg-primary selection:text-black">
      {/* Background signature texture */}
      <div className="fixed inset-0 bg-gradient-to-br from-primary/10 to-secondary/10 opacity-20 pointer-events-none" />
      
      <header className="relative z-20 pt-24 pb-12 px-12 text-center max-w-4xl mx-auto">
        <h1 className="text-editorial text-5xl md:text-8xl font-black italic uppercase tracking-tighter text-primary">
          足球数研所
        </h1>
        <p className="mt-6 text-utility text-lg opacity-60 tracking-[0.2em] font-light uppercase">
          AI-Driven Quantitative Intelligence
        </p>
      </header>

      <CyberFeed>
        {/* Module 1: Introduction */}
        <CyberCard variant="high" className="relative">
          <div className="flex justify-between items-start mb-8">
            <h2 className="text-editorial text-4xl font-bold uppercase italic text-secondary">
              The Synthetic Ether
            </h2>
            <CapsulePill variant="secondary">Active Protocol</CapsulePill>
          </div>
          <p className="text-utility text-lg leading-relaxed mb-8 opacity-90">
            Welcome to the new era of data visualization. This interface is built on the 
            principles of <strong>Liquid Intelligence</strong>—shifting from rigid containers to 
            layered, ionized surfaces that breathe with your data.
          </p>
          <div className="flex gap-4">
            <CyberButton variant="primary">Launch Lab</CyberButton>
            <CyberButton variant="glass">Documentation</CyberButton>
          </div>
        </CyberCard>

        {/* Module 2: Metrics Snapshot */}
        <CyberCard className="border-t border-l border-primary/20">
          <div className="flex gap-2 mb-6">
            <CapsulePill variant="primary" outline>Quant Feed</CapsulePill>
            <CapsulePill variant="tertiary" outline>Real-time</CapsulePill>
          </div>
          <div className="grid grid-cols-2 gap-12">
            <div>
              <label className="text-utility text-xs uppercase tracking-widest opacity-50 block mb-2">
                Predictive Accuracy
              </label>
              <div className="text-editorial text-6xl font-black text-primary italic">
                94.8%
              </div>
            </div>
            <div>
              <label className="text-utility text-xs uppercase tracking-widest opacity-50 block mb-2">
                Processed Samples
              </label>
              <div className="text-editorial text-6xl font-black text-foreground italic">
                12.4M
              </div>
            </div>
          </div>
        </CyberCard>

        {/* Module 3: Technical Specs */}
        <CyberCard variant="low">
          <h3 className="text-editorial text-2xl font-bold uppercase mb-8 flex items-center gap-3">
            <Database className="w-6 h-6 text-tertiary" />
            System Architecture
          </h3>
          <ul className="space-y-6">
            {[
              { icon: Sparkle, title: "Neural Processing", desc: "Multi-layered transformer architecture at 12ms latency." },
              { icon: BarChart3, title: "Edge Analytics", desc: "Decentralized computation for real-time match variance." },
              { icon: Activity, title: "Dynamic Liquidity", desc: "Adaptive glassmorphism responds to market volatility." }
            ].map((item, i) => (
              <li key={i} className="flex gap-6 group cursor-default">
                <div className="w-12 h-12 glass-cyber rounded-full flex items-center justify-center shrink-0 group-hover:scale-110 group-hover:bg-primary/20 transition-all">
                  <item.icon className="w-5 h-5 text-primary" />
                </div>
                <div>
                  <h4 className="text-editorial font-bold text-lg uppercase tracking-wide">
                    {item.title}
                  </h4>
                  <p className="text-utility opacity-60 text-sm mt-1">
                    {item.desc}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </CyberCard>
      </CyberFeed>

      <footer className="py-24 text-center opacity-30 text-utility text-xs uppercase tracking-[0.4em]">
        &copy; 2026 MEOW BROTHER QUANT LAB . ALL RIGHTS RESERVED
      </footer>
    </main>
  );
}
