#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性脚本：结算 06-15 ~ 06-17 已结束、尚未打标签的 8 场世界杯研报。

比分经联网多源核实（ESPN/BBC/FIFA/Al Jazeera 等交叉印证），
按各推荐的让球/大小球结算机制计算 picked_correct（1命中/0未中/-1走水）。
卡片 inference 为首选时按首选判定（西班牙场如此）。

运行：cd /home/ubuntu/app/backend && venv/bin/python3 scripts/settle_wc_results_0617.py
"""
import sqlite3
from datetime import datetime, timezone

DB_PATH = "/home/ubuntu/app/backend/worldcup.db"

# (match_id, market, direction, odds, picked_correct, hs, as_, wdl, 备注)
SETTLEMENTS = [
    ("wc_19609162", "wtn", "home",    1.57, 0, 0, 0, "draw",     "西0-0佛 · 首选零封获胜未中（次选佛+2.75命中）"),
    ("wc_19609139", "ou",  "under",   1.84, 1, 1, 1, "draw",     "比1-1埃 · 小2.5命中(总2)"),
    ("wc_19609161", "ah",  "ah_away", 1.78, 0, 1, 1, "draw",     "沙1-1乌 · 乌-1未中(平局)"),
    ("wc_19609160", "ah",  "ah_home", 1.83, 0, 2, 2, "draw",     "伊2-2新 · 伊-0.5未中(平局)"),
    ("wc_19609143", "ah",  "ah_home", 1.81, 1, 3, 1, "home_win", "法3-1塞 · 法-1命中(净胜2)"),
    ("wc_19609163", "ah",  "ah_away", 2.07, 1, 1, 4, "away_win", "伊1-4挪 · 挪-2命中(净胜3)"),
    ("wc_19609145", "ah",  "ah_away", 1.93, 0, 3, 0, "home_win", "阿根廷3-0阿尔 · 阿尔+1.25未中(净胜3)"),
    ("wc_19609164", "ah",  "ah_home", 1.70, 1, 3, 1, "home_win", "奥3-1约 · 奥-1.25命中(净胜2)"),
]


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    try:
        for mid, mkt, d, odds, pc, hs, as_, wdl, note in SETTLEMENTS:
            rep = conn.execute("SELECT home_team,away_team,match_time FROM wc_reports WHERE match_id=?", (mid,)).fetchone()
            if rep is None:
                print(f"SKIP {mid}: 无 wc_reports 行"); continue
            conn.execute(
                """INSERT OR REPLACE INTO wc_prediction_audit
                   (match_id, match_date, home, away, picked_market, picked_direction, picked_odds,
                    picked_confidence, picked_correct, actual_home_score, actual_away_score, actual_wdl, audit_time)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (mid, (rep["match_time"] or "")[:10], rep["home_team"], rep["away_team"],
                 mkt, d, odds, None, pc, hs, as_, wdl, now),
            )
            tag = {1: "命中", 0: "未中", -1: "走水"}[pc]
            print(f"SET {mid}: {hs}-{as_} → picked_correct={pc}({tag})  | {note}")
        conn.commit()
        print("--- readback ---")
        for r in conn.execute(
            "SELECT match_id, actual_home_score||'-'||actual_away_score AS score, picked_correct "
            "FROM wc_prediction_audit WHERE match_id IN "
            "('wc_19609162','wc_19609139','wc_19609161','wc_19609160','wc_19609143','wc_19609163','wc_19609145','wc_19609164') "
            "ORDER BY match_id").fetchall():
            print(" ", dict(r))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
