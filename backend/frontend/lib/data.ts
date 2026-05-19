import sqlite3 from 'sqlite3';
import { open, Database } from 'sqlite';

/**
 * 1. SQLite 数据库单例模式 (Singleton)
 * 解决 Next.js 开发环境下 HMR 导致 Database is locked 的致命隐患
 */
const globalForSqlite = globalThis as unknown as { db: Database | undefined };

export async function getDb(): Promise<Database> {
  if (globalForSqlite.db) {
    return globalForSqlite.db;
  }

  const db = await open({
    filename: process.env.DB_PATH || '/Users/wanglujun/Desktop/Football_Data_Lake/25-26英超全数据.db',
    driver: sqlite3.Database,
  });

  // 在开发环境下将实例挂载到 globalThis
  if (process.env.NODE_ENV !== 'production') {
    globalForSqlite.db = db;
  }

  return db;
}

/* ── 类型定义 ──────────────────────────────── */

export interface KpiStats {
  win_rate: string;
  roi: string;
  loss_games: string;
  live_matches: string;
}

export interface FixtureData {
  id: string;
  match_time: string;
  home_team: string;
  away_team: string;
  handicap: string;
  ev_value: number;
}

/* ── 数据抓取函数 (RSC Direct) ─────────────── */

/**
 * 2. 获取核心 KPI 指标
 * SQL 方言降级：PostgreSQL -> SQLite (strftime, date('now'))
 */
export async function getKpiStats(): Promise<KpiStats> {
  try {
    const db = await getDb();
    
    // SQLite 聚合查询：计算胜率与亏损场数
    const res = await db.get(`
      SELECT 
        ROUND(SUM(CASE WHEN goals_for > goals_conceded THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) || '%' as win_rate,
        '+31.2%' as roi, /* ROI 核心模型暂留 Mock */
        SUM(CASE WHEN goals_for < goals_conceded THEN 1 ELSE 0 END) || '场' as loss_games,
        (SELECT COUNT(DISTINCT Match_ID) FROM dim_match WHERE date(Date) = date('now')) || '' as live_matches
      FROM int_team_match_flattened
      WHERE team_id IS NOT NULL 
    `);

    if (!res) {
      return { win_rate: '0%', roi: '0%', loss_games: '0场', live_matches: '0' };
    }

    return res as KpiStats;
  } catch (error) {
    console.error('SQLite connection error in getKpiStats:', error);
    return { win_rate: '--%', roi: '--%', loss_games: '--', live_matches: '--' };
  }
}

/**
 * 3. 获取每日赛事池
 * SQL 方言降级：使用 SQLite 的时间处理逻辑
 */
export async function getDailyFixtures(limit = 10): Promise<FixtureData[]> {
  try {
    const db = await getDb();
    
    const rows = await db.all(`
      SELECT 
        CAST(Match_ID AS TEXT) as id,
        '20:00' as match_time, /* SQLite dim_match 仅包含日期，此处 Mock 时间 */
        Home_Team_Name as home_team,
        Away_Team_Name as away_team,
        '0' as handicap,
        0.0 as ev_value
      FROM dim_match
      WHERE date(Date) >= date('now')
      ORDER BY Date ASC
      LIMIT ?
    `, [limit]);

    return rows as FixtureData[];
  } catch (error) {
    console.error('SQLite connection error in getDailyFixtures:', error);
    return [];
  }
}
