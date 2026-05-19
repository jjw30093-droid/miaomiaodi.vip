# miaomiaodi.cc 上线前 Site Audit — 阶段 1 信息收集报告

> 生成时间：2026-04-29 UTC | 审计范围：只读，不涉及任何修改
> 目标读者：外部 reviewer，10 分钟掌握全貌

---

## 1. 项目结构 & 技术栈

### 顶层目录树（深度 2–3，已忽略 node_modules / .next / venv / __pycache__ / .git）

```
/home/ubuntu/app/
├── CLAUDE.md                   ← 全局运维守则
├── backend/                    ← Python FastAPI 后端（port 8000）
│   ├── api_server.py           ← 主入口，路由挂载 + CORS + Middleware
│   ├── ecosystem.config.js     ← PM2 进程定义（17 个 app/cron）
│   ├── auth_deps.py            ← JWT 签发 / 解析 / 三级 UserTier
│   ├── wechat_auth_router.py   ← 微信验证码登录主逻辑
│   ├── cdk_router.py           ← CDK 发卡 / 兑换
│   ├── report_router.py        ← 研报列表 / 付费隔离
│   ├── sync_router.py          ← 内部 payload 同步（X-Sync-Token）
│   ├── user_router.py          ← 用户资料 / 设备会话管理
│   ├── model_health_router.py  ← 模型健康快照
│   ├── review_router.py        ← 赛后复盘 Admin 接口
│   ├── rate_limit.py           ← 内存固定窗口限流工具
│   ├── football_uk.db          ← 唯一生产 SQLite 数据库（223 MB）
│   ├── models_v4/              ← 当前生产模型（LightGBM WDL/OU + CatBoost Lambda）
│   ├── models_v5_lambda/       ← v5 影子模型（4 × CatBoost Poisson）
│   ├── calibration/            ← 联赛偏置 / 温度缩放校准
│   ├── v5_feature_engineering/ ← 双 Poisson 特征工程脚本
│   ├── scripts/                ← cron 辅助脚本（backup、shadow_predict 等）
│   ├── deploy/
│   │   └── nginx.conf          ← 样板（实际配置在 /etc/nginx/sites-available/）
│   ├── backups/                ← 每日 DB 备份（30 天滚动）
│   └── logs/                   ← PM2 日志（自动轮转）
├── frontend/                   ← Next.js 16 前端（port 3000）
│   ├── app/                    ← App Router 页面
│   ├── components/             ← React 组件
│   ├── lib/                    ← auth.ts（NextAuth）、fetchReport、leagueNames
│   ├── hooks/
│   ├── types/
│   └── public/                 ← 静态资源（logo、SVG，无 manifest.json）
└── backend/frontend/           ← ⚠️ 与 /home/ubuntu/app/frontend/ 路径重叠（历史遗留同名目录）
```

> **注意**：`/home/ubuntu/app/backend/frontend/` 是一个旧的 frontend 副本（有自己的 `.git`、`package.json`、`CLAUDE.md`），与 `/home/ubuntu/app/frontend/` 是不同目录。PM2 `football-frontend` 实际指向 `/home/ubuntu/app/frontend/`（通过 `cwd: '/home/ubuntu/app/frontend'`）。两个目录同时存在可能造成混淆。

### 前端技术栈

| 项目 | 版本 |
|------|------|
| Next.js | **16.2.1**（App Router） |
| React | 19.2.4 |
| TypeScript | ^5 |
| Tailwind CSS | v4（@tailwindcss/postcss） |
| next-auth | 5.0.0-beta.30（CredentialsProvider，wechat + credentials 两种）|
| SWR | 2.4.1（客户端数据请求） |
| ECharts | 6.0.0 + echarts-for-react 3.0.6（图表） |
| Framer Motion | 12.38.0（动画） |
| lucide-react | ^1.6.0（图标） |
| react-markdown | ^10 + remark-gfm（研报 Markdown 渲染） |
| sqlite / sqlite3 | 5.1.1 / 6.0.1（Next.js Route Handler 直连后端 DB 的依赖，实际未确认是否启用） |

