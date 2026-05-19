-- models/marts/mart_match_prediction_matrix.sql
{{ config(materialized='view') }}

WITH rolling_features AS (
    -- 引入我们刚刚建好的近5场滚动状态表
    SELECT * FROM {{ ref('int_team_rolling_features') }}
),

match_info AS (
    -- 引入已清洗的赛事基础维表
    SELECT
        match_id,
        match_date,
        League_ID,
        Home_Team_ID,
        Home_Team_Name,
        Away_Team_ID,
        Away_Team_Name
    FROM {{ ref('stg_match_info') }}
)

SELECT
    m.match_id,
    m.match_date,
    m.League_ID,
    m.Home_Team_Name,
    m.Away_Team_Name,

    -------------------------------------------------------------------------
    -- [主队近期状态底色] Home Team Form
    -------------------------------------------------------------------------
    hf.roll_5_npxGD AS home_L5_npxGD,
    hf.roll_5_ppda AS home_L5_ppda,
    hf.roll_5_field_tilt AS home_L5_field_tilt,
    hf.roll_5_golden_zone_ratio AS home_L5_golden_zone,
    hf.roll_5_team_goals_prevented AS home_L5_goals_prevented,
    hf.roll_5_split_npxG_for AS home_L5_home_npxG,

    -------------------------------------------------------------------------
    -- [客队近期状态底色] Away Team Form
    -------------------------------------------------------------------------
    af.roll_5_npxGD AS away_L5_npxGD,
    af.roll_5_ppda AS away_L5_ppda,
    af.roll_5_field_tilt AS away_L5_field_tilt,
    af.roll_5_golden_zone_ratio AS away_L5_golden_zone,
    af.roll_5_team_goals_prevented AS away_L5_goals_prevented,
    af.roll_5_split_npxG_for AS away_L5_away_npxG,

    -------------------------------------------------------------------------
    -- [对位相克特征] Matchup Differentials
    -------------------------------------------------------------------------
    ROUND((hf.roll_5_npxGD - af.roll_5_npxGD), 2) AS form_npxGD_diff,
    ROUND((hf.roll_5_field_tilt - af.roll_5_field_tilt), 2) AS control_tilt_diff,
    ROUND((hf.roll_5_golden_zone_ratio - af.roll_5_golden_zone_ratio), 4) AS penetration_diff

FROM match_info m
LEFT JOIN rolling_features hf
    ON m.match_id = hf.match_id AND m.Home_Team_ID = hf.team_id
LEFT JOIN rolling_features af
    ON m.match_id = af.match_id AND m.Away_Team_ID = af.team_id

WHERE hf.roll_5_npxGD IS NOT NULL
  AND af.roll_5_npxGD IS NOT NULL