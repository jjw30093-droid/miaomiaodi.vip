# 喵弟量化研究所 — 数据管道架构升级方案

## 一、现状诊断

### 你现在有什么
```
数据源(3个) → SQLite(40+表) → Python脚本(30+个) → PM2 Cron → FastAPI → Next.js
```

### 核心问题
1. **无分层概念**：dim_match、int_rolling、report_store 混在一个库里，没有 Bronze/Silver/Gold 的清晰边界
2. **管道耦合严重**：batch_sync 直接写 dim_match，feature_engineering 直接读写 int_*，出错时不知道哪一层坏了
3. **没有数据合约**：Python 推送的 JSON 结构和前端期望的不一致，每次改都可能引入新bug
4. **模型和数据混训**：校准器用错了模型路径、赔率spider抓错比赛，根因都是管道没有校验环节
5. **调度靠PM2 cron**：没有依赖关系管理，job-retrain 可能在 job-postmatch 之前跑

### 你做得好的地方
- 特征工程体系完整（Elo、rolling、shot_pace、opp_adj_npxgd）
- 4-Agent LangGraph 架构优雅
- 闭环反馈链路已打通（predict → audit → drift → retrain）
- 实时首发更新机制（poll_lineup 每5分钟）

---

## 二、目标架构

借鉴 GoalAlpha 的"共享底座 + 多管线"思路 和 KwachuQ 的 Medallion 架构，但**不引入 Airflow/Docker/PostgreSQL 等重型基础设施**（你是独立开发者，轻量化优先）。

### 核心原则
- **SQLite 够用就继续用**（82MB，单机写入没有并发瓶颈）
- **PM2 继续用**（但加依赖链保护）
- **用 Python 脚本实现 Medallion 分层**（不需要 dbt CLI，直接 SQL + Python）
- **每一层有明确的输入/输出/校验规则**

### 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    数据源层 (Sources)                        │
│  FotMob API  │  NowGoal Spider  │  Football-Data CSV        │
└──────┬───────┴────────┬─────────┴────────┬──────────────────┘
       │                │                  │
       ↓                ↓                  ↓
┌─────────────────────────────────────────────────────────────┐
│               Bronze 层 (原始数据，只追加不修改)              │
│                                                              │
│  表命名: bronze_*                                            │
│  · bronze_match_raw      ← batch_fotmob_sync 写入           │
│  · bronze_team_stats     ← 原始 fact_team_match_stats       │
│  · bronze_shotmap        ← 原始 fact_shotmap                │
│  · bronze_player_stats   ← 原始 fact_player_match_stats     │
│  · bronze_odds_csv       ← football-data.co.uk CSV          │
│  · bronze_odds_live      ← titan_odds_spider JSON→SQL       │
│                                                              │
│  规则: INSERT ONLY，保留原始字段名，不做任何计算              │
│  校验: 每次写入后检查 row_count 增量，异常则报警              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ↓
┌─────────────────────────────────────────────────────────────┐
│               Silver 层 (清洗标准化，可重跑)                  │
│                                                              │
│  表命名: silver_*                                            │
│  · silver_match          ← 标准化队名、日期、League分类      │
│  · silver_team_stats     ← home/away 拆分、类型转换          │
│  · silver_odds           ← 多源合并(CSV+live)、队名映射      │
│  · silver_player         ← 球员标准化、去重                  │
│                                                              │
│  规则: DELETE + INSERT (全量重建)，幂等可重跑                │
│  校验: 队名映射覆盖率 > 95%，赔率主客方向验证                │
│  新增: 赔率方向校验(AH vs EU一致性检查在这里做)              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ↓
┌─────────────────────────────────────────────────────────────┐
│               Gold 层 (特征 + 模型 + 产品)                   │
│                                                              │
│  子层 1: 特征库 (Features)                                   │
│  · gold_team_rolling     ← 5/10场滚动(npxGD, ppda, Elo等)   │
│  · gold_match_features   ← 单场特征向量(45+维)              │
│  · gold_player_influence ← 球员防守贡献基线                  │
│                                                              │
│  子层 2: 模型产物 (Model Artifacts)                          │
│  · models_v4/model_wdl.lgb                                  │
│  · models_v4/model_ou.lgb                                   │
│  · models_v4/calibrators.pkl                                │
│  · models_v4/meta.json (含 feature_importance, RPS)         │
│                                                              │
│  子层 3: 产品输出 (Products)                                 │
│  · gold_prediction_audit ← 预测记录 + 审计结果               │
│  · gold_report_store     ← 研报内容 + 推荐方向               │
│  · gold_model_health     ← 漂移检测日志                      │
│                                                              │
│  规则: 特征库可重算，模型产物版本化，产品输出不可逆           │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ↓
┌─────────────────────────────────────────────────────────────┐
│               服务层 (API + Frontend)                        │
│                                                              │
│  FastAPI ← 读取 gold_report_store + gold_prediction_audit   │
│  Next.js ← 渲染研报 + ECharts图表                           │
│  WeChat OAuth + CDK 变现                                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、管道编排（替代当前PM2散乱cron）

