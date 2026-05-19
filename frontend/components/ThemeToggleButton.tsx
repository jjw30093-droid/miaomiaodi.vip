'use client';

import { Sun, Moon } from 'lucide-react';
import { useTheme } from './ThemeProvider';

export default function ThemeToggleButton() {
  const { theme, toggleTheme } = useTheme();
  return (
    <button
      onClick={toggleTheme}
      aria-label="切换深色/浅色模式"
      className="w-9 h-9 flex items-center justify-center rounded-full bg-white/10 border border-white/15 backdrop-blur-md hover:bg-white/20 active:scale-95 transition-all shadow-md flex-shrink-0"
    >
      {theme === 'dark'
        ? <Sun size={18} className="text-yellow-400" />
        : <Moon size={18} className="text-sky-400" />}
    </button>
  );
}
