# 用户数据回滚 SOP — 业务库回滚时保留用户数据

> **适用场景**：某次业务数据出 bug，需要把 `football_uk.db` 回滚到昨天的备份，  
> 同时**不丢失**今天的注册用户、VIP 兑换、设备会话等用户数据。
>
> **版本**：2026-04-30  
> **维护人**：运营/Claude

---

## 前置说明

| 数据目录 | 内容 | 备份频率 |
|---------|------|---------|
| `backend/backups/` | 完整业务库（含用户数据），由 pm2 `job-db-backup` 自动备份 | 每日 |
| `backend/user_backups/` | 用户系统表独立备份（轻量，60K 级） | 每日 19:00 UTC（cron）|

用户系统表清单（独立备份覆盖的表）：
- `users` — 用户账号
- `user_sessions` — 设备会话 / jti 白名单
- `shop_cdk` — CDK 卡密
- `admin_audit_log` — 管理审计
- `user_meta` — 用户 quota
- `user_unlocks` — 解锁记录
- `wechat_users` — 旧表（deprecated，有历史数据）

---

## 操作步骤

### Step 0：评估影响

```bash
# 确认要回滚到哪个业务备份
ls -lh /home/ubuntu/app/backend/backups/ | tail -5

# 确认用户独立备份最新时间
ls -lh /home/ubuntu/app/backend/user_backups/
cat /home/ubuntu/app/backend/user_backups/backup.log | tail -5
```

**决策原则**：
- 若业务库 bug 发生在今天，回滚到昨天业务备份 + 今天用户备份（最晚 19:00 UTC）
- 用户备份比业务备份晚 → 直接覆盖用户表即可
- 用户备份比业务备份早 → 评估期间是否有新注册/VIP 兑换，再决定是否手动补数据

---

### Step 1：停止所有进程

```bash
pm2 stop football-backend football-frontend
pm2 list | grep -E "online|errored"
# 期望：两个进程都 stopped
```

---

### Step 2：备份当前"出事现场"

```bash
INCIDENT_TS=$(date -u +%Y%m%d_%H%M%S)
cp /home/ubuntu/app/backend/football_uk.db \
   /home/ubuntu/app/backend/football_uk.db.incident_${INCIDENT_TS}
echo "事故现场已备份：football_uk.db.incident_${INCIDENT_TS}"
```

---

### Step 3：恢复昨天的业务库

```bash
# 找到目标备份文件（按需替换 YYYYMMDD）
BACKUP_FILE=$(ls /home/ubuntu/app/backend/backups/football_uk_*.db 2>/dev/null | sort | tail -2 | head -1)
echo "将恢复：$BACKUP_FILE"

# 恢复
cp "$BACKUP_FILE" /home/ubuntu/app/backend/football_uk.db
echo "业务库已恢复"

# 验证基本完整性
sqlite3 /home/ubuntu/app/backend/football_uk.db "SELECT COUNT(*) FROM dim_match;" 2>&1
```

---

### Step 4：用用户独立备份覆盖用户表

> 仅覆盖用户系统相关表，业务数据（dim_match / report_store 等）完全不动。

```bash
# 找最新用户备份
USER_BACKUP=$(ls /home/ubuntu/app/backend/user_backups/users_*.db 2>/dev/null | sort | tail -1)
echo "用户备份：$USER_BACKUP"

# 逐表导入（DROP + 重建）
for TABLE in users user_sessions shop_cdk admin_audit_log user_meta user_unlocks wechat_users; do
    ROW_COUNT=$(sqlite3 "$USER_BACKUP" "SELECT COUNT(*) FROM $TABLE;" 2>/dev/null || echo "NOT_FOUND")
    if [ "$ROW_COUNT" = "NOT_FOUND" ]; then
        echo "跳过 $TABLE（用户备份中不存在）"
        continue
    fi
    echo "导入 $TABLE（${ROW_COUNT} 行）..."
    # 从用户备份导出该表的 schema + 数据
    sqlite3 "$USER_BACKUP" ".dump $TABLE" | sqlite3 /home/ubuntu/app/backend/football_uk.db
done
echo "用户表导入完成"
```

**注意**：`.dump` 已包含 `DROP TABLE IF EXISTS` + `CREATE TABLE` + `INSERT`，会完整替换该表内容。

---

### Step 5：验证用户表行数与预期一致

```bash
echo "=== 生产库用户表行数 ==="
for TABLE in users user_sessions shop_cdk admin_audit_log user_meta user_unlocks; do
    PROD_COUNT=$(sqlite3 /home/ubuntu/app/backend/football_uk.db "SELECT COUNT(*) FROM $TABLE;" 2>/dev/null || echo "ERROR")
    BKP_COUNT=$(sqlite3 "$USER_BACKUP" "SELECT COUNT(*) FROM $TABLE;" 2>/dev/null || echo "N/A")
    echo "  $TABLE: 生产=${PROD_COUNT}  备份=${BKP_COUNT}  $([ "$PROD_COUNT" = "$BKP_COUNT" ] && echo '✅' || echo '⚠️ 不一致')"
done
```

期望：所有表行数与用户备份一致（不一致时检查是否 wechat_users 等 deprecated 表）。

---

### Step 6：启动服务

```bash
pm2 start football-backend
sleep 5
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/  && echo " backend OK"

pm2 start football-frontend
sleep 5
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000   && echo " frontend OK"

pm2 logs football-backend --lines 20 --nostream | grep -iE "error|exception|fatal" | head -5 || echo "no errors"
```

---

### Step 7：smoke test 用户功能

```bash
# 1. 获取一个现有用户的 jti（session 是否恢复）
sqlite3 /home/ubuntu/app/backend/football_uk.db \
  "SELECT user_id, jti, created_at FROM user_sessions WHERE revoked_at IS NULL LIMIT 3;"

# 2. 确认 VIP 用户 vip_expires_at 已恢复（不为 NULL）
sqlite3 /home/ubuntu/app/backend/football_uk.db \
  "SELECT id, nickname, role, vip_expires_at FROM users WHERE role='vip';"

# 3. 调用 /api/v1/reports/latest 确认业务数据可读
curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/api/v1/reports/latest" && echo ""
```

---

## 可能遇到的问题

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 业务库恢复后用户无法登录 | user_sessions jti 不在恢复后的白名单里 | 正常，用户重新登录即可签发新 jti |
| user_sessions 恢复后被踢 | MAX_DEVICES=1，旧 jti 已过期 | 正常，用户重新登录 |
| `sqlite3 .dump` 报表不存在 | 用户备份比业务库旧，表结构变化 | 检查 db_migrate.py 版本，手动 migrate |
| 业务库 WAL 文件残留 | 未 `checkpoint` 就复制 | 先 `sqlite3 db "PRAGMA wal_checkpoint(FULL);"` 再复制 |

---

## 自动备份检查命令

```bash
# 确认独立备份 cron 正在运行
sudo crontab -l | grep backup_user_data

# 手动触发一次备份
/home/ubuntu/app/backend/scripts/backup_user_data.sh

# 检查备份日志
tail -10 /home/ubuntu/app/backend/user_backups/backup.log
```
