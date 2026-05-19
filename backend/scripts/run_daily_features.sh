#!/bin/bash
# run_daily_features.sh
# 每日 03:20 UTC (11:20 CST) 在 batch_sync (03:00) 之后运行：
#   1. refresh_rolling_features.py --all: 重建 int_team_match_flattened + int_team_rolling_features
#   2. feature_engineering.py: 更新 int_team_elo_history

set -e
export PROJECT_ROOT="/home/ubuntu/app/backend"
export DB_PATH="$PROJECT_ROOT/football_uk.db"
PYTHON="$PROJECT_ROOT/venv/bin/python3"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] === 开始每日特征工程 ==="

# Step 1: rebuild int_team_match_flattened + rolling features
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Step 1: refresh_rolling_features --all..."
cd "$PROJECT_ROOT"
"$PYTHON" scripts/refresh_rolling_features.py --all
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Step 1 完成"

# Step 2: ELO ratings
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Step 2: feature_engineering.py..."
"$PYTHON" feature_engineering.py
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Step 2 完成"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] === 每日特征工程完成 ==="
