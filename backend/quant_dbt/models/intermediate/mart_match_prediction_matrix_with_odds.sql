-- models/intermediate/mart_match_prediction_matrix_with_odds.sql
{{ config(materialized='view') }}

WITH base_matrix AS (
    SELECT * FROM {{ ref('mart_match_prediction_matrix') }}
),
odds AS (
    SELECT * FROM {{ ref('stg_match_odds') }}
)

SELECT 
    m.*, 
    -- 附加赔率模块 (Odds Features)
    o.odds_1x2_home,
    o.odds_1x2_draw,
    o.odds_1x2_away,
    o.odds_ah_line,
    o.odds_ah_home,
    o.odds_ah_away,
    o.odds_ou_line,
    o.odds_over_ou_line,
    o.odds_under_ou_line
FROM base_matrix m
-- Phase 2.5: JOIN by match_id (precise), replacing name+date fuzzy join
LEFT JOIN odds o ON m.Match_ID = o.match_id
