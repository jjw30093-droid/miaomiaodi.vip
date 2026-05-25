import type { Metadata } from 'next';
import Link from 'next/link';
import Image from 'next/image';

export const metadata: Metadata = {
  title: '关于我们 | 足球数研所',
  description: '足球数研所 · 一个专注于足球高阶数据（xG / xA / Dixon-Coles）与 AI 量化分析报告的独立科研平台。',
};

export default function AboutPage() {
  return (
    <main className="min-h-screen bg-[#050610] text-slate-300">
      {/* 顶部导航 */}
      <div className="sticky top-0 z-10 border-b border-white/5 bg-[#050610]/80 backdrop-blur-xl">
        <div className="mx-auto max-w-2xl px-5 py-4 flex items-center gap-3">
          <Link
            href="/"
            className="text-slate-500 hover:text-slate-300 transition-colors text-sm"
          >
            ← 返回
          </Link>
          <span className="text-slate-600">|</span>
          <span className="text-xs text-slate-500 font-mono">足球数研所</span>
        </div>
      </div>

      {/* 正文 */}
      <article className="mx-auto max-w-2xl px-5 py-12 pb-24">
        {/* 页面标题 */}
        <header className="mb-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-[#b388ff]/20 bg-[#b388ff]/5 mb-4">
            <span className="text-xs font-mono font-bold tracking-widest text-[#b388ff] uppercase">About</span>
          </div>
          <h1 className="text-2xl font-black text-white leading-tight mb-2 flex items-center gap-3">
            <Image
              src="/logo_meow.jpg"
              alt="足球数研所"
              width={40}
              height={40}
              className="rounded-full object-contain flex-shrink-0"
              priority
            />
            关于足球数研所
          </h1>
          <p className="text-sm text-slate-500 font-mono">About · miaomiaodi.vip</p>
        </header>

        {/* 引言 */}
        <div className="mb-8 p-4 rounded-xl border border-white/5 bg-white/[0.02]">
          <p className="text-sm leading-7 text-slate-400">
            我们是一群热爱战术板、厌倦了主观嘴炮的足球人。用数据说话，让概率替情绪做决定 —— 这就是足球数研所。
          </p>
        </div>

        <div className="space-y-8">
          {/* 01 */}
          <section>
            <h2 className="text-base font-black text-white mb-3 flex items-center gap-2">
              <span className="text-[#b388ff] font-mono text-sm">01</span>
              我们在做什么
            </h2>
            <div className="space-y-3 pl-6 border-l border-white/5">
              <p className="text-sm leading-7 text-slate-400">
                足球数研所（miaomiaodi.vip）是一个专注于足球高阶数据分析的独立科研平台。我们不是传统的赛前分析站，更不是博彩网站 — 我们把英超、西甲、德甲、意甲、法甲、J联赛、K联赛、A联赛等 10+ 主流联赛的每一场比赛，当成一道可被量化的数学题来解。
              </p>
              <p className="text-sm leading-7 text-slate-400">
                核心输出是三件事：<span className="text-white font-semibold">AI 赛前量化研报</span>（15+ 章节深度数据分析）、<span className="text-white font-semibold">三维预测模型</span>（胜平负 / 进球数 / Spread Line）、<span className="text-white font-semibold">赛后精度审计</span>（模型预测 vs 实际结果的公开回测）。
              </p>
            </div>
          </section>

          {/* 02 */}
          <section>
            <h2 className="text-base font-black text-white mb-3 flex items-center gap-2">
              <span className="text-[#b388ff] font-mono text-sm">02</span>
              数据来源的透明度
            </h2>
            <div className="space-y-3 pl-6 border-l border-white/5">
              <p className="text-sm leading-7 text-slate-400">
                所有推演的起点是数据 — 我们同时从多个独立源拉取、交叉验证，不做"一家之言"：
              </p>
              <ul className="space-y-3">
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[#b388ff]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-slate-400">
                    <span className="text-white font-semibold">基础赛果 &amp; 市场价格：</span>Football-Data.co.uk（1993 年起的历史市场价格原始档案）+ The Odds API（主流博彩公司实时开盘 / 收盘市场价格）
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[#b388ff]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-slate-400">
                    <span className="text-white font-semibold">高阶数据：</span>Understat（xG / xA / 射门质量热力图）+ Fotmob（首发阵容、场上热区、对位数据）
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[#b388ff]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-slate-400">
                    <span className="text-white font-semibold">战术与球员：</span>Opta 派生指标（PPDA 压迫强度、Field Tilt 场地倾斜、Big Chances Created）
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[#b388ff]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-slate-400">
                    <span className="text-white font-semibold">联赛覆盖：</span>五大联赛 + 欧冠 / 欧联 + J1/K1/A 联赛 + 阿根廷甲级 + 巴甲 + MLS，每晚实时刷新
                  </p>
                </li>
              </ul>
            </div>
          </section>

          {/* 03 */}
          <section>
            <h2 className="text-base font-black text-white mb-3 flex items-center gap-2">
              <span className="text-[#b388ff] font-mono text-sm">03</span>
              模型方法论（方法论 &gt; 结果）
            </h2>
            <div className="space-y-3 pl-6 border-l border-white/5">
              <p className="text-sm leading-7 text-slate-400">
                我们同时运行三套独立模型，每场比赛都让它们各自给出判断，再通过置信度规则择优输出：
              </p>
              <ul className="space-y-3">
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[#b388ff]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-slate-400">
                    <span className="text-white font-semibold">WDL 主客平：</span>XGBoost 梯度提升 + 温度缩放校准 + 联赛级 bias 偏移
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[#b388ff]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-slate-400">
                    <span className="text-white font-semibold">进球数预测 (Goals)：</span>XGBoost + 联赛动态进球线阈值（不同联赛进球分布差异大）
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[#b388ff]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-slate-400">
                    <span className="text-white font-semibold">Spread Line 预测：</span>Dixon-Coles 联合泊松 λ 估计 + XGBoost 修正
                  </p>
                </li>
              </ul>
              <p className="text-sm leading-7 text-slate-400">
                每周一凌晨自动重训一次（近 12 周滑窗），每个模型都有独立的 Brier Score、Accuracy、Calibration 监控 — 跑偏了会触发 drift 告警。每一次预测，我们都会在赛后公开对比预测 vs 实际结果（含 Brier Score 趋势），<span className="text-white font-semibold">不挑选、不隐藏</span>。
              </p>
            </div>
          </section>

          {/* 04 */}
          <section>
            <h2 className="text-base font-black text-white mb-3 flex items-center gap-2">
              <span className="text-[#b388ff] font-mono text-sm">04</span>
              SHAP 可解释性
            </h2>
            <div className="pl-6 border-l border-white/5">
              <p className="text-sm leading-7 text-slate-400">
                光给概率不够 — 我们用 SHAP 算法（Shapley Additive Explanations）把每一次预测拆给你看：主队名次排位、近 5 场 xG 差、主客场数据倾斜、轮换程度、首发影响 … 每个特征对最终概率的贡献度都有一张归因图。不懂为什么模型给出主胜最高概率？点开研报的"归因分析"章节，你会看到一行透明的"为什么"。
              </p>
            </div>
          </section>

          {/* 05 */}
          <section>
            <h2 className="text-base font-black text-white mb-3 flex items-center gap-2">
              <span className="text-[#b388ff] font-mono text-sm">05</span>
              最高置信度原则
            </h2>
            <div className="pl-6 border-l border-white/5">
              <p className="text-sm leading-7 text-slate-400">
                每场研报只输出<span className="text-white font-semibold">置信度最高的一个</span>预测方向。三套模型各自给出概率分布，系统自动选取校准后置信度最高、Brier Score 历史表现最优的那条输出。低置信度场次会被自动过滤 — 宁可不出，也不降低精度。
              </p>
            </div>
          </section>

          {/* 06 */}
          <section>
            <h2 className="text-base font-black text-white mb-3 flex items-center gap-2">
              <span className="text-[#b388ff] font-mono text-sm">06</span>
              立场与免责
            </h2>
            <div className="pl-6 border-l border-white/5">
              <p className="text-sm leading-7 text-slate-400">
                足球数研所是足球数据分析的 SaaS 工具，<span className="text-white font-semibold">不是博彩网站，不提供投注建议</span>。所有研报、概率数据、AI 分析结论<span className="text-white font-semibold">仅供足球爱好者与数据科学从业者学术参考，不构成任何形式的投注建议，我们不对任何投注结果承担责任</span>。请务必遵守你所在国家和地区的法律法规。详细免责条款见{' '}
                <Link href="/terms#disclaimer" className="text-[#b388ff]/80 hover:text-[#b388ff] transition-colors">
                  服务条款 · 免责声明 →
                </Link>
              </p>
            </div>
          </section>

          {/* 07 */}
          <section>
            <h2 className="text-base font-black text-white mb-3 flex items-center gap-2">
              <span className="text-[#b388ff] font-mono text-sm">07</span>
              联系我们
            </h2>
            <div className="space-y-4 pl-6 border-l border-white/5">
              <p className="text-sm leading-7 text-slate-400">
                如果你对足球数据也有一份执着，或者有研报 bug、数据源建议、合作洽谈，欢迎通过以下渠道联系我们：
              </p>
              <ul className="space-y-2">
                <li className="flex items-center gap-3">
                  <span className="mt-0 w-1.5 h-1.5 rounded-full bg-[#b388ff]/60 flex-shrink-0" />
                  <p className="text-sm text-slate-400">
                    <span className="text-white font-semibold">微信公众号：</span>足球喵喵弟
                  </p>
                </li>
                <li className="flex items-center gap-3">
                  <span className="mt-0 w-1.5 h-1.5 rounded-full bg-[#b388ff]/60 flex-shrink-0" />
                  <p className="text-sm text-slate-400">
                    <span className="text-white font-semibold">邮箱：</span>
                    <a href="mailto:jjw30093@gmail.com" className="text-[#b388ff]/80 hover:text-[#b388ff] transition-colors">
                      jjw30093@gmail.com
                    </a>
                  </p>
                </li>
              </ul>
              {/* 公众号二维码 */}
              <div className="mt-4 flex flex-col items-start gap-2">
                <p className="text-xs text-slate-500 font-mono">扫码关注公众号，获取每日研报推送</p>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src="/images/wechat-qr.jpg"
                  alt="足球喵喵弟 微信公众号二维码"
                  width={220}
                  height={220}
                  className="rounded-xl border border-white/10 bg-white p-2"
                  style={{ display: 'block' }}
                />
              </div>
            </div>
          </section>
        </div>

        {/* 底部分割 */}
        <div className="mt-12 pt-6 border-t border-white/5 flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-xs text-slate-600 font-mono">© 2025 足球数研所</p>
          <div className="flex items-center gap-4">
            <Link href="/terms" className="text-xs text-[#b388ff]/60 hover:text-[#b388ff] transition-colors">
              服务条款 →
            </Link>
            <Link href="/privacy" className="text-xs text-[#b388ff]/60 hover:text-[#b388ff] transition-colors">
              隐私政策 →
            </Link>
          </div>
        </div>
      </article>
    </main>
  );
}
