# 喵弟量化 Backend — Claude 操作守则

> 本文件记录真实事故与铁律。每条规则背后都有一次线上故障。**不得删除本文件。**

---

## 1. 🚨 时区标准：统一使用 UTC 开球日期（2026-04-23 修复）

**背景**：`dim_match.Date`、`report_store.match_time`、`prediction_audit.match_date` 三张表各用不同时区基准，导致欧洲 19:00 UTC 场次的日期全部差一天，post_match_review 无法正确匹配复盘。

### 铁律
- **`dim_match.Date`** = UTC 开球日期（从 `status.utcTime` 解析，不用 Fotmob 查询日期）
- **`report_store.match_time`** = UTC 开球时间（格式 `YYYY-MM-DD HH:MM:SS`）
- **`prediction_audit.match_date`** = UTC 开球日期（用 `m.get('date')` 即 kickoff UTC date，不用 `date.today()`）
- **绝对不要**用 Fotmob 的查询日期 `d` 作为 dim_match.Date（Fotmob 按 CST 分桶，欧洲晚场会错位 +1 天）

### 关键代码位置
- `scripts/batch_fotmob_sync.py:275` — 必须解析 `status.utcTime` 取 UTC date
- `run_tonight_reports.py:1309` — `report_date` 必须用 `m.get('date', report_date)`
- `fotmob_scheduler.py:93` — 已正确使用 `kickoff.strftime("%Y-%m-%d %H:%M:%S")`（UTC）

---

## 2. 🚨 dim_match 没有 kickoff_time 列（2026-04 事故）

`dim_match` 表**没有** `kickoff_time` 列，只有 `Date`（字符串，UTC 日期）。

任何需要开球时间的查询，必须 JOIN `report_store.match_time`：
```sql
JOIN report_store rs ON CAST(rs.match_id AS TEXT) = CAST(d.Match_ID AS TEXT)
WHERE rs.match_time >= datetime('now', '-6 hours')
```

---

## 3. 数据库路径：只用 football_uk.db（2026-04 修复）

| 文件 | 状态 |
|------|------|
| `football_uk.db` | ✅ 唯一生产库，~106MB（2026-04-27 实测） |
| `football_data.db` | ❌ 旧测试库，已废弃 |
| `football.db` | ❌ 已删除（空文件） |

`.env` 必须写：`DB_PATH=/home/ubuntu/app/backend/football_uk.db`

---

## 4. 服务器目录结构（不得删除的目录）

```
/home/ubuntu/app/backend/
├── football_uk.db          ← 生产数据库，绝对不删
├── backups/                ← 自动备份，绝对不删
├── models_v4/              ← 当前使用的 ML 模型，绝对不删
├── venv/                   ← Python 虚拟环境（22,537 个文件，正常）
├── logs/                   ← pm2 日志，自动轮转，不手动删
├── reports/                ← 历史研报，可压缩归档但不直接删
├── schedule/               ← 当日赛程 JSON，runtime 文件
├── odds/                   ← 赔率数据
└── quant_dbt/              ← dbt 模型代码
```

**可以删除的（清理时参考）**：
- `*.bak`, `*_bak`, `*_old`, `*_v1`, `*_deprecated` 命名的文件
- `check_*.py`, `fix_*.py` 一次性调试脚本
- `__pycache__/`, `*.pyc`
- `.DS_Store`

---

## 5. API 速率限制与 IP 提取（2026-04 修复）

服务器在 Cloudflare + Nginx 后面，`request.client.host` 永远是 `127.0.0.1`。

**必须用 `rate_limit.client_ip(request)`** 提取真实 IP：
```python
from rate_limit import client_ip as _client_ip
real_ip = _client_ip(request)  # CF-Connecting-IP → X-Real-IP → X-Forwarded-For
```

已加速率限制的端点：
- `/api/v1/quant/{match_id}` — 60次/分钟/IP
- `/api/v1/market/{match_id}` — 60次/分钟/IP
- `/api/v1/lineup_eval` — 30次/分钟/IP
- `/wechat/code` — 10次/分钟/IP
- `/wechat/webhook` — 120次/分钟/IP

---

## 6. pm2 cron 进程 stopped 状态是正常的

pm2 里 `status=stopped` 的 cron job **不是故障**，是正常的 cron 等待状态。
只有 `autorestart: true` 的进程才会在跑完后 restart。

**真正异常**：连续 restart 次数 `↺` 很高 + exit_code 非 0。

---

## 7. closing_odds_retry 查询模板

`dim_match` 没有 kickoff_time，必须 JOIN report_store：
```sql
SELECT d.Match_ID, d.Date, d.Home_Team_Name, d.Away_Team_Name
FROM dim_match d
JOIN report_store rs ON CAST(rs.match_id AS TEXT) = CAST(d.Match_ID AS TEXT)
WHERE d.status = 'Finish'
  AND rs.match_time IS NOT NULL
  AND rs.match_time <= datetime('now', '-15 minutes')
  AND rs.match_time >= datetime('now', '-6 hours')
  AND NOT EXISTS (
      SELECT 1 FROM silver_match_odds s
      WHERE s.match_id = d.Match_ID AND s.period = 'closing'
  )
```

---

## 8. 模型漂移告警触发逻辑（review_engine.py）

**2026-05-04 升级**：阈值收紧 + 加 AH 维度 + 触发后自动调 recalibrate（subprocess.Popen），从"只打印建议"升级为"自动动作"。

漂移判定为四选一（满足任意一个触发 Server 酱推送 + 自动 recalibrate）：

| 指标 | 阈值 | 旧值 |
|------|------|------|
| WDL 准确率（近 50 场） | < **42%** | 38% |
| OU 准确率（近 50 场） | < **48%** | 50% |
| **AH 准确率（picked_market='ah'，近 50 场内 n≥10）** | < **42%** | 不存在 |
| Brier WDL 得分 | > 0.75 | 0.75 |

AH 命中率使用 `picked_correct`（推荐胜率），半负记 0.25 分。

推送消息显示哪个穿底要看具体数值，不要只看消息标题判断。

### 触发后自动动作（2026-05-04 落地）
`ReviewEngine.AUTO_RECALIB_ON_DRIFT = True` 时，drift=True 会立即 `subprocess.Popen([python, "-m", "recalibrate"])` 异步重训，并写一条 `ingest_failure_log step='drift_auto_recalibrate'` 作为审计。

### 样本数累积型自动触发（用户铁律：满 200 场必触发）
`scripts/check_recalib_trigger.py` 由 `job-check-recalib-trigger` cron 每日 03:35 UTC 跑：
- 读 `models_v4/calibration.json.updated_at` 作为上次 recalibrate 时戳
- COUNT(*) prediction_audit WHERE actual_wdl IS NOT NULL AND audit_time > 上次时戳
- 累积 ≥ `RECALIB_TRIGGER_SAMPLES`（默认 200）→ subprocess 调 recalibrate
- 写 `ingest_failure_log step='auto_recalibrate' resolved=1` 作为审计痕迹

**事故起因**：4/14 ~ 5/4 累积 289 场仍无任何重训，因为旧代码：
1. `check_drift` 只看胜率不计样本累积
2. 旧阈值 38/50/0.75 太宽，5/2 实测 WDL=40%/OU=51%/brier=0.233 全擦边过关
3. AH 完全不在 drift 里
4. 触发后只 `print` 不动作

