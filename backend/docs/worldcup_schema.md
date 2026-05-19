# worldcup.db — 世界杯数据缓存层 Schema 文档

> **创建日期**：2026-05-18  
> **归属**：miaomiaodi.cc（数据 host 站），通过内部 HTTP API 供 miaomiaodi.vip 调用  
> **物理路径**：`/home/ubuntu/app/backend/worldcup.db`  
> **初始化脚本**：`backend/scripts/init_worldcup_db.py`

---

## 架构原则

| 原则 | 说明 |
|------|------|
| **物理隔离** | 独立 SQLite 文件，不复用 `football_uk.db` |
| **业务解耦** | `wc_*` 表与现有业务表**零外键关联**，方便未来拆独立微服务 |
| **软关联** | 所有跨表关联通过 `sportmonks_id` 字段软关联，无 `FOREIGN KEY` 约束 |
| **原始数据保留** | `raw_json` 存 Sportmonks 完整 payload，保证数据可溯源 |
| **幂等去重** | `data_hash`（sha256）用于同步时判断是否需要更新 |
| **双站定位** | 不含站点特定字段（`visible_on_cc` 等），付费/可见性在 API 层判断 |

---

## 通用字段（每张表都有）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 内部自增主键 |
| `sportmonks_id` | INTEGER | Sportmonks 实体 ID；维度表 UNIQUE，事实表允许重复 |
| `raw_json` | TEXT | 完整 Sportmonks 原始 payload（JSON 字符串）|
| `data_hash` | TEXT | `raw_json` 的 sha256，同步时去重判断 |
| `synced_at` | TIMESTAMP | 本条记录最近同步时间（UTC）|
| `sync_source` | TEXT | `'manual'` / `'cron'` / `'backfill'` |
| `api_version` | TEXT | Sportmonks API 版本号，如 `'v3'` |
| `created_at` | TIMESTAMP | 首次写入时间（UTC）|
| `updated_at` | TIMESTAMP | 最近更新时间（UTC，建议同步时手动刷新）|

> **例外**：`wc_sync_log` 是纯内部审计表，`sportmonks_id` / `data_hash` 无实体意义，允许 NULL。

---

## 表清单

### 1. wc_seasons — 赛季（届次）

**用途**：存储 6 届世界杯的顶层信息（2006/2010/2014/2018/2022/2026）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `year` | INTEGER NOT NULL | 举办年份，如 `2026` |
| `name` | TEXT NOT NULL | 赛事全名，如 `'FIFA World Cup 2026'` |
| `host_country` | TEXT | 东道主，如 `'USA/Canada/Mexico'` |
| `total_teams` | INTEGER | 参赛队数，如 `48`（2026 扩军）|
| `winner_team_sportmonks_id` | INTEGER | 冠军队 ID，赛前为 NULL |

**典型查询**：
```sql
-- 所有届次
SELECT year, name, host_country, total_teams FROM wc_seasons ORDER BY year;

-- 通过 sportmonks_id 关联赛程
SELECT * FROM wc_fixtures WHERE season_sportmonks_id = (
    SELECT sportmonks_id FROM wc_seasons WHERE year = 2026
);
```

**索引**：`idx_wc_seasons_sportmonks_id` (UNIQUE)

---

### 2. wc_stages — 赛制阶段

**用途**：存储每届赛制的各个阶段（小组赛、16强、8强、半决赛、决赛等）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `season_sportmonks_id` | INTEGER NOT NULL | 所属赛季（软关联 wc_seasons）|
| `name` | TEXT NOT NULL | 阶段名称，如 `'Group Stage'`, `'Round of 16'` |
| `type` | TEXT | `'group'` 或 `'knockout'` |
| `sort_order` | INTEGER | 排序序号 |

**典型查询**：
```sql
SELECT s.year, st.name, st.type
FROM wc_stages st
JOIN wc_seasons s ON s.sportmonks_id = st.season_sportmonks_id
WHERE s.year = 2026
ORDER BY st.sort_order;
```

