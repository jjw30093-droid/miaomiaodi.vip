import Link from 'next/link';

export default function Footer() {
  return (
    <footer className="w-full py-6 border-t border-stone-200 dark:border-white/5 bg-transparent">
      <div className="flex flex-col items-center gap-3">
        <div className="flex items-center justify-center gap-4 flex-wrap">
          <Link
            href="/about"
            className="text-xs text-stone-500 hover:text-stone-700 dark:text-gray-500 dark:hover:text-gray-300 transition-colors duration-200 whitespace-nowrap"
          >
            关于我们
          </Link>
          <span className="text-stone-400 dark:text-gray-700 text-xs">·</span>
          <Link
            href="/terms#disclaimer"
            className="text-xs text-stone-500 hover:text-stone-700 dark:text-gray-500 dark:hover:text-gray-300 transition-colors duration-200 whitespace-nowrap"
          >
            免责声明
          </Link>
          <span className="text-stone-400 dark:text-gray-700 text-xs">·</span>
          <Link
            href="/terms"
            className="text-xs text-stone-500 hover:text-stone-700 dark:text-gray-500 dark:hover:text-gray-300 transition-colors duration-200 whitespace-nowrap"
          >
            服务条款
          </Link>
          <span className="text-stone-400 dark:text-gray-700 text-xs">·</span>
          <Link
            href="/privacy"
            className="text-xs text-stone-500 hover:text-stone-700 dark:text-gray-500 dark:hover:text-gray-300 transition-colors duration-200 whitespace-nowrap"
          >
            隐私政策
          </Link>
        </div>
        <span className="text-xs text-stone-500 dark:text-gray-600">© 2025 喵弟数据研究室</span>
      </div>
    </footer>
  );
}
