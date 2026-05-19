# 喵弟量化研究所 — 生产服务器总守则

> **本文件不得删除。** 每条规则都来自真实事故。

---

## 🚨 §0 双站定位（长期不变，所有改动必须遵守）

本账号下两个站点职责严格分离，**任何新功能开发前必须先判定归属**：

| 站点 | 定位 | 内容方向 |
|------|------|----------|
| **miaomiaodi.cc** | GEO / SEO 优化、品牌露出 | 免费公开内容、流量入口、品牌资产 |
| **miaomiaodi.vip** | 知识付费（延续 .cc 现有付费内容） | 会员体系、付费产品、订阅、社群 |

### 共同约定

- 数据资产（如 wc_* 表、模型预测、量化研究数据）**两站共享，不重复落库**
- 数据源站点：暂定 miaomiaodi.cc 物理 host，通过内部 HTTP API 供 .vip 调用
- 免费 / 流量 / SEO 功能 → **归 .cc**；付费 / 会员 / 交易功能 → **归 .vip**
- **禁止**在 .cc 上做付费墙、订阅、交易类功能
- **禁止**在 .vip 上做以 SEO / GEO 为目的的公开页

### 跨站改动必须确认（涉及以下任意一项时，改动前先明确归属）

- [ ] 数据库 schema 变更（影响共享数据资产时）
- [ ] 新增 API endpoint（决定暴露在 .cc / .vip / 内部 service）
- [ ] 用户系统 / 鉴权（付费用户 vs 匿名访客的处理路径）
- [ ] 域名 / Cloudflare / Nginx 配置（两站独立但部署在同账号下）

### 过渡期说明（截至本节最后更新日：2026-05-18）

当前 miaomiaodi.vip 尚未建站，所有付费 / 会员 / 交易功能仍运行在 miaomiaodi.cc 上。
本文档中以下章节描述的是过渡期现状，而非长期架构方向：

- `backend/CLAUDE.md §20`（CDK 发卡端点）
- `backend/CLAUDE.md §21`（付费内容三档分层 GUEST / REGISTERED / VIP）
- `frontend/CLAUDE.md` 中 VIP 角色相关渲染逻辑（ROLE_DISPLAY 等）

平移计划：.vip 建站后，上述三项整体迁出 .cc。迁移完成前，这些代码继续维护、
继续遵守现有约定；迁移完成后，本节将更新为"已完成迁移"并指向 .vip 文档。

新功能开发遵循 §0 双站定位的长期方向，不要在 .cc 上新增付费 / 交易类逻辑。

---

## 项目架构一览

```
/home/ubuntu/app/
├── backend/          ← FastAPI + SQLite，Python，port 8000
│   └── CLAUDE.md     ← 后端专项守则（必读）
├── frontend/         ← Next.js App Router，port 3000
│   └── CLAUDE.md     ← 前端专项守则（必读）
└── CLAUDE.md         ← 本文件（全局守则）

域名：miaomiaodi.cc（Cloudflare → Nginx → Next.js/FastAPI）
服务器：AWS Lightsail，Ubuntu，UTC+0
```

---

## 🚨 Rule 1：删 `.next/` = 网站立刻宕机（2026-04-23 事故）

`frontend/.next/` 是 Next.js 生产构建产物。`next start`（pm2 生产模式）**必须依赖它**。

**删了 = 网站挂**，pm2 状态仍显示 `online`，但所有请求无响应。

**修复命令**：
```bash
cd /home/ubuntu/app/frontend
npm run build          # ~5 分钟
pm2 restart football-frontend
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000  # 期望 200
```

**永远不要**在服务器清理脚本、rsync exclude 以外的地方删除 `.next/`。

---

## 🚨 Rule 2：两个进程是网站的命脉，不得随意 stop/kill

| pm2 名称 | 端口 | 说明 |
|----------|------|------|
| `football-backend` | 8000 | FastAPI，API 服务 |
| `football-frontend` | 3000 | Next.js，前端页面 |

Nginx 把流量分发给这两个进程。任意一个挂了网站就挂了。

重启命令（安全顺序）：
```bash
pm2 restart football-backend
pm2 restart football-frontend
# 验证
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000
```

---

## 🚨 Rule 3：唯一生产数据库是 football_uk.db

