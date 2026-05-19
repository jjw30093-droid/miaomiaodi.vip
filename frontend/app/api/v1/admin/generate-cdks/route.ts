/**
 * Next.js Route Handler — admin 发卡代理
 *
 * 流程：浏览器 POST 这里 → 校验 NextAuth session 是否 admin →
 *       服务端注入 X-Admin-Token → 转发到 FastAPI /api/v1/admin/generate-cdks
 *
 * 关键安全点：
 *   - process.env.ADMIN_SECRET_TOKEN 仅在 Next.js 服务端可读
 *   - 不带 NEXT_PUBLIC_ 前缀，**不会进客户端 bundle**
 *   - 双层鉴权（session + 内网 token）
 */
import { NextResponse } from 'next/server';
import { auth } from '@/lib/auth';

export const dynamic = 'force-dynamic';

export async function POST(req: Request) {
  // 1) 第一层：必须是已登录 super admin（与 lib/auth.ts 的 SUPER_ADMIN_USER 对齐）
  const session = await auth();
  const adminUser = process.env.SUPER_ADMIN_USER;
  if (
    !adminUser ||
    !session?.user ||
    (session.user as any).name !== adminUser
  ) {
    return NextResponse.json({ detail: '需要管理员登录' }, { status: 401 });
  }

  // 2) 第二层：服务端读 ADMIN_SECRET_TOKEN
  const adminToken = process.env.ADMIN_SECRET_TOKEN;
  if (!adminToken) {
    return NextResponse.json(
      { detail: '服务端未配置 ADMIN_SECRET_TOKEN' },
      { status: 503 },
    );
  }

  let body: any;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: 'invalid JSON body' }, { status: 400 });
  }

  const backendBase = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';

  const upstream = await fetch(`${backendBase}/api/v1/admin/generate-cdks`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Admin-Token': adminToken,
      'X-Forwarded-For': req.headers.get('x-forwarded-for') || '',
      'CF-Connecting-IP': req.headers.get('cf-connecting-ip') || '',
      'User-Agent': req.headers.get('user-agent') || '',
    },
    body: JSON.stringify({
      ...body,
      // 由服务端注入真实 admin 用户名，浏览器不能自填
      admin_username: (session.user as any).name,
    }),
    cache: 'no-store',
  });

  const text = await upstream.text();
  let data: any;
  try {
    data = JSON.parse(text);
  } catch {
    data = { detail: text || 'upstream returned non-JSON' };
  }
  return NextResponse.json(data, { status: upstream.status });
}
