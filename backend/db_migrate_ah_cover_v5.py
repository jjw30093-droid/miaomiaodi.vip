"""
Schema 迁移：新增 pred_ah_cover_v5 REAL 列

背景（2026-05-18）：v5 Lambda AH 模型已上线，能正常输出预测方向，
但 cover 概率从未被持久化到 prediction_audit，导致无法做 calibration / Brier 审计。
本脚本新增 pred_ah_cover_v5 REAL 列（与 pred_ou_over_v5 REAL 命名对称）。
SQLite ADD COLUMN 是 O(1) 元数据操作，不重写数据行，毫秒级完成。
脚本幂等，可重复执行。
"""

import sqlite3
import os

DB = os.environ.get("DB_PATH", "/home/ubuntu/app/backend/football_uk.db")


def run():
    conn = sqlite3.connect(DB)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(prediction_audit)").fetchall()]

        added = []
        if "pred_ah_cover_v5" not in cols:
            conn.execute("ALTER TABLE prediction_audit ADD COLUMN pred_ah_cover_v5 REAL")
            added.append("pred_ah_cover_v5 REAL")

        if added:
            conn.commit()
            print(f"✅ 已添加列: {', '.join(added)}")
        else:
            print("ℹ️  所有列已存在，跳过迁移")

        # 验证
        final_cols = [r[1] for r in conn.execute("PRAGMA table_info(prediction_audit)").fetchall()]
        for col in ["pred_ah_pick_v5", "pred_ah_line_v5", "pred_ah_cover_v5"]:
            status = "✅" if col in final_cols else "❌ 缺失！"
            print(f"  {status} {col}")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