**修复后**：任意一项漂移立即重训 + 满 200 场必重训 + 周一 cron 兜底。

### 关键文件
- `review_engine.py` — `check_drift()` 加 ah_acc + 收紧阈值 + `_auto_recalibrate()`
- `scripts/check_recalib_trigger.py` — 累积触发器（新建）
- `recalibrate.py` — 第 3 步追加 `calibration_engine.train()` 重训 calibrators.pkl
- `ecosystem.config.js` — `job-check-recalib-trigger` cron 03:35 UTC

### AH 联赛黑名单（同次落地，详见 run_tonight_reports.py）
近 14 天 picked_market='ah' 实际胜率 < 35% 的联赛在 `_select_single_pick()` 中跳过 AH 候选，让 OU 单独竞争。当前已知触发：英超(47) 20%、J联赛(223) 31%。
环境变量 `AH_LEAGUE_BLACKLIST_THRESHOLD` 可覆盖。

**2026-05-04 增补 #2：AH 模型切换 V5 Lambda + 黑名单仅看 Lambda 数据**：黑名单 SQL 加 `AND pa.ah_source='v5_lambda'` 过滤——Lambda 之前的 v4 数据不再污染黑名单判定。Lambda 测试集英超 61%、J联赛 70%，远超阈值 35%，切换后 14 天内 n<5 → 黑名单不触发。

### AH 置信度阈值（同次落地）
AH market 的 HIGH 阈值由 0.45 收紧到 0.55（OU 保留 0.45）。
理由：5 月初观察 AH HIGH 26 场仅 34.6% 胜率，明显比 MID（50%）差，原阈值过于激进。

### V5 Lambda AH 模型上线（2026-05-04 增补 #2）

AH 模型由 v5_lambda 双 CatBoost + Dixon-Coles ρ 完全接管：
- 路径：`/home/ubuntu/app/backend/models_v5_lambda/`（4 个 .cbm + rho.json）
- 推理：`lambda_ah_predictor.LambdaAHPredictor`（包装类，签名兼容旧 `ah_model.AHPredictor.predict_match`）
- 覆盖 8 个联赛：47/53/54/55/87/113/223/9080（NowGoal spider 当前白名单）
- 不在 8 联赛或特征行未生成时返回 None → run_tonight 不出 AH 让 OU 单独竞争
- **不留 v4 fallback**（用户铁律：不能一部分是 v4 一部分是 v5）
- 测试集 956 行（2026-01-10 → 2026-04-27）AH 56.6%（vs 当前生产 7d 36.6%）

每日 ETL 链：`job-build-lambda-features` cron `25 3 * * *` 跑 `scripts/rebuild_lambda_features.sh`：
1. `build_matrix_v5.py --include_future` → `mart_prediction_matrix_v5`
2. `build_ah_dataset_v5.py` → `mart_ah_dataset_v5`
3. `build_lambda_dataset_v5.py --include_future` → `mart_lambda_dataset_v5` 含 split='inference' 行

`prediction_audit.ah_source` 列记录每条 AH 推荐来源（'v5_lambda' / NULL）。`_get_ah_league_winrate()` 仅统计 ah_source='v5_lambda' 的样本，避免历史 v4 数据污染。

后续 Track B：扩展 NowGoal spider 联赛白名单 + 重训 Lambda 实现真正全联赛覆盖。

**2026-05-18 修补：v5 Lambda AH 概率日志补全**
修复前 `pred_ah_pick_v5` / `pred_ah_line_v5` 从未被写入（链路断裂：ah_pred 未透传进 job dict → log_prediction 没有 v5 参数 → UPDATE 语句无 v5 列）。
修复内容：
- 新增 `pred_ah_cover_v5 REAL` 列（与 `pred_ou_over_v5` 命名对称），迁移脚本 `db_migrate_ah_cover_v5.py`
- `pred_ah_pick_v5 TEXT` 存方向 'home'/'away'，`pred_ah_line_v5 REAL` 存盘口，`pred_ah_cover_v5 REAL` 存最佳方向覆盖概率
- `run_tonight_reports.py` 行 1819 job dict 加 `'ah_pred_v5': ah_pred`；行 1055 log_prediction 调用加 `ah_pred_v5` / `ah_line_v5` 参数
- `review_engine.py` log_prediction 签名加 `ah_pred_v5=None, ah_line_v5=None`；UPDATE SQL 扩 3 列
- 历史 6 行 v5_lambda 记录 NULL 不回填（重跑会污染历史审计语义）

### 关键文件（V5 Lambda）
- `lambda_ah_predictor.py` — Lambda AH 预测器（新建）
- `v5_feature_engineering/inference_lambda.py` — score matrix + derive_ah 纯函数库
- `v5_feature_engineering/train_lambda_v5.py` — 训练入口
- `v5_feature_engineering/build_matrix_v5.py` / `build_lambda_dataset_v5.py` — ETL（已加 `--include_future`）
- `scripts/rebuild_lambda_features.sh` — 三步 ETL bash wrapper
- `models_v5_lambda/` — 4 个 cbm + rho.json
- 旧 `models_v4/ah_*.lgb` 不删（保留作回滚保险）

### V5 Lambda 也接管 OU + conf_score 公式对齐（2026-05-04 增补 #3）

**背景**：v4 OU LightGBM 7天命中率 42.9%（仅勉强超硬币），Lambda 测试集 OU 52.2%（+2pp）。同一次 score_matrix 推断已经可以同时输出 OU 和 AH，顺手接管 OU 无额外成本。

**OU Lambda 覆盖**：
- `lambda_ah_predictor.predict_match_full(match_id, league_id, ou_line, ah_line)` 单次推理同时返回 `{ou, ah, lambda}` 三个子字典
- `predict_match()` 保持向后兼容（委托给 `predict_match_full` 并只返回 `result['ah']`）
- `run_tonight_reports.py` Step 1b 先调 `predict_match_full`；若在 8 联赛内，用 Lambda OU 覆盖 v4 OU（`ou_dict['over_25']` 原值存入 `over_25_v4_raw` 供 SHAP 审计）
- `ou_dict['ou_source'] = 'v5_lambda'`（8 联赛内）/ `None`（8 联赛外，使用 v4）

**跳过 v4 OU 专用校正**（Lambda 不需要）：
- `_select_single_pick`：若 `ou.get('ou_source') == 'v5_lambda'`，跳过 `_poisson_convert_ou` 和联赛 `ou_bias`（Lambda `derive_ou` 已按实际盘口线推断）
- Step 2c 量化概率基准线：同样分支跳过

**conf_score 公式对齐**：
- OU 基线从 `clip(actual_rate, 0.3, 0.7)`（约 0.47~0.62）改为固定 `0.5`（与 AH 一致）
- 同 prob=0.65 → OU 旧 score ≈ 0.22，新 score = 0.30（与 AH 相同）
- `OU_BIAS_SHIFT` env var 继续负责方向去偏（over/under 倾向校正），职责正交，不动

**ou_source 审计列**：
- `prediction_audit.ou_source TEXT`（2026-05-04 ALTER TABLE 已加）
- `review_engine.record_picked()` 写入：picked_market='ou' 时写 ou_source，其他市场留 NULL
- `_picks` dict 包含 `ou_source`，透传给 `record_picked`

**v4 OU LightGBM 仍保留**：仍在 run_tonight 内跑（for SHAP 归因图 + 8 联赛外兜底），不删。

