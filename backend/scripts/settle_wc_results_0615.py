#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性脚本：给 2026-06-15 凌晨结束的 4 场世界杯研报打结算标签（全部命中）。

写入 worldcup.db.wc_prediction_audit.picked_correct = 1（命中）。
标签由站长人工给定（WC 实盘手动结算）。比分尚未由 Sportmonks 同步，
本脚本只写 picked_correct + 推荐方向元数据，供首页归档卡渲染。

运行（服务器，后端 venv）：
    cd /home/ubuntu/app/backend
    venv/bin/python3 scripts/settle_wc_results_0615.py
"""
import sqlite3
from datetime import datetime, timezone

DB_PATH = "/home/ubuntu/app/backend/worldcup.db"

# (match_id, picked_market, picked_direction, picked_odds, picked_correct, 备注)
SETTLEMENTS = [
    ("wc_19609158", "ah",   "ah_home", 2.00, 1, "德国 主让3.5 命中"),
    ("wc_19609138", "btts", "yes",     1.78, 1, "双方进球 命中"),
    ("wc_19609157", "ou",   "under",   1.41, 1, "小球 2.5 命中"),
    ("wc_19609159", "ah",   "ah_home", 1.88, 1, "瑞典 主让0.5 命中"),
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
            "SELECT match_id, picked_market, picked_direction, picked_correct "
            "FROM wc_prediction_audit WHERE match_id IN "
            "('wc_19609158','wc_19609138','wc_19609157','wc_19609159') ORDER BY match_id"
        ).fetchall():
            print(" ", dict(r))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
