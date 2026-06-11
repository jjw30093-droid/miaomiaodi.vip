'use client';

interface Props {
  profile: any;
  isDark: boolean;
}

const ROLE_DISPLAY: Record<string, string> = {
  admin: '🛡️ 管理员',
  vip: '⭐ VIP 会员',
  user: '普通用户',
  registered: '普通用户',
};

export default function AccountInfoCard({ profile, isDark }: Props) {
  const rows = [
    { label: 'OpenID 尾号', value: profile?.openid_tail || '—', mono: true },
    { label: '注册日期', value: profile?.created_at?.slice(0, 10) || '—', mono: false },
    { label: '当前角色', value: ROLE_DISPLAY[profile?.role] || '普通用户', mono: false },
  ];

  return (
    <div className="flex flex-col gap-3">
      {rows.map(row => (
        <div key={row.label} className="flex items-center justify-between">
          <span className="text-[13px] font-bold uppercase tracking-widest"
            style={{ color: isDark ? 'rgba(255,255,255,0.4)' : '#5b3f43' }}>
            {row.label}
          </span>
          <span className={`text-[15px] font-bold ${row.mono ? 'font-mono' : ''}`}
            style={{ color: isDark ? (row.mono ? '#D4AF37' : '#fff') : (row.mono ? 'var(--primary-neon)' : '#191c1d') }}>
            {row.value}
          </span>
        </div>
      ))}
    </div>
  );
}
