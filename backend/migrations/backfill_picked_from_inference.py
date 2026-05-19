"""
backfill_picked_from_inference.py
=================================
Part B3: 从 report_store.inference 历史文本回填 prediction_audit.picked_* 字段。

旧 inference 格式示例：
  【HIGH】客胜 @2.10 67.9%  (14.6%/17.5%/67.9%)
  【MID】小球 @1.85 61.6%  (24.7%/37.0%/38.3%)
  【LOW】客胜 @2.35 48.4%  (13.9%/37.8%/48.4%)
  【观望】本场各方向置信度均低 ...

回填范围：最近 8 周（更早格式多版本不稳定）。
运行：python3 migrations/backfill_picked_from_inference.py
"""
import os
import re
import sqlite3
import logging

PROJECT_ROOT = os.environ.get("PROJECT_ROOT",
                              os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(PROJECT_ROOT, "football_uk.db")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# 【CONF】LABEL @ODDS PROB%
RE_PICK = re.compile(
    r"【(?P<conf>HIGH|MID|MEDIUM|LOW|观望)】\s*(?P<label>[^\s@]+)(?:\s*@(?P<odds>[\d.]+))?\s*(?P<prob>[\d.]+)?%"
)

# label → (market, direction)
LABEL_MAP = {
    "主胜":     ("wdl", "home"),
    "平局":     ("wdl", "draw"),
    "客胜":     ("wdl", "away"),
    "大球":     ("ou",  "over"),   # 兜底；实际会带 (>2.5)
    "小球":     ("ou",  "under"),
}


def _parse_label(label: str):
    # 去掉 (>2.5) 之类尾巴
    base = re.sub(r"[\(\（].*", "", label).strip()
    if base in LABEL_MAP:
        return LABEL_MAP[base]
    # 大球(>2.5) / 小球(≤2.5)
    if base.startswith("大球"):
        return ("ou", "over")
    if base.startswith("小球"):
        return ("ou", "under")
    # 亚盘方向：主让/主受/客让/客受
    if base.startswith("主让") or base.startswith("主受"):
        return ("ah", "ah_home")
    if base.startswith("客让") or base.startswith("客受"):
        return ("ah", "ah_away")
    return (None, None)


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT match_id, inference
        FROM report_store
        WHERE match_time >= datetime('now', '-56 days')
          AND inference IS NOT NULL
    """).fetchall()

    log.info(f"扫描 {len(rows)} 行 report_store（近 8 周）")

    updated = skipped = no_match = 0
    for r in rows:
        inf = r["inference"] or ""
        m = RE_PICK.search(inf)
        if not m:
            no_match += 1
            continue
        conf  = m.group("conf")
        label = m.group("label") or ""
        odds  = m.group("odds")
        market, direction = _parse_label(label)
        if not market:
            skipped += 1
            continue

        # 归一化：观望 → SKIP；MEDIUM → MID
        conf_norm = {"观望": "SKIP", "MEDIUM": "MID"}.get(conf, conf)
        odds_f = float(odds) if odds else None

        # 必须已有 prediction_audit 行，否则插入空行兜底
        exists = cur.execute("SELECT 1 FROM prediction_audit WHERE match_id=?",
                             (r["match_id"],)).fetchone()
        if not exists:
            cur.execute("""INSERT OR IGNORE INTO prediction_audit (match_id, match_date)
                           VALUES (?, date('now'))""", (r["match_id"],))

        cur.execute("""
            UPDATE prediction_audit SET
                picked_market     = COALESCE(picked_market,     ?),
                picked_direction  = COALESCE(picked_direction,  ?),
                picked_odds       = COALESCE(picked_odds,       ?),
                picked_confidence = COALESCE(picked_confidence, ?)
            WHERE match_id=?
        """, (market, direction, odds_f, conf_norm, r["match_id"]))
        updated += 1

    conn.commit()

    # 回填 picked_correct（对已审计行）
    log.info("回填 picked_correct（对 actual_wdl 非空行重放）...")
    corr_rows = cur.execute("""
        SELECT match_id, picked_market, picked_direction, picked_confidence,
               actual_wdl, actual_ou, actual_home_score, actual_away_score,
               pred_ah_line, pred_ah_pick, ah_correct
        FROM prediction_audit
        WHERE picked_market IS NOT NULL
          AND actual_wdl IS NOT NULL
          AND picked_correct IS NULL
    """).fetchall()
    fixed = 0
    for x in corr_rows:
        if x["picked_confidence"] == "SKIP":
            continue
        pc = None
        pm, pd = x["picked_market"], x["picked_direction"]
        if pm == "wdl":
            target = {"home": "home_win", "draw": "draw", "away": "away_win"}.get(pd)
            pc = 1 if target == x["actual_wdl"] else 0
        elif pm == "ou":
            if x["actual_ou"] == "push":
                pc = None
            else:
                pc = 1 if pd == x["actual_ou"] else 0
        elif pm == "ah":
            hs, as_, aline = x["actual_home_score"], x["actual_away_score"], x["pred_ah_line"]
            if hs is not None and as_ is not None and aline is not None:
                adj = hs - as_ - aline
                side = "home" if pd == "ah_home" else "away"
                if adj > 0:
                    pc = 1 if side == "home" else 0
                elif adj < 0:
                    pc = 1 if side == "away" else 0
                else:
                    pc = None
        if pc is not None:
            cur.execute("UPDATE prediction_audit SET picked_correct=? WHERE match_id=?",
                        (pc, x["match_id"]))
            fixed += 1

    conn.commit()

    log.info(f"✅ 回填完成: updated={updated}  skipped={skipped}  no_match={no_match}")
    log.info(f"   picked_correct 补齐 {fixed} 行")

    # 汇报
    summary = cur.execute("""
        SELECT picked_market, picked_confidence,
               COUNT(*) AS n,
               SUM(CASE WHEN picked_correct=1 THEN 1 ELSE 0 END) AS hits,
               SUM(CASE WHEN picked_correct IS NOT NULL THEN 1 ELSE 0 END) AS settled
        FROM prediction_audit
        WHERE picked_market IS NOT NULL
        GROUP BY picked_market, picked_confidence
        ORDER BY picked_market, picked_confidence
    """).fetchall()
    log.info("分布（market × confidence）:")
    for s in summary:
        acc = (s["hits"] / s["settled"] * 100) if s["settled"] else 0.0
        log.info(f"  {s['picked_market']:4s} {s['picked_confidence'] or '(none)':6s}  "
                 f"n={s['n']:3d}  settled={s['settled']:3d}  hit={s['hits']:3d}  acc={acc:5.1f}%")

    conn.close()


if __name__ == "__main__":
    run()
