import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: '服务条款 | 喵弟数据研究室',
  description: '喵弟数据研究室用户服务条款，包含免责声明、账号安全、订阅政策及第三方依赖说明。',
};

export default function TermsPage() {
  return (
    <main className="min-h-screen bg-[var(--color-background)] text-stone-700 dark:text-slate-300">
      {/* 顶部导航 */}
      <div className="sticky top-0 z-10 border-b border-stone-200 dark:border-white/5 bg-[var(--header-bg)] backdrop-blur-xl">
        <div className="mx-auto max-w-2xl px-5 py-4 flex items-center gap-3">
          <Link
            href="/"
            className="text-stone-500 hover:text-stone-700 dark:text-slate-500 dark:hover:text-slate-300 transition-colors text-sm"
          >
            ← 返回
          </Link>
          <span className="text-stone-400 dark:text-slate-600">|</span>
          <span className="text-xs text-stone-500 dark:text-slate-500 font-mono">喵弟数据研究室</span>
        </div>
      </div>

      {/* 正文 */}
      <article className="mx-auto max-w-2xl px-5 py-12 pb-24">
        {/* 页面标题 */}
        <header className="mb-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-primary-neon/20 bg-primary-neon/5 mb-4">
            <span className="text-xs font-mono font-bold text-primary-neon">法律声明</span>
          </div>
          <h1 className="text-2xl font-bold text-stone-900 dark:text-white leading-tight mb-2">
            服务条款
          </h1>
          <p className="text-sm text-stone-500 dark:text-slate-500 font-mono">Terms of Service · miaomiaodi.vip</p>
        </header>

        {/* 引言 */}
        <div className="mb-8 p-4 rounded-xl border border-stone-200 dark:border-white/5 bg-stone-50 dark:bg-white/[0.02]">
          <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
            欢迎来到<span className="text-stone-900 dark:text-white font-semibold">喵弟数据研究室</span> (miaomiaodi.vip)。
            在使用我们的数据服务前，请花两分钟了解我们的规则。使用本网站，即代表你同意以下条款：
          </p>
        </div>

        <div className="space-y-8">
          {/* 条款 1 — 免责声明 */}
          <section id="disclaimer">
            <h2 className="text-base font-bold text-stone-900 dark:text-white mb-3 flex items-center gap-2">
              <span className="text-primary-neon font-mono text-sm">01</span>
              核心底线与免责声明（最重要的一条）
            </h2>
            <div className="space-y-3 pl-6 border-l border-stone-200 dark:border-white/5">
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                我们是一家专注于足球高阶数据（xG、xA等）与战术分析的独立科研平台。网站提供的所有可视化图表、AI 赛前推演及赛后复盘研报，仅供足球战术分析、数据科学探讨及球迷交流参考，<span className="text-stone-900 dark:text-white font-semibold">绝不构成任何形式的博彩、投注或理财建议</span>。
              </p>
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                请务必遵守你所在国家和地区的法律法规。任何人因使用本站数据进行非法对赌或博彩造成的损失，本站概不负责，也不承担任何法律连带责任。
              </p>
            </div>
          </section>

          {/* 条款 2 */}
          <section>
            <h2 className="text-base font-bold text-stone-900 dark:text-white mb-3 flex items-center gap-2">
              <span className="text-primary-neon font-mono text-sm">02</span>
              账号安全与合理使用
            </h2>
            <div className="space-y-3 pl-6 border-l border-stone-200 dark:border-white/5">
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                <span className="text-stone-900 dark:text-white font-semibold">专属账号：</span>我们采用便捷的微信验证码鉴权系统。你的账号（及 VIP 权限）仅供个人使用，<span className="text-stone-900 dark:text-white font-semibold">严禁与他人共享、出租或转售账号</span>。
              </p>
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                <span className="text-stone-900 dark:text-white font-semibold">反爬虫与数据保护：</span>我们花费了大量算力与 AI 资源来清洗和生成这些深度报告。严禁使用任何自动化程序（爬虫、脚本等）高频抓取、盗用本站的图表或付费文本。系统会对高频异常请求进行监控，一旦发现恶意抓取，我们将立即永久封禁该账号所在 IP 及微信关联账号，且不予退款。
              </p>
            </div>
          </section>

          {/* 条款 3 */}
          <section>
            <h2 className="text-base font-bold text-stone-900 dark:text-white mb-3 flex items-center gap-2">
              <span className="text-primary-neon font-mono text-sm">03</span>
              订阅服务与退款政策
            </h2>
            <div className="space-y-3 pl-6 border-l border-stone-200 dark:border-white/5">
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                <span className="text-stone-900 dark:text-white font-semibold">数字商品性质：</span>我们的 VIP 服务提供的是实时的数字化内容与高级图表解锁。由于数字商品具有"一旦解锁即可复制与阅读"的不可逆特性，<span className="text-stone-900 dark:text-white font-semibold">VIP 订阅一旦生效，原则上不提供退款服务</span>。
              </p>
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                <span className="text-stone-900 dark:text-white font-semibold">开通方式：</span>账号开通由管理员人工审核处理，请通过站内联系方式与管理员沟通，确认后将为你开通对应权限。
              </p>
            </div>
          </section>

          {/* 条款 4 */}
          <section>
            <h2 className="text-base font-bold text-stone-900 dark:text-white mb-3 flex items-center gap-2">
              <span className="text-primary-neon font-mono text-sm">04</span>
              第三方依赖与免责
            </h2>
            <div className="pl-6 border-l border-stone-200 dark:border-white/5">
              <p className="text-sm leading-7 text-stone-600 dark:text-slate-400">
                本站的运转依赖外部足球基础数据源、大型语言模型（AI）API 以及第三方平台服务。作为一个独立开发项目，我们会尽全力维护服务器的稳定，但不对因上游 API 波动、网络故障导致的短期服务不可用承担违约责任。同时，AI 生成的战术报告偶尔可能存在事实性幻觉，请结合客观比赛情况进行判断。
              </p>
            </div>
          </section>
        </div>

        {/* 底部分割 */}
        <div className="mt-12 pt-6 border-t border-stone-200 dark:border-white/5 flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-xs text-stone-500 dark:text-slate-600 font-mono">© 2025 喵弟数据研究室</p>
          <div className="flex items-center gap-4">
            <span className="text-xs text-stone-500 dark:text-slate-600">当前页面</span>
            <Link href="/privacy" className="text-xs text-primary-neon/70 hover:text-primary-neon transition-colors">
              隐私政策 →
            </Link>
          </div>
        </div>
      </article>
    </main>
  );
}
