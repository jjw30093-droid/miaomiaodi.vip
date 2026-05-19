-- quant_dbt/models/staging/stg_shotmap.sql

WITH source AS (
    SELECT rowid, * FROM {{ source('main', 'fact_shotmap') }}
),

deduplicated AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY "Match_ID", "Player_ID", "Minute", "X_Coord", "Y_Coord" 
            ORDER BY rowid DESC
        ) AS rn
    FROM source
),

renamed AS (
    SELECT
        CAST("Match_ID" AS INTEGER) AS match_id,
        CAST("Player_ID" AS INTEGER) AS player_id,
        "Minute",
        "Period",
        "X_Coord",
        "Y_Coord",
        CAST(COALESCE("xG", 0) AS REAL) AS xg,
        CAST(COALESCE("xGOT", 0) AS REAL) AS xgot,
        "Situation",
        "Outcome"
    FROM deduplicated
    WHERE rn = 1
)

SELECT * FROM renamed