**索引**：`idx_wc_stages_sportmonks_id` (UNIQUE)

---

### 3. wc_groups — 小组

**用途**：存储小组赛阶段各小组（A-H 或 A-L）。淘汰赛阶段无小组。

| 字段 | 类型 | 说明 |
|------|------|------|
| `season_sportmonks_id` | INTEGER NOT NULL | 所属赛季 |
| `stage_sportmonks_id` | INTEGER NOT NULL | 所属阶段（软关联 wc_stages）|
| `name` | TEXT NOT NULL | 小组名称，如 `'Group A'` |

**典型查询**：
```sql
-- 2026 年所有小组
SELECT g.name FROM wc_groups g
JOIN wc_seasons s ON s.sportmonks_id = g.season_sportmonks_id
WHERE s.year = 2026 ORDER BY g.name;
```

**索引**：`idx_wc_groups_sportmonks_id` (UNIQUE)

---

### 4. wc_teams — 参赛队伍

**用途**：跨届去重存储国家队信息。同一国家队在多届世界杯中共享一条记录（按 sportmonks_id）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | TEXT NOT NULL | 队伍全名，如 `'Brazil'` |
| `short_name` | TEXT | 缩写，如 `'BRA'` |
| `country_id` | INTEGER | Sportmonks 国家 ID |
| `logo_path` | TEXT | 队徽 URL 路径 |
| `founded` | INTEGER | 成立年份 |

**典型查询**：
```sql
-- 查 2026 年某场比赛的两队信息
SELECT ht.name as home, at.name as away
FROM wc_fixtures f
JOIN wc_teams ht ON ht.sportmonks_id = f.home_team_sportmonks_id
JOIN wc_teams at ON at.sportmonks_id = f.away_team_sportmonks_id
WHERE f.sportmonks_id = 123456;
```

**索引**：`idx_wc_teams_sportmonks_id` (UNIQUE)

---

### 5. wc_venues — 比赛场馆

**用途**：存储比赛场地信息。2026 年美加墨世界杯涉及 16 个场馆。

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | TEXT NOT NULL | 场馆名称 |
| `city` | TEXT | 城市 |
| `country` | TEXT | 国家 |
| `capacity` | INTEGER | 容量 |
| `latitude` | REAL | 纬度（地图显示用）|
| `longitude` | REAL | 经度 |

**索引**：`idx_wc_venues_sportmonks_id` (UNIQUE)

---

### 6. wc_fixtures — 比赛主表 ⭐ 最核心

**用途**：存储所有比赛的核心信息，包括 2026 年淘汰赛阶段的**占位赛程**（对阵未确定时）。

#### 占位赛程（2026 特有）

2026 年小组赛结束前，16 强赛程已知但对阵尚未确定，使用占位字段：

```
is_placeholder = 1
home_team_sportmonks_id = NULL
away_team_sportmonks_id = NULL
placeholder_home = 'Winner Group A'
placeholder_away = 'Runner-up Group B'
```

小组赛结束后，同步时更新为实际队伍 ID，`is_placeholder` 改为 0。

#### 历史赛事标记

2006/2010/2014 三届历史赛事用 `is_historical = 1` 标记，同步策略为"一次写入，不再更新"。

