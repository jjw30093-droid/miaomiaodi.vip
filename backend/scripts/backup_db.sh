#!/bin/bash
# backup_db.sh
# 每日 18:00 UTC (02:00 CST 次日) 备份 football_uk.db
# 保留最近 30 天；每周日额外保留一份周备份。
# pm2 cron: '0 18 * * *'

set -e
export PROJECT_ROOT="/home/ubuntu/app/backend"
PYTHON="$PROJECT_ROOT/venv/bin/python3"
DB_PATH="$PROJECT_ROOT/football_uk.db"
BACKUP_DIR="$PROJECT_ROOT/backups"
WEEKLY_DIR="$BACKUP_DIR/weekly"
KEEP_DAYS=30

mkdir -p "$BACKUP_DIR" "$WEEKLY_DIR"

TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
DEST="$BACKUP_DIR/football_uk_${TIMESTAMP}.db"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] 开始备份..."

# 用 Python sqlite3 的 backup() 方法保证一致性（WAL 安全）
"$PYTHON" - <<PYEOF
import sqlite3, sys
src = sqlite3.connect("$DB_PATH")
dst = sqlite3.connect("$DEST")
src.backup(dst)
dst.close()
src.close()
print("backup ok")
PYEOF

SIZE=$(du -sh "$DEST" | cut -f1)
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ✅ 备份完成: $DEST ($SIZE)"

# 每周日额外保留一份
DOW=$(date -u +%u)   # 1=Mon … 7=Sun
if [ "$DOW" = "7" ]; then
    WDEST="$WEEKLY_DIR/football_uk_weekly_${TIMESTAMP}.db"
    cp "$DEST" "$WDEST"
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] 📦 周备份: $WDEST"
fi

# 删除超过 KEEP_DAYS 天的日备份
find "$BACKUP_DIR" -maxdepth 1 -name "football_uk_*.db" -mtime +"$KEEP_DAYS" -delete
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] 🧹 清理 ${KEEP_DAYS} 天前旧备份完成"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] 当前备份列表:"
ls -lh "$BACKUP_DIR"/*.db 2>/dev/null | awk '{print "  " $5, $9}' || true
