-- models/intermediate/int_team_rolling_features.sql
{{ config(materialized='table') }}

WITH match_history AS (
    SELECT * FROM {{ ref('int_team_match_flattened') }}
)

SELECT
    match_id,
    match_date,
    team_id,
    is_home,
    opponent_id,

    -------------------------------------------------------------------------
    -- 核心维度一：无点球真实实力与机会创造 (Rolling 5)
    -------------------------------------------------------------------------
    ROUND(AVG(npxGD) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2) AS roll_5_npxGD,
    ROUND(AVG(xGD) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2) AS roll_5_xGD,
    ROUND(AVG(big_chances_created) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 1) AS roll_5_big_chances_created,

    -------------------------------------------------------------------------
    -- 核心维度二：战术压迫与场地倾斜 (Rolling 5)
    -------------------------------------------------------------------------
    ROUND(AVG(proxy_ppda) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2) AS roll_5_ppda,
    ROUND(AVG(field_tilt) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2) AS roll_5_field_tilt,
    ROUND(AVG(possession_diff) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 1) AS roll_5_poss_diff,
    ROUND(AVG(long_ball_ratio) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2) AS roll_5_long_ball_ratio,

    -------------------------------------------------------------------------
    -- 核心维度三：穿透力、终结效率与门将兜底 (Rolling 5)
    -------------------------------------------------------------------------
    ROUND(AVG(box_shot_ratio) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2) AS roll_5_box_shot_ratio,
    ROUND(AVG(shot_quality_added) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2) AS roll_5_shot_quality_added,
    ROUND(AVG(team_goals_prevented) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2) AS roll_5_team_goals_prevented,

    -------------------------------------------------------------------------
    -- 🚨 核心修复：微观维度四：射门地图高阶威慑力 (Rolling 5)
    -------------------------------------------------------------------------
    -- 近5场本方黄金开火区射门占比
    ROUND(AVG(golden_zone_shot_ratio_for) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 4) AS roll_5_golden_zone_ratio,
    -- 近5场本方远射依赖度
    ROUND(AVG(outside_box_shot_ratio_for) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 4) AS roll_5_outside_box_ratio,
    -- 近5场被对手在黄金区射门占比
    ROUND(AVG(golden_zone_shot_ratio_conceded) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 4) AS roll_5_golden_zone_conceded,

    -------------------------------------------------------------------------
    -- 主客场极端推演：相同主客场条件下的表现 (Rolling 5 Home/Away)
    -------------------------------------------------------------------------
    ROUND(AVG(npxG_for) OVER(PARTITION BY team_id, is_home ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2) AS roll_5_split_npxG_for,
    ROUND(AVG(npxGA_against) OVER(PARTITION BY team_id, is_home ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2) AS roll_5_split_npxGA_against,

    -------------------------------------------------------------------------
    -- Phase 1.1: xG 拆分来源（开球 vs 定位球）(Rolling 5)
    -------------------------------------------------------------------------
    ROUND(AVG(xG_open_play_for) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2) AS roll_5_open_play_xg_for,
    ROUND(AVG(xG_set_play_for)  OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2) AS roll_5_set_play_xg_for,

    -------------------------------------------------------------------------
    -- Phase B: 最优窗口列（从 window_winners.json 扫描结果）
    -------------------------------------------------------------------------
    -- npxGD: best=14
    ROUND(AVG(npxGD) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING), 2) AS roll_14_npxGD,
    -- field_tilt: best=3
    ROUND(AVG(field_tilt) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 2) AS roll_3_field_tilt,
    -- box_shot_ratio: best=3
    ROUND(AVG(box_shot_ratio) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 2) AS roll_3_box_shot_ratio,
    -- big_chances_created: best=3
    ROUND(AVG(big_chances_created) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 1) AS roll_3_big_chances_created,
    -- open_play_xg_for: best=3
    ROUND(AVG(xG_open_play_for) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 2) AS roll_3_open_play_xg_for,
    -- blocked_shots: new feature, best=14
    ROUND(AVG(blocked_shots) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING), 1) AS roll_14_blocked_shots,
    -- keeper_saves: new feature, best=5
    ROUND(AVG(keeper_saves) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 1) AS roll_5_keeper_saves

FROM match_history