| 字段 | 类型 | 说明 |
|------|------|------|
| `season_sportmonks_id` | INTEGER NOT NULL | 所属赛季 |
| `stage_sportmonks_id` | INTEGER | 所属阶段 |
| `group_sportmonks_id` | INTEGER | 所属小组（淘汰赛为 NULL）|
| `venue_sportmonks_id` | INTEGER | 场馆 |
| `home_team_sportmonks_id` | INTEGER | 主队（占位时为 NULL）|
| `away_team_sportmonks_id` | INTEGER | 客队（占位时为 NULL）|
| `placeholder_home` | TEXT | 主队占位描述，如 `'Winner Group A'` |
| `placeholder_away` | TEXT | 客队占位描述 |
| `is_placeholder` | BOOLEAN DEFAULT 0 | 1 = 对阵未确定 |
| `starting_at` | TIMESTAMP | UTC 开球时间 |
| `status` | TEXT | Sportmonks 状态字符串，如 `'FT'`, `'NS'`, `'LIVE'` |
| `round_id` | INTEGER | 轮次 ID |
| `leg_num` | INTEGER DEFAULT 1 | 第几回合（小组赛=1）|
| `home_score` | INTEGER | 主队进球（冗余，细分在 wc_scores）|
| `away_score` | INTEGER | 客队进球 |
| `has_events` | BOOLEAN DEFAULT 0 | 是否已同步事件数据 |
| `has_lineups` | BOOLEAN DEFAULT 0 | 是否已同步阵容数据 |
| `has_statistics` | BOOLEAN DEFAULT 0 | 是否已同步统计数据 |
| `odds_markets_count` | INTEGER DEFAULT 0 | 已拉取赔率市场数 |
| `odds_last_checked_at` | TIMESTAMP | 最近查赔率时间 |
| `is_historical` | BOOLEAN DEFAULT 0 | 1 = 历史赛事，永不再同步 |
| `referee_sportmonks_id` | INTEGER | 主裁判 ID |

**典型查询**：
```sql
-- 2026 年今日比赛
SELECT f.starting_at, ht.name as home, at.name as away, f.status
FROM wc_fixtures f
JOIN wc_teams ht ON ht.sportmonks_id = f.home_team_sportmonks_id
JOIN wc_teams at ON at.sportmonks_id = f.away_team_sportmonks_id
JOIN wc_seasons s ON s.sportmonks_id = f.season_sportmonks_id
WHERE s.year = 2026
  AND date(f.starting_at) = date('now')
ORDER BY f.starting_at;

-- 需要同步深度数据的比赛（已完赛但缺详情）
SELECT sportmonks_id FROM wc_fixtures
WHERE status = 'FT'
  AND (has_events = 0 OR has_lineups = 0 OR has_statistics = 0)
  AND is_historical = 0;

-- 待确定对阵的占位赛程
SELECT starting_at, placeholder_home, placeholder_away, stage_sportmonks_id
FROM wc_fixtures WHERE is_placeholder = 1 ORDER BY starting_at;
```

**索引**：
- `idx_wc_fixtures_sportmonks_id`
- `idx_wc_fixtures_season_starting` (season_sportmonks_id, starting_at)
- `idx_wc_fixtures_status`

---

### 7. wc_scores — 比分明细

**用途**：存储多种比分类型（半场/全场/加时/点球）。`wc_fixtures` 冗余存 `home_score/away_score` 供快速展示，本表存细分。

| 字段 | 类型 | 说明 |
|------|------|------|
| `fixture_sportmonks_id` | INTEGER NOT NULL | 所属比赛 |
| `type_id` | INTEGER | Sportmonks 比分类型 ID |
| `description` | TEXT | `'CURRENT'` / `'FT'` / `'HT'` / `'ET'` / `'PEN'` |
| `score_home` | INTEGER | 主队该阶段比分 |
| `score_away` | INTEGER | 客队该阶段比分 |

**典型查询**：
```sql
SELECT description, score_home, score_away
FROM wc_scores
WHERE fixture_sportmonks_id = 123456
ORDER BY description;
```

**索引**：`idx_wc_scores_fixture`, `idx_wc_scores_sportmonks_id`

---

### 8. wc_events — 比赛事件

**用途**：存储进球、红黄牌、换人、VAR 判罚等事件流水。每场比赛可能有 20-50 条记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| `fixture_sportmonks_id` | INTEGER NOT NULL | 所属比赛 |
| `player_sportmonks_id` | INTEGER | 相关球员 ID |
| `player_name` | TEXT | 球员姓名（冗余存，避免 JOIN）|
| `team_sportmonks_id` | INTEGER | 所属球队 |
| `type` | TEXT | `'goal'` / `'yellowcard'` / `'redcard'` / `'substitution'` / `'var'` |
| `minute` | INTEGER | 事件发生分钟数 |
| `extra_minute` | INTEGER | 伤停补时分钟（如第 90+3 分钟）|
| `info` | TEXT | 附加描述，如 `'header'`, `'penalty'` |

