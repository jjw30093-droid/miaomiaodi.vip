# 🏟️ Football Data Lake - 核心数据维度总览 (2026 版)

本指南旨在为 AI 分析师提供本地数据湖（Data Lake）的完整画像，涵盖 SQLite 结构化数据、JSON 实时流数据及研报存储维度。

---

## 1. 核心特征库 (SQLite: 25-26英超全数据.db)

数据湖的灵魂在于 **Opta 高阶滚动战力指标** 与 **球员影响力建模**。

### 📊 A. 球队滚动战力 (Table: `int_team_rolling_features`)
存储每支球队最近 5 场比赛的移动平均表现，是研报生成的底层核心。
- **npxGD (无点球预期净胜球)**: 移除点球干扰后的真实攻防统治力（核心指标）。
- **PPDA (高位压迫强度)**: 数值越小代表前场反抢越激进。
- **Field Tilt (场地倾斜度)**: 前场 30 米区域的控球占比，衡量压迫效果。
- **Golden Zone Ratio (黄金区占比)**: 射门发生在禁区内“高价值区域”的比例。
- **Goals Prevented (门将受压度)**: 门将及其防线额外封堵出的失球数。

### 🩺 B. 球员影响力雷达 (Table: `int_player_influence`)
用于评估关键球员缺阵对球队 xG 的百分比削减。
- **xG/xA Share**: 球员在场时包揽全队预期进球/助攻的百分比份额。
- **Chances Created Share**: 球员创造机会占全队的权重。
- **Recoveries Share**: 球员在防守端的球权夺回贡献。

### 🤖 C. 研报存储与状态 (Table: `report_store`)
- **match_id**: 全局唯一 FotMob ID。
- **home_prob / away_prob**: AI 模型判定的主客胜率。
- **pipeline_status**: `PRE_MATCH_READY` (初稿), `ANALYSIS_UPDATED` (深度), `FINAL_REPORT_READY` (终稿)。

---

## 2. 调度总线 (JSON: schedule & odds)

用于衔接外部爬虫与本地特征库的“桥接层”。

### 📅 赛程底稿 (`schedule/target_matches.json`)
- **match_id**: 核心键值。
- **league**: 联赛名称（用于触发不同的 Agent 策略，如英超触发情报采集）。
- **kickoff_time**: 判断研报更新版本的时间锚点。

### 📈 盘口实时流 (`odds/match_odds_data.json`)
- **Asian Handicap (亚盘)**: `line` (让球数), `over_or_home` (贴水)。
- **Over/Under (大小球)**: 进球数界限与水位。
- **Movement (水位走势)**: 记录初盘(`initial`)与即时盘(`latest`)的对比，用于捕捉机构博弈意图。

---

## 3. 实体映射引擎 (Mapping)

- **team_mapping.json**: 解决实体命名漂移（如 `PSG` -> `Paris Saint-Germain`）。
- **Logic**: API Server 采用 4 级降级匹配机制（字典 -> 精确 -> 包含 -> 模糊）。

---

## 📜 数据湖健康度检查 (2026-04-04 状态)
- **特征数据量**: `int_team_rolling_features` (4126 条), `int_player_influence` (86449 条)。
- **实时研报状态**: `report_store` 已累计 87 场深度报告。
- **覆盖范围**: 当前数据库对 **25-26 英超** 具备 100% 颗粒度覆盖。非英超联赛目前正逐步接入中。

---
*编撰人：喵弟量化实验室数据中心*
