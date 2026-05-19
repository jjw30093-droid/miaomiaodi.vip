{{ config(
    materialized='incremental',
    unique_key="match_id || '-' || team_id"
) }}

WITH team_stats AS (
    SELECT * FROM {{ ref('stg_team_stats') }}
    {% if is_incremental() %}
    WHERE match_id NOT IN (SELECT match_id FROM {{ this }})
    {% endif %}
)

SELECT
    m.match_id,
    m.match_date,
    m.Season,
    t1.team_id,
    CASE WHEN t1.team_id = m.Home_Team_ID THEN 1 ELSE 0 END AS is_home,
    t2.team_id AS opponent_id,

    -- [基础进球与预期数据]
    t1.goals AS goals_for,
    t2.goals AS goals_conceded,
    t1.expected_goals AS xG_for,
    t2.expected_goals AS xGA_against,
    (t1.expected_goals - t2.expected_goals) AS xGD,
    t1.expected_goals_non_penalty AS npxG_for,
    t2.expected_goals_non_penalty AS npxGA_against,
    (t1.expected_goals_non_penalty - t2.expected_goals_non_penalty) AS npxGD,

    t1.xg_open_play AS xG_open_play_for,
    t1.xg_set_play AS xG_set_play_for,

    -- [机会创造与射门质量]
    t1.big_chance AS big_chances_created,
    t1.big_chance_missed AS big_chances_missed,
    t2.big_chance AS big_chances_conceded,
    (t1.expected_goals_on_target - t1.expected_goals) AS shot_quality_added,

    -- [射门维度]
    t1.total_shots AS total_shots_for,
    t1.shots_on_target AS shots_on_target_for,
    t1.shots_inside_box AS shots_inside_box_for,
    t1.shots_outside_box AS shots_outside_box_for,
    ROUND(t1.shots_inside_box / NULLIF(t1.total_shots, 0), 2) AS box_shot_ratio,

    -- [控球率及差值]
    t1.ball_possession AS possession_pct,
    (t1.ball_possession - t2.ball_possession) AS possession_diff,

    -- [场地倾斜度 Field Tilt: 前场传球占比]
    ROUND(t1.opposition_half_passes /
          NULLIF((t1.opposition_half_passes + t2.opposition_half_passes), 0), 2) AS field_tilt,

    t1.touches_opp_box AS touches_in_opp_box,
    ROUND(t1.long_balls_accurate / NULLIF(t1.passes, 0), 2) AS long_ball_ratio,

    -- [防守压迫指数]
    (t2.expected_goals_on_target - t2.goals) AS team_goals_prevented,
    ROUND(t2.own_half_passes /
          NULLIF((
              t1.tackles +
              t1.interceptions +
              t1.fouls
          ), 0), 2) AS proxy_ppda,

    -- [Phase B 新增: 门将扑救 + 封堵射门]
    CAST(COALESCE(t1.keeper_saves, 0) AS REAL) AS keeper_saves,
    CAST(COALESCE(t1.blocked_shots, 0) AS REAL) AS blocked_shots,

    -- [微观维度缝合] 射门地图高阶威慑力
    CAST(COALESCE(sz_t1.golden_zone_shot_ratio, 0) AS REAL) AS golden_zone_shot_ratio_for,
    CAST(COALESCE(sz_t1.outside_box_shot_ratio, 0) AS REAL) AS outside_box_shot_ratio_for,
    CAST(COALESCE(sz_t1.avg_xG_per_shot, 0) AS REAL) AS avg_xG_per_shot_for,
    CAST(COALESCE(sz_t2.golden_zone_shot_ratio, 0) AS REAL) AS golden_zone_shot_ratio_conceded,
    CAST(COALESCE(sz_t2.outside_box_shot_ratio, 0) AS REAL) AS outside_box_shot_ratio_conceded

FROM team_stats t1
JOIN team_stats t2
    ON t1.match_id = t2.match_id
    AND t1.team_id != t2.team_id
JOIN {{ ref('stg_match_info') }} m
    ON t1.match_id = m.match_id
LEFT JOIN {{ ref('int_team_shot_zones') }} sz_t1
    ON t1.match_id = sz_t1.match_id
    AND t1.team_id = sz_t1.team_id
LEFT JOIN {{ ref('int_team_shot_zones') }} sz_t2
    ON t2.match_id = sz_t2.match_id
    AND t2.team_id = sz_t2.team_id