**典型查询**：
```sql
-- 某场比赛进球时间轴
SELECT minute, extra_minute, player_name, team_sportmonks_id, type, info
FROM wc_events
WHERE fixture_sportmonks_id = 123456 AND type = 'goal'
ORDER BY minute, extra_minute;
```

**索引**：`idx_wc_events_fixture`, `idx_wc_events_sportmonks_id`

---

### 9. wc_statistics — 技术统计

**用途**：存储比赛技术统计（射门/控球率/传球成功率等），支持球队级和球员级两种粒度。

| 字段 | 类型 | 说明 |
|------|------|------|
| `fixture_sportmonks_id` | INTEGER NOT NULL | 所属比赛 |
| `team_sportmonks_id` | INTEGER | 球队 ID（球员统计时为 NULL）|
| `player_sportmonks_id` | INTEGER | 球员 ID（球队统计时为 NULL）|
| `type` | TEXT NOT NULL | 统计类型，如 `'shots_on_target'`, `'possession'` |
| `value` | TEXT NOT NULL | 值（存字符串，调用方按需转数值）|

> `value` 用 TEXT 类型存储的原因：Sportmonks 统计值类型不统一（`"54%"`, `"12"`, `"1.23"` 都有可能），统一用字符串存储，查询时转换。

**典型查询**：
```sql
-- 某场比赛两队控球率对比
SELECT t.name, s.value as possession
FROM wc_statistics s
JOIN wc_teams t ON t.sportmonks_id = s.team_sportmonks_id
WHERE s.fixture_sportmonks_id = 123456
  AND s.type = 'possession'
  AND s.player_sportmonks_id IS NULL;
```

**索引**：`idx_wc_statistics_fixture`, `idx_wc_statistics_sportmonks_id`

---

### 10. wc_lineups — 出场阵容

**用途**：存储每场比赛的首发和替补球员信息。每场比赛通常有 22-30 条记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| `fixture_sportmonks_id` | INTEGER NOT NULL | 所属比赛 |
| `team_sportmonks_id` | INTEGER NOT NULL | 所属球队 |
| `player_sportmonks_id` | INTEGER NOT NULL | 球员 ID |
| `player_name` | TEXT | 球员姓名（冗余存）|
| `jersey_number` | INTEGER | 号码 |
| `position` | TEXT | `'goalkeeper'` / `'defender'` / `'midfielder'` / `'attacker'` |
| `is_starter` | BOOLEAN DEFAULT 1 | 0 = 替补 |
| `formation_position` | TEXT | 阵型中的位置标识，如 `'CB'`, `'LW'` |

**典型查询**：
```sql
-- 某队首发阵容
SELECT player_name, jersey_number, position, formation_position
FROM wc_lineups
WHERE fixture_sportmonks_id = 123456
  AND team_sportmonks_id = 789
  AND is_starter = 1
ORDER BY jersey_number;
```

**索引**：`idx_wc_lineups_fixture`, `idx_wc_lineups_sportmonks_id`

---

### 11. wc_odds — 赛前赔率快照（Step 3）

**用途**：存储 Sportmonks pre-match odds。同步策略不硬编码年份，只处理 `wc_fixtures.raw_json` 中 `has_odds = true` 的比赛；当前主要覆盖 2018/2022。

