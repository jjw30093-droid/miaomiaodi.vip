/**
 * DELETE /api/v1/admin/users/[id]/unlocks/[matchId] — 撤销用户的单场授权
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

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ id: string; matchId: string }> },
) {
  const { id, matchId } = await params;
  const adminToken = await verifyAdmin();
  if (!adminToken) return NextResponse.json({ detail: '需要管理员登录' }, { status: 401 });

  const base = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';
  const upstream = await fetch(`${base}/api/v1/admin/users/${id}/unlocks/${matchId}`, {
    method: 'DELETE',
    headers: { 'X-Admin-Token': adminToken },
    cache: 'no-store',
  });
  return NextResponse.json(await upstream.json().catch(() => ({})), { status: upstream.status, headers: NO_CACHE });
}
