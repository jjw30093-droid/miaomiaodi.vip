import Link from 'next/link';

export default function Footer() {
  return (
    <footer className="w-full py-6 border-t border-white/5 bg-transparent">
      <div className="flex flex-col items-center gap-3">
        <div className="flex items-center justify-center gap-4 flex-wrap">
          <Link
            href="/about"
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors duration-200 whitespace-nowrap"
          >
            关于我们
          </Link>
          <span className="text-gray-700 text-xs">·</span>
          <Link
            href="/terms#disclaimer"
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors duration-200 whitespace-nowrap"
          >
            免责声明
          </Link>
          <span className="text-gray-700 text-xs">·</span>
          <Link
            href="/terms"
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors duration-200 whitespace-nowrap"
          >
            服务条款
          </Link>
          <span className="text-gray-700 text-xs">·</span>
          <Link
            href="/privacy"
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors duration-200 whitespace-nowrap"
          >
            隐私政策
          </Link>
        </div>
        <span className="text-xs text-gray-600 font-mono">© 2025 喵弟数据研究室</span>
      </div>
    </footer>
  );
}
