'use client';
import React from 'react';
import { LayoutDashboard, Target, BarChart3, Settings, LogOut, Bell } from 'lucide-react';
import { useTheme } from './ThemeProvider';

const Sidebar = () => {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <aside className="fixed left-0 top-0 bottom-0 w-20 flex flex-col items-center py-8 z-50 transition-all duration-500 bg-background/80 backdrop-blur-2xl border-r border-foreground/5 shadow-sm">
      <div className="w-12 h-12 rounded-2xl flex items-center justify-center mb-12 shadow-lg cursor-pointer hover:scale-110 transition-transform bg-neon text-white dark:text-black">
        <span className="font-black text-xl">D</span>
      </div>

      <nav className="flex flex-col gap-8 flex-1">
        <NavItem icon={<LayoutDashboard size={22} />} active />
        <NavItem icon={<Target size={22} />} />
        <NavItem icon={<BarChart3 size={22} />} />
        <NavItem icon={<Bell size={22} />} />
      </nav>

      <div className="flex flex-col gap-8 mt-auto">
        <NavItem icon={<Settings size={22} />} />
        <NavItem icon={<LogOut size={22} />} />
      </div>
    </aside>
  );
};

const NavItem = ({ icon, active = false }: { icon: React.ReactNode; active?: boolean }) => (
  <div className={`p-3 rounded-2xl cursor-pointer transition-all duration-300 group relative ${
    active 
      ? 'bg-neon/10 text-neon shadow-sm border border-neon/20' 
      : 'text-foreground/40 hover:text-foreground hover:bg-foreground/5'
  }`}>
    {icon}
    {active && (
      <div className="absolute left-[-16px] top-1/2 -translate-y-1/2 w-1.5 h-6 rounded-r-full shadow-md bg-neon shadow-neon/40" />
    )}
  </div>
);

export default Sidebar;
