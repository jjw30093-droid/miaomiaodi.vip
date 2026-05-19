'use client';

import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { useSession, signOut } from 'next-auth/react';
import { motion, AnimatePresence, LayoutGroup } from 'motion/react';
import {
  Activity,
  Cpu,
  Archive,
  User,
  Search,
  X,
  Check,
  Copy,
  Lock,
  Star,
  ChevronRight,
  Info,
  ChevronDown,
  Filter
} from 'lucide-react';
import { BackgroundEffects } from '@/components/BackgroundEffects';
import StrategyEquityChart from '@/components/StrategyEquityChart';
import ModelDashboard from '@/components/model/ModelDashboard';
import { apiClient } from '@/lib/apiClient';
import ThemeToggleButton from '@/components/ThemeToggleButton';
import { useTheme } from '@/components/ThemeProvider';

// ─── Types ───────────────────────────────────────────────────────────────────

interface Team {
  name: string;
  icon?: string;
  prob: number;
}

interface Match {
  id: string;
  league: string;
  time: string;
  display_category: 'UPCOMING' | 'ARCHIVE';
  homeTeam: Team;
  awayTeam: Team;
  status: string;
  drawProb?: number;
  inference?: string;
  is_daily_free?: boolean;
}

// ─── Sub-components ──────────────────────────────────────────────────────────

import { formatMatchTime } from '@/lib/formatTime';
const ProbabilityBar = ({ value, colorClass, lightColorClass }: { value: number, colorClass: string, lightColorClass?: string }) => {
  const [width, setWidth] = React.useState(0);
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  React.useEffect(() => {
    const t = setTimeout(() => setWidth(value), 80);
    return () => clearTimeout(t);
  }, [value]);
  const fillClass = (!isDark && lightColorClass) ? lightColorClass : colorClass;
  return (
    <div suppressHydrationWarning className={`relative h-1.5 w-full rounded-full overflow-hidden border ${isDark ? 'bg-white/5 border-white/5' : 'bg-black/10 border-black/10'}`}>
      <div
        className={`h-full rounded-full ${fillClass}`}
        style={{ width: `${width}%`, transition: 'width 0.9s ease-out' }}
      />
    </div>
  );
};

const CompactMatchCard = ({ match, isLoggedIn }: { match: Match, isLoggedIn: boolean, onClick: () => void }) => (
  <div
    onClick={() => window.location.href=`/report/${match.id}`}
    className={`relative glass-panel rounded-2xl p-4 flex flex-col items-center justify-center gap-3 cursor-pointer active:scale-95 transition-all hover:bg-white/5 overflow-hidden group ${match.display_category === 'ARCHIVE' ? 'opacity-60' : ''}`}
  >
    <div className="text-[9px] font-black tracking-widest text-primary-neon/60 uppercase absolute top-2 left-3">
      {match.league}
    </div>
    {match.is_daily_free && (
      <div className="absolute top-2 right-2 text-[7px] font-black text-green-400 border border-green-500/30 rounded-full px-1.5 py-0.5">
        今日免费
      </div>
    )}
    <div className="flex items-center justify-center gap-3 w-full mt-2">
      <img src={match.homeTeam.icon || "/logo_meow.jpg"} alt="H" className="w-8 h-8 rounded-full border border-white/10" />
      <span className="text-xs font-bold text-white/75">VS</span>
      <img src={match.awayTeam.icon || "/logo_meow.jpg"} alt="A" className="w-8 h-8 rounded-full border border-white/10" />
    </div>
    <div className="text-center w-full px-1">
      <div className="text-[11px] font-bold text-white mb-0.5 truncate">{match.homeTeam.name} vs {match.awayTeam.name}</div>
      <div className="text-[9px] text-white/75 font-medium">{formatMatchTime(match.time)}</div>
    </div>
    {isLoggedIn ? (
      <div className="w-full flex h-1 bg-white/5 rounded-full overflow-hidden">
        <div className="h-full bg-primary-neon" style={{ width: `${match.homeTeam.prob}%` }} />
        <div className="h-full bg-secondary-magenta" style={{ width: `${match.awayTeam.prob}%` }} />
      </div>
    ) : (
      <div className="w-full flex items-center justify-center gap-1 h-4">
        <Lock size={9} className="text-white/30" />
        <span className="text-[8px] text-[#1D4ED8] font-bold [text-shadow:0_0_6px_rgba(59,130,246,0.7)]">登录查看</span>
      </div>
    )}
  </div>
);

