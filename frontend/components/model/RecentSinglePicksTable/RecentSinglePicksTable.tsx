'use client';
import React, { useState } from 'react';
import type { RecentPick } from '@/lib/modelHealth/types';
import { formatROI } from '@/lib/modelHealth/formatters';
import { useTheme } from '@/components/ThemeProvider';

interface Props {
  picks: RecentPick[];
}

type OutcomeKey = RecentPick['outcome'];

interface OutcomeStyle {
  label: string;
  icon: string;
  color: string;
  badgeBg: string;
  badgeText: string;
  rowTint: string;
  stripe: string;
  textColor: string;       // 主文字（队名）颜色
  matchOpacity: number;    // 整张卡片不透明度（未中淡化）
}

const MARKET_LABEL: Record<string, string> = {
  wdl: 'WDL',
  ou:  'O/U',
  ah:  'AH',
};

function buildOutcomeMeta(isDark: boolean): Record<OutcomeKey, OutcomeStyle> {
  return {
    hit: {
      label: '命中',
      icon: '✓',
      // 命中：强对比，亮绿色 chip + 绿色左条 + 绿色主字
      color:     isDark ? '#34D399' : '#059669',
      badgeBg:   isDark ? '#10B981' : '#10B981',
      badgeText: '#FFFFFF',
      rowTint:   isDark ? 'rgba(16, 185, 129, 0.10)' : '#ECFDF5',
      stripe:    isDark ? '#10B981' : '#10B981',
      textColor: isDark ? '#F1F5F9' : '#0F172A',
      matchOpacity: 1,
    },
    miss: {
      // 未中：淡化处理，去除浓烈的红色 tint，只保留极淡的中性灰底，不抢戏
      label: '未中',
      icon: '✗',
      color:     isDark ? '#94A3B8' : '#94A3B8',     // 灰红色，不刺眼
      badgeBg:   isDark ? '#334155' : '#F1F5F9',     // 灰底
      badgeText: isDark ? '#94A3B8' : '#64748B',
      rowTint:   isDark ? '#0F172A' : '#FFFFFF',     // 同主背景，不染色
      stripe:    isDark ? '#475569' : '#CBD5E1',     // 灰色左条
      textColor: isDark ? '#94A3B8' : '#94A3B8',     // 主字也灰化
      matchOpacity: 0.65,                             // 整体降亮度
    },
    pending: {
      label: '待结',
      icon: '⋯',
      color:     isDark ? '#CBD5E1' : '#475569',
      badgeBg:   isDark ? '#1E293B' : '#F1F5F9',
      badgeText: isDark ? '#CBD5E1' : '#64748B',
      rowTint:   isDark ? '#0F172A' : '#FFFFFF',
      stripe:    isDark ? '#475569' : '#94A3B8',
      textColor: isDark ? '#F1F5F9' : '#0F172A',
      matchOpacity: 1,
    },
  };
}

function PickCard({ pick, meta, palette }: {
  pick: RecentPick;
  meta: OutcomeStyle;
  palette: ReturnType<typeof buildPalette>;
}) {
  const market = MARKET_LABEL[pick.market] ?? pick.market?.toUpperCase() ?? '—';
  const direction = pick.pick ?? '—';
  const isHit = pick.outcome === 'hit';

  const pnlColor =
    pick.pnl == null
      ? palette.label
      : pick.pnl > 0
      ? palette.success
      : palette.label;     // 亏损也用灰色淡化，不再刺眼红

  return (
    <div
      className="rounded-xl border p-3 flex flex-col gap-2"
      style={{
        background: meta.rowTint,
        borderColor: palette.cardBorder,
        borderLeftWidth: 4,
        borderLeftColor: meta.stripe,
        opacity: meta.matchOpacity,
      }}
    >
      <div className="flex items-center justify-between">
        <span
          className="font-semibold font-mono tabular-nums"
          style={{ fontSize: 12, color: palette.label }}
        >
          {pick.date}
        </span>
        <span
          className="inline-flex items-center gap-1 font-black uppercase tracking-wider px-2 py-0.5 rounded-full"
          style={{ fontSize: 12, color: meta.badgeText, background: meta.badgeBg }}
        >
          <span aria-hidden className="text-sm font-black leading-none">{meta.icon}</span>
          {meta.label}
        </span>
      </div>

      <p
        className="font-bold leading-snug"
        style={{ fontSize: 14, color: meta.textColor }}
      >
        {pick.home} <span style={{ color: palette.label }}>vs</span> {pick.away}
      </p>

      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-semibold" style={{ fontSize: 12, color: palette.label }}>
          {market}
        </span>
        <span
          className="font-black"
          style={{ fontSize: 13, color: isHit ? palette.success : palette.textSoft }}
        >
          {direction}
        </span>
        {pick.odds != null && (
          <span
            className="font-semibold font-mono tabular-nums"
            style={{ fontSize: 12, color: palette.label }}
          >
            @ {pick.odds.toFixed(2)}
          </span>
        )}
        <span
          className="ml-auto font-black italic font-mono tabular-nums"
          style={{ fontSize: 14, color: pnlColor }}
        >
          {pick.pnl != null ? formatROI(pick.pnl) : '—'}
        </span>
      </div>
    </div>
  );
}

