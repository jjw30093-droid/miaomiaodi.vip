/**
 * Next.js Route Handler — 管理员用户操作代理
 * DELETE /api/v1/admin/users/[id]                 — 删除用户
 * POST   /api/v1/admin/users/[id]/reset-password  — 重置密码
 * POST   /api/v1/admin/users/[id]/disable         — 停用/启用
 */
import { NextResponse } from 'next/server';
import { auth } from '@/lib/auth';

export const dynamic = 'force-dynamic';

async function verifyAdmin(): Promise<string | null> {
  const session = await auth();
  const adminUser = process.env.SUPER_ADMIN_USER;
  if (!adminUser || !session?.user || (session.user as any).name !== adminUser) return null;
  const adminToken = process.env.ADMIN_SECRET_TOKEN;
  return adminToken || null;
}

export async function DELETE(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const adminToken = await verifyAdmin();
  if (!adminToken) return NextResponse.json({ detail: '需要管理员登录' }, { status: 401 });

  const backendBase = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
  const upstream = await fetch(`${backendBase}/api/v1/admin/users/${id}`, {
    method: 'DELETE',
    headers: { 'X-Admin-Token': adminToken },
    cache: 'no-store',
  });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const adminToken = await verifyAdmin();
  if (!adminToken) return NextResponse.json({ detail: '需要管理员登录' }, { status: 401 });

  const url = new URL(req.url);
  const action = url.pathname.split('/').pop(); // reset-password or disable
  const body = await req.json().catch(() => ({}));
  const backendBase = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
  const upstream = await fetch(`${backendBase}/api/v1/admin/users/${id}/${action}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Admin-Token': adminToken },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
