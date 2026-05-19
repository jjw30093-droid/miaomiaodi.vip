"""
fit_league_offsets.py
======================
A1 + A2: 联赛级 OU 偏置校正 + 决策阈值标定

数据来源：
  - raw_footballdata_odds  → 各联赛实际进球 → 历史大/小球率（大样本，2023-2026）
  - prediction_audit       → 模型近期预测均值（用于验证偏差方向）

产出：
  - calibration_league 表（每个联赛一行）

用法：
  python3 calibration/fit_league_offsets.py        # 正常运行
  python3 calibration/fit_league_offsets.py --dry  # 只打印，不写入 DB
"""

import os
import sys
import sqlite3
import argparse
import logging
from datetime import datetime

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Div → FotMob League_ID 映射 ──────────────────────────────────────────────
DIV_TO_LID = {
    "E0":  47,   # EPL
    "D1":  87,   # Bundesliga
    "SP1": 55,   # La Liga
    "I1":  54,   # Serie A
    "F1":  53,   # Ligue 1
    "K1":  9080, # K-League 1
    "J1":  223,  # J-League 1
    "A1":  113,  # A-League (Australia)
    "UCL": 42,   # Champions League
}

# 联赛中文名
LID_NAMES = {
    47: "英超", 87: "德甲", 55: "西甲", 54: "意甲", 53: "法甲",
    9080: "K联赛", 223: "J联赛", 113: "澳超", 42: "欧冠",
    73: "欧联", 10216: "欧会联",
}

# OULine 默认值（football-data.co.uk 字段，若为 NULL 用此默认）
DEFAULT_OU_LINE = 2.5


def ensure_table(conn):
    """创建 calibration_league 表（如不存在）"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calibration_league (
            league_id       INTEGER PRIMARY KEY,
            league_name     TEXT,
            ou_line         REAL    DEFAULT 2.5,
            ou_actual_rate  REAL,        -- 历史实际大球率（基于 raw_footballdata_odds）
            ou_model_rate   REAL,        -- 模型平均预测大球概率（基于 prediction_audit）
            ou_bias         REAL,        -- actual_rate - model_rate（校正量）
            ou_threshold    REAL,        -- 推荐决策阈值（0.5 - ou_bias）
            sample_hist     INTEGER,     -- raw_footballdata_odds 样本数
            sample_audit    INTEGER,     -- prediction_audit 样本数
            updated_at      TEXT
        )
    """)
    conn.commit()