### 当前问题
PM2 cron 没有依赖关系，所有 job 独立触发。`job-retrain` 可能在 `job-postmatch` 之前跑。

### 方案：Pipeline Runner（轻量级依赖链）

**不引入 Airflow**，用一个 Python 脚本 `pipeline_runner.py` 管理依赖：

```python
# pipeline_runner.py — 每日主管道（替代多个独立cron）
# 一个cron触发: 03:00 UTC，内部按顺序执行

PIPELINE = [
    # Step 1: Bronze — 数据采集
    {"name": "ingest_matches",   "script": "scripts/batch_fotmob_sync.py",  "timeout": 600},
    {"name": "ingest_odds",      "script": "titan_odds_spider.py",          "timeout": 300},

    # Step 2: Silver — 清洗标准化
    {"name": "silver_transform", "script": "pipeline/silver_transform.py",  "timeout": 300},

    # Step 3: Gold — 特征计算
    {"name": "feature_eng",      "script": "feature_engineering.py",        "timeout": 600},

    # Step 4: Gold — 研报生成
    {"name": "schedule",         "script": "fotmob_scheduler.py",           "timeout": 120},
    {"name": "reports",          "script": "run_tonight_reports.py",        "timeout": 1200},

    # Step 5: Gold — 赛后审计（对昨天的比赛）
    {"name": "postmatch",        "script": "post_match_review.py",         "timeout": 300},

    # Step 6: Gold — 模型迭代
    {"name": "retrain_check",    "script": "retrain_if_needed.py",         "timeout": 1800},
]

# 每个 step 执行前检查上一步成功，失败则停止并通知
# 支持 --from step_name 从某一步开始（断点续跑）
# 支持 --only step_name 只跑某一步（调试用）
```

### 独立cron保留
- `poll_lineup.py` — 每5分钟（实时性要求高，不进主管道）
- `titan_odds_spider.py` — 每30分钟刷新赔率（也独立）

### PM2 简化为3个cron
```javascript
// 1. 每日主管道（03:00 UTC）
{ name: 'daily-pipeline', script: 'pipeline_runner.py', cron: '0 3 * * *' }

// 2. 赔率轮询（每30分钟）
{ name: 'odds-refresh',   script: 'titan_odds_spider.py', cron: '*/30 * * * *' }

// 3. 首发轮询（每5分钟）
{ name: 'lineup-poll',    script: 'poll_lineup.py', cron: '*/5 * * * *' }
```

---

## 四、数据质量校验（每层都有 Gate）

### Bronze Gate（采集后）
```python
def validate_bronze(conn):
    checks = [
        ("match_count", "SELECT COUNT(*) FROM bronze_match_raw WHERE Date = ?", [yesterday]),
        ("stats_count", "SELECT COUNT(*) FROM bronze_team_stats WHERE match_id IN (SELECT Match_ID FROM bronze_match_raw WHERE Date = ?)", [yesterday]),
    ]
    for name, sql, params in checks:
        result = conn.execute(sql, params).fetchone()[0]
        if result == 0:
            raise QualityGateError(f"Bronze gate failed: {name} = 0")
```

