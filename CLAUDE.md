# 喵弟量化研究所 — miaomiaodi.vip 项目守则

> **本文件不得删除。** 每条规则都来自真实事故。
> vip 站专注付费闭环。基础规则与 cc 站相同（pm2 / nginx / .env / 时区），见下文 §共通规则。

---

## §0 双站定位

| 站点 | 定位 |
|------|------|
| miaomiaodi.cc | GEO / SEO / 引流 |
| **miaomiaodi.vip**（本仓库）| 知识付费、单场研报付费、VIP 套餐、世界杯通票 |

- **禁止**在 .vip 上做以 SEO / GEO 为目的的公开页
- **禁止**在 .cc 上做付费墙、订阅、交易类功能
- 两站历史上 vip 是真身、cc 是 vip 的 fork（用于 GEO 引流）
- 两个仓库代码各自独立，共用 logo 和设计 token

---

## 项目架构一览
/home/ubuntu/app/                      ← 生产服务器路径
├── backend/                           ← FastAPI + SQLite，Python，port 8000
│   ├── sync_router.py                 ← 付费内容物理截断核心，改前必读
│   ├── auth_deps.py                   ← 鉴权链路核心，改前必读
│   └── routers/                       ← 其他业务路由
├── frontend/                          ← Next.js App Router，port 3000
│   ├── app/report/[match_id]/page.tsx ← 研报付费墙核心
│   ├── components/PaywallOverlay.tsx  ← 付费墙 UI
│   └── lib/auth.ts + lib/fetchReport.ts ← 鉴权 + adapter
└── CLAUDE.md                          ← 本文件
本地 Mac 仓库路径：~/projects/miaomiaodi.vip/
GitHub: git@github.com:jjw30093-droid/miaomiaodi.vip.git
域名：miaomiaodi.vip（Cloudflare → Nginx → Next.js/FastAPI）
服务器：AWS Lightsail，Ubuntu，UTC+0

---

## 付费体系核心约束（不可破坏）

### 鉴权链路

- `CurrentUser.is_vip` = `tier == UserTier.VIP`，**禁止**加 `ENABLE_VIP_GATING` 之类的开关回退
- JWT 解码时 `role IN ('vip', 'super_admin')` 才升 tier 到 VIP；REGISTERED 永远不是 VIP
- VIP 过期判断 `vip_expires_at` 在 `make_jwt` 阶段做；`CurrentUser` 侧只看 tier
- 新加端点默认要求登录（`get_current_user`）；开放给 GUEST 必须显式用 `get_optional_user` 并加注释说明理由

### 付费内容物理截断

- 任何返回研报正文的端点必须按 `is_gated` 物理截断 `report_markdown`，**禁止**依赖前端隐藏
- `is_gated` 默认 True，放行条件三选一：
  1. `is_free_match`（report_store.is_free=1）
  2. `user.is_vip` 命中
  3. `user_unlocks` 表对该 user_id + match_id 有记录
- response 必须返回 `is_gated` / `access_level` / `unlock_reason` 三字段给前端
- 前端 PaywallOverlay 必须读 `unlock_reason` 显示差异化文案

### schema 约束

- `users.role` 取值：`'registered' | 'vip' | 'super_admin'`
- `user_unlocks` 当前用 username 关联（脆弱）；新写代码必须 JOIN users 用 user_id 兜底
- 未来 schema 改动：新增 user_id 列 + 保留 username 双写 + 迁移完成后再删

### 改动必读文件

- `backend/auth_deps.py`（鉴权 + JWT 解码）
- `backend/sync_router.py`（付费内容截断）
- `frontend/lib/auth.ts`（NextAuth session callback）
- `frontend/app/report/[match_id]/page.tsx`（accessLevel 计算）
- `frontend/components/PaywallOverlay.tsx`（unlock_reason 渲染）
- `frontend/lib/fetchReport.ts`（adapter 字段映射）

---

## 验证（强制）

### 三必查

```bash
pm2 describe football-frontend | grep cwd
sudo nginx -T | grep -A2 "server_name miaomiaodi.vip"
curl -sI https://miaomiaodi.vip/
```

### 付费回归 6 case（任何鉴权/付费改动必跑）

