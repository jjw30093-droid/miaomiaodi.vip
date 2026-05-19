#!/usr/bin/env python3
"""
silver_builder.py
=================
Phase 2 Step 3 — Silver 层构建（C + A 阶段）

职责：
  1. 从 dim_match 增量 upsert dim_team（新队 → 插入，已有队 → 更新 last_seen_date）
  2. 从各别名源（team_mapping、JSON 文件）补充别名到 dim_team.aliases
  3. 计算今明两日比赛的队名命中率（Quality Gate 4 指标）
  4. 写 silver_build_log 表，供 pipeline_runner 质量门读取

用法：
  python3 silver_builder.py                  # 正常执行
  python3 silver_builder.py --dry-run        # 只统计，不写库

退出码：
  0 = 成功（即使 resolve_rate < 阈值，步骤本身不失败；让 gate 处理）
  1 = 严重错误（DB 不可访问等）
"""

import os
import sys
import json
import sqlite3
import argparse
import logging
from datetime import datetime, date, timedelta

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "football_uk.db")
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("silver_builder")

# silver_build_log DDL
DDL_LOG = """
CREATE TABLE IF NOT EXISTS silver_build_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_ts          TEXT    NOT NULL,
    teams_total     INTEGER,
    teams_new       INTEGER,
    teams_updated   INTEGER,
    resolve_checked INTEGER,
    resolve_matched INTEGER,
    resolve_rate    REAL,
    status          TEXT,    -- 'OK' | 'WARN' | 'ERROR'
    notes           TEXT
);
"""

RESOLVE_THRESHOLD = 0.90  # 低于此值写 WARN（但 silver_builder 本身不 exit 1）


def ensure_log_table(conn: sqlite3.Connection):
    conn.executescript(DDL_LOG)
    conn.commit()


