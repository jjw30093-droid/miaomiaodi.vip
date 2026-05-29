# miaomiaodi.vip 项目守则

足球量化研究所 vip 站。定位:单场研报付费 + VIP 套餐 + 世界杯通票。
引流入口在 miaomiaodi.cc,本项目专注付费闭环。

## 技术栈

同 cc 站。两个项目历史上是 fork 关系。共用 logo、共享设计 token。

## 付费体系核心约束

### 鉴权链路(不可破坏)

- `CurrentUser.is_vip` = `tier == UserTier.VIP`,禁止加 ENABLE_VIP_GATING 之类的开关回退
- JWT 解码时 `role IN ('vip', 'super_admin')` 才升 tier 到 VIP,registered 永远不是 VIP
- VIP 过期判断 `vip_expires_at` 在 make_jwt 阶段做,CurrentUser 侧只看 tier
- 新加端点默认要求登录(用 `get_current_user`),开放给 GUEST 必须显式用 `get_optional_user` 并加注释说明为什么

### 付费内容物理截断

- 任何返回研报正文的端点必须按 `is_gated` 物理截断 report_markdown,不能依赖前端隐藏
- `is_gated` 默认 True,放行条件三选一:`is_free_match` / `user.is_vip` / `user_unlocks` 命中
- response 必须返回 `is_gated` / `access_level` / `unlock_reason` 三字段给前端用
- 前端 PaywallOverlay 必须读 `unlock_reason` 显示差异化文案

### schema 约束

- users.role 取值:`'registered' | 'vip' | 'super_admin'`
- user_unlocks 当前用 username 关联(脆弱),新写代码必须 JOIN users 用 user_id 兜底
- 未来 schema 改动:新增 user_id 列 + 保留 username 列双写 + 迁移完成后再删

## 改前必读

- 设计系统:与 cc 共用 globals.css 设计 token
- 鉴权代码:backend/auth_deps.py、backend/sync_router.py、frontend/lib/auth.ts
- 付费链路:frontend/app/report/[match_id]/page.tsx、components/PaywallOverlay.tsx、lib/fetchReport.ts adapter
- 不要让任何 API 端点直接绕过 sync_router 的 gating 逻辑暴露研报正文

## 验证(强制三必查)

同 cc 站三必查 + 付费回归 6 case:

1. GUEST + paid → is_gated=true, has_md=false
2. GUEST + free → is_gated=false, has_md=true
3. REGISTERED + paid → is_gated=true (关键:UI 不应显示赛后复盘)
4. REG + user_unlocks 命中 + paid → unlocked, has_md=true
5. VIP + paid → vip, has_md=true
6. VIP 已过期 + paid → registered, has_md=false (用 ENABLE_VIP_GATING=0 之类的快捷绕过算 fail)

任何鉴权/付费改动 push 之前必须人工跑 case 3 — 这是最容易踩坑的一档。

## 支付通道

- 一期:CDK 手动开通 + 爱发电跳转
- 过渡期:虎皮椒(个人收款合规接口,单笔限 499,商品名脱敏)
- 终态:Stripe(等日本银行卡)

合规红线:

- 不接第四方聚合支付(央行严打的换码跑分模式)
- 商品名禁用 "博彩 / 赌 / 竞彩 / 盘口 / 赔率",统一 "数据研报-{league}-{date}-{home}vs{away}"
- 单笔金额 > 499 强制 Stripe 路径,不走虎皮椒

## 数据库

- 主库:/home/ubuntu/app/backend/football_uk.db
- 关键表:users / user_sessions / user_unlocks / shop_cdk / orders(Day 2 加)/ products(Day 2 加)/ report_store
- schema 改动前先 sqlite3 dump 当前表,改动后跑 baseline 对比

## 红线

同 cc + 以下:

1. 不在前端做付费判断(前端隐藏不算保护,后端必须物理截断)
2. 不引入"登录即 VIP"、"测试期全免费"之类的全局开关
3. 不在 git 历史里留 password_hash dump 或者 JWT_SECRET
4. 涉及虎皮椒回调必须验证签名,不能裸调
