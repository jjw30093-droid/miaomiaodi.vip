'use client';

import { useEffect } from 'react';
import { X } from 'lucide-react';
import Link from 'next/link';
import ContactAdminPanel from '@/components/ContactAdminPanel';

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function ContactAdminModal({ open, onClose }: Props) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-sm"
        onClick={e => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute -top-3 -right-3 z-10 w-8 h-8 rounded-full bg-zinc-800 border border-zinc-700 flex items-center justify-center text-zinc-400 hover:text-white transition-colors"
          aria-label="关闭"
        >
          <X size={14} />
        </button>
        <ContactAdminPanel />
        <div className="mt-3 text-center">
          <Link
            href="/login"
            className="text-xs text-zinc-400 hover:text-[var(--primary-neon)] transition-colors"
          >
            已有账号？点此登录 →
          </Link>
        </div>
      </div>
    </div>
  );
}