| 字段 | 类型 | 说明 |
|------|------|------|
| `fixture_sportmonks_id` | INTEGER NOT NULL | 所属比赛 |
| `market_id` | INTEGER | 赔率市场 ID |
| `bookmaker_id` | INTEGER | Bookmaker ID |
| `label` | TEXT | 展示标签 |
| `original_label` | TEXT | 原始标签 |
| `name` | TEXT | 赔率名称 |
| `market_description` | TEXT | 市场描述 |
| `value` | TEXT | 赔率选项值 |
| `probability` | TEXT | Sportmonks 给出的概率文本 |
| `dp3` | TEXT | 十进制赔率 |
| `fractional` | TEXT | 分数赔率 |
| `american` | TEXT | 美式赔率 |
| `total` | TEXT | 大小球盘口 |
| `handicap` | TEXT | 让球盘口 |
| `stopped` | BOOLEAN | 是否停止交易 |
| `winning` | BOOLEAN | 是否命中（赛后可能有值）|
| `latest_bookmaker_update` | TIMESTAMP | bookmaker 最近更新时间 |
| `participants` | TEXT | 参与方 JSON 文本 |
| `sort_order` | INTEGER | 排序字段 |

**典型查询**：
```sql
-- 某场比赛的 1X2 相关赔率
SELECT market_id, bookmaker_id, label, name, dp3, probability
FROM wc_odds
WHERE fixture_sportmonks_id = 18452325
ORDER BY market_id, bookmaker_id, sort_order;
```

**索引**：`idx_wc_odds_fixture`, `idx_wc_odds_sportmonks_id`, `idx_wc_odds_market_bookmaker`

---

### 12. wc_standings — 小组排名

**用途**：存储每届世界杯小组赛阶段各队的积分榜状态。非实时，随 API 同步更新。

| 字段 | 类型 | 说明 |
|------|------|------|
| `season_sportmonks_id` | INTEGER NOT NULL | 所属赛季 |
| `stage_sportmonks_id` | INTEGER | 所属阶段 |
| `group_sportmonks_id` | INTEGER | 所属小组 |
| `team_sportmonks_id` | INTEGER NOT NULL | 队伍 |
| `position` | INTEGER | 小组排名（1-4）|
| `played` | INTEGER DEFAULT 0 | 已踢场数 |
| `won` | INTEGER DEFAULT 0 | 胜 |
| `drawn` | INTEGER DEFAULT 0 | 平 |
| `lost` | INTEGER DEFAULT 0 | 负 |
| `goals_for` | INTEGER DEFAULT 0 | 进球 |
| `goals_against` | INTEGER DEFAULT 0 | 失球 |
| `points` | INTEGER DEFAULT 0 | 积分 |
| `form` | TEXT | 近期状态，如 `'WWDLL'` |

**典型查询**：
```sql
-- 2026 年 A 组最新排名
SELECT t.name, st.position, st.played, st.won, st.drawn, st.lost,
       st.goals_for, st.goals_against, st.points
FROM wc_standings st
JOIN wc_teams t ON t.sportmonks_id = st.team_sportmonks_id
JOIN wc_seasons s ON s.sportmonks_id = st.season_sportmonks_id
JOIN wc_groups g ON g.sportmonks_id = st.group_sportmonks_id
WHERE s.year = 2026 AND g.name = 'Group A'
ORDER BY st.position;
```

**索引**：`idx_wc_standings_season_group`

---

### 13. wc_sync_log — 同步审计日志

**用途**：记录每次 Sportmonks API 同步操作的结果，用于排查失败、监控同步健康状态。

| 字段 | 类型 | 说明 |
|------|------|------|
| `endpoint` | TEXT NOT NULL | API endpoint，如 `'/v3/football/fixtures?filters=seasonId:xx'` |
| `http_status` | INTEGER | HTTP 状态码，如 `200`, `429`, `500` |
| `rows_inserted` | INTEGER DEFAULT 0 | 本次新插入行数 |
| `rows_updated` | INTEGER DEFAULT 0 | 本次更新行数 |
| `rows_unchanged` | INTEGER DEFAULT 0 | 哈希未变，跳过的行数 |
| `error_msg` | TEXT | 错误信息（成功时为 NULL）|
| `retry_count` | INTEGER DEFAULT 0 | 重试次数 |
| `started_at` | TIMESTAMP NOT NULL | 同步开始时间（UTC）|
| `finished_at` | TIMESTAMP | 同步结束时间 |
| `duration_ms` | INTEGER | 耗时毫秒 |
| `season_sportmonks_id` | INTEGER | 本次同步的赛季（批量同步时可 NULL）|
| `layer` | TEXT | `'basic'` / `'deep'` / `'odds'`（同步粒度）|

