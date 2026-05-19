/**
 * lib/formatTime.ts
 * ─────────────────────────────────────────────────────────────────
 * 将后端返回的 UTC ISO 8601 时间字符串（"2026-04-12T10:30:00Z"）
 * 转换为用户浏览器所在本地时区的可读格式，并附加"(本地时间)"标注。
 *
 * 兼容格式：
 *   - "2026-04-12T10:30:00Z"  ← 标准格式（新后端）
 *   - "2026-04-12 10:30"      ← 旧格式兜底（无 T、无 Z）
 */

export function formatMatchTime(utcStr: string | null | undefined): string {
  if (!utcStr) return 'TBD';

  // 规范化：确保 JS Date 能正确按 UTC 解析
  let normalized = utcStr.trim();
  if (!normalized.includes('T')) {
    // "2026-04-12 10:30:00" → "2026-04-12T10:30:00Z"
    normalized = normalized.replace(' ', 'T');
    if (!normalized.endsWith('Z') && !normalized.includes('+')) {
      normalized += 'Z';
    }
  } else if (!normalized.endsWith('Z') && !normalized.includes('+')) {
    normalized += 'Z';
  }

  const d = new Date(normalized);
  if (isNaN(d.getTime())) return utcStr; // 无法解析则原样返回

  const now = new Date();

  // 比较本地日历日期（用本地年月日，不是 UTC 日期）
  const localDay = (date: Date) =>
    `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;

  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);

  // 本地时间 HH:MM
  const timeStr = d.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });

  if (localDay(d) === localDay(now)) {
    return `今日 ${timeStr} (本地时间)`;
  }
  if (localDay(d) === localDay(tomorrow)) {
    return `明日 ${timeStr} (本地时间)`;
  }

  // 其他日期：MM-DD HH:MM (本地时间)
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day   = String(d.getDate()).padStart(2, '0');
  return `${month}-${day} ${timeStr} (本地时间)`;
}
