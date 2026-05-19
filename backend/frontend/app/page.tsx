'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'motion/react';
import { 
  Activity, 
  History, 
  Crown, 
  User, 
  Lock, 
  Star, 
  ChevronRight,
  Sun, Moon, Info, Search, X, Check, Copy
} from 'lucide-react';
import { BackgroundEffects } from '@/components/BackgroundEffects';

// ─── Types ───────────────────────────────────────────────────────────────────
interface Team {
  name: string;
  icon?: string;
  prob: number;
}

interface Match {
  id: string;
  league: string;
  leagueLogo?: string;
  time: string;
  display_category: 'UPCOMING' | 'ARCHIVE';
  homeTeam: Team;
  awayTeam: Team;
  status: 'HOT' | 'FREE' | 'VIP'
      | 'PRE_MATCH_READY' | 'ANALYSIS_UPDATED'
      | 'FINAL_REPORT_READY' | 'REVIEW_GENERATED' | 'ARCHIVED' | 'FINISHED';
  drawProb?: number;
  inference?: string;
}

// ─── Sub-components ──────────────────────────────────────────────────────────

const ProbabilityBar = ({ value, colorClass, glowClass }: { value: number, colorClass: string, glowClass: string }) => (
  <div className="relative h-2.5 w-full bg-white/5 rounded-full overflow-hidden border border-white/10 group-hover:bg-white/10 transition-colors">
    <motion.div 
      initial={{ width: 0 }}
      animate={{ width: `${value}%` }}
      transition={{ duration: 1.5, ease: "easeOut" }}
      className={`absolute top-0 left-0 h-full rounded-full ${colorClass} ${glowClass}`}
    />
  </div>
);

const CompactMatchCard = ({ match, isFavorite, onToggleFavorite, onCardClick }: { 
  match: Match, 
  isFavorite: boolean, 
  onToggleFavorite: (e: React.MouseEvent) => void,
  onCardClick: () => void
}) => {
  return (
    <div onClick={onCardClick} className="block cursor-pointer">
      <div className="relative glass-panel rounded-2xl p-4 flex flex-col items-center justify-center gap-3 active:scale-95 transition-all hover:bg-white/5 overflow-hidden group">
        {/* Diagonal Hot Tag */}
        {match.status === 'HOT' && (
          <div className="absolute top-0 right-0 w-16 h-16 overflow-hidden pointer-events-none z-20 rounded-tr-2xl">
            <div className="absolute top-[8px] -right-[24px] bg-gradient-to-r from-red-600 to-orange-500 text-white text-[9px] font-black py-0.5 w-24 text-center transform rotate-45 shadow-[0_0_10px_rgba(239,68,68,0.6)] border-y border-white/20 tracking-wider uppercase">
              热门
            </div>
          </div>
        )}

        {/* Header */}
        <div className="flex justify-between items-center w-full relative z-10">
          <div className="flex items-center gap-1.5 min-w-0">
            <div className="flex items-center gap-1.5 text-[10px] tracking-wide text-white/60 font-display uppercase font-bold truncate">
              {match.leagueLogo && (
                <img src={match.leagueLogo} alt={match.league} className="w-4 h-4 rounded-full shadow-[0_0_5px_rgba(255,255,255,0.2)] flex-shrink-0" referrerPolicy="no-referrer" />
              )}
              {match.league} <span className="text-gray-500 font-normal mx-0.5">•</span> <span className="text-primary-neon">{match.time.split(' ')[1] || match.time}</span>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button 
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); onToggleFavorite(e); }} 
              className="text-gray-400 hover:text-yellow-400 transition-all duration-300 active:scale-90 z-30"
            >
              <Star size={14} className={`transition-all duration-300 ${isFavorite ? "fill-yellow-400 text-yellow-400 drop-shadow-[0_0_5px_rgba(250,204,21,0.8)] scale-110" : "scale-100 hover:scale-110"}`} />
            </button>
            {match.status === 'VIP' && <Lock size={12} className="text-yellow-500 drop-shadow-[0_0_5px_rgba(234,179,8,0.5)]" />}
          </div>
        </div>

        <div className="flex justify-between items-center w-full relative z-10">
          <div className="flex flex-col items-center gap-2 w-[42%]">
            <div className="w-10 h-10 rounded-full glass-panel !rounded-full p-2 flex items-center justify-center shadow-none bg-white/5 border-white/10 group-hover:border-primary-neon/30 transition-colors">
              <img src={match.homeTeam.icon || "/logo_meow.jpg"} alt="H" className="w-full h-full object-contain" />
            </div>
            <span className="font-display font-bold text-[11px] tracking-wide text-center leading-tight line-clamp-2 text-white/90">{match.homeTeam.name}</span>
          </div>
          
          <div className="text-gray-600 font-display italic text-xs w-[16%] text-center">VS</div>
          
          <div className="flex flex-col items-center gap-2 w-[42%]">
             <div className="w-10 h-10 rounded-full glass-panel !rounded-full p-2 flex items-center justify-center shadow-none bg-white/5 border-white/10 group-hover:border-secondary-magenta/30 transition-colors">
              <img src={match.awayTeam.icon || "/logo_meow.jpg"} alt="A" className="w-full h-full object-contain" />
            </div>
            <span className="font-display font-bold text-[11px] tracking-wide text-center leading-tight line-clamp-2 text-white/90">{match.awayTeam.name}</span>
          </div>
        </div>

        <div className="w-full mt-1">
           <div className="flex justify-between text-[9px] font-black italic mb-1 px-1">
             <span className="text-primary-neon">{match.homeTeam.prob}%</span>
             <span className="text-secondary-magenta">{match.awayTeam.prob}%</span>
           </div>
           <div className="flex h-1.5 w-full bg-white/5 rounded-full overflow-hidden gap-0.5 px-0.5">
              <div className="h-full bg-primary-neon rounded-full" style={{ width: `${match.homeTeam.prob}%` }} />
              <div className="h-full bg-secondary-magenta rounded-full ml-auto" style={{ width: `${match.awayTeam.prob}%` }} />
           </div>
        </div>
      </div>
    </div>
  );
};

