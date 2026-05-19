#!/usr/bin/env bash
# rebuild_lambda_features.sh — 重建 mart_lambda_dataset_v5（含未来场次）
# pm2 cron: 03:25 UTC（dbt 03:20 之后、run-tonight 04:40 之前）
#
# 数据流：
#   dbt → mart_prediction_matrix_v5 (--include_future)
#       → mart_ah_dataset_v5
#       → mart_lambda_dataset_v5 (--include_future, split='inference')
#       → LambdaAHPredictor.predict_match() 读取
set -euo pipefail

cd /home/ubuntu/app/backend
source venv/bin/activate

LOG_PREFIX="[$(date -u +'%Y-%m-%d %H:%M:%S UTC')] rebuild_lambda_features"

echo "${LOG_PREFIX} Step 1/3: build_matrix_v5 --include_future"
python -m v5_feature_engineering.build_matrix_v5 --include_future

echo "${LOG_PREFIX} Step 2/3: build_ah_dataset_v5"
python -m v5_feature_engineering.build_ah_dataset_v5

echo "${LOG_PREFIX} Step 3/3: build_lambda_dataset_v5 --include_future"
python -m v5_feature_engineering.build_lambda_dataset_v5 --include_future

echo "${LOG_PREFIX} ✅ done"