---

## 9. WDL 推荐赔率门槛

`run_tonight_reports.py:480`：
```python
WDL_MIN_ODDS = 1.60  # WDL 赔率 <1.60 不出 WDL 推荐，让位给 OU/AH
```

低于 1.60 的 WDL pick 是历史遗留（规则加入前生成的报告），不是 bug。

---

## 10. JWT 有效期

`auth_deps.py`：`JWT_EXPIRE_DAYS = int(os.environ.get("JWT_EXPIRE_DAYS", "14"))`

默认 14 天（从 30 天缩短，2026-04 修复）。可通过 `.env` 覆盖。

---

## 11. 🚨 用户系统已知坑（2026-04-23）

### 11.1 超管（user_id=0）在 users 表里没有记录

`mintSuperAdminApiToken`（`lib/auth.ts`）签发的 JWT 里 `user_id=0`，而 `users` 表里没有 `id=0` 的行。

**不处理时的后果**：`GET /api/v1/user/me` 查不到记录 → 返回 404 → 前端 profile=null → 所有字段显示默认值。

**已修复（user_router.py `/me` 端点）**：user_id=0 时直接从 JWT claims 返回合成资料，不查 DB：
```python
if user.user_id == 0:
    return {
        "user_id": 0,
        "nickname": user.nickname or "超级管理员",
        "role": user.role or "admin",
        "openid_tail": "ADMIN",
        "created_at": None,
        ...
    }
```
**铁律**：修改 `user_router.py` 的 `/me` 端点时，不得删除这段 `user_id == 0` 的特判。

---

### 11.2 JWT 有效期：30 天（已从 14 天改为 30 天）

`auth_deps.py`：`JWT_EXPIRE_DAYS = int(os.environ.get("JWT_EXPIRE_DAYS", "30"))`

**注意**：第 10 条的描述有误（历史遗留），实际当前默认值是 **30 天**，不是 14 天。

---

### 11.3 用户自改昵称后，WeChat 登录不会覆盖

`wechat_auth_router.py` 的 poll 端点：仅在 `WECHAT_APPID` 和 `WECHAT_APPSECRET` **都配置**时才会拉取微信昵称并覆盖 DB。当前两者均未配置，所以：
- 用户在 app 里改的昵称（存 DB）**不会被登录覆盖**
- JWT 签发时直接用 DB 里的昵称

**铁律**：将来配置 WECHAT_APPID/APPSECRET 后，需要在覆盖逻辑里加判断：若用户已手动修改过昵称（`updated_at` 晚于 `created_at` 且 nickname != '足球探索者'），则不覆盖。

---

## 12. H9：rolling_zones / xG-split 特征训练实验（2026-04-23）

### 12.1 关键发现：zones 覆盖不足导致样本缩水

- `dim_match` 完赛（`status='Finish' AND home_score IS NOT NULL`）：**6782**
- 覆盖（`COUNT(DISTINCT match_id)`）：
  - `int_match_features_extended`: **7384**
  - `int_team_rolling_extended`: **7384**
  - `int_team_rolling_features`: **7384**
  - `int_team_rolling_zones`: **2062** ← **瓶颈**
- `int_team_shot_zones` 日期范围（join `dim_match.Date`）：**2025-08-15 → 2026-03-27**（2063 场）
- `fact_shotmap` 覆盖（用 `dim_match` IN 子查询）：**2023-08-11 → 2026-04-22**（7355 场）

结论：不是 `fact_shotmap` ingest 少，也不是 `int_team_shot_zones.sql` 里有 Date/时间过滤；更可能是 `int_team_shot_zones` 依赖 `stg_player_stats` 做 `(match_id, player_id) -> team_id` 的 join，早期比赛的 player/team 映射不完整，导致 zones 特征缺失。

### 12.2 影子训练结果（不切换生产）

- **v4_refresh（52 features，同样本 6782）**：`rps_model = 0.1278`
- **v5_leftzones（66 features，zones 左连接，同样本 6782）**：`rps_model = 0.1279`
- **v5_xgonly（56 features，仅 xG-split，不含 zones，同样本 6782）**：`rps_model = 0.1282`

判定：在同样本对比下，本轮新增特征对 WDL 的 RPS **未达到 ≥0.001 改善阈值**。

### 12.3 OU holdout（2026-01 ~ 2026-04 完赛，n=1203，阈值 0.5）

- `v4_refresh` OU accuracy：**0.6043**（727/1203）
- `v5_leftzones` OU accuracy：**0.5919**（712/1203）
- `v5_xgonly` OU accuracy：**0.5860**（705/1203）

结论：该窗口内 OU 表现 v4_refresh 更优；本轮不建议切换线上 `MODELS_DIR`，保留为实验记录。

---

## 13. player stats / shot_zones 历史覆盖限制（2026-04-23）

`fact_player_match_stats` 和 `stg_player_stats` 只从 **2025-08-15** 起有数据，源头是 `scripts/batch_fotmob_sync.py` 的启动时间（以及其按近 7 天窗口同步的运行方式）。回溯到更早需要单独跑历史 backfill 脚本。

**不建议回填**：
- Phase 1 实验已证明 zones 特征即便样本扩到 6782 也无改善
- 回填 2 年需几小时 + 撞 Fotmob rate limit 风险
- 改善预测效果不确定

如果将来要评估更长窗口的特征（如赛季级 Elo / 疲劳），再评估是否值得回填。

---

## 14. 🚨 线程函数禁止引用 main() 局部变量（2026-04-25 事故）

**事故**：`run_tonight_reports.py:871` 在线程池函数 `_process_match_llm_phase(job)` 内部使用了 `args.version`，但 `args` 是 `main()` 的局部变量。线程内抛 `NameError: name 'args' is not defined`，被外层 `except Exception` 静默吞掉，仅打 WARNING。结果：连续 2 天所有研报生成成功但 **report_store 一行未入库**，首页 `/reports/latest` 全部归 ARCHIVE，UPCOMING 卡片清零，网站首页"看似在线但全空"。

### 铁律
- **线程/进程池函数体内不得引用 argparse 的 `args.*`**；需要的参数必须通过：
  1. 模块级常量（`REPORT_VERSION = ...`，由 main() 用 `global` 覆盖）
  2. 或 job dict 显式传入（`job['version']`）
- **不得用 `except Exception: log.warning(...)` 包住 DB 写入**。DB sync 失败必须 `log.error()` + 包含 match_id，必要时让任务整体失败让外层告警可见。
- **新增 CLI 参数后，必须 grep 该参数名在所有线程/进程池函数内的引用**：
  ```bash
  grep -n "args\." run_tonight_reports.py
  # 期望：所有命中行都在 def main(): 函数体内（行号 > main() 起始行）
  ```

### 何时复查这条规则
- 任何在 `run_tonight_reports.py` 增加 `parser.add_argument` 的 PR
- 任何把现有同步逻辑包进 `ThreadPoolExecutor` / `ProcessPoolExecutor` 的重构

---

## 15. 🚨 pm2 cron 顺序铁律：reader 必须在 writer 之后（2026-04-26 修复）

**事故**：`job-post-match-audit` 排 02:00 UTC，但它读取的 `dim_match.home_score` 要等到 `job-batch-sync` 03:00 UTC 才会写入。结果连续多月每天 audit 跑了等于没跑，`prediction_audit.actual_wdl` 永远滞后 24 小时。同样 `job-daily-backtest` (02:30) 和 `job-recalibrate` (周一 02:45) 也读 prediction_audit，都早于 audit。

