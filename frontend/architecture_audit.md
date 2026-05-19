# 喵弟量化实验室：架构审计报告 (Cloud-Local Separation 2.0)

**审计人员**：高级技术审计员 (Antigravity)
**审计日期**：2026-04-03
**项目状态**：全链路联调阶段 (v2.0 架构)

---

## 1. 系统架构与数据流转现状

目前系统已成功实现 **“云本分离 2.0”** 模式，其核心哲学是 **“本地烘焙，云端透传”**。

- **提前烘焙 (Pre-baking)**：
  - **脚本端**：`scripts/sync_overview.py` 和 `scripts/aws_pusher.py` 承担了 100% 的业务权重。它们负责从复杂的本地 SQLite 多表中联表查询、执行下划线转驼峰的字段映射、计算比赛阶段分类（Upcoming/Archive）。
  - **优势**：云端完全不感知业务逻辑，数据库压力降至最低，前端拿到的就是可以直接消费的“成型 JSON”。

- **透明透传 (Transparent Pass-through)**：
  - **API端**：FastAPI (`main.py`) 仅作为 JSON 快照的持久化 KV 存储（以 `match_id` 或 `current_snapshot` 为 Key）。
  - **流程**：`POST` 接收原始 Body -> 存入 Text/JSONB 字段 -> `GET` 直接返回该字符串。
  - **优势**：极高的响应速度，云端代码零维护成本，极大降低了因数据库 Schema 变更导致的 500 风险。

---

## 2. 前后端数据契约 (Data Contracts) 审查

经过对 `scripts/` (Python) 与 `frontend/types/` (TypeScript) 的对照，扫描结果如下：

### ✅ 严格对齐项 (Overview)
- **ID 映射**：Python 使用 `id: str(row['match_id'])`，前端 `Match` interface 使用 `id: string`。**完全吻合**。
- **大盘分类**：`display_category` 字段逻辑（UPCOMING/ARCHIVE）在 Python 中生成，前端通过 `activeTab` 状态准确过滤。字段名与枚举值一致。

### ⚠️ 高风险不一致 (Payload)
- **结构坍塌隐患**：
  - **Python 处理**：`aws_pusher.py` 在兜底逻辑中，将缺失的 `npxg_trend` 和 `shot_map_data` 设为 `[]` (List)。
  - **前端预期**：`hooks/useMatchPayload.ts` 定义的 `NpxgTrend` 是一个对象结构 `{ home_team: { overall: [] }, ... }`。
  - **后果**：当 Python 推送空数组 `[]` 时，前端执行 `data.npxg_trend?.home_team?.overall` 会因访问数组上的不存在属性而返回 `undefined`。虽然 `hooks` 增加了 `parseIfString` 和 `EMPTY_TREND` 兜底，但这种 **“数组 vs 对象”** 的基础类型不匹配是典型的契约隐患。

- **字段名拼写检查**：
  - `aws_pusher.py` 推送 `match_id`。
  - `types/report.ts` 中存在两个定义：`CloudReportPayload` 使用 `match_id`，而 `ReportData`（UI 内部对象）使用 `matchId`。
  - **风险**：在 `useMatchPayload.ts` 转换层需要格外小心，目前 `...raw` 扩展操作会保留 `match_id`，若 UI 误引用 `matchId` 将导致空值。

---

## 3. 代码异味与脆弱点 (Code Smells & Vulnerabilities)

### 🔴 前端 Next.js 缓存风险
- **风险描述**：`app/page.tsx` 中使用了 `?t=${Date.now()}` 来强制刷新，这属于“暴力旁路”。
- **脆弱点**：Next.js 15+ 的 `fetch` 默认具有极强的持久化缓存。如果云端通过本地脚本同步了新数据，但前端 `App Router` 命中缓存，用户将看到过时的时间轴位次，造成“赔率或研报滞后”的严重体验问题。

### 🟡 ECharts 空数据崩溃风险
- **风险描述**：`TeamTrendChart` 等组件强依赖于数组内容的有效性。
- **脆弱点**：如果 `npxg_trend` 经过 `parseIfString` 后得到的虽然不是 null，但其中的 `overall` 列表长度为 0，部分 ECharts 配置（如计算 Y 轴 Max/Min）可能会因为 `Math.max(...emptyArray)` 得到 `-Infinity`，导致 Canvas 渲染崩溃或白屏。

### 🟠 安全性脆弱性
- **Token 硬编码**：`miaodi_secret_2026` 散落在多个文件中。
- **越权推送**：目前的 `X-Sync-Token` 校验在 FastAPI 中虽然存在，但属于全域令牌。如果泄露，攻击者可以覆盖任何一场比赛的 Payload。

---

## 4. 交接专家改进建议 (Refactoring Roadmap)

1.  **[P0] 统一 Payload 骨架**：
    修改 `scripts/aws_pusher.py` 的兜底逻辑，确保即便空数据也推送对象结构（例如 `{"home_team": {"overall": []}, "away_team": ...}`），而非空数组 `[]`。

2.  **[P1] 环境配置隔离**：
    立即引入 `.env` 系统。将 `CLOUD_API_URL`、`DB_PATH` 以及 `SYNC_TOKEN` 从代码中剥离，特别是本地脚本和云端 FastAPI 必须共用一套环境变量逻辑。

3.  **[P2] 前端数据洗涤层 (Adapter)**：
    在 `useMatchPayload.ts` 中增加一个 `normalizePayload` 函数，将 Python 风格的 `match_id` 转换为前端 UI 风格的 `matchId`，并补全所有缺失的 UI 字段，确保 UI 组件层不再需要感知数据是从哪里同步过来的。

4.  **[P2] 增加全局 Error Boundary**：
    在 `MatchReportDetail` 页面中，为图表组件包裹 `React ErrorBoundary`，防止单张 ECharts 图表的渲染异常导致整个研报页崩溃。