const MatchCard = ({ match, onClick, isLoggedIn }: { match: Match, onClick: () => void, isLoggedIn: boolean }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const isLocked = match.status === 'VIP';

  // 概率：API 可能返回 null（未鉴权），防止 null 导致 drawProb=100%
  const hProbRaw = match.homeTeam.prob != null ? Number(match.homeTeam.prob) : null;
  const aProbRaw = match.awayTeam.prob != null ? Number(match.awayTeam.prob) : null;
  const dProbRaw = match.drawProb     != null ? Number(match.drawProb)     : null;
  const hasProbs = hProbRaw != null && aProbRaw != null;
  const hProb    = hProbRaw ?? 0;
  const aProb    = aProbRaw ?? 0;
  const drawProb = (
    dProbRaw != null && dProbRaw > 0
      ? dProbRaw
      : hasProbs
        ? Math.max(0, 100 - hProb - aProb)
        : 0
  ).toFixed(1);
  // 有数据才渲染概率栏；无数据时退化为锁图标（即使已登录）
  const showProbs = isLoggedIn && hasProbs;

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
      onClick={onClick}
      className={`glass-panel rounded-3xl p-6 mb-5 relative overflow-hidden transition-all duration-300 hover:shadow-[0_20px_50px_rgba(0,0,0,0.4)] border border-white/5 active:scale-[0.98] ${match.display_category === 'ARCHIVE' ? 'opacity-70' : ''}`}
    >
      {/* Decorative Glows */}
      <div className="absolute top-0 right-0 w-32 h-32 bg-primary-neon/5 blur-[50px] -mr-10 -mt-10 rounded-full" />
      <div className="absolute bottom-0 left-0 w-32 h-32 bg-secondary-magenta/5 blur-[50px] -ml-10 -mb-10 rounded-full" />
      
      <div className="flex justify-between items-center mb-5 relative z-10">
        <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-white/5 border border-white/5">
          <span className="w-1.5 h-1.5 rounded-full bg-primary-neon animate-pulse" />
          <span className="text-xs font-black text-primary-neon tracking-widest uppercase">{match.league}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs font-bold text-white/75">{formatMatchTime(match.time)}</span>
          {isLocked && <Lock size={14} className="text-yellow-500 drop-shadow-[0_0_8px_rgba(234,179,8,0.5)]" />}
        </div>
      </div>

      <div className="flex justify-between items-center mb-8 relative z-10 px-2">
        <div className="flex flex-col items-center gap-3 w-2/5 text-center">
          <img src={match.homeTeam.icon || "/logo_meow.jpg"} alt="H" className="w-12 h-12 rounded-full border border-white/10 shadow-[0_0_15px_rgba(255,255,255,0.05)]" />
          <span className="font-bold text-sm text-white leading-tight min-h-[3em] flex items-center justify-center">{match.homeTeam.name}</span>
        </div>
        <div className="text-white/75 font-bold text-sm w-1/5 text-center">VS</div>
        <div className="flex flex-col items-center gap-3 w-2/5 text-center">
          <img src={match.awayTeam.icon || "/logo_meow.jpg"} alt="A" className="w-12 h-12 rounded-full border border-white/10 shadow-[0_0_15_rgba(255,255,255,0.05)]" />
          <span className="font-bold text-sm text-white leading-tight min-h-[3em] flex items-center justify-center">{match.awayTeam.name}</span>
        </div>
      </div>

      {showProbs ? (
        <div className="grid grid-cols-3 gap-6 relative z-10">
          <div className="flex flex-col items-center gap-2">
            <span className="text-[10px] font-black text-white/50 tracking-widest uppercase">主胜</span>
            <span className="text-2xl font-black text-primary-neon drop-shadow-[0_0_10px_rgba(0,240,255,0.3)]">{hProb}%</span>
            <ProbabilityBar value={hProb} colorClass="bg-primary-neon" />
          </div>
          <div className="flex flex-col items-center gap-2">
            <span className="text-[10px] font-black text-white/50 tracking-widest uppercase">平局</span>
            <span className="text-2xl font-black text-white/80">{drawProb}%</span>
            <ProbabilityBar value={Number(drawProb)} colorClass="bg-white/30" lightColorClass="bg-black/40" />
          </div>
          <div className="flex flex-col items-center gap-2">
            <span className="text-[10px] font-black text-white/50 tracking-widest uppercase">客胜</span>
            <span className="text-2xl font-black text-secondary-magenta drop-shadow-[0_0_10px_rgba(219,39,119,0.3)]">{aProb}%</span>
            <ProbabilityBar value={aProb} colorClass="bg-secondary-magenta" />
          </div>
        </div>
      ) : (
        <div className="relative z-10 grid grid-cols-3 gap-6">
          {['主胜', '平局', '客胜'].map(label => (
            <div key={label} className="flex flex-col items-center gap-2">
              <span className="text-[10px] font-black text-white/50 tracking-widest uppercase">{label}</span>
              <div className="flex items-center justify-center w-full h-8">
                <Lock size={16} className="text-white/30" />
              </div>
              <div className="h-1.5 w-full bg-white/5 rounded-full" />
            </div>
          ))}
          <div className="col-span-3 mt-1">
            <Link
              href="/login"
              onClick={e => e.stopPropagation()}
              className="block w-full text-center py-2.5 rounded-full bg-primary-neon/10 border border-primary-neon/30 text-primary-neon text-xs font-black tracking-widest hover:bg-primary-neon/20 transition-all"
            >
              登录解锁胜平负概率
            </Link>
          </div>
        </div>
      )}

    </div>
  );
};

