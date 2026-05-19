"""
db_migrate_phase2.py
====================
Phase 2 幂等迁移脚本。不触碰现有 db_migrate.py。

Steps (可单独执行，也可 --apply 全部运行):
  1. create-tables      建 dim_team、silver_build_log
  2. alter-audit        prediction_audit 加 5 列 (幂等)
  3. seed-dim-team      合并 4 个源 → dim_team
  4. backfill-ou-line   用 regex 扫 reports/*.md 回填 pred_ou_line
  5. recompute-audit    对已 audit 行用新 line 重算 actual_ou / ou_correct / brier_ou
  6. create-odds-tables 建 silver_match_odds、odds_snapshot_log (Phase 2.5)
  7. backfill-silver-odds 从 raw_footballdata_odds 回填 silver_match_odds (Phase 2.5)

用法:
    python3 db_migrate_phase2.py --dry-run          # 打印 SQL 不执行
    python3 db_migrate_phase2.py --step create-tables
    python3 db_migrate_phase2.py --step alter-audit
    python3 db_migrate_phase2.py --step seed-dim-team
    python3 db_migrate_phase2.py --step backfill-ou-line
    python3 db_migrate_phase2.py --step recompute-audit
    python3 db_migrate_phase2.py --step create-odds-tables
    python3 db_migrate_phase2.py --step backfill-silver-odds
    python3 db_migrate_phase2.py --apply             # 依次运行全部 7 步
    python3 db_migrate_phase2.py --verify            # 只读：输出 coverage 报告
"""

import os
import re
import sys
import json
import glob
import argparse
import sqlite3
import logging
from datetime import datetime

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(PROJECT_ROOT, "football_uk.db")
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")