UI 库：无第三方 Mobile UI 框架，完全自写组件 + Tailwind。状态管理：SWR（服务端状态） + React useState/useContext（本地）。主题：自写 ThemeProvider + localStorage 持久化。

### 后端技术栈

| 项目 | 版本 |
|------|------|
| FastAPI | 0.135.2 |
| Uvicorn | 0.42.0（ASGI） |
| python-jose | JWT 签发/验证（HS256） |
| LightGBM | 4.6.0（WDL / OU 模型） |
| CatBoost | 未在 requirements.txt 中明确列出（模型文件 `.cbm` 存在）|
| SQLite | 内置（无 ORM，全量原生 `sqlite3` 调用） |
| httpx | 0.28.1（异步 HTTP 调用微信 API） |
| DrissionPage | 4.1.1.2（Chrome 浏览器自动化抓赔率） |
| LangChain / LangGraph | 最新版（LLM 研报生成） |
| google-genai / openai | Gemini + OpenAI 双通道 |

**是否 Monorepo？** 否，前后端是两个独立进程。无 BFF 层——前端通过 nginx `location /api/ → 127.0.0.1:8000` 透传到 FastAPI；Next.js 本身不做数据聚合，`next.config.ts` 里配置了 `rewrites` 把 `/api/v1/` 打到后端。

> **reviewer 直觉：看起来 OK**。技术栈清晰，前后端分离。唯一提醒：`next-auth@5.0.0-beta.30` 仍为 beta 版本，有潜在 breaking change 风险；`sqlite` 出现在前端依赖中，需 confirm 是否有直连 DB 的路由。

---

## 2. 部署 & 基础设施

### AWS 资源（代码推断）

- **EC2/Lightsail**：`AWS_PEM_KEY=/home/ubuntu/.ssh/LightsailDefaultKey-ap-northeast-1.pem` → 东京区域 Lightsail 实例
- **对象存储**：requirements.txt 含 `minio==7.2.20`，但 .env 中无 MinIO/S3 endpoint 配置；未确认是否启用
- **RDS/CloudFront/Route53**：代码中无 RDS/CloudFront 引用；DNS 由 Cloudflare 管理（见下）

### Nginx 配置（实际：`/etc/nginx/sites-available/miaomiaodi.cc`）

```nginx
# 路由规则（简化）：
location /api/auth/      → 127.0.0.1:3000  (NextAuth 内部路由，必须先于 /api/)
location /static/        → 127.0.0.1:8000  (静态资源，Cache 30d immutable)
location /api/           → 127.0.0.1:8000  (FastAPI，超时 120s，body ≤ 5MB)
location /               → 127.0.0.1:3000  (Next.js)

gzip on;
# SSL: /etc/letsencrypt/live/miaomiaodi.cc/fullchain.pem
```

⚠️ nginx 未配置任何 `limit_req` / `limit_conn`，限流完全依赖应用层内存计数器。

### Cloudflare

- 接入层：Cloudflare 橙云代理（代码内 `rate_limit.py` 优先读取 `CF-Connecting-IP` Header，确认 CF 是前置代理）
- 回源：Cloudflare → nginx（443）→ 后端进程
- Cloudflare 具体配置（WAF Rules、Bot Fight Mode、Cache Rules）：**未在仓库中找到 `wrangler.toml` 或导出的 Cloudflare 配置，需 confirm**

### HTTPS 证书

- **Let's Encrypt + Certbot** 自动管理
- 证书：`miaomiaodi.cc` + `www.miaomiaodi.cc`（ECDSA 算法）
- **到期时间：2026-07-26**（距今约 87 天），certbot 应已配置自动续签，需 confirm cron 是否正常

### 启动方式

- **PM2**（`ecosystem.config.js`）管理所有进程（2 个常驻 + 15 个 cron/daemon）
- 开机自启：需 `pm2 startup` + `pm2 save`。**未在仓库中找到 systemd unit 文件，需 confirm** 服务器重启后是否自动拉起 PM2

### DB & 备份策略

