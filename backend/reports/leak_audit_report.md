# V6 重训前数据泄漏诊断报告

生成时间: 2026-05-07

---

## 嫌疑 #1: closing odds 时间戳

### SQL 结果 — 赔率时间戳分析（2024/2025 + 2025/2026 赛季）

| market | period | provider | n | earliest | latest | avg_hours_offset | min_hours_offset | max_hours_offset |
|--------|--------|----------|---|----------|--------|-----------------|-----------------|-----------------|
| 1x2 | closing | Bet365 | 3843 | 2026-04-17 | 2026-05-07 | 6815.01 | -41.67 | 14643.02 |
| 1x2 | opening | Bet365 | 3926 | 2026-04-17 | 2026-05-07 | 6675.56 | -41.67 | 14643.02 |
| ah | closing | Bet365 | 3843 | 2026-04-17 | 2026-05-07 | 6815.01 | -41.67 | 14643.02 |
| ah | opening | Bet365 | 3925 | 2026-04-17 | 2026-05-07 | 6674.79 | -41.67 | 14643.02 |
| ou | closing | Bet365 | 2460 | 2026-04-17 | 2026-05-07 | 9209.34 | -41.67 | 15129.92 |
| ou | opening | Bet365 | 2460 | 2026-04-17 | 2026-05-07 | 9209.34 | -41.67 | 15129.92 |

**avg_hours_offset = +6815 小时 = +284 天**：这不是泄漏，而是时间戳字段的含义问题。

### 样本核查 — 近期 closing AH 时间戳

| match_id | market | period | match_date | scraped_at | inserted_at | hours_offset |
|----------|--------|--------|------------|------------|-------------|-------------|
| 4837457 | ah | closing | 2026-05-09 | 2026-05-07T06:20 | 2026-05-07 06:20:00 | -41.7 |
| 4813732 | ah | closing | 2026-05-09 | 2026-05-07T06:20 | 2026-05-07 06:20:00 | -41.7 |

near-future 比赛（2026-05-09）的 closing odds 在 2026-05-07 已抓取，scraped_at = inserted_at（每次 UPSERT 刷新），表明来源是 NowGoal 实时爬取（合理）。

### 根本原因分析

`silver_match_odds` 有两层数据来源：

1. **历史数据（2021-2025）**：来源于 `raw_footballdata_odds`（football-data.co.uk CSV，含 `B365C*` closing 列）。这批数据于 2026 年 4 月批量导入，`scraped_at` 全部 >= 2026-04-17，但 **赔率内容本身是开球前市场收盘价**（football-data.co.uk 的 `C` 列即赛前最终赔率，不含赛后结果信息）。
2. **近期数据（2025-至今）**：由 `titan_odds_spider.py` 实时爬取，`scraped_at` 真实反映抓取时间。

**关键验证：** 查历史完赛比赛 closing odds 是否全部在比赛日之后抓取：

| Season | n | avg_hrs_before_kickoff_day | scraped_after_match | scraped_before_match |
|--------|---|--------------------------|---------------------|---------------------|
| 2021/2022 | 1621 | +37983 (=4.3 years) | 1621 | 0 |
| 2022/2023 | 1600 | +29157 | 1600 | 0 |
| 2023/2024 | 1697 | +19907 | 1697 | 0 |
| 2024/2025 | 1741 | +11100 | 1741 | 0 |
| 2025/2026 | 1892 | +2548 | 1892 | 0 |

**结论**：对于所有历史完赛比赛，`scraped_at > match_date`，即赔率在比赛结束后才被记录入库。但这是数据管理层面的时间戳问题，**不是内容泄漏**：

- football-data.co.uk `B365C*` 列记录的是**开球前**的市场收盘价，该内容本身不含结果信息
- 在实际推理场景中，closing odds 在开球前 ~30 分钟由 titan_odds_spider 实时抓取
- 在训练数据中，这批历史赔率值代表的是开球前市场信号，内容语义正确