LEAGUE_MAP = {
    47:   'E0',
    54:   'D1',
    87:   'SP1',
    55:   'I1',
    53:   'F1',
    223:  'J1',
    9080: 'K1',
    113:  'A1',
    572:  'UCL',  # UEFA Champions League
    73:   'EL',   # UEFA Europa League
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

DRY_RUN = False


def execute(conn: sqlite3.Connection, sql: str, params=(), description: str = ""):
    if DRY_RUN:
        log.info(f"[DRY-RUN] {description or sql[:80]}")
        return
    conn.execute(sql, params)


# ── Step 1: create-tables ─────────────────────────────────────────────────────

DDL_DIM_TEAM = """
CREATE TABLE IF NOT EXISTS dim_team (
    team_id          INTEGER PRIMARY KEY,
    canonical_name   TEXT    NOT NULL,
    name_cn          TEXT,
    aliases          TEXT    NOT NULL DEFAULT '[]',
    league           TEXT,
    league_id        INTEGER,
    country          TEXT,
    last_seen_date   TEXT,
    created_at       TEXT    DEFAULT CURRENT_TIMESTAMP,
    updated_at       TEXT    DEFAULT CURRENT_TIMESTAMP
);
"""

DDL_DIM_TEAM_IDX = [
    "CREATE INDEX IF NOT EXISTS idx_dim_team_canonical ON dim_team(canonical_name);",
    "CREATE INDEX IF NOT EXISTS idx_dim_team_league    ON dim_team(league_id);",
]

DDL_SILVER_BUILD_LOG = """
CREATE TABLE IF NOT EXISTS silver_build_log (
    run_ts           TEXT PRIMARY KEY,
    step             TEXT,
    teams_total      INT,
    teams_new        INT,
    resolve_rate     REAL,
    status           TEXT,
    notes            TEXT
);
"""

# ── Phase 2.5: Odds DDL ────────────────────────────────────────────────────────

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
CREATE INDEX IF NOT EXISTS idx_smo_match  ON silver_match_odds(match_id);
CREATE INDEX IF NOT EXISTS idx_smo_date   ON silver_match_odds(match_date);
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


def step_create_tables(conn: sqlite3.Connection):
    log.info("─── Step 1: create-tables ───")
    if not DRY_RUN:
        conn.executescript(DDL_DIM_TEAM + DDL_SILVER_BUILD_LOG)
        for idx in DDL_DIM_TEAM_IDX:
            conn.execute(idx)
        conn.commit()
        log.info("  ✅ dim_team, silver_build_log 创建/已存在")
    else:
        log.info(f"[DRY-RUN] CREATE TABLE dim_team, silver_build_log, indexes")


# ── Step 2: alter-audit ───────────────────────────────────────────────────────

NEW_COLUMNS = [
    ("pred_ou_line",        "REAL",   "大小球线（如 3.5）"),
    ("pred_ah_pick",        "TEXT",   "亚盘方向 home|away"),
    ("pred_ah_line",        "REAL",   "亚盘让球"),
    ("prob_sanity_flag",    "TEXT",   "NULL|EXTREME"),
    ("actual_ou_line_used", "REAL",   "审计时实际用的 line"),
]


def step_alter_audit(conn: sqlite3.Connection):
    log.info("─── Step 2: alter-audit ───")
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(prediction_audit)").fetchall()}
    for col_name, col_type, comment in NEW_COLUMNS:
        if col_name in existing_cols:
            log.info(f"  ⏭️  列 {col_name} 已存在，跳过")
            continue
        sql = f"ALTER TABLE prediction_audit ADD COLUMN {col_name} {col_type};"
        if not DRY_RUN:
            try:
                conn.execute(sql)
                conn.commit()
                log.info(f"  ✅ 已添加列: {col_name} {col_type}  -- {comment}")
            except Exception as e:
                log.warning(f"  ⚠️  添加列 {col_name} 失败: {e}")
        else:
            log.info(f"[DRY-RUN] {sql}  -- {comment}")


# ── Step 3: seed-dim-team ─────────────────────────────────────────────────────

def _upsert_team(conn, team_id, canonical_name, league_id, aliases_to_add: list):
    """插入或合并 dim_team 记录，返回是否是新行"""
    existing = conn.execute(
        "SELECT aliases FROM dim_team WHERE team_id=?", (team_id,)
    ).fetchone()
    league = LEAGUE_MAP.get(league_id, str(league_id) if league_id else None)

    if not existing:
        conn.execute(
            """INSERT INTO dim_team (team_id, canonical_name, league, league_id, aliases, last_seen_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (team_id, canonical_name, league, league_id,
             json.dumps(aliases_to_add, ensure_ascii=False),
             datetime.now().strftime('%Y-%m-%d'))
        )
        return True
    else:
        # 合并 aliases（去重）
        old_aliases = json.loads(existing[0] or '[]')
        merged = list(dict.fromkeys(old_aliases + aliases_to_add))  # 保序去重
        conn.execute(
            "UPDATE dim_team SET aliases=?, updated_at=CURRENT_TIMESTAMP WHERE team_id=?",
            (json.dumps(merged, ensure_ascii=False), team_id)
        )
        return False


def step_seed_dim_team(conn: sqlite3.Connection):
    log.info("─── Step 3: seed-dim-team ───")
    if DRY_RUN:
        log.info("[DRY-RUN] seed dim_team from dim_match + 4 alias sources")
        return

    # 1. 从 dim_match 获取所有球队 (home + away)
    rows = conn.execute("""
        SELECT Home_Team_ID, Home_Team_Name, League_ID FROM dim_match
        UNION
        SELECT Away_Team_ID, Away_Team_Name, League_ID FROM dim_match
    """).fetchall()

    new_count = 0
    total_count = 0
    for team_id, canonical_name, league_id in rows:
        if not team_id or not canonical_name:
            continue
        total_count += 1
        is_new = _upsert_team(conn, team_id, canonical_name, league_id, [])
        if is_new:
            new_count += 1

    conn.commit()
    log.info(f"  从 dim_match 加载: {total_count} 条记录，新增 {new_count} 行")

    # 2. team_mapping 表 (footballdata_name → standard_name/FotMob canonical)
    #    footballdata_name 作为 alias 追加到对应 canonical 的 dim_team 行
    alias_count = 0
    mapping_rows = conn.execute("SELECT footballdata_name, standard_name FROM team_mapping").fetchall()
    for fd_name, canonical in mapping_rows:
        if not fd_name or not canonical:
            continue
        # 找 canonical 对应的 team_id
        entry = conn.execute(
            "SELECT team_id FROM dim_team WHERE canonical_name=?", (canonical,)
        ).fetchone()
        if entry:
            old = json.loads(conn.execute(
                "SELECT aliases FROM dim_team WHERE team_id=?", (entry[0],)
            ).fetchone()[0] or '[]')
            if fd_name not in old:
                merged = old + [fd_name]
                conn.execute(
                    "UPDATE dim_team SET aliases=?, updated_at=CURRENT_TIMESTAMP WHERE team_id=?",
                    (json.dumps(merged, ensure_ascii=False), entry[0])
                )
                alias_count += 1
    conn.commit()
    log.info(f"  从 team_mapping 表 追加 {alias_count} 条别名")

    # 3. team_mapping.json  {raw_name: canonical_name}
    json_path = os.path.join(PROJECT_ROOT, "team_mapping.json")
    alias_count2 = 0
    if os.path.exists(json_path):
        with open(json_path, encoding='utf-8') as f:
            jmap = json.load(f)
        for raw_name, canonical in jmap.items():
            entry = conn.execute(
                "SELECT team_id, aliases FROM dim_team WHERE canonical_name=?", (canonical,)
            ).fetchone()
            if entry:
                old = json.loads(entry[1] or '[]')
                if raw_name not in old:
                    merged = old + [raw_name]
                    conn.execute(
                        "UPDATE dim_team SET aliases=?, updated_at=CURRENT_TIMESTAMP WHERE team_id=?",
                        (json.dumps(merged, ensure_ascii=False), entry[0])
                    )
                    alias_count2 += 1
        conn.commit()
        log.info(f"  从 team_mapping.json 追加 {alias_count2} 条别名")

    # 4. team_name_mappings.json  {"E0|TeamName": canonical}
    json_path2 = os.path.join(PROJECT_ROOT, "team_name_mappings.json")
    alias_count3 = 0
    if os.path.exists(json_path2):
        with open(json_path2, encoding='utf-8') as f:
            jmap2 = json.load(f)
        for key, canonical in jmap2.items():
            # key 格式: "E0|Tottenham" 或直接 "Tottenham"
            raw_name = key.split('|', 1)[-1] if '|' in key else key
            entry = conn.execute(
                "SELECT team_id, aliases FROM dim_team WHERE canonical_name=?", (canonical,)
            ).fetchone()
            if entry:
                old = json.loads(entry[1] or '[]')
                if raw_name not in old:
                    merged = old + [raw_name]
                    conn.execute(
                        "UPDATE dim_team SET aliases=?, updated_at=CURRENT_TIMESTAMP WHERE team_id=?",
                        (json.dumps(merged, ensure_ascii=False), entry[0])
                    )
                    alias_count3 += 1
        conn.commit()
        log.info(f"  从 team_name_mappings.json 追加 {alias_count3} 条别名")

    # 5. fuzzy_match_odds.py 中的 TEAM_ALIASES dict 硬编码别名
    HARD_ALIASES = {
        'Wolverhampton Wanderers': ['Wolves'],
        'Nottingham Forest':       ["Nott'm Forest"],
        'Manchester United':       ['Man United', 'Man Utd'],
        'Manchester City':         ['Man City'],
        'Sheffield United':        ['Sheffield Utd'],
        'Luton Town':              ['Luton'],
        'Ipswich Town':            ['Ipswich'],
        'Leicester City':          ['Leicester'],
        'Brighton & Hove Albion':  ['Brighton'],
        'Tottenham Hotspur':       ['Tottenham'],
        'Atletico Madrid':         ['Athletico Madrid', 'Ath Madrid'],
        'Athletic Club':           ['Athletico Club', 'Ath Bilbao'],
        'Real Sociedad':           ['Sociedad'],
        'Celta Vigo':              ['Celta'],
        'Rayo Vallecano':          ['Vallecano'],
        'Deportivo Alaves':        ['Alaves'],
        'Espanyol':                ['Espanol'],
        'Real Valladolid':         ['Valladolid'],
        'Real Oviedo':             ['Oviedo'],
        'Real Betis':              ['Betis'],
        'Paris Saint-Germain':     ['Paris SG', 'Paris FC'],
        'Bayern München':          ['Bayern Munich', 'Bayern'],
        "Borussia M'gladbach":     ["M'gladbach", 'Borussia MG'],
        'Eintracht Frankfurt':     ['Ein Frankfurt'],
        'Mainz 05':                ['Mainz'],
        'TSG Hoffenheim':          ['Hoffenheim'],
        'Leipzig':                 ['RB Leipzig'],
        '1. FC Köln':              ['FC Koln'],
        'Bayer Leverkusen':        ['Leverkusen'],
        'Sanfrecce Hiroshima':     ['Hiroshima Sanfrecce'],
        'Yokohama F.Marinos':      ['Yokohama Marinos'],
        'Urawa Red Diamonds':      ['Urawa Reds'],
        'Gamba Osaka':             ['Gamba'],
        'Cerezo Osaka':            ['Cerezo'],
        'F.C. Tokyo':              ['FC Tokyo'],
    }
    alias_count4 = 0
    for canonical, alias_list in HARD_ALIASES.items():
        entry = conn.execute(
            "SELECT team_id, aliases FROM dim_team WHERE canonical_name=?", (canonical,)
        ).fetchone()
        if entry:
            old = json.loads(entry[1] or '[]')
            added = [a for a in alias_list if a not in old]
            if added:
                merged = old + added
                conn.execute(
                    "UPDATE dim_team SET aliases=?, updated_at=CURRENT_TIMESTAMP WHERE team_id=?",
                    (json.dumps(merged, ensure_ascii=False), entry[0])
                )
                alias_count4 += len(added)
    conn.commit()
    log.info(f"  从硬编码 HARD_ALIASES 追加 {alias_count4} 条别名")

    # 汇总
    total = conn.execute("SELECT COUNT(*) FROM dim_team").fetchone()[0]
    with_aliases = conn.execute("SELECT COUNT(*) FROM dim_team WHERE aliases != '[]'").fetchone()[0]
    log.info(f"  ✅ dim_team 合计 {total} 行，{with_aliases} 行有别名")


# ── Step 4: backfill-ou-line ─────────────────────────────────────────────────

OU_LINE_RE  = re.compile(
    r'大小球[（(]([\d.]+)[）)]'          # 格式1: 大小球（3.5）
    r'|大小球[盘口]*[^，。\n]{0,8}在\s*([\d.]+)\s*球'  # 格式2: 大小球盘口稳定在 2.25 球
    r'|大(?:小球)?\s*([\d.]+)\s*球'      # 格式3: 大3.5球 / 大 3.5 球
    r'|[Oo][Uu]\s*line[：:=\s]*([\d.]+)'  # 格式4: OU line: 2.5
)
AH_LINE_RE  = re.compile(
    r'亚盘[（(]([-\d./]+)[）)]'          # 格式1: 亚盘（-0.25）
    r'|亚盘[^，。\n]{0,10}让\s*([-\d./]+)\s*球'  # 格式2: 亚盘主让 0.25 球
)
MATCH_ID_RE = re.compile(r'report_\d{4}-\d{2}-\d{2}_(\d+)\.md$')


def _parse_ah_line(raw: str) -> float | None:
    """解析亚盘让球字符串，如 '-0.25', '0.5/1', '-0.75' → float 取中值"""
    if not raw:
        return None
    try:
        if '/' in raw:
            parts = raw.split('/')
            return sum(float(p) for p in parts) / len(parts)
        return float(raw)
    except (ValueError, TypeError):
        return None


def step_backfill_ou_line(conn: sqlite3.Connection):
    log.info("─── Step 4: backfill-ou-line ───")
    if not os.path.exists(REPORTS_DIR):
        log.warning(f"  ⚠️ 找不到 reports 目录: {REPORTS_DIR}")
        return

    report_files = glob.glob(os.path.join(REPORTS_DIR, "report_*_*.md"))
    log.info(f"  扫描 {len(report_files)} 个带 match_id 的研报文件...")

    # 检查列是否存在（干跑模式下 ALTER TABLE 尚未执行）
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(prediction_audit)").fetchall()}
    col_exists = 'pred_ou_line' in existing_cols

    updated = 0
    skipped_no_match = 0
    skipped_no_line  = 0

    for fpath in sorted(report_files):
        fname = os.path.basename(fpath)
        m = MATCH_ID_RE.search(fname)
        if not m:
            continue
        match_id = m.group(1)

        # 只回填尚未有 pred_ou_line 的行
        if col_exists:
            row = conn.execute(
                "SELECT pred_ou_line FROM prediction_audit WHERE match_id=?", (match_id,)
            ).fetchone()
        else:
            # 干跑模式：列还不存在，只检查行是否存在
            row = conn.execute(
                "SELECT match_id FROM prediction_audit WHERE match_id=?", (match_id,)
            ).fetchone()
            row = (None,) if row else None  # 伪装成 (pred_ou_line=None,)
        if not row:
            skipped_no_match += 1
            continue
        if row[0] is not None:  # 已有值，跳过
            continue

        try:
            with open(fpath, encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            log.warning(f"  ⚠️ 读取 {fname} 失败: {e}")
            continue

        ou_m = OU_LINE_RE.search(content)
        if not ou_m:
            skipped_no_line += 1
            continue
        # 取第一个非 None 的捕获组
        ou_line_str = next((g for g in ou_m.groups() if g is not None), None)
        if not ou_line_str:
            skipped_no_line += 1
            continue
        ou_line = float(ou_line_str)

        ah_m = AH_LINE_RE.search(content)
        ah_line_str = next((g for g in ah_m.groups() if g is not None), None) if ah_m else None
        ah_line = _parse_ah_line(ah_line_str) if ah_line_str else None

        if DRY_RUN:
            log.info(f"[DRY-RUN] UPDATE prediction_audit SET pred_ou_line={ou_line} WHERE match_id={match_id}")
            updated += 1
            continue

        conn.execute(
            "UPDATE prediction_audit SET pred_ou_line=?, pred_ah_line=? WHERE match_id=?",
            (ou_line, ah_line, match_id)
        )
        updated += 1
        log.info(f"  ✅ {fname}: ou_line={ou_line}" + (f", ah_line={ah_line}" if ah_line else ""))

    if not DRY_RUN:
        conn.commit()
    log.info(f"  回填完成: 更新 {updated} 行 | 无 audit 记录 {skipped_no_match} 个 | 研报未含线值 {skipped_no_line} 个")


# ── Step 5: recompute-audit ───────────────────────────────────────────────────

def step_recompute_audit(conn: sqlite3.Connection):
    """
    对所有已审计行（actual_wdl IS NOT NULL）用新的 pred_ou_line 重算
    actual_ou / ou_correct / brier_ou / actual_ou_line_used。
    幂等：如果 actual_ou_line_used = pred_ou_line 则跳过（无需重算）。
    """
    log.info("─── Step 5: recompute-audit ───")

    # 检查新列是否存在（干跑模式下可能还没 ALTER）
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(prediction_audit)").fetchall()}
    if 'pred_ou_line' not in existing_cols:
        if DRY_RUN:
            log.info("[DRY-RUN] pred_ou_line 列尚未存在（需先 --step alter-audit），跳过重算预演")
            return
        else:
            log.warning("  ⚠️ pred_ou_line 列不存在，请先运行 --step alter-audit")
            return

    rows = conn.execute("""
        SELECT match_id, pred_wdl_pick, pred_ou_pick, pred_ou_over,
               pred_wdl_home, pred_wdl_draw, pred_wdl_away,
               actual_home_score, actual_away_score, actual_wdl,
               pred_ou_line, actual_ou_line_used
        FROM prediction_audit
        WHERE actual_wdl IS NOT NULL
    """).fetchall()

    recomputed = 0
    skipped    = 0

    for r in rows:
        mid = r[0]
        hs  = r[7]
        as_ = r[8]
        if hs is None or as_ is None:
            continue

        stored_line = r[10]
        used_line   = stored_line if stored_line is not None else 2.5
        old_used    = r[11]

        # 幂等检查：如果已经用正确的 line 算过，跳过
        if old_used is not None and abs(old_used - used_line) < 0.001:
            skipped += 1
            continue

        total = hs + as_
        if total > used_line:
            actual_ou = 'over'
        elif total < used_line:
            actual_ou = 'under'
        else:
            actual_ou = 'push'

        ou_correct = None if actual_ou == 'push' else (1 if r[2] == actual_ou else 0)
        brier_ou   = None if actual_ou == 'push' else \
                     (r[3] - (1.0 if actual_ou == 'over' else 0.0)) ** 2

        if DRY_RUN:
            old_actual = r[9] or '?'
            log.info(
                f"[DRY-RUN] {mid}: ou_line={used_line} "
                f"total={total} actual_ou={actual_ou} (was '{old_actual}') "
                f"ou_correct={ou_correct}"
            )
            recomputed += 1
            continue

        conn.execute("""
            UPDATE prediction_audit SET
                actual_ou=?, ou_correct=?, brier_ou=?,
                actual_ou_line_used=?,
                audit_time=?
            WHERE match_id=?
        """, (
            actual_ou, ou_correct,
            round(brier_ou, 4) if brier_ou is not None else None,
            used_line,
            datetime.now().isoformat(),
            mid,
        ))
        recomputed += 1

    if not DRY_RUN:
        conn.commit()

    log.info(f"  ✅ 重算完成: {recomputed} 行已更新，{skipped} 行无变化（已是最新）")


# ── Step 6: create-odds-tables ────────────────────────────────────────────────

def step_create_odds_tables(conn: sqlite3.Connection):
    log.info("─── Step 6: create-odds-tables ───")
    if DRY_RUN:
        log.info("[DRY-RUN] CREATE TABLE IF NOT EXISTS silver_match_odds ...")
        log.info("[DRY-RUN] CREATE TABLE IF NOT EXISTS odds_snapshot_log ...")
        return
    conn.executescript(DDL_SILVER_MATCH_ODDS)
    conn.executescript(DDL_ODDS_SNAPSHOT_LOG)
    conn.commit()

    # 验证
    smo_exists = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='silver_match_odds'"
    ).fetchone()[0]
    osl_exists = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='odds_snapshot_log'"
    ).fetchone()[0]
    log.info(f"  ✅ silver_match_odds 存在={bool(smo_exists)}, "
             f"odds_snapshot_log 存在={bool(osl_exists)}")


# ── Step 7: backfill-silver-odds ──────────────────────────────────────────────

def step_backfill_silver_odds(conn: sqlite3.Connection):
    log.info("─── Step 7: backfill-silver-odds ───")
    if DRY_RUN:
        raw_count = conn.execute("SELECT COUNT(*) FROM raw_footballdata_odds").fetchone()[0]
        log.info(f"[DRY-RUN] 将从 raw_footballdata_odds ({raw_count} 行) 回填 silver_match_odds")
        return
    try:
        sys.path.insert(0, PROJECT_ROOT)
        from silver_builder import _ingest_footballdata_odds
        count = _ingest_footballdata_odds(conn)
        log.info(f"  ✅ 回填完成: {count} 行写入 silver_match_odds (source=footballdata)")
    except ImportError as e:
        log.error(f"  ❌ 无法导入 silver_builder: {e}")
        raise
    except Exception as e:
        log.error(f"  ❌ 回填失败: {e}", exc_info=True)
        raise


# ── --verify ──────────────────────────────────────────────────────────────────

def step_verify(conn: sqlite3.Connection):
    log.info("─── Verify Report ───")

    # dim_team
    try:
        total_teams = conn.execute("SELECT COUNT(*) FROM dim_team").fetchone()[0]
        by_league   = conn.execute("SELECT league, COUNT(*) FROM dim_team GROUP BY league").fetchall()
        no_alias    = conn.execute("SELECT COUNT(*) FROM dim_team WHERE aliases='[]'").fetchone()[0]
        log.info(f"  dim_team: {total_teams} 行，{no_alias} 行无别名")
        for league, cnt in by_league:
            log.info(f"    {league or 'NULL'}: {cnt}")
    except Exception as e:
        log.warning(f"  dim_team 不存在或查询失败: {e}")

    # prediction_audit
    total_pa = conn.execute("SELECT COUNT(*) FROM prediction_audit").fetchone()[0]
    has_line  = conn.execute("SELECT COUNT(*) FROM prediction_audit WHERE pred_ou_line IS NOT NULL").fetchone()[0]
    audited   = conn.execute("SELECT COUNT(*) FROM prediction_audit WHERE actual_wdl IS NOT NULL").fetchone()[0]
    mismatch  = conn.execute("""
        SELECT COUNT(*) FROM prediction_audit
        WHERE actual_wdl IS NOT NULL
          AND actual_ou_line_used IS NOT NULL
          AND pred_ou_line IS NOT NULL
          AND ABS(actual_ou_line_used - pred_ou_line) > 0.001
    """).fetchone()[0]
    extreme   = conn.execute(
        "SELECT COUNT(*) FROM prediction_audit WHERE prob_sanity_flag='EXTREME'"
    ).fetchone()[0]

    log.info(f"  prediction_audit: {total_pa} 行，{audited} 行已审计，{has_line} 行有 pred_ou_line")
    log.info(f"    line 不一致: {mismatch} 行  |  EXTREME 预警: {extreme} 行")

    # 每行详情
    if audited > 0:
        log.info("  已审计行详情:")
        rows = conn.execute("""
            SELECT match_id, home_name, away_name,
                   pred_ou_pick, pred_ou_line, actual_ou_line_used,
                   actual_home_score + actual_away_score AS total,
                   actual_ou, ou_correct
            FROM prediction_audit
            WHERE actual_wdl IS NOT NULL
            ORDER BY audit_time DESC
            LIMIT 20
        """).fetchall()
        for r in rows:
            line_tag = f"line={r[4] or '?'}" if r[4] else "line=NULL(→2.5)"
            log.info(
                f"    {r[1]} vs {r[2]}: {line_tag} "
                f"total={r[6]} pred={r[3]} actual={r[7]} correct={r[8]}"
            )

    # silver_match_odds
    try:
        smo_total = conn.execute("SELECT COUNT(*) FROM silver_match_odds").fetchone()[0]
        smo_by_source = conn.execute(
            "SELECT source, market, period, COUNT(*) FROM silver_match_odds GROUP BY 1,2,3"
        ).fetchall()
        smo_matches = conn.execute(
            "SELECT COUNT(DISTINCT match_id) FROM silver_match_odds"
        ).fetchone()[0]
        log.info(f"  silver_match_odds: {smo_total} 行，覆盖 {smo_matches} 场比赛")
        for source, market, period, cnt in smo_by_source:
            log.info(f"    {source}/{market}/{period}: {cnt}")

        # overround 分布
        or_rows = conn.execute("""
            SELECT market, period, source,
                ROUND(AVG(overround),4) AS avg,
                ROUND(MIN(overround),4) AS mn,
                ROUND(MAX(overround),4) AS mx
            FROM silver_match_odds WHERE overround IS NOT NULL GROUP BY 1,2,3
        """).fetchall()
        for r in or_rows:
            log.info(f"    overround {r[0]}/{r[1]}/{r[2]}: avg={r[3]} min={r[4]} max={r[5]}")
    except Exception as e:
        log.info(f"  silver_match_odds 不存在或查询失败: {e}")

    # odds_snapshot_log
    try:
        osl_total = conn.execute("SELECT COUNT(*) FROM odds_snapshot_log").fetchone()[0]
        osl_days  = conn.execute(
            "SELECT COUNT(DISTINCT DATE(snapshot_ts)) FROM odds_snapshot_log"
        ).fetchone()[0]
        log.info(f"  odds_snapshot_log: {osl_total} 行，{osl_days} 天快照")
    except Exception as e:
        log.info(f"  odds_snapshot_log 不存在或查询失败: {e}")


# ── main ──────────────────────────────────────────────────────────────────────

STEPS = [
    ('create-tables',        step_create_tables),
    ('alter-audit',          step_alter_audit),
    ('seed-dim-team',        step_seed_dim_team),
    ('backfill-ou-line',     step_backfill_ou_line),
    ('recompute-audit',      step_recompute_audit),
    ('create-odds-tables',   step_create_odds_tables),    # Phase 2.5
    ('backfill-silver-odds', step_backfill_silver_odds),  # Phase 2.5
]


def main():
    global DRY_RUN

    parser = argparse.ArgumentParser(description="Phase 2 幂等迁移脚本")
    parser.add_argument('--db', default=DB_PATH, help='SQLite DB 路径')
    parser.add_argument('--step', choices=[s[0] for s in STEPS], help='单独执行某个步骤')
    parser.add_argument('--apply', action='store_true', help='依次执行全部 7 步')
    parser.add_argument('--dry-run', action='store_true', dest='dry_run',
                        help='只打印 SQL，不修改数据库')
    parser.add_argument('--verify', action='store_true', help='只读检查，输出 coverage 报告')
    args = parser.parse_args()

    if not (args.step or args.apply or args.verify):
        parser.print_help()
        sys.exit(0)

    DRY_RUN = args.dry_run
    if DRY_RUN:
        log.info("🔍 [DRY-RUN 模式] 只打印 SQL，不修改数据库")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        if args.verify:
            step_verify(conn)
        elif args.apply:
            for name, fn in STEPS:
                fn(conn)
            log.info("🎉 全部 7 步完成！运行 --verify 查看 coverage 报告")
        else:
            fn = dict(STEPS)[args.step]
            fn(conn)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
