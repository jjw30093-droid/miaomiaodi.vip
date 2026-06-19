'use client';

import React, { useState, useEffect, useMemo } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { usePathname } from 'next/navigation';
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
import { apiClient } from '@/lib/apiClient';
import ThemeToggleButton from '@/components/ThemeToggleButton';
import { useTheme } from '@/components/ThemeProvider';
import ContactAdminModal from '@/components/ContactAdminModal';
import Footer from '@/components/layout/Footer';
import { translateLeague } from '@/lib/leagueNames';
import { translateTeam } from '@/lib/teamNames';

// ─── Types ───────────────────────────────────────────────────────────────────

interface Team {
  name: string;
  icon?: string;
  prob: number | null;
}

interface Match {
  id: string;
  league: string;
  time: string;
  display_category: 'UPCOMING' | 'ARCHIVE' | 'GATED';
  homeTeam: Team;
  awayTeam: Team;
  status: string;
  drawProb?: number | null;
  inference?: string;
  is_daily_free?: boolean;
  picked_correct?: number | null;  // 1=命中 0=未中 -1=走水 null=未结算/未出
  tournament_type?: string;
}

const MATCH_PAGE_SIZE = 10;

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

const CompactMatchCard = ({ match, isLoggedIn, isDark, onClick }: { match: Match, isLoggedIn: boolean, onClick: () => void, isDark: boolean }) => {
  // API 返回已是百分比（0~100），直接取整即可，不再 ×100
  const hPctRaw = match.homeTeam.prob != null ? Number(match.homeTeam.prob) : null;
  const aPctRaw = match.awayTeam.prob != null ? Number(match.awayTeam.prob) : null;
  const hasPct  = hPctRaw != null && aPctRaw != null;
  const hPct    = Math.round(hPctRaw ?? 0);
  const aPct    = Math.round(aPctRaw ?? 0);
  const leagueZh = translateLeague(match.league);
  // 结算标签：1=命中 0=未中 -1=走水 null=未结算/未出
  const pc = match.picked_correct;
  const resultStamp =
      pc === 1             ? { text: '命中', cls: isDark ? 'bg-red-500/10 text-red-400 border-red-500/50'  : 'bg-red-50 text-red-600 border-red-400' }
    : pc === 0             ? { text: '未中', cls: isDark ? 'bg-white/[0.04] text-white/40 border-white/15' : 'bg-zinc-100 text-zinc-400 border-zinc-300' }
    : pc === -1            ? { text: '走水', cls: isDark ? 'bg-sky-500/10 text-sky-300 border-sky-500/40'  : 'bg-sky-50 text-sky-600 border-sky-300' }
    : null;

  return (
  <button
    type="button"
    onClick={onClick}
    suppressHydrationWarning
    className={`relative w-full rounded-2xl px-5 py-4 text-left active:scale-[0.99] transition-all ${
      isDark
        ? 'glass-panel hover:bg-white/5'
        : 'bg-white shadow-[0px_4px_16px_rgba(25,28,29,0.06)] hover:shadow-[0px_8px_24px_rgba(25,28,29,0.10)]'
    }`}
  >
    {/* 内容层 — ARCHIVE 时整体变暗，命中印章不在此层 */}
    <div className={match.display_category === 'ARCHIVE' ? (isDark ? 'opacity-45' : 'opacity-50') : undefined}>
      {/* 联赛 + 时间 */}
      <div className="flex items-center justify-between mb-3">
        <span className={`text-xs font-bold ${isDark ? 'text-[var(--primary-neon)]/70' : 'text-[#005faf]'}`}>{leagueZh}</span>
        <span className={`text-xs font-medium ${isDark ? 'text-white/50' : 'text-[#5b3f43]'}`}>{formatMatchTime(match.time)}</span>
      </div>
      {/* 主队 VS 客队 */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <img src={match.homeTeam.icon || "/logo_meow.jpg"} alt="H" className={`w-10 h-10 rounded-full shrink-0 ${isDark ? 'border border-white/10' : 'border border-[#e1e3e4]'}`} />
          <span className={`text-base font-bold truncate ${isDark ? 'text-white' : 'text-[#191c1d]'}`}>{match.homeTeam.name}</span>
        </div>
        <span className={`text-sm font-bold shrink-0 px-2 ${isDark ? 'text-white/40' : 'text-[#5b3f43]'}`}>VS</span>
        <div className="flex items-center gap-3 flex-1 min-w-0 justify-end">
          <span className={`text-base font-bold truncate text-right ${isDark ? 'text-white' : 'text-[#191c1d]'}`}>{match.awayTeam.name}</span>
          <img src={match.awayTeam.icon || "/logo_meow.jpg"} alt="A" className={`w-10 h-10 rounded-full shrink-0 ${isDark ? 'border border-white/10' : 'border border-[#e1e3e4]'}`} />
        </div>
      </div>
    </div>
    {/* 结算印章 — 绝对定位，不在内容层内，保持全亮（命中/未中/走水） */}
    {resultStamp && (
      <span suppressHydrationWarning className={`absolute right-4 top-1/2 -translate-y-1/2 text-sm font-black px-3 py-1.5 rounded-full pointer-events-none border-2 ${resultStamp.cls}`}>{resultStamp.text}</span>
    )}
  </button>
  );
};

const MatchCard = ({ match, onClick, isLoggedIn, isDark }: { match: Match, onClick: () => void, isLoggedIn: boolean, isDark: boolean }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const isLocked = false;

  // 概率：API 可能返回 null（未鉴权），防止 null 导致 drawProb=100%
  const hProbRaw = match.homeTeam.prob != null ? Number(match.homeTeam.prob) : null;
  const aProbRaw = match.awayTeam.prob != null ? Number(match.awayTeam.prob) : null;
  const dProbRaw = match.drawProb     != null ? Number(match.drawProb)     : null;
  const hasProbs = hProbRaw != null && aProbRaw != null;
  // API 返回已是百分比（0~100），直接取整即可，不再 ×100
  const hProb    = Math.round(hProbRaw ?? 0);
  const aProb    = Math.round(aProbRaw ?? 0);
  const drawProb = Math.round(
    dProbRaw != null && dProbRaw > 0
      ? dProbRaw
      : hasProbs
        ? Math.max(0, 100 - hProb - aProb)
        : 0
  );
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

  if (!isDark) {
    // ── Stitch Light Mode Card ──────────────────────────────
    return (
      <div
        onClick={onClick}
        suppressHydrationWarning
        className={`bg-white rounded-[1.5rem] p-6 mb-5 relative overflow-hidden transition-all duration-300 shadow-[0px_12px_32px_rgba(25,28,29,0.06)] active:scale-[0.98] cursor-pointer hover:shadow-[0px_16px_40px_rgba(25,28,29,0.10)] ${match.display_category === 'ARCHIVE' ? 'opacity-70' : ''}`}
      >
        {/* Soft bg glow */}
        <div className="absolute top-0 right-0 w-32 h-32 bg-[#ffd9de] rounded-full blur-[40px] -mr-10 -mt-10 opacity-30 pointer-events-none" />

        {/* League + Time */}
        <div className="flex justify-between items-center mb-6 relative z-10">
          <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-[#d4e3ff]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#005faf]" />
            <span className="text-xs font-bold text-[#003567] tracking-wider uppercase">{translateLeague(match.league)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-[#5b3f43] bg-[#f2f4f5] px-2 py-0.5 rounded-full">{formatMatchTime(match.time)}</span>
            {isLocked && <Lock size={13} className="text-[#924700]" />}
          </div>
        </div>

        {/* Teams */}
        <div className="flex justify-between items-center mb-6 relative z-10">
          <div className="flex flex-col items-center gap-2 w-[40%] text-center">
            <img src={match.homeTeam.icon || "/logo_meow.jpg"} alt="H" className="w-12 h-12 rounded-full border border-[#e1e3e4] object-contain" />
            <span className="font-bold text-sm text-[#191c1d] leading-tight">{match.homeTeam.name}</span>
          </div>
          <div className="flex flex-col items-center justify-center w-[20%]">
            <span className="text-xs font-medium text-[#5b3f43] bg-[#e1e3e4] px-2 py-1 rounded-full">VS</span>
          </div>
          <div className="flex flex-col items-center gap-2 w-[40%] text-center">
            <img src={match.awayTeam.icon || "/logo_meow.jpg"} alt="A" className="w-12 h-12 rounded-full border border-[#e1e3e4] object-contain" />
            <span className="font-bold text-sm text-[#191c1d] leading-tight">{match.awayTeam.name}</span>
          </div>
        </div>

        {/* Probabilities */}
        {showProbs ? (
          <div className="bg-[#f2f4f5] rounded-xl p-4 relative z-10">
            <p className="text-xs font-bold text-[#5b3f43] mb-3 text-center uppercase tracking-widest">模型预测</p>
            <div className="flex justify-between items-end gap-2 h-16">
              <div className="flex flex-col items-center justify-end w-1/3 h-full">
                <div className="w-full bg-[#b7004d]/20 rounded-t-md relative flex items-end justify-center" style={{ height: `${Math.max(hProb, 8)}%` }}>
                  <span className="text-xs font-bold text-[#b7004d] absolute -top-4">{hProb}%</span>
                </div>
                <span className="text-xs text-[#191c1d] mt-1 font-medium">主胜</span>
              </div>
              <div className="flex flex-col items-center justify-end w-1/3 h-full">
                <div className="w-full bg-[#005faf]/20 rounded-t-md relative flex items-end justify-center" style={{ height: `${Math.max(drawProb, 8)}%` }}>
                  <span className="text-xs font-bold text-[#005faf] absolute -top-4">{drawProb}%</span>
                </div>
                <span className="text-xs text-[#191c1d] mt-1 font-medium">平局</span>
              </div>
              <div className="flex flex-col items-center justify-end w-1/3 h-full">
                <div className="w-full bg-[#b7004d] rounded-t-md relative flex items-end justify-center" style={{ height: `${Math.max(aProb, 8)}%` }}>
                  <span className="text-xs font-bold text-[#b7004d] absolute -top-4">{aProb}%</span>
                </div>
                <span className="text-xs text-[#191c1d] mt-1 font-medium">客胜</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="bg-[#f2f4f5] rounded-xl p-4 relative z-10">
            <div className="flex items-center justify-center gap-2 py-2">
              <Lock size={14} className="text-[#8f6f73]" />
              <span className="text-sm font-bold text-[#b7004d]">加微信开通查看</span>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── Dark Mode Card (original) ───────────────────────────
  return (
    <div
      onClick={onClick}
      className={`glass-panel rounded-3xl p-6 mb-5 relative overflow-hidden transition-all duration-300 hover:shadow-md border border-white/5 active:scale-[0.98] ${match.display_category === 'ARCHIVE' ? 'opacity-70' : ''}`}
    >
      {/* Decorative Glows — theme-only decoration */}
      <div className="absolute top-0 right-0 w-32 h-32 bg-[var(--primary-neon)]/5 blur-[50px] -mr-10 -mt-10 rounded-full" />
      <div className="absolute bottom-0 left-0 w-32 h-32 bg-secondary-magenta/5 blur-[50px] -ml-10 -mb-10 rounded-full" />

      <div className="flex justify-between items-center mb-5 relative z-10">
        <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-white/5 border border-white/5">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary-neon)]" />
          <span className="text-xs font-black text-[var(--primary-neon)] tracking-widest uppercase">{translateLeague(match.league)}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs font-bold text-white/75">{formatMatchTime(match.time)}</span>
          {isLocked && <Lock size={14} className="text-yellow-500" />}
        </div>
      </div>

      <div className="flex justify-between items-center mb-8 relative z-10 px-2">
        <div className="flex flex-col items-center gap-3 w-2/5 text-center">
          <img src={match.homeTeam.icon || "/logo_meow.jpg"} alt="H" className="w-12 h-12 rounded-full border border-white/10" />
          <span className="font-bold text-sm text-white leading-tight min-h-[3em] flex items-center justify-center">{match.homeTeam.name}</span>
        </div>
        <div className="text-white/75 font-bold text-sm w-1/5 text-center">VS</div>
        <div className="flex flex-col items-center gap-3 w-2/5 text-center">
          <img src={match.awayTeam.icon || "/logo_meow.jpg"} alt="A" className="w-12 h-12 rounded-full border border-white/10" />
          <span className="font-bold text-sm text-white leading-tight min-h-[3em] flex items-center justify-center">{match.awayTeam.name}</span>
        </div>
      </div>

      {showProbs ? (
        <div className="grid grid-cols-3 gap-6 relative z-10">
          <div className="flex flex-col items-center gap-2">
            <span className="text-xs font-black text-white/50 tracking-widest uppercase">主胜</span>
            <span className="text-2xl font-black text-[var(--primary-neon)]">{hProb}%</span>
            <ProbabilityBar value={hProb} colorClass="bg-primary-neon" />
          </div>
          <div className="flex flex-col items-center gap-2">
            <span className="text-xs font-black text-white/50 tracking-widest uppercase">平局</span>
            <span className="text-2xl font-black text-white/80">{drawProb}%</span>
            <ProbabilityBar value={drawProb} colorClass="bg-white/30" lightColorClass="bg-black/40" />
          </div>
          <div className="flex flex-col items-center gap-2">
            <span className="text-xs font-black text-white/50 tracking-widest uppercase">客胜</span>
            <span className="text-2xl font-black text-secondary-magenta">{aProb}%</span>
            <ProbabilityBar value={aProb} colorClass="bg-secondary-magenta" />
          </div>
        </div>
      ) : (
        <div className="relative z-10 grid grid-cols-3 gap-6">
          {['主胜', '平局', '客胜'].map(label => (
            <div key={label} className="flex flex-col items-center gap-2">
              <span className="text-xs font-black text-white/50 tracking-widest uppercase">{label}</span>
              <div className="flex items-center justify-center w-full h-8">
                <Lock size={16} className="text-white/30" />
              </div>
              <div className="h-1.5 w-full bg-white/5 rounded-full" />
            </div>
          ))}
          <div className="col-span-3 mt-1">
            <span className="block w-full text-center py-2.5 rounded-full bg-[var(--primary-neon)]/10 border border-[var(--primary-neon)]/30 text-[var(--primary-neon)] text-xs font-black tracking-widest">
              加微信开通查看概率
            </span>
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
  const pathname = usePathname();
  const { data: session, status } = useSession();
  const isLoggedIn = !!session?.user;
  const apiToken = (session?.user as any)?.apiToken as string | undefined;

  // 用户区块所需变量（复用 Navbar 逻辑）
  const avatarUrl = (session?.user as any)?.avatarUrl as string | undefined;
  const isVip = (session?.user as any)?.role === 'vip';
  const avatarSrc = avatarUrl || null;

  const [activeTab, setActiveTab] = useState<'matches' | 'archive' | 'profile'>('matches');
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
  const [contactOpen, setContactOpen] = useState(false);
  const [visibleCount, setVisibleCount] = useState(MATCH_PAGE_SIZE);
  const loadMoreRef = React.useRef<HTMLDivElement | null>(null);

  const handleCardClick = (id: string) => {
    const match = matches.find(m => m.id === id);
    if (isLoggedIn || match?.display_category === 'ARCHIVE') {
      window.location.href = '/report/' + id;
    } else {
      setContactOpen(true);
    }
  };

  useEffect(() => {
    if (status === 'loading') return; // 等 session 落定再请求
    const fetchData = async () => {
      try {
        setLoading(true);
        const data = await apiClient.get<Match[]>('/reports/latest', { token: apiToken });
        const translated = (data || []).map(m => ({
          ...m,
          homeTeam: { ...m.homeTeam, name: translateTeam(m.homeTeam.name) },
          awayTeam: { ...m.awayTeam, name: translateTeam(m.awayTeam.name) },
        }));
        setMatches(translated);
      } catch (e) {
        console.error('API Error:', e);
        setError('服务连接超时，请检查网络。');
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [apiToken, status]);

  const availableLeagues = useMemo(() => {
    // 用中文显示名 dedupe（J. League East/West → "J联赛" 合并为一项）
    // GATED matches (未登录) 也纳入联赛列表，确保联赛筛选有数据
    const visibleLeagues = matches
      .filter(m => m.display_category === 'UPCOMING' || m.display_category === 'GATED')
      .map(m => translateLeague(m.league))
      .filter(Boolean);
    return Array.from(new Set(visibleLeagues)).sort();
  }, [matches]);

  const filteredMatches = useMemo(() => {
    const now = new Date();

    // m.time 存储为 UTC，格式可能是 "2026-05-06T10:00:00Z" 或 "2026-05-06 10:00:00"
    // 只在没有时区标记时才追加 'Z'
    const parseUTC = (t: string) => {
      if (!t) return new Date(0);
      let s = t.trim().replace(' ', 'T');
      if (!s.endsWith('Z') && !s.includes('+') && !s.match(/[+-]\d{2}:\d{2}$/)) s += 'Z';
      const d = new Date(s);
      return isNaN(d.getTime()) ? new Date(0) : d;
    };

    // 日期比较统一用 CST（UTC+8），避免深夜欧洲场次归错日期
    const toCSTDate = (d: Date) => {
      if (!d || isNaN(d.getTime())) return '';
      const cst = new Date(d.getTime() + 8 * 60 * 60 * 1000);
      return cst.toISOString().slice(0, 10); // YYYY-MM-DD in CST
    };
    const todayCST    = toCSTDate(now);
    const tomorrowCST = toCSTDate(new Date(now.getTime() + 24 * 60 * 60 * 1000));

    let list = matches.filter(m => {
      const matchSearch = searchQuery === '' ||
        m.homeTeam.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        m.awayTeam.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        m.league.toLowerCase().includes(searchQuery.toLowerCase()) ||
        translateLeague(m.league).includes(searchQuery);

      if (!matchSearch) return false;

      if (activeTab === 'matches') {
        if (m.display_category !== 'UPCOMING' && m.display_category !== 'GATED') return false;

        const matchTime = parseUTC(m.time);

        // GATED 基础过滤：只保留 24h 内以后的场次（排除历史残留）
        if (m.display_category === 'GATED') {
          const dayAgo = new Date(now.getTime() - 24 * 60 * 60 * 1000);
          if (matchTime <= dayAgo) return false;
        }

        // 联赛筛选 — UPCOMING 和 GATED 都生效（用中文名匹配，East/West 合并）
        if (leagueFilters.size > 0 && !leagueFilters.has(translateLeague(m.league))) return false;

        // 日期筛选 — UPCOMING 和 GATED 都生效，用 CST 比较
        if (dateFilter === 'all') return true;
        const matchDateCST = toCSTDate(matchTime);
        if (dateFilter === 'today')    return matchDateCST === todayCST;
        if (dateFilter === 'tomorrow') return matchDateCST === tomorrowCST;

      } else if (activeTab === 'archive') {
        if (m.display_category !== 'ARCHIVE') return false;
      }

      return true;
    });

    return list.sort((a, b) => parseUTC(a.time).getTime() - parseUTC(b.time).getTime());
  }, [matches, searchQuery, dateFilter, leagueFilters, activeTab]);

  // 已结束比赛：仅世界杯场次，按时间倒序
  const recentArchivedMatches = useMemo(() => {
    return matches
      .filter(m => m.display_category === 'ARCHIVE' && m.id.startsWith('wc_'))
      .sort((a, b) => b.time.localeCompare(a.time));
  }, [matches]);

  useEffect(() => {
    setVisibleCount(MATCH_PAGE_SIZE);
  }, [activeTab, dateFilter, leagueFilters, searchQuery]);

  const homeVisibleMatches = useMemo(() => {
    return filteredMatches.slice(0, visibleCount);
  }, [filteredMatches, visibleCount]);

  const homeVisibleArchivedMatches = useMemo(() => {
    const remaining = Math.max(0, visibleCount - filteredMatches.length);
    return recentArchivedMatches.slice(0, remaining);
  }, [filteredMatches.length, recentArchivedMatches, visibleCount]);

  const archiveVisibleMatches = useMemo(() => {
    return filteredMatches.slice(0, visibleCount);
  }, [filteredMatches, visibleCount]);

  const currentFeedTotal = activeTab === 'archive'
    ? filteredMatches.length
    : filteredMatches.length + recentArchivedMatches.length;
  const hasMoreMatches = visibleCount < currentFeedTotal;
  const loadMoreMatches = React.useCallback(() => {
    setVisibleCount(prev => Math.min(prev + MATCH_PAGE_SIZE, currentFeedTotal));
  }, [currentFeedTotal]);

  useEffect(() => {
    if (!hasMoreMatches || loading) return;
    const el = loadMoreRef.current;
    if (!el) return;

    const observer = new IntersectionObserver((entries) => {
      if (!entries[0]?.isIntersecting) return;
      loadMoreMatches();
    }, { rootMargin: '260px 0px' });

    observer.observe(el);
    return () => observer.disconnect();
  }, [hasMoreMatches, loadMoreMatches, loading, visibleCount]);

  useEffect(() => {
    if (!hasMoreMatches || loading) return;

    let ticking = false;
    const checkNearBottom = () => {
      ticking = false;
      const doc = document.documentElement;
      const scrollTop = window.scrollY || doc.scrollTop || document.body.scrollTop || 0;
      const viewportHeight = window.innerHeight || doc.clientHeight;
      const scrollHeight = Math.max(doc.scrollHeight, document.body.scrollHeight);
      if (scrollHeight - (scrollTop + viewportHeight) < 560) {
        loadMoreMatches();
      }
    };
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(checkNearBottom);
    };

    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('wheel', onScroll, { passive: true });
    window.addEventListener('touchmove', onScroll, { passive: true });
    checkNearBottom();

    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('wheel', onScroll);
      window.removeEventListener('touchmove', onScroll);
    };
  }, [hasMoreMatches, loadMoreMatches, loading, visibleCount]);

  const ELITE_MATCH = filteredMatches[0];
  const OTHER_MATCHES = filteredMatches.slice(1);

  return (
    <div suppressHydrationWarning className={`min-h-screen overflow-x-hidden font-sans ${isDark ? 'bg-[#09090b] pb-32' : 'pb-28'}`}>
      {/* Stitch Light Mode: sticky top app bar — mirrors dark mode header */}
      {!isDark && (
        <header suppressHydrationWarning className="fixed top-0 w-full z-50 bg-[var(--color-background)] border-b border-black/8 flex justify-between items-center px-5 py-3">
          <div className="flex items-center gap-3">
            <Image
              src="/logo_meow.jpg"
              alt="喵弟数据研究室 Logo"
              width={36}
              height={36}
              className="rounded-full object-contain flex-shrink-0"
              priority
            />
            <div className="flex flex-col leading-none">
              <h1 className="font-black text-base tracking-tight text-slate-900" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                喵弟数据研究室
              </h1>
              <p className="text-xs font-black text-slate-500 tracking-widest">miaomiaodi.cc</p>
            </div>
          </div>
          <ThemeToggleButton />
        </header>
      )}

      <div className={`max-w-md mx-auto relative z-10 px-4 ${!isDark ? 'pt-16' : ''}`}>
        {/* Header — dark mode keeps original; light mode moved to sticky bar above */}
        <header className={`pb-4 flex flex-col items-center ${isDark ? 'pt-8' : 'pt-4'}`}>
          {isDark && (
            <div className="flex items-center justify-between gap-4 mb-6 w-full">
              <div className="flex items-center gap-4">
                <div className="relative w-14 h-14 flex-shrink-0">
                  <Image
                    src="/logo_meow.jpg"
                    alt="喵弟数据研究室 Logo"
                    width={56}
                    height={56}
                    className="w-full h-full object-contain relative z-10 rounded-full"
                    priority
                  />
                </div>
                <div className="flex flex-col">
                  <h1 className="font-black text-2xl tracking-tight text-zinc-50" style={{ fontFamily: "'Plus Jakarta Sans', sans-serif" }}>
                    足球量化研报
                  </h1>
                  <p className="text-xs font-black text-zinc-400 w-full [text-align-last:justify]">miaomiaodi.cc</p>
                </div>
              </div>
              <ThemeToggleButton />
            </div>
          )}

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
                    <Search size={14} className={`absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none group-focus-within:text-[var(--primary-neon)] transition-colors ${isDark ? 'text-white/40' : 'text-black/40'}`} />
                    <input
                      suppressHydrationWarning
                      autoFocus
                      type="text"
                      placeholder="搜索俱乐部、联赛..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className={`w-full rounded-full py-2.5 pl-9 pr-4 text-sm font-medium focus:outline-none focus:border-[var(--primary-neon)]/40 transition-all ${isDark ? 'bg-white/5 border border-white/10 text-white placeholder-white/40' : 'bg-black/5 border border-black/15 text-black placeholder-black/40'}`}
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
                            suppressHydrationWarning
                            className="relative w-9 h-9 rounded-xl overflow-hidden flex-shrink-0"
                            style={{
                              border: isDark
                                ? isVip ? '2px solid rgba(191,165,93,0.6)' : '2px solid rgba(0,255,195,0.3)'
                                : isVip ? '2px solid rgba(146,71,0,0.4)' : '2px solid rgba(183,0,77,0.3)',
                            }}
                          >
                            {avatarSrc ? (
                              <Image src={avatarSrc} alt="avatar" fill className="object-cover" unoptimized />
                            ) : (
                              <span className="flex items-center justify-center w-full h-full text-base" style={{ background: isDark ? '#12161b' : '#f2f4f5' }}>🐱</span>
                            )}
                          </div>
                          <div className="flex flex-col gap-0.5">
                            <span suppressHydrationWarning className={`text-xs font-bold leading-tight ${isDark ? 'text-white' : 'text-[#191c1d]'}`}>{session?.user?.name || '用户'}</span>
                            {isVip && (
                              <span
                                suppressHydrationWarning
                                className="text-xs font-black px-1.5 py-0.5 rounded-full w-fit leading-tight"
                                style={isDark
                                  ? { background: 'rgba(191,165,93,0.15)', color: '#BFA55D', border: '1px solid rgba(191,165,93,0.3)' }
                                  : { background: '#ffdcc6', color: '#924700', border: 'none' }}
                              >
                                VIP
                              </span>
                            )}
                            {!isVip && (
                              <span suppressHydrationWarning className={`text-xs leading-tight ${isDark ? 'text-white/50' : 'text-[#5b3f43]'}`}>普通会员</span>
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
                        className={`inline-block px-8 py-2.5 font-bold rounded-full active:scale-95 transition-all duration-200 text-sm ${
                          isDark
                            ? 'bg-[var(--primary-neon)]/10 border border-[var(--primary-neon)]/50 text-white tracking-widest hover:bg-[var(--primary-neon)]/20 hover:border-[var(--primary-neon)]/70'
                            : 'bg-gradient-to-r from-[#b7004d] to-[#de2264] text-white shadow-[0px_4px_12px_rgba(183,0,77,0.3)] hover:opacity-90'
                        }`}
                      >
                        {isDark ? '登录' : '登录 →'}
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
                    ? 'bg-white/5 border border-white/10 hover:bg-white/10 hover:border-[var(--primary-neon)]/40'
                    : 'bg-[rgba(210,216,226,0.82)] border border-[rgba(140,150,175,0.25)] shadow-[0_2px_8px_rgba(0,0,0,0.06)] hover:bg-[rgba(200,207,218,0.92)] hover:border-[rgba(140,150,175,0.40)]'
                }`}
                aria-label={searchOpen ? '关闭搜索' : '搜索'}
              >
                <AnimatePresence mode="wait" initial={false}>
                  {searchOpen ? (
                    <motion.span key="x" initial={{ rotate: -90, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} exit={{ rotate: 90, opacity: 0 }} transition={{ duration: 0.12 }}>
                      <X size={14} suppressHydrationWarning className={isDark ? 'text-white/60' : 'text-[#191c1d]/60'} />
                    </motion.span>
                  ) : (
                    <motion.span key="mag" initial={{ rotate: 90, opacity: 0 }} animate={{ rotate: 0, opacity: 1 }} exit={{ rotate: -90, opacity: 0 }} transition={{ duration: 0.12 }}>
                      <Search size={15} suppressHydrationWarning className={isDark ? 'text-white/60' : 'text-[#191c1d]/60'} />
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
                className={`flex-1 py-2 rounded-full text-xs font-bold transition-all whitespace-nowrap ${
                  dateFilter === tab.id
                    ? isDark
                      ? 'bg-primary-neon border-0 text-white'
                      : 'bg-[#d4e3ff] text-[#003567] shadow-sm border-0'
                    : isDark
                      ? 'bg-[#27272a] border border-zinc-700 text-zinc-300'
                      : 'bg-white text-[#191c1d] shadow-sm border-0'
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
                className={`w-full flex items-center justify-center gap-1 py-2 rounded-full text-xs font-bold transition-all whitespace-nowrap ${
                  leagueFilters.size > 0
                    ? isDark
                      ? 'bg-primary-neon border-0 text-white'
                      : 'bg-[#d4e3ff] text-[#003567] shadow-sm border-0'
                    : isDark
                      ? 'bg-[#27272a] border border-zinc-700 text-zinc-300'
                      : 'bg-white text-[#191c1d] shadow-sm border-0'
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
                      suppressHydrationWarning
                      className={`rounded-2xl shadow-2xl overflow-hidden min-w-[140px] ${isDark ? 'bg-[#0a0d18] border border-white/10' : 'bg-white border border-[#e1e3e4]'}`}
                    >
                      {/* 联赛列表 */}
                      <div className="py-2 max-h-[260px] overflow-y-auto">
                        {availableLeagues.length === 0 ? (
                          <p suppressHydrationWarning className={`text-xs text-center py-4 px-4 ${isDark ? 'text-white/30' : 'text-[#5b3f43]'}`}>暂无联赛数据</p>
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
                                suppressHydrationWarning
                                className={`w-full flex items-center gap-3 px-4 py-2.5 text-xs font-bold transition-colors ${isDark ? 'hover:bg-white/5' : 'hover:bg-[#f2f4f5]'}`}
                              >
                                <span suppressHydrationWarning className={`w-4 h-4 rounded flex items-center justify-center border flex-shrink-0 transition-all ${checked ? isDark ? 'bg-primary-neon border-primary-neon' : 'bg-[#b7004d] border-[#b7004d]' : isDark ? 'border-white/20 bg-transparent' : 'border-[#8f6f73]/40 bg-transparent'}`}>
                                  {checked && (
                                    <svg width="9" height="7" viewBox="0 0 9 7" fill="none">
                                      <path d="M1 3.5L3.5 6L8 1" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                                    </svg>
                                  )}
                                </span>
                                <span suppressHydrationWarning className={checked ? isDark ? 'text-[var(--primary-neon)]' : 'text-[#b7004d]' : isDark ? 'text-white/75' : 'text-[#191c1d]'}>{league}</span>
                              </button>
                            );
                          })
                        )}
                      </div>

                      {/* 底部操作栏 */}
                      <div suppressHydrationWarning className={`flex items-center gap-2 px-3 py-2.5 border-t ${isDark ? 'border-white/5' : 'border-[#f2f4f5]'}`}>
                        <button
                          onClick={() => { setPendingLeagues(new Set()); }}
                          suppressHydrationWarning
                          className={`flex-1 py-1.5 text-xs font-bold transition-colors rounded-full border ${isDark ? 'text-white/40 hover:text-white/70 border-white/10 hover:border-white/20' : 'text-[#5b3f43] border-[#e1e3e4] hover:bg-[#f2f4f5]'}`}
                        >
                          清除
                        </button>
                        <button
                          onClick={() => {
                            setLeagueFilters(new Set(pendingLeagues));
                            setShowLeagueDropdown(false);
                          }}
                          suppressHydrationWarning
                          className={`flex-1 py-1.5 text-xs font-bold rounded-full transition-colors ${isDark ? 'bg-[var(--primary-neon)]/10 border border-[var(--primary-neon)]/40 text-[var(--primary-neon)] hover:bg-[var(--primary-neon)]/20' : 'bg-[#b7004d] text-white hover:opacity-90 border-0'}`}
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
                <div className="w-10 h-10 border-2 border-[var(--primary-neon)]/20 border-t-[var(--primary-neon)] rounded-full animate-spin" />
                <p className={`text-xs font-bold animate-pulse ${isDark ? 'text-white/50' : 'text-[#5b3f43]'}`}>加载中</p>
              </div>
            ) : error ? (
              <div className={`p-10 text-center rounded-3xl ${isDark ? 'glass-panel border-red-500/20' : 'bg-white shadow-sm'}`}>
                <Info className="w-10 h-10 text-red-500/40 mx-auto mb-4" />
                <p className="text-sm font-bold text-red-400 mb-6">暂时无法加载</p>
                <button onClick={() => window.location.reload()} className={`px-8 py-2 rounded-full text-xs font-bold border ${isDark ? 'bg-white/5 border-white/10' : 'bg-[#f2f4f5] border-[#e1e3e4]'}`}>点击重试</button>
              </div>
            ) : (
              <>
                {/* 即将开赛列表 */}
                {filteredMatches.length === 0 ? (
                  <div className="py-16 text-center opacity-30">
                    <Activity size={48} className="mx-auto mb-6 opacity-20" />
                    <p className="font-bold text-lg">暂无赛事数据</p>
                    <p className="text-xs mt-2 font-medium tracking-tighter">当前时段暂无符合量化标准的预测报告</p>
                  </div>
                ) : (
                  <>
                    {/* 游客引导横幅 */}
                    {!isLoggedIn && (
                      <div className="border border-[var(--primary-neon)]/30 rounded-xl mb-4 overflow-hidden">
                        <button
                          onClick={() => setContactOpen(true)}
                          className="w-full bg-[var(--primary-neon)]/10 p-3 text-xs font-medium text-zinc-800 dark:text-white text-left"
                        >
                          💬 加管理员微信开通账号，查看完整研报
                        </button>
                        <Link
                          href="/login"
                          className="flex items-center justify-center gap-1.5 w-full py-2.5 bg-white/5 dark:bg-white/5 border-t border-[var(--primary-neon)]/20 text-sm font-bold text-[var(--primary-neon)]"
                        >
                          已有账号？点此登录 →
                        </Link>
                      </div>
                    )}
                    <div className="flex flex-col gap-3">
                      {homeVisibleMatches.map(m => (
                        <CompactMatchCard key={m.id} match={m} isLoggedIn={isLoggedIn} isDark={isDark} onClick={() => handleCardClick(m.id)} />
                      ))}
                    </div>
                  </>
                )}

                {/* 已结束 — 所有用户可见，不受日期/联赛筛选影响 */}
                {homeVisibleArchivedMatches.length > 0 && (
                  <section className="mt-8 pb-4">
                    <div suppressHydrationWarning className={`flex items-center gap-2 mb-4 pb-2 border-b ${isDark ? 'border-white/5' : 'border-black/6'}`}>
                      <span suppressHydrationWarning className={`w-1.5 h-1.5 rounded-full ${isDark ? 'bg-white/25' : 'bg-[#8f6f73]'}`} />
                      <h2 suppressHydrationWarning className={`text-sm font-bold ${isDark ? 'tracking-widest uppercase text-white/50 font-display' : 'text-[#5b3f43]'}`}>已结束</h2>
                      <span suppressHydrationWarning className={`text-xs font-bold ml-auto ${isDark ? 'text-white/25' : 'text-[#8f6f73]/60'}`}>{recentArchivedMatches.length} 场</span>
                    </div>
                    <div className="flex flex-col gap-3">
                      {homeVisibleArchivedMatches.map(m => (
                        <CompactMatchCard key={m.id} match={m} isLoggedIn={isLoggedIn} isDark={isDark} onClick={() => handleCardClick(m.id)} />
                      ))}
                    </div>
                  </section>
                )}

                {hasMoreMatches && (
                  <div ref={loadMoreRef} className="py-8 flex flex-col items-center gap-2">
                    <button
                      type="button"
                      onClick={loadMoreMatches}
                      suppressHydrationWarning
                      className={`px-5 py-2.5 rounded-full text-sm font-bold border transition-all active:scale-95 ${
                        isDark
                          ? 'bg-white/5 border-white/10 text-white/75'
                          : 'bg-white border-[#e1e3e4] text-[#191c1d] shadow-sm'
                      }`}
                    >
                      加载更多比赛
                    </button>
                    <span suppressHydrationWarning className={`text-xs font-medium ${isDark ? 'text-white/30' : 'text-[#8f6f73]/70'}`}>
                      已显示 {Math.min(visibleCount, currentFeedTotal)} / {currentFeedTotal} 场
                    </span>
                  </div>
                )}
              </>
            )
          )}

          {activeTab === 'archive' && (
            <section className="animate-in fade-in duration-500 pb-12">
               <div className="flex items-center justify-between mb-6">
                 <div className="flex items-center gap-2">
                    <span suppressHydrationWarning className={`w-1.5 h-1.5 rounded-full ${isDark ? 'bg-gray-500' : 'bg-[#924700]'}`} />
                    <h2 suppressHydrationWarning className={`text-sm font-bold ${isDark ? 'tracking-widest uppercase text-white/80 font-display' : 'text-[#191c1d]'}`}>历史研报</h2>
                  </div>
                  <span suppressHydrationWarning className={`text-xs font-bold uppercase tracking-tighter ${isDark ? 'text-white/50' : 'text-[#5b3f43]'}`}>Total {filteredMatches.length}</span>
               </div>

               {filteredMatches.length === 0 ? (
                 <div className="py-24 text-center opacity-30">
                    <Archive size={48} className="mx-auto mb-6 opacity-20" />
                    <p suppressHydrationWarning className="font-bold text-lg">暂无归档记录</p>
                    <p className="text-xs mt-2 font-medium tracking-tighter">当前没有符合筛选条件的归档记录</p>
                 </div>
               ) : (
                 <div className="grid grid-cols-2 gap-4">
                   {archiveVisibleMatches.map(m => (
                     <CompactMatchCard key={m.id} match={m} isLoggedIn={isLoggedIn} isDark={isDark} onClick={() => handleCardClick(m.id)} />
                   ))}
                 </div>
               )}
               {hasMoreMatches && (
                 <div ref={loadMoreRef} className="py-8 flex flex-col items-center gap-2">
                   <button
                     type="button"
                     onClick={loadMoreMatches}
                     suppressHydrationWarning
                     className={`px-5 py-2.5 rounded-full text-sm font-bold border transition-all active:scale-95 ${
                       isDark
                         ? 'bg-white/5 border-white/10 text-white/75'
                         : 'bg-white border-[#e1e3e4] text-[#191c1d] shadow-sm'
                     }`}
                   >
                     加载更多比赛
                   </button>
                   <span suppressHydrationWarning className={`text-xs font-medium ${isDark ? 'text-white/30' : 'text-[#8f6f73]/70'}`}>
                     已显示 {Math.min(visibleCount, currentFeedTotal)} / {currentFeedTotal} 场
                   </span>
                 </div>
               )}
            </section>
          )}

          {activeTab === 'profile' && (
             <div className="py-24 text-center opacity-30">
               <User size={48} className="mx-auto mb-6 opacity-20" />
               <p className="font-bold text-lg">个人主页</p>
               <p className="text-xs mt-2 font-medium tracking-tighter">请先登录查看您的账户状态</p>
            </div>
          )}
        </main>
        <Footer />
      </div>

      {/* Nav */}
      {isDark ? (
        <div className="fixed bottom-0 left-0 right-0 max-w-md mx-auto px-6 pb-6 z-50 pointer-events-none">
          <nav className="bg-[#09090b] border border-zinc-800 rounded-full px-6 py-3 flex justify-between items-center shadow-[0_-4px_20px_rgba(0,0,0,0.5)] pointer-events-auto">
            <button onClick={() => setActiveTab('matches')} className="flex flex-col items-center gap-0.5 transition-all">
              {activeTab === 'matches' ? (
                <div className="flex flex-col items-center gap-0.5 bg-primary-neon text-white rounded-full px-4 py-1.5">
                  <Activity size={20} />
                  <span className="text-xs font-bold">赛事</span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-0.5 text-zinc-400 px-4 py-1.5">
                  <Activity size={20} />
                  <span className="text-xs font-bold">赛事</span>
                </div>
              )}
            </button>
            <Link href="/model" className="flex flex-col items-center gap-0.5 transition-all">
              <div className="flex flex-col items-center gap-0.5 text-zinc-400 px-4 py-1.5">
                <Cpu size={20} />
                <span className="text-xs font-bold">模型</span>
              </div>
            </Link>
            <button onClick={() => setActiveTab('archive')} className="flex flex-col items-center gap-0.5 transition-all">
              {activeTab === 'archive' ? (
                <div className="flex flex-col items-center gap-0.5 bg-primary-neon text-white rounded-full px-4 py-1.5">
                  <Archive size={20} />
                  <span className="text-xs font-bold">归档</span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-0.5 text-zinc-400 px-4 py-1.5">
                  <Archive size={20} />
                  <span className="text-xs font-bold">归档</span>
                </div>
              )}
            </button>
            <Link href="/center?tab=profile" className="flex flex-col items-center gap-0.5 transition-all">
              {pathname.startsWith('/center') ? (
                <div className="flex flex-col items-center gap-0.5 bg-primary-neon text-white rounded-full px-4 py-1.5">
                  <User size={20} />
                  <span className="text-xs font-bold">我的</span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-0.5 text-zinc-400 px-4 py-1.5">
                  <User size={20} />
                  <span className="text-xs font-bold">我的</span>
                </div>
              )}
            </Link>
          </nav>
        </div>
      ) : (
        /* Stitch Light Mode Bottom Nav — uses real routing；图标用 lucide SVG，不依赖 Google Fonts */
        <nav className="fixed bottom-0 left-0 right-0 z-50 bg-white/90 backdrop-blur-[20px] rounded-t-[1.5rem] shadow-[0px_-8px_24px_rgba(25,28,29,0.06)] flex justify-around items-center px-4 pb-6 pt-2">
          {[
            { href: '/',                    Icon: Activity, label: '赛事' },
            { href: '/model',               Icon: Cpu,      label: '模型' },
            { href: '/archive',             Icon: Archive,  label: '归档' },
            { href: '/center?tab=profile',  Icon: User,     label: '我的' },
          ].map(item => {
            const isActive = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href.split('?')[0]);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex flex-col items-center justify-center transition-all active:scale-95 duration-150 ${
                  isActive
                    ? 'bg-[#b7004d] text-white rounded-full px-5 py-1.5 shadow-md shadow-[#b7004d]/20'
                    : 'text-[#005faf] p-2'
                }`}
              >
                <item.Icon size={22} className="mb-0.5" />
                <span className="text-xs font-bold leading-none">{item.label}</span>
              </Link>
            );
          })}
        </nav>
      )}

      <ContactAdminModal open={contactOpen} onClose={() => setContactOpen(false)} />
    </div>
  );
}