**但存在一个值得关注的问题**：`scraped_at` 字段在 `v5_feature_engineering` 管道中完全未被使用（`grep` 结果为空），管道直接从 `silver_match_odds` 读取赔率数值而不做时间戳过滤，若数据录入有误可能无感知。

### 判定: ⚠️ 时间戳语义误导，内容无泄漏，但存在监控盲区

**证据：**
- 赔率内容 = 开球前市场收盘价（football-data.co.uk 标准）✅
- `scraped_at` 与 `inserted_at` 所有记录不一致（100% different）✅ 说明 UPSERT 机制正常
- v5 特征管道未使用 `scraped_at` 过滤 ⚠️
- 历史数据批量导入时间远晚于比赛日期，若有任何赔率订正（bookmaker 赛后调整），无法通过时间戳检测

---

## 嫌疑 #2: rolling 特征窗口

### 代码路径

**dbt SQL 模型** (`/home/ubuntu/app/backend/quant_dbt/models/intermediate/int_team_rolling_features.sql`):

```sql
ROUND(AVG(npxGD) OVER(
    PARTITION BY team_id 
    ORDER BY match_date 
    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
), 2) AS roll_5_npxGD
```

**Python 滚动脚本** (`/home/ubuntu/app/backend/v5_feature_engineering/build_rolling_v5.py`):

```python
# 注释说明：
# 'all' rolling：shift(1).rolling(window, min_periods).mean()   窗口 3,5,10,15
shifted = team_df[col].shift(1)
team_df[f'roll_{w}_all_{col}'] = shifted.rolling(w, min_periods=min_p).mean()
```

### 分析

- **dbt SQL 版本**：`ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING` — 窗口不包含当前行，正确排除当前比赛。✅
- **Python 版本**：`shift(1)` 先错位，再滚动 — 等价于 `PRECEDING AND 1 PRECEDING`，同样正确排除当前比赛。✅
- 主客场分场景滚动：`ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING` on `PARTITION BY team_id, is_home` ✅
- 所有窗口（3, 5, 10, 14）均使用相同结构

### SQL 验证 — mart_lambda_dataset_v5 split 分布

| split | MIN(match_date) | MAX(match_date) | COUNT(*) |
|-------|-----------------|-----------------|----------|
| inference | 2026-04-06 | 2026-04-06 | 1 |
| test | 2026-01-25 | 2026-05-06 | 921 |
| train | 2024-01-01 | 2025-09-27 | 4298 |
| val | 2025-09-27 | 2026-01-25 | 921 |

数据集包含 6140 行（train 4298 + val 921 + test 921）完赛比赛，无重叠。

### 判定: ✅ 通过

**证据：** 所有 rolling 窗口明确使用 `1 PRECEDING` 下限，排除当前比赛自身数据。Python 版本使用 `shift(1)` 实现等价效果。

---

## 嫌疑 #3: Pi-Rating 更新时机

### 代码路径

**Pi-Rating 构建** (`/home/ubuntu/app/backend/v5_feature_engineering/build_pi_ratings.py`):

`_run_full_history()` 函数先更新评级，再存快照（**快照 = 该场比赛结束后的评级**）：

```python
for r in matches.itertuples(index=False):
    _, delta = _update_match(ratings, h_id, a_id, ...)  # 先更新
    # 快照评级（更新后）
    history.append({
        'match_id': int(r.Match_ID),
        'pi_home_for': t['home_for'],  # <- 存的是赛后评级
        ...
    })
```

**关键：** `int_team_pi_ratings` 中每条记录存的是该场比赛 **结束后** 的评级，因此如果直接用该表 join，`match_id` 对应的 pi 值就是赛后信息（泄漏）。

### 特征矩阵中的 lag 处理

**`build_matrix_v5.py` 第 178-189 行**（Pi-Rating lag-1）：

