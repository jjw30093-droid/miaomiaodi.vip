import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: '隐私政策 | 喵弟数据研究室',
  description: '喵弟数据研究室隐私政策，说明我们收集哪些信息、如何使用及与第三方的数据共享范围。',
};

export default function PrivacyPage() {
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
          <span className="text-xs text-slate-500 font-mono">喵弟数据研究室</span>
        </div>
      </div>

      {/* 正文 */}
      <article className="mx-auto max-w-2xl px-5 py-12 pb-24">
        {/* 页面标题 */}
        <header className="mb-10">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-[#baff00]/20 bg-[#baff00]/5 mb-4">
            <span className="text-xs font-mono font-bold tracking-widest text-[#baff00] uppercase">Privacy</span>
          </div>
          <h1 className="text-2xl font-black text-white leading-tight mb-2">
            🔒 隐私政策
          </h1>
          <p className="text-sm text-slate-500 font-mono">Privacy Policy · miaomiaodi.cc</p>
        </header>

        {/* 引言 */}
        <div className="mb-8 p-4 rounded-xl border border-white/5 bg-white/[0.02]">
          <p className="text-sm leading-7 text-slate-400">
            我们非常讨厌隐私泄露，所以我们也会像保护自己的数据一样保护你的数据。以下是我们处理信息的原则：
          </p>
        </div>

        <div className="space-y-8">
          {/* 条款 1 */}
          <section>
            <h2 className="text-base font-black text-white mb-3 flex items-center gap-2">
              <span className="text-[#baff00] font-mono text-sm">01</span>
              我们收集哪些信息？
            </h2>
            <div className="space-y-4 pl-6 border-l border-white/5">
              <div>
                <p className="text-xs font-bold text-white mb-1">业务必须信息</p>
                <p className="text-sm leading-7 text-slate-400">
                  当你通过微信获取验证码登录时，我们会获取你的微信 OpenID、昵称和头像，这仅仅是为了给你创建一个独一无二的账号，并绑定你的 VIP 权益。
                </p>
              </div>
              <div>
                <p className="text-xs font-bold text-white mb-1">运行与安全保障信息</p>
                <p className="text-sm leading-7 text-slate-400">
                  为了防止恶意攻击、管理设备并发数量（防止一个账号多端滥用），系统会自动记录你的 IP 地址、浏览器设备标识（User-Agent）及登录时间戳。
                </p>
              </div>
              <div>
                <p className="text-xs font-bold text-white mb-1">本地偏好</p>
                <p className="text-sm leading-7 text-slate-400">
                  我们会使用基础的 Cookies 或 LocalStorage 来保持你的登录状态，并记住你的阅读偏好（例如你设置了深色模式还是浅色模式）。
                </p>
              </div>
            </div>
          </section>

          {/* 条款 2 */}
          <section>
            <h2 className="text-base font-black text-white mb-3 flex items-center gap-2">
              <span className="text-[#baff00] font-mono text-sm">02</span>
              这些信息用来做什么？
            </h2>
            <div className="pl-6 border-l border-white/5">
              <p className="text-sm leading-7 text-slate-400">
                我们收集的信息仅用于维持网站的核心运转（鉴权、解锁报告、防爬虫风控）。我们是一个单纯卖数据服务的团队，<span className="text-white font-semibold">绝对不会向任何无关的第三方广告商出售你的个人隐私数据</span>。
              </p>
            </div>
          </section>

          {/* 条款 3 */}
          <section>
            <h2 className="text-base font-black text-white mb-3 flex items-center gap-2">
              <span className="text-[#baff00] font-mono text-sm">03</span>
              数据流转与第三方共享
            </h2>
            <div className="space-y-4 pl-6 border-l border-white/5">
              <p className="text-sm leading-7 text-slate-400">
                为了提供完整的服务，我们的系统必须和以下大厂进行数据交互，但流转极其克制：
              </p>
              <ul className="space-y-3">
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[#baff00]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-slate-400">
                    <span className="text-white font-semibold">腾讯生态：</span>处理验证码下发与登录鉴权。
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[#baff00]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-slate-400">
                    <span className="text-white font-semibold">AI 大模型服务商：</span>我们会将客观的足球比赛数据发送给 AI 生成研报，但<span className="text-white font-semibold">绝对不会</span>把你的个人微信号或行为轨迹发送给 AI 训练。
                  </p>
                </li>
                <li className="flex items-start gap-3">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[#baff00]/60 flex-shrink-0" />
                  <p className="text-sm leading-7 text-slate-400">
                    <span className="text-white font-semibold">支付处理方：</span>当你在进行订阅或充值时，你的账单信息是由合规的支付渠道独立处理的，我们仅接收"支付成功"的加密回执。
                  </p>
                </li>
              </ul>
            </div>
          </section>
        </div>

        {/* 底部分割 */}
        <div className="mt-12 pt-6 border-t border-white/5 flex flex-col sm:flex-row items-center justify-between gap-3">
          <p className="text-xs text-slate-600 font-mono">© 2025 喵弟数据研究室</p>
          <div className="flex items-center gap-4">
            <Link href="/terms" className="text-xs text-[#baff00]/60 hover:text-[#baff00] transition-colors">
              ← 服务条款
            </Link>
            <span className="text-xs text-slate-600">当前页面</span>
          </div>
        </div>
      </article>
    </main>
  );
}
