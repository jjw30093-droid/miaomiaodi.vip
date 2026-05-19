-- models/intermediate/int_team_rolling_zones.sql
-- 5 场滚动的金区 / 盒外射门质量指标
-- 数据源：int_team_shot_zones（静态每场聚合） + int_team_match_flattened（提供 match_date 和 is_home）
{{ config(materialized='table') }}

WITH zones_with_date AS (
    SELECT
        z.match_id,
        z.team_id,
        f.match_date,
        f.is_home,
        f.opponent_id,
        z.golden_zone_shot_ratio,
        z.outside_box_shot_ratio,
        z.avg_xG_per_shot,
        z.high_value_shots_count,
        z.team_shot_execution_added
    FROM {{ ref('int_team_shot_zones') }} z
    JOIN {{ ref('int_team_match_flattened') }} f
      ON z.match_id = f.match_id AND z.team_id = f.team_id
)

SELECT
    match_id,
    match_date,
    team_id,
    is_home,
    opponent_id,

    ROUND(AVG(golden_zone_shot_ratio)
        OVER(PARTITION BY team_id ORDER BY match_date
             ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 4) AS roll_5_golden_zone_ratio_zones,

    ROUND(AVG(outside_box_shot_ratio)
        OVER(PARTITION BY team_id ORDER BY match_date
             ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 4) AS roll_5_outside_box_ratio_zones,

    ROUND(AVG(avg_xG_per_shot)
        OVER(PARTITION BY team_id ORDER BY match_date
             ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 4) AS roll_5_avg_xg_per_shot,

    ROUND(AVG(high_value_shots_count)
        OVER(PARTITION BY team_id ORDER BY match_date
             ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2) AS roll_5_high_value_shots,

    ROUND(AVG(team_shot_execution_added)
        OVER(PARTITION BY team_id ORDER BY match_date
             ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 4) AS roll_5_shot_execution_added

FROM zones_with_date
