{{ config(
    materialized='incremental',
    unique_key="match_id || '-' || team_id"
) }}

WITH shotmap_with_team AS (
    -- 使用已去重并初步清洗的 staging 层数据
    SELECT
        s.match_id,
        s.player_id,
        p.team_id,
        s.Minute,
        s.X_Coord,
        s.Y_Coord,
        s.xg,
        s.xgot,
        s.Situation,
        s.Outcome
    FROM {{ ref('stg_shotmap') }} s
    JOIN {{ ref('stg_player_stats') }} p
        ON s.match_id = p.match_id
        AND s.player_id = p.player_id
    {% if is_incremental() %}
    WHERE s.match_id NOT IN (SELECT match_id FROM {{ this }})
    {% endif %}
),

shot_zone_flags AS (
    SELECT
        match_id,
        team_id,
        xg,
        xgot,
        CASE WHEN X_Coord >= 85 AND Y_Coord BETWEEN 35 AND 65 THEN 1 ELSE 0 END AS is_golden_zone_shot,
        CASE WHEN X_Coord < 83 THEN 1 ELSE 0 END AS is_outside_box_shot,
        CASE WHEN xg >= 0.3 THEN 1 ELSE 0 END AS is_high_value_shot
    FROM shotmap_with_team
)

SELECT
    match_id,
    team_id,
    COUNT(*) AS map_total_shots,
    SUM(is_golden_zone_shot) AS golden_zone_shots,
    ROUND((SUM(is_golden_zone_shot) * 1.0) / NULLIF(COUNT(*), 0), 4) AS golden_zone_shot_ratio,
    SUM(is_outside_box_shot) AS outside_box_shots,
    ROUND((SUM(is_outside_box_shot) * 1.0) / NULLIF(COUNT(*), 0), 4) AS outside_box_shot_ratio,
    ROUND(AVG(xg), 4) AS avg_xG_per_shot,
    SUM(is_high_value_shot) AS high_value_shots_count,
    ROUND(SUM(xgot - xg), 4) AS team_shot_execution_added
FROM shot_zone_flags
GROUP BY match_id, team_id