- 每日 18:00 UTC（北京时间次日 02:00）运行 `scripts/backup_db.sh`
- 使用 SQLite `backup()` API（WAL 安全），保留 30 天滚动 + 每周日独立保存 weekly/
- 当前最新备份：`football_uk_20260429_180000.db`
- **无远程备份**（S3/MinIO 未确认），全部备份在本机 `backend/backups/`，单点故障风险

> **reviewer 直觉：有 risk**。①nginx 缺 `limit_req`；②备份仅在本机，未确认异地；③Let's Encrypt 自动续签需 confirm；④PM2 开机自启需 confirm。

---

## 3. 用户系统

### 认证方式

**微信公众号验证码登录**（主流程）：用户将网页显示的 4 位验证码发送到微信公众号，后端 Webhook 收到后绑定 OpenID → 下发 JWT。

### 完整登录时序

```
① 用户点击「微信扫码」
   前端: WeChatCodeCard.tsx → POST /api/v1/auth/wechat/code
   后端: wechat_auth_router.py:_create_wechat_code() 生成 4 位码 + UUID session_id
         写入内存 _sessions 字典（5 分钟 TTL）
   响应: { session_id, code, expires_in: 300 }

② 网页展示 code，引导用户发送到公众号
   前端: WeChatCodeCard.tsx setInterval 每 2s 轮询 /api/v1/auth/wechat/poll/{session_id}

③ 用户向公众号发送验证码
   微信平台 → POST /api/v1/auth/wechat/webhook（含 SHA1 签名验证）
   后端: wechat_auth_router.py:_wechat_webhook_message()
         → 匹配 _sessions 中的 code
         → 将 openid 写入 session，标记 verified=True
         → INSERT OR IGNORE INTO users (openid) 创建用户记录
         → 向公众号回复「验证成功」

④ 前端轮询命中 verified=True
   后端: wechat_auth_router.py:_poll_wechat_session()
         → 查 users 表 (id, role, nickname, avatar_url, vip_expires_at)
         → 调 issue_session_token() 写 user_sessions 表（jti + 设备信息）
         → make_jwt() 签发 HS256 JWT（30 天有效期）
         → 返回 { status: "confirmed", token: "<JWT>" }
   文件: auth_deps.py:make_jwt() / issue_session_token()

⑤ 前端用 JWT 完成 NextAuth 登录
   前端: WeChatCodeCard.tsx:90 → signIn('wechat', { api_token: data.token })
   文件: lib/auth.ts:CredentialsProvider('wechat').authorize()
         → parseApiJwt() 解析 JWT payload（不验签，SSR 内网可信）
         → 返回 NextAuth User 对象（含 role / apiToken / jti）
         → NextAuth 回调 jwt() → session() 把 apiToken 写入 NextAuth session cookie

⑥ 后续请求携带凭证
   前端: NextAuth session（httpOnly cookie） + 请求时从 session 取 apiToken 写入 Authorization: Bearer <JWT>
   后端: auth_deps.py:get_optional_user() / get_current_user() 验证 JWT + jti 白名单
```

### 「必须关注公众号」校验逻辑

**当前代码中不存在强制关注公众号的拦截**。任何能向公众号发消息（包括未关注的用户用临时会话）的人都可以完成验证。`wechat_auth_router.py` 中无 `event=subscribe` 的检查。若业务上要求"必须关注才能登录"，**需 confirm 是否有 Cloudflare Worker 或外部拦截层实现此逻辑**。

> ⚠️ **需 follow-up**：若运营依赖「关注公众号」增粉，当前代码不满足此要求。

### Session 有效期 / Token 过期 / Refresh

- FastAPI JWT 有效期：**30 天**（`JWT_EXPIRE_DAYS=30`，`auth_deps.py:45`）
- NextAuth session cookie：策略 `jwt`，过期跟随 `AUTH_SECRET` + NextAuth 内部配置（lib/auth.ts 未显式设 `maxAge`，NextAuth 默认 30 天）
- **无 Refresh Token 机制**：JWT 过期后用户需重新微信验证码登录
- jti 白名单：每次请求通过 `get_optional_user()` 查 `user_sessions` 表，`revoked_at IS NOT NULL` 则立刻失效
- 多设备限制：`MAX_DEVICES_PER_USER=2`，超出则踢出最早登录设备

