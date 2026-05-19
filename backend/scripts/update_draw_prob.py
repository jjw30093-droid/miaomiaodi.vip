#!/usr/bin/env python3
"""
从欧赔 JSON 和研报 Markdown 提取赔率，换算三项概率写入 report_store。

来源优先级：
  1. odds/match_odds_data.json（按 fotmob_id=match_id 查找，精确）
  2. reports/ 目录下对应的 Markdown 文件（正则匹配欧赔）
  3. 兜底：draw_prob = max(0, 100 - home_prob - away_prob)
"""
import json
import re
import sqlite3
import glob
import os

import os as _os
_UDD = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
DB_PATH    = _os.environ.get("DB_PATH", _os.path.join(_UDD, "football_uk.db"))
ODDS_JSON  = _os.path.join(_UDD, "odds", "match_odds_data.json")
REPORTS_DIR= _os.path.join(_UDD, "reports")


def normalize(h_odds: float, d_odds: float, a_odds: float):
    """小数赔率 → 归一化隐含概率（%），去除庄家利润率。"""
    rh = 1 / h_odds
    rd = 1 / d_odds
    ra = 1 / a_odds
    total = rh + rd + ra
    return (
        round((rh / total) * 100, 1),
        round((rd / total) * 100, 1),
        round((ra / total) * 100, 1),
    )


def from_json(match_id: str, lookup: dict):
    entry = lookup.get(match_id)
    if not entry:
        return None
    try:
        eu = entry["odds"]["european_1x2"]
        src = eu.get("latest") or eu.get("initial") or {}
        h, d, a = float(src["home"]), float(src["draw"]), float(src["away"])
        if h > 1 and d > 1 and a > 1:
            return normalize(h, d, a)
    except Exception:
        pass
    return None


def from_markdown(match_id: str):
    files = glob.glob(os.path.join(REPORTS_DIR, f"*_{match_id}.md"))
    if not files:
        return None
    content = open(files[0], encoding="utf-8").read()
    # 匹配格式：主X.XX/平X.XX/客X.XX  或  home:X.XX draw:X.XX away:X.XX
    patterns = [
        r'主[胜]?\s*(\d+\.?\d+)\s*/\s*平[局]?\s*(\d+\.?\d+)\s*/\s*客[胜]?\s*(\d+\.?\d+)',
        r'(?i)home[:\s]+(\d+\.\d+)[,\s/]+draw[:\s]+(\d+\.\d+)[,\s/]+away[:\s]+(\d+\.\d+)',
    ]
    for pat in patterns:
        m = re.search(pat, content, re.IGNORECASE | re.MULTILINE)
        if m:
            try:
                h, d, a = float(m.group(1)), float(m.group(2)), float(m.group(3))
                if h > 1 and d > 1 and a > 1:
                    return normalize(h, d, a)
            except Exception:
                pass
    return None


def main():
    print("=== update_draw_prob.py ===")

    with open(ODDS_JSON, encoding="utf-8") as f:
        odds_list = json.load(f)
    lookup = {e["fotmob_id"]: e for e in odds_list if "fotmob_id" in e}
    print(f"Loaded {len(lookup)} entries from match_odds_data.json")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 1. 添加列
    try:
        conn.execute("ALTER TABLE report_store ADD COLUMN draw_prob REAL")
        conn.commit()
        print("✓ Added draw_prob column")
    except sqlite3.OperationalError:
        print("  draw_prob column already exists")

    rows = conn.execute(
        "SELECT match_id, home_prob, away_prob FROM report_store"
    ).fetchall()

    stats = {"json": 0, "md": 0, "fallback": 0, "skip": 0}

    for row in rows:
        mid   = str(row["match_id"])
        ex_h  = row["home_prob"]
        ex_a  = row["away_prob"]

        # --- 方法 1: JSON 欧赔 ---
        result = from_json(mid, lookup)
        if result:
            h, d, a = result
            conn.execute(
                "UPDATE report_store SET home_prob=?, draw_prob=?, away_prob=? WHERE match_id=?",
                (h, d, a, mid)
            )
            stats["json"] += 1
            continue

        # --- 方法 2: Markdown 正则 ---
        result = from_markdown(mid)
        if result:
            h, d, a = result
            conn.execute(
                "UPDATE report_store SET home_prob=?, draw_prob=?, away_prob=? WHERE match_id=?",
                (h, d, a, mid)
            )
            stats["md"] += 1
            continue

        # --- 方法 3: 兜底（保留已有主客概率，补算平局）---
        if ex_h and ex_a and ex_h > 0 and ex_a > 0:
            draw_p = round(max(0.0, 100.0 - ex_h - ex_a), 1)
            conn.execute(
                "UPDATE report_store SET draw_prob=? WHERE match_id=?",
                (draw_p, mid)
            )
            stats["fallback"] += 1
        else:
            stats["skip"] += 1

    conn.commit()
    conn.close()

    print(f"\n✓ 完成:")
    print(f"  来自 JSON 欧赔:    {stats['json']} 场")
    print(f"  来自 Markdown:     {stats['md']} 场")
    print(f"  兜底计算平局:      {stats['fallback']} 场")
    print(f"  无数据跳过:        {stats['skip']} 场")


if __name__ == "__main__":
    main()
