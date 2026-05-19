# miaomiaodi.cc P0 修复报告 — 模块 1 付费闭环

> **执行时间**：2026-04-29 20:20 UTC  
> **操作员**：Claude（READ+WRITE，后端 only）  
> **备份文件**：`backend/api_server.py.bak.20260429` / `backend/report_router.py.bak.20260429`

---

## Step 1 — 旧端点 `/api/v1/report/{match_id}` 调用面扫描

**结论：情形 (a) — 前端零调用，端点已提前废弃**

```
frontend/ grep "/api/v1/report/"   → 0 matches
frontend/ grep "api/v1/report\b"   → 1 match（types/football.ts:3，JSDoc 注释，非调用）
backend/  grep "/api/v1/report/{"  → api_server.py:171（410 stub，已优先注册）
```

**关键发现**：`api_server.py:166–179` 中已存在一个 410 stub，以 `@app.get`（优先于 report_router）形式挂载，所有请求已被拦截并返回 410。`report_router.get_premium_report` 的路由实际上永远不会触达（api_server.py:182 注释已说明）。

**操作**：B1 已提前修复，无需再改代码。`report_router.py` 中的旧函数体保留（不删除，避免影响其他模块的 import），仅验证其已被 api_server.py 的 410 stub 覆盖。

---

## Step 3 — npxg / shot_map 端点鉴权状态扫描

| 端点路径 | 文件:行号 | 当前鉴权 | 需修复 |
|----------|-----------|---------|--------|
| `GET /api/v1/quant/{match_id}` | api_server.py:271 | `Depends(get_current_user)` ✅ | 否 |
| `GET /api/v1/market/{match_id}` | api_server.py:398 | `Depends(get_current_user)` ✅ | 否 |
| `GET /model/health` | model_health_router.py:236 | `Depends(get_current_user)` ✅ | 否 |
| `GET /model/snapshot` | model_health_router.py:253 | `Depends(get_current_user)` ✅ | 否 |
| npxg_trend 数据 | sync_router.py:483 | 已被 `GET /api/v1/sync/match_payload/{id}`（`get_current_user`）覆盖 | 否，已覆盖 |
| shot_map_data 数据 | sync_router.py:484 | 同上 | 否，已覆盖 |
| `POST /api/v1/lineup_eval` | api_server.py:420 | **无鉴权** 🔴 | **是（B2）→ 已修复** |
| `GET /api/v1/strategies/equity_curves` | report_router.py:343 | **无鉴权** 🔴 | **是（B3）→ 已修复** |

npxg 差值图和射门分布图数据均通过 `sync_router.get_match_payload` 作为 payload 字段返回，该端点已有 `Depends(get_current_user)`（line 454），无独立暴露的无鉴权路径。

---

## 修复 diff

### B2 — `api_server.py`（lineup_eval 加 JWT 鉴权）

```diff
--- api_server.py.bak.20260429
+++ api_server.py
@@ -418,7 +418,11 @@
 
 
 @app.post("/api/v1/lineup_eval")
-def evaluate_lineup(request: LineupEvaluationRequest, http_request: Request):
+def evaluate_lineup(
+    request: LineupEvaluationRequest,
+    http_request: Request,
+    user: CurrentUser = Depends(get_current_user),  # 2026-04-29 P0 修复：登录才可访问（注册用户即可，无需 VIP）
+):
     from rate_limit import hit as _rl, client_ip as _cip
     _rl("lineup_eval", _cip(http_request), 30)  # 阵容评测较重，30/min per IP
```

### B3 — `report_router.py`（equity_curves 加 JWT 鉴权）

```diff
--- report_router.py.bak.20260429
+++ report_router.py
@@ -341,7 +341,9 @@
 
 
 @router.get("/strategies/equity_curves")
-async def get_equity_curves():
+async def get_equity_curves(
+    user: CurrentUser = Depends(get_current_user),  # 2026-04-29 P0 修复：登录才可访问（注册用户即可，无需 VIP）
+):
     """
     返回 V4 模型 OOS 权益曲线数据，供首页策略展示图表使用。
```

---

## Step 7 — 验证结果

### 无 token 测试（应全部 4xx）

| 端点 | 期望 | 实际 | 状态 |
|------|------|------|------|
| `GET /api/v1/report/12345` | 410 | **410** | ✅ |
| `POST /api/v1/lineup_eval` (无 token) | 401 | **401** | ✅ |
| `GET /api/v1/strategies/equity_curves` (无 token) | 401 | **401** | ✅ |

### 有效 JWT 测试（VIP user_id=3，应全部 200）

| 端点 | 期望 | 实际 | 状态 |
|------|------|------|------|
| `POST /api/v1/lineup_eval` + Bearer token | 200 | **200** | ✅ |
| `GET /api/v1/strategies/equity_curves` + Bearer token | 200 | **200** | ✅ |
| `GET /api/v1/quant/5205813` + Bearer token | 200 | **200** | ✅（不受影响） |

---

## PM2 重启后日志（最近 30 行）

```
2026-04-29 20:21:47: [DEBUG] api_server.DB_PATH=/home/ubuntu/app/backend/football_uk.db, exists=True
2026-04-29 20:21:47: [DEBUG] db_migrate.DB_PATH=/home/ubuntu/app/backend/football_uk.db, exists=True
2026-04-29 20:21:47: [INFO] Probability calibrators loaded successfully.
2026-04-29 20:21:47: 🚀 启动数据总线服务 (9.0 终极容错版)...
2026-04-29 20:21:47: INFO: Started server process [453566]
2026-04-29 20:21:47: INFO: Waiting for application startup.
2026-04-29 20:21:47: INFO: Application startup complete.
2026-04-29 20:21:47: INFO: Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

无 ImportError / NameError / 崩溃。唯一的 DeprecationWarning（`on_event` → lifespan）为预存警告，与本次改动无关。

---

## 修复端点汇总

| # | 端点 | 修复方式 | 文件 |
|---|------|---------|------|
| B1 | `GET /api/v1/report/{match_id}` | 已由 api_server.py:171 提前废弃（410），无需改动 | api_server.py（现有） |
| B2 | `POST /api/v1/lineup_eval` | 加 `Depends(get_current_user)` | api_server.py:420–425 |
| B3 | `GET /api/v1/strategies/equity_curves` | 加 `Depends(get_current_user)` | report_router.py:343–345 |

---

## 遗留问题 / 未偏离计划之处

- **archive 接口**：按任务规定「完全不动」，registered 用户仍可访问历史 inference（audit_module1_payment.md 中已标 R1）
- **字段截断逻辑**（sync_router / reports/latest）：未触碰
- **P1/P2 项**（timing-safe / 超管 jti / CDK expires_at）：未触碰
- **前端代码**：未触碰
- **备份文件**：`api_server.py.bak.20260429` / `report_router.py.bak.20260429` 均保留