### 用户表 Schema（`users` 表，主表）

| 字段 | 类型 | 用途 |
|------|------|------|
| id | INTEGER PK AUTOINCREMENT | 用户数字 ID |
| openid | TEXT UNIQUE NOT NULL | 微信 OpenID，系统唯一凭证 |
| nickname | TEXT DEFAULT '足球探索者' | 显示昵称（用户可自改） |
| avatar_url | TEXT DEFAULT '' | 头像 URL |
| role | TEXT DEFAULT 'registered' | `registered` / `vip` / `admin` |
| vip_expires_at | DATETIME | VIP 到期（ISO-8601 UTC），NULL = 非 VIP |
| created_at / updated_at | DATETIME | 时间戳 |
| preferences | TEXT DEFAULT '{}' | JSON 用户偏好 |
| nickname_lower | TEXT | 昵称小写（用于搜索）|

> ⚠️ **旧表 `wechat_users` 仍存在**（字段：openid, is_vip, vip_expires_at），代码注释标注 `DEPRECATED 2026-04-17`，但数据库未删除。需 confirm 是否有残留代码读写此表。

### 退出登录 / 踢下线

- 退出：`POST /api/v1/user/logout` → 在 `user_sessions` 表 `revoked_at=now()`，下次请求时 jti 校验失败返回 GUEST
- 踢下线：`DELETE /api/v1/user/sessions/{target_jti}`（用户可主动踢出其他设备）
- 自动踢出：登录超过 MAX_DEVICES(=2) 台时，踢出最早登录的 jti

> **reviewer 直觉：看起来 OK**。登录流程完整，jti 白名单机制防止 token 泄露后滥用。需 follow-up：① 强制关注公众号逻辑缺失；② `wechat_users` 旧表清理。

---

## 4. 付费 & 会员

### 会员等级模型

| 等级 | role 字段值 | 判定条件 |
|------|------------|---------|
| 普通注册用户 | `registered` | 登录即有 |
| VIP | `vip` | `role='vip'` AND `vip_expires_at > now()` |
| 管理员 | `admin` | `role='admin'`（等同 VIP 访问权限，user_id=0 虚拟超管）|

VIP 等级定义在 `users.role` + `users.vip_expires_at`，无月卡/年卡区分（统一按天数累加）。

### CDK 表结构（`shop_cdk`）

| 字段 | 类型 | 用途 |
|------|------|------|
| id | INTEGER PK | 自增 |
| code | TEXT UNIQUE | 兑换码（10 位大写字母+数字，剔除 O/0/I/1） |
| quota | INTEGER | 点数型额度（向后兼容，现主流为 vip_days） |
| is_used | INTEGER DEFAULT 0 | 是否已使用 |
| used_by | TEXT | 使用者 user_id |
| created_at / expires_at | DATETIME | 创建时间 / 过期时间 |
| vip_days | INTEGER DEFAULT 0 | 兑换后延长的 VIP 天数（7=周卡，30=月卡）|

### CDK 生成 & 防重放

- **生成脚本**：`POST /api/v1/admin/generate-cdks`（`cdk_router.py:270`），需 `X-Admin-Token` Header
- 生成算法：`secrets.choice(_CDK_ALPHABET)` × 10 位（密码学安全随机，空间约 10^15 级别）
- 防碰撞：`UNIQUE` 约束 + 循环重试（最多 100 次）
- **防爆破**：`cdk_router.py:_check_rate_limit()` — 内存固定窗口，同 IP 1 分钟最多 5 次尝试
- 防重放：`BEGIN EXCLUSIVE TRANSACTION` 原子操作校验 + 标记，并发安全
- 前端代理：`frontend/app/api/v1/admin/generate-cdks/route.ts` 服务端代理，不暴露 ADMIN_SECRET_TOKEN 到浏览器

### 私域转账 → CDK 兑换流程

