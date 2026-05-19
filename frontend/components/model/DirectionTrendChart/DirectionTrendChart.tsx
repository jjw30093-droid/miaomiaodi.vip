'use client';
import React from 'react';
import type { DirectionTrend } from '@/lib/modelHealth/types';
import RollingAccuracyChart from '../RollingAccuracyChart';

interface Props {
  data: DirectionTrend;
}

export default function DirectionTrendChart({ data }: Props) {
  const currentHidden = {
    wdl: data.current.wdl.hidden,
    ou:  data.current.ou.hidden,
    ah:  data.current.ah.hidden,
  };

  return <RollingAccuracyChart data={data} currentHidden={currentHidden} />;
}
