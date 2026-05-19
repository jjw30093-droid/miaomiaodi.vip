{{ config(
    materialized='incremental',
    unique_key="match_id || '-' || player_id"
) }}

WITH safe_player_stats AS (
    -- 从 staging 层获取已去重并初步清洗的数据
    SELECT
        match_id,
        team_id,
        player_id,
        minutes_played,
        is_goalkeeper,
        xg_xa,
        chances_created,
        defensive_actions,
        recoveries,
        xgot_faced,
        goals_conceded
    FROM {{ ref('stg_player_stats') }}
    {% if is_incremental() %}
    WHERE match_id NOT IN (SELECT match_id FROM {{ this }})
    {% endif %}
),

team_match_totals AS (
    -- 计算单场比赛全队总和作为分母
    SELECT
        match_id,
        team_id,
        SUM(xg_xa) AS team_total_xg_xa,
        SUM(chances_created) AS team_total_chances,
        SUM(defensive_actions) AS team_total_def_actions,
        SUM(recoveries) AS team_total_recoveries
    FROM safe_player_stats
    GROUP BY match_id, team_id
)

SELECT
    p.match_id,
    p.team_id,
    p.player_id,
    p.minutes_played,
    p.is_goalkeeper,

    -------------------------------------------------------------------------
    -- [进攻核心依赖度] Offensive Influence Share
    -------------------------------------------------------------------------
    p.xg_xa AS player_xg_xa,
    ROUND(p.xg_xa / NULLIF(t.team_total_xg_xa, 0), 4) AS xg_xa_share,

    p.chances_created AS player_chances_created,
    ROUND(p.chances_created / NULLIF(t.team_total_chances, 0), 4) AS chances_created_share,

    -------------------------------------------------------------------------
    -- [防守中枢依赖度] Defensive Influence Share
    -------------------------------------------------------------------------
    p.recoveries AS player_recoveries,
    ROUND(p.recoveries / NULLIF(t.team_total_recoveries, 0), 4) AS recoveries_share,

    p.defensive_actions AS player_defensive_actions,
    ROUND(p.defensive_actions / NULLIF(t.team_total_def_actions, 0), 4) AS def_actions_share,

    -------------------------------------------------------------------------
    -- [门将神勇度] Goalkeeper Value Added
    -------------------------------------------------------------------------
    CASE
        WHEN p.is_goalkeeper = 1 THEN (p.xgot_faced - p.goals_conceded)
        ELSE NULL
    END AS goals_prevented

FROM safe_player_stats p
LEFT JOIN team_match_totals t
    ON p.match_id = t.match_id
    AND p.team_id = t.team_id