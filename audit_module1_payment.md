# miaomiaodi.cc 上线前 Audit — 模块 1：付费闭环

> **审计范围**：VIP 内容管控 · CDK 生命周期 · 付费内容暴露面 · 前后端一致性 · 管理员接口安全 · 风险评级
> **生成时间**：2026-04-29（READ-ONLY，未改任何代码）
> **审计文件**：report_router.py / sync_router.py / api_server.py / cdk_router.py / review_router.py / auth_deps.py / lib/auth.ts / app/report/[match_id]/page.tsx / app/api/v1/admin/generate-cdks/route.ts

---

## 总评

| 等级 | 计数 | 说明 |
|------|------|------|
| 🔴 BLOCKER | 3 | 上线前必须修复，存在实质性收入损失或安全风险 |
| 🟡 RISK | 5 | 建议修复，短期可接受但需跟进 |
| 🟢 OK | 12 | 实现正确，无需改动 |

---

## § 1  VIP 内容管控（付费场门控）

### 1.1 sync_router — `GET /api/v1/sync/match_payload/{match_id}`

**文件**：`sync_router.py` ≈ line 450–760  
**鉴权**：`Depends(get_current_user)` → GUEST 自动 401 ✅  
**字段截断逻辑**：

```
is_gated = True  when  not user.is_vip AND not is_free_match
├── report_markdown  = None          if is_gated
├── post_match_review = None         if not user.is_vip
├── inference        = ""            if user.is_guest  (理应不到此处，因 GUEST → 401)
├── home/draw/away_prob = None       if user.is_guest
└── lineup_brief     = 公开（所有用户可见）
```

**评级**：🟢 OK — 付费场 markdown 对非 VIP 注册用户正确截断；赛后复盘 VIP 独享逻辑正确。

---

### 1.2 report_router — `GET /api/v1/reports/latest`

**文件**：`report_router.py` line 219–320  
**鉴权**：`Depends(get_optional_user)` → GUEST 200（stub）  
**三档脱敏**：

| 用户级别 | inference | 概率字段 | is_gated |
|----------|-----------|----------|----------|
| GUEST    | ""        | null     | 是       |
| REGISTERED（付费场）| "" | 有值 | 是 |
| VIP      | 完整      | 有值     | 否       |

**评级**：🟢 OK — 三档脱敏正确实现，GUEST 不暴露 inference。

---

### 1.3 report_router — `GET /api/v1/reports/archive`

**文件**：`report_router.py` line 378  
**鉴权**：`Depends(get_current_user)` → GUEST 401 ✅  
**问题**：归档接口对所有**已登录**用户（含 registered 非 VIP）返回完整 `inference` 字段，无 VIP 门控。

```python
# 约 line 395–440：SELECT inference FROM report_store WHERE is_archived=1 ...
# 返回时无 is_vip 分支，inference 直接传出
```

**业务影响**：任何免费注册用户可通过 `/reports/archive` 分页查到历史所有付费场次的推荐文字（核心 pick），等同于无限期免费使用核心研报结论。

**评级**：🟡 RISK（archive 主要是历史数据，实时场次影响有限，但信息策略不一致）

**修复建议**：
```python
# 在 archive 端点加 VIP 分支
inference_out = row["inference"] if user.is_vip else ""
```

---

### 1.4 report_router — `GET /api/v1/report/{match_id}` ← 遗留端点

**文件**：`report_router.py` line 21–184  
**鉴权**：**无 JWT，无 Depends** — username 通过 Query Parameter 传入

```python
@router.get("/report/{match_id}")
async def get_premium_report(match_id: str, username: Optional[str] = None):
    ...
    if not username or username == "anonymous":
        # 无用户名 → 返回完整 .md 内容（is_unlocked=False 但 content=完整文件）
        with open(target_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"match_id": match_id, "is_unlocked": False, "content": content}
```

