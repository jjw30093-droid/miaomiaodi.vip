#!/bin/bash
# 实时监控 backfill_2122_big5.py 进度
DB=/home/ubuntu/app/backend/football_uk.db
LOG=/home/ubuntu/app/backend/logs/backfill_2122.log

LEAGUES=(
  "47:EPL英超:380"
  "87:La_Liga西甲:380"
  "54:Bundesliga德甲:306"
  "55:Serie_A意甲:380"
  "53:Ligue1法甲:382"
)
TOTAL_TARGET=1828

while true; do
  clear
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  2021/22 BIG5 回填进度监控   $(date '+%Y-%m-%d %H:%M:%S UTC')"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  TOTAL_DONE=0

  for entry in "${LEAGUES[@]}"; do
    IFS=: read -r lid name target <<< "$entry"

    # 完整场次：dim_match 有比分 + fact_shotmap 有记录
    done=$(sqlite3 "$DB" "
      SELECT COUNT(DISTINCT d.Match_ID)
      FROM dim_match d
      JOIN fact_shotmap fs ON fs.Match_ID = d.Match_ID
      WHERE d.Season='2021/2022' AND d.League_ID=$lid AND d.home_score IS NOT NULL;
    ")

    # 已写 dim_match（含判负/无数据场次）
    dim_done=$(sqlite3 "$DB" "
      SELECT COUNT(*) FROM dim_match
      WHERE Season='2021/2022' AND League_ID=$lid;
    ")

    pct=$(( done * 100 / target ))
    bar_len=$(( pct * 20 / 100 ))
    bar=$(printf '%0.s█' $(seq 1 $bar_len 2>/dev/null) | head -c $bar_len)
    space=$(printf '%0.s░' $(seq 1 $((20 - bar_len)) 2>/dev/null) | head -c $((20 - bar_len)))

    printf "  %-14s [%s%s] %3d%% (%d/%d  dim=%d)\n" \
      "$name" "$bar" "$space" "$pct" "$done" "$target" "$dim_done"

    TOTAL_DONE=$((TOTAL_DONE + done))
  done

  TOTAL_PCT=$(( TOTAL_DONE * 100 / TOTAL_TARGET ))
  TOTAL_BAR_LEN=$(( TOTAL_PCT * 20 / 100 ))
  TOTAL_BAR=$(printf '%0.s█' $(seq 1 $TOTAL_BAR_LEN 2>/dev/null) | head -c $TOTAL_BAR_LEN)
  TOTAL_SPACE=$(printf '%0.s░' $(seq 1 $((20 - TOTAL_BAR_LEN)) 2>/dev/null) | head -c $((20 - TOTAL_BAR_LEN)))

  FAILS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM ingest_failure_log WHERE script_name='backfill_2122_big5' AND resolved=0;")
  IS_RUNNING=$(ps aux | grep "backfill_2122" | grep -v grep | grep -v watch | wc -l)

  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  printf "  %-14s [%s%s] %3d%% (%d/%d)\n" \
    "合计" "$TOTAL_BAR" "$TOTAL_SPACE" "$TOTAL_PCT" "$TOTAL_DONE" "$TOTAL_TARGET"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  if [ "$IS_RUNNING" -gt 0 ]; then
    echo "  状态: 🟢 运行中"
  else
    echo "  状态: ⭕ 已停止"
  fi
  echo "  失败场次: $FAILS 场（见 ingest_failure_log）"
  echo ""
  echo "  最新日志:"
  grep -E "✅|❌|⏸️|🏁|待抓取" "$LOG" | tail -5 | sed 's/^/    /'
  echo ""
  echo "  [Ctrl+C 退出]"

  sleep 10
done
