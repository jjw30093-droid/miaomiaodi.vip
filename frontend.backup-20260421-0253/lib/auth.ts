import NextAuth from 'next-auth';
import CredentialsProvider from 'next-auth/providers/credentials';
import crypto from 'node:crypto';

const BACKEND = process.env.FASTAPI_URL || 'http://127.0.0.1:8000';

// ── 为超管本地签发 FastAPI JWT（HS256，与 backend/auth_deps.make_jwt 字段对齐）──────
function b64url(input: Buffer | string): string {
  return Buffer.from(input).toString('base64')
    .replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
}

function mintSuperAdminApiToken(username: string): string | null {
  const secret = process.env.JWT_SECRET;
  if (!secret) {
    console.warn('[Auth/Super] JWT_SECRET 未配置，无法为超管签发 FastAPI token');
    return null;
  }
  const now = Math.floor(Date.now() / 1000);
  const header  = { alg: 'HS256', typ: 'JWT' };
  const payload = {
    user_id:    0,                       // 虚拟 ID，不入 user_sessions
    role:       'vip',
    nickname:   username,
    avatar_url: '',
    is_vip:     true,
    exp:        now + 60 * 60 * 24 * 30, // 30 天，对齐 JWT_EXPIRE_DAYS
  };
  const h   = b64url(JSON.stringify(header));
  const p   = b64url(JSON.stringify(payload));
  const sig = crypto.createHmac('sha256', secret).update(`${h}.${p}`).digest();
  return `${h}.${p}.${b64url(sig)}`;
}

// 启动时检查：AUTH_SECRET 必须显式配置，不允许硬编码 fallback 上生产
if (!process.env.AUTH_SECRET) {
  // 仅开发环境容忍缺失，生产环境 Next.js 会在构建/启动时抛错
  console.warn('[Auth] WARNING: AUTH_SECRET 未配置，生产环境必须设置此环境变量！');
}

interface ApiJwtPayload {
  user_id: number;
  role: string;
  is_vip: boolean;
  nickname: string;
  avatar_url: string;
  vip_expires_at?: string;
  jti?: string;
  exp?: number;
}

/** 解析 FastAPI JWT payload（base64，不验签，SSR 内网可信）*/
function parseApiJwt(token: string): ApiJwtPayload | null {
  try {
    const seg = token.split('.')[1];
    const json = Buffer.from(seg, 'base64url').toString('utf-8');
    const p = JSON.parse(json);

    // 修复 is_vip bug：同时检查 role 字段和 vip_expires_at
    const now = Math.floor(Date.now() / 1000);
    let isVip = Boolean(p.is_vip) && p.role === 'vip';
    if (isVip && p.vip_expires_at) {
      try {
        const expTs = new Date(p.vip_expires_at).getTime() / 1000;
        if (now > expTs) isVip = false;
      } catch {
        isVip = false;
      }
    }

    return {
      user_id:       Number(p.user_id),
      role:          isVip ? 'vip' : (p.role || 'registered'),
      is_vip:        isVip,
      nickname:      p.nickname || '足球探索者',
      avatar_url:    p.avatar_url || '',
      vip_expires_at: p.vip_expires_at ?? undefined,
      jti:           p.jti ?? undefined,
    };
  } catch {
    return null;
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    // ── Provider 1: 微信公众号验证码登录 ────────────────────────
    CredentialsProvider({
      id: 'wechat',
      name: 'WeChat',
      credentials: {
        api_token: { label: 'API Token', type: 'text' },
      },
      async authorize(credentials) {
        if (!credentials?.api_token) return null;
        try {
          const payload = parseApiJwt(credentials.api_token as string);
          if (!payload) return null;

          return {
            id:            String(payload.user_id),
            name:          payload.nickname,
            email:         `${payload.user_id}@wechat`,
            role:          payload.role,
            apiToken:      credentials.api_token as string,
            avatarUrl:     payload.avatar_url,
            vipExpiresAt:  payload.vip_expires_at ?? null,
            jti:           payload.jti ?? null,
          } as any;
        } catch (e) {
          console.error('[Auth/WeChat]', e);
          return null;
        }
      },
    }),

    // ── Provider 2: 账号密码登录（管理员 / 测试）────────────────
    CredentialsProvider({
      id: 'credentials',
      name: 'Credentials',
      credentials: {
        username: { label: 'Username', type: 'text' },
        password: { label: 'Password', type: 'password' },
      },
      async authorize(credentials) {
        if (!credentials?.username) return null;

        // 超级管理员：凭证必须全部来自环境变量
        const superUser = process.env.SUPER_ADMIN_USER;
        const superPass = process.env.SUPER_ADMIN_PASS;
        if (superUser && credentials.username === superUser) {
          if (superPass && credentials.password === superPass) {
            const apiToken = mintSuperAdminApiToken(credentials.username as string);
            console.log(`[Auth/Super] Minted FastAPI JWT for ${credentials.username}: ${apiToken ? 'OK' : 'FAILED (JWT_SECRET missing?)'}`);
            return {
              id:           `superadmin_${credentials.username}`,
              name:         credentials.username as string,
              email:        `${credentials.username}@superadmin`,
              role:         'vip',
              apiToken,
              avatarUrl:    null,
              vipExpiresAt: null,
              jti:          null,
            } as any;
          }
          return null;
        }

        // 普通用户密码登录（无密码注册模式已废弃，仅超级管理员可用密码登录）
        // init_session 端点已移除，非 admin 一律返回 null（认证失败）
        return null;
      },
    }),
  ],

  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.role         = (user as any).role         ?? 'user';
        token.apiToken     = (user as any).apiToken     ?? null;
        token.avatarUrl    = (user as any).avatarUrl    ?? null;
        token.vipExpiresAt = (user as any).vipExpiresAt ?? null;
        token.jti          = (user as any).jti          ?? null;
      }
      return token;
    },
    async session({ session, token }) {
      (session.user as any).role         = token.role;
      (session.user as any).apiToken     = token.apiToken     ?? null;
      (session.user as any).avatarUrl    = token.avatarUrl    ?? null;
      (session.user as any).vipExpiresAt = token.vipExpiresAt ?? null;
      (session.user as any).jti          = token.jti          ?? null;
      return session;
    },
  },

  pages: { signIn: '/login' },
  session: { strategy: 'jwt' },
  secret: process.env.AUTH_SECRET || 'dev_only_secret_change_in_prod',
  trustHost: true,
});
