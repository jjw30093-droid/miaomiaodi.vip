# miaomiaodi.cc 上线前 Audit — 模块 2：Cloudflare 配置盘点

> **审计时间**：2026-04-29 20:30 UTC  
> **操作模式**：READ-ONLY（仅 GET）  
> **Token 来源**：用户直接提供（Account API Token，脱敏：`cfat_j...3078`）  
> **⚠️ 紧急：Token 明天到期 → 2026-04-30T23:59:59Z，需在明天前续期**

---

## § 1 Zone 元信息

| 字段 | 值 |
|------|-----|
| Zone ID | `51474947d7a62a3d169ef0b8d0df83fe` |
| 域名 | miaomiaodi.cc |
| **Plan** | **Free Website（$0/mo）** |
| Status | active |
| development_mode | 0（关闭） |
| paused | false |
| 注册商 | Namecheap |
| NS 服务器 | anahi.ns.cloudflare.com / gabriel.ns.cloudflare.com |
| Zone 创建时间 | 2026-03-31（接入 CF 不足 1 个月） |

**Free Plan 的限制**（影响后续分析）：
- ❌ 无 WAF Custom Rules（需 Pro+）
- ❌ 无高级 Rate Limiting（需 Pro+）
- ❌ 无 Bot Fight Mode 高级模式（需 Pro+）
- ❌ 无 IP 白名单/Geo 封锁（需 Enterprise）
- ✅ Managed Free Ruleset（Log4j/Shellshock 等基础防护）
- ✅ DDoS L7 自动缓解
- ✅ Page Rules 3 条（但 Account Token 无权查询，见 §7）

---

## § 2 DNS & Origin IP 暴露面

### DNS 记录完整列表

| Type | Name | Content | Proxied | TTL |
|------|------|---------|---------|-----|
| A | miaomiaodi.cc | `<ORIGIN_IP_REDACTED>` | **true ✅** | auto |
| A | www.miaomiaodi.cc | `<ORIGIN_IP_REDACTED>` | **true ✅** | auto |
| MX | miaomiaodi.cc | eforward1~5.registrar-servers.com | false（灰云）| auto |
| TXT | miaomiaodi.cc | `v=spf1 include:spf.efwd.registrar-servers.com ~all` | false | auto |

- **无 api. 子域名**（无需担心 api subdomain 灰云）
- **MX 灰云**：指向 Namecheap 邮件转发服务器（`registrar-servers.com`），不暴露回源 IP ✅
- **SPF**：仅引用 registrar 的 SPF，不含回源 IP ✅

### dig 实测结果

```
dig miaomiaodi.cc @1.1.1.1      → 104.21.74.95 / 172.67.201.192 （CF IP 段）✅
dig www.miaomiaodi.cc @1.1.1.1  → 172.67.201.192 / 104.21.74.95 （CF IP 段）✅
dig api.miaomiaodi.cc @1.1.1.1  → (无结果) ✅
dig txt miaomiaodi.cc           → "v=spf1 include:spf.efwd.registrar-servers.com ~all" ✅
dig mx miaomiaodi.cc            → eforward{1-5}.registrar-servers.com ✅
```

### Certificate Transparency (crt.sh)

CT 记录仅有：`miaomiaodi.cc` / `*.miaomiaodi.cc` / `www.miaomiaodi.cc`  
**无任何子域名泄露回源 IP** ✅

### Origin IP 暴露结论

