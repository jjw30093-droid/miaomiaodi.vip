"""
refresh_rolling_features.py
============================
对指定球队重新计算并更新 int_team_match_flattened 和 int_team_rolling_features。
主要用于 dbt 未运行时手动修复滞后特征。

用法：
  python scripts/refresh_rolling_features.py --team_ids 8564 8600
  python scripts/refresh_rolling_features.py --all   # 全量重算（慢）
"""

import os, sys, sqlite3, argparse
from pathlib import Path

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", str(Path(__file__).resolve().parent.parent))
DB_PATH      = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))
sys.path.insert(0, PROJECT_ROOT)

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


FLATTEN_SQL = """
INSERT OR REPLACE INTO int_team_match_flattened
(match_id, match_date, Season, team_id, is_home, opponent_id,
 goals_for, goals_conceded, xG_for, xGA_against, xGD,
 npxG_for, npxGA_against, npxGD,
 xG_open_play_for, xG_set_play_for,
 big_chances_created, big_chances_missed, big_chances_conceded, shot_quality_added,
 total_shots_for, shots_on_target_for, shots_inside_box_for, shots_outside_box_for, box_shot_ratio,
 possession_pct, possession_diff, field_tilt,
 touches_in_opp_box, long_ball_ratio,
 team_goals_prevented, proxy_ppda,
 keeper_saves, blocked_shots,
 golden_zone_shot_ratio_for, outside_box_shot_ratio_for, avg_xG_per_shot_for,
 golden_zone_shot_ratio_conceded, outside_box_shot_ratio_conceded)

WITH sz AS (
    SELECT
        match_id, team_id,
        ROUND(SUM(CASE WHEN (X_Coord BETWEEN 88.5 AND 100) AND (Y_Coord BETWEEN 21.1 AND 78.9) THEN 1.0 ELSE 0 END) / NULLIF(COUNT(*), 0), 4) AS golden_zone_shot_ratio,
        ROUND(SUM(CASE WHEN X_Coord < 83 THEN 1.0 ELSE 0 END) / NULLIF(COUNT(*), 0), 4) AS outside_box_shot_ratio,
        ROUND(AVG(COALESCE(xG, 0)), 4) AS avg_xG_per_shot
    FROM fact_shotmap
    GROUP BY match_id, team_id
)
SELECT
    t1.Match_ID        AS match_id,
    d.Date             AS match_date,
    d.Season,
    t1.Team_ID         AS team_id,
    CASE WHEN t1.Team_ID = d.Home_Team_ID THEN 1 ELSE 0 END AS is_home,
    t2.Team_ID         AS opponent_id,
    -- 进球
    COALESCE(t1.Goals, 0)                      AS goals_for,
    COALESCE(t2.Goals, 0)                      AS goals_conceded,
    COALESCE(t1.expected_goals, 0)             AS xG_for,
    COALESCE(t2.expected_goals, 0)             AS xGA_against,
    COALESCE(t1.expected_goals, 0) - COALESCE(t2.expected_goals, 0) AS xGD,
    COALESCE(t1.expected_goals_non_penalty, 0)             AS npxG_for,
    COALESCE(t2.expected_goals_non_penalty, 0)             AS npxGA_against,
    COALESCE(t1.expected_goals_non_penalty, 0) - COALESCE(t2.expected_goals_non_penalty, 0) AS npxGD,
    COALESCE(t1.expected_goals_open_play, 0)               AS xG_open_play_for,
    COALESCE(t1.expected_goals_set_play, 0)                AS xG_set_play_for,
    -- 机会
    COALESCE(t1.big_chance, 0)                 AS big_chances_created,
    COALESCE(t1.big_chance_missed_title, 0)    AS big_chances_missed,
    COALESCE(t2.big_chance, 0)                 AS big_chances_conceded,
    COALESCE(t1.expected_goals_on_target, 0) - COALESCE(t1.expected_goals, 0) AS shot_quality_added,
    -- 射门
    COALESCE(t1.total_shots, 0)                AS total_shots_for,
    COALESCE(t1.ShotsOnTarget, 0)              AS shots_on_target_for,
    COALESCE(t1.shots_inside_box, 0)           AS shots_inside_box_for,
    COALESCE(t1.shots_outside_box, 0)          AS shots_outside_box_for,
    ROUND(COALESCE(t1.shots_inside_box, 0) * 1.0 / NULLIF(t1.total_shots, 0), 2) AS box_shot_ratio,
    -- 控球
    COALESCE(t1.BallPossesion, 0)              AS possession_pct,
    COALESCE(t1.BallPossesion, 0) - COALESCE(t2.BallPossesion, 0) AS possession_diff,
    -- 场地倾斜
    ROUND(COALESCE(t1.opposition_half_passes, 0) * 1.0 /
          NULLIF(COALESCE(t1.opposition_half_passes, 0) + COALESCE(t2.opposition_half_passes, 0), 0), 2) AS field_tilt,
    COALESCE(t1.touches_opp_box, 0)            AS touches_in_opp_box,
    ROUND(COALESCE(t1.long_balls_accurate, 0) * 1.0 / NULLIF(t1.passes, 0), 2) AS long_ball_ratio,
    -- 防守
    COALESCE(t2.expected_goals_on_target, 0) - COALESCE(t2.Goals, 0) AS team_goals_prevented,
    ROUND(COALESCE(t2.own_half_passes, 0) * 1.0 /
          NULLIF(COALESCE(t1."matchstats.headers.tackles", 0) + COALESCE(t1.interceptions, 0) + COALESCE(t1.fouls, 0), 0), 2) AS proxy_ppda,
    -- Phase B 新增: 门将扑救 + 封堵射门
    COALESCE(t1.keeper_saves, 0)             AS keeper_saves,
    COALESCE(t1.blocked_shots, 0)            AS blocked_shots,
    -- 射门地图
    COALESCE(sz1.golden_zone_shot_ratio, 0)    AS golden_zone_shot_ratio_for,
    COALESCE(sz1.outside_box_shot_ratio, 0)    AS outside_box_shot_ratio_for,
    COALESCE(sz1.avg_xG_per_shot, 0)           AS avg_xG_per_shot_for,
    COALESCE(sz2.golden_zone_shot_ratio, 0)    AS golden_zone_shot_ratio_conceded,
    COALESCE(sz2.outside_box_shot_ratio, 0)    AS outside_box_shot_ratio_conceded

FROM fact_team_match_stats t1
JOIN fact_team_match_stats t2
    ON t1.Match_ID = t2.Match_ID AND t1.Team_ID != t2.Team_ID
JOIN dim_match d ON d.Match_ID = t1.Match_ID
LEFT JOIN sz sz1 ON sz1.match_id = t1.Match_ID AND sz1.team_id = t1.Team_ID
LEFT JOIN sz sz2 ON sz2.match_id = t1.Match_ID AND sz2.team_id = t2.Team_ID

WHERE t1.Period = 'All' AND t2.Period = 'All'
  AND d.status = 'Finish'
  {team_filter}
  AND t1.Match_ID NOT IN (
      SELECT DISTINCT match_id FROM int_team_match_flattened
      WHERE team_id = t1.Team_ID
  )
ORDER BY d.Date
"""


