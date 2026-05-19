'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Mail, Lock, User, ArrowRight, ArrowLeft } from 'lucide-react';
import { BackgroundEffects } from '@/components/BackgroundEffects';

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const handleRegister = (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      alert("两次密码不一致");
      return;
    }
    // Simulate registration
    router.push('/');
  };

  return (
    <div className="relative min-h-screen bg-gradient-to-br from-[#020513] via-[#060918] to-[#0a0514] overflow-hidden font-sans flex items-center justify-center p-4">
      <BackgroundEffects />
      
      <div className="relative z-10 w-full max-w-md">
        {/* Logo */}
        <div className="flex flex-col items-center justify-center gap-4 mb-8">
          <div className="relative w-16 h-16 flex-shrink-0">
            <div className="absolute inset-0 bg-secondary-magenta/20 blur-[20px] rounded-full animate-pulse-glow" />
            <img 
              src="/logo_meow.jpg"
              alt="Logo" 
              className="w-full h-full object-contain drop-shadow-[0_0_15px_rgba(255,0,229,0.5)] mix-blend-screen relative z-10"
            />
          </div>
          <h1 className="font-display italic font-bold text-2xl tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-white via-secondary-magenta to-white text-glow-magenta drop-shadow-[0_2px_2px_rgba(0,0,0,0.8)]">
            喵弟数据研究室
          </h1>
          <p className="text-secondary-magenta/80 text-sm tracking-widest font-display uppercase">新智能体注册通道</p>
        </div>

        {/* Register Form Card */}
        <div className="glass-panel rounded-3xl p-8 shadow-[0_0_30px_rgba(255,0,229,0.1)] border border-secondary-magenta/20 relative overflow-hidden">
          
          {/* Return Button */}
          <Link
            href="/login"
            className="absolute top-4 left-4 z-50 flex items-center justify-center p-2 rounded-full text-gray-400 hover:text-secondary-magenta hover:bg-white/5 transition-all duration-300 group"
          >
            <ArrowLeft size={20} className="group-hover:-translate-x-1 transition-transform duration-300" />
          </Link>

          {/* Decorative corner accents */}
          <div className="absolute top-0 right-0 w-8 h-8 border-t-2 border-r-2 border-secondary-magenta/50 rounded-tr-3xl" />
          <div className="absolute bottom-0 left-0 w-8 h-8 border-b-2 border-l-2 border-primary-neon/50 rounded-bl-3xl" />

          <form onSubmit={handleRegister} className="flex flex-col gap-5 mt-4">
            <div className="space-y-1">
              <label className="text-xs font-display font-bold text-gray-400 uppercase tracking-widest ml-1">Codename</label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-gray-500 group-focus-within:text-secondary-magenta transition-colors">
                  <User size={18} />
                </div>
                <input 
                  type="text" required value={name} onChange={(e) => setName(e.target.value)}
                  className="w-full bg-black/40 border border-white/10 rounded-xl py-3 pl-10 pr-4 text-white placeholder-gray-600 focus:outline-none focus:border-secondary-magenta/50 focus:ring-1 focus:ring-secondary-magenta/50 transition-all font-display text-sm"
                  placeholder="Agent Neo"
                />
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-display font-bold text-gray-400 uppercase tracking-widest ml-1">邮箱地址</label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-gray-500 group-focus-within:text-secondary-magenta transition-colors">
                  <Mail size={18} />
                </div>
                <input 
                  type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                  className="w-full bg-black/40 border border-white/10 rounded-xl py-3 pl-10 pr-4 text-white placeholder-gray-600 focus:outline-none focus:border-secondary-magenta/50 focus:ring-1 focus:ring-secondary-magenta/50 transition-all font-display text-sm"
                  placeholder="neo@matrix.net"
                />
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-display font-bold text-gray-400 uppercase tracking-widest ml-1">密码</label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-gray-500 group-focus-within:text-secondary-magenta transition-colors">
                  <Lock size={18} />
                </div>
                <input 
                  type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-black/40 border border-white/10 rounded-xl py-3 pl-10 pr-4 text-white placeholder-gray-600 focus:outline-none focus:border-secondary-magenta/50 focus:ring-1 focus:ring-secondary-magenta/50 transition-all font-display text-sm"
                  placeholder="••••••••"
                />
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-display font-bold text-gray-400 uppercase tracking-widest ml-1">确认密码</label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-gray-500 group-focus-within:text-secondary-magenta transition-colors">
                  <Lock size={18} />
                </div>
                <input 
                  type="password" required value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)}
                  className="w-full bg-black/40 border border-white/10 rounded-xl py-3 pl-10 pr-4 text-white placeholder-gray-600 focus:outline-none focus:border-secondary-magenta/50 focus:ring-1 focus:ring-secondary-magenta/50 transition-all font-display text-sm"
                  placeholder="••••••••"
                />
              </div>
            </div>

            <button 
              type="submit"
              className="mt-2 w-full relative group overflow-hidden rounded-xl bg-gradient-to-r from-secondary-magenta/20 to-purple-600/20 border border-secondary-magenta/30 p-3.5 flex items-center justify-center gap-2 hover:from-secondary-magenta/40 hover:to-purple-600/40 transition-all duration-300 active:scale-[0.98]"
            >
              <span className="font-display font-bold text-white tracking-widest uppercase text-sm">Initialize</span>
              <ArrowRight size={16} className="text-secondary-magenta group-hover:translate-x-1 transition-transform" />
            </button>
          </form>

          <div className="mt-6 text-center">
            <p className="text-xs text-gray-500 font-display">
              已有访问权限？{' '}
              <Link href="/login" className="text-primary-neon hover:text-cyan-400 transition-colors font-bold tracking-wide">
                进入系统
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
