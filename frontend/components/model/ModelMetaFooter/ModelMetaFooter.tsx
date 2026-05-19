'use client';
import React from 'react';
import type { TrainingMeta, DriftStatus } from '@/lib/modelHealth/types';

interface Props {
  meta: TrainingMeta;
  drift: DriftStatus;
}

export default function ModelMetaFooter({ meta, drift }: Props) {
  const trainedAt = meta.trained_at
    ? new Date(meta.trained_at).toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
    : null;
  const samples = meta.n_samples ?? meta.sample_count ?? null;
  const featuresN = meta.features?.length ?? meta.features_n ?? null;
  const versions = meta.model_versions ?? { wdl: 'v4', ou: 'v4', ah: 'v1' };
  const isAdjusting = drift.status === 'adjusting' && drift.adjusting_days > 0;

  return (
    <div
      className="rounded-2xl border p-4 flex flex-col gap-2"
      style={{ background: 'var(--v2-bg-card)', borderColor: 'var(--v2-border)' }}
    >
      <p
        className="text-xs font-bold uppercase tracking-wider"
        style={{ color: 'var(--v2-text-tertiary)' }}
      >
        模型元信息
      </p>

      <div
        className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm font-semibold font-mono tabular-nums"
        style={{ color: 'var(--v2-text-secondary)' }}
      >
        {trainedAt && <span>训练 {trainedAt}</span>}
        {samples != null && <span>样本 {samples.toLocaleString()} 场</span>}
        {featuresN != null && <span>{featuresN} 维特征</span>}
        <span>
          WDL {versions.wdl ?? 'v4'} · OU {versions.ou ?? 'v4'} · AH {versions.ah ?? 'v1'}
        </span>
      </div>

      {isAdjusting && (
        <p
          className="text-sm font-bold"
          style={{ color: 'var(--v2-accent-warning)' }}
        >
          模型自检中 · 第 {drift.adjusting_days} 天调整
        </p>
      )}
    </div>
  );
}
