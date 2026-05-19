/**
 * markdownChunker.ts
 * ──────────────────
 * 将完整 Markdown 研报按特定 H2 标题切分为 public + vip 两段。
 * 取最先出现的 VIP 锚点标题作为分割点。
 */

/** 默认：从这些 H2 往后属于 VIP 内容 */
export const DEFAULT_VIP_SPLIT_HEADINGS = [
  '## 💰 市场交易价值',
  '## ⚔️ 战术及战力损耗',
  '## 🎯 决策端最终结论',
];

export interface ChunkResult {
  publicMd: string;
  vipMd: string;
  hasVip: boolean;
}

/**
 * @param md       完整研报 Markdown 字符串
 * @param splitAt  触发 VIP 切割的 H2 标题数组（取最先出现的那个）
 */
export function chunkMarkdown(
  md: string,
  splitAt: string[] = DEFAULT_VIP_SPLIT_HEADINGS,
): ChunkResult {
  if (!md) return { publicMd: '', vipMd: '', hasVip: false };

  let splitIndex = -1;

  for (const heading of splitAt) {
    const idx = md.indexOf(heading);
    if (idx !== -1 && (splitIndex === -1 || idx < splitIndex)) {
      splitIndex = idx;
    }
  }

  if (splitIndex === -1) {
    return { publicMd: md, vipMd: '', hasVip: false };
  }

  return {
    publicMd: md.slice(0, splitIndex).trimEnd(),
    vipMd:    md.slice(splitIndex),
    hasVip:   true,
  };
}