### 数据流依赖（UTC，新 cron 必须遵守）
```
03:00  batch-sync         FotMob → dim_match (scores)
03:20  dbt-features       fact_* → dbt models
03:30  post-match-audit   dim_match → prediction_audit.actual_*
03:45  post-match-review  dim_match + report_store → LLM 复盘
04:00  scheduler          FotMob → target_matches.json
04:00  daily-backtest     prediction_audit → equity_curves.json
04:40  run-tonight        target_matches.json + report_store → 研报
04:45  recalibrate (Mon)  prediction_audit → 校准模型
04:50  shadow-v5          schedule → shadow predictions
```

### 铁律
- **新增任何 pm2 cron job 前，必须先确认它读哪些表 / 文件，再决定排在依赖 writer 之后**
- **读 `dim_match.home_score`、`fact_*`、`silver_match_odds` 的 job 最早 03:30 UTC 起步**
- **读 `prediction_audit.actual_*` 的 job 最早 04:00 UTC 起步**
- **修改任意 job cron 时，必须 `pm2 jlist | grep cron_restart` 检查所有 cron 时间，画依赖图验证顺序**
- **持久化使用 `pm2 save`**，不能只用 `pm2 restart --cron`（不持久化，重启服务器会丢失）

### 防御性日志
`post_match_review.py:get_finished_matches()` 已加 ERROR 日志：当 `prediction_audit` 有行但 `dim_match` 缺分数时打 ERROR。如果 cron 顺序回归会立刻告警。

### 自检脚本（2026-04-27 新增）
任何 cron 改动后必须运行：
```bash
cd /home/ubuntu/app/backend && python3 scripts/check_cron_order.py
```
脚本静态解析 `ecosystem.config.js`，按依赖图检查 reader vs writer 时间。
- exit 0 = 全部满足
- exit 1 = 列出违反条目（含 reader/writer cron 表达式 + 原因）
- 已落地依赖：post-match-audit > batch-sync, daily-backtest > audit, recalibrate > audit, post-match-review > batch-sync, dbt-features > batch-sync, run-tonight > scheduler, shadow-v5 > run-tonight。

---

## 16. 🚨 picks 不变量：每场已完赛比赛必须有 picked_market（2026-04-26 修复）

**业务前提**：网站对每场比赛收费 → 前端强制呈现推荐 → 复盘必须能查对错。
**永远不允许**出现"已完赛比赛但 prediction_audit.picked_market=NULL"的情况。

### 不变量
对任意 `dim_match.status='Finish' AND home_score IS NOT NULL` 的比赛：
- `prediction_audit.picked_market` 不得为 NULL
- `prediction_audit.picked_direction` 不得为 NULL
- `prediction_audit.picked_correct ∈ {0, 1, NULL(仅 push)}`
- `prediction_audit.picked_*` 必须与 `report_store.inference` 一致（**inference 是 source of truth**——它是用户付费看到的字符串）

### 写入路径（双写 + 自愈）
- Phase 1 B2 `record_picked()` 早写一次（让中间环节可读）
- Phase 2 `log_prediction(picks=...)` 在同一事务再写一次（覆盖式，幂等）
- 任意一处异常必须 `log.error + record_failure(step='record_picked'|'log_prediction')`，**禁止 `log.warning` 吞掉**
- 收尾 reconciliation：`run_tonight_reports.py` 与 `post_match_review.py` 都跑 `_reconcile_picks_for_today` / `reconcile_missing_picks`，基于 `pick_parser.parse_inference(report_store.inference)` 反解补写

### 监控
`compute_single_pick_stats` 返回 `n_missing_pick`；`print_summary` 见到 `>0` 必须告警 + 触发 reconciliation。

### 关键代码位置
- `pick_parser.py` — inference 文本反解共享模块
- `review_engine.py:log_prediction(picks=...)` — 单事务双写 picks
- `run_tonight_reports.py:_reconcile_picks_for_today()` — 报告生成结尾闸门
- `post_match_review.py:reconcile_missing_picks()` — 复盘前自愈
- `scripts/backfill_missing_picks.py` — 一次性历史回填

---

## 17. 📜 复盘 pipeline 事故全录（2026-04-23 → 2026-04-26）

### 事故 #1（2026-04-26 cron 顺序错乱）— 详见 §15
- **症状**：`prediction_audit.actual_wdl/ou` 全部 NULL，连续多月每天 audit 跑了等于没跑。
- **根因**：`job-post-match-audit` 02:00 UTC 跑在 `job-batch-sync` 03:00 UTC 之前。
- **教训**：reader 必须排在 writer 之后；新增 cron 必看依赖图（§15）。

### 事故 #2（2026-04-26 INSERT OR REPLACE 抹掉 picks）
- **症状**：4/25 全 30 场中 13 场 `picked_market=NULL`，复盘统计静默丢失。
- **根因**：`review_engine.py:log_prediction` 用 `INSERT OR REPLACE`，把 Phase 1 `record_picked` 写的 `picked_market/direction/odds/confidence` 抹平。
- **修复**：改为 `INSERT OR IGNORE + UPDATE`（仅更新本路径列），并让 `log_prediction(picks=...)` 在同一事务一并写 picks。
- **教训**：**`INSERT OR REPLACE` = `DELETE + INSERT`**，凡是该行被另一处 UPDATE 写入过的列都会被清空。涉及多写入路径的表禁用 REPLACE。

### 事故 #4（2026-04-26 picked_direction 双约定共存 + audit 早于 picks）— 详见 §18
- **症状**：周末 WDL 市场出现 1 场 `picked_correct=NULL`（market=wdl 不应有 push）。
- **根因**：两个 picks 写入路径用了不同字符串约定（短 vs 长），picked_correct 计算函数只认其中之一，碰到对方写入会**静默错判 0**；本次 NULL 是 audit 早于 picks 的"漏算"叠加约定不一致。
- **修复**：canonical 统一为长形式 `home_win/draw/away_win`；`compute_picked_correct` 抽到 pick_parser 共享 + 双形式容错 + 未知值 ERROR；reconcile 补 picks 时同步回算 picked_correct；一次性 SQL 归一历史数据。
- **教训**：**枚举值不能两套并存**——同一字段的取值字典必须文档化、单点定义、所有读写路径统一。读路径碰到未知值必须 ERROR + None，不能默默映射成 0。

### 事故 #3（2026-04-26 复盘统计静默吞 NULL picks）
- **症状**：用户问"昨天战绩"时答不出（13 场被静默过滤）。
- **根因**：`post_match_review.py:compute_single_pick_stats` 用 `WHERE picked_market IS NOT NULL`，把数据缺失等同于"没数据"。
- **修复**：单独统计 `n_missing_pick` 并在 summary 显眼报警；定时 audit 跑 reconciliation 自愈。
- **教训**：**统计 SQL 里的 `WHERE x IS NOT NULL` 是有毒的**——它把"该有值但缺失"和"本不该有值"混为一谈。数据完整性问题必须先报警再统计。

