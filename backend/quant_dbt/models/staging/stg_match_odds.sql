-- models/staging/stg_match_odds.sql
-- Phase 2.5: 从 silver_match_odds 读取，消除对旧 team_mapping 的依赖
{{ config(materialized='view') }}

WITH opening_1x2 AS (
    SELECT
        match_id,
        match_date,
        raw_home        AS odds_1x2_home,
        raw_draw        AS odds_1x2_draw,
        raw_away        AS odds_1x2_away,
        fair_home       AS fair_1x2_home,
        fair_draw       AS fair_1x2_draw,
        fair_away       AS fair_1x2_away,
        overround       AS overround_1x2
    FROM {{ source('main', 'silver_match_odds') }}
    WHERE market = '1x2' AND period = 'opening'
),

opening_ou AS (
    SELECT
        match_id,
        raw_home                        AS odds_over,
        raw_away                        AS odds_under,
        COALESCE(raw_line, 2.5)         AS odds_ou_line,
        fair_home                       AS fair_over,
        fair_away                       AS fair_under
    FROM {{ source('main', 'silver_match_odds') }}
    WHERE market = 'ou' AND period = 'opening'
),

opening_ah AS (
    SELECT
        match_id,
        raw_home    AS odds_ah_home,
        raw_away    AS odds_ah_away,
        raw_line    AS odds_ah_line
    FROM {{ source('main', 'silver_match_odds') }}
    WHERE market = 'ah' AND period = 'opening'
)

SELECT
    dm.Date                             AS match_date,
    dm.Home_Team_Name                   AS standard_home_team_name,
    dm.Away_Team_Name                   AS standard_away_team_name,
    e.match_id,
    -- 1x2 raw
    e.odds_1x2_home,
    e.odds_1x2_draw,
    e.odds_1x2_away,
    -- OU
    u.odds_ou_line,
    u.odds_over                         AS odds_over_ou_line,
    u.odds_under                        AS odds_under_ou_line,
    -- AH
    a.odds_ah_line,
    a.odds_ah_home,
    a.odds_ah_away,
    -- fair probabilities
    e.fair_1x2_home,
    e.fair_1x2_draw,
    e.fair_1x2_away,
    e.overround_1x2,
    u.fair_over,
    u.fair_under
FROM opening_1x2 e
JOIN {{ source('main', 'dim_match') }} dm ON e.match_id = dm.Match_ID
LEFT JOIN opening_ou  u ON e.match_id = u.match_id
LEFT JOIN opening_ah  a ON e.match_id = a.match_id