**典型查询**：
```sql
-- 最近 20 次同步记录
SELECT endpoint, http_status, rows_inserted, rows_updated, duration_ms,
       error_msg, started_at
FROM wc_sync_log
ORDER BY started_at DESC
LIMIT 20;

-- 有失败的同步
SELECT endpoint, error_msg, started_at, retry_count
FROM wc_sync_log
WHERE error_msg IS NOT NULL OR http_status != 200
ORDER BY started_at DESC;

-- 各 endpoint 最近同步时间
SELECT endpoint, MAX(started_at) as last_sync, 
       SUM(rows_inserted) as total_inserted
FROM wc_sync_log
WHERE error_msg IS NULL
GROUP BY endpoint;
```

**索引**：`idx_wc_sync_log_started_at`, `idx_wc_sync_log_endpoint`

---

## 索引汇总

| 索引名 | 表 | 字段 | 类型 | 用途 |
|--------|-----|------|------|------|
| `idx_wc_seasons_sportmonks_id` | wc_seasons | sportmonks_id | UNIQUE | 主查键 |
| `idx_wc_stages_sportmonks_id` | wc_stages | sportmonks_id | UNIQUE | 主查键 |
| `idx_wc_groups_sportmonks_id` | wc_groups | sportmonks_id | UNIQUE | 主查键 |
| `idx_wc_teams_sportmonks_id` | wc_teams | sportmonks_id | UNIQUE | 主查键 |
| `idx_wc_venues_sportmonks_id` | wc_venues | sportmonks_id | UNIQUE | 主查键 |
| `idx_wc_fixtures_sportmonks_id` | wc_fixtures | sportmonks_id | INDEX | 主查键 |
| `idx_wc_scores_sportmonks_id` | wc_scores | sportmonks_id | INDEX | 主查键 |
| `idx_wc_events_sportmonks_id` | wc_events | sportmonks_id | INDEX | 主查键 |
| `idx_wc_statistics_sportmonks_id` | wc_statistics | sportmonks_id | INDEX | 主查键 |
| `idx_wc_lineups_sportmonks_id` | wc_lineups | sportmonks_id | INDEX | 主查键 |
| `idx_wc_fixtures_season_starting` | wc_fixtures | (season_sportmonks_id, starting_at) | INDEX | 按赛季+时间查比赛 |
| `idx_wc_fixtures_status` | wc_fixtures | status | INDEX | 按状态过滤（FT/NS/LIVE）|
| `idx_wc_scores_fixture` | wc_scores | fixture_sportmonks_id | INDEX | 按比赛查比分 |
| `idx_wc_events_fixture` | wc_events | fixture_sportmonks_id | INDEX | 按比赛查事件 |
| `idx_wc_statistics_fixture` | wc_statistics | fixture_sportmonks_id | INDEX | 按比赛查统计 |
| `idx_wc_lineups_fixture` | wc_lineups | fixture_sportmonks_id | INDEX | 按比赛查阵容 |
| `idx_wc_odds_fixture` | wc_odds | fixture_sportmonks_id | INDEX | 按比赛查赔率 |
| `idx_wc_odds_sportmonks_id` | wc_odds | sportmonks_id | INDEX | 赔率主查键 |
| `idx_wc_odds_market_bookmaker` | wc_odds | (market_id, bookmaker_id) | INDEX | 按市场和公司查赔率 |
| `idx_wc_standings_season_group` | wc_standings | (season_sportmonks_id, group_sportmonks_id) | INDEX | 小组排名查询 |
| `idx_wc_sync_log_started_at` | wc_sync_log | started_at DESC | INDEX | 最近同步记录 |
| `idx_wc_sync_log_endpoint` | wc_sync_log | endpoint | INDEX | 按 endpoint 查历史 |