| Case | 身份 | match | 期望 |
|---|---|---|---|
| 1 | GUEST | paid | `is_gated=true, has_md=false, access_level='guest'` |
| 2 | GUEST | free | `is_gated=false, has_md=true, unlock_reason='free_match'` |
| 3 | REGISTERED | paid | `is_gated=true, has_md=false`（UI 不显示赛后复盘）|
| 4 | REG + user_unlocks 命中 | paid | `unlock_reason='single_unlock', has_md=true` |
| 5 | VIP 未过期 | paid | `access_level='vip', has_md=true` |
| 6 | VIP 已过期 | paid | `is_gated=true, has_md=false`（用 `ENABLE_VIP_GATING=0` 之类的快捷绕过 = FAIL）|

**Case 3 是最容易回归出问题的一档**，push 前必跑。

前端改动：`npm run build` 0 error → `pm2 restart football-frontend` → Cloudflare Purge + 隐私模式核验。
后端改动：相关 API curl 验证 + 6 case 回归。

---

## 支付通道（合规为重）

| 阶段 | 通道 | 状态 |
|---|---|---|
| 一期（含 CDK 兜底）| 爱发电跳转 + CDK 手动开通 | 已有 CDK，爱发电待接 |
| 过渡期 | 虎皮椒（个人微信/支付宝聚合，单笔限 499 元）| 待接 |
| 终态 | Stripe | 等日本银行卡 |

### 合规红线

- **禁止**接第四方聚合支付（央行严打的换码跑分模式）
- 商品名禁用 "博彩 / 赌 / 竞彩 / 盘口 / 赔率"，统一格式 `数据研报-{league}-{date}-{home}vs{away}`
- 单笔金额 > 499 元强制走 Stripe 路径，不走虎皮椒
- 虎皮椒回调必须验证签名，不能裸调
- 备用通道：爱发电链接挂着，虎皮椒挂了不影响收钱

---

## 数据库
/home/ubuntu/app/backend/football_uk.db   ← 主库
/home/ubuntu/app/backend/worldcup.db      ← 世界杯库

`.env` 必须：`DB_PATH=/home/ubuntu/app/backend/football_uk.db`

### 关键表

| 表 | 用途 | 改动注意 |
|---|---|---|
| `users` | 用户主表 | role/vip_expires_at 字段不可随意改语义 |
| `user_sessions` | 多端登录 token | jti 用于踢人 |
| `user_unlocks` | 单场解锁记录 | username 关联（脆弱），新代码用 JOIN user_id |
| `shop_cdk` | CDK 码 | quota / vip_days 双轨 |
| `report_store` | 研报正文 | `is_free` 为 1 时全员可见，`is_archived` 为 1 时归档 |
| `orders` | 订单（Day 2 加）| 待创建 |
| `products` | 套餐 SKU（Day 2 加）| 待创建 |

schema 改动前先 `sqlite3 dump` 当前表，改动后跑 baseline 对比。

---

## 开发工作流（git 流程）
Mac 本地（~/projects/miaomiaodi.vip）
↓ Claude Code 改文件
↓ git add + commit + push（SSH 不要 PAT）
GitHub (jjw30093-droid/miaomiaodi.vip)
↓ ssh 服务器 git pull
Lightsail 生产
↓ npm run build + pm2 restart
↓ Cloudflare Purge + 三必查 + 6 case 回归
线上验证

**禁止**：
- 服务器和 GitHub 同时改文件
- 用 rsync 推代码绕过 git
- HTTPS + PAT（token 明文写进 `.git/config`）
- 6 case 回归没跑就 push

---

## §共通规则（与 cc 一致）

### 🚨 Rule 1：删 `.next/` = 宕机
`frontend/.next/` 是 Next.js 生产构建产物。删了 = 宕机，pm2 仍显示 online 但无响应。修复：`npm run build && pm2 restart football-frontend`。

### 🚨 Rule 2：两个进程是命脉
`football-backend`（8000）和 `football-frontend`（3000），任一挂了网站就挂。

### 🚨 Rule 3：时区统一 UTC
服务器 `Etc/UTC`。`dim_match.Date` / `report_store.match_time` 全部 UTC 存储。Fotmob API 按 CST 查询，解析用 `status.utcTime`。

### 🚨 Rule 6：pm2 重启命令按改动类型
- 代码改动：`pm2 restart football-backend`
- `.env` 改了：`pm2 startOrRestart ecosystem.config.js --only football-backend --update-env`
- `ecosystem.config.js` 改了：`pm2 delete && pm2 start`
- 改完 `pm2 save`

### 🚨 Rule 7：nginx server 级 if 用三段 set 变量法
```nginx
set $block 0;
if (全局拦截) { set $block 1; }
if (例外路径) { set $block 0; }
if ($block = 1) { return 403; }
```