```
/home/ubuntu/app/backend/football_uk.db   ✅ 唯一真源，~106MB（2026-04-27 实测）
/home/ubuntu/app/football_uk.db           ⚠️  0-byte 空壳文件，历史残留，清理候选（勿读写）
/home/ubuntu/app/backend/football_data.db ❌ 旧测试库，废弃
```

`.env` 中必须：`DB_PATH=/home/ubuntu/app/backend/football_uk.db`

**备份目录**：`backend/backups/`，自动每日备份，**不得删除**。

### 生产库 Schema 变更记录（2026-04-23）

| 表 | 变更 | 说明 |
|----|------|------|
| `report_store` | `ADD COLUMN version TEXT DEFAULT 'v3'` | 研报三版本标签（v1/v2/v3），历史 300 行回填 v3 |
| `ingest_failure_log` | 新建表 | 脚本失败持久化，含索引 idx_ingest_failure_match / idx_ingest_failure_unresolved |

`ingest_failure_log` schema：
```sql
CREATE TABLE ingest_failure_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  script_name TEXT NOT NULL,
  match_id TEXT,
  step TEXT,           -- 'fetch' | 'parse' | 'insert' | 'audit'
  error_msg TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  resolved INTEGER DEFAULT 0
);
```

---

## 🚨 Rule 4：时区统一用 UTC

服务器时区 `Etc/UTC`，所有时间字段存 UTC：
- `dim_match.Date` = UTC 开球日期（`YYYY-MM-DD`）
- `report_store.match_time` = UTC 开球时间（`YYYY-MM-DD HH:MM:SS`）
- `prediction_audit.match_date` = UTC 开球日期

**Fotmob API 按 CST 分桶**——查询 UTC 日期 `20260422` 会返回 CST 4/22 的比赛（含 UTC 4/21 晚上的欧洲场次）。解析时必须用 `status.utcTime` 字段取 UTC 日期，不能直接用查询日期 `d`。

**API 查询日期必须用 CST**：`batch_fotmob_sync.py` / `fotmob_scheduler.py` 传给 Fotmob API 的 `date=YYYYMMDD` 参数必须用 `datetime.now(CST)` 生成（CST = UTC+8）；入库字段仍用 UTC（不动 `status.utcTime` 解析）。

---

## 清理服务器时的豁免清单（永远不删）

```
/home/ubuntu/app/frontend/.next/         ← 生产构建，删了宕机
/home/ubuntu/app/frontend/node_modules/  ← npm 依赖（34,877 文件，正常）
/home/ubuntu/app/backend/venv/           ← Python 环境（22,537 文件，正常）
/home/ubuntu/app/backend/football_uk.db  ← 生产数据库
/home/ubuntu/app/backend/backups/        ← 数据库备份
/home/ubuntu/app/backend/models_v4/      ← ML 模型
/home/ubuntu/app/backend/logs/           ← 日志（自动轮转管理）
/home/ubuntu/app/backend/CLAUDE.md       ← 本守则
/home/ubuntu/app/frontend/CLAUDE.md      ← 前端守则
/home/ubuntu/app/CLAUDE.md               ← 本文件
```

---

## 磁盘清理安全白名单（可以删的）

```bash
find /home/ubuntu/app -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
find /home/ubuntu/app -name "*.pyc" -delete
find /home/ubuntu/app -name ".DS_Store" -delete
find /home/ubuntu/app/backend -name "*.bak*" -not -name "*.db*"  # 代码备份（不含DB备份）
```

---

## 本地 ↔ 服务器同步

**服务器 → 本地**（拉代码）：
```bash
rsync -avz --progress \
  -e 'ssh -i ~/Downloads/LightsailDefaultKey-ap-northeast-1.pem' \
  --exclude='venv/' --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' \
  --exclude='logs/' --exclude='backups/' --exclude='.env' \
  --exclude='__pycache__/' --exclude='*.pyc' --exclude='odds/' \
  --exclude='reports/' --exclude='schedule/' --exclude='chrome_bot_profile/' \
  --exclude='node_modules/' --exclude='.next/' --exclude='.git/' \
  --exclude='*.pkl' --exclude='*.lgb' --exclude='*.bak' \
  ubuntu@54.168.246.157:/home/ubuntu/app/ \
  /Users/wanglujun/Desktop/Football_Data_Lake/
```