### Silver Gate（清洗后）
```python
def validate_silver(conn):
    # 队名映射覆盖率
    unmapped = conn.execute("SELECT COUNT(*) FROM silver_match WHERE home_team_std IS NULL").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM silver_match").fetchone()[0]
    if unmapped / total > 0.05:
        raise QualityGateError(f"队名映射覆盖率不足: {unmapped}/{total}")

    # 赔率方向校验（AH和EU一致性）
    suspicious = conn.execute("""
        SELECT COUNT(*) FROM silver_odds
        WHERE ah_line > 0 AND eu_home > eu_away  -- AH说客让球但EU说主队热门
           OR ah_line < 0 AND eu_home < eu_away  -- AH说主让球但EU说客队热门
    """).fetchone()[0]
    if suspicious > 0:
        log.warning(f"⚠️ {suspicious} 场赔率方向可疑（AH/EU不一致）")
```

### Gold Gate（特征后）
```python
def validate_gold(conn):
    # 特征完整性
    missing_features = conn.execute("""
        SELECT COUNT(*) FROM gold_match_features
        WHERE home_elo IS NULL OR away_elo IS NULL
    """).fetchone()[0]

    # 模型输出合理性
    absurd_preds = conn.execute("""
        SELECT COUNT(*) FROM gold_prediction_audit
        WHERE pred_wdl_draw < 0.03 OR pred_wdl_home > 0.95
    """).fetchone()[0]
    if absurd_preds > 0:
        log.warning(f"⚠️ {absurd_preds} 场预测概率异常")
```

---

## 五、数据源管理

### 当前数据源
| 源 | 用途 | 可靠性 | 改进 |
|---|------|--------|------|
| FotMob SSR | 赛程+比分+首发+shotmap | 中（偶尔502） | 加备用源 |
| NowGoal | 赔率(EU+AH+OU) | 低（模糊匹配易错） | **已修复主客校验** |
| Football-Data CSV | 历史赔率 | 高（但需手动更新） | 自动化下载 |

### 建议新增数据源
1. **Transfermarkt** — 球员身价、伤停信息（当前靠FotMob，不够全）
2. **FBref/StatsBomb** — 更详细的xG/xA数据（free tier）
3. **Pinnacle/Betfair** — 更精准的closing line赔率（训练数据用）

### 数据源抽象层
```python
# data_sources/base.py
class DataSource(ABC):
    @abstractmethod
    def fetch(self, match_id: str) -> dict: ...

    @abstractmethod
    def validate(self, data: dict) -> bool: ...

# data_sources/fotmob.py
class FotMobSource(DataSource):
    def fetch(self, match_id):
        return self.client.match_details(match_id)

    def validate(self, data):
        return data.get("general", {}).get("matchId") is not None

# data_sources/nowgoal.py
class NowGoalSource(DataSource):
    def fetch(self, match_id):
        titan_id, is_swapped = self.find_titan_id(match_id)
        odds = self.fetch_odds(titan_id)
        if is_swapped: odds = self.swap_home_away(odds)
        return odds

    def validate(self, data):
        eu = data.get("european_1x2", {}).get("latest", {})
        return float(eu.get("home", 0)) > 1  # 赔率必须>1
```

---

## 六、模型管道（ML Pipeline）

### 当前 vs 目标

| 环节 | 当前 | 目标 |
|------|------|------|
| 训练数据 | `prepare_training_data()` 内联SQL | 读取 `gold_match_features` 表 |
| 特征一致性 | 训练和推理用不同路径组装 | 统一从 `build_feature_row()` |
| Train/Val | 刚加的80/20 | 保持，加OOS验证 |
| 模型评估 | RPS + Brier | 加校准曲线、模型vs市场对比 |
| 校准 | IsotonicRegression (有阶梯问题) | 混合校准(80% raw + 20% cal) |
| 版本管理 | `models_v4/` 硬编码 | `models/{version}/` + meta.json 记录版本链 |
| A/B测试 | 无 | Shadow model: 新模型和旧模型同时预测，比较后切换 |

