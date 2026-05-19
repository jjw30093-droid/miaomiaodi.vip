-- quant_dbt/models/staging/stg_player_stats.sql

WITH source AS (
    SELECT rowid, * FROM {{ source('main', 'fact_player_match_stats') }}
),

deduplicated AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY "Match_ID", "Player_ID" 
            ORDER BY rowid DESC
        ) AS rn
    FROM source
),

renamed AS (
    SELECT
        CAST("Match_ID" AS INTEGER) AS match_id,
        CAST("Team_ID" AS INTEGER) AS team_id,
        CAST("Player_ID" AS INTEGER) AS player_id,
        "Player_Name",
        "minutes_played",
        "is_goalkeeper",
        CAST(COALESCE("xg_and_xa", 0) AS REAL) AS xg_xa,
        CAST(COALESCE("chances_created", 0) AS REAL) AS chances_created,
        CAST(COALESCE("defensive_actions", 0) AS REAL) AS defensive_actions,
        CAST(COALESCE("recoveries", 0) AS REAL) AS recoveries,
        CAST(COALESCE("expected_goals_on_target_faced", 0) AS REAL) AS xgot_faced,
        CAST(COALESCE("goals_conceded", 0) AS REAL) AS goals_conceded
    FROM deduplicated
    WHERE rn = 1
)

SELECT * FROM renamed
