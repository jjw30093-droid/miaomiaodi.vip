#!/bin/bash
# run_2223_full_pipeline.sh
# 完整流水线：等待 FotMob 回填 → NowGoal → Phase 0 重跑 → Phase 1 重训
# 日志: logs/pipeline_2223.log
set -euo pipefail

BACKEND=/home/ubuntu/app/backend
PYTHON=/home/ubuntu/app/backend/venv/bin/python3
LOG=$BACKEND/logs/pipeline_2223.log
BACKFILL_PID=2625812

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

exec >> "$LOG" 2>&1
log "========================================================"
log "run_2223_full_pipeline 启动"
log "========================================================"

cd "$BACKEND"

# ─────────────────────────────────────────────────────────────
# STEP 0: 等待 FotMob 回填完成
# ─────────────────────────────────────────────────────────────
log "[STEP 0] 等待 FotMob 回填 (PID=$BACKFILL_PID)..."
while kill -0 $BACKFILL_PID 2>/dev/null; do
    ROWS=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('football_uk.db')
r = conn.execute(\"SELECT COUNT(*) FROM dim_match WHERE Season='2022/2023' AND League_ID IN (47,87,54,55,53)\").fetchone()
print(r[0])
")
    log "  → dim_match 2022/23 rows: $ROWS  (等待 PID $BACKFILL_PID 结束...)"
    sleep 120
done

# 验证回填结果
TOTAL=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('football_uk.db')
r = conn.execute(\"SELECT COUNT(*) FROM dim_match WHERE Season='2022/2023' AND League_ID IN (47,87,54,55,53)\").fetchone()
print(r[0])
")
log "[STEP 0] FotMob 回填完成: $TOTAL 场写入 dim_match"

# ─────────────────────────────────────────────────────────────
# STEP 1: NowGoal fixtures
# ─────────────────────────────────────────────────────────────
log ""
log "[STEP 1] fetch_nowgoal_2223_fixtures.py"
$PYTHON scripts/fetch_nowgoal_2223_fixtures.py
log "[STEP 1] 完成"

# ─────────────────────────────────────────────────────────────
# STEP 2: FotMob ↔ NowGoal 映射
# ─────────────────────────────────────────────────────────────
log ""
log "[STEP 2] map_fotmob_to_nowgoal_2223.py"
$PYTHON scripts/map_fotmob_to_nowgoal_2223.py
MAPPED=$($PYTHON -c "import json; d=json.load(open('data/nowgoal_2223_mapping.json')); print(len(d))")
log "[STEP 2] 映射完成: $MAPPED 场"

# ─────────────────────────────────────────────────────────────
# STEP 3: 赔率抓取（~1.5-2h，串行限速）
# ─────────────────────────────────────────────────────────────
log ""
log "[STEP 3] fetch_nowgoal_odds_2223.py  (预计 1.5~2 小时)"
$PYTHON scripts/fetch_nowgoal_odds_2223.py
ODDS=$($PYTHON -c "import json; d=json.load(open('odds/match_odds_data_2223.json')); print(len(d))" 2>/dev/null || echo "0")
log "[STEP 3] 赔率抓取完成: $ODDS 场"

# ─────────────────────────────────────────────────────────────
# STEP 4: 入库 silver_match_odds
# ─────────────────────────────────────────────────────────────
log ""
log "[STEP 4] ingest_2223_odds_to_silver.py"
$PYTHON scripts/ingest_2223_odds_to_silver.py
SMO=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('football_uk.db')
r = conn.execute(\"SELECT COUNT(*) FROM silver_match_odds s JOIN dim_match d ON d.Match_ID=s.match_id WHERE d.Season='2022/2023' AND d.League_ID IN (47,87,54,55,53) AND s.source='nowgoal'\").fetchone()
print(r[0])
")
log "[STEP 4] silver_match_odds 2022/23 rows: $SMO"

# ─────────────────────────────────────────────────────────────
# STEP 5: 覆盖率报告
# ─────────────────────────────────────────────────────────────
log ""
log "[STEP 5] coverage_report_2223.py"
$PYTHON scripts/coverage_report_2223.py
log "[STEP 5] 报告已生成 → reports/nowgoal_2223_coverage.md"

# ─────────────────────────────────────────────────────────────
# STEP 6: Phase 0 — Pi-Ratings 重建
# ─────────────────────────────────────────────────────────────
log ""
log "[STEP 6] Phase 0-a: build_pi_ratings.py  (DROP TABLE 全量重建)"
$PYTHON v5_feature_engineering/build_pi_ratings.py
log "[STEP 6] Pi-Ratings 重建完成"

# ─────────────────────────────────────────────────────────────
# STEP 7: Phase 0 — Composite Ratios 重建
# ─────────────────────────────────────────────────────────────
log ""
log "[STEP 7] Phase 0-b: build_composite_ratios.py  (DROP TABLE 全量重建)"
$PYTHON v5_feature_engineering/build_composite_ratios.py
log "[STEP 7] Composite Ratios 重建完成"

# ─────────────────────────────────────────────────────────────
# STEP 8: Phase 0 — Matrix 重建
# ─────────────────────────────────────────────────────────────
log ""
log "[STEP 8] Phase 0-c: build_matrix_v5.py --include-future  (DROP TABLE 全量重建)"
$PYTHON v5_feature_engineering/build_matrix_v5.py --include-future
log "[STEP 8] Matrix 重建完成"

# ─────────────────────────────────────────────────────────────
# STEP 9: Phase 0 — Lambda Dataset 重建（含 --include-future）
# ─────────────────────────────────────────────────────────────
log ""
log "[STEP 9] Phase 0-d: build_lambda_dataset_v5.py --include-future  (DROP TABLE 全量重建)"
$PYTHON v5_feature_engineering/build_lambda_dataset_v5.py --include-future
TOTAL_DS=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('football_uk.db')
rows = conn.execute(\"SELECT split, COUNT(*) FROM mart_lambda_dataset_v5 GROUP BY split ORDER BY split\").fetchall()
print(' | '.join(f'{r[0]}={r[1]}' for r in rows))
")
log "[STEP 9] mart_lambda_dataset_v5: $TOTAL_DS"

# 诊断：22/23 BIG5 是否进入数据集
DIAG_2223=$($PYTHON -c "
import sqlite3
conn = sqlite3.connect('football_uk.db')
rows = conn.execute(\"\"\"
    SELECT d.League_ID, COUNT(*) as n
    FROM mart_lambda_dataset_v5 m
    JOIN dim_match d ON d.Match_ID = m.match_id
    WHERE d.Season='2022/2023' AND d.League_ID IN (47,87,54,55,53)
    GROUP BY d.League_ID ORDER BY d.League_ID
\"\"\").fetchall()
print(' | '.join(f'{r[0]}:{r[1]}' for r in rows))
")
log "[STEP 9] 2022/23 BIG5 进入数据集: $DIAG_2223"

# ─────────────────────────────────────────────────────────────
# STEP 10: 备份旧 Phase 1 结果
# ─────────────────────────────────────────────────────────────
log ""
log "[STEP 10] 备份旧 Phase 1 eval_report → eval_report_pre_2223_backfill.csv"
GLOBAL_DIR="$BACKEND/models_v5_lambda/global"
if [ -f "$GLOBAL_DIR/eval_report.csv" ]; then
    cp "$GLOBAL_DIR/eval_report.csv"     "$GLOBAL_DIR/eval_report_pre_2223_backfill.csv"
    cp "$GLOBAL_DIR/eval_metrics.json"   "$GLOBAL_DIR/eval_metrics_pre_2223_backfill.json"
    log "[STEP 10] 备份完成"
else
    log "[STEP 10] 无旧文件，跳过备份"
fi

# ─────────────────────────────────────────────────────────────
# STEP 11: Phase 1 — 全局模型重训
# ─────────────────────────────────────────────────────────────
log ""
log "[STEP 11] Phase 1: train_global_v5.py"
$PYTHON v5_feature_engineering/train_global_v5.py
log "[STEP 11] Phase 1 训练完成 → models_v5_lambda/global/"

# ─────────────────────────────────────────────────────────────
# 完成
# ─────────────────────────────────────────────────────────────
log ""
log "========================================================"
log "run_2223_full_pipeline 全部完成"
log "下一步: Phase 2 (train_league_v5.py) + Phase 3 (compare_models_v5.py)"
log "========================================================"