### 评估框架（借鉴GoalAlpha的RPS+校准曲线思路）

```python
# evaluation.py
class ModelEvaluator:
    def __init__(self, y_true, y_pred_probs, odds_implied=None):
        self.y_true = y_true
        self.y_pred = y_pred_probs
        self.odds = odds_implied

    def rps(self):
        """Ranked Probability Score — WDL分布质量"""
        ...

    def calibration_curve(self, n_bins=10):
        """分桶校准: 每个概率区间的预测均值 vs 实际频率"""
        ...

    def model_vs_market(self):
        """模型RPS vs 赔率RPS — 模型是否有附加价值"""
        ...

    def report(self) -> dict:
        """输出完整评估报告，保存到 models/{version}/eval_report.json"""
        ...
```

---

## 七、执行计划（分4期）

### 第1期：管道编排 + 质量门（1-2天）
- [ ] 创建 `pipeline_runner.py` 替代散乱cron
- [ ] 添加 Bronze/Silver/Gold 质量校验
- [ ] 简化 ecosystem.config.js 为3个cron
- **收益**：出问题时秒定位是哪一层

### 第2期：Silver层标准化（2-3天）
- [ ] 创建 `silver_transform.py`：队名映射、赔率合并、方向校验
- [ ] 赔率AH/EU一致性检查（替代Elo保护的更优方案）
- [ ] 统一数据合约（Python输出结构 = 前端期望结构）
- **收益**：赔率错误在Silver层就被拦截

### 第3期：特征一致性 + 模型版本化（2-3天）
- [ ] 训练和推理统一用 `build_feature_row()`
- [ ] `models/{version}/` 目录结构 + meta.json 版本链
- [ ] 评估框架：RPS + 校准曲线 + 模型vs市场
- **收益**：不再出现校准器/模型路径混乱

### 第4期：监控 + 告警（1-2天）
- [ ] Telegram Bot 告警（管道失败、漂移检测、赔率异常）
- [ ] 每日健康报告（自动发送到Telegram）
- [ ] 简单 dashboard（可选，用 Metabase 或纯 HTML）
- **收益**：不用每天手动检查日志

---

## 八、和参考项目的对比

| 维度 | KwachuQ (GitHub) | GoalAlpha (小红书) | 喵弟(你) | 建议 |
|------|-------------------|---------------------|----------|------|
| 数据源 | SofaScore API | 多源 | FotMob+NowGoal+CSV | 够用，加赔率校验 |
| 存储 | PostgreSQL+MinIO | MySQL | SQLite | SQLite够用 |
| 分层 | 明确Medallion | 共享底座+隔离管线 | 无分层 | **加Medallion** |
| 调度 | Airflow DAG | 自研调度 | PM2 cron | **加pipeline_runner** |
| 转换 | dbt(SQL) | 自研 | dbt+Python混用 | 统一为Python |
| 模型 | 无(纯BI) | LightGBM+DC+Stacking | LightGBM+校准 | 加评估框架 |
| 校准 | 无 | 多层校准 | IsotonicRegression | **加混合校准** |
| 前端 | Metabase | Glass UI | Next.js | 继续Next.js |
| 变现 | 无 | 无(?) | WeChat+CDK | 你的优势 |

### 你不需要的
- ❌ Airflow（太重，你一个人维护不了）
- ❌ PostgreSQL（SQLite完全够用）
- ❌ Docker（AWS上直接跑就行）
- ❌ MinIO（你没有多节点存储需求）
- ❌ Dixon-Coles模型（GoalAlpha用的，比LightGBM难维护）

### 你需要的
- ✅ Medallion分层思想（不需要物理分库，表命名约定即可）
- ✅ 质量门（每层校验）
- ✅ 管道依赖链（pipeline_runner）
- ✅ 评估框架（RPS + 校准曲线）
- ✅ 数据合约（Python输出结构强校验）
