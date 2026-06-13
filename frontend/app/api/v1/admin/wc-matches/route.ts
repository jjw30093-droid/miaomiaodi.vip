/**
 * GET /api/v1/admin/wc-matches — 近 7 天 + 未来 14 天 WC 场次列表（用于授权弹窗）
 */
import { NextResponse } from 'next/server';
import { auth } from '@/lib/auth';

export const dynamic = 'force-dynamic';

async function verifyAdmin(): Promise<string | null> {
  const session = await auth();
  const adminUser = process.env.SUPER_ADMIN_USER;
  if (!adminUser || !session?.user || (session.user as any).name !== adminUser) return null;
  return process.env.ADMIN_SECRET_TOKEN || null;
}

const NO_CACHE = { 'Cache-Control': 'no-store, no-cache' };

export async function GET() {
  const adminToken = await verifyAdmin();
  if (!adminToken) return NextResponse.json({ detail: '需要管理员登录' }, { status: 401, headers: NO_CACHE });

  const base = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
  const upstream = await fetch(`${base}/api/v1/wc/admin/matches`, {
    headers: { 'X-Admin-Token': adminToken },
    cache: 'no-store',
  });
  return NextResponse.json(await upstream.json().catch(() => []), { status: upstream.status, headers: NO_CACHE });
}