const MatchCard = ({ match, isFavorite, onToggleFavorite, onClick }: { match: Match, isFavorite: boolean, onToggleFavorite: (e: React.MouseEvent) => void, onClick?: (e: React.MouseEvent) => void }) => {
  const [copied, setCopied] = useState(false);
  const [prediction, setPrediction] = useState<'home' | 'draw' | 'away' | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);
  const isLocked = match.status === 'VIP';
  const drawProb = (
    match.drawProb != null && match.drawProb > 0
      ? match.drawProb
      : Math.max(0, 100 - match.homeTeam.prob - match.awayTeam.prob)
  ).toFixed(1);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (match.inference) {
      navigator.clipboard.writeText(match.inference);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div 
      className={`relative glass-panel rounded-3xl p-5 mb-4 overflow-hidden group ${onClick ? 'cursor-pointer hover:shadow-[0_0_30px_rgba(0,240,255,0.15)] transition-shadow duration-300' : ''}`}
      onClick={onClick}
    >
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-3/4 h-1/2 bg-primary-neon/5 blur-[50px] rounded-full pointer-events-none" />

      {/* Diagonal Hot Tag */}
      {match.status === 'HOT' && (
        <div className="absolute top-0 right-0 w-24 h-24 overflow-hidden pointer-events-none z-20 rounded-tr-3xl">
          <div className="absolute top-[18px] -right-[28px] bg-gradient-to-r from-red-600 to-orange-500 text-white text-[11px] font-black py-1 w-32 text-center transform rotate-45 shadow-[0_0_15px_rgba(239,68,68,0.6)] border-y border-white/20 tracking-widest uppercase">
            热门
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex justify-between items-center mb-4 relative z-10">
        <div className="flex items-center gap-2.5">
          {match.leagueLogo && (
            <img src={match.leagueLogo} alt={match.league} className="w-7 h-7 rounded-full shadow-[0_0_8px_rgba(255,255,255,0.2)] flex-shrink-0" referrerPolicy="no-referrer" />
          )}
          <div className="text-base tracking-wide text-white font-display uppercase font-extrabold drop-shadow-[0_2px_2px_rgba(0,0,0,0.8)]">
            {match.league} <span className="text-gray-500 font-normal mx-1 text-sm">•</span> <span className="text-primary-neon text-glow-cyan">{match.time.split(' ')[1] || match.time}</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button 
            onClick={(e) => { e.stopPropagation(); e.preventDefault(); onToggleFavorite(e); }} 
            className="text-gray-400 hover:text-yellow-400 transition-all duration-300 active:scale-90 z-30"
          >
            <Star size={18} className={`transition-all duration-300 ${isFavorite ? "fill-yellow-400 text-yellow-400 drop-shadow-[0_0_8px_rgba(250,204,21,0.8)] scale-110" : "scale-100 hover:scale-110"}`} />
          </button>
          {isLocked && <Lock size={16} className="text-yellow-500 drop-shadow-[0_0_5px_rgba(234,179,8,0.5)]" />}
        </div>
      </div>

      {/* Teams */}
      <div className="flex justify-between items-center mb-6 relative z-10">
        <div className="flex flex-col items-center gap-2 w-2/5">
          <div className="w-14 h-14 rounded-full glass-panel !rounded-full p-2.5 flex items-center justify-center bg-white/5 border-white/10 group-hover:border-primary-neon/40 transition-colors duration-500">
            <img src={match.homeTeam.icon || "/logo_meow.jpg"} alt="H" className="w-full h-full object-contain" />
          </div>
          <span className="font-display font-bold text-base tracking-wide text-center leading-tight text-white">{match.homeTeam.name}</span>
        </div>
        <div className="text-gray-500 font-display italic text-sm animate-pulse">VS</div>
        <div className="flex flex-col items-center gap-2 w-2/5">
          <div className="w-14 h-14 rounded-full glass-panel !rounded-full p-2.5 flex items-center justify-center bg-white/5 border-white/10 group-hover:border-secondary-magenta/40 transition-colors duration-500">
            <img src={match.awayTeam.icon || "/logo_meow.jpg"} alt="A" className="w-full h-full object-contain" />
          </div>
          <span className="font-display font-bold text-base tracking-wide text-center leading-tight text-white">{match.awayTeam.name}</span>
        </div>
      </div>

      {/* Locked Content Area */}
      <div className="relative">
        <div className={isLocked ? 'blur-md opacity-30 pointer-events-none select-none' : ''}>
          {/* Three-Column Probabilities with Prediction Interaction */}
          <div className="flex gap-3 items-end w-full relative z-10">
            {/* Home */}
            <div
              onClick={(e) => { e.stopPropagation(); setPrediction(prediction === 'home' ? null : 'home'); }}
              className={`group/prob flex flex-col items-center gap-2 flex-1 cursor-pointer transition-all duration-300 p-2 rounded-xl border ${prediction === 'home' ? 'bg-primary-neon/10 border-primary-neon/50 scale-105 -translate-y-1 shadow-[0_4px_20px_rgba(0,240,255,0.2)]' : prediction ? 'opacity-30 scale-95 border-transparent' : 'border-transparent hover:border-primary-neon/30 hover:bg-primary-neon/5'}`}
            >
              <span className={`font-display font-bold tabular-nums ${prediction === 'home' ? 'text-3xl text-white' : 'text-2xl text-primary-neon text-glow-cyan'}`}>
                {match.homeTeam.prob}%
              </span>
              <ProbabilityBar value={match.homeTeam.prob} colorClass="bg-primary-neon" glowClass="shadow-[0_0_10px_#00F0FF]" />
              <span className="text-[11px] font-bold tracking-wider flex items-center gap-1 text-gray-400">
                主胜 {prediction === 'home' && <Check size={12} className="text-primary-neon" />}
              </span>
            </div>

            {/* Draw */}
            <div
              onClick={(e) => { e.stopPropagation(); setPrediction(prediction === 'draw' ? null : 'draw'); }}
              className={`group/prob flex flex-col items-center gap-2 flex-1 cursor-pointer transition-all duration-300 p-2 rounded-xl border ${prediction === 'draw' ? 'bg-white/10 border-white/50 scale-105 -translate-y-1' : prediction ? 'opacity-30 scale-95 border-transparent' : 'border-transparent hover:border-white/30 hover:bg-white/5'}`}
            >
              <span className={`font-display font-bold tabular-nums ${prediction === 'draw' ? 'text-2xl text-white' : 'text-xl text-white/70'}`}>
                {drawProb}%
              </span>
              <ProbabilityBar value={Number(drawProb)} colorClass="bg-white" glowClass="shadow-[0_0_8px_rgba(255,255,255,0.8)]" />
              <span className="text-[11px] font-bold tracking-wider flex items-center gap-1 text-gray-400">
                平局 {prediction === 'draw' && <Check size={12} className="text-white" />}
              </span>
            </div>

            {/* Away */}
            <div
              onClick={(e) => { e.stopPropagation(); setPrediction(prediction === 'away' ? null : 'away'); }}
              className={`group/prob flex flex-col items-center gap-2 flex-1 cursor-pointer transition-all duration-300 p-2 rounded-xl border ${prediction === 'away' ? 'bg-secondary-magenta/10 border-secondary-magenta/50 scale-105 -translate-y-1 shadow-[0_4px_20px_rgba(255,0,229,0.2)]' : prediction ? 'opacity-30 scale-95 border-transparent' : 'border-transparent hover:border-secondary-magenta/30 hover:bg-secondary-magenta/5'}`}
            >
              <span className={`font-display font-bold tabular-nums ${prediction === 'away' ? 'text-3xl text-white' : 'text-2xl text-secondary-magenta text-glow-magenta'}`}>
                {match.awayTeam.prob}%
              </span>
              <ProbabilityBar value={match.awayTeam.prob} colorClass="bg-secondary-magenta" glowClass="shadow-[0_0_10px_#FF00E5]" />
              <span className="text-[11px] font-bold tracking-wider flex items-center gap-1 text-gray-400">
                客胜 {prediction === 'away' && <Check size={12} className="text-secondary-magenta" />}
              </span>
            </div>
          </div>

          {/* AI Inference - Collapsible */}
          {match.inference && (
            <div className="mt-5 relative z-10">
              <div className="bg-white/5 p-3 rounded-xl border border-white/10 hover:bg-white/10 transition-colors">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1">
                    <span className="text-white font-semibold text-sm block mb-1">AI Inference:</span>
                    <div className={`transition-all duration-500 ease-in-out overflow-hidden ${isExpanded ? 'max-h-[500px] opacity-100' : 'max-h-[40px] opacity-80'}`}>
                      <p className="text-sm text-gray-300 leading-relaxed">{match.inference}</p>
                    </div>
                  </div>
                  {isExpanded && (
                    <button
                      onClick={handleCopy}
                      className="text-gray-400 hover:text-white transition-all p-1 active:scale-90 mt-5 flex-shrink-0"
                      title="复制到剪贴板"
                    >
                      {copied ? <Check size={16} className="text-green-500" /> : <Copy size={16} />}
                    </button>
                  )}
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); setIsExpanded(!isExpanded); }}
                  className="text-primary-neon text-xs mt-2 hover:text-white transition-colors font-medium flex items-center gap-1"
                >
                  {isExpanded ? '收起' : '展开全文'}
                  <span className={`transition-transform duration-300 ${isExpanded ? 'rotate-180' : ''}`}>↓</span>
                </button>
              </div>
            </div>
          )}
        </div>

        {/* VIP Lock Overlay */}
        {isLocked && (
          <div className="absolute inset-0 flex flex-col items-center justify-center z-20">
            <div className="w-14 h-14 bg-yellow-500/20 rounded-full flex items-center justify-center mb-2 backdrop-blur-md border border-yellow-500/30 shadow-[0_0_20px_rgba(234,179,8,0.3)]">
              <Lock size={28} className="text-yellow-500" />
            </div>
            <span className="text-primary-neon font-display tracking-wide text-sm">解锁完整 AI 分析</span>
          </div>
        )}
      </div>
    </div>
  );
};

