/**
 * GET  /api/v1/admin/users/[id]/unlocks — 查询用户的单场授权列表
 * POST /api/v1/admin/users/[id]/unlocks — 给用户授权某场研报
 */
import { NextResponse } from 'next/server';
import { auth } from '@/lib/auth';

export const dynamic = 'force-dynamic';

const NO_CACHE = { 'Cache-Control': 'no-store, no-cache' };

async function verifyAdmin(): Promise<string | null> {
  const session = await auth();
  const adminUser = process.env.SUPER_ADMIN_USER;
  if (!adminUser || !session?.user || (session.user as any).name !== adminUser) return null;
  return process.env.ADMIN_SECRET_TOKEN || null;
}

export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const adminToken = await verifyAdmin();
  console.log('[unlocks GET] adminToken length:', adminToken?.length, 'first4:', adminToken?.slice(0,4));
  if (!adminToken) return NextResponse.json({ detail: '需要管理员登录' }, { status: 401, headers: NO_CACHE });

  const base = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
  const upstream = await fetch(`${base}/api/v1/admin/users/${id}/unlocks`, {
    headers: { 'X-Admin-Token': adminToken },
    cache: 'no-store',
  });
  return NextResponse.json(await upstream.json().catch(() => []), { status: upstream.status, headers: NO_CACHE });
}

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const adminToken = await verifyAdmin();
  if (!adminToken) return NextResponse.json({ detail: '需要管理员登录' }, { status: 401, headers: NO_CACHE });

  const body = await req.json().catch(() => ({}));
  const base = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
  const upstream = await fetch(`${base}/api/v1/admin/users/${id}/unlocks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Admin-Token': adminToken },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  return NextResponse.json(await upstream.json().catch(() => ({})), { status: upstream.status, headers: NO_CACHE });
}
