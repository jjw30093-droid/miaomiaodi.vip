#!/usr/bin/env bash
# 用户数据独立备份脚本
# 用途: 将用户系统相关表导出到独立 .db，与业务数据备份解耦
# 输出: backend/user_backups/users_YYYYMMDD_HHMMSS.db
# 保留: 最近 60 天，超出自动滚动删除
# 失败保护: 大小异常 / 导出失败时不覆盖，立刻退出

set -euo pipefail

DB_PATH="/home/ubuntu/app/backend/football_uk.db"
OUT_DIR="/home/ubuntu/app/backend/user_backups"
TS=$(date -u +%Y%m%d_%H%M%S)
OUT_FILE="$OUT_DIR/users_${TS}.db"
LOG_FILE="$OUT_DIR/backup.log"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }

# 用户系统表清单（含 deprecated 的 wechat_users，有 4 行历史数据，保留备份）
# user_preferences 尚未建表，脚本对 "no such table" 优雅跳过
TABLES=(
    users
    user_sessions
    shop_cdk
    admin_audit_log
    user_meta
    user_unlocks
    wechat_users
    user_preferences
)

mkdir -p "$OUT_DIR"

TMP_FILE="${OUT_FILE}.tmp"

# 导出：逐表 .dump（sqlite3 .dump 自带 BEGIN/COMMIT，不能再包外层事务）
# missing 表只写注释跳过
for t in "${TABLES[@]}"; do
    if sqlite3 "$DB_PATH" "SELECT 1 FROM $t LIMIT 1;" > /dev/null 2>&1; then
        sqlite3 "$DB_PATH" ".dump $t" | sqlite3 "$TMP_FILE"
    else
        echo "-- WARN: table '$t' not found in $DB_PATH, skipped" >> "$LOG_FILE"
    fi
done

# 大小合理性检查（用户数据通常 < 1MB；> 100MB 说明误导入业务数据）
SIZE=$(stat -c%s "$TMP_FILE")
if [ "$SIZE" -gt 104857600 ]; then
    log "ERROR: backup size ${SIZE} bytes > 100MB 异常，中止备份，删除临时文件"
    rm -f "$TMP_FILE"
    exit 1
fi

if [ "$SIZE" -lt 1024 ]; then
    log "WARN: backup size ${SIZE} bytes 过小（< 1KB），users 表可能为空，仍保留"
fi

# 原子替换
mv "$TMP_FILE" "$OUT_FILE"

# 验证：确认关键表在备份文件里能查询
for t in users user_sessions shop_cdk; do
    ROW_COUNT=$(sqlite3 "$OUT_FILE" "SELECT COUNT(*) FROM $t;" 2>/dev/null || echo "ERROR")
    if [ "$ROW_COUNT" = "ERROR" ]; then
        log "ERROR: 备份验证失败，表 $t 不可读，请检查 $OUT_FILE"
        exit 1
    fi
done

# 滚动：保留最近 60 天
find "$OUT_DIR" -name "users_*.db" -mtime +60 -delete 2>/dev/null || true

log "SUCCESS: $OUT_FILE (${SIZE} bytes) | users=$(sqlite3 "$OUT_FILE" 'SELECT COUNT(*) FROM users;') user_sessions=$(sqlite3 "$OUT_FILE" 'SELECT COUNT(*) FROM user_sessions;') shop_cdk=$(sqlite3 "$OUT_FILE" 'SELECT COUNT(*) FROM shop_cdk;')"