---

## 架构决策记录（ADR）

### ADR-1：维度表 sportmonks_id 加 UNIQUE，事实表不加

事实表（wc_events, wc_statistics, wc_lineups）对应 Sportmonks 的子实体，同一场比赛会有多条记录，`sportmonks_id` 不唯一。`wc_scores` 的 `sportmonks_id` 也允许 NULL（部分比分类型无独立 ID）。

### ADR-2：wc_statistics.value 用 TEXT 存储

Sportmonks 统计 API 返回的值格式混杂（百分比字符串、整数、浮点数），统一用 TEXT 存储，调用方按 `type` 字段判断格式并转换，避免 SQLite 隐式类型转换导致精度问题。

### ADR-3：wc_fixtures 冗余存 home_score/away_score

`wc_scores` 表存细分比分（HT/FT/ET/PEN），但快速展示时频繁 JOIN 性能差。`wc_fixtures` 冗余存 `home_score/away_score` 表示全场最终比分（FT），同步时需双写。

### ADR-4：wc_sync_log 的通用字段允许 NULL

`wc_sync_log` 是内部运维审计表，不对应任何 Sportmonks 实体，`sportmonks_id` 和 `data_hash` 无语义意义，设为 NULLABLE。`raw_json` 可选存储完整 API 响应（调试用，可能很大，正常运营时可以不存）。

### ADR-5：不设 is_placeholder 为 GENERATED COLUMN

SQLite GENERATED COLUMN 在老版本有兼容性问题。`is_placeholder` 由写入方负责维护，同步时若 `home_team_sportmonks_id` 非 NULL 则同步改为 0。

### ADR-6：history 标记设在 wc_fixtures 而非 wc_seasons

2022 年世界杯与 2026 年同步策略不同（2022 历史赛事只需一次性回填，2026 实时同步）。标记在 fixture 级别比在 season 级别更灵活，支持混合策略（如 2022 决赛赔率需要更新时可单独解除历史标记）。

### ADR-7：历史阵容缺 player_id 时使用负数哨兵值

Step 1 的 `wc_lineups.player_sportmonks_id` 是 `NOT NULL`，但 2006 等较早赛事的 Sportmonks lineup payload 偶尔缺少 `player_id`。Step 3 不重建既有表；同步脚本保留完整 `raw_json`，并用 `-abs(lineup.id)` 作为可追踪哨兵值写入 `player_sportmonks_id`，避免丢弃历史阵容行。

---

## 使用方式

```bash
# 首次初始化
cd /home/ubuntu/app/backend
venv/bin/python scripts/init_worldcup_db.py

# 检查建表结果
sqlite3 worldcup.db ".tables"

# 重建（开发环境清数据用）
venv/bin/python scripts/init_worldcup_db.py --drop-existing

# 查 schema
sqlite3 worldcup.db ".schema wc_fixtures"

# 查所有索引
sqlite3 worldcup.db "SELECT name, tbl_name FROM sqlite_master WHERE type='index' ORDER BY tbl_name, name;"

# Step 2 basic 层迁移 / 同步
venv/bin/python scripts/migrate_worldcup_step2.py
venv/bin/python scripts/sync_worldcup_sportmonks.py --all --layer basic --sleep 500

# Step 3 deep + odds 层迁移 / 同步
venv/bin/python scripts/migrate_worldcup_step3.py
venv/bin/python scripts/sync_worldcup_sportmonks.py --all --layer deep --sleep 300
venv/bin/python scripts/sync_worldcup_sportmonks.py --all --layer odds --sleep 300
```

---

## 下一步

- **Step 4**：后端 API endpoint（`/api/worldcup/fixtures` 等）
- **Step 5**：前端展示页（`/worldcup/*`）
- **Step 6**：预测模型集成
