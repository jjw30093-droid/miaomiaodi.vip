-- quant_dbt/models/staging/stg_team_stats.sql

WITH source AS (
    SELECT rowid, * FROM {{ source('main', 'fact_team_match_stats') }}
    WHERE Period = 'All'
),

deduplicated AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY "Match_ID", "Team_ID" 
            ORDER BY rowid DESC -- 假设最后插入的记录更准确，或者是任意挑选一个
        ) AS rn
    FROM source
),

renamed AS (
    SELECT
        CAST("Match_ID" AS INTEGER) AS match_id,
        CAST("Team_ID" AS INTEGER) AS team_id,
        "Period",
        CAST(COALESCE("Goals", 0) AS REAL) AS goals,
        CAST(COALESCE("expected_goals", 0) AS REAL) AS expected_goals,
        CAST(COALESCE("expected_goals_non_penalty", 0) AS REAL) AS expected_goals_non_penalty,
        CAST(COALESCE("expected_goals_on_target", 0) AS REAL) AS expected_goals_on_target,
        CAST(COALESCE("total_shots", 0) AS REAL) AS total_shots,
        CAST(COALESCE("ShotsOnTarget", 0) AS REAL) AS shots_on_target,
        CAST(COALESCE("shots_inside_box", 0) AS REAL) AS shots_inside_box,
        CAST(COALESCE("shots_outside_box", 0) AS REAL) AS shots_outside_box,
        CAST(COALESCE("big_chance", 0) AS REAL) AS big_chance,
        CAST(COALESCE("big_chance_missed_title", 0) AS REAL) AS big_chance_missed,
        CAST(COALESCE("BallPossesion", 0) AS REAL) AS ball_possession,
        CAST(COALESCE("passes", 0) AS REAL) AS passes,
        CAST(COALESCE("accurate_passes", 0) AS REAL) AS accurate_passes,
        CAST(COALESCE("opposition_half_passes", 0) AS REAL) AS opposition_half_passes,
        CAST(COALESCE("own_half_passes", 0) AS REAL) AS own_half_passes,
        CAST(COALESCE("touches_opp_box", 0) AS REAL) AS touches_opp_box,
        CAST(COALESCE("long_balls_accurate", 0) AS REAL) AS long_balls_accurate,
        CAST(COALESCE("interceptions", 0) AS REAL) AS interceptions,
        CAST(COALESCE("fouls", 0) AS REAL) AS fouls,
        CAST(COALESCE("expected_goals_open_play", 0) AS REAL) AS xg_open_play,
        CAST(COALESCE("expected_goals_set_play", 0) AS REAL) AS xg_set_play,
        CAST(COALESCE("matchstats.headers.tackles", 0) AS REAL) AS tackles,
        CAST(COALESCE("blocked_shots", 0) AS REAL) AS blocked_shots,
        CAST(COALESCE("keeper_saves", 0) AS REAL) AS keeper_saves
    FROM deduplicated
    WHERE rn = 1
)

SELECT * FROM renamed