// ─── Main Hub Component ───────────────────────────────────────────────────

export default function FootballLabPage() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const { data: session } = useSession();
  const isLoggedIn = !!session?.user;

  // 用户区块所需变量（复用 Navbar 逻辑）
  const avatarUrl = (session?.user as any)?.avatarUrl as string | undefined;
  const isVip = (session?.user as any)?.role === 'vip';
  const avatarSrc = avatarUrl
    ? (avatarUrl.startsWith('/static') ? `http://localhost:8000${avatarUrl}` : avatarUrl)
    : null;

  const [activeTab, setActiveTab] = useState<'matches' | 'model' | 'archive' | 'profile'>('matches');
  const [dateFilter, setDateFilter] = useState<'today' | 'tomorrow' | 'all'>('all');
  const [leagueFilters, setLeagueFilters] = useState<Set<string>>(new Set()); // empty = all
  const [pendingLeagues, setPendingLeagues] = useState<Set<string>>(new Set());
  const [showLeagueDropdown, setShowLeagueDropdown] = useState(false);
  const [dropdownPos, setDropdownPos] = useState({ top: 0, right: 0 });
  const leagueBtnRef = React.useRef<HTMLDivElement>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const data = await apiClient.get<Match[]>('/reports/latest');
        setMatches(data || []);
      } catch (e) {
        console.error('API Error:', e);
        setError('服务连接超时，请检查网络。');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const availableLeagues = useMemo(() => {
    const upcomingLeagues = matches
      .filter(m => m.display_category === 'UPCOMING')
      .map(m => m.league)
      .filter(Boolean);
    return Array.from(new Set(upcomingLeagues)).sort();
  }, [matches]);

  const filteredMatches = useMemo(() => {
    const now = new Date();
    const toDateStr = (d: Date) => d.toDateString();

    let list = matches.filter(m => {
      const matchSearch = searchQuery === '' ||
        m.homeTeam.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        m.awayTeam.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        m.league.toLowerCase().includes(searchQuery.toLowerCase());

      if (!matchSearch) return false;

      // Tab-specific secondary filtering
      if (activeTab === 'matches') {
        if (m.display_category !== 'UPCOMING') return false;
        if (leagueFilters.size > 0 && !leagueFilters.has(m.league)) return false;

        if (dateFilter === 'all') return true;
        const matchDate = new Date(m.time.replace(' ', 'T'));
        if (dateFilter === 'today') return toDateStr(matchDate) === toDateStr(now);
        if (dateFilter === 'tomorrow') {
          const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1);
          return toDateStr(matchDate) === toDateStr(tomorrow);
        }
      } else if (activeTab === 'archive') {
        if (m.display_category !== 'ARCHIVE') return false;
      }

      return true;
    });

    return list.sort((a, b) => {
      return new Date(a.time.replace(' ', 'T')).getTime() - new Date(b.time.replace(' ', 'T')).getTime();
    });
  }, [matches, searchQuery, dateFilter, leagueFilters, activeTab]);

  const ELITE_MATCH = filteredMatches[0];
  const OTHER_MATCHES = filteredMatches.slice(1, 9);

  return (
    <div className="min-h-screen overflow-x-hidden font-sans pb-32">
      <BackgroundEffects />
      
      <div className="max-w-md mx-auto relative z-10 px-6">
        {/* Header */}
        <header className="pt-8 pb-6 flex flex-col items-center">
          <div className="flex items-center justify-between gap-4 mb-6">
            <div className="flex items-center gap-4">
              <div className="relative w-14 h-14 flex-shrink-0 animate-float">
                <div className="absolute inset-0 bg-primary-neon/10 blur-xl rounded-full" />
                <Image
                  src="/logo_meow.jpg"
                  alt="喵弟数据研究室 Logo"
                  width={56}
                  height={56}
                  className="w-full h-full object-contain relative z-10 rounded-full dark:drop-shadow-[0_0_15px_rgba(0,240,255,0.5)]"
                  priority
                />
              </div>
              <div className="flex flex-col">
                <h1 suppressHydrationWarning className={`font-display italic font-black text-2xl tracking-[0.1em] bg-clip-text text-transparent bg-gradient-to-r ${isDark ? 'from-white via-primary-neon to-white' : 'from-red-500 via-blue-500 to-red-400'}`}>
                  喵弟数据研究室
                </h1>
                <p className="text-[9px] font-black text-[#C9A84C] w-full [text-align-last:justify] [text-shadow:0_0_8px_rgba(201,168,76,0.9),0_0_18px_rgba(201,168,76,0.5)]">miaomiaodi.cc</p>
              </div>
            </div>
            <ThemeToggleButton />
          </div>

          {/* Auth + Search Row — 放大镜点击后向左滑动，搜索框从右侧扩展 */}
          <LayoutGroup id="auth-search-row">
            <div className="flex items-center w-full mb-6 gap-2 min-h-[38px]">

              {/* 左侧内容区：Auth content ↔ Search input，互相切换 */}
              <AnimatePresence mode="popLayout" initial={false}>
                {searchOpen ? (
                  /* 搜索模式：搜索框从右侧滑入 */
                  <motion.div
                    key="search-input-row"
                    initial={{ opacity: 0, x: 28 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 28 }}
                    transition={{ duration: 0.22, ease: [0.25, 0.46, 0.45, 0.94] }}
                    className="flex-1 min-w-0 relative group"
                  >
                    <Search size={14} className={`absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none group-focus-within:text-primary-neon transition-colors ${isDark ? 'text-white/40' : 'text-black/40'}`} />
                    <input
                      suppressHydrationWarning
                      autoFocus
                      type="text"
                      placeholder="搜索俱乐部、联赛..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className={`w-full rounded-full py-2.5 pl-9 pr-4 text-sm font-medium focus:outline-none focus:border-primary-neon/40 transition-all ${isDark ? 'bg-white/5 border border-white/10 text-white placeholder-white/40' : 'bg-black/5 border border-black/15 text-black placeholder-black/40'}`}
                    />
                  </motion.div>
                ) : (
                  /* 默认模式：Auth 内容从左侧滑入 */
                  <motion.div
                    key="auth-content"
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: -20 }}
                    transition={{ duration: 0.22, ease: [0.25, 0.46, 0.45, 0.94] }}
                    className="flex-1 min-w-0"
                  >
                    {isLoggedIn ? (
                      /* 已登录：显示头像 + 昵称 + VIP 徽章 */
                      <div className="flex items-center justify-between w-full px-1">
                        <div className="flex items-center gap-3">
                          <div
                            className="relative w-9 h-9 rounded-xl overflow-hidden flex-shrink-0"
                            style={{
                              border: isVip
                                ? '2px solid rgba(191,165,93,0.6)'
                                : '2px solid rgba(0,255,195,0.3)',
                            }}
                          >
                            {avatarSrc ? (
                              <Image src={avatarSrc} alt="avatar" fill className="object-cover" unoptimized />
                            ) : (
                              <span className="flex items-center justify-center w-full h-full text-base" style={{ background: '#12161b' }}>🐱</span>
                            )}
                          </div>
                          <div className="flex flex-col gap-0.5">
                            <span className="text-xs font-bold text-white leading-tight">{session?.user?.name || '用户'}</span>
                            {isVip && (
                              <span
                                className="text-[9px] font-black px-1.5 py-0.5 rounded-full w-fit leading-tight"
                                style={{ background: 'rgba(191,165,93,0.15)', color: '#BFA55D', border: '1px solid rgba(191,165,93,0.3)' }}
                              >
                                VIP
                              </span>
                            )}
                            {!isVip && (
                              <span className="text-[9px] text-white/50 leading-tight">普通会员</span>
                            )}
                          </div>
                        </div>
                        <Link
                          href="/center?tab=profile"
                          suppressHydrationWarning
                          className={`px-4 py-1.5 font-bold rounded-full text-xs tracking-widest transition-all ${isDark ? 'bg-white/5 border border-white/10 text-white/70 hover:bg-white/10' : 'bg-black/8 border border-black/15 text-black hover:bg-black/15'}`}
                        >
                          个人中心
                        </Link>
                      </div>
                    ) : (
                      /* 未登录：显示登录 / 注册按钮 */
                      <Link
                        href="/login"
                        suppressHydrationWarning
                        className={`inline-block px-8 py-2 font-bold rounded-full active:scale-95 transition-all duration-200 text-sm tracking-widest ${
                          isDark
                            ? 'bg-primary-neon/10 border border-primary-neon/50 text-white shadow-[0_0_16px_rgba(0,240,255,0.22),inset_0_0_12px_rgba(0,240,255,0.06)] hover:bg-primary-neon/[0.18] hover:border-primary-neon/70 hover:shadow-[0_0_28px_rgba(0,240,255,0.38),inset_0_0_16px_rgba(0,240,255,0.10)]'
                            : 'bg-amber-100/60 border border-amber-400/50 text-red-500 shadow-[0_0_14px_rgba(201,168,76,0.30),inset_0_0_10px_rgba(201,168,76,0.12)] hover:bg-amber-100/80 hover:border-amber-400/70 hover:shadow-[0_0_22px_rgba(201,168,76,0.45),inset_0_0_14px_rgba(201,168,76,0.18)] drop-shadow-[0_0_6px_rgba(239,68,68,0.55)]'
                        }`}
                      >
                        登录 / 注册
                      </Link>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>

              {/* 放大镜/关闭按钮 — layout 动画使其在 auth 退出时向左平移 */}
              <motion.button
                layout="position"
                transition={{ layout: { duration: 0.22, ease: [0.25, 0.46, 0.45, 0.94] } }}
                onClick={() => setSearchOpen(v => !v)}
                suppressHydrationWarning
                className={`flex-shrink-0 w-9 h-9 flex items-center justify-center rounded-full transition-colors ${
                  isDark
                    ? 'bg-white/5 border border-white/10 hover:bg-white/10 hover:border-primary-neon/40'
                    : 'bg-[rgba(210,216,226,0.82)] border border-[rgba(140,150,175,0.25)] shadow-[0_2px_8px_rgba(0,0,0,0.06)] hover:bg-[rgba(200,207,218,0.92)] hover:border-[rgba(140,150,175,0.40)]'
                }`}
                aria-label={searchOpen ? '关闭搜索' : '搜索'}
              >
                <AnimatePresence mode="wait" initial={false}>
                  {searchOpen ? (
                    <motion.span key="x" initial={{ rotate: -90, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} exit={{ rotate: 90, opacity: 0 }} transition={{ duration: 0.12 }}>
                      <X size={14} className="text-white/60" />
                    </motion.span>
                  ) : (
                    <motion.span key="mag" initial={{ rotate: 90, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} exit={{ rotate: -90, opacity: 0 }} transition={{ duration: 0.12 }}>
                      <Search size={15} className="text-white/60" />
                    </motion.span>
                  )}
                </AnimatePresence>
              </motion.button>

            </div>
          </LayoutGroup>

          <div className="flex w-full gap-2 overflow-x-auto no-scrollbar items-center">
            {[
              { id: 'all', label: '全部' },
              { id: 'today', label: '今日' },
              { id: 'tomorrow', label: '明日' },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setDateFilter(tab.id as any)}
                suppressHydrationWarning
                className={`flex-1 py-2 rounded-full text-xs font-bold transition-all border whitespace-nowrap ${
                  dateFilter === tab.id
                    ? isDark
                      ? 'bg-primary-neon/10 border-primary-neon text-primary-neon'
                      : 'bg-red-500/8 border-red-500 text-red-500 shadow-[0_0_10px_rgba(239,68,68,0.25)]'
                    : isDark
                      ? 'bg-white/5 border-white/10 text-white/75'
                      : 'bg-white/30 border-slate-300/50 text-slate-500'
                }`}
              >
                {tab.label}
              </button>
            ))}
            {/* League filter — multi-select */}
            <div className="relative flex-1" ref={leagueBtnRef}>
              <button
                onClick={() => {
                  if (leagueBtnRef.current) {
                    const r = leagueBtnRef.current.getBoundingClientRect();
                    setDropdownPos({ top: r.bottom + 8, right: window.innerWidth - r.right });
                  }
                  setPendingLeagues(new Set(leagueFilters));
                  setShowLeagueDropdown(v => !v);
                }}
                suppressHydrationWarning
                className={`w-full flex items-center justify-center gap-1 py-2 rounded-full text-xs font-bold transition-all border whitespace-nowrap ${
                  leagueFilters.size > 0
                    ? isDark
                      ? 'bg-primary-neon/10 border-primary-neon text-primary-neon'
                      : 'bg-red-500/8 border-red-500 text-red-500 shadow-[0_0_10px_rgba(239,68,68,0.25)]'
                    : isDark
                      ? 'bg-white/5 border-white/10 text-white/75'
                      : 'bg-white/30 border-slate-300/50 text-slate-500'
                }`}
              >
                <Filter size={9} />
                <span className="truncate max-w-[48px]">联赛{leagueFilters.size > 0 ? ` ×${leagueFilters.size}` : ''}</span>
                <ChevronDown size={9} className={`transition-transform duration-200 ${showLeagueDropdown ? 'rotate-180' : ''}`} />
              </button>

              {/* backdrop — outside AnimatePresence so it doesn't interfere */}
              {showLeagueDropdown && (
                <div className="fixed inset-0 z-40" onClick={() => setShowLeagueDropdown(false)} />
              )}

              <AnimatePresence>
                {showLeagueDropdown && (
                    <motion.div
                      key="league-dropdown"
                      initial={{ opacity: 0, y: -6, scale: 0.97 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: -6, scale: 0.97 }}
                      transition={{ duration: 0.15, ease: 'easeOut' }}
                      style={{ position: 'fixed', top: dropdownPos.top, right: dropdownPos.right, zIndex: 9999 }}
                      className="bg-[#0a0d18] border border-white/10 rounded-2xl shadow-2xl overflow-hidden min-w-[140px]"
                    >
                      {/* 联赛列表 */}
                      <div className="py-2 max-h-[260px] overflow-y-auto">
                        {availableLeagues.length === 0 ? (
                          <p className="text-[10px] text-white/30 text-center py-4 px-4">暂无联赛数据</p>
                        ) : (
                          availableLeagues.map(league => {
                            const checked = pendingLeagues.has(league);
                            return (
                              <button
                                key={league}
                                onClick={() => {
                                  setPendingLeagues(prev => {
                                    const next = new Set(prev);
                                    checked ? next.delete(league) : next.add(league);
                                    return next;
                                  });
                                }}
                                className="w-full flex items-center gap-3 px-4 py-2.5 text-xs font-bold transition-colors hover:bg-white/5"
                              >
                                {/* checkbox */}
                                <span className={`w-4 h-4 rounded flex items-center justify-center border flex-shrink-0 transition-all ${checked ? 'bg-primary-neon border-primary-neon' : 'border-white/20 bg-transparent'}`}>
                                  {checked && (
                                    <svg width="9" height="7" viewBox="0 0 9 7" fill="none">
                                      <path d="M1 3.5L3.5 6L8 1" stroke="#000" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                                    </svg>
                                  )}
                                </span>
                                <span className={checked ? 'text-primary-neon' : 'text-white/75'}>{league}</span>
                              </button>
                            );
                          })
                        )}
                      </div>

                      {/* 底部操作栏 */}
                      <div className="flex items-center gap-2 px-3 py-2.5 border-t border-white/5">
                        <button
                          onClick={() => {
                            setPendingLeagues(new Set());
                          }}
                          className="flex-1 py-1.5 text-[10px] font-bold text-white/40 hover:text-white/70 transition-colors rounded-full border border-white/10 hover:border-white/20"
                        >
                          清除
                        </button>
                        <button
                          onClick={() => {
                            setLeagueFilters(new Set(pendingLeagues));
                            setShowLeagueDropdown(false);
                          }}
                          className="flex-1 py-1.5 text-[10px] font-bold rounded-full bg-primary-neon/10 border border-primary-neon/40 text-primary-neon hover:bg-primary-neon/20 transition-colors"
                        >
                          确认{pendingLeagues.size > 0 ? `（${pendingLeagues.size}）` : ''}
                        </button>
                      </div>
                    </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </header>

        {/* Content Tabs */}
        <main className="min-h-[400px]">
          {activeTab === 'matches' && (
            loading ? (
              <div className="flex flex-col items-center justify-center py-24 gap-4">
                <div className="w-10 h-10 border-2 border-primary-neon/20 border-t-primary-neon rounded-full animate-spin" />
                <p className="text-[10px] font-bold text-white/50 tracking-widest animate-pulse uppercase">Syncing Neural Nodes...</p>
              </div>
            ) : error ? (
              <div className="glass-panel p-10 text-center rounded-3xl border-red-500/20">
                <Info className="w-10 h-10 text-red-500/40 mx-auto mb-4" />
                <p className="text-sm font-bold text-red-400 mb-6">{error}</p>
                <button onClick={() => window.location.reload()} className="px-8 py-2 bg-white/5 rounded-full text-xs font-bold border border-white/10">点击重试</button>
              </div>
            ) : filteredMatches.length === 0 ? (
              <div className="py-24 text-center opacity-30">
                 <Activity size={48} className="mx-auto mb-6 opacity-20" />
                 <p className="font-display italic font-bold tracking-widest text-lg">NO QUANT DATA FOUND</p>
                 <p className="text-xs mt-2 font-medium tracking-tighter">当前时段暂无符合量化标准的预测报告</p>
              </div>
            ) : (
              <>
                {ELITE_MATCH && (
                  <section className="mb-10">
                    <div className="flex items-center gap-2 mb-4">
                      <span className="w-1.5 h-1.5 rounded-full bg-primary-neon shadow-[0_0_8px_#00F0FF]" />
                      <h2 className="text-xs font-black tracking-widest uppercase text-white/80">焦点模型深度解析</h2>
                    </div>
                    <MatchCard match={ELITE_MATCH} isLoggedIn={isLoggedIn} onClick={() => window.location.href=`/report/${ELITE_MATCH.id}`} />
                  </section>
                )}

                {OTHER_MATCHES.length > 0 && (
                  <section>
                     <div className="flex items-center gap-2 mb-4">
                      <span className="w-1.5 h-1.5 rounded-full bg-secondary-magenta shadow-[0_0_8px_#FF00E5]" />
                      <h2 className="text-xs font-black tracking-widest uppercase text-white/80">后续研报预览</h2>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      {OTHER_MATCHES.map(m => (
                        <CompactMatchCard key={m.id} match={m} isLoggedIn={isLoggedIn} onClick={() => window.location.href=`/report/${m.id}`} />
                      ))}
                    </div>
                  </section>
                )}
              </>
            )
          )}

          {activeTab === 'model' && (
            <section>
              <ModelDashboard />
            </section>
          )}

          {activeTab === 'archive' && (
            <section className="animate-in fade-in duration-500 pb-12">
               <div className="flex items-center justify-between mb-6">
                 <div className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-gray-500 shadow-[0_0_8px_rgba(255,255,255,0.2)]" />
                    <h2 className="text-sm font-black tracking-widest uppercase text-white/80 font-display">历史研报数据库</h2>
                  </div>
                  <span className="text-[10px] font-bold text-white/50 uppercase tracking-tighter">Total {filteredMatches.length}</span>
               </div>
               
               {filteredMatches.length === 0 ? (
                 <div className="py-24 text-center opacity-30">
                    <Archive size={48} className="mx-auto mb-6 opacity-20" />
                    <p className="font-display italic font-bold tracking-widest text-lg uppercase">Archive Vault Empty</p>
                    <p className="text-xs mt-2 font-medium tracking-tighter">当前没有符合筛选条件的归档记录</p>
                 </div>
               ) : (
                 <div className="grid grid-cols-2 gap-4">
                   {filteredMatches.map(m => (
                     <CompactMatchCard key={m.id} match={m} isLoggedIn={isLoggedIn} onClick={() => window.location.href=`/report/${m.id}`} />
                   ))}
                 </div>
               )}
            </section>
          )}

          {activeTab === 'profile' && (
             <div className="py-24 text-center opacity-30">
               <User size={48} className="mx-auto mb-6 opacity-20" />
               <p className="font-display italic font-bold tracking-widest text-lg uppercase">User Profile</p>
               <p className="text-xs mt-2 font-medium tracking-tighter">请先登录实验室查看您的账户状态</p>
            </div>
          )}
        </main>
      </div>

      {/* Nav */}
      <div className="fixed bottom-0 left-0 right-0 max-w-md mx-auto px-6 pb-6 z-50 pointer-events-none">
        <nav className="bg-[#050814]/95 border border-white/10 rounded-full px-8 py-4 flex justify-between items-center backdrop-blur-xl shadow-[0_20px_50px_rgba(0,0,0,0.8)] pointer-events-auto">
          <button 
            onClick={() => setActiveTab('matches')}
            className={`flex flex-col items-center gap-1 transition-all ${activeTab === 'matches' ? 'text-primary-neon' : 'text-white/75 hover:text-white'}`}
          >
            <Activity size={24} className={activeTab === 'matches' ? "drop-shadow-[0_0_8px_rgba(0,240,255,0.8)]" : ""} />
            <span className="text-[10px] font-bold tracking-tight">赛事</span>
          </button>
          <button 
            onClick={() => setActiveTab('model')}
            className={`flex flex-col items-center gap-1 transition-all ${activeTab === 'model' ? 'text-white' : 'text-white/75 hover:text-white'}`}
          >
            <Cpu size={24} className={activeTab === 'model' ? "text-primary-neon drop-shadow-[0_0_8px_rgba(0,240,255,0.8)]" : ""} />
            <span className="text-[10px] font-bold tracking-tight">模型</span>
          </button>
          <button 
            onClick={() => setActiveTab('archive')}
            className={`flex flex-col items-center gap-1 transition-all ${activeTab === 'archive' ? 'text-white' : 'text-white/75 hover:text-white'}`}
          >
            <Archive size={24} className={activeTab === 'archive' ? "text-primary-neon drop-shadow-[0_0_8px_rgba(0,240,255,0.8)]" : ""} />
            <span className="text-[10px] font-bold tracking-tight">归档</span>
          </button>
          <button 
            onClick={() => setActiveTab('profile')}
            className={`flex flex-col items-center gap-1 transition-all ${activeTab === 'profile' ? 'text-white' : 'text-white/75 hover:text-primary-neon'}`}
          >
            <User size={24} className={activeTab === 'profile' ? "text-primary-neon drop-shadow-[0_0_8px_rgba(0,240,255,0.8)]" : ""} />
            <span className="text-[10px] font-bold tracking-tight">我的</span>
          </button>
        </nav>
      </div>
    </div>
  );
}