### 三次事故的共同模式（防御要点）
1. **silent except 是慢性毒药**：`except Exception: log.warning(...)` 让 DB 写失败不可见。任何 DB 写入失败必须 `log.error + record_failure`。
2. **多写入路径要么合一、要么互不重叠**：禁用 `INSERT OR REPLACE` 在被多处 UPDATE 的表上；改 `INSERT OR IGNORE + UPDATE` 仅写本路径列。
3. **统计前先校验数据完整性**：任何"按某列分组/过滤"的统计前，先 COUNT 该列 NULL 数；NULL > 0 必须告警，不能直接 `WHERE col IS NOT NULL` 跳过。
4. **source of truth 必须明确**：`report_store.inference` = 用户付费看到的字符串 = 真理。其它表必须能从它反推一致。建立 reconciliation 闸门。
5. **cron 依赖图每改必校验**：`pm2 jlist | grep cron_restart`，画出 reader/writer 依赖。

### pipeline 改动 checklist（每次 PR 必过）
- [ ] 新增/改动 cron job？→ 重画依赖图，确认 reader 在 writer 之后（§15）
- [ ] 改了 `prediction_audit` 写入逻辑？→ 检查 `INSERT OR REPLACE` 是否会抹掉别处写入的列（§17 事故 #2）
- [ ] 加了 `except Exception: log.warning`？→ 改成 `log.error + record_failure`（§17 防御要点 1）
- [ ] 加了 `WHERE x IS NOT NULL` 过滤？→ 同时统计 NULL 数并在 summary 告警（§17 防御要点 3）
- [ ] 加了从 `report_store.inference` 派生的字段？→ 加 reconciliation 闸门，定时回校（§16）
- [ ] 在 ThreadPoolExecutor 里调用 DB？→ 不能引用 `args.*` 局部变量（§14）；DB 写入失败用 ERROR 不用 WARNING

---

## 18. 🚨 picked_direction 字符串约定：长形式 + 双形式容错（2026-04-26 修复）

**事故**（事故 #4）：1 场 WDL 比赛 `picked_correct=NULL`，定位发现 `prediction_audit.picked_direction` 同表两种约定共存：
- `record_picked` 路径（run_tonight_reports.py `_dir_map`）写 **短形式** `home/draw/away`
- `pick_parser.parse_inference` 路径（reconcile/backfill）写 **长形式** `home_win/draw/away_win`

`audit_match.picked_correct` 的 `map_ = {'home':'home_win',...}` 只认短形式，碰到长形式 `map_.get('away_win')=None`，`picked_correct = (None == actual_wdl)` 静默返回 0 → 错判但无告警。同样 `_compute_picked_correct` 在 backfill 里只认长形式，碰到短形式也静默返 0。任意一个 audit/backfill 路径若读到对方写入的方向，都会产出系统性错误。

迁移前 DB 状态（已修复）：
```
wdl / home(42)     draw(5)    away(27)      ← 短形式（record_picked）
wdl / home_win(3)  draw(5)    away_win(5)   ← 长形式（pick_parser）
```

### 铁律
- **canonical 形式 = 长形式**（与 `actual_wdl` 同字典）：
  - WDL：`home_win` / `draw` / `away_win`
  - OU：`over` / `under`
  - AH：`ah_home` / `ah_away`
- 所有写入 `picked_direction` 的路径**必须输出长形式**（`record_picked` 调用方在传 dict 前完成转换）
- 所有读取 `picked_direction` 的 picked_correct 计算路径**必须双形式容错** + **未知值返 None + log.error**（不能默认 0，那是错判）
- 读路径只走 `pick_parser.compute_picked_correct(market, direction, hs, as_, ah_line, ou_line)` 共享函数，禁止本地复制
- 新增 picked_direction 取值时：先在 §18 列出新值，再加代码 + 自测

### 关键代码位置
- `pick_parser.py` `compute_picked_correct()` —— 唯一读路径（双形式容错 + 未知值 ERROR）
- `run_tonight_reports.py` `_dir_map` —— 写路径，identity 长形式
- `review_engine.py` `audit_match` Part B —— 调用 `compute_picked_correct`
- `scripts/normalize_wdl_directions.py` —— 一次性迁移（已跑过 2026-04-26）

### 检查清单（每次涉及 picks 的 PR）
- [ ] 新写法是否输出长形式？grep `picked_direction` 写入点的来源
- [ ] picked_correct 计算是否复用 `pick_parser.compute_picked_correct`？禁止本地副本
- [ ] 新增方向取值是否更新了 §18 列表 + `pick_parser.py` 自测？

### 监控
若 `compute_picked_correct` 打 ERROR `WDL/OU/AH 未知方向`，说明又有新约定混入，立即修复并加自测。

---

## 19. 🚨 target_matches 覆盖不变量：BIG_FIVE 不可静默归零（2026-04-27 修复）

**事故**（事故 #5，详见 §17）：4/24 04:00 UTC fotmob_scheduler 因 API 部分返回，4/25 周五 9 场大赛（含 Man City、Arsenal、Atletico、PSG、Bologna 等）全部漏出研报，且无任何 ERROR / `record_failure`。新空 `target_matches.json` 静默覆盖旧版，run_tonight 一场都没生成。

### 不变量
对任意 BIG_FIVE_LIDS 内的联赛：
- 在赛季中（近 28 天 BIG_FIVE 总场次 ≥ 5），`target_matches.json` 中 BIG_FIVE 不得 < 5 场
- 抓取脚本数量异常时**保留旧 .json**，不允许新空文件覆盖
- run_tonight 启动前必须再校验一次（双闸门），缺口时就地补抓

### 写入路径（双闸门）
1. **fotmob_scheduler.py** 抓完即 sanity check（total + BIG_FIVE 计数 + 联赛分布），失败：
   - `record_failure(step='sanity_check')`
   - 保留旧文件（清理已过期场次后写回）
   - 原子写入：先写 `.new` 再 `os.replace`
2. **run_tonight_reports.py:_validate_and_repair_target_coverage()** 启动前再校验：
   - BIG_FIVE 历史基线（近 28 天）≥ 5 但本次 < 5 → ERROR + `record_failure(step='target_coverage_gap')`
   - 就地调 `fotmob_scheduler.fetch_fotmob_schedule()` 补抓
   - 补抓后场次更多 → 用新结果继续

### 监控
- `ingest_failure_log` 出现 step IN ('sanity_check','target_coverage_gap') 必告警
- 一次性补救：`scripts/repair_weekend_2026_04_25.py --apply`（默认 dry-run）

### 关键代码
- `fotmob_scheduler.py:_has_big_five_in_window()` — 赛季判断
- `fotmob_scheduler.fetch_fotmob_schedule()` — sanity check + 原子写入
- `run_tonight_reports.py:_validate_and_repair_target_coverage()` — 双闸门第二道
- `scripts/check_cron_order.py` — 防 §15 cron 回归

---

## 17 续：复盘 pipeline 事故全录（追加 #5 / #6）

### 事故 #5（2026-04-27 fotmob 静默丢 9 场大赛）
- **症状**：周末 9 场欧洲核心赛事零研报输出，前端"今晚没大场"，已完赛进 dim_match 但 report_store 无对应行。
- **根因**：fotmob API 4/24 抓 4/25 时返回部分数据缺失 BIG_FIVE，scheduler 不校验直接写覆盖；空结果保护只在 0 场时触发，部分缺失（>0 但少）反而落进库。
- **修复**：fotmob_scheduler 抓后 sanity（total + big_five + 历史基线）→ 失败保留旧 .json + record_failure；run_tonight 启动前补一道闸门 + 就地补抓（§19）。
- **教训**：**外部 API 输出必须有"数量基线对比"**，"返回什么就用什么"是慢性失效模式；空结果保护必须扩展到"异常少"。