def upsert_dim_team_from_match(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """
    从 dim_match 增量 upsert dim_team：
      - 新 team_id → INSERT
      - 已有 team_id 且 last_seen_date < 最新日期 → UPDATE last_seen_date
    返回 {'total': int, 'new': int, 'updated': int}
    """
    # 使用 dim_match 中的主客队 ID + 名称 + 联赛 + 最新出现日期
    rows = conn.execute("""
        SELECT
            Home_Team_ID   AS team_id,
            Home_Team_Name AS canonical_name,
            League_ID      AS league_id,
            MAX(Date)      AS last_seen
        FROM dim_match
        WHERE Home_Team_ID IS NOT NULL
        GROUP BY Home_Team_ID
        UNION
        SELECT
            Away_Team_ID,
            Away_Team_Name,
            League_ID,
            MAX(Date)
        FROM dim_match
        WHERE Away_Team_ID IS NOT NULL
        GROUP BY Away_Team_ID
    """).fetchall()

    # league_id → league_code 映射（与 fuzzy_match_odds.py 一致）
    LEAGUE_MAP = {
        47: 'E0', 54: 'D1', 87: 'SP1', 55: 'I1',
        53: 'F1', 223: 'J1', 9080: 'K1', 113: 'A1',
        77: 'UCL', 90: 'UEL',  # 欧冠 / 欧联
    }

    existing = {
        r[0]: r[1]  # team_id → last_seen_date
        for r in conn.execute("SELECT team_id, last_seen_date FROM dim_team").fetchall()
    }

    new_count = 0
    updated_count = 0
    total = len(rows)

    for team_id, canonical_name, league_id, last_seen in rows:
        league_code = LEAGUE_MAP.get(league_id, '')

        if team_id not in existing:
            # 新队 → INSERT
            if not dry_run:
                conn.execute("""
                    INSERT OR IGNORE INTO dim_team
                        (team_id, canonical_name, league, league_id, aliases, last_seen_date)
                    VALUES (?, ?, ?, ?, '[]', ?)
                """, (team_id, canonical_name, league_code, league_id, last_seen))
            new_count += 1
        else:
            # 已有队 → 更新 last_seen_date（若更新）
            old_date = existing.get(team_id) or ''
            if last_seen and last_seen > old_date:
                if not dry_run:
                    conn.execute("""
                        UPDATE dim_team
                        SET last_seen_date = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE team_id = ?
                    """, (last_seen, team_id))
                updated_count += 1

    if not dry_run:
        conn.commit()

    log.info(f"  dim_team upsert: total={total}, new={new_count}, updated={updated_count}")
    return {'total': total, 'new': new_count, 'updated': updated_count}


def refresh_aliases(conn: sqlite3.Connection, dry_run: bool = False):
    """
    调用 db_migrate_phase2.step_seed_dim_team 补充别名
    （幂等：已有别名跳过，只追加新别名）
    dry_run 模式下跳过写操作。
    """
    if dry_run:
        log.info("  [DRY-RUN] 跳过别名刷新")
        return
    try:
        from db_migrate_phase2 import step_seed_dim_team
        step_seed_dim_team(conn)
        log.info("  aliases 刷新完成（via db_migrate_phase2.step_seed_dim_team）")
    except ImportError:
        log.warning("  db_migrate_phase2 未找到，跳过别名刷新")
    except Exception as e:
        log.warning(f"  别名刷新异常（非致命）: {e}")


def calc_resolve_rate(conn: sqlite3.Connection) -> dict:
    """
    计算今明两日比赛（dim_match 中状态为 Fixture/Unknown 的）队名命中率。
    使用 dim_team 的 canonical_name 精确匹配（不调用 fuzzy resolver，保持快速）。
    返回 {'checked': int, 'matched': int, 'rate': float, 'unmatched': list}
    """
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    # 取今明两日 Fixture / Scheduled / 任意未完赛
    matches = conn.execute("""
        SELECT Match_ID, Home_Team_Name, Away_Team_Name
        FROM dim_match
        WHERE Date BETWEEN ? AND ?
          AND (status IS NULL OR status NOT IN ('Finish', 'Cancelled', 'Postponed'))
        LIMIT 200
    """, (today, tomorrow)).fetchall()

    if not matches:
        # 若无 Fixture，也检查今明两天的所有比赛（含 Finish）
        matches = conn.execute("""
            SELECT Match_ID, Home_Team_Name, Away_Team_Name
            FROM dim_match
            WHERE Date BETWEEN ? AND ?
            LIMIT 200
        """, (today, tomorrow)).fetchall()

    if not matches:
        log.info("  今明无赛事，跳过命中率计算")
        return {'checked': 0, 'matched': 0, 'rate': 1.0, 'unmatched': []}

    # 加载 dim_team canonical set + alias set
    canonical_set = {
        r[0] for r in conn.execute("SELECT canonical_name FROM dim_team").fetchall()
    }
    alias_map = {}  # alias_lower → canonical_name
    for r in conn.execute("SELECT canonical_name, aliases FROM dim_team").fetchall():
        cname, aliases_json = r[0], r[1]
        try:
            for a in json.loads(aliases_json or '[]'):
                alias_map[a.lower()] = cname
        except Exception:
            pass

    def is_resolved(name: str) -> bool:
        if not name:
            return False
        if name in canonical_set:
            return True
        if name.lower() in canonical_set:
            return True
        if name.lower() in alias_map:
            return True
        return False

    checked = len(matches) * 2  # 每场两队
    matched = 0
    unmatched = []

    for mid, home, away in matches:
        if is_resolved(home):
            matched += 1
        else:
            unmatched.append(f"[{mid}] HOME: {home}")
        if is_resolved(away):
            matched += 1
        else:
            unmatched.append(f"[{mid}] AWAY: {away}")

    rate = matched / checked if checked > 0 else 1.0
    log.info(f"  命中率: {matched}/{checked} = {rate:.2%}  未命中: {len(unmatched)}")
    if unmatched[:5]:
        for u in unmatched[:5]:
            log.info(f"    ✗ {u}")

    return {'checked': checked, 'matched': matched, 'rate': rate, 'unmatched': unmatched}


def write_log(conn: sqlite3.Connection, upsert_stats: dict, resolve_stats: dict,
              dry_run: bool = False, notes: str = ''):
    rate = resolve_stats.get('rate', 1.0)
    status = 'OK' if rate >= RESOLVE_THRESHOLD else 'WARN'
    if dry_run:
        status = 'DRY-RUN'

    row = (
        datetime.now().isoformat(),
        upsert_stats.get('total', 0),
        upsert_stats.get('new', 0),
        upsert_stats.get('updated', 0),
        resolve_stats.get('checked', 0),
        resolve_stats.get('matched', 0),
        round(rate, 4),
        status,
        notes or (', '.join(resolve_stats.get('unmatched', [])[:10]) or None),
    )
    if not dry_run:
        conn.execute("""
            INSERT INTO silver_build_log
                (run_ts, teams_total, teams_new, teams_updated,
                 resolve_checked, resolve_matched, resolve_rate, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, row)
        conn.commit()

    log.info(f"  silver_build_log: status={status}, resolve_rate={rate:.2%}")
    return status


# ── Phase 2.5: Step E — Silver Odds ───────────────────────────────────────────

ODDS_JSON_PATH = os.path.join(PROJECT_ROOT, "odds", "match_odds_data.json")

DDL_SILVER_MATCH_ODDS = """
CREATE TABLE IF NOT EXISTS silver_match_odds (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id        INTEGER NOT NULL,
    match_date      TEXT,
    home_team_id    INTEGER,
    away_team_id    INTEGER,
    market          TEXT NOT NULL,
    period          TEXT NOT NULL DEFAULT 'opening',
    provider        TEXT DEFAULT 'Bet365',
    raw_home        REAL,
    raw_draw        REAL,
    raw_away        REAL,
    raw_line        REAL,
    fair_home       REAL,
    fair_draw       REAL,
    fair_away       REAL,
    overround       REAL,
    source          TEXT NOT NULL,
    scraped_at      TEXT,
    inserted_at     TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(match_id, market, period, source)
);
CREATE INDEX IF NOT EXISTS idx_smo_match ON silver_match_odds(match_id);
CREATE INDEX IF NOT EXISTS idx_smo_date  ON silver_match_odds(match_date);
"""

DDL_ODDS_SNAPSHOT_LOG = """
CREATE TABLE IF NOT EXISTS odds_snapshot_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id        INTEGER,
    fotmob_id       TEXT,
    match_name      TEXT,
    market          TEXT NOT NULL,
    provider        TEXT,
    raw_home        REAL,
    raw_draw        REAL,
    raw_away        REAL,
    raw_line        REAL,
    snapshot_ts     TEXT NOT NULL,
    inserted_at     TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_osl_fotmob ON odds_snapshot_log(fotmob_id);
CREATE INDEX IF NOT EXISTS idx_osl_match  ON odds_snapshot_log(match_id);
"""


def ensure_odds_tables(conn: sqlite3.Connection):
    conn.executescript(DDL_SILVER_MATCH_ODDS)
    conn.executescript(DDL_ODDS_SNAPSHOT_LOG)
    conn.commit()


def _normalize_3way(h: float, d: float, a: float):
    """归一化 3-way 市场 (1x2)。返回 (fair_h, fair_d, fair_a, overround) 或 None×4。"""
    try:
        h, d, a = float(h), float(d), float(a)
        if h <= 0 or d <= 0 or a <= 0:
            return None, None, None, None
        total_inv = 1/h + 1/d + 1/a
        overround = total_inv - 1.0
        fair_h = (1/h) / total_inv
        fair_d = (1/d) / total_inv
        fair_a = (1/a) / total_inv
        return round(fair_h, 6), round(fair_d, 6), round(fair_a, 6), round(overround, 6)
    except (TypeError, ValueError, ZeroDivisionError):
        return None, None, None, None


def _normalize_2way(h: float, a: float):
    """归一化 2-way 市场 (OU/AH)。返回 (fair_h, fair_a, overround) 或 None×3。"""
    try:
        h, a = float(h), float(a)
        if h <= 0 or a <= 0:
            return None, None, None
        total_inv = 1/h + 1/a
        overround = total_inv - 1.0
        fair_h = (1/h) / total_inv
        fair_a = (1/a) / total_inv
        return round(fair_h, 6), round(fair_a, 6), round(overround, 6)
    except (TypeError, ValueError, ZeroDivisionError):
        return None, None, None


def _safe_float(v):
    """安全转换为 float，失败返回 None。"""
    try:
        if v is None or v == '':
            return None
        return float(v)
    except (ValueError, TypeError):
        return None


def _fd_odds_to_decimal(v):
    """
    football-data.co.uk AH/OU 赔率格式自动检测：
      - 旧格式（water）: v < 1.3 → decimal = 1 + v
      - 新格式（decimal）: v >= 1.3 → 直接使用
    1x2 赔率始终是 decimal，不需要此函数。
    """
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return (1.0 + v) if v < 1.3 else v


def _parse_nowgoal_nested(rec: dict, match_id: int, match_date: str,
                           provider: str, now_ts: str) -> list:
    """
    解析 titan_odds_spider 输出的嵌套 JSON 格式，生成 market_rows。
    格式：rec["odds"] = {"european_1x2": {"initial": {"home":..,"draw":..,"away":..}, "latest":...},
                         "over_under":   {"initial": {"over_or_home":..,"line":..,"under_or_away":..}, "latest":...},
                         "asian_handicap": {...}}
    OU/AH 值为 water 格式（需 +1 转十进制），1x2 已为十进制。
    """
    odds_data = rec.get("odds", {}) if isinstance(rec.get("odds"), dict) else {}
    if not odds_data:
        return []

    market_rows = []

    # 1x2
    eu = odds_data.get("european_1x2", {}) or {}
    for period_key, period_name in [("initial", "opening"), ("latest", "closing")]:
        p = (eu.get(period_key) or {})
        h1 = _safe_float(p.get("home"))
        d1 = _safe_float(p.get("draw"))
        a1 = _safe_float(p.get("away"))
        if h1 and h1 > 1 and d1 and d1 > 1 and a1 and a1 > 1:
            fh, fd, fa, ovr = _normalize_3way(h1, d1, a1)
            market_rows.append(('1x2', period_name, h1, d1, a1, None, fh, fd, fa, ovr,
                                 match_id, match_date, provider, now_ts))

    # OU (water → decimal: +1)
    ou = odds_data.get("over_under", {}) or {}
    for period_key, period_name in [("initial", "opening"), ("latest", "closing")]:
        p = (ou.get(period_key) or {})
        ov_w = _safe_float(p.get("over_or_home"))
        un_w = _safe_float(p.get("under_or_away"))
        ln   = _safe_float(p.get("line"))
        if ov_w is not None and un_w is not None:
            ov_d = 1 + ov_w
            un_d = 1 + un_w
            if ov_d > 1 and un_d > 1:
                fh, fa, ovr = _normalize_2way(ov_d, un_d)
                market_rows.append(('ou', period_name, ov_d, None, un_d, ln,
                                     fh, None, fa, ovr,
                                     match_id, match_date, provider, now_ts))

    # AH (water → decimal: +1)
    ah = odds_data.get("asian_handicap", {}) or {}
    for period_key, period_name in [("initial", "opening"), ("latest", "closing")]:
        p = (ah.get(period_key) or {})
        h_w = _safe_float(p.get("over_or_home"))
        a_w = _safe_float(p.get("under_or_away"))
        ln  = _safe_float(p.get("line"))
        if h_w is not None and a_w is not None:
            h_d = 1 + h_w
            a_d = 1 + a_w
            if h_d > 1 and a_d > 1:
                fh, fa, ovr = _normalize_2way(h_d, a_d)
                market_rows.append(('ah', period_name, h_d, None, a_d, ln,
                                     fh, None, fa, ovr,
                                     match_id, match_date, provider, now_ts))

    return market_rows


def _ingest_nowgoal_odds(conn: sqlite3.Connection) -> int:
    """
    读取 odds/match_odds_data.json → UPSERT silver_match_odds (source='nowgoal')。
    支持 titan_odds_spider 的嵌套 JSON 格式：
      rec.odds.european_1x2 / over_under / asian_handicap（各含 initial/latest）
    每场比赛最多生成 6 行：3 市场 × 2 时段。
    返回写入行数。
    """
    if not os.path.exists(ODDS_JSON_PATH):
        log.warning(f"  NowGoal JSON 不存在: {ODDS_JSON_PATH}")
        return 0

    try:
        with open(ODDS_JSON_PATH, "r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception as e:
        log.warning(f"  读取 NowGoal JSON 失败: {e}")
        return 0

    # dim_match lookup: Match_ID (Fotmob ID) → (match_id, date)
    dim_rows = conn.execute("SELECT Match_ID, Date FROM dim_match").fetchall()
    mid_map = {str(r[0]): (int(r[0]), r[1] or '') for r in dim_rows}

    count = 0
    now_ts = datetime.now().isoformat()

    for rec in records:
        fotmob_id = str(rec.get("fotmob_id", ""))
        if not fotmob_id:
            log.warning(f"[_ingest_nowgoal_odds] 跳过损坏记录（缺 fotmob_id），keys={list(rec.keys())[:4]}")
            continue
        if fotmob_id not in mid_map:
            continue
        match_id, match_date = mid_map[fotmob_id]

        provider = (rec.get("odds") or {}).get("provider", "Bet365") or "Bet365"
        market_rows = _parse_nowgoal_nested(rec, match_id, match_date, provider, now_ts)

        for row in market_rows:
            (market, period, raw_h, raw_d, raw_a, raw_line,
             fair_h, fair_d, fair_a, overround,
             mid, mdate, prov, ts) = row
            try:
                conn.execute("""
                    INSERT INTO silver_match_odds
                        (match_id, match_date, market, period, provider,
                         raw_home, raw_draw, raw_away, raw_line,
                         fair_home, fair_draw, fair_away, overround,
                         source, scraped_at)
                    VALUES (?, ?, ?, ?, ?,
                            ?, ?, ?, ?,
                            ?, ?, ?, ?,
                            'nowgoal', ?)
                    ON CONFLICT(match_id, market, period, source) DO UPDATE SET
                        raw_home=excluded.raw_home, raw_draw=excluded.raw_draw,
                        raw_away=excluded.raw_away, raw_line=excluded.raw_line,
                        fair_home=excluded.fair_home, fair_draw=excluded.fair_draw,
                        fair_away=excluded.fair_away, overround=excluded.overround,
                        scraped_at=excluded.scraped_at
                """, (mid, mdate, market, period, prov,
                      raw_h, raw_d, raw_a, raw_line,
                      fair_h, fair_d, fair_a, overround,
                      ts))
                count += 1
            except Exception as e:
                log.debug(f"    nowgoal upsert 失败 [{mid}/{market}/{period}]: {e}")

    conn.commit()
    log.info(f"  NowGoal: {count} 行 upsert → silver_match_odds")
    return count


def ingest_nowgoal_odds_from_dict(conn: sqlite3.Connection, fotmob_id: str,
                                   odds_data: dict, match_date: str = '') -> int:
    """
    直接从 odds_data dict 写入 silver_match_odds。
    closing_odds_watcher 调用此函数写入闭盘快照，period='closing', source='nowgoal'。
    odds_data 格式同 titan_odds_spider.fetch_single_match_odds() 返回值。
    返回写入行数。
    """
    if not odds_data:
        return 0

    dim_row = conn.execute(
        "SELECT Match_ID, Date FROM dim_match WHERE Match_ID = ?", (fotmob_id,)
    ).fetchone()
    if not dim_row:
        if match_date:
            # dim_match 中没有该场次（常见于当日新增场次尚未同步）。
            # closing_odds_watcher 已传入 match_date，fotmob_id 本身就是 Match_ID，
            # 直接继续写入 silver_match_odds，不阻断闭盘赔率收集。
            log.warning(
                f"  ingest_nowgoal_odds_from_dict: fotmob_id={fotmob_id} 不在 dim_match，"
                f"但已提供 match_date={match_date}，继续写入（dim_match 将在下次同步中补齐）"
            )
            match_id = int(fotmob_id)
        else:
            log.warning(
                f"  ingest_nowgoal_odds_from_dict: fotmob_id={fotmob_id} 不在 dim_match 且无 match_date，跳过"
            )
            return 0
    else:
        match_id = int(dim_row[0])
        if not match_date:
            match_date = dim_row[1] or ''

    provider = odds_data.get("provider", "Bet365") or "Bet365"
    now_ts = datetime.now().isoformat()

    # 构造与 _parse_nowgoal_nested 兼容的包装 rec
    pseudo_rec = {"fotmob_id": fotmob_id, "odds": odds_data}
    market_rows = _parse_nowgoal_nested(pseudo_rec, match_id, match_date, provider, now_ts)

    # 只写 closing 时段（watcher 用途）
    closing_rows = [r for r in market_rows if r[1] == 'closing']
    if not closing_rows:
        # latest 不存在时降级用 opening 作为 closing（T-10min 抓到的即为最新）
        closing_rows = [(r[0], 'closing') + r[2:] for r in market_rows if r[1] == 'opening']

    count = 0
    for row in closing_rows:
        (market, period, raw_h, raw_d, raw_a, raw_line,
         fair_h, fair_d, fair_a, overround,
         mid, mdate, prov, ts) = row
        try:
            conn.execute("""
                INSERT INTO silver_match_odds
                    (match_id, match_date, market, period, provider,
                     raw_home, raw_draw, raw_away, raw_line,
                     fair_home, fair_draw, fair_away, overround,
                     source, scraped_at)
                VALUES (?, ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        'nowgoal', ?)
                ON CONFLICT(match_id, market, period, source) DO UPDATE SET
                    raw_home=excluded.raw_home, raw_draw=excluded.raw_draw,
                    raw_away=excluded.raw_away, raw_line=excluded.raw_line,
                    fair_home=excluded.fair_home, fair_draw=excluded.fair_draw,
                    fair_away=excluded.fair_away, overround=excluded.overround,
                    scraped_at=excluded.scraped_at
            """, (mid, mdate, market, period, prov,
                  raw_h, raw_d, raw_a, raw_line,
                  fair_h, fair_d, fair_a, overround,
                  ts))
            count += 1
        except Exception as e:
            log.debug(f"    ingest_nowgoal_from_dict 失败 [{mid}/{market}/{period}]: {e}")

    conn.commit()
    return count


def backfill_audit_odds_final(conn: sqlite3.Connection, lookback_days: int = 7) -> int:
    """
    Phase 2.5 Step 4: 回填 prediction_audit.odds_final_* 字段。
    从 silver_match_odds 中取 nowgoal closing 1x2 赔率，更新 prediction_audit 中
    尚未填写 odds_final_home 的历史记录。
    返回更新行数。
    """
    cutoff = (datetime.now().date() - timedelta(days=lookback_days)).isoformat()
    try:
        cursor = conn.execute("""
            UPDATE prediction_audit AS pa
            SET odds_final_home = smo.raw_home,
                odds_final_draw = smo.raw_draw,
                odds_final_away = smo.raw_away,
                finalized_at    = datetime('now')
            FROM silver_match_odds smo
            WHERE pa.match_id = CAST(smo.match_id AS TEXT)
              AND smo.market  = '1x2'
              AND smo.period  = 'closing'
              AND smo.source  = 'nowgoal'
              AND pa.odds_final_home IS NULL
              AND pa.match_date >= ?
        """, (cutoff,))
        conn.commit()
        cnt = cursor.rowcount
        log.info(f"  backfill_audit_odds_final: {cnt} 行更新（lookback={lookback_days}天）")
        return cnt
    except Exception as e:
        log.warning(f"  backfill_audit_odds_final 失败（非致命）: {e}")
        return 0


def _ingest_footballdata_odds(conn: sqlite3.Connection) -> int:
    """
    从 raw_footballdata_odds → INSERT OR IGNORE silver_match_odds (source='footballdata')。
    两轮匹配：Pass 1 精确名+日期 JOIN dim_match，Pass 2 team_resolver fuzzy。
    每条记录最多 6 行：2 时段 × 3 市场。
    返回写入行数。
    """
    try:
        total_raw = conn.execute("SELECT COUNT(*) FROM raw_footballdata_odds").fetchone()[0]
    except Exception as e:
        log.warning(f"  raw_footballdata_odds 不存在: {e}")
        return 0

    log.info(f"  footballdata 来源: {total_raw} 行原始数据")

    # 加载 raw_footballdata_odds
    raw_rows = conn.execute("""
        SELECT rowid, "Date", "HomeTeam", "AwayTeam",
               "B365H", "B365D", "B365A",
               "B365CH", "B365CD", "B365CA",
               "B365>2.5", "B365<2.5",
               "B365C>2.5", "B365C<2.5",
               "OULine", "OUCLine",
               "B365AHH", "B365AHA",
               "B365CAHH", "B365CAHA",
               "AHh", "AHCh"
        FROM raw_footballdata_odds
    """).fetchall()

    # Pass 1: 精确名 + 日期 JOIN dim_match
    # 构建 (date, home_lower, away_lower) → match_id 索引
    match_index = {}
    for row in conn.execute("""
        SELECT Match_ID, Date, Home_Team_Name, Away_Team_Name,
               Home_Team_ID, Away_Team_ID
        FROM dim_match
        WHERE Date IS NOT NULL
    """).fetchall():
        mid = row[0] if isinstance(row, tuple) else row['Match_ID']
        dt  = (row[1] if isinstance(row, tuple) else row['Date'] or '')[:10]
        hn  = (row[2] if isinstance(row, tuple) else row['Home_Team_Name'] or '').lower()
        an  = (row[3] if isinstance(row, tuple) else row['Away_Team_Name'] or '').lower()
        htid = row[4] if isinstance(row, tuple) else row['Home_Team_ID']
        atid = row[5] if isinstance(row, tuple) else row['Away_Team_ID']
        match_index[(dt, hn, an)] = (mid, htid, atid)

    # Pass 2: team_resolver fuzzy（可选，import 失败则只用 Pass 1）
    resolver = None
    try:
        from team_resolver import TeamResolver
        resolver = TeamResolver(conn)
    except Exception:
        pass

    count   = 0
    skipped = 0
    now_ts  = datetime.now().isoformat()

    for r in raw_rows:
        if isinstance(r, sqlite3.Row):
            def _col(name):
                try: return r[name]
                except IndexError: return None
        else:
            cols = [
                'rowid','Date','HomeTeam','AwayTeam',
                'B365H','B365D','B365A','B365CH','B365CD','B365CA',
                'B365>2.5','B365<2.5','B365C>2.5','B365C<2.5',
                'OULine','OUCLine',
                'B365AHH','B365AHA','B365CAHH','B365CAHA',
                'AHh','AHCh'
            ]
            _d = dict(zip(cols, r))
            def _col(name): return _d.get(name)

        raw_date = str(_col('Date') or '')[:10]
        home_raw = str(_col('HomeTeam') or '')
        away_raw = str(_col('AwayTeam') or '')

        # Pass 1
        key = (raw_date, home_raw.lower(), away_raw.lower())
        match_info = match_index.get(key)

        # Pass 2: fuzzy（若 Pass 1 未命中）
        if not match_info and resolver:
            try:
                result = resolver.resolve_match(home_raw, away_raw, raw_date)
                if result:
                    match_id_r, htid_r, atid_r = result
                    match_info = (match_id_r, htid_r, atid_r)
            except Exception:
                pass

        if not match_info:
            skipped += 1
            continue

        match_id, htid, atid = match_info

        # 构建各市场各时段行
        market_rows = []

        # 1x2 opening
        h1 = _safe_float(_col('B365H'));  d1 = _safe_float(_col('B365D'));  a1 = _safe_float(_col('B365A'))
        if h1 and d1 and a1:
            fh, fd, fa, ovr = _normalize_3way(h1, d1, a1)
            market_rows.append(('1x2', 'opening', h1, d1, a1, None, fh, fd, fa, ovr))

        # 1x2 closing
        h1c = _safe_float(_col('B365CH')); d1c = _safe_float(_col('B365CD')); a1c = _safe_float(_col('B365CA'))
        if h1c and d1c and a1c:
            fh, fd, fa, ovr = _normalize_3way(h1c, d1c, a1c)
            market_rows.append(('1x2', 'closing', h1c, d1c, a1c, None, fh, fd, fa, ovr))

        # OU opening (旧格式 water 自动转 decimal)
        ov_o = _fd_odds_to_decimal(_safe_float(_col('B365>2.5')))
        un_o = _fd_odds_to_decimal(_safe_float(_col('B365<2.5')))
        ln_o = _safe_float(_col('OULine'))
        if ov_o and un_o and ln_o is not None:              # 强制要求盘口线，防止 raw_line=NULL 污染
            fh, fa, ovr = _normalize_2way(ov_o, un_o)
            market_rows.append(('ou', 'opening', ov_o, None, un_o, ln_o, fh, None, fa, ovr))
        elif ov_o and un_o and ln_o is None:
            log.warning(f"  ⚠️  跳过 OU opening 无盘口线: match_id={match_id} ov={ov_o} un={un_o}")

        # OU closing
        ov_c = _fd_odds_to_decimal(_safe_float(_col('B365C>2.5')))
        un_c = _fd_odds_to_decimal(_safe_float(_col('B365C<2.5')))
        ln_c = _safe_float(_col('OUCLine'))
        if ov_c and un_c and ln_c is not None:              # 强制要求盘口线
            fh, fa, ovr = _normalize_2way(ov_c, un_c)
            market_rows.append(('ou', 'closing', ov_c, None, un_c, ln_c, fh, None, fa, ovr))
        elif ov_c and un_c and ln_c is None:
            log.warning(f"  ⚠️  跳过 OU closing 无盘口线: match_id={match_id} ov={ov_c} un={un_c}")

        # AH opening (旧格式 water 自动转 decimal)
        ah_h = _fd_odds_to_decimal(_safe_float(_col('B365AHH')))
        ah_a = _fd_odds_to_decimal(_safe_float(_col('B365AHA')))
        ah_l = _safe_float(_col('AHh'))
        if ah_h and ah_a and ah_l is not None:              # 强制要求盘口线
            fh, fa, ovr = _normalize_2way(ah_h, ah_a)
            market_rows.append(('ah', 'opening', ah_h, None, ah_a, ah_l, fh, None, fa, ovr))
        elif ah_h and ah_a and ah_l is None:
            log.warning(f"  ⚠️  跳过 AH opening 无盘口线: match_id={match_id} ah_h={ah_h} ah_a={ah_a}")

        # AH closing
        ah_hc = _fd_odds_to_decimal(_safe_float(_col('B365CAHH')))
        ah_ac = _fd_odds_to_decimal(_safe_float(_col('B365CAHA')))
        ah_lc = _safe_float(_col('AHCh'))
        if ah_hc and ah_ac and ah_lc is not None:           # 强制要求盘口线
            fh, fa, ovr = _normalize_2way(ah_hc, ah_ac)
            market_rows.append(('ah', 'closing', ah_hc, None, ah_ac, ah_lc, fh, None, fa, ovr))
        elif ah_hc and ah_ac and ah_lc is None:
            log.warning(f"  ⚠️  跳过 AH closing 无盘口线: match_id={match_id} ah_hc={ah_hc} ah_ac={ah_ac}")

        for (market, period, raw_h, raw_d, raw_a, raw_line,
             fair_h, fair_d, fair_a, overround) in market_rows:
            try:
                conn.execute("""
                    INSERT INTO silver_match_odds
                        (match_id, match_date, home_team_id, away_team_id,
                         market, period, provider,
                         raw_home, raw_draw, raw_away, raw_line,
                         fair_home, fair_draw, fair_away, overround,
                         source, scraped_at)
                    VALUES (?, ?, ?, ?,
                            ?, ?, 'Bet365',
                            ?, ?, ?, ?,
                            ?, ?, ?, ?,
                            'footballdata', ?)
                    ON CONFLICT(match_id, market, period, source) DO UPDATE SET
                        raw_home=excluded.raw_home, raw_draw=excluded.raw_draw,
                        raw_away=excluded.raw_away, raw_line=excluded.raw_line,
                        fair_home=excluded.fair_home, fair_draw=excluded.fair_draw,
                        fair_away=excluded.fair_away, overround=excluded.overround,
                        scraped_at=excluded.scraped_at
                """, (match_id, raw_date, htid, atid,
                      market, period,
                      raw_h, raw_d, raw_a, raw_line,
                      fair_h, fair_d, fair_a, overround,
                      now_ts))
                count += 1
            except Exception as e:
                log.debug(f"    footballdata upsert 失败 [{match_id}/{market}/{period}]: {e}")

    conn.commit()
    log.info(f"  footballdata: {count} 行写入 silver_match_odds，{skipped} 行未匹配 dim_match")
    return count


def _append_snapshot_log(conn: sqlite3.Connection) -> int:
    """
    读取 odds/match_odds_data.json，将每市场 latest 赔率 append 到 odds_snapshot_log。
    返回写入行数。
    """
    if not os.path.exists(ODDS_JSON_PATH):
        log.warning(f"  NowGoal JSON 不存在，跳过 snapshot: {ODDS_JSON_PATH}")
        return 0

    try:
        with open(ODDS_JSON_PATH, "r", encoding="utf-8") as f:
            records = json.load(f)
    except Exception as e:
        log.warning(f"  读取 NowGoal JSON 失败: {e}")
        return 0

    # dim_match.Match_ID IS the Fotmob ID — load valid set for existence check
    valid_match_ids = {
        str(row[0]) for row in conn.execute("SELECT Match_ID FROM dim_match").fetchall()
    }

    def _fotmob_to_mid(fid_str):
        if fid_str in valid_match_ids:
            try:
                return int(fid_str)
            except ValueError:
                return None
        return None

    count    = 0
    snap_ts  = datetime.now().isoformat()

    for rec in records:
        fotmob_id  = str(rec.get("fotmob_id", ""))
        match_id   = _fotmob_to_mid(fotmob_id)
        home_team  = rec.get("home_team", "")
        away_team  = rec.get("away_team", "")
        match_name = f"{home_team} vs {away_team}" if home_team else fotmob_id

        snapshots = []

        # 1x2 latest
        h1 = _safe_float(rec.get("latest_1x2_home"))
        d1 = _safe_float(rec.get("latest_1x2_draw"))
        a1 = _safe_float(rec.get("latest_1x2_away"))
        if h1 and d1 and a1:
            snapshots.append(('1x2', h1, d1, a1, None))

        # OU latest
        ov = _safe_float(rec.get("latest_over"))
        un = _safe_float(rec.get("latest_under"))
        ln = _safe_float(rec.get("latest_ou_line") or rec.get("ou_line"))
        if ov is not None: ov = 1 + ov
        if un is not None: un = 1 + un
        if ov and un:
            snapshots.append(('ou', ov, None, un, ln))

        # AH latest
        ah_h = _safe_float(rec.get("latest_ah_home"))
        ah_a = _safe_float(rec.get("latest_ah_away"))
        ah_l = _safe_float(rec.get("latest_ah_line") or rec.get("ah_line"))
        if ah_h is not None: ah_h = 1 + ah_h
        if ah_a is not None: ah_a = 1 + ah_a
        if ah_h and ah_a:
            snapshots.append(('ah', ah_h, None, ah_a, ah_l))

        for (market, raw_h, raw_d, raw_a, raw_line) in snapshots:
            try:
                conn.execute("""
                    INSERT INTO odds_snapshot_log
                        (match_id, fotmob_id, match_name, market, provider,
                         raw_home, raw_draw, raw_away, raw_line, snapshot_ts)
                    VALUES (?, ?, ?, ?, 'Bet365', ?, ?, ?, ?, ?)
                """, (match_id, fotmob_id, match_name, market,
                      raw_h, raw_d, raw_a, raw_line, snap_ts))
                count += 1
            except Exception as e:
                log.debug(f"    snapshot insert 失败 [{fotmob_id}/{market}]: {e}")

    conn.commit()
    log.info(f"  odds_snapshot_log: {count} 条快照写入")
    return count


def build_silver_odds(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """
    Step E: 构建 silver_match_odds + odds_snapshot_log。
    调用顺序：ensure tables → ingest nowgoal → ingest footballdata → append snapshot。
    返回摘要 dict。
    """
    ensure_odds_tables(conn)

    if dry_run:
        ng_count  = 0
        fd_count  = 0
        snap_count = 0
        log.info("  [DRY-RUN] 跳过 silver odds 写入")
    else:
        log.info("  [E1] 摄取 NowGoal 赔率 → silver_match_odds...")
        ng_count = _ingest_nowgoal_odds(conn)

        log.info("  [E2] footballdata 赔率回填已停用（改用 NowGoal closing odds）")
        fd_count = 0  # DEPRECATED 2026-04-18: footballdata 回填路径已退役

        log.info("  [E3] 追加 odds_snapshot_log...")
        snap_count = _append_snapshot_log(conn)

    total = conn.execute("SELECT COUNT(*) FROM silver_match_odds").fetchone()[0]
    log.info(f"  Step E 完成: nowgoal={ng_count}, footballdata={fd_count}, "
             f"snapshot={snap_count}, silver_match_odds总行数={total}")
    return {
        'nowgoal':     ng_count,
        'footballdata': fd_count,
        'snapshot':    snap_count,
        'total':       total,
    }


def main():
    parser = argparse.ArgumentParser(description="Silver 层构建（Phase 2 Step 3）")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    args = parser.parse_args()

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
    except Exception as e:
        log.error(f"DB 连接失败: {e}")
        sys.exit(1)

    try:
        ensure_log_table(conn)

        log.info("=== Silver Build Step 3 ===")
        log.info(f"  dry_run={args.dry_run}")

        # Step A: upsert dim_team from dim_match
        log.info("[A] 从 dim_match 增量 upsert dim_team...")
        upsert_stats = upsert_dim_team_from_match(conn, dry_run=args.dry_run)

        # Step B: refresh aliases from mapping sources
        log.info("[B] 刷新别名...")
        refresh_aliases(conn, dry_run=args.dry_run)

        # Step C: calculate resolve rate
        log.info("[C] 计算今明赛事命中率...")
        resolve_stats = calc_resolve_rate(conn)

        # Step D: write log
        log.info("[D] 写 silver_build_log...")
        status = write_log(conn, upsert_stats, resolve_stats, dry_run=args.dry_run)

        # Step E: build silver odds
        log.info("[E] 构建 silver_match_odds / odds_snapshot_log...")
        try:
            odds_stats = build_silver_odds(conn, dry_run=args.dry_run)
        except Exception as e:
            log.warning(f"  Step E 失败（非致命，继续）: {e}")
            odds_stats = {}

        # 输出摘要
        rate = resolve_stats['rate']
        print(f"\nsilver_build 完成: teams_new={upsert_stats['new']}, "
              f"teams_updated={upsert_stats['updated']}, "
              f"resolve_rate={rate:.2%}, status={status}, "
              f"odds_ng={odds_stats.get('nowgoal','-')}, "
              f"odds_fd={odds_stats.get('footballdata','-')}")

        if status == 'WARN':
            log.warning(f"  ⚠️ 命中率 {rate:.2%} 低于阈值 {RESOLVE_THRESHOLD:.0%}，"
                        f"请检查 silver_build_log 中 notes 字段")

    except Exception as e:
        log.error(f"silver_builder 执行失败: {e}", exc_info=True)
        conn.close()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
