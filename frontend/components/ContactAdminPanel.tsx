'use client';

/**
 * ContactAdminPanel
 * 游客详情页底部：扫码联系管理员开通账号
 * 二维码图片：/images/admin-wechat-qr-v2.jpg（管理员上传替换；换图时递增版本号避免 CDN/浏览器缓存吐旧图）
 */

export default function ContactAdminPanel() {
  return (
    <div className="rounded-2xl border border-zinc-700/40 bg-zinc-900/60 p-6 flex flex-col items-center gap-4 text-center mt-4">
      {/* 图标 */}
      <div className="w-10 h-10 rounded-full bg-[var(--primary-neon)]/10 flex items-center justify-center">
        <span className="text-[var(--primary-neon)] text-xl">💬</span>
      </div>

      {/* 标题 */}
      <div>
        <p className="text-base font-black text-white mb-1">开通账号查看完整分析</p>
        <p className="text-xs text-zinc-400 leading-relaxed">
          扫码添加管理员微信，开通后可查看<br />
          推荐方向 · 市场概率 · 预计首发 · 近期表现
        </p>
      </div>

      {/* 二维码 */}
      <img
        src="/images/admin-wechat-qr-v2.jpg"
        alt="管理员微信二维码"
        className="w-44 h-44 rounded-2xl object-cover"
        style={{ border: '1px solid rgba(255,255,255,0.10)' }}
        onError={(e) => {
          // 图片缺失时显示占位文案
          (e.target as HTMLImageElement).style.display = 'none';
        }}
      />

      <p className="text-xs text-zinc-500">扫描上方二维码 · 联系管理员开通</p>
    </div>
  );
}
