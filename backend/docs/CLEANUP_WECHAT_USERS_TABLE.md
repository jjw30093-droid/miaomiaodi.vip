# wechat_users 表清理计划

> **版本**：2026-04-30  
> **性质**：计划文档，**不执行任何 DROP/DELETE**  
> **背景**：`wechat_users` 是 2026-04-17 前的旧用户存储。Migration 7（`db_migrate.py:214`）已将数据同步到 `users` 表，旧表自此标记 DEPRECATED。当前表保留 4 行历史数据，不再写入新数据。

---

## 当前状态

| 项目 | 现状 |
|------|------|
| 物理表 | 存在，4 行 |
| Schema | `id, openid, is_vip, created_at, vip_expires_at` |
| 写入路径 | **无**（cdk_router.py:150 注释已说明 "以 users 表为准，已废弃 wechat_users"） |
| 读取路径 | 仅 db_migrate.py Migration 7（同步到 users，幂等，无副作用） |
| 独立备份 | `backup_user_data.sh` 仍备份此表（保留历史记录） |

---

## 为什么不立即 DROP

1. **数据安全期**：4 行 openid 历史数据是 4 个真实微信用户的身份信息，需确认已 100% 同步到 `users` 表后再删。
2. **Migration 7 幂等保护**：Migration 7 每次启动都会跑一次 `_migrate_wechat_users_to_users()`。若先 DROP 表，Migration 3（`_add_vip_expires_at_to_wechat_users`）在新实例部署时会 `CREATE TABLE IF NOT EXISTS`，重建空表。需要同步删除 db_migrate.py 中相关迁移调用，否则出现"删了又建"循环。
3. **回滚窗口**：按 SOP 保留 30 天窗口确认线上无问题。

---

## 执行前验证清单

在执行清理之前，必须确认以下 **全部通过**：

```bash
# 1. 确认 wechat_users 中所有 openid 都在 users 表中
sqlite3 /home/ubuntu/app/backend/football_uk.db "
SELECT w.openid,
       u.id AS users_id,
       u.vip_expires_at AS users_vip,
       w.vip_expires_at AS wechat_vip
FROM wechat_users w
LEFT JOIN users u ON u.wechat_openid = w.openid
ORDER BY w.id;
-- 期望：users_id IS NOT NULL（无孤儿行）
"

# 2. 确认 vip_expires_at 同步正确（wechat_vip ≤ users_vip）
# 期望：所有行 users_vip >= wechat_vip，或 wechat_vip IS NULL

# 3. 确认近 30 天无写入
sqlite3 /home/ubuntu/app/backend/football_uk.db "
SELECT MAX(created_at) FROM wechat_users;
-- 期望：早于 2026-04-17（DEPRECATED 日期）
"
```

---

## 执行步骤（计划，待人工批准）

### Step 1：备份

```bash
# 在清理前做一次专项备份（timestamp 标记）
BACKUP_PATH=/home/ubuntu/app/backend/backups/wechat_users_final_$(date -u +%Y%m%d).db
sqlite3 /home/ubuntu/app/backend/football_uk.db ".dump wechat_users" | sqlite3 "$BACKUP_PATH"
echo "备份完成：$BACKUP_PATH"
```

### Step 2：修改 db_migrate.py

需要移除（或 stub）两处调用，防止"删了又建"：

**移除 `run_migrations()` 中的两行调用（db_migrate.py:23 和 :28）：**

```python
# 删除以下两行（或注释掉）：
_add_vip_expires_at_to_wechat_users(conn)   # line 23
_migrate_wechat_users_to_users(conn)         # line 28
```

**保留函数体**（Migration 3 和 Migration 7 的函数定义保留，只移除调用），便于审计和紧急回滚参考。

在函数顶部加注释：
```python
# CLEANUP 2026-05-??: 调用已从 run_migrations() 移除，
# wechat_users 表已于 YYYY-MM-DD DROP。函数保留供审计。
```

### Step 3：DROP 物理表

```bash
# 操作前必须停止 backend（防止 migration 重建表）
pm2 stop football-backend

sqlite3 /home/ubuntu/app/backend/football_uk.db "DROP TABLE IF EXISTS wechat_users;"
echo "wechat_users 已删除"

# 重启
pm2 start football-backend
sleep 8
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/  # 期望 200
```

### Step 4：验证

```bash
# 确认表不存在
sqlite3 /home/ubuntu/app/backend/football_uk.db ".tables" | tr ' ' '\n' | grep wechat_users
# 期望：空（无输出）

# 确认 migration 不会重建
pm2 logs football-backend --lines 30 --nostream | grep wechat_users
# 期望：无任何输出（migration 调用已移除）
```

### Step 5：更新 backup_user_data.sh

移除 `backup_user_data.sh` 的 TABLE 列表中的 `wechat_users`：

```bash
# 找到该行并编辑
grep -n "wechat_users" /home/ubuntu/app/backend/scripts/backup_user_data.sh
# 从 TABLES 变量中删除 "wechat_users"
```

---

## 回滚方案

若执行后出现问题，30 天内可从备份恢复：

```bash
# 恢复 wechat_users
BACKUP_PATH=/home/ubuntu/app/backend/backups/wechat_users_final_YYYYMMDD.db
sqlite3 "$BACKUP_PATH" ".dump wechat_users" | sqlite3 /home/ubuntu/app/backend/football_uk.db
echo "wechat_users 已恢复"
```

同时需要在 `db_migrate.py:run_migrations()` 中恢复两行调用。

---

## 执行时间窗口建议

| 条件 | 建议时间 |
|------|----------|
| 执行前验证清单全部通过 | ✅ |
| 距 DEPRECATED（2026-04-17）至少 30 天 | 2026-05-17 之后 |
| 选择业务低峰 | UTC 10:00-16:00（北京 18:00-00:00 次日）|

**建议执行日期：2026-05-17 UTC 12:00 之后**，运营确认无异常后操作。
