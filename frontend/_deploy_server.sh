#!/bin/bash
# 部署脚本：上传 run_tonight_reports.py (双线程+联赛优先) + 修改 pipeline_runner.py 超时
# 用法: bash _deploy_server.sh

KEY="/Users/wanglujun/Downloads/LightsailDefaultKey-ap-northeast-1.pem"
HOST="ubuntu@54.168.246.157"
REMOTE="/home/ubuntu/app/backend"

echo "=== 1. 上传 run_tonight_reports.py ==="
scp -i "$KEY" /Users/wanglujun/Desktop/Football_Data_Lake/run_tonight_reports.py \
    "$HOST:$REMOTE/run_tonight_reports.py"
echo "✅ 上传完成"

echo ""
echo "=== 2. 修改 pipeline_runner.py: reports 超时 1800 → 6000 ==="
ssh -i "$KEY" "$HOST" "
  cd $REMOTE
  # 检查当前值
  grep -n '\"reports\"\|timeout.*1800\|timeout.*6000' pipeline_runner.py | head -10
  # 替换（仅替换 reports 步骤的 timeout）
  sed -i 's/\"name\": \"reports\".*\"timeout\": 1800/\"name\": \"reports\", \"desc\": \"生成今晚研报\", \"script\": \"run_tonight_reports.py\", \"timeout\": 6000/g' pipeline_runner.py
  echo '--- 替换后验证 ---'
  grep -n 'reports.*timeout\|timeout.*reports' pipeline_runner.py | head -5
"

echo ""
echo "=== 3. 重启 daily-pipeline ==="
ssh -i "$KEY" "$HOST" "pm2 restart daily-pipeline && pm2 list | grep daily"

echo ""
echo "=== 完成 ==="
