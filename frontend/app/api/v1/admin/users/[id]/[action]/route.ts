/**
 * Next.js Route Handler — 管理员用户子操作代理
 * POST /api/v1/admin/users/[id]/reset-password
 * POST /api/v1/admin/users/[id]/disable
 */
import { NextResponse } from 'next/server';
import { auth } from '@/lib/auth';

export const dynamic = 'force-dynamic';

const NO_CACHE = { 'Cache-Control': 'no-store, no-cache' };

export async function POST(
  req: Request,
  { params }: { params: Promise<{ id: string; action: string }> }
) {
  const session = await auth();
  const adminUser = process.env.SUPER_ADMIN_USER;
  if (!adminUser || !session?.user || (session.user as any).name !== adminUser) {
    return NextResponse.json({ detail: '需要管理员登录' }, { status: 401, headers: NO_CACHE });
  }
  const adminToken = process.env.ADMIN_SECRET_TOKEN;
  if (!adminToken) {
    return NextResponse.json({ detail: '服务端未配置 ADMIN_SECRET_TOKEN' }, { status: 503, headers: NO_CACHE });
  }

  const { id, action } = await params;
  const body = await req.json().catch(() => ({}));
  const backendBase = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
  const upstream = await fetch(`${backendBase}/api/v1/admin/users/${id}/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Admin-Token': adminToken },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status, headers: NO_CACHE });
}