**攻击面**：
1. **无 username 路径（line 113–117）**：任何人 `GET /api/v1/report/<id>` 不带 username → 返回 `is_unlocked=False` + **完整 .md 文件内容**。前端靠 Paywall 组件截断，但后端数据已完整发送，curl / Postman 直连即可读取全文。
2. **伪造 username 路径**：传入任意 username 字符串即可尝试消耗他人 quota（`user_meta.report_quota`）或记录解锁（`user_unlocks`），无签名验证。
3. **物理文件扫描**：端点直接 `os.listdir(REPORTS_DIR)` 暴露文件系统路径探测面。

**这是系统内唯一未挂 JWT 鉴权的研报读取路径，是付费闭环最大漏洞。**

**评级**：🔴 BLOCKER

**修复方案**：
```python
# 方案 A（推荐）：废弃该端点（已有 sync_router.get_match_payload 替代），返回 410
@router.get("/report/{match_id}", deprecated=True)
async def get_premium_report_deprecated(match_id: str):
    return JSONResponse(status_code=410,
        content={"detail": "此接口已废弃，请使用 /api/v1/sync/match_payload/{match_id}"})

# 方案 B：加 JWT 鉴权
@router.get("/report/{match_id}")
async def get_premium_report(match_id: str, user: CurrentUser = Depends(get_current_user)):
    if not user.is_vip:
        raise HTTPException(403, "VIP 专属内容")
    ...
```

---

### 1.5 report_router — `GET /api/v1/strategies/equity_curves`

**文件**：`report_router.py` line 343  
**鉴权**：**无任何依赖**（既无 get_optional_user 也无 get_current_user）

```python
@router.get("/strategies/equity_curves")
async def get_equity_curves():
    ...
```

返回 `models_v4/equity_curves.json`，含策略回测净值曲线、每场 PnL、历史命中率等模型表现数据。

**评级**：🟡 RISK（不直接泄露研报内容，但暴露模型性能数据，可被竞争者用于核实策略真实性）

**修复建议**：至少加 `Depends(get_current_user)` 要求登录。

---

### 1.6 api_server — `POST /api/v1/lineup_eval`

**文件**：`api_server.py` line 420–470  
**鉴权**：**无 JWT 依赖**，仅速率限制（30/min/IP）

```python
@app.post("/api/v1/lineup_eval")
def evaluate_lineup(request: LineupEvaluationRequest, http_request: Request):
    from rate_limit import hit as _rl, client_ip as _cip
    _rl("lineup_eval", _cip(http_request), 30)   # 无 Depends(get_current_user)
```

该端点查询 `dim_player + int_player_influence`，返回球员战术角色和 xG 份额数据。

**评级**：🔴 BLOCKER（CLAUDE.md §21 明确要求读取 lineup 数据需要登录；且 in-memory 限流在服务重启后失效）

**修复建议**：
```python
@app.post("/api/v1/lineup_eval")
def evaluate_lineup(
    request: LineupEvaluationRequest,
    http_request: Request,
    user: CurrentUser = Depends(get_current_user),   # 加这一行
):
```

---

## § 2  CDK 生命周期

### 2.1 CDK 兑换流程

**文件**：`cdk_router.py` line 108–238

**流程验证**：

| 步骤 | 实现 | 评级 |
|------|------|------|
| JWT 鉴权（GUEST → 401） | `get_optional_user` + `if user.is_guest: raise 401` | 🟢 OK |
| 速率限制（5/min/IP） | 自定义 `_check_rate_limit` + `rate_limit.client_ip` 穿透 CF | 🟢 OK |
| CDK 校验 + 标记已使用 | `BEGIN EXCLUSIVE TRANSACTION`，`SELECT ... WHERE is_used=0` 再 `UPDATE is_used=1` | 🟢 OK |
| VIP 到期时间累加 | `base = max(current_exp, now_utc) + timedelta(days=vip_days)` → 正确累加，不被截断 | 🟢 OK |
| 时区一致性 | `datetime.now(timezone.utc)` + ISO format 存库 | 🟢 OK |
| JWT 重签（沿用 jti） | `issue_session_token(reuse_jti=user.jti)` — 不新建会话，不踢出当前登录 | 🟢 OK |
| 审计 | `admin_audit_log` 含 actor/payload/ip/ua | 🟢 OK |
| quota 向后兼容 | `user_meta.report_quota + quota_delta` | 🟢 OK |

