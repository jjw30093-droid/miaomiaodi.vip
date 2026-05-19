"use client";
import dynamic from 'next/dynamic';
import { TeamShotHistory } from '@/types/report';

const InteractiveShotMap = dynamic(
  () => import('@/components/InteractiveShotMap'),
  { ssr: false, loading: () => (
    <div className="py-16 flex items-center justify-center opacity-30">
      <div className="w-6 h-6 border-2 border-primary-neon/40 border-t-primary-neon rounded-full animate-spin" />
    </div>
  )}
);

interface Props {
  homeTeam: TeamShotHistory;
  awayTeam: TeamShotHistory;
  homeTeamName: string;
  awayTeamName: string;
}

export default function InteractiveShotMapClient(props: Props) {
  return <InteractiveShotMap {...props} />;
}