### 事故 #6（2026-04-27 audit cron 顺序回归）
- **症状**：4/26 夜场 22 场 actual_wdl=NULL，复盘统计漏算。
- **根因**：CLAUDE.md §15 文字承诺要让 audit 排在 batch-sync 之后，但 `ecosystem.config.js` 一直是 `'0 2 * * *'` (02:00 UTC)，早于 batch-sync 03:00 UTC；同样 daily-backtest (02:30) 和 recalibrate (周一 02:45)。
- **修复**：ecosystem.config.js 三个 cron 改为 03:30 / 04:00 / 周一 05:00；新增 `scripts/check_cron_order.py` 静态校验（§15 自检脚本）；`post_match_review.py:reconcile_missing_audit()` 自愈未跑的 audit。
- **教训**：**文档承诺 ≠ 代码落地**。CLAUDE.md 描述的铁律必须有对应的"可执行检查"（自检脚本），否则就是慢性失效。每条铁律 PR 时同步加自动化校验。

### 事故 #7（2026-05-02 BIG_FIVE 渐进性丢失 5 场，§19 闸门未触发）
- **症状**：2026-05-02 5 场 BIG_FIVE（Como/Arsenal/Leverkusen/Metz/Alaves）完全漏出 pipeline：无研报、无赔率、无预测审计。
- **根因 1**：fotmob_scheduler 保留逻辑 `kickoff_time > now_dt`（naive datetime）时区边界 bug。5/1 Thordata 代理过期 → FotMob API 连续 2 天失败 → 保留旧 .json 时每天误删 4 场"刚过 UTC 午夜"的未来场次：34→30→26。
- **根因 2**：run_tonight `_validate_and_repair_target_coverage` 单一阈值 `big_five_count < 5` 太松，26 场含 >5 场 BIG_FIVE → 不触发 → 5 场漏算。
- **修复**：(1) `fotmob_scheduler.py:188` 保留逻辑加 `-6h safety buffer`（宁少删勿多删）；(2) 新增 per-league BIG_FIVE 回归检测（连续两次 .json 比对，跌幅 >50% 记 `league_coverage_regression`）；(3) `run_tonight._validate_and_repair_target_coverage` 升级为 per-league 28 天基线对比，发现联赛完全缺失时触发补抓；(4) `titan_odds_spider.py` 3 处静默 skip 加 `record_failure`；(5) 一次性脚本 `scripts/repair_2026_05_02_big_five.py` 回填 5 场赔率（30 行，5/5 成功）。
- **教训**：**§19 的 BIG_FIVE 不变量必须细化到联赛级别**。整体计数 ≥ 5 不能保证每个联赛都覆盖。外部 API 连续失败时，保留逻辑的 naive datetime 比较可能渐进式丢失场次，每次丢一点不触发硬性阈值——需要"前后两次文件的 diff"或"per-league 基线"才能感知。

---

## 20. 🔐 Admin 接口鉴权约定（2026-04-27 落地）

> **[过渡期现状 - 待迁移至 miaomiaodi.vip]**
> 本节描述 CDK 发卡端点的当前实现，位于 .cc 站点的 backend。
> 按 §0 双站定位长期方向，发卡属于交易类功能应归 .vip。
> 平移完成前继续按本节维护，不要在 .cc 新增同类功能。

### 铁律
- 所有 `POST /api/v1/admin/*` 端点必须携带 `X-Admin-Token` Header
- token 值来自后端 `.env` 的 `ADMIN_SECRET_TOKEN`（与 `JWT_SECRET` 不同的独立密钥）
- 后端校验函数：`cdk_router._verify_admin()` / `review_router._verify_admin()`，统一使用 `secrets.compare_digest`（timing-safe）
- 未配置 `ADMIN_SECRET_TOKEN` 时：拒绝所有请求并返 503（防裸跑）

### 前端调用约定
- **浏览器禁止直连后端 admin 端点**——会暴露 X-Admin-Token
- 必须走 Next.js Route Handler 服务端代理：`frontend/app/api/v1/admin/*/route.ts`
- 代理层校验 `auth()` 拿到的 NextAuth session，确认 `user.name === process.env.SUPER_ADMIN_USER` 后再注入 X-Admin-Token 转发

### 关键代码位置
- `cdk_router.py:_verify_admin()` —— admin 鉴权依赖
- `cdk_router.py:generate_cdks()` —— 批量发卡端点
- `review_router.py:_verify_admin()` —— 复盘触发
- `frontend/app/api/v1/admin/generate-cdks/route.ts` —— 服务端代理
- `admin_audit_log` 表 —— 所有 admin 动作的审计记录（actor / payload / ip / ua / created_at）

### 检查清单（每次新增 admin 接口）
- [ ] 端点路径以 `/api/v1/admin/` 开头
- [ ] 添加 `_: None = Depends(_verify_admin)` 鉴权依赖
- [ ] 写一行 `admin_audit_log` 记录入参摘要 + IP + UA
- [ ] 前端必须走 Route Handler 代理，浏览器 bundle 不含 ADMIN_SECRET_TOKEN
- [ ] curl 验证：错 token → 401，对 token → 200，无 token → 422
- [ ] 服务端代理同时校验 NextAuth session（双层防御）

### 已知 Follow-ups
- ADMIN_SECRET_TOKEN 双值轮替（rotation，零停机）—— 单人运维场景下未上
- admin 身份从 username 软识别升级为 JWT `role='admin'` claim

---

## 21. 🚨 付费内容硬隔离（2026-04-27 上线前）

> **[过渡期现状 - 待迁移至 miaomiaodi.vip]**
> 本节描述 .cc 上的付费内容三档分层（GUEST / REGISTERED / VIP）。
> 按 §0 双站定位长期方向，付费墙、会员体系应归 .vip。
> 平移完成前继续按本节维护，不要在 .cc 扩展付费分层逻辑或新增付费档位。

**业务诉求**：抖音视频引流 → 落地页防同行恶意举报 → "你注册了我给你看，你不注册啥都不给你看"。

### 端点鉴权矩阵

| 端点 | 鉴权依赖 | GUEST 响应 | REGISTERED 响应 | VIP 响应 |
|------|----------|------------|------------------|----------|
| `/api/v1/reports/latest` | `get_optional_user` | 200 + GATED stub（仅 id+队名+队徽+time+league）| 200 + 完整字段，付费场 inference='' | 200 + 全量 |
| `/api/v1/reports/daily_free_id` | `get_current_user` | 401 | 200 | 200 |
| `/api/v1/sync/match_payload/{id}` | `get_current_user` | 401 | 200，付费场 markdown=null | 200 + 全量 |
| `/api/v1/quant/{id}` | `get_current_user` | 401 | 200 | 200 |
| `/api/v1/market/{id}` | `get_current_user` | 401 | 200 | 200 |

### 铁律
- **所有研报相关读端点不得使用纯 `get_optional_user` 而后端不脱敏**——审计时必须确认每个 GUEST 200 的端点都有显式字段过滤（`if user.is_guest: ...stub...`）
- **新增任何返回 `report_store` / `match_payloads` / `prediction_audit` 数据的端点**，默认走 `Depends(get_current_user)`（即 GUEST 401）；除非业务明确要求 GUEST 可见
- **前端不得绕过后端**：detail page 走 SSR `auth()` 检查 + redirect，不走"客户端 fetch + 401 处理"路径（两者都做更稳妥）

