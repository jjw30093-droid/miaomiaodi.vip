'use client';

import { useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import {
  ChevronLeft,
  Search,
  Rocket,
  BarChart3,
  Crown,
  Shield,
  HelpCircle,
  Mail,
  ChevronDown,
  TrendingUp,
} from 'lucide-react';
import Image from 'next/image';
import { useTheme } from '@/components/ThemeProvider';
import ThemeToggleButton from '@/components/ThemeToggleButton';

// ────────────────────────────────────────────────────────────
//  数据：FAQ 内容（实际产品文案，与本系统功能严格对应）
// ────────────────────────────────────────────────────────────

interface FAQItem {
  q: string;
  a: string;            // 段落支持 \n 换行
  highlight?: string;   // 关键短语（用品牌色高亮）
}

interface FAQSection {
  id: string;
  title: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  accent: string;       // 浅色主色（icon + 标题）
  accentDark: string;   // 深色主色
  items: FAQItem[];
}

const FAQ_SECTIONS: FAQSection[] = [
  {
    id: 'start',
    title: '快速入门',
    icon: Rocket,
    accent: '#0F766E',
    accentDark: '#10B981',
    items: [
      {
        q: '喵弟数据研究室是做什么的？',
        a: '我们用机器学习模型对每天的足球比赛做出概率预测，输出置信度最高的预测方向。所有结果都会在赛后核对，按"近 7 / 14 / 30 天"的滚动窗口公开命中率与 Brier Score，精度透明可追溯。',
        highlight: '业绩透明可追溯',
      },
      {
        q: '我打开 App，第一眼应该看哪个数字？',
        a: '看「模型精度 · 近 30 天」卡片里的命中率和 Brier Score。命中率告诉你模型预测方向的准确比例；Brier Score 是概率校准指标，越低说明模型概率输出与真实结果越吻合。',
        highlight: '命中率 / Brier Score',
      },
      {
        q: '如何阅读分析报告？',
        a: '研报分为两个层次：① 新手视图 — 一张卡片展示模型预测方向、置信度星级、近期命中率，适合快速了解概况；② 专业视图 — 完整的战术分析、SHAP 归因图、射门期望值、阵容对比，适合深度研读。数据仅供学术参考，不构成任何投注建议。',
      },
    ],
  },
  {
    id: 'reports',
    title: '研报解读',
    icon: BarChart3,
    accent: '#0047B3',
    accentDark: '#60A5FA',
    items: [
      {
        q: '命中率和 Brier Score 哪个更重要？',
        a: '两个指标各有侧重。\n• 命中率 ≥ 50% 说明模型预测方向正确率超过随机水平，是最直观的精度指标。\n• Brier Score 衡量概率本身的准确性（值越低越好，理想值 < 0.20）— 比命中率更全面，能反映模型对"高置信度"场次的概率校准质量。\n两者同时优秀才代表模型在统计上可靠。',
        highlight: 'Brier Score',
      },
      {
        q: '净值曲线 ×1.138 是什么意思？',
        a: '把 1 元等比例放大成 1.138 元，相当于本金涨了 13.8%。曲线起点永远是 ×1.00，末端高于 1.00 = 赚钱，低于 1.00 = 亏损。"本金 ×1.00" 那条虚线就是盈亏分界。',
      },
      {
        q: '模型预测的"主胜 55%"靠谱吗？',
        a: '我们每天会做"概率校准"测试：把所有"模型说 55%"的比赛拿出来，看实际命中率是不是接近 55%。误差 < 10% 我们才承认这个预测可信。\n注：体育赛事单场结果有强随机性，55% 不等于"一定胜"，只是"重复同一类比赛 100 次，约 55 次主胜"的统计意义。',
        highlight: '概率校准',
      },
      {
        q: 'WDL / O/U / AH 是什么意思？',
        a: '• WDL（胜平负）— 主胜 / 平局 / 客胜三选一，模型输出三方概率分布\n• Goals（进球数）— 全场总进球数预测，对应 Over/Under 市场\n• Spread（比分差）— 基于 Dixon-Coles 模型的比分差预测，对应 AH 市场\n三套模型各自独立预测，系统从中选取校准后置信度最优的方向输出。',
      },
      {
        q: '为什么有的研报没有预测方向？',
        a: '当模型在三个市场都找不到「市场隐含概率 < 模型预测概率」的置信空间，或近期 Brier Score 超出阈值导致校准失准时，系统会自动跳过该场次。"不输出"比"强行输出低置信度预测"更符合精度标准。',
      },
    ],
  },
  {
    id: 'vip',
    title: '会员与付费',
    icon: Crown,
    accent: '#B45309',
    accentDark: '#FBBF24',
    items: [
      {
        q: 'VIP 会员能看到什么？',
        a: '• 完整研报 Markdown（包含 LLM 战术分析、关键变量、风险提示）\n• 球员级攻防贡献评分（22 名首发逐人评分）\n• 历史预测复盘与精度明细\n• 阵容确认实时推送\n非 VIP 也能看到「模型预测方向 + 命中率 + Brier Score」核心三件套，付费部分主要是辅助分析的细节数据。',
        highlight: '完整研报 / 球员评分 / 实时推送',
      },
      {
        q: '怎么开通 VIP？',
        a: '当前仅支持兑换码（CDK）开通。在「我的 → 兑换码」输入卡密即可激活。后续将支持微信支付直购，敬请期待。',
      },
      {
        q: '兑换码在哪里购买？',
        a: '关注公众号【足球喵喵弟】，回复「VIP」可获取最新购买链接和限时活动信息。',
        highlight: '足球喵喵弟',
      },
    ],
  },
  {
    id: 'account',
    title: '账号与登录',
    icon: Shield,
    accent: '#5B21B6',
    accentDark: '#A78BFA',
    items: [
      {
        q: '为什么要用微信扫码登录？',
        a: '微信扫码免去了密码记忆和短信验证，在公众号里完成确认即可秒登。我们不存储你的微信密码，仅获取 OpenID 用于身份识别。',
      },
      {
        q: '修改昵称、头像在哪里？',
        a: '「我的 → 账号资料」可直接修改昵称（最多 20 字符），点击头像可上传图片（≤ 2MB，支持 JPG/PNG）。改完后刷新即可生效。',
      },
      {
        q: '能在多设备同时登录吗？',
        a: '可以。同一账号在 App、小程序、网页上可同时保持登录态，每次登录会在「设备与安全」里显示最新的登录设备和时间。如发现陌生设备，请立即在该页面退出并联系客服。',
      },
    ],
  },
  {
    id: 'misc',
    title: '其他常见问题',
    icon: HelpCircle,
    accent: '#475569',
    accentDark: '#94A3B8',
    items: [
      {
        q: '研报是几点更新的？',
        a: '一般每天凌晨 3:00（UTC+8）批量生成第二天的全部场次。开赛前 30 分钟会做"首发确认"二次更新；赛后 30 分钟内出复盘。',
      },
      {
        q: '历史研报怎么看？',
        a: '「我的 → 归档」按日期倒序展示已结算的所有研报，可点击进入查看模型预测 vs 赛果对比、复盘射门图等。',
      },
      {
        q: '联赛覆盖范围？',
        a: '英超、西甲、意甲、德甲、法甲、欧冠、欧联、世预赛 + 主要杯赛，少量 J 联赛、澳超等亚太赛事。模型样本量不足的偏门联赛暂不出研报。',
      },
      {
        q: '反馈 / 投诉 / 建议？',
        a: '邮件 support@miaomiaodi.cc，或公众号【足球喵喵弟】留言。我们承诺工作日 24 小时内回复。',
      },
    ],
  },
];

// ────────────────────────────────────────────────────────────
//  Components
// ────────────────────────────────────────────────────────────

function FAQRow({
  item,
  isDark,
  accent,
  isOpen,
  onToggle,
  isLast,
}: {
  item: FAQItem;
  isDark: boolean;
  accent: string;
  isOpen: boolean;
  onToggle: () => void;
  isLast: boolean;
}) {
  // 把 highlight 关键词上色
  const renderAnswer = () => {
    if (!item.highlight) return item.a;
    const parts = item.a.split(item.highlight);
    return parts.map((p, i) => (
      <span key={i}>
        {p}
        {i < parts.length - 1 && (
          <span style={{ color: accent, fontWeight: 800 }}>{item.highlight}</span>
        )}
      </span>
    ));
  };

  return (
    <div
      className={isLast ? '' : 'border-b'}
      style={{ borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(25,28,29,0.08)' }}
    >
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between py-4 text-left active:opacity-70 transition-opacity"
      >
        <span
          className="flex-1 font-bold pr-3"
          style={{ fontSize: 14, color: isDark ? '#FFFFFF' : '#0F172A', lineHeight: 1.5 }}
        >
          {item.q}
        </span>
        <ChevronDown
          size={18}
          style={{
            color: isOpen ? accent : isDark ? 'rgba(255,255,255,0.4)' : '#94A3B8',
            transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s ease',
            flexShrink: 0,
          }}
        />
      </button>
      <div
        style={{
          maxHeight: isOpen ? 600 : 0,
          overflow: 'hidden',
          transition: 'max-height 0.3s ease',
        }}
      >
        <p
          className="pb-4 whitespace-pre-line font-medium"
          style={{
            fontSize: 13,
            lineHeight: 1.7,
            color: isDark ? 'rgba(255,255,255,0.8)' : '#334155',
          }}
        >
          {renderAnswer()}
        </p>
      </div>
    </div>
  );
}

function FAQSectionCard({
  section,
  isDark,
  openKeys,
  onToggle,
  query,
}: {
  section: FAQSection;
  isDark: boolean;
  openKeys: Set<string>;
  onToggle: (key: string) => void;
  query: string;
}) {
  const accent = isDark ? section.accentDark : section.accent;
  const Icon = section.icon;

  // 搜索过滤
  const filtered = useMemo(() => {
    if (!query.trim()) return section.items;
    const q = query.toLowerCase();
    return section.items.filter(
      it => it.q.toLowerCase().includes(q) || it.a.toLowerCase().includes(q),
    );
  }, [section.items, query]);

  if (filtered.length === 0) return null;

  return (
    <div
      className="rounded-3xl overflow-hidden"
      style={
        isDark
          ? { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', backdropFilter: 'blur(24px)' }
          : { background: '#fff', boxShadow: '0 1px 4px rgba(25,28,29,0.08)' }
      }
    >
      <div
        className="px-5 py-4 flex items-center gap-3 border-b"
        style={{ borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(25,28,29,0.08)' }}
      >
        <span
          className="flex items-center justify-center w-8 h-8 rounded-full"
          style={{ background: `${accent}1F` /* 12% alpha */, color: accent }}
        >
          <Icon size={16} />
        </span>
        <h2
          className="font-black italic tracking-tight"
          style={{
            fontSize: 16,
            color: isDark ? '#fff' : '#191c1d',
            fontFamily: "'Plus Jakarta Sans', sans-serif",
          }}
        >
          {section.title}
        </h2>
        <span
          className="ml-auto font-bold"
          style={{
            fontSize: 12,
            color: isDark ? 'rgba(255,255,255,0.35)' : '#94A3B8',
          }}
        >
          {filtered.length} 项
        </span>
      </div>
      <div className="px-5">
        {filtered.map((item, idx) => {
          const key = `${section.id}-${idx}`;
          return (
            <FAQRow
              key={key}
              item={item}
              isDark={isDark}
              accent={accent}
              isOpen={openKeys.has(key)}
              onToggle={() => onToggle(key)}
              isLast={idx === filtered.length - 1}
            />
          );
        })}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────
//  Main page
// ────────────────────────────────────────────────────────────

export default function HelpCenterPage() {
  const router = useRouter();
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const [query, setQuery] = useState('');
  const [openKeys, setOpenKeys] = useState<Set<string>>(new Set());

  const toggleKey = (key: string) => {
    setOpenKeys(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // 搜索时自动展开所有匹配
  const totalMatched = useMemo(() => {
    if (!query.trim()) return 0;
    const q = query.toLowerCase();
    return FAQ_SECTIONS.reduce((sum, s) => {
      return sum + s.items.filter(it => it.q.toLowerCase().includes(q) || it.a.toLowerCase().includes(q)).length;
    }, 0);
  }, [query]);

  const pageBg = isDark ? '#06080C' : '#F4F5F7';
  const headerBg = isDark ? 'rgba(6, 8, 12, 0.85)' : 'rgba(244, 245, 247, 0.85)';
  const headerBorder = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(25,28,29,0.08)';

  return (
    <div className="min-h-screen pb-20" style={{ background: pageBg }}>
      {/* Header */}
      <header
        className="sticky top-0 z-40 backdrop-blur-xl border-b"
        style={{ background: headerBg, borderColor: headerBorder }}
      >
        <div className="max-w-md mx-auto flex items-center gap-3 px-4 h-14">
          <button
            onClick={() => router.back()}
            className="flex items-center justify-center w-9 h-9 rounded-full active:scale-95 transition-transform"
            style={{
              background: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.04)',
              color: isDark ? '#fff' : '#0F172A',
            }}
            aria-label="返回"
          >
            <ChevronLeft size={20} />
          </button>
          <div className="flex items-center gap-2 flex-1">
            <div className="w-8 h-8 rounded-full overflow-hidden flex-shrink-0">
              <Image src="/logo_meow.jpg" alt="logo" width={32} height={32} className="w-full h-full object-cover" />
            </div>
            <div className="flex flex-col leading-tight">
              <span
                className="font-black italic"
                style={{
                  fontSize: 15,
                  color: isDark ? '#fff' : '#191c1d',
                  fontFamily: "'Plus Jakarta Sans', sans-serif",
                }}
              >
                帮助中心
              </span>
              <span
                className="font-mono"
                style={{ fontSize: 12, color: isDark ? 'rgba(255,255,255,0.35)' : '#5b3f43' }}
              >
                miaomiaodi.cc
              </span>
            </div>
          </div>
          <ThemeToggleButton />
        </div>
      </header>

      <main className="max-w-md mx-auto px-4 pt-4 flex flex-col gap-4">
        {/* Hero — 引导语 */}
        <div
          className="rounded-3xl p-5 relative overflow-hidden"
          style={{
            background: isDark
              ? 'linear-gradient(135deg, rgba(16,185,129,0.15), rgba(0,71,179,0.10))'
              : 'linear-gradient(135deg, #ECFDF5 0%, #EFF6FF 100%)',
            border: isDark
              ? '1px solid rgba(255,255,255,0.08)'
              : '1px solid rgba(15, 118, 110, 0.20)',
          }}
        >
          <div className="flex items-start gap-3 relative z-10">
            <span
              className="flex items-center justify-center w-12 h-12 rounded-full flex-shrink-0"
              style={{
                background: isDark ? 'rgba(16,185,129,0.2)' : '#FFFFFF',
                color: isDark ? '#34D399' : '#0F766E',
                boxShadow: isDark ? 'none' : '0 2px 8px rgba(15, 118, 110, 0.15)',
              }}
            >
              <TrendingUp size={22} />
            </span>
            <div className="flex-1">
              <p
                className="font-black mb-1"
                style={{
                  fontSize: 16,
                  color: isDark ? '#fff' : '#0F172A',
                  fontFamily: "'Plus Jakarta Sans', sans-serif",
                  lineHeight: 1.3,
                }}
              >
                想知道模型靠不靠谱？
              </p>
              <p
                className="font-medium"
                style={{
                  fontSize: 12,
                  color: isDark ? 'rgba(255,255,255,0.7)' : '#475569',
                  lineHeight: 1.5,
                }}
              >
                看「<span style={{ color: isDark ? '#34D399' : '#0F766E', fontWeight: 800 }}>近 30 天命中率 &amp; Brier Score</span>」就够了。
                <br />
                以下是用户最关心的 17 个问题。
              </p>
            </div>
          </div>
        </div>

        {/* 搜索框 */}
        <div
          className="flex items-center gap-2 rounded-full px-4 py-3"
          style={{
            background: isDark ? 'rgba(255,255,255,0.06)' : '#fff',
            border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(25,28,29,0.08)',
          }}
        >
          <Search size={16} style={{ color: isDark ? 'rgba(255,255,255,0.45)' : '#94A3B8', flexShrink: 0 }} />
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="搜索关键词，例如：Brier、VIP、登录…"
            className="flex-1 bg-transparent outline-none font-medium"
            style={{
              fontSize: 13,
              color: isDark ? '#fff' : '#0F172A',
            }}
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              className="font-bold"
              style={{ fontSize: 12, color: isDark ? 'rgba(255,255,255,0.45)' : '#94A3B8' }}
            >
              清除
            </button>
          )}
        </div>

        {query.trim() && (
          <p
            className="font-semibold -mt-1"
            style={{ fontSize: 12, color: isDark ? 'rgba(255,255,255,0.5)' : '#64748B' }}
          >
            找到 <span style={{ color: isDark ? '#34D399' : '#0F766E', fontWeight: 900 }}>{totalMatched}</span> 条结果
          </p>
        )}

        {/* FAQ 分类 */}
        {FAQ_SECTIONS.map(s => (
          <FAQSectionCard
            key={s.id}
            section={s}
            isDark={isDark}
            openKeys={openKeys}
            onToggle={toggleKey}
            query={query}
          />
        ))}

        {/* 联系我们：公众号二维码 + 邮件 */}
        <div
          className="rounded-3xl p-5 flex flex-col gap-4"
          style={
            isDark
              ? { background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }
              : { background: '#fff', boxShadow: '0 1px 4px rgba(25,28,29,0.08)' }
          }
        >
          <div className="flex flex-col gap-1">
            <p
              className="font-black italic"
              style={{
                fontSize: 16,
                color: isDark ? '#fff' : '#191c1d',
                fontFamily: "'Plus Jakarta Sans', sans-serif",
              }}
            >
              直接找真人聊聊
            </p>
            <p
              className="font-medium"
              style={{ fontSize: 12, color: isDark ? 'rgba(255,255,255,0.7)' : '#475569', lineHeight: 1.6 }}
            >
              扫码关注公众号
              <span style={{ color: isDark ? '#34D399' : '#0F766E', fontWeight: 800, margin: '0 2px' }}>
                【足球喵喵弟】
              </span>
              ，发消息直达运营，回复最快。
            </p>
          </div>

          {/* 二维码主区 */}
          <div
            className="flex items-center gap-4 rounded-2xl p-4"
            style={{
              background: isDark ? 'rgba(16, 185, 129, 0.08)' : '#ECFDF5',
              border: isDark ? '1px solid rgba(16, 185, 129, 0.25)' : '1px solid #A7F3D0',
            }}
          >
            {/* QR 二维码 */}
            <div
              className="rounded-xl overflow-hidden flex-shrink-0"
              style={{
                width: 110,
                height: 110,
                background: '#FFFFFF',
                padding: 6,
                boxShadow: isDark
                  ? '0 0 0 1px rgba(255,255,255,0.1)'
                  : '0 1px 4px rgba(0,0,0,0.06)',
              }}
            >
              <img
                src="/images/wechat-qr.jpg"
                alt="足球喵喵弟 公众号二维码"
                className="w-full h-full object-cover rounded-lg"
              />
            </div>

            {/* 右侧引导 */}
            <div className="flex flex-col gap-1.5 flex-1 min-w-0">
              <p
                className="font-black"
                style={{
                  fontSize: 14,
                  color: isDark ? '#34D399' : '#047857',
                  fontFamily: "'Plus Jakarta Sans', sans-serif",
                  lineHeight: 1.2,
                }}
              >
                足球喵喵弟
              </p>
              <p
                className="font-semibold"
                style={{ fontSize: 12, color: isDark ? 'rgba(255,255,255,0.7)' : '#475569', lineHeight: 1.5 }}
              >
                · 每日分析报告自动推送<br />
                · 兑换 VIP / 反馈建议<br />
                · 24h 内人工回复
              </p>
            </div>
          </div>

          {/* 备用邮件 */}
          <a
            href="mailto:support@miaomiaodi.cc"
            className="flex items-center justify-center gap-2 rounded-full py-2.5 active:scale-95 transition-transform border"
            style={{
              background: 'transparent',
              borderColor: isDark ? 'rgba(255,255,255,0.15)' : '#CBD5E1',
              color: isDark ? '#CBD5E1' : '#475569',
            }}
          >
            <Mail size={14} />
            <span className="font-bold" style={{ fontSize: 12 }}>
              备用邮箱 support@miaomiaodi.cc
            </span>
          </a>
        </div>

        {/* Footer */}
        <p
          className="text-center font-bold pb-4 mt-2"
          style={{ fontSize: 12, color: isDark ? 'rgba(255,255,255,0.2)' : '#94A3B8' }}
        >
          喵弟数据研究室 · v1.0 · © 2026
        </p>
      </main>
    </div>
  );
}
