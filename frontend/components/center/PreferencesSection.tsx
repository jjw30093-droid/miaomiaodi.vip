'use client';

import { useState } from 'react';
import { useSession } from 'next-auth/react';
import { useTheme } from '@/components/ThemeProvider';
import { apiClient } from '@/lib/apiClient';

interface Prefs {
  theme: string;
  notify_lineup: boolean;
  notify_postmatch: boolean;
}

interface Props {
  initialPrefs: Prefs;
  isDark: boolean;
}

const THEME_OPTS = [
  { value: 'light', label: '☀️ 浅色' },
  { value: 'dark',  label: '🌑 深色'  },
  { value: 'system', label: '⚙️ 系统'  },
];

export default function PreferencesSection({ initialPrefs, isDark }: Props) {
  const { data: session } = useSession();
  const { theme, toggleTheme } = useTheme();
  const apiToken = (session?.user as any)?.apiToken as string | undefined;
  const [prefs, setPrefs] = useState<Prefs>(initialPrefs);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const saveToBackend = async (updated: Prefs) => {
    if (!apiToken) return;
    setSaving(true);
    try {
      await apiClient.put('/user/preferences', updated, { token: apiToken });
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  };

  const applyTheme = (newThemeValue: string) => {
    if (newThemeValue === 'system') {
      const sysDark = typeof window !== 'undefined'
        ? window.matchMedia('(prefers-color-scheme: dark)').matches
        : true;
      const targetTheme = sysDark ? 'dark' : 'light';
      if (theme !== targetTheme) toggleTheme();
    } else {
      if (theme !== newThemeValue) toggleTheme();
    }
  };

  const updatePref = (key: keyof Prefs, value: any) => {
    const updated = { ...prefs, [key]: value };
    setPrefs(updated);
    if (key === 'theme') applyTheme(value);
    saveToBackend(updated);
  };

  const activeColor = isDark ? '#E91E63' : '#b7004d';
  const activeBg = isDark ? 'rgba(233,30,99,0.1)' : 'rgba(183,0,77,0.08)';
  const activeBorder = isDark ? 'rgba(233,30,99,0.3)' : 'rgba(183,0,77,0.25)';
  const inactiveColor = isDark ? 'rgba(255,255,255,0.45)' : '#5b3f43';
  const inactiveBg = isDark ? 'rgba(255,255,255,0.04)' : 'rgba(25,28,29,0.04)';
  const inactiveBorder = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(25,28,29,0.1)';

  return (
    <div className="flex flex-col gap-5">
      {saved && (
        <p className="text-center text-[13px] font-bold py-2 px-4 rounded-xl"
          style={{ background: activeBg, color: activeColor, border: `1px solid ${activeBorder}` }}>
          ✓ 设置已保存（跨设备同步）
        </p>
      )}

      {/* 主题 segmented */}
      <div>
        <p className="text-[13px] font-bold uppercase tracking-widest mb-3"
          style={{ color: isDark ? 'rgba(255,255,255,0.4)' : '#5b3f43' }}>显示主题</p>
        <div className="flex gap-2">
          {THEME_OPTS.map(opt => {
            const isActive = prefs.theme === opt.value;
            return (
              <button
                key={opt.value}
                onClick={() => updatePref('theme', opt.value)}
                className="flex-1 py-3 rounded-xl text-[13px] font-bold transition-all active:scale-[0.97]"
                style={{
                  background: isActive ? activeBg : inactiveBg,
                  border: `1px solid ${isActive ? activeBorder : inactiveBorder}`,
                  color: isActive ? activeColor : inactiveColor,
                }}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* 通知 toggles */}
      <div>
        <p className="text-[13px] font-bold uppercase tracking-widest mb-3"
          style={{ color: isDark ? 'rgba(255,255,255,0.4)' : '#5b3f43' }}>推送通知</p>
        <div className="flex flex-col gap-4">
          {([
            { key: 'notify_lineup' as const, label: '首发阵容推送', desc: '首发确认后推送通知' },
            { key: 'notify_postmatch' as const, label: '赛后复盘推送', desc: '比赛结束后 AI 复盘报告' },
          ] as const).map(item => {
            const on = prefs[item.key];
            return (
              <div key={item.key} className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-[15px] font-bold" style={{ color: isDark ? '#fff' : '#191c1d' }}>
                    {item.label}
                  </p>
                  <p className="text-[13px] font-bold mt-0.5" style={{ color: isDark ? 'rgba(255,255,255,0.4)' : '#5b3f43' }}>
                    {item.desc}
                  </p>
                </div>
                <button
                  onClick={() => updatePref(item.key, !on)}
                  disabled={saving}
                  className="relative w-12 h-6 rounded-full transition-all flex-shrink-0 disabled:opacity-50"
                  style={{ background: on ? activeColor : (isDark ? 'rgba(255,255,255,0.12)' : 'rgba(25,28,29,0.12)') }}
                  aria-label={item.label}
                >
                  <span
                    className="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all shadow-sm"
                    style={{ left: on ? '24px' : '2px' }}
                  />
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