function PickRow({ pick, meta, palette }: {
  pick: RecentPick;
  meta: OutcomeStyle;
  palette: ReturnType<typeof buildPalette>;
}) {
  const market = MARKET_LABEL[pick.market] ?? pick.market?.toUpperCase() ?? '—';
  const isHit = pick.outcome === 'hit';
  const pnlColor =
    pick.pnl == null
      ? palette.label
      : pick.pnl > 0
      ? palette.success
      : palette.label;

  return (
    <tr
      className="border-b"
      style={{
        borderColor: palette.cardBorder,
        background: meta.rowTint,
        opacity: meta.matchOpacity,
      }}
    >
      <td
        className="py-3 pl-3 font-semibold font-mono tabular-nums"
        style={{
          fontSize: 12,
          color: palette.label,
          boxShadow: `inset 4px 0 0 ${meta.stripe}`,
        }}
      >
        {pick.date?.slice(5)}
      </td>
      <td
        className="py-3 font-semibold max-w-[140px] truncate"
        style={{ fontSize: 13, color: meta.textColor }}
      >
        {pick.home} <span style={{ color: palette.label }}>v</span> {pick.away}
      </td>
      <td className="py-3 text-center font-semibold font-mono" style={{ fontSize: 12 }}>
        <span style={{ color: palette.label }}>{market} </span>
        <span className="font-black" style={{ color: isHit ? palette.success : palette.textSoft }}>
          {pick.pick ?? '—'}
        </span>
      </td>
      <td
        className="py-3 text-right font-semibold font-mono tabular-nums"
        style={{ fontSize: 12, color: palette.label }}
      >
        {pick.odds != null ? pick.odds.toFixed(2) : '—'}
      </td>
      <td className="py-3 text-right">
        <span
          className="inline-flex items-center gap-1 font-black uppercase tracking-wider px-2 py-0.5 rounded-full"
          style={{ fontSize: 12, color: meta.badgeText, background: meta.badgeBg }}
        >
          <span aria-hidden className="text-sm font-black leading-none">{meta.icon}</span>
          {meta.label}
        </span>
      </td>
      <td
        className="py-3 pr-3 text-right font-black italic font-mono tabular-nums"
        style={{ fontSize: 13, color: pnlColor }}
      >
        {pick.pnl != null ? formatROI(pick.pnl) : '—'}
      </td>
    </tr>
  );
}

function buildPalette(isDark: boolean) {
  return {
    cardBg:     isDark ? '#0F172A' : '#FFFFFF',
    cardBorder: isDark ? '#334155' : '#E2E8F0',
    text:       isDark ? '#F1F5F9' : '#0F172A',
    textSoft:   isDark ? '#CBD5E1' : '#475569',
    label:      isDark ? '#94A3B8' : '#64748B',
    success:    isDark ? '#34D399' : '#059669',
    mutedBg:    isDark ? '#1E293B' : '#F8FAFC',
  };
}

export default function RecentSinglePicksTable({ picks }: Props) {
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const palette = buildPalette(isDark);
  const outcomeMeta = buildOutcomeMeta(isDark);

  const [expanded, setExpanded] = useState(false);
  const shown = expanded ? picks.slice(0, 30) : picks.slice(0, 5);

  // 统计：把"赚多少"前置展示
  const settled = picks.filter(p => p.outcome !== 'pending');
  const hitCount = settled.filter(p => p.outcome === 'hit').length;
  const missCount = settled.filter(p => p.outcome === 'miss').length;

  const cardStyle: React.CSSProperties = {
    background: palette.cardBg,
    borderColor: palette.cardBorder,
  };

  if (!picks.length) {
    return (
      <div
        className="rounded-2xl border p-6 text-center font-semibold"
        style={{ ...cardStyle, fontSize: 14, color: palette.label }}
      >
        暂无近期预测记录
      </div>
    );
  }

  return (
    <div className="rounded-2xl border p-5 flex flex-col gap-3" style={cardStyle}>
      <div className="flex items-center justify-between">
        <p
          className="font-bold uppercase tracking-wider"
          style={{ fontSize: 12, color: palette.label }}
        >
          近期预测
        </p>
        {settled.length > 0 && (
          <span className="font-semibold tabular-nums" style={{ fontSize: 12, color: palette.label }}>
            <span style={{ color: palette.success, fontWeight: 900 }}>{hitCount} 中</span>
            <span style={{ margin: '0 4px' }}>/</span>
            <span>{missCount} 未中</span>
          </span>
        )}
      </div>

      {/* Mobile card view */}
      <div className="flex flex-col gap-2 sm:hidden">
        {shown.map(p => (
          <PickCard
            key={`${p.match_id}-${p.date}`}
            pick={p}
            meta={outcomeMeta[p.outcome] ?? outcomeMeta.pending}
            palette={palette}
          />
        ))}
      </div>

      {/* Desktop table */}
      <div className="hidden sm:block overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b" style={{ borderColor: palette.cardBorder }}>
              {['日期', '对阵', '方向', '市场价格', '结果', 'PnL'].map(h => (
                <th
                  key={h}
                  className="pb-3 font-bold uppercase tracking-wider"
                  style={{ fontSize: 12, color: palette.label }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map(p => (
              <PickRow
                key={`${p.match_id}-${p.date}`}
                pick={p}
                meta={outcomeMeta[p.outcome] ?? outcomeMeta.pending}
                palette={palette}
              />
            ))}
          </tbody>
        </table>
      </div>

      {picks.length > 5 && (
        <button
          onClick={() => setExpanded(e => !e)}
          className="w-full py-2 rounded-full font-bold min-h-[44px] border"
          style={{
            fontSize: 13,
            color: palette.textSoft,
            borderColor: palette.cardBorder,
            background: palette.mutedBg,
          }}
        >
          {expanded ? '收起' : `查看更多（共 ${Math.min(picks.length, 30)} 场）`}
        </button>
      )}
    </div>
  );
}
