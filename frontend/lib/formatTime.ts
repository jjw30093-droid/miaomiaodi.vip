/**
 * lib/formatTime.ts
 * 将后端返回的 UTC 时间字符串转为北京时间（Asia/Shanghai，UTC+8）。
 */

const TZ = 'Asia/Shanghai';

export function formatMatchTime(utcStr: string | null | undefined): string {
  if (!utcStr) return 'TBD';

  let normalized = utcStr.trim();
  if (!normalized.includes('T')) {
    normalized = normalized.replace(' ', 'T');
    if (!normalized.endsWith('Z') && !normalized.includes('+')) normalized += 'Z';
  } else if (!normalized.endsWith('Z') && !normalized.includes('+')) {
    normalized += 'Z';
  }

  const d = new Date(normalized);
  if (isNaN(d.getTime())) return utcStr;

  // 北京时间日历日期
  const bjDay = (date: Date) => {
    const parts = new Intl.DateTimeFormat('zh-CN', {
      timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(date);
    const y = parts.find(p => p.type === 'year')?.value;
    const m = parts.find(p => p.type === 'month')?.value;
    const dd = parts.find(p => p.type === 'day')?.value;
    return `${y}-${m}-${dd}`;
  };

  const timeStr = d.toLocaleTimeString('zh-CN', {
    timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false,
  });

  const now = new Date();
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);

  const todayKey = bjDay(now);
  const tmrKey   = bjDay(tomorrow);
  const matchKey = bjDay(d);

  const month = matchKey.split('-')[1];
  const day   = matchKey.split('-')[2];

  if (matchKey === todayKey)  return `今日 ${timeStr} 北京时间`;
  if (matchKey === tmrKey)    return `明日 ${timeStr} 北京时间`;
  return `${month}-${day} ${timeStr} 北京时间`;
}