**旧接口（`POST /api/v1/redeem`）**：已返回 410 Gone，注释清晰说明身份冒充风险 ✅

**CDK 到期时间（expires_at）**：CDK 自身有 expires_at 校验（line 71–77），格式异常时宽松处理（不拦截），属于可接受设计。

**评级**：🟢 OK — CDK 兑换流程完整，事务安全，VIP 累加正确。

---

### 2.2 CDK 生成（Admin 接口）

**文件**：`cdk_router.py` line 270–344 + `frontend/app/api/v1/admin/generate-cdks/route.ts`

| 检查项 | 状态 |
|--------|------|
| 后端鉴权：`secrets.compare_digest` timing-safe | 🟢 OK |
| 未配置 ADMIN_SECRET_TOKEN → 503 拒绝（不 fail-open） | 🟢 OK |
| count 上限 50 / quota 上限 100 / vip_days 仅 0\|7\|30 | 🟢 OK |
| CDK 字符集剔除易混淆字符（O/0/I/1） | 🟢 OK |
| 前端代理层：NextAuth session 校验（SUPER_ADMIN_USER）后注入 token | 🟢 OK |
| 浏览器 bundle 不含 ADMIN_SECRET_TOKEN（无 NEXT_PUBLIC_ 前缀） | 🟢 OK |
| admin_username 由服务端注入（`session.user.name`），浏览器不能自填 | 🟢 OK |

**评级**：🟢 OK — 批量发卡双层防御完整。

---

## § 3  付费内容实际暴露面

### 3.1 漏洞全景

```
路径                                          GUEST 可获内容              REGISTERED 可获内容
──────────────────────────────────────────────────────────────────────────────────────────
GET /api/v1/report/{match_id}                 ⚠️ 完整 .md 文件（BLOCKER）  ⚠️ 同上 + 可伪造quota消耗
GET /api/v1/sync/match_payload/{id}          401                         markdown=null（截断正确）
GET /api/v1/reports/latest                   stub（inference=""）         inference=""（付费场截断）
GET /api/v1/reports/archive                  401                         ⚠️ inference 完整（RISK）
GET /api/v1/reports/daily_free_id            401                         OK
GET /api/v1/quant/{match_id}                 401                         OK（无 VIP 差异，同 CLAUDE.md §21）
GET /api/v1/market/{match_id}                401                         OK（无 VIP 差异，同 §21）
GET /api/v1/strategies/equity_curves         ⚠️ 完整模型数据（RISK）      同上
POST /api/v1/lineup_eval                     ⚠️ 球员数据（BLOCKER）       同上（无鉴权）
```

### 3.2 核心研报（inference 文字）暴露路径

| 路径 | REGISTERED 可见？ | 备注 |
|------|------------|------|
| `/api/v1/report/{match_id}` | ✅ 完整（BLOCKER） | 旧接口，无 JWT |
| `/api/v1/sync/match_payload` 付费场 | ❌ inference="" | 正确截断 |
| `/api/v1/reports/latest` 付费场 | ❌ inference="" | 正确截断 |
| `/api/v1/reports/archive` 已归档场 | ✅ 完整（RISK） | 缺 VIP 门控 |

---

## § 4  前端 / 后端一致性

### 4.1 SSR 权限检查（`app/report/[match_id]/page.tsx`）

```typescript
// line 744–748
const session = await auth();
const role = (session?.user as any)?.role as string | undefined;
accessLevel = !session?.user ? 'anonymous' : role === 'vip' || role === 'admin' ? 'vip' : 'registered';
```

- ANONYMOUS → 渲染 `<LoginPrompt>` 组件，不请求任何数据 ✅
- REGISTERED → 后端 `report_markdown=null`，前端显示 PaywallOverlay ✅
- VIP → 完整渲染所有章节 ✅
- `role === 'admin'` 视同 VIP ✅