**本地 → 服务器**（推代码，部署前必须 build）：
```bash
# 1. 推代码
rsync -avz --exclude='node_modules/' --exclude='.next/' --exclude='venv/' \
  --exclude='*.db' --exclude='.env' \
  /Users/wanglujun/Desktop/Football_Data_Lake/frontend/ \
  ubuntu@54.168.246.157:/home/ubuntu/app/frontend/

# 2. 服务器上重新构建
ssh ubuntu@54.168.246.157 "cd /home/ubuntu/app/frontend && npm run build && pm2 restart football-frontend"
```

---

## 紧急故障排查顺序

```bash
# 1. 检查两个主进程
pm2 list | grep -E "football-backend|football-frontend"

# 2. 检查本地响应
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000

# 3. 检查 nginx
sudo nginx -t && sudo systemctl status nginx

# 4. 查最新错误日志
pm2 logs football-backend --lines 30 --nostream
pm2 logs football-frontend --lines 30 --nostream

# 5. 如果前端 3000 不通，先检查 .next 是否存在
ls /home/ubuntu/app/frontend/.next/ || echo "需要 npm run build！"
```

---

## 🚨 Rule 6：pm2 重启命令按改动类型选择（2026-04-30 事故）

**背景**：`ecosystem.config.js` 中读取 `.env` 的代码只在 PM2 **首次创建进程**时执行一次。`pm2 restart` 复用已加载的进程定义（含已注入的 env vars），**不重读 `.env` 文件**。改了 `.env` 内容以为重启就生效，实际进程仍跑旧 env——花 30 分钟才排查出"为什么 SUPER_ADMIN_JWT_SECRET 未配置"。

| 改动类型 | 正确命令 |
|----------|----------|
| 只改 `.py` / `.ts` 代码 | `pm2 restart football-backend` |
| 改了 **`.env` 内容** | `pm2 startOrRestart ecosystem.config.js --only football-backend --update-env` |
| 改了 **`ecosystem.config.js`** 本身 | `pm2 delete football-backend && pm2 start ecosystem.config.js --only football-backend` |

**改完记得 `pm2 save`**，否则服务器重启后配置丢失。

```bash
# 验证 env var 是否真的生效（以 SUPER_ADMIN_JWT_SECRET 为例）
pm2 env 1 | grep SUPER_ADMIN  # 1 是 football-backend 的 pm2 id
```

---

## 🚨 Rule 7：nginx server 级 if 早于 location 匹配，路径例外必须用 set 变量法（2026-04-30 事故）

**背景**：为防止攻击者绕过 Cloudflare 直连 origin，在 nginx server 块加了 `if ($cf_or_local = 0) { return 403; }`。预期 `location ^~ /.well-known/acme-challenge/` 能豁免 LE 续证路径，实际 LE challenge 也被 403 拦截。

**根因**：nginx `if` 在 **rewrite phase** 执行，早于 location 匹配阶段。`location ^~` 的高优先级只影响 location 选择，无法覆盖更早执行的 server 级 `if return`。

**铁律**：需要"全局拦截 + 路径例外"时，**禁止**直接写 `if (condition) { return 403; }`，必须用三段 set 变量法：

```nginx
# ✅ 正确：三段 set 变量法（nginx 官方认可的多条件模拟模式）
set $block 0;
if (全局拦截条件) {
    set $block 1;          # 标记：想拦截
}
if (例外路径条件) {
    set $block 0;          # 覆盖：豁免例外
}
if ($block = 1) {
    return 403;            # 最终执行拦截
}

# ❌ 错误：单个 if return，location 豁免无效
if (全局拦截条件) {
    return 403;            # 会拦截所有路径，包括 location ^~ 例外
}
```

**实际案例**（`/etc/nginx/sites-available/miaomiaodi.cc`）：
```nginx
set $block_cf 0;
if ($cf_or_local = 0) {          # 非 CF IP → 标记拦截
    set $block_cf 1;
}
if ($request_uri ~* "^/.well-known/acme-challenge/") {  # LE challenge → 豁免
    set $block_cf 0;
}
if ($block_cf = 1) {
    return 403;
}
```