```
① 管理员手动收款（微信/支付宝）
② 调用 POST /api/v1/admin/generate-cdks（X-Admin-Token 鉴权）生成 CDK 码
   文件: cdk_router.py:270, frontend/app/api/v1/admin/generate-cdks/route.ts
③ 通过微信私聊发送 CDK 码给用户
④ 用户登录后 → POST /api/v1/cdk/redeem（JWT 鉴权）
   文件: cdk_router.py:108
   → 校验 CDK 有效性 + 标记已使用
   → 计算新 vip_expires_at（在现有到期基础上累加 vip_days）
   → UPDATE users SET role='vip', vip_expires_at=...
   → 重签 JWT（沿用 jti，不踢下线）
   → 返回新 token，前端调用 signIn() 刷新 NextAuth session
```

### VIP 过期机制

- **请求时实时校验**（不依赖 cron）：`auth_deps.py:get_optional_user()` 每次请求解析 JWT 时检查 `vip_expires_at`，过期则强制降为 `registered`
- 无定期扫描/踢出过期 VIP 的 cron job

### 前端 VIP 判定

- NextAuth session 中存储 `vipExpiresAt` + `role`
- `lib/auth.ts:parseApiJwt()` 在 SSR 层解析 FastAPI JWT payload（不验签）并同步检查 `vip_expires_at`
- 各页面通过 `useSession()` / SSR `auth()` 拿到 `session.user.role` 判定渲染哪一档内容

### 付费功能的 Server 端鉴权点

| 端点 | 文件 | 鉴权依赖 | VIP 要求 |
|------|------|---------|---------|
| `GET /api/v1/quant/{match_id}` | api_server.py:271 | `get_current_user` | 否（登录即可） |
| `GET /api/v1/market/{match_id}` | api_server.py:398 | `get_current_user` | 否 |
| `GET /api/v1/sync/match_payload/{match_id}` | sync_router.py:450 | `get_current_user` | 否（但 VIP 字段更多）|
| `GET /api/v1/reports/latest` | report_router.py:219 | `get_optional_user` | 否（GUEST stub，非 VIP inference 截断）|
| `GET /api/v1/reports/daily_free_id` | report_router.py:320 | `get_current_user` | 否 |
| `GET /api/v1/reports/archive/leagues` | report_router.py:358 | `get_current_user` | 否 |
| `GET /api/v1/reports/archive` | report_router.py:378 | `get_current_user` | 否 |
| `GET /api/v1/strategies/equity_curves` | report_router.py:343 | 无（开放） | 否 |
| `GET /api/v1/model/health` | model_health_router.py:235 | `get_current_user` | 否 |
| `GET /api/v1/model/snapshot` | model_health_router.py:252 | `get_current_user` | 否 |

> ⚠️ **需 follow-up**：`GET /api/v1/strategies/equity_curves` 无任何鉴权，任何人（含爬虫）可直接获取模型业绩数据。确认是否为预期公开。

> **reviewer 直觉：有 risk**。CDK 流程机制合理，防重放/防爆破到位。但：① `equity_curves` 端点开放；② 无 VIP-only 的硬鉴权端点（所有付费内容靠字段截断，前端 server 层截断可靠，但需 confirm 无直连 FastAPI 绕过路径）。

---

## 5. 前端 UX（重点：移动端）

### 主要页面清单

| 路径 | 文件 | 功能 |
|------|------|------|
| `/` | app/page.tsx | 首页：今日赛程卡片 + 模型预测概率 |
| `/login` | app/login/page.tsx | 登录页：微信验证码 / 密码双模式 |
| `/register` | app/register/page.tsx | 注册引导 |
| `/report/[match_id]` | app/report/[match_id]/page.tsx | 研报详情（SSR，付费隔离） |
| `/archive` | app/archive/page.tsx | 历史研报归档 |
| `/model` | app/model/page.tsx + ModelPageV2.tsx | 模型健康 / 业绩展示 |
| `/center` | app/center/page.tsx | 个人中心（设备管理、CDK 兑换、VIP 状态）|
| `/help` | app/help/page.tsx | FAQ |
| `/about` | app/about/page.tsx | 关于 |
| `/privacy` | app/privacy/page.tsx | 隐私政策 |
| `/terms` | app/terms/page.tsx | 使用条款 |
| `/admin/cdk` | app/admin/cdk/page.tsx | 管理员发卡页（需超管登录）|