---

## 永远不删
/home/ubuntu/app/frontend/.next/
/home/ubuntu/app/frontend/node_modules/
/home/ubuntu/app/backend/venv/
/home/ubuntu/app/backend/football_uk.db
/home/ubuntu/app/backend/worldcup.db
/home/ubuntu/app/backend/backups/
/home/ubuntu/app/backend/models*/
/home/ubuntu/app/backend/logs/
**/CLAUDE.md

---

## 紧急故障排查

```bash
pm2 list | grep -E "football-backend|football-frontend"
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000
sudo nginx -t && sudo systemctl status nginx
pm2 logs football-backend --lines 30 --nostream
pm2 logs football-frontend --lines 30 --nostream
```

付费相关故障：先跑 6 case 看哪个 case 不通过，定位是鉴权层还是 gating 层。

---

## §Claude Code 自动化守则(2026-05-20 立)

这套规则来自 Day 1-2 的真实违规事故。每条都必须遵守,违反一次记录在案。

### Rule 1: raw stdout 必须贴全

对 cat / sed / grep / ls / wc / find / git log / curl / sqlite3 等只读类命令,
执行后必须**逐字贴 raw stdout**,不允许任何形式的替代:

禁止的输出模式:
- "已贴""见上方""完整内容如前"
- "全文如下:" 后接 3 行摘要
- 表格汇总: "| Step | 期望 | 实测 |" 替代真实终端文字
- "結果まとめ:" 类日语/中文汇总
- "全 X case pass" 不附 raw stdout

允许的输出模式:
- 命令前打印 ===== 命令N: 描述 =====
- 命令的真实 stdout/stderr 完整粘贴
- 命令之间用 ===== 分隔符隔开

### Rule 2: 空 ===== 标记 ===== = 严重违规

如果用户要求"分 N 段输出",每段 ===== 后必须有真实内容。
出现 "===== N =====" 后接空行或仅有"等待用户决策"类文字 = 严重违规。

### Rule 3: 明确动词授权制(MOST IMPORTANT)

只有用户 prompt 中**明确出现下列动词**时,才允许执行对应操作:

| 用户必须说出的词 | 才能执行 |
|---|---|
| "改 / modify / 修改 / 编辑 / 写入" | 写文件 / sed -i |
| "git add" | git add |
| "commit" | git commit |
| "push" | git push |
| "deploy / 部署 / pm2 restart" | 远程部署 |
| "build / npm run build" | 跑构建 |
| "rm / 删 / delete" | 删除文件 |

未出现对应动词时,严禁执行。"看 / 摸 / 摸现状 / 审计 / 摸底 / 调研 / read" 永远只允许只读。

### Rule 4: 只读任务严禁顺便改

接到 cat / grep / sed -n / sqlite3 SELECT 等只读指令时,
**不允许在同一回合里修改任何文件**,即使发现明显 bug 也只能在回复里报告,不动手。

### Rule 5: 改代码必走 git

绝对禁止:
- ssh 服务器后用 vim/nano/sed -i 直接改服务器文件
- 用 scp/rsync 把本地改动推到服务器
- 服务器上 git stash 用户没改过的本地变更

唯一允许的链路:
本地 Mac 改 → git add + commit + push → ssh server → git pull → npm build → pm2 restart

### Rule 6: 持久化输出文件必须读

当 Bash tool 输出含 `persisted-output` 标签或类似截断提示时:
1. 用 Read tool / cat 读取该 file 完整内容
2. 贴 raw 内容到对话,不许写摘要
3. 文件过长用 sed -n 分段读

### Rule 7: 违规自报

任何一次违规,在下一条回复开头必须用一行声明:
"违规自报: Rule N - 具体行为"
不允许隐瞒、辩护、用日语切换话题。

## 红线

1. 不在前端做付费判断（前端隐藏不算保护，后端必须物理截断）
2. 不引入"登录即 VIP"、"测试期全免费"之类的全局开关
3. 不在 git 历史里留 password_hash dump 或 JWT_SECRET
4. 涉及虎皮椒回调必须验签
5. 不验证就宣告"完成"/"已部署"
6. 改一处顺手破坏精调过的样式 / 参数 / class
7. `.env` / `*.db` / 模型文件不进 git
8. SSH key / token 不出现在对话或 git 历史
9. 改鉴权 / 付费代码不跑 6 case 回归直接 push = 严重违规