'use client';

import { useState } from 'react';
import { useSession } from 'next-auth/react';
import { apiClient } from '@/lib/apiClient';

interface Prefs {
  theme: string;
  notify_lineup: boolean;
  notify_postmatch: boolean;
}

export default function PreferencesPanel({ initialPrefs }: { initialPrefs: Prefs }) {
  const { data: session } = useSession();
  const apiToken = (session?.user as any)?.apiToken as string | undefined;
  const [prefs, setPrefs] = useState<Prefs>(initialPrefs);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const save = async (updated: Prefs) => {
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

  const updatePref = (key: keyof Prefs, value: any) => {
    const updated = { ...prefs, [key]: value };
    setPrefs(updated);
    save(updated);
  };

  return (
    <div className="flex flex-col gap-4">
      {saved && (
        <div
          className="text-center py-2 px-4 rounded-xl text-sm font-bold"
          style={{ background: 'rgba(191,165,93,0.08)', color: '#BFA55D', border: '1px solid rgba(191,165,93,0.2)' }}
        >
          ✓ 设置已保存（跨设备同步）
        </div>
      )}

      {/* 主题 */}
      <div
        className="rounded-2xl p-5 flex flex-col gap-3"
        style={{ background: '#12161b', border: '1px solid rgba(255,255,255,0.07)' }}
      >
        <span className="text-xs font-bold uppercase tracking-widest" style={{ color: 'rgba(191,165,93,0.8)' }}>显示主题</span>
        <div className="flex gap-2">
          {[
            { value: 'dark', label: '🌑 深色' },
            { value: 'light', label: '☀️ 浅色' },
            { value: 'system', label: '⚙️ 跟随系统' },
          ].map(opt => (
            <button
              key={opt.value}
              onClick={() => updatePref('theme', opt.value)}
              className="flex-1 py-2.5 rounded-xl text-xs font-bold transition-all"
              style={{
                background: prefs.theme === opt.value ? 'rgba(191,165,93,0.15)' : 'rgba(255,255,255,0.04)',
                border: `1px solid ${prefs.theme === opt.value ? 'rgba(191,165,93,0.4)' : 'rgba(255,255,255,0.08)'}`,
                color: prefs.theme === opt.value ? '#BFA55D' : 'rgba(250,250,252,0.5)',
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* 通知 */}
      <div
        className="rounded-2xl p-5 flex flex-col gap-3"
        style={{ background: '#12161b', border: '1px solid rgba(255,255,255,0.07)' }}
      >
        <span className="text-xs font-bold uppercase tracking-widest" style={{ color: 'rgba(191,165,93,0.8)' }}>推送通知</span>
        {[
          { key: 'notify_lineup' as const, label: '首发阵容推送', desc: '首发确认后通过公众号推送通知' },
          { key: 'notify_postmatch' as const, label: '赛后复盘推送', desc: '比赛结束后 AI 复盘报告推送' },
        ].map(item => (
          <div key={item.key} className="flex items-center justify-between gap-4">
            <div>
              <div className="text-sm font-bold text-white">{item.label}</div>
              <div className="text-xs mt-0.5" style={{ color: 'rgba(250,250,252,0.4)' }}>{item.desc}</div>
            </div>
            <button
              onClick={() => updatePref(item.key, !prefs[item.key])}
              disabled={saving}
              className="relative w-12 h-6 rounded-full transition-all flex-shrink-0"
              style={{
                background: prefs[item.key] ? 'rgba(191,165,93,0.5)' : 'rgba(255,255,255,0.1)',
                border: `1px solid ${prefs[item.key] ? 'rgba(191,165,93,0.6)' : 'rgba(255,255,255,0.15)'}`,
              }}
            >
              <span
                className="absolute top-0.5 w-5 h-5 rounded-full transition-all"
                style={{
                  background: prefs[item.key] ? '#BFA55D' : 'rgba(255,255,255,0.4)',
                  left: prefs[item.key] ? '24px' : '2px',
                }}
              />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