def compute_historical_ou_rates(conn) -> dict:
    """
    从 raw_footballdata_odds 计算每个 Div 的实际大球率（按 OULine 分）。
    对于 OULine 为 NULL 的行，使用默认 2.5。
    返回 {league_id: {"rate": float, "count": int, "line": float}}
    """
    result = {}
    rows = conn.execute("""
        SELECT
            Div,
            COALESCE(OULine, ?) as ou_line,
            FTHG + FTAG as goals,
            COUNT(*) as cnt
        FROM raw_footballdata_odds
        WHERE FTHG IS NOT NULL AND FTAG IS NOT NULL
        GROUP BY Div, COALESCE(OULine, ?)
        ORDER BY Div, cnt DESC
    """, (DEFAULT_OU_LINE, DEFAULT_OU_LINE)).fetchall()

    # 对每个 Div 取样本最多的 OULine（通常就是 2.5）
    div_data = {}
    for row in rows:
        div, ou_line, _, cnt = row
        if div not in div_data or cnt > div_data[div]["cnt"]:
            div_data[div] = {"ou_line": ou_line, "cnt": cnt}

    # 对每个 Div 计算实际大球率
    for div, info in div_data.items():
        lid = DIV_TO_LID.get(div)
        if lid is None:
            continue
        ou_line = info["ou_line"]
        rows2 = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN FTHG + FTAG > ? THEN 1 ELSE 0 END) as over_cnt
            FROM raw_footballdata_odds
            WHERE Div = ? AND FTHG IS NOT NULL AND FTAG IS NOT NULL
        """, (ou_line, div)).fetchone()
        total, over_cnt = rows2[0], rows2[1]
        if total > 0:
            result[lid] = {
                "rate":    round(over_cnt / total, 4),
                "count":   total,
                "ou_line": ou_line,
            }
    return result


def compute_model_ou_rates(conn) -> dict:
    """
    从 prediction_audit 计算每个联赛的模型平均 pred_ou_over。
    只用有实际结果的行（actual_wdl IS NOT NULL）。
    返回 {league_id: {"rate": float, "count": int}}
    """
    result = {}
    rows = conn.execute("""
        SELECT
            d.League_ID,
            AVG(pa.pred_ou_over) as avg_pred,
            COUNT(*)             as cnt
        FROM prediction_audit pa
        JOIN dim_match d ON d.Match_ID = pa.match_id
        WHERE pa.actual_wdl IS NOT NULL
          AND pa.pred_ou_over IS NOT NULL
        GROUP BY d.League_ID
    """).fetchall()
    for row in rows:
        lid, avg_pred, cnt = row
        result[lid] = {"rate": round(avg_pred, 4), "count": cnt}
    return result


def fit_and_write(dry_run: bool = False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_table(conn)

    hist_rates  = compute_historical_ou_rates(conn)
    model_rates = compute_model_ou_rates(conn)

    # 全局 fallback（当联赛数据不足时使用）
    global_hist  = sum(v["rate"] * v["count"] for v in hist_rates.values()) / \
                   max(1, sum(v["count"] for v in hist_rates.values()))
    global_model = sum(v["rate"] * v["count"] for v in model_rates.values()) / \
                   max(1, sum(v["count"] for v in model_rates.values()))
    global_bias  = round(global_hist - global_model, 4)

    log.info(f"全局: 历史大球率={global_hist:.3f}  模型均值={global_model:.3f}  偏置={global_bias:+.3f}")

    # 所有目标联赛 ID
    TARGET_LIDS = list(DIV_TO_LID.values()) + [73, 10216]
    TARGET_LIDS = list(set(TARGET_LIDS))

    records = []
    for lid in TARGET_LIDS:
        h  = hist_rates.get(lid, {})
        m  = model_rates.get(lid, {})

        actual_rate  = h.get("rate")
        model_rate   = m.get("rate")
        sample_hist  = h.get("count", 0)
        sample_audit = m.get("count", 0)
        ou_line      = h.get("ou_line", DEFAULT_OU_LINE)

        # 偏置计算：若历史数据不足，使用全局偏置
        if actual_rate is not None and model_rate is not None:
            bias = round(actual_rate - model_rate, 4)
            src  = "per-league"
        elif actual_rate is not None:
            # 只有历史数据，缺模型数据 → 用全局模型均值
            bias = round(actual_rate - global_model, 4)
            src  = "hist-only"
        else:
            bias = global_bias
            src  = "global"

        # 阈值 = 0.5 - bias（等价于把实际率平移到 0.5 处）
        threshold = round(0.5 - bias, 4)
        threshold = max(0.35, min(0.65, threshold))  # 防止极端值

        rec = {
            "league_id":      lid,
            "league_name":    LID_NAMES.get(lid, str(lid)),
            "ou_line":        ou_line,
            "ou_actual_rate": actual_rate,
            "ou_model_rate":  model_rate,
            "ou_bias":        bias,
            "ou_threshold":   threshold,
            "sample_hist":    sample_hist,
            "sample_audit":   sample_audit,
            "updated_at":     datetime.utcnow().isoformat(),
        }
        records.append(rec)

        hist_str  = f"{actual_rate:.3f}" if actual_rate is not None else "N/A  "
        model_str = f"{model_rate:.3f}" if model_rate is not None else "N/A  "
        log.info(
            f"  LID={lid:5d} {LID_NAMES.get(lid, '?'):6s}: "
            f"hist={hist_str:>6}({sample_hist:4d}) "
            f"model={model_str:>6}({sample_audit:3d}) "
            f"bias={bias:+.3f}  τ={threshold:.3f}  [{src}]"
        )

    if dry_run:
        log.info("DRY RUN — 不写入 DB")
        return records

    # 写入 DB（UPSERT）
    for rec in records:
        conn.execute("""
            INSERT INTO calibration_league
                (league_id, league_name, ou_line, ou_actual_rate, ou_model_rate,
                 ou_bias, ou_threshold, sample_hist, sample_audit, updated_at)
            VALUES
                (:league_id, :league_name, :ou_line, :ou_actual_rate, :ou_model_rate,
                 :ou_bias, :ou_threshold, :sample_hist, :sample_audit, :updated_at)
            ON CONFLICT(league_id) DO UPDATE SET
                league_name    = excluded.league_name,
                ou_line        = excluded.ou_line,
                ou_actual_rate = excluded.ou_actual_rate,
                ou_model_rate  = excluded.ou_model_rate,
                ou_bias        = excluded.ou_bias,
                ou_threshold   = excluded.ou_threshold,
                sample_hist    = excluded.sample_hist,
                sample_audit   = excluded.sample_audit,
                updated_at     = excluded.updated_at
        """, rec)

    conn.commit()
    conn.close()
    log.info(f"✅ 写入 calibration_league: {len(records)} 条")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true", help="只打印，不写入 DB")
    args = parser.parse_args()
    fit_and_write(dry_run=args.dry)
