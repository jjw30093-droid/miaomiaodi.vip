import type { ModelSnapshotV2 } from './types';

const BASE = process.env.NEXT_PUBLIC_API_URL || '/api/v1';

export async function fetchSnapshot(token: string, date = 'latest'): Promise<ModelSnapshotV2> {
  const res = await fetch(`${BASE}/model/snapshot?date=${encodeURIComponent(date)}`, {
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}
