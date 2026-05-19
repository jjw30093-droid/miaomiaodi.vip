export function formatPct(x: number | null | undefined, digits = 1): string {
  if (x == null) return '—';
  return `${(x * 100).toFixed(digits)}%`;
}

export function formatMultiplier(startWan: number, endValue: number): string {
  return `${startWan}万 → ${(startWan * endValue).toFixed(1)}万`;
}

export function formatDateCN(iso: string): string {
  const parts = iso.split('-');
  if (parts.length < 3) return iso;
  return `${parseInt(parts[1])}月${parseInt(parts[2])}日`;
}

export function formatROI(x: number | null | undefined): string {
  if (x == null) return '—';
  const pct = (x * 100).toFixed(1);
  return x >= 0 ? `+${pct}%` : `${pct}%`;
}
