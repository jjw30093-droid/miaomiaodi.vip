#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性脚本：给已结束的世界杯研报打结算标签（命中/未中/走水）。

写入 worldcup.db.wc_prediction_audit.picked_correct：
    1 = 命中  /  0 = 未中  /  -1 = 走水（push）

标签由站长人工给定（WC 实盘手动结算）。本脚本不写实际比分（Sportmonks
同步尚未回填），只写 picked_correct + 推荐方向元数据，供首页归档卡渲染。

运行（服务器，后端 venv）：
    cd /home/ubuntu/app/backend
    venv/bin/python3 scripts/settle_wc_results.py
"""
import os
import sqlite3
import sys
from datetime import datetime, timezone

DB_PATH = "/home/ubuntu/app/backend/worldcup.db"

# (match_id, picked_market, picked_direction, picked_odds, picked_correct, 备注)
SETTLEMENTS = [
    ("wc_19609130", "ah", "ah_away", 1.80, 0,  "瑞士 -1.75 未中"),
    ("wc_19609155", "ah", "ah_away", 2.00, -1, "苏格兰 -1 走水"),
    ("wc_19609131", "ah", "ah_away", 2.02, 1,  "摩洛哥 +0.75 命中"),
    ("wc_19609156", "ou", "under",   2.08, 1,  "小 2.25 命中"),
]


def main() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        for match_id, market, direction, odds, correct, note in SETTLEMENTS:
            rep = conn.execute(
                "SELECT home_team, away_team, match_time FROM wc_reports WHERE match_id=?",
                (match_id,),
            ).fetchone()
            if rep is None:
                print(f"SKIP {match_id}: 无 wc_reports 行")
                continue
            match_date = (rep["match_time"] or "")[:10]
            conn.execute(
                """
                INSERT OR REPLACE INTO wc_prediction_audit
                    (match_id, match_date, home, away,
                     picked_market, picked_direction, picked_odds, picked_confidence,
                     picked_correct, actual_home_score, actual_away_score, actual_wdl,
                     audit_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)
                """,
                (match_id, match_date, rep["home_team"], rep["away_team"],
                 market, direction, odds, None, correct, now),
            )
            print(f"SET {match_id}: picked_correct={correct}  ({note})")
        conn.commit()
        print("--- readback ---")
        for r in conn.execute(
            "SELECT match_id, picked_market, picked_direction, picked_odds, picked_correct "
            "FROM wc_prediction_audit WHERE match_id IN "
            "('wc_19609130','wc_19609155','wc_19609131','wc_19609156') ORDER BY match_id"
        ).fetchall():
            print(" ", dict(r))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
