/**
 * 足球数据业务模型定义 (Data Binding)
 * 对齐 Python FastAPI 后端: /api/v1/market, /api/v1/quant, /api/v1/report
 */

export interface MarketData {
  match_id: string;
  handicap: string;      // spread line (e.g., -0.5)
  odds: number;          // decimal odds
  oi_flow?: number;      // 资金流向 (可选)
  roi?: number[];        // 历史收益走势 (用于 Dashboard)
}

export interface WinRate {
  won: number;
  lost: number;
}

export interface QuantData {
  match_id: string;
  winRate: WinRate;
  ev: number;            // 期望价值 (Expected Value)
  npxGD_diff?: number;   // 非点球期望净胜球差
  golden_zone_penetration?: number; // 黄金区穿透力
}

export interface ReportData {
  match_id: string;
  title: string;
  publish_date: string;
  author: string;
  markdown_content: string; // 核心研报正文
  is_premium: boolean;      // 是否为付费研报
}

export interface MatchSummary {
  id: string;
  homeName: string;
  awayName: string;
  time: string;
  handicap: string;
  ev: number;
  hasReport: boolean;
}