### 关键代码位置
- `report_router.py:get_latest_reports()` —— 三档脱敏
- `report_router.py:get_daily_free_id()` —— 强制登录
- `sync_router.py:get_match_payload()` —— 强制登录 + 付费场 markdown 截断
- `api_server.py:get_quant_data` / `get_market_data` —— 强制登录
- `frontend/components/MatchCardGated.tsx` —— GUEST 卡片渲染
- `frontend/app/report/[match_id]/page.tsx` —— SSR `auth()` redirect

### 检查清单（每次新增读端点）
- [ ] 端点是否返回 inference / picks / pred_* / report_markdown / 任何"付费内容"？→ 必须 `Depends(get_current_user)`
- [ ] 若必须 GUEST 200（如首页列表），用 `get_optional_user` + 显式 `if user.is_guest:` 分支返 stub
- [ ] curl 模拟：无 token、registered token、vip token 各跑一遍，确认敏感字段不泄露
- [ ] 前端调用栈：SSR auth 检查 + 客户端容错 401 双重防御

---

## 22. 🔐 开发后门 dev-login 管理（2026-04-27）

### 端点
`GET /api/v1/auth/dev-login?secret=<DEV_LOGIN_SECRET>` —— 持 secret 即可一键登录 `DEV_LOGIN_UID`（默认 11）账户，写 JWT 进 `localStorage` + 跳首页。**绕过微信验证码**。

### 默认状态（线上）
- **路由不挂载**：`ENABLE_DEV_LOGIN!=1` 时，`@app.get` 包在 `if _DEV_LOGIN_ENABLED:` 块内根本不注册到 FastAPI app。访问该路径返 404
- 即使启用，也仅允许 `DEV_LOGIN_ALLOWED_IPS` 中的 IP 访问（默认 `127.0.0.1`）
- secret 比较走 `secrets.compare_digest`（timing-safe）

### 三层防御
1. **路由层**：`ENABLE_DEV_LOGIN=1` 才挂载，否则 404
2. **IP 层**：`rate_limit.client_ip(request)`（CF-Connecting-IP → X-Real-IP → X-Forwarded-For）必须在 `DEV_LOGIN_ALLOWED_IPS` 集合中
3. **Secret 层**：`secrets.compare_digest` timing-safe 比较

### 临时启用流程（应急排障）
```bash
# 1. 编辑 .env
sed -i 's/^ENABLE_DEV_LOGIN=0/ENABLE_DEV_LOGIN=1/' /home/ubuntu/app/backend/.env
# 如需公网 IP 访问，加到白名单：
# vi /home/ubuntu/app/backend/.env  →  DEV_LOGIN_ALLOWED_IPS=127.0.0.1,<你的公网 IP>

# 2. 重启
pm2 restart football-backend --update-env

# 3. 验证（浏览器或 curl）
curl -i "http://127.0.0.1:8000/api/v1/auth/dev-login?secret=$DEV_LOGIN_SECRET"
# 期望 200 + HTML（包含 localStorage.setItem 脚本）

# 4. ❗ 用完立即关闭
sed -i 's/^ENABLE_DEV_LOGIN=1/ENABLE_DEV_LOGIN=0/' /home/ubuntu/app/backend/.env
pm2 restart football-backend --update-env
```

### 铁律
- **排障完成 24h 内必须关闭**（写一行注释记录开启时间，别忘了关）
- 任何 PR 提交前自查：`grep ENABLE_DEV_LOGIN backend/.env` 必须是 `=0`
- secret 至少每季度轮换一次：`openssl rand -hex 16` 生成新值，更新 `.env` 后重启
- `DEV_LOGIN_ALLOWED_IPS` 不得包含 `0.0.0.0` 或 CIDR 通配符

### 关键代码位置
- `api_server.py:471-540` —— 整段 dev-login 实现（含 `if _DEV_LOGIN_ENABLED:` 守卫）
- `rate_limit.client_ip()` —— 真实 IP 提取（穿透 CF + nginx）

### 已知 Follow-ups
- 增加 audit log（每次 dev-login 成功记一条 admin_audit_log）
- 增加自动告警：检测到 `ENABLE_DEV_LOGIN=1` 时通过 SERVERCHAN_KEY 推送提醒

---

## 23. 🚨 archiver 时区铁律 + run_tonight 覆盖告警（2026-04-27 修复）

### 23.1 archiver.py 时区铁律
`report_store.match_time` 永远存 UTC（CLAUDE.md §1）。归档阈值**必须**用 `datetime.now(timezone.utc) - 2h`，与 match_time 同坐标系字符串比较。

**历史 bug**（2026-04-27 修复，原 archiver.py:14-20）：曾用 `datetime.now(CST) - 2h` 作字符串阈值，因 CST=UTC+8，比较时 buggy_thr 比真实 UTC-2h 阈值字符串大约 **6 小时**，导致：
- 比赛在真正开球前 ~6h 被错误标 `is_archived=1`
- 下游 run_post_match_reviews 因 `is_archived=1` 拉到未结束比赛
- LLM 收到 `home_score=NULL + 空 shots` 的 prompt → 写入"AI 分析中..."占位
- 表现为 ingest_failure_log step=`reconcile_parse_failed` 的诡异错误

**铁律**：
- archiver.py 内已加防御 `if threshold_dt > now_utc_naive: log.error + return 0`
- 任何对 `match_time` 字段做时间比较的脚本都必须 `datetime.now(timezone.utc).replace(tzinfo=None)`
- 不得 import `CST = timezone(timedelta(hours=8))` 用于 match_time 比较

### 23.2 run_tonight 二次闸门告警（CLAUDE.md §19 收尾）
`run_tonight_reports.py:_validate_and_repair_target_coverage()` 在补抓也失败时（fetch_fotmob_schedule 不带回更多场次或抛异常），**必须**通过 `notify_utils.notify()` 推 Server 酱告警。

**告警内容必须包含**：
- 日期窗口（window_dates）
- 实抓 BIG_FIVE 数 + 28 天基线
- 异常原因（exception 字符串或"未带来更多比赛"）

**已落地** run_tonight_reports.py:1063-1078。无 SERVERCHAN_KEY 时降级到 log.error 不阻断。

### 23.3 检查清单（每次新增/改动 cron job）
- [ ] 是否读 `report_store.match_time`？→ 阈值用 UTC，禁止 CST
- [ ] 是否读 `dim_match.Date`？→ 同上
- [ ] 是否触发 LLM 调用？→ 失败必须走 record_failure + notify
- [ ] 新写入路径是否影响 `picked_correct` / `actual_*`？→ 跑 scripts/check_cron_order.py 确认依赖

---

## 24. 🚨 silver_match_odds 时间戳语义（2026-05-04 增补）

**事故背景**：2026-05-04 误判事件——用户用 `WHERE inserted_at >= '2026-05-01' AND inserted_at < '2026-05-02'` 查 5/1 三场赔率，返回 0，误以为 pipeline 漏抓。实际数据齐全（每场 6 行），只是 `inserted_at = 2026-04-30 06:20`（首次入库时间，比 5/1 早一天），用错了字段。耗时排查整条 pipeline 与 pm2 才定位是查询误判。

### 表的两列时间戳，含义不同，**绝对不可互换**

