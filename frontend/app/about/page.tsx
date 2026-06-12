import type { Metadata } from 'next';
import Link from 'next/link';
import Image from 'next/image';

export const metadata: Metadata = {
  title: '关于我们 | 足球数研所',
  description: '足球数研所 · AI-powered football match analysis platform using Dixon-Coles, LightGBM and SHAP. 专业足球数据研究。',
  keywords: ['football analytics', 'Dixon-Coles', 'LightGBM', 'SHAP', 'Brier Score', 'football prediction', '足球数据分析', '足球研报'],
};

export default function AboutPage() {
  return (
    <main className="min-h-screen bg-[var(--color-background)] text-stone-700 dark:text-slate-300">
      {/* 顶部导航 */}
      <div className="sticky top-0 z-10 border-b border-stone-200 dark:border-white/5 bg-[var(--color-background)]/80 dark:bg-zinc-950/80 backdrop-blur-xl">
        <div className="mx-auto max-w-2xl px-5 py-4 flex items-center gap-3">
          <Link
            href="/"
            className="text-stone-500 hover:text-stone-800 dark:text-slate-500 dark:hover:text-slate-300 transition-colors text-sm"
          >
            ← 返回
          </Link>
          <span className="text-stone-300 dark:text-slate-600">|</span>
          <span className="text-xs text-stone-400 dark:text-slate-500 font-mono">喵弟数据研究室</span>
        </div>
      </div>

      {/* 正文 */}
      <article className="mx-auto max-w-2xl px-5 py-12 pb-24">
        {/* 页面标题 */}
        <header className="mb-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-amber-200 bg-amber-50 dark:border-amber-700/30 dark:bg-amber-900/10 mb-4">
            <span className="text-xs font-mono font-bold tracking-widest text-amber-700 dark:text-amber-400 uppercase">About</span>
          </div>
          <h1 className="text-2xl font-black text-stone-900 dark:text-white leading-tight mb-2 flex items-center gap-3">
            <Image
              src="/logo_meow.jpg"
              alt="喵弟数据研究室"
              width={40}
              height={40}
              className="rounded-full object-contain flex-shrink-0"
              priority
            />
            关于喵弟数据研究室
          </h1>
          <p className="text-sm text-slate-500 font-mono">About · miaomiaodi.cc</p>
        </header>

        {/* 引言 */}
        <div className="mb-8 p-4 rounded-xl border border-stone-200 bg-stone-50 dark:border-white/5 dark:bg-white/[0.02]">
          <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
            我们是一群热爱战术板、厌倦了主观嘴炮的足球人。用数据说话，让概率替情绪做决定 —— 这就是喵弟。
          </p>
        </div>

        <div className="space-y-8">
          {/* 01 */}
          <section>
            <h2 className="text-base font-black text-stone-900 dark:text-white mb-3 flex items-center gap-2">
              <span className="text-[color:var(--primary-neon)] font-mono text-sm">01</span>
              我们在做什么
            </h2>
            <div className="space-y-3 pl-6 border-l border-stone-200 dark:border-white/5">
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                喵弟数据研究室（miaomiaodi.cc）是一个专注于足球高阶数据分析的独立科研平台。我们不是传统的赛前分析站，更不是博彩网站 — 我们把英超、西甲、德甲、意甲、法甲、J联赛、K联赛、A联赛等 10+ 主流联赛的每一场比赛，当成一道可被量化的数学题来解。
              </p>
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                核心输出是三件事：<span className="text-white font-semibold">AI 赛前研报</span>（15+ 章节的深度推演）、<span className="text-white font-semibold">三大市场概率分析</span>（WDL / Goals / Spread）、<span className="text-white font-semibold">赛后复盘与模型精度公开</span>。
              </p>
            </div>
          </section>

          {/* 02 */}
          <section>
            <h2 className="text-base font-black text-stone-900 dark:text-white mb-3 flex items-center gap-2">
              <span className="text-[color:var(--primary-neon)] font-mono text-sm">02</span>
              数据来源的透明度
            </h2>
            <div className="space-y-3 pl-6 border-l border-stone-200 dark:border-white/5">
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                所有推演的起点是数据 — 我们同时从多个独立源拉取、交叉验证，不做"一家之言"：
              </p>
              <ul className="space-y-3">
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[color:var(--primary-neon)]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                    <span className="text-stone-900 dark:text-white font-semibold">基础赛果 &amp; 市场价格：</span>Football-Data.co.uk（1993 年起的历史市场价格档案）+ The Odds API（主流交易商实时市场价格）
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[color:var(--primary-neon)]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                    <span className="text-stone-900 dark:text-white font-semibold">高阶数据：</span>Understat（xG / xA / 射门质量热力图）+ Fotmob（首发阵容、场上热区、对位数据）
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[color:var(--primary-neon)]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                    <span className="text-stone-900 dark:text-white font-semibold">战术与球员：</span>Opta 派生指标（PPDA 压迫强度、Field Tilt 场地倾斜、Big Chances Created）
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[color:var(--primary-neon)]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                    <span className="text-stone-900 dark:text-white font-semibold">联赛覆盖：</span>五大联赛 + 欧冠 / 欧联 + J1/K1/A 联赛 + 阿根廷甲级 + 巴甲 + MLS，每晚实时刷新
                  </p>
                </li>
              </ul>
            </div>
          </section>

          {/* 03 */}
          <section>
            <h2 className="text-base font-black text-stone-900 dark:text-white mb-3 flex items-center gap-2">
              <span className="text-[color:var(--primary-neon)] font-mono text-sm">03</span>
              模型方法论（方法论 &gt; 结果）
            </h2>
            <div className="space-y-3 pl-6 border-l border-stone-200 dark:border-white/5">
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                我们同时运行三套独立模型，每场比赛都让它们各自给出判断，再通过置信度规则选取最优输出：
              </p>
              <ul className="space-y-3">
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[color:var(--primary-neon)]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                    <span className="text-stone-900 dark:text-white font-semibold">WDL 主客平：</span>XGBoost 梯度提升 + 温度缩放校准 + 联赛级 bias 偏移
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[color:var(--primary-neon)]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                    <span className="text-stone-900 dark:text-white font-semibold">进球数预测 (Goals)：</span>XGBoost + 联赛动态进球线阈值（不同联赛进球分布差异大）
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[color:var(--primary-neon)]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                    <span className="text-stone-900 dark:text-white font-semibold">Spread Line 预测：</span>Dixon-Coles 联合泊松 λ 估计 + XGBoost 比分差修正
                  </p>
                </li>
              </ul>
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                每周一凌晨自动重训一次（近 12 周滑窗），每个模型都有独立的 Brier Score、Accuracy、Calibration 监控 — 跑偏了会触发 drift 告警。模型的每一次预测，我们都会在赛后审计命中与否，<span className="text-white font-semibold">不挑选、不隐藏</span>。
              </p>
            </div>
          </section>

          {/* 04 */}
          <section>
            <h2 className="text-base font-black text-stone-900 dark:text-white mb-3 flex items-center gap-2">
              <span className="text-[color:var(--primary-neon)] font-mono text-sm">04</span>
              SHAP 可解释性
            </h2>
            <div className="pl-6 border-l border-stone-200 dark:border-white/5">
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                光给概率不够 — 我们用 SHAP 算法（Shapley Additive Explanations）把每一次预测拆给你看：主队名次排位、近 5 场 xG 差、主客场数据倾斜、轮换程度、首发影响 … 每个特征对最终概率的贡献度都有一张归因图。不懂为什么预测推主胜？点开研报的"归因分析"章节，你会看到一行透明的"为什么"。
              </p>
            </div>
          </section>

          {/* 05 */}
          <section>
            <h2 className="text-base font-black text-stone-900 dark:text-white mb-3 flex items-center gap-2">
              <span className="text-[color:var(--primary-neon)] font-mono text-sm">05</span>
              输出哲学
            </h2>
            <div className="pl-6 border-l border-stone-200 dark:border-white/5">
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                每场研报只输出置信度最高的<span className="text-white font-semibold">一个</span>预测方向。三套模型各自给出概率分布，系统自动选取校准后置信度最高、Brier Score 历史表现最优的那条输出。低置信度场次会被自动过滤 — 宁可不出，也不降低精度。
              </p>
            </div>
          </section>

          {/* 06 */}
          <section>
            <h2 className="text-base font-black text-stone-900 dark:text-white mb-3 flex items-center gap-2">
              <span className="text-[color:var(--primary-neon)] font-mono text-sm">06</span>
              立场与免责
            </h2>
            <div className="pl-6 border-l border-stone-200 dark:border-white/5">
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                喵弟是足球战术 × 数据科学的研究工具，<span className="text-white font-semibold">不是博彩网站</span>。任何研报、图表、AI 分析<span className="text-white font-semibold">仅供足球爱好者与数据科学从业者参考，不构成任何形式的投注建议</span>。请务必遵守你所在国家和地区的法律法规。详细免责条款见{' '}
                <Link href="/terms#disclaimer" className="text-[color:var(--primary-neon)]/80 hover:text-[color:var(--primary-neon)] transition-colors">
                  服务条款 · 免责声明 →
                </Link>
              </p>
            </div>
          </section>

          {/* 07 */}
          <section>
            <h2 className="text-base font-black text-stone-900 dark:text-white mb-3 flex items-center gap-2">
              <span className="text-[color:var(--primary-neon)] font-mono text-sm">07</span>
              方法论文献
            </h2>
            <div className="space-y-3 pl-6 border-l border-stone-200 dark:border-white/5">
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                以下文献是本平台核心算法的学术基础，欢迎研究者参考：
              </p>
              <ul className="space-y-3">
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[color:var(--primary-neon)]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                    Dixon, M. J., &amp; Coles, S. G. (1997). Modelling association football scores and inefficiencies in the football betting market. <em>Journal of the Royal Statistical Society: Series C</em>, 46(2), 265–280.{' '}
                    <a href="https://doi.org/10.1111/1467-9876.00065" target="_blank" rel="noopener noreferrer" className="text-[color:var(--primary-neon)]/80 hover:text-[color:var(--primary-neon)] transition-colors">
                      DOI: 10.1111/1467-9876.00065 ↗
                    </a>
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[color:var(--primary-neon)]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                    Karlis, D., &amp; Ntzoufras, I. (2003). Analysis of sports data by using bivariate Poisson models. <em>Journal of the Royal Statistical Society: Series D</em>, 52(3), 381–393.{' '}
                    <a href="https://doi.org/10.1111/1467-9884.00366" target="_blank" rel="noopener noreferrer" className="text-[color:var(--primary-neon)]/80 hover:text-[color:var(--primary-neon)] transition-colors">
                      DOI: 10.1111/1467-9884.00366 ↗
                    </a>
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[color:var(--primary-neon)]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                    Lundberg, S. M., &amp; Lee, S. I. (2017). A unified approach to interpreting model predictions. <em>Advances in Neural Information Processing Systems</em>, 30 (NeurIPS 2017).
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[color:var(--primary-neon)]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                    Brier, G. W. (1950). Verification of forecasts expressed in terms of probability. <em>Monthly Weather Review</em>, 78(1), 1–3.
                  </p>
                </li>
              </ul>
            </div>
          </section>

          {/* 08 */}
          <section>
            <h2 className="text-base font-black text-stone-900 dark:text-white mb-3 flex items-center gap-2">
              <span className="text-[color:var(--primary-neon)] font-mono text-sm">08</span>
              联系我们
            </h2>
            <div className="space-y-4 pl-6 border-l border-stone-200 dark:border-white/5">
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                如果你对足球数据也有一份执着，或者有研报 bug、数据源建议、合作洽谈，欢迎通过以下渠道联系我们：
              </p>
              <ul className="space-y-2">
                <li className="flex items-center gap-3">
                  <span className="mt-0 w-1.5 h-1.5 rounded-full bg-[color:var(--primary-neon)]/60 flex-shrink-0" />
                  <p className="text-sm text-stone-600 dark:text-slate-400">
                    <span className="text-stone-900 dark:text-white font-semibold">微信公众号：</span>足球喵喵弟
                  </p>
                </li>
                <li className="flex items-center gap-3">
                  <span className="mt-0 w-1.5 h-1.5 rounded-full bg-[color:var(--primary-neon)]/60 flex-shrink-0" />
                  <p className="text-sm text-stone-600 dark:text-slate-400">
                    <span className="text-stone-900 dark:text-white font-semibold">邮箱：</span>
                    <a href="mailto:jjw30093@gmail.com" className="text-[color:var(--primary-neon)]/80 hover:text-[color:var(--primary-neon)] transition-colors">
                      jjw30093@gmail.com
                    </a>
                  </p>
                </li>
              </ul>
              {/* 公众号二维码 */}
              <div className="mt-4 flex flex-col items-start gap-2">
                <p className="text-xs text-stone-400 dark:text-slate-500 font-mono">扫码关注公众号，获取每日研报推送</p>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src="/images/admin-wechat-qr-v2.jpg"
                  alt="足球喵喵弟 微信二维码"
                  width={220}
                  height={220}
                  className="rounded-xl border border-stone-200 dark:border-white/10 bg-white p-2"
                  style={{ display: 'block' }}
                />
              </div>
            </div>
          </section>
        </div>

        {/* 底部分割 */}
        <div className="mt-12 pt-6 border-t border-stone-200 dark:border-white/5 flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-xs text-stone-400 dark:text-slate-600 font-mono">© 2025 喵弟数据研究室</p>
          <div className="flex items-center gap-4">
            <Link href="/terms" className="text-xs text-[color:var(--primary-neon)]/70 hover:text-[color:var(--primary-neon)] transition-colors">
              服务条款 →
            </Link>
            <Link href="/privacy" className="text-xs text-[color:var(--primary-neon)]/70 hover:text-[color:var(--primary-neon)] transition-colors">
              隐私政策 →
            </Link>
          </div>
        </div>
      </article>
    </main>
  );
}