### 响应式方案

- Tailwind CSS v4，无显式 sm/md/lg 断点文件，内联 `className` 混用 `px-`/`py-` 等绝对值
- 无第三方 Mobile UI 库（antd-mobile / Vant 等），完全自写
- 首页同一组件使用 `isDark` 分支分别渲染深/浅色版本，**未发现明确的移动端 breakpoint 响应式布局**（主要依靠 flex/自适应宽度）
- **BottomNav.tsx** 组件存在，推测有移动端底部导航栏

### 深浅色模式

- 实现：自写 `ThemeProvider.tsx`（React Context + localStorage）
- 切换持久化：`localStorage.setItem('theme', ...)`
- 防 FOUC：`layout.tsx` `<head>` 内嵌同步 JS 脚本（读 localStorage → 添加 `dark`/`light` class）
- **默认：深色（'dark'）**，不跟随系统（`useEffect` 读 localStorage，无 `prefers-color-scheme` 检测）

### 字号体系

- 正文以 `text-xs`（12px）/ `text-sm`（14px）为主，部分标签低至 `text-[7px]`（页面内有 7px 标签文字）
- 字体：Space Grotesk / Plus Jakarta Sans / Manrope（均来自 Google Fonts）
- 无 `rem`/`em` 自适应字号体系，全部 Tailwind 固定像素级别
- ⚠️ 7px 文字在移动端可能不可读

### viewport meta

**未在 `app/layout.tsx` 中找到显式 `<meta name="viewport">`**。Next.js 16 在 App Router 下会自动注入 viewport meta，但无法确认是否有自定义 `width=device-width, initial-scale=1` 设置——需 confirm 实际渲染的 HTML head。

### PWA

- **无 `manifest.json`**（`public/` 目录未发现），不支持 PWA 安装
- 无 service worker

### 主要交互组件来源

- Modal / Toast：自写（无明确 Toast 组件，错误提示通过 React state 控制 DOM 显示）
- Drawer：未确认（无找到独立 Drawer 组件）
- 图表：ECharts（`EChartWrapper.tsx`, `NpxgTrendChart.tsx` 等）

> **reviewer 直觉：有 risk**。① 7px 最小字号过小；② 无 `prefers-color-scheme` 自适应（强制深色默认）；③ 无 PWA 支持；④ 移动端 breakpoint 响应式待 confirm。建议上线前在真机（iOS Safari / Android Chrome）验证关键页面可读性。

---

## 6. 安全 & 反爬

### API 路由清单