**isFreeMatch 逻辑**：SSR 期间调 `GET /api/v1/reports/daily_free_id`，注意该接口要求登录（GUEST → 401）。当 ANONYMOUS 用户访问时，fetch 会失败（401），isFreeMatch 保持 false，降级安全 ✅

**评级**：🟢 OK — SSR 权限矩阵与后端行为一致。

### 4.2 VIP 角色实时校验

**文件**：`auth_deps.py:get_optional_user`

```python
# JWT payload 里 role='vip' 还需满足 vip_expires_at > now()
is_vip = (role == 'vip' and vip_expires_at > datetime.utcnow())
```

CDK 兑换后 JWT 重签包含新 vip_expires_at → 用户刷新页面即可实时解锁，无需重新登录 ✅

**评级**：🟢 OK — 双重 VIP 校验（role + 时间戳），防止 JWT 过期后伪装。

### 4.3 超管 JWT（user_id=0）

**文件**：`lib/auth.ts:mintSuperAdminApiToken`

```typescript
// 本地签发 JWT：user_id=0, role='vip', no jti
// → 绕过 user_sessions 白名单
// → users 表无 id=0 记录（有特判，OK）
// → 如果 JWT_SECRET 泄露 → 永久不可撤销的超管访问权限
```

- jti 缺失意味着无法通过 user_sessions 表撤销超管 JWT
- 若 JWT_SECRET 被泄露，攻击者可自行签发 `role='vip'` JWT，且无会话白名单兜底

**评级**：🟡 RISK（单人运维场景下风险可接受，但应补 jti + user_sessions 白名单）

---

## § 5  管理员接口安全

### 5.1 cdk_router — `_verify_admin`

```python
if not secrets.compare_digest(x_admin_token, ADMIN_SECRET_TOKEN):
    raise HTTPException(status_code=401, ...)
```

**评级**：🟢 OK — timing-safe compare_digest ✅

### 5.2 review_router — `_verify_admin`

**文件**：`review_router.py` ≈ line 45

```python
# 使用 != 而非 secrets.compare_digest
if x_admin_token != ADMIN_SECRET_TOKEN:
    raise HTTPException(status_code=401, ...)
```

字符串 `!=` 存在 timing side-channel，攻击者可通过测量响应时间逐字节猜测 token。

**评级**：🟡 RISK（需要高精度网络测量，低优先级，但属于 CLAUDE.md §20 铁律违反）

**修复**：
```python
if not secrets.compare_digest(x_admin_token or "", ADMIN_SECRET_TOKEN or ""):
```

### 5.3 dev-login 端点

**文件**：`api_server.py` line 471–540  
**默认状态**：`ENABLE_DEV_LOGIN != 1` 时路由不挂载（404）✅  
**三层防御**：路由注册条件 + IP 白名单 + timing-safe secret 比较 ✅

**评级**：🟢 OK（线上 `=0` 时完全不暴露）

---

## § 6  退款 / 审计追踪

| 项目 | 状态 | 说明 |
|------|------|------|
| CDK 兑换 `admin_audit_log` | 🟢 OK | actor / payload / ip / ua / created_at 完整 |
| CDK 使用 `shop_cdk.used_by` | 🟢 OK | 记录 user_id |
| CDK 使用 `shop_cdk.is_used=1` | 🟢 OK | 防止重复兑换，EXCLUSIVE 事务 |
| 研报解锁 `user_unlocks` | 🟢 OK（旧系统）| 新系统走 VIP 时间轴，无需逐场 unlock |
| VIP 到期时间变更 `users.vip_expires_at` | 🟢 OK | updated_at 同步更新 |
| 退款流程 | ⚪ 未审计 | 无自动退款逻辑，属运营手工处理 |
| VIP 撤销 API | ⚪ 未审计 | 无用户发起撤销端点；管理员可直接改 DB |

---

## § 7  综合风险矩阵