// ─── Main Page Component ───────────────────────────────────────────────────

export default function FootballLabPage() {
  const [dateFilter, setDateFilter] = useState<'yesterday' | 'today' | 'tomorrow' | 'all'>('today');
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [searchQuery, setSearchQuery] = useState('');
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [favorites, setFavorites] = useState<string[]>([]);
  const [sortBy, setSortBy] = useState<'hot' | 'time'>('hot');
  const [selectedMatch, setSelectedMatch] = useState<Match | null>(null);

  // 1. Data Fetching
  useEffect(() => {
    const fetchLatestReports = async () => {
      try {
        const response = await fetch(`/api/v1/reports/latest?t=${Date.now()}`, { cache: 'no-store' });
        if (!response.ok) throw new Error('API Sync Failed');
        const data = await response.json();
        setMatches(data);
      } catch (error) {
        console.error('>>> [fetchLatestReports] Error:', error);
      } finally {
        setLoading(false);
      }
    };
    fetchLatestReports();

    // Init Favorites from localStorage
    const savedFavs = localStorage.getItem('favorites');
    if (savedFavs) {
      try {
        setFavorites(JSON.parse(savedFavs));
      } catch (e) {
        setFavorites([]);
      }
    }

    // Init Theme
    const savedTheme = localStorage.getItem('theme') as 'dark' | 'light';
    if (savedTheme) {
      setTheme(savedTheme);
    }
  }, []);

  // Sync favorites to localStorage
  useEffect(() => {
    localStorage.setItem('favorites', JSON.stringify(favorites));
  }, [favorites]);

  // Sync theme
  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'light') {
      root.classList.add('light');
      root.setAttribute('data-theme', 'light');
    } else {
      root.classList.remove('light');
      root.removeAttribute('data-theme');
    }
    localStorage.setItem('theme', theme);
  }, [theme]);

  const toggleFavorite = (id: string) => {
    setFavorites(prev => 
      prev.includes(id) ? prev.filter(f => f !== id) : [...prev, id]
    );
  };

  const isLight = theme === 'light';

  // 2. Logic: Filter and Sort
  const filteredMatches = React.useMemo(() => {
    const now = new Date();
    const toDateStr = (d: Date) => d.toDateString();

    let subset = matches.filter(m => {
      // Search filter
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const hit = m.homeTeam.name.toLowerCase().includes(q) ||
          m.awayTeam.name.toLowerCase().includes(q) ||
          m.league.toLowerCase().includes(q) ||
          (m.inference || '').toLowerCase().includes(q);
        if (!hit) return false;
      }
      // Date filter
      if (dateFilter === 'all') return true;
      const matchDate = new Date(m.time.replace(' ', 'T'));
      if (dateFilter === 'yesterday') {
        const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
        return toDateStr(matchDate) === toDateStr(yesterday);
      }
      if (dateFilter === 'today') {
        return toDateStr(matchDate) === toDateStr(now);
      }
      if (dateFilter === 'tomorrow') {
        const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1);
        return toDateStr(matchDate) === toDateStr(tomorrow);
      }
      return true;
    });

    const favs = subset.filter(m => favorites.includes(m.id));
    const others = subset.filter(m => !favorites.includes(m.id));
    const sortFn = (a: Match, b: Match) => {
      if (sortBy === 'hot') {
        if (a.status === 'HOT' && b.status !== 'HOT') return -1;
        if (a.status !== 'HOT' && b.status === 'HOT') return 1;
      }
      return new Date(a.time.replace(' ', 'T')).getTime() - new Date(b.time.replace(' ', 'T')).getTime();
    };
    return [...favs.sort(sortFn), ...others.sort(sortFn)];
  }, [matches, dateFilter, searchQuery, sortBy, favorites]);

  const ELITE_MATCH = filteredMatches[0];
  const SUB_MATCHES = filteredMatches.slice(1);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0D0F14] flex flex-col items-center justify-center gap-6">
        <BackgroundEffects />
        <div className="w-16 h-16 border-2 border-primary-neon/20 border-t-primary-neon rounded-full animate-spin relative z-10" />
        <p className="text-[11px] font-display font-black text-primary-neon/50 uppercase tracking-[0.5em] animate-pulse relative z-10">
          NEURAL SYNC :: QUANT NODE ACTIVE
        </p>
      </div>
    );
  }

  return (
    <main className="min-h-screen relative overflow-x-hidden bg-[#0D0F14] text-white">
      <BackgroundEffects />

      <div className="relative z-10 max-w-md mx-auto min-h-screen flex flex-col pb-24">

        {/* ── Header ── */}
        <header className="pt-2 pb-4 px-6 flex flex-col items-center">
          
          {/* Logo + Title Row */}
          <div className="flex items-center justify-center gap-3 mb-3 w-full pt-4">
            <div className="relative w-14 h-14 flex-shrink-0">
              <div className="absolute inset-0 bg-primary-neon/20 blur-[20px] rounded-full animate-pulse-glow" />
              <img src="/logo_meow.jpg" className="w-full h-full object-contain relative z-10 drop-shadow-[0_0_15px_rgba(0,240,255,0.5)] mix-blend-screen" alt="Logo" />
            </div>
            <div className="flex flex-col">
              <h1 className="font-display italic font-black text-2xl tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-white via-primary-neon to-white drop-shadow-[0_2px_2px_rgba(0,0,0,0.8)]">
                喵弟数据研究室
              </h1>
              <p className="text-[9px] font-black tracking-[0.3em] uppercase text-primary-neon/40">FUZZY LOGIC QUANT HUB</p>
            </div>
          </div>

          {/* Auth Button */}
          <div className="flex justify-center w-full mb-5">
            <Link 
              href="/login" 
              className="px-8 py-2 bg-primary-neon/10 border border-primary-neon/40 text-primary-neon font-bold rounded-full shadow-[0_0_15px_rgba(0,240,255,0.15)] hover:bg-primary-neon hover:text-black hover:shadow-[0_0_25px_rgba(0,240,255,0.4)] active:scale-95 transition-all text-sm tracking-widest font-display"
            >
              登录 / 注册
            </Link>
          </div>

          {/* Search Bar */}
          <div className="w-full mb-5 relative group">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
              <Search size={18} className="text-gray-400 group-focus-within:text-primary-neon transition-colors" />
            </div>
            <input
              type="text"
              placeholder="搜索球队、联赛或 AI 分析..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-white/5 border border-white/10 text-white text-sm rounded-full py-3 pl-11 pr-10 focus:outline-none focus:border-primary-neon/50 focus:ring-1 focus:ring-primary-neon/50 transition-all placeholder-gray-500 shadow-[inset_0_2px_4px_rgba(0,0,0,0.2)]"
            />
            {searchQuery && (
              <button 
                onClick={() => setSearchQuery('')}
                className="absolute inset-y-0 right-0 pr-4 flex items-center text-gray-400 hover:text-white transition-colors"
              >
                <X size={16} />
              </button>
            )}
          </div>

          {/* Date Filter Pills */}
          <div className="flex w-full justify-between items-center gap-2 overflow-x-auto pb-1">
            {([
              { key: 'yesterday', label: '昨天' },
              { key: 'today', label: '今天' },
              { key: 'tomorrow', label: '明天' },
              { key: 'all', label: '联赛筛选' },
            ] as const).map((item) => (
              <button
                key={item.key}
                onClick={() => setDateFilter(item.key)}
                className={`whitespace-nowrap flex-1 py-1.5 rounded-full text-sm font-medium transition-colors ${
                  dateFilter === item.key
                    ? 'bg-primary-neon/10 border border-primary-neon text-primary-neon shadow-[0_0_10px_rgba(0,240,255,0.2)]'
                    : 'bg-white/5 border border-white/10 text-gray-400 hover:text-white'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
        </header>

        {/* ── Match Content ── */}
        <main className="flex-1 px-4 overflow-y-auto pb-6">
          <AnimatePresence mode="wait">
            {filteredMatches.length === 0 ? (
              <motion.div
                key="empty"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="py-32 flex flex-col items-center justify-center text-center"
              >
                <Info className="w-12 h-12 mb-4 text-gray-700 animate-pulse" />
                <p className="text-[11px] font-black tracking-[0.3em] uppercase text-gray-600">暂无赛事数据</p>
                <p className="text-[10px] text-gray-700 mt-2 tracking-widest">尝试切换日期或搜索其他关键词</p>
              </motion.div>
            ) : (
              <motion.div
                key={dateFilter}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
              >
                {/* 焦点赛事 */}
                {ELITE_MATCH && (
                  <div className="mb-6">
                    <div className="flex justify-between items-center mb-3 px-1">
                      <h2 className="text-white font-display font-bold flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-primary-neon shadow-[0_0_8px_#00F0FF]" />
                        焦点赛事
                      </h2>
                      <div className="flex bg-white/5 rounded-full p-0.5 border border-white/10 backdrop-blur-md">
                        <button
                          onClick={() => setSortBy('hot')}
                          className={`px-3 py-1 rounded-full text-[10px] font-medium transition-all ${sortBy === 'hot' ? 'bg-primary-neon text-black shadow-[0_0_10px_rgba(0,240,255,0.3)]' : 'text-gray-400 hover:text-white'}`}
                        >
                          按热门
                        </button>
                        <button
                          onClick={() => setSortBy('time')}
                          className={`px-3 py-1 rounded-full text-[10px] font-medium transition-all ${sortBy === 'time' ? 'bg-primary-neon text-black shadow-[0_0_10px_rgba(0,240,255,0.3)]' : 'text-gray-400 hover:text-white'}`}
                        >
                          按时间
                        </button>
                      </div>
                    </div>
                    <MatchCard
                      match={ELITE_MATCH}
                      isFavorite={favorites.includes(ELITE_MATCH.id)}
                      onToggleFavorite={() => toggleFavorite(ELITE_MATCH.id)}
                      onClick={(e) => { e.stopPropagation(); setSelectedMatch(ELITE_MATCH); }}
                    />
                  </div>
                )}

                {/* 更多预测 */}
                {SUB_MATCHES.length > 0 && (
                  <div className="mt-2">
                    <div className="flex items-center gap-2 mb-4 px-1">
                      <span className="w-2 h-2 rounded-full bg-secondary-magenta shadow-[0_0_8px_#FF00E5]" />
                      <h2 className="text-white font-display font-bold">更多预测</h2>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      {SUB_MATCHES.map(m => (
                        <CompactMatchCard
                          key={m.id}
                          match={m}
                          isFavorite={favorites.includes(m.id)}
                          onToggleFavorite={() => toggleFavorite(m.id)}
                          onCardClick={() => setSelectedMatch(m)}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </main>

        {/* ── Match Detail Modal ── */}
        <AnimatePresence>
          {selectedMatch && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-[100] flex items-end sm:items-center justify-center p-4 bg-black/80 backdrop-blur-md"
              onClick={() => setSelectedMatch(null)}
            >
              <motion.div
                initial={{ y: 100, opacity: 0, scale: 0.95 }}
                animate={{ y: 0, opacity: 1, scale: 1 }}
                exit={{ y: 100, opacity: 0, scale: 0.95 }}
                transition={{ type: 'spring', bounce: 0.3, duration: 0.6 }}
                className="w-full max-w-md relative max-h-[90vh] flex flex-col rounded-3xl bg-[#0a0f1a] border border-white/10 shadow-[0_0_50px_rgba(0,240,255,0.15)] overflow-hidden"
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  className="absolute top-4 right-4 text-white/70 hover:text-white bg-black/50 p-2 rounded-full border border-white/20 transition-colors z-50"
                  onClick={() => setSelectedMatch(null)}
                >
                  <X size={20} />
                </button>
                <div className="overflow-y-auto">
                  <div className="p-1">
                    <MatchCard
                      match={selectedMatch}
                      isFavorite={favorites.includes(selectedMatch.id)}
                      onToggleFavorite={() => toggleFavorite(selectedMatch.id)}
                    />
                  </div>
                  <div className="px-6 pb-6 pt-2">
                    <Link
                      href={`/report/${selectedMatch.id}`}
                      className="w-full flex items-center justify-center gap-2 bg-primary-neon/10 text-primary-neon font-bold py-3.5 rounded-full border border-primary-neon/30 hover:bg-primary-neon hover:text-black transition-all duration-300 shadow-[0_0_15px_rgba(0,240,255,0.1)]"
                    >
                      <Activity size={18} />
                      查看完整深度分析
                    </Link>
                  </div>
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Bottom Navigation ── */}
        <div className="fixed bottom-0 left-0 right-0 max-w-md mx-auto h-32 bg-gradient-to-t from-[#010205] via-[#010205]/90 to-transparent pointer-events-none z-40" />
        <nav className="fixed bottom-0 left-0 right-0 max-w-md mx-auto bg-[#050814]/95 rounded-t-3xl border-t border-white/10 px-6 py-4 flex justify-between items-center z-50 shadow-[0_-8px_30px_rgba(0,0,0,0.8)] backdrop-blur-xl">
          <button className="flex flex-col items-center gap-1.5 text-primary-neon">
            <Activity size={26} className="drop-shadow-[0_0_10px_rgba(0,240,255,0.8)]" />
            <span className="text-[11px] font-bold tracking-wide">赛事</span>
          </button>
          <button className="flex flex-col items-center gap-1.5 text-gray-400 hover:text-white transition-colors">
            <History size={26} />
            <span className="text-[11px] font-bold tracking-wide">AI预测</span>
          </button>
          <button className="flex flex-col items-center gap-1.5 text-gray-400 hover:text-white transition-colors">
            <Crown size={26} />
            <span className="text-[11px] font-bold tracking-wide">VIP</span>
          </button>
          <Link href="/login" className="flex flex-col items-center gap-1.5 text-gray-400 hover:text-primary-neon transition-colors">
            <User size={26} />
            <span className="text-[11px] font-bold tracking-wide">我的</span>
          </Link>
        </nav>

      </div>
    </main>
  );
}
