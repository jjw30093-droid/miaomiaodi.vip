'use client';

/**
 * WcModelPredictionsCard
 * 世界杯「模型预测对标」卡片
 * 数据来自 wc_cc_predictions（Sportmonks 第三方模型概率）
 * 与市场共识并排展示，标注免责声明
 * 仅在 tournamentType==='wc' 且 wcCcPredictions 非空时渲染
 */

interface PredEntry {
  predictions?: Record<string, number>;
  home?: number | null;
  draw?: number | null;
  away?: number | null;
  over?: number | null;
  under?: number | null;
  btts_yes?: number | null;
  btts_no?: number | null;
}

interface WcCcPredictions {
  fulltime_result?: PredEntry;
  over_under_2_5?: PredEntry;
  both_teams_to_score?: PredEntry;
  [key: string]: any;
}

interface Props {
  wcCcPredictions: WcCcPredictions | null | undefined;
  marketHomeProb: number | null | undefined;  // % 百分制
  marketDrawProb: number | null | undefined;
  marketAwayProb: number | null | undefined;
  marketOuOver?:  number | null | undefined;  // OU over 概率 %
  homeTeam: string;
  awayTeam: string;
  hideWdl?: boolean; // 已有 GlassPickBlock 展示 WDL 对比时去重
}

function pct(v: number | null | undefined): string {
  if (v == null || isNaN(Number(v))) return '—';
  const n = Number(v);
  // Sportmonks 已经是 % 制，market 也是 % 制
  return `${n.toFixed(1)}%`;
}

export default function WcModelPredictionsCard({
  wcCcPredictions,
  marketHomeProb,
  marketDrawProb,
  marketAwayProb,
  marketOuOver,
  homeTeam,
  awayTeam,
  hideWdl = false,
}: Props) {
  if (!wcCcPredictions) return null;

  const ft = wcCcPredictions.fulltime_result;
  const ou = wcCcPredictions.over_under_2_5;
  const btts = wcCcPredictions.both_teams_to_score;

  // 从 predictions sub-dict 取值（Sportmonks 嵌套格式）
  const modelHome = ft?.predictions?.home ?? ft?.home;
  const modelDraw = ft?.predictions?.draw ?? ft?.draw;
  const modelAway = ft?.predictions?.away ?? ft?.away;
  const modelOver  = ou?.predictions?.over ?? ou?.over;
  const modelBtts  = btts?.predictions?.yes ?? btts?.btts_yes;

  // 若全部为 null 则不渲染
  if (modelHome == null && modelDraw == null) return null;

  const rows: { label: string; market: string; model: string }[] = [
    ...(!hideWdl ? [
      { label: `${homeTeam} 主胜`, market: pct(marketHomeProb), model: pct(modelHome) },
      { label: '平局',              market: pct(marketDrawProb), model: pct(modelDraw) },
      { label: `${awayTeam} 客胜`, market: pct(marketAwayProb), model: pct(modelAway) },
    ] : []),
    ...(modelOver != null ? [{ label: '大球 (>2.5)', market: pct(marketOuOver), model: pct(modelOver) }] : []),
    ...(modelBtts != null ? [{ label: '双方进球',    market: '—',               model: pct(modelBtts) }] : []),
  ];

  // hideWdl 模式下若无其他行则不渲染
  if (rows.length === 0) return null;

  return (
    <div className="rounded-xl border border-zinc-700/40 bg-zinc-900/60 p-4 mt-4">
      <h3 className="text-sm font-bold text-zinc-300 mb-3">
        📊 模型预测对标
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-zinc-400">
              <th className="text-left pb-2 pr-4">维度</th>
              <th className="text-right pb-2 pr-4">市场共识（去水）</th>
              <th className="text-right pb-2">算法模型（参考）</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className="border-t border-zinc-800">
                <td className="py-1.5 pr-4 text-zinc-300">{r.label}</td>
                <td className="py-1.5 pr-4 text-right text-[#baff00] font-mono">{r.market}</td>
                <td className="py-1.5 text-right text-zinc-400 font-mono">{r.model}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[10px] text-zinc-500 leading-relaxed">
        ⚠️ 算法模型为 Sportmonks 第三方预测数据，2026 实盘待验证，仅供参考。
        市场共识（去水）为本研报推荐依据。
      </p>
    </div>
  );
}