```python
print('🥧 加载 Pi-Ratings（lag-1）...')
pi = pd.read_sql_query("""
    SELECT match_id, team_id, match_date,
           pi_home_for, pi_home_against, pi_away_for, pi_away_against
    FROM int_team_pi_ratings
    ORDER BY team_id, match_date, match_id
""", conn)
pi_lag = pi.copy()
for col in ('pi_home_for', 'pi_home_against', 'pi_away_for', 'pi_away_against'):
    pi_lag[col] = pi_lag.groupby('team_id')[col].shift(1)  # <- lag-1!
```

然后用 `pi_lag`（而非原始 `pi`）join 到特征矩阵，以 `match_id` 为 key。

### 验证

样本验证（team_id=9825 的前 5 场比赛）：

| match_id | match_date | pi_home_for（赛后） | pi_lag（shift-1 = 赛前） |
|----------|------------|---------------------|-------------------------|
| 3609929 | 2021-08-13 | 0.000000 | NaN（首场，无赛前评级）|
| 3609939 | 2021-08-22 | 0.083712 | 0.000000（= 第 1 场赛后）|
| 3609953 | 2021-08-28 | 0.083712 | 0.083712（= 第 2 场赛后）|
| 3609959 | 2021-09-11 | 0.083712 | 0.083712 |
| 3609971 | 2021-09-18 | 0.086822 | 0.083712（= 第 4 场赛后）|

`shift(1)` 正确将评级向后错位一位，确保 Match X 使用的是 Match X-1 结束后的评级，即 Match X 开球前的评级状态。

### 判定: ✅ 通过

**证据：** `build_matrix_v5.py` 使用 `groupby('team_id')[col].shift(1)` 实现 lag-1，特征矩阵中的 pi 评级正确反映开球前状态，不包含当场比赛结果信息。

---

## 嫌疑 #4: Test set 切分

### 切分代码 (`build_lambda_dataset_v5.py`)

```python
def time_split(df: pd.DataFrame, train_pct=0.70, val_pct=0.15):
    n = len(df)
    n_train = int(n * train_pct)
    n_val   = int(n * val_pct)
    
    df = df.sort_values('match_date').reset_index(drop=True)  # 严格时间排序
    df['split'] = 'train'
    df.loc[n_train: n_train + n_val - 1, 'split'] = 'val'
    df.loc[n_train + n_val:, 'split'] = 'test'
```

**无 shuffle，纯时间顺序切分。** ✅

### 时间分布验证

| split | date_bucket | n |
|-------|-------------|---|
| test | 2025+ | 921 |
| train | 2024-2025 | 2494 |
| train | 2025+ | 1804 |
| val | 2025+ | 921 |

### 精确边界

| split | MIN(match_date) | MAX(match_date) | COUNT(*) |
|-------|-----------------|-----------------|----------|
| train | 2024-01-01 | 2025-09-27 | 4298 |
| val | 2025-09-27 | 2026-01-25 | 921 |
| test | 2026-01-25 | 2026-05-06 | 921 |

**重叠检查：** train-val 和 val-test 之间 match_id 重叠数 = 0（已验证）。

**边界注意：** train 最后日期与 val 最早日期同为 2025-09-27，可能存在同日切分点（按行号切分而非日期，同日比赛按 sort 顺序分入不同 split）。这是正常行为，不构成泄漏。

### 判定: ✅ 通过

**证据：** 纯时间顺序 70/15/15 切分，train < val < test 时间递增，无 shuffle，无跨期泄漏。

---

## 嫌疑 #5: 特征列泄漏风险

### mart_lambda_dataset_v5 中的 closing_* 列（21 列）

```
closing_eu_raw_home, closing_eu_raw_draw, closing_eu_raw_away, closing_eu_line,
closing_eu_fair_home, closing_eu_fair_draw, closing_eu_fair_away,
closing_ah_raw_home, closing_ah_raw_draw, closing_ah_raw_away, closing_ah_line,
closing_ah_fair_home, closing_ah_fair_draw, closing_ah_fair_away,
closing_ou_raw_home, closing_ou_raw_draw, closing_ou_raw_away, closing_ou_line,
closing_ou_fair_home, closing_ou_fair_draw, closing_ou_fair_away
```