| 路径 | Method | 需登录 | 需 VIP | 说明 |
|------|--------|-------|--------|------|
| `GET /` | GET | ✗ | ✗ | API 健康检查 |
| `GET /api/v1/quant/{match_id}` | GET | ✅ | ✗ | 量化预测数据 |
| `GET /api/v1/market/{match_id}` | GET | ✅ | ✗ | 赔率市场数据 |
| `POST /api/v1/lineup_eval` | POST | ✅ | ✗ | 首发评估 |
| `POST /api/v1/calibrate/train` | POST | Admin Token | ✗ | 重训校准器 |
| `GET /api/v1/reports/latest` | GET | ✗ (GUEST stub) | ✗ | 研报列表（GUEST 字段截断）|
| `GET /api/v1/reports/daily_free_id` | GET | ✅ | ✗ | 每日免费场次 |
| `GET /api/v1/reports/archive` | GET | ✅ | ✗ | 历史归档 |
| `GET /api/v1/reports/archive/leagues` | GET | ✅ | ✗ | 联赛列表 |
| **`GET /api/v1/strategies/equity_curves`** | GET | **✗ 开放** | ✗ | 业绩曲线 JSON |
| `GET /api/v1/sync/match_payload/{match_id}` | GET | ✅ | ✗ | 研报 payload |
| `POST /api/v1/sync/match_payload` | POST | Sync Token | ✗ | 内部写入（INTERNAL_SYNC_TOKEN）|
| `GET /api/v1/auth/wechat/webhook` | GET | ✗ | ✗ | 微信平台验证（SHA1 签名） |
| `POST /api/v1/auth/wechat/webhook` | POST | ✗ | ✗ | 微信消息回调（SHA1 签名）|
| `POST /api/v1/auth/wechat/code` | POST | ✗ | ✗ | 生成验证码（限流 10/min） |
| `GET /api/v1/auth/wechat/poll/{session_id}` | GET | ✗ | ✗ | 轮询登录结果 |
| `POST /api/v1/cdk/redeem` | POST | ✅ | ✗ | CDK 兑换（限流 5/min/IP）|
| `POST /api/v1/admin/generate-cdks` | POST | Admin Token | ✗ | 批量发卡 |
| `POST /api/v1/admin/trigger_reviews` | POST | Admin Token | ✗ | 触发复盘 |
| `POST /api/v1/admin/mark_finished` | POST | Admin Token | ✗ | 手动完赛标记 |
| `GET /api/v1/admin/review_status` | GET | Admin Token | ✗ | 复盘状态查询 |
| `GET /api/v1/user/me` | GET | ✅ | ✗ | 当前用户信息 |
| `PATCH /api/v1/user/nickname` | PATCH | ✅ | ✗ | 改昵称 |
| `POST /api/v1/user/avatar` | POST | ✅ | ✗ | 改头像 |
| `GET/PUT /api/v1/user/preferences` | GET/PUT | ✅ | ✗ | 用户偏好 |
| `GET /api/v1/user/sessions` | GET | ✅ | ✗ | 当前设备列表 |
| `DELETE /api/v1/user/sessions/{jti}` | DELETE | ✅ | ✗ | 踢出指定设备 |
| `POST /api/v1/user/logout` | POST | ✅ | ✗ | 退出登录 |
| `GET /api/v1/model/health` | GET | ✅ | ✗ | 模型健康指标 |
| `GET /api/v1/model/snapshot` | GET | ✅ | ✗ | 模型快照 |
| `GET /api/v1/auth/dev-login` | GET | Dev Only | ✗ | 开发调试后门（`ENABLE_DEV_LOGIN=0` 时 404）|

### 限流

- **应用层**：`rate_limit.py` 固定窗口内存计数（进程重启清零）
  - 微信验证码：10/min/IP（wechat_auth_router.py）
  - CDK 兑换：5/min/IP（cdk_router.py）
  - Webhook：120/min/IP
- **nginx 层**：无 `limit_req` / `limit_conn` 配置
- **Cloudflare**：未确认 Rate Limiting 规则

### CORS 配置

```python
allow_origins = ["https://miaomiaodi.cc", "https://www.miaomiaodi.cc"]  # 生产
allow_methods = ["*"]
allow_headers = ["*"]
allow_credentials  # 未显式设置（FastAPI 默认 False）
```

⚠️ `allow_credentials=True` 未启用，若前端需带 cookie 跨域（当前 NextAuth 用 httpOnly cookie），需 confirm 是否有影响。`allow_methods=["*"]` 允许任意方法（含 DELETE/PATCH），在 Cloudflare WAF 层可考虑收窄。

### 敏感接口防护

- Admin 接口（generate-cdks / trigger_reviews / calibrate/train）：`X-Admin-Token`，`secrets.compare_digest` timing-safe 比较（`cdk_router.py`）
- ⚠️ **`review_router.py:_verify_admin`（line 45）使用 `!=` 明文比较，非 timing-safe**，存在 timing attack 风险（虽然概率极低）
- 内部同步接口：`INTERNAL_SYNC_TOKEN`（无 timing-safe，同样 `!=` 比较）

### 敏感信息管理

- `.env` 已在 `backend/.gitignore` 中：`.env`、`.env.local`、`.env.production`
- 前端 `frontend/.gitignore` 同样排除 `.env*`
- 未发现 `.env` 误提交历史（git log 未返回相关记录）
- **未在仓库中找到 Cloudflare WAF / Page Rules / Bot Fight Mode 导出配置，需 confirm**
- `dev-login` 后门：`ENABLE_DEV_LOGIN=0`（当前已关闭）