| 列 | 默认值 | UPSERT 行为 | 语义 |
|----|-------|------------|------|
| `inserted_at` | `DEFAULT CURRENT_TIMESTAMP` | **不更新**（仅首次 INSERT 时锁定） | 赔率第一次出现在系统的时间，通常赛前 1-3 天 |
| `scraped_at` | 无默认值，每次显式写 | **每次 UPSERT 刷新**（`ON CONFLICT DO UPDATE SET ... scraped_at=excluded.scraped_at`） | 赔率最近一次被刷新的时间 |

代码出处：`silver_builder.py:493-498` 的 ON CONFLICT 子句明确只更新业务字段 + scraped_at，不动 inserted_at。

### 查询语义对照表

| 想问的问题 | 用的字段 | 维度 |
|----------|---------|------|
| "某日新出现的赔率"（哪些比赛今天开始追踪）| `inserted_at` | 场次发现维度 |
| "某日刷新过的赔率"（今天 cron 跑了什么）| `scraped_at` | 运维维度 |
| "某日开球的比赛赔率"（业务侧关心的当天赛事）| 通过 `match_id` JOIN `dim_match.Date` 或表内 `match_date` | 业务维度 |

### 铁律

- **禁止用 `inserted_at` 做"业务日期"过滤**——它是技术字段，不是 kickoff date
- 排查"是否漏抓"时正确顺序：
  1. 先 `SELECT COUNT(*) FROM silver_match_odds WHERE match_id = ?` 看记录是否存在
  2. 再看 `inserted_at`/`scraped_at` 各自时戳判断"何时入库 vs 何时最后刷新"
  3. 不可只看一个时间字段就下结论
- 三种维度不可替代。误用会导致"看起来缺数据但实际数据齐全"的误判（2026-05-04 调查取证）

### 检查清单（每次新增 silver_* 时间字段查询时）
- [ ] 想表达的是"业务日期"还是"运维日期"？
- [ ] 选对字段了吗（inserted_at / scraped_at / match_date）？
- [ ] 排查缺数据前，是否先按 match_id 直查过？

---

## 25. 🚨 match_odds_data.json schema 不变量（2026-05-05 事故）

**事故**：`repair_2026_05_02_big_five.py` 把 `fetch_single_match_odds()` 的裸返回值直接 append 进 JSON（缺外层包装），产生 10 条损坏记录。`run_tonight_reports.py` 崩溃 3 次，`titan_odds_spider.py` merge 也崩溃，赔率停更近 24 小时。

### 记录结构（强制）

每条记录**必须**包含以下字段：

```json
{
  "fotmob_id": "<string>",      // FotMob match ID，必须是 str
  "titan_id":  "<string>",      // NowGoal ID（可为空字符串）
  "match_name": "<string>",     // "Home vs Away"（可为空字符串）
  "odds": {                     // 嵌套赔率 dict（必须是 dict）
    "provider": "Bet365",
    "asian_handicap": { "initial": {...}, "latest": {...} },
    "over_under":     { "initial": {...}, "latest": {...} },
    "european_1x2":   { "initial": {...}, "latest": {...} }
  }
}
```

**禁止**直接 append `fetch_single_match_odds()` 的返回值——它是裸 `odds_data`，缺少外层包装。

### 写入方（3 处，改动前必查）

| 文件 | 行为 |
|------|------|
| `titan_odds_spider.py:375,458-459` | 批量写入 + merge（merge 时过滤损坏记录） |
| `odds_fetcher.py:101-106` | 增量写入 |
| `final_lock.py:80-84` | T-30 刷新（须用 `str(mid)` + 补全 `titan_id`/`match_name`） |

### 读取方（7 处，全部已加防御守卫）

所有读取 `match_odds_data.json` 的字典推导/集合推导必须带 `if "fotmob_id" in o` 守卫，跳过时打 `log.warning`。

### 铁律
- `fotmob_id` 统一用 `str` 类型（禁止 `int(mid)`）
- 新增写入方时，必须构造完整信封结构，禁止 append 裸 odds_data
- 新增读取方时，必须带 `if "fotmob_id" in o` 守卫



---

## 26. 🚨 PM2 在线变更纪律（2026-05-13 事故追加）

**事故**：2026-05-12 新增 `scripts/shadow_cup_wdl_v5.py` 和 `eval_shadow_cup_wdl_v5.py`，
脚本 docstring 里写了 cron 时间，但**未写入 `ecosystem.config.js`**。用户感知"PM 崩了"，
实际是新脚本根本没注册成 PM2 cron job，安静地不运行。同日 5/11 晚改动 `.env` 后触发 pm2 操作，
扰动了 5/12 的 cron 触发，全天 pipeline 静默（所有 log 文件 0 字节）。

**同日发现的固有缺陷**：`fotmob_scheduler.py` `DATES_AHEAD=3` 在周中运行时扫描窗口卡在赛事荒漠期，
无法覆盖 5/16-5/18 周末赛程。修复方案：新增独立 `job-weekend-prefetch` 每天 03:00 UTC 补扫 7 天。

### 铁律

- **禁止**在线 `pm2 start <脚本>` 当 cron job 用，而不同步写入 `ecosystem.config.js`——重启服务器会丢失
- **新增 cron 脚本**必须在 docstring 顶部写明 cron 时间（`# Cron: HH:MM UTC`），同步写入 ecosystem.config.js
- **改了 `.env` 内容**后，必须用 `pm2 startOrRestart ecosystem.config.js --only <name> --update-env`，
  普通 `pm2 restart` **不重读** `.env`（§6 铁律）
- **改了 `ecosystem.config.js`** 后，必须 `pm2 delete <name> && pm2 start ecosystem.config.js --only <name>`
- **每次改动后**：`pm2 save`（持久化）+ `python3 scripts/check_cron_order.py`（校验依赖顺序）

### 新增 cron 脚本流程（不可省步骤）

```bash
# 1. 写脚本（在 docstring 顶部注明：# Cron: HH:MM UTC = HH:MM CST）
# 2. 加入 ecosystem.config.js（注意 §15 依赖顺序，cron 时刻不能早于依赖的 writer）
# 3. 注册到 PM2
pm2 delete job-<name> 2>/dev/null || true   # 删旧实例（若存在）
pm2 start ecosystem.config.js --only job-<name>
# 4. 持久化
pm2 save
# 5. 校验依赖顺序
python3 /home/ubuntu/app/backend/scripts/check_cron_order.py
# 6. 手动触发一次测试（可选）
pm2 trigger job-<name> restart
```

### 删除 cron 脚本流程

```bash
# 1. 在 ecosystem.config.js 中删除或注释该 app
pm2 delete job-<name>
pm2 save
```

### 紧急回滚

```bash
pm2 resurrect   # 从 ~/.pm2/dump.pm2 恢复上次 pm2 save 的快照
```

### 检查清单（每次新增/改动 cron）

- [ ] 新脚本 docstring 写了 `# Cron: HH:MM UTC = HH:MM CST`？
- [ ] ecosystem.config.js 有对应 app，包含完整字段（name/script/cron_restart/autorestart/error_file）？
- [ ] cron 时刻符合 §15 依赖顺序（reader 在 writer 之后）？
- [ ] `pm2 save` 持久化了？
- [ ] `check_cron_order.py` 返回 exit 0？
- [ ] 手动触发 + 看日志确认脚本能正常跑通？