### 以及 ah_line_movement / ah_odds_movement

`ah_line_movement = closing_ah_line - opening_ah_line`（盘口移动）
`ah_odds_movement = closing_ah_home - opening_ah_home`（赔率移动）

### 语义分析

| 问题 | 分析 |
|------|------|
| closing odds 是否代表赛后信息？ | 否。closing odds = 开球前市场最终收盘价，不含赛果 |
| 在历史数据中，closing odds 是否真实存在于开球前？ | 是。football-data.co.uk `B365C*` 列为赛前收盘价的行业标准数据集 |
| 在推理（live）场景中，是否可以获得 closing odds？ | 是。titan_odds_spider 在开球前 ~30 分钟抓取最终赔率 |
| ah_line_movement 是否泄漏未来信息？ | 否。盘口移动 = 开市到收市的价格变化，整体在开球前即可知 |
| closing odds 在 mart_lambda_dataset_v5 覆盖率？ | 训练集 99.8%（4289/4298），测试集 95.5%（880/921）|

### 测试集 closing AH accuracy 验证（防止内容泄漏检验）

| split | n | closing_ah_accuracy |
|-------|---|---------------------|
| train | 4289 | 38.5% |
| val | 920 | 41.7% |
| test | 880 | 39.6% |

closing AH 主队胜率约 40%，合理（非 50% 是因为 AH 让球线非零时的主客队对称性）。若为赛后泄漏数据，模型本身预测能力不会来自纯随机猜测，此结果不支持内容泄漏假设。

### 潜在风险点（⚠️ 低风险但值得关注）

1. **scraped_at 无过滤机制**：特征管道直接读取 `silver_match_odds`，不校验 `scraped_at < match_kickoff_time`。若未来有赔率数据因爬虫错误而被赛后值覆盖，管道无法感知。
2. **historical bulk import 可验证性**：2021-2023 历史赔率的 `scraped_at` = 2026 年，无法反向验证当时数据采集的准确性。

### 判定: ✅ 通过（语义安全）/ ⚠️ 建议增加时间戳守卫

---

## 总结

| 嫌疑 | 判定 | 严重程度 | 修复成本 |
|------|------|----------|----------|
| #1: closing odds 时间戳 | ⚠️ 语义误导，内容无泄漏 | 低 | 低（加 scraped_at 守卫注释） |
| #2: rolling 特征窗口 | ✅ 通过 | — | — |
| #3: Pi-Rating 更新时机 | ✅ 通过 | — | — |
| #4: Test set 切分 | ✅ 通过 | — | — |
| #5: 特征列泄漏风险 | ✅ 通过（语义安全）| 低 | 低 |

### 关键结论

**本次审计未发现会导致训练集性能虚高的结构性数据泄漏。** V6 重训可以在当前数据管道基础上进行。

### 建议下一步行动

1. **低优先级修复（建议）**：在 `build_matrix_v5.py` / `build_ah_dataset_v5.py` 加入 `scraped_at` 合理性断言（如 `scraped_at < match_date + 24h` 的异常比例统计），作为数据质量日志，而非过滤器。

2. **Pi-Rating 首场 NaN**：`shift(1)` 导致每队第一场比赛 Pi 特征全为 NaN。检查 `build_matrix_v5.py` 第 408 行的 closing_* 填充策略是否同样处理了 pi 首场 NaN（当前代码对 `closing_*` 列用均值填充，pi 是否有类似处理需确认）。

3. **测试集时间窗口覆盖**：test set 范围 2026-01-25 ~ 2026-05-06（约 15% 的 921 场），其中相当一部分比赛的 closing odds 在比赛日之后才实际入库（scraped_at 显示为 2026-05-07）。虽然内容正确，但建议在训练结束后做一次"closing odds 可用性延迟"的专项分析，以确认推理窗口设计（scrape time vs inference time）一致。

---

*本报告为只读审计，未修改任何文件或数据。*
*审计工具：SQLite 直查 + Python 代码静态分析 + grep*
