/**
 * Next.js Route Handler — 管理员用户管理代理
 * GET  /api/v1/admin/users       — 列出所有用户
 * POST /api/v1/admin/users       — 创建新用户
 */
import { NextResponse } from 'next/server';
import { auth } from '@/lib/auth';

export const dynamic = 'force-dynamic';

async function verifyAdmin() {
  const session = await auth();
  const adminUser = process.env.SUPER_ADMIN_USER;
  const adminToken = process.env.ADMIN_SECRET_TOKEN;
  const userName = (session?.user as any)?.name ?? null;
  console.log('[Admin] verifyAdmin:', {
    hasSession: !!session,
    userName,
    adminUserSet: !!adminUser,
    adminTokenSet: !!adminToken,
    nameMatch: !!adminUser && userName === adminUser,
  });
  if (!adminUser || !session?.user || userName !== adminUser) {
    return null;
  }
  if (!adminToken) return null;
  return adminToken;
}

export async function GET(req: Request) {
  const adminToken = await verifyAdmin();
  if (!adminToken) return NextResponse.json({ detail: '需要管理员登录' }, { status: 401 });

  const backendBase = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
  const upstream = await fetch(`${backendBase}/api/v1/admin/users`, {
    headers: { 'X-Admin-Token': adminToken },
    cache: 'no-store',
  });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}

export async function POST(req: Request) {
  const adminToken = await verifyAdmin();
  if (!adminToken) return NextResponse.json({ detail: '需要管理员登录' }, { status: 401 });

  const body = await req.json().catch(() => ({}));
  const backendBase = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
  const upstream = await fetch(`${backendBase}/api/v1/admin/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Admin-Token': adminToken },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
