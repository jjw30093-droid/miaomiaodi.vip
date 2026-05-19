-- quant_dbt/models/staging/stg_match_info.sql

WITH source AS (
    SELECT * FROM {{ source('main', 'dim_match') }}
),

renamed AS (
    SELECT
        CAST("Match_ID" AS INTEGER) AS match_id,
        "Date" AS match_date,
        "League_ID",
        "Season",
        "Match_Round" AS round,
        "Home_Team_ID",
        "Home_Team_Name",
        "Away_Team_ID",
        "Away_Team_Name"
    FROM source
),

deduplicated AS (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY match_id ORDER BY match_date DESC) AS rn
    FROM renamed
)

SELECT
    match_id,
    match_date,
    League_ID,
    Season,
    round,
    Home_Team_ID,
    Home_Team_Name,
    Away_Team_ID,
    Away_Team_Name
FROM deduplicated
WHERE rn = 1