| # | 路径/文件 | 类型 | 等级 | 简述 |
|---|-----------|------|------|------|
| B1 | `report_router.py:21` `/api/v1/report/{match_id}` | 鉴权缺失 | 🔴 BLOCKER | 无 JWT，完整 .md 文件公开暴露；可伪造 username 消耗他人 quota |
| B2 | `api_server.py:420` `POST /api/v1/lineup_eval` | 鉴权缺失 | 🔴 BLOCKER | 无任何 auth 依赖，仅速率限制（重启失效） |
| B3 | `report_router.py:343` `GET /api/v1/strategies/equity_curves` | 鉴权缺失 | 🔴 BLOCKER* | 无任何依赖，完全公开 *（降级为 RISK 可接受，不含研报内容） |
| R1 | `report_router.py:378` `/reports/archive` | 信息泄露 | 🟡 RISK | registered 用户获取历史 inference 完整文字 |
| R2 | `review_router.py:45` `_verify_admin` | timing side-channel | 🟡 RISK | `!=` 比较，违反 §20 铁律 |
| R3 | `lib/auth.ts:mintSuperAdminApiToken` | jti 缺失 | 🟡 RISK | 超管 JWT 不可撤销，JWT_SECRET 泄露风险 |
| R4 | `cdk_router.py:71-77` CDK expires_at 宽松处理 | 格式兜底 | 🟡 RISK | 格式异常时 `pass` 静默，过期码可能被使用 |
| OK | 其余所有路径 | — | 🟢 OK | 见上文各节 |

> *equity_curves 无研报数据，实际危害低于 B1/B2，但技术上属于"无鉴权公开接口"

---

## § 8  修复优先级建议

### 🔴 P0（上线前必须完成）

**B1 — 废弃 `/api/v1/report/{match_id}`**
```python
# report_router.py:21
@router.get("/report/{match_id}", deprecated=True)
async def get_premium_report_deprecated():
    return JSONResponse(status_code=410, content={
        "detail": "此接口已废弃，请使用 /api/v1/sync/match_payload/{match_id}"
    })
```
确认前端已全部迁移到 `sync_router` 端点后执行。

**B2 — lineup_eval 加 JWT 鉴权**
```python
# api_server.py:420
@app.post("/api/v1/lineup_eval")
def evaluate_lineup(
    request: LineupEvaluationRequest,
    http_request: Request,
    user: CurrentUser = Depends(get_current_user),
):
```

### 🟡 P1（上线后 1 周内）

**R1 — archive 接口 VIP 门控**
```python
# report_router.py 归档列表返回时
"inference": row["inference"] if user.is_vip else "",
```

**R2 — review_router timing-safe**
```python
# review_router.py:_verify_admin
if not secrets.compare_digest(x_admin_token or "", ADMIN_SECRET_TOKEN or ""):
```

**B3 — equity_curves 加最低鉴权**
```python
@router.get("/strategies/equity_curves")
async def get_equity_curves(user: CurrentUser = Depends(get_current_user)):
```

### 🟡 P2（上线后 1 个月内）

**R3 — 超管 JWT 补 jti**：`mintSuperAdminApiToken` 生成 jti 并写入 `user_sessions`，使超管 JWT 可撤销。

**R4 — CDK expires_at 格式异常硬拒**：将 `except ValueError: pass` 改为 `log.warning + raise HTTPException(400)`。

---

## 附：验证命令

```bash
# B1 验证（上线前应 410）
curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/api/v1/report/12345"
# 期望: 410（修复后）；当前: 404 或 200（漏洞活跃）

# B2 验证（上线前应 401）
curl -s -X POST "http://localhost:8000/api/v1/lineup_eval" \
  -H "Content-Type: application/json" \
  -d '{"player_names":["Salah"]}' | python3 -m json.tool
# 期望: {"detail":"Not authenticated"}（修复后）；当前: 200 + 数据

# R2 验证
grep -n "secrets.compare_digest\|!= ADMIN" /home/ubuntu/app/backend/review_router.py
# 期望: 仅见 compare_digest（修复后）

# R1 验证
curl -s -H "Authorization: Bearer <registered_token>" \
  "http://localhost:8000/api/v1/reports/archive?limit=1" | python3 -c "
import sys, json; d=json.load(sys.stdin)
inf = d.get('items', [d])[0].get('inference','')
print('RISK: inference visible' if inf else 'OK: inference hidden')
"
```