> **reviewer 直觉：有 risk / 需 follow-up**。① `review_router._verify_admin` 用 `!=` 非 timing-safe；② `sync_router.verify_sync_token` 同样 `!=`；③ nginx 无速率限制；④ `equity_curves` 端点完全开放；⑤ 缺少 CAPTCHA / bot challenge 保护高频轮询接口（`/poll/{session_id}` 每 2s 轮询无限流）。

---

## 7. 待办 & 已知问题

### 代码库内 TODO / FIXME / HACK 注释

```
frontend/app/report/[match_id]/page.tsx:247
  // TODO: 接入 home_recent_form / away_recent_form / beginner_summary
  → 研报「初学者视图」三个数据字段尚未接入后端 API
```

其余 Python 后端文件未发现 TODO/FIXME/HACK 注释（扫描 `backend/*.py` 无命中）。

### 最近 14 天 git log（代码层面当前已无 git commit 历史，由 CLAUDE.md 记录变更）

从 CLAUDE.md 事故记录和 backups/ 文件时间戳推断，近期（2026-04-22 ~ 2026-04-29）主要迭代焦点：

| 日期（UTC）| 主要内容 |
|-----------|---------|
| 2026-04-22 | 数据库 UPSERT 修复，前后两份 DB backup |
| 2026-04-23 | `report_store` schema 变更（version 列）；`ingest_failure_log` 新建；`archiver.py` 时区 bug 修复；`run_tonight_reports.py` 线程局部变量 bug |
| 2026-04-25 | `fotmob_scheduler` 静默丢场 9 场事故修复；双闸门 sanity check；DB backup |
| 2026-04-26 | `prediction_audit` cron 顺序修复；`picked_direction` 约定统一；INSERT OR REPLACE → INSERT OR IGNORE + UPDATE 修复 |
| 2026-04-27 | Admin 接口鉴权标准化（X-Admin-Token）；付费内容硬隔离上线；dev-login 后门管理；模型快照 cron；DB 两次 backup |
| 2026-04-28 | `report_router.py` / `run_tonight_reports.py` / `workflow.py` bak 文件创建（当日有 major 改动） |
| 2026-04-29 | `calibration_league` 联赛字典同步；DB pre_league_relabel 备份；今日最新 backup |

### 已知未解决问题（CLAUDE.md + 对话记录）

1. **OU 特征 `league_over_2_5_rate_season` 泄漏**：`build_ou_features_v5.py:build_league_avgs()` 使用全赛季均值（含未来比赛赛果），需改为 expanding window（仅影响 OU 模型，非 Lambda/AH 模型）
2. **WDL 模型不预测平局**：Poisson 模型结构限制，平局永远输出最低概率；已记录，需 calibration step
3. **v5 Lambda 模型处于影子运行**（A/B 测试），生产仍为 v4（`MODEL_VERSION=v4`）
4. **`equity_curves` 端点无鉴权**（§6 已标）
5. **`review_router._verify_admin` 非 timing-safe 比较**（§6 已标）
6. **首页研报 `home_recent_form` 等三个字段 TODO 未接入**（§7 已标）
7. **无 PWA manifest / Service Worker**（§5 已标）
8. **备份无异地存储**（§2 已标）
9. **旧表 `wechat_users` 未清理**（§3 已标）
10. **验证码轮询 `/poll/{session_id}` 无速率限制**：bot 可以高速轮询，浪费 DB 连接

---

## 附：一句话总结每节状态

| 节 | 状态 |
|----|------|
| §1 技术栈 | 看起来 OK（next-auth beta + sqlite 前端依赖需 confirm）|
| §2 部署 | **有 risk**（备份无异地、nginx 无 limit_req、PM2 开机自启需 confirm）|
| §3 用户系统 | **需 follow-up**（强制关注公众号逻辑缺失、旧表未清理）|
| §4 付费 | **有 risk**（equity_curves 开放、无 VIP-only 硬隔离端点）|
| §5 前端 UX | **有 risk**（7px 字体、无 PWA、无系统主题跟随）|
| §6 安全 | **需 follow-up**（review_router timing attack、poll 接口无限流、CF 配置未确认）|
| §7 待办 | 10 项已知问题，最高优先级：equity_curves 鉴权 + timing-safe Admin 比较 |