- **当前 DNS**：全部 A 记录橙云代理，公开 DNS 只返回 CF IP，不暴露 `<ORIGIN_IP_REDACTED>`
- **历史风险**：域名 2026-03-31 接入 CF，此前若有裸 IP 直连或灰云 DNS，历史记录可能残留在 Shodan/ZoomEye 等被动扫描数据库中。强烈建议检查 [shodan.io/host/<ORIGIN_IP_REDACTED>](https://shodan.io) 确认是否已有历史记录
- **nginx**：监听 80/443，无 `server_name` 直接暴露 IP 的配置，Certbot 管理 HTTPS 证书 ✅

---

## § 3 SSL/TLS 配置

| 设置 | 值 | 评估 |
|------|-----|------|
| ssl mode | **strict** | ✅ 最安全模式，CF→origin 用 HTTPS+证书验证 |
| always_use_https | on | ✅ HTTP 自动 301 跳 HTTPS |
| automatic_https_rewrites | on | ✅ 页面内混合内容自动升级 |
| min_tls_version | 1.2 | ✅ 拒绝 TLS 1.0/1.1 |
| tls_1_3 | on | ✅ 支持最新 TLS |

**SSL 配置满分**，无任何反模式（`flexible` 漏洞不存在）。

---

## § 4 安全设置

| 设置 | 值 | 评估 |
|------|-----|------|
| security_level | medium | ✅ 对已知恶意 IP 自动 Challenge |
| browser_check | on | ✅ 浏览器指纹验证（阻止简单 curl bot） |
| challenge_ttl | 1800s（30分钟）| 一般，可调高至 3600 |
| hotlink_protection | off | 无图片热链防护（无大图资产，可接受） |
| cache_level | aggressive | ⚠️ 见 §7 缓存分析 |
| browser_cache_ttl | 14400s（4小时）| 合理 |

---

## § 5 WAF Custom Rules

**Custom Rules（zone 级自定义）：0 条**

原因：Free Plan 不支持自定义 WAF Rules（需 Pro $20/mo）。

### Managed Free Ruleset（已激活）

CF 托管规则集 `Cloudflare Managed Free Ruleset`（version 66，2025-12-11 更新），已激活以下类型的 block 规则（全部 `enabled=True`）：

| 类别 | 已激活规则示例 |
|------|-------------|
| Log4j | Log4j Headers + URI（2条，block）|
| Shellshock | Shellshock（1条，block）|
| Confluence RCE | CVE-2022-26134 / CVE-2023-22515（2条，block）|
| React/Next.js | CVE-2025-43864/43865, CVE-2025-55182/55183（4条，block）⭐ 含 Next.js 漏洞 |
| Wordpress | 多条 XSS/SQLi/RCE/文件包含（15条，block）|
| Header 合法性 | Validate Headers（1条，block）|

> ⭐ **React Router / Next.js CVE-2025-x 规则是本站的关键防护**，Free Plan 已自动覆盖。

### DDoS L7 Ruleset（自动缓解）

100+ 签名规则自动运行，包含：
- 已知 botnet 签名（#1-#93）
- 异常 UA/Header 检测
- 高请求速率缓解（origin + cached）
- **认证端点高频检测**（`a86652e8...` — "HTTP requests causing a high request rate to authentication endpoints"）⭐ 可能覆盖 `/api/v1/auth/wechat/code`

---

## § 6 Rate Limiting Rules

**CF 层自定义 Rate Limit Rules：0 条**

`http_ratelimit` phase 无任何 zone 级规则。仅依赖：
1. DDoS L7 的自动高频检测（基于 CF 内部阈值，不可配置）
2. 后端应用层 `rate_limit.py` 内存限流（重启清零）

**覆盖对比**：

| 端点 | CF Rate Limit | 后端限流 | 重启后 |
|------|-----------|---------|--------|
| `/api/v1/auth/wechat/code` | 仅 DDoS L7 兜底 | ✅ 10/min/IP | ⚠️ 清零 |
| `/api/v1/auth/wechat/poll/*` | 仅 DDoS L7 兜底 | ✅ 120/min/IP | ⚠️ 清零 |
| `/api/v1/cdk/redeem` | ❌ 无 | ✅ 5/min/IP | ⚠️ 清零 |
| `/api/v1/sync/match_payload/*` | ❌ 无 | ❌ 无 | — |
| `/api/v1/quant/*` | ❌ 无 | ✅ 60/min/IP | ⚠️ 清零 |
| `/api/v1/strategies/equity_curves` | ❌ 无 | ❌ 无（刚加鉴权）| — |

---

## § 7 Cache Rules / Page Rules / Transform Rules

### Cache Rules（Custom）：0 条

`http_request_cache_settings` phase 无任何自定义规则。

**实测**：`curl -I https://miaomiaodi.cc/api/v1/reports/latest` 返回：
```
cf-cache-status: DYNAMIC
```

`DYNAMIC` = CF 识别到 JSON API 响应，**未缓存，直接穿透到 origin** ✅  
CF 默认对 `application/json` + 带 `Authorization` header 的请求不缓存（这是有利的行为）。

**风险确认**：`cache_level=aggressive` 对本站影响有限，因为：
- 所有 `/api/*` 路由返回 JSON，CF 默认不缓存
- 所有带 JWT 的请求 CF 不缓存（带认证头）
- 静态资源（`/static/*`, `/_next/static/*`）正常缓存 ✅

### Page Rules

**查询失败（错误码 1011）**：Account API Token 无权访问 Page Rules，需要 Zone-scoped API Token 或 Global API Key 才能查询。

> 无法确认 Page Rules 配置。需额外授权查询（低优先级）。

### Transform Rules：0 条

`http_request_transform` / `http_response_headers_transform` 均无规则。

---

## § 8 Bot 防护 / Workers / Turnstile

### Bot Management（CF 返回）

| 设置 | 值 | 评估 |
|------|-----|------|
| fight_mode | **false** | ⚠️ Bot Fight Mode 未开启 |
| ai_bots_protection | block | ✅ AI 爬虫（GPTBot 等）自动拦截 |
| content_bots_protection | disabled | 内容抓取保护未启用 |
| crawler_protection | disabled | 爬虫保护未启用 |
| using_latest_model | true | ✅ |

> Bot Fight Mode（免费功能）**未开启**——开启后可挑战已知 bot 指纹，对保护付费内容端点有额外价值，且 **Free Plan 可用，零成本**。

### Workers Routes

**0 条**——无任何 Worker 逻辑（无边缘计算）。

### Turnstile（CAPTCHA 替代）

代码库全局 grep 无任何 Turnstile 集成（`cf-turnstile`）。  
**未部署**。微信验证码端点 `/api/v1/auth/wechat/code` 无 CAPTCHA 保护。

---

## § 9 五大风险评估

### ① Origin IP 是否已对外泄露？

**⚠️ 当前未泄露，历史不确定**

当前：所有 A 记录橙云，dig 只返回 CF IP，SPF/MX 不含回源 IP，CT 日志干净。  
隐患：域名 2026-03-31 才接入 CF，此前是否裸 IP 运行尚不可知，Shodan 可能已索引过。**建议检查 shodan.io 是否有 `<ORIGIN_IP_REDACTED>:8000` 或 `<ORIGIN_IP_REDACTED>:3000` 的历史记录**。如果有，攻击者可绕过 CF 直连 origin（nginx 对直连无 IP 白名单保护）。

### ② `/api/*` 是否真的在 CF 橙云保护内？是否有 bypass？

**✅ 在橙云内，无 bypass 规则，CF 不缓存 API 响应**

实测 `cf-cache-status: DYNAMIC`，CF 识别 JSON 不缓存，所有 API 请求通过 WAF 层。无自定义 cache bypass 规则。

### ③ `/api/v1/auth/wechat/poll/*` 高频轮询端点，CF 层有无 Rate Limit 兜底？

**⚠️ 无 CF 层自定义 Rate Limit**

CF 仅有 DDoS L7 自动检测（阈值不可配置，不保证 10s 轮询场景下生效）。后端 `rate_limit.py` 限速 120/min/IP，但 PM2 重启后清零（无持久化）。极端情况：攻击者在 PM2 重启窗口内可以不受限制地暴力轮询，枚举 session UUID。

### ④ `/admin/*` 是否有 Geo 限制 / IP 白名单 / 额外 Challenge？

**❌ 无任何 CF 层保护**

CF 自定义 WAF Rules = 0 条（Free Plan 不支持）。`/api/v1/admin/generate-cdks` 等接口唯一保护是：
1. Next.js Route Handler（服务端 session 校验 + X-Admin-Token 注入）
2. 后端 `secrets.compare_digest` 验证

没有 CF 层的 Geo/IP/Challenge 防护。任何全球 IP 均可向 admin 端点发送请求（只是会被 401 拒绝）。

### ⑤ 付费内容端点有无 Bot Fight / Rate Limit 兜底？

**⚠️ CF 层无专项防护**

`/api/v1/sync/match_payload/*`、`/api/v1/quant/*`、`/api/v1/strategies/equity_curves` 在 CF 层：
- Bot Fight Mode = off（未开启）
- 无 Rate Limit 规则
- Managed Ruleset 保护（Log4j/RCE 类）覆盖，但不覆盖"高频合法请求刷取内容"场景

**唯一防线**是后端 JWT 鉴权（刚通过 P0 修复加上）+ 部分端点的应用层限速。

---

## § 10 总结：CF 这层目前真正在防什么，哪些是裸奔的

### ✅ CF 目前真正在防的

| 防护 | 机制 |
|------|------|
| 大规模 DDoS | L7 DDoS 自动缓解（100+ 签名，全天候）|
| 已知 botnet / 恶意 IP | Managed Free Ruleset + DDoS 签名 block |
| Log4j / Shellshock / Confluence RCE | Managed Free Ruleset block |
| **Next.js CVE-2025-43864/55182/55183** | **Managed Free Ruleset block**（本站高度相关）|
| SSL 降级 / TLS 1.0 攻击 | min_tls=1.2, strict mode |
| 基础 bot 指纹（浏览器检查）| browser_check=on |
| AI 爬虫（GPTBot 等）| ai_bots_protection=block |
| CF→Origin MITM | SSL strict mode（origin 需有效证书）|

### ❌ CF 层裸奔的（需后端或手动配置保护）

| 未防护项 | 风险等级 | 建议 |
|---------|---------|------|
| **自定义 Rate Limit**（/auth/wechat/code, /cdk/redeem 等）| 🟡 中 | 升级 Pro($20/mo) 或依赖后端 |
| **Bot Fight Mode**（未开启）| 🟡 中 | 免费开启，建议立即 enable |
| `/admin/*` 无 IP/Geo 防护 | 🟡 中 | Free 无此功能；依赖后端双层鉴权 |
| **Turnstile**（微信登录无 CAPTCHA）| 🟡 中 | 免费部署，可保护 /wechat/code |
| 付费内容高频刷取 | 🟡 中 | 需后端加 rate limit 或 Pro Rate Limit |
| 回源 IP 历史泄露（Shodan）| 🟡 中 | 检查 Shodan + nginx 加 CF-IP-only 白名单 |
| Page Rules 配置（无法查询）| ⚪ 未知 | 需 Zone Token 或 Global API Key 补查 |

---

## 附：立即行动项

| 优先级 | 动作 | 成本 | 预期收益 |
|--------|------|------|---------|
| 🔴 **P0** | **CF API Token 续期**（明天 2026-04-30 到期）| 0 | 保持 CF API 访问 |
| 🟡 P1 | **开启 Bot Fight Mode**（CF Dashboard → Security → Bots）| $0 | 减少 bot 刷接口 |
| 🟡 P1 | **Shodan 检查 `<ORIGIN_IP_REDACTED>`** | $0 | 确认历史暴露面 |
| 🟡 P1 | **nginx 加 CF IP 白名单**（仅允许 CF IP 直连 80/443）| $0 | 防 origin bypass |
| 🟡 P2 | **部署 Turnstile** 在微信登录页 | $0 | 保护 /wechat/code |
| 🟡 P2 | 后端 rate limit 持久化（Redis 或 SQLite）| 低 | PM2 重启后不清零 |
| ⚪ P3 | 升级 CF Pro（$20/mo）→ 自定义 WAF + Rate Limit | $20/mo | admin/auth 端点 CF 层防护 |
