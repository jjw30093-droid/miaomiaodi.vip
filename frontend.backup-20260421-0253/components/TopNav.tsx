'use client';
import React from 'react';
import { Search, Moon, Sun } from 'lucide-react';
import { useTheme } from './ThemeProvider';

const TopNav = () => {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <header className="fixed top-0 left-20 right-0 h-20 flex items-center justify-between px-10 z-40 transition-all duration-500 bg-background/40 backdrop-blur-xl border-b border-foreground/5 shadow-sm">
      <div className="flex items-center gap-12 w-full max-w-[1400px] mx-auto">
        {/* Logo / Brand Name */}
        <div className="text-xl font-black italic tracking-tighter text-foreground">GoalAlpha</div>

        {/* 顶部菜单 */}
        <div className="hidden md:flex items-center gap-10">
           <MenuLink label="主页" active />
           <MenuLink label="核心特性" />
           <MenuLink label="支付方案" />
           <MenuLink label="关于我们" />
        </div>

        {/* 搜索框 */}
        <div className="flex-1 max-w-sm relative group ml-auto mr-10">
           <Search className="absolute left-4 top-1/2 -translate-y-1/2 transition-colors text-foreground/40 group-focus-within:text-neon" size={16} />
           <input 
             type="text" 
             placeholder="搜索资源、模型或赛事..." 
             className="w-full border rounded-2xl py-2 pl-12 pr-4 text-xs focus:outline-none transition-all bg-background/50 border-foreground/10 text-foreground focus:ring-2 focus:ring-neon/10 focus:border-neon"
           />
        </div>

        {/* 主题切换与用户信息 */}
        <div className="flex items-center gap-6">
           <button 
             onClick={toggleTheme}
             className="p-2.5 rounded-xl border border-foreground/10 hover:bg-foreground/5 transition-all text-foreground"
             title={isDark ? "切换至浅色模式" : "切换至深色模式"}
           >
             {isDark ? <Sun size={18} /> : <Moon size={18} />}
           </button>

           <div className="p-1 rounded-full px-4 text-[10px] font-black uppercase tracking-widest bg-neon/10 text-neon">
             登录
           </div>
           
           <button className="px-6 py-2.5 font-black text-[10px] uppercase tracking-widest rounded-xl transition-all hover:scale-105 active:scale-95 bg-neon text-white dark:text-black shadow-lg shadow-neon/20">
             进入控制台 →
           </button>
        </div>
      </div>
    </header>
  );
};

const MenuLink = ({ label, active = false }: { label: string; active?: boolean }) => (
  <div className={`text-[11px] font-bold cursor-pointer transition-colors ${
    active ? 'text-neon' : 'text-foreground/40 hover:text-foreground'
  }`}>
    {label}
  </div>
);

export default TopNav;