ROLLING_SQL = """
INSERT OR REPLACE INTO int_team_rolling_features
(match_id, match_date, team_id, is_home, opponent_id,
 roll_5_npxGD, roll_5_xGD, roll_5_big_chances_created,
 roll_5_ppda, roll_5_field_tilt, roll_5_poss_diff, roll_5_long_ball_ratio,
 roll_5_box_shot_ratio, roll_5_shot_quality_added, roll_5_team_goals_prevented,
 roll_5_golden_zone_ratio, roll_5_outside_box_ratio, roll_5_golden_zone_conceded,
 roll_5_split_npxG_for, roll_5_split_npxGA_against, roll_5_open_play_xg_for, roll_5_set_play_xg_for,
 -- Phase B 最优窗口列
 roll_14_npxGD, roll_3_field_tilt, roll_3_box_shot_ratio,
 roll_3_big_chances_created, roll_3_open_play_xg_for,
 roll_14_blocked_shots, roll_5_keeper_saves)

SELECT
    match_id, match_date, team_id, is_home, opponent_id,
    ROUND(AVG(npxGD) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(xGD)   OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(big_chances_created) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 1),
    ROUND(AVG(proxy_ppda)    OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(field_tilt)    OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(possession_diff) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 1),
    ROUND(AVG(long_ball_ratio)  OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(box_shot_ratio)   OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(shot_quality_added) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(team_goals_prevented) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(golden_zone_shot_ratio_for)      OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 4),
    ROUND(AVG(outside_box_shot_ratio_for)      OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 4),
    ROUND(AVG(golden_zone_shot_ratio_conceded) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 4),
    ROUND(AVG(npxG_for)    OVER(PARTITION BY team_id, is_home ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(npxGA_against) OVER(PARTITION BY team_id, is_home ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(xG_open_play_for) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(xG_set_play_for)  OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 2),
    -- Phase B 最优窗口
    ROUND(AVG(npxGD)              OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(field_tilt)         OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(box_shot_ratio)     OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(big_chances_created) OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 1),
    ROUND(AVG(xG_open_play_for)   OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 2),
    ROUND(AVG(blocked_shots)      OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING), 1),
    ROUND(AVG(keeper_saves)       OVER(PARTITION BY team_id ORDER BY match_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING), 1)

FROM int_team_match_flattened
WHERE team_id IN ({team_ids})
"""


