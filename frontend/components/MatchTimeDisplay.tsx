'use client';

/**
 * MatchTimeDisplay — 客户端组件
 * 在 Server Component 内安全地渲染本地时间（浏览器负责时区转换）。
 * 用法：<MatchTimeDisplay utcStr={report.matchTime} />
 */
import { formatMatchTime } from '@/lib/formatTime';

interface Props {
  utcStr?: string | null;
  className?: string;
}

export function MatchTimeDisplay({ utcStr, className }: Props) {
  return <span className={className}>{formatMatchTime(utcStr)}</span>;
}