def refresh(conn, team_ids: list):
    ids_str = ",".join(str(t) for t in team_ids)
    team_filter = f"AND t1.Team_ID IN ({ids_str})" if team_ids else ""

    log.info(f"Step 1: 补全 int_team_match_flattened (teams={ids_str or 'ALL'}) ...")
    sql = FLATTEN_SQL.format(team_filter=team_filter)
    try:
        cur = conn.execute(sql)
        log.info(f"  已插入 {cur.rowcount} 条记录")
    except Exception as e:
        log.error(f"  ❌ 失败: {e}")
        raise

    log.info(f"Step 2: 重算 int_team_rolling_features ...")
    rolling_ids = ids_str if ids_str else "SELECT DISTINCT team_id FROM int_team_match_flattened"
    sql2 = ROLLING_SQL.format(team_ids=rolling_ids if ids_str else
                              "SELECT DISTINCT team_id FROM int_team_match_flattened")
    # SQLite 不允许 IN (subquery) 在 PARTITION BY 后，用临时表代替
    if not ids_str:
        rolling_ids_str = ",".join(
            str(r[0]) for r in conn.execute(
                "SELECT DISTINCT team_id FROM int_team_match_flattened"
            ).fetchall()
        )
        sql2 = ROLLING_SQL.format(team_ids=rolling_ids_str)

    try:
        cur2 = conn.execute(sql2)
        log.info(f"  已更新 {cur2.rowcount} 条记录")
    except Exception as e:
        log.error(f"  ❌ 失败: {e}")
        raise

    conn.commit()

    # 验证
    for tid in team_ids:
        r = conn.execute("""
            SELECT rf.match_id, d.Date, rf.roll_5_npxGD
            FROM int_team_rolling_features rf
            JOIN dim_match d ON d.Match_ID = rf.match_id
            WHERE rf.team_id=? ORDER BY d.Date DESC LIMIT 1
        """, (tid,)).fetchone()
        if r:
            log.info(f"  ✅ team_id={tid} 最新特征: [{r[1]}] npxGD={r[2]}")
        else:
            log.warning(f"  ⚠️ team_id={tid} 无特征记录")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--team_ids", nargs="+", type=int)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        if args.all:
            refresh(conn, [])
        elif args.team_ids:
            refresh(conn, args.team_ids)
        else:
            parser.print_help()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
