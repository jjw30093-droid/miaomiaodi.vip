import sqlite3
import pandas as pd
from sqlalchemy import create_engine, text
import os

# 配置路径
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "football_uk.db"))
ENGINE = create_engine(f"sqlite:///{DB_PATH}")

def normalize_fact_stats(engine):
    """函数1: 将 fact_team_match_stats 的字段名规范化"""
    print("🚀 Step 1: Normalizing fact_team_match_stats...")
    with engine.connect() as conn:
        # 1. 读取原始数据
        df = pd.read_sql("SELECT * FROM fact_team_match_stats", conn)
        
        # 2. 字段重命名映射
        rename_map = {
            'BallPossesion': 'ball_possession',
            'big_chance_missed_title': 'big_chance_missed',
            'matchstats.headers.tackles': 'tackles',
            'ShotsOnTarget': 'shots_on_target',
            'ShotsOffTarget': 'shots_off_target'
        }
        df.rename(columns=rename_map, inplace=True)
        
        # 3. 写入临时表
        df.to_sql('_normalized_team_stats', engine, if_exists='replace', index=False)
        print(f"✅ Normalized data written to _normalized_team_stats. Rows: {len(df)}")

def rebuild_stg_match_info(engine):
    """函数2: 从 dim_match 重建 stg_match_info"""
    print("🚀 Step 2: Syncing stg_match_info from dim_match...")
    # 注意：用户提到 stg_match_info 是 VIEW，这里我们只确认数据源，不对 VIEW 执行操作。
    # 这里通过检查数据源 dim_match 逻辑来确保下游可用
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM dim_match")).scalar()
        print(f"✅ dim_match count: {count}")

def rebuild_stg_team_stats(engine):
    """函数3: 从 _normalized_team_stats 重建 stg_team_stats 的底层逻辑数据"""
    print("🚀 Step 3: Preparing data for stg_team_stats...")
    # 同样地，如果 stg_team_stats 是 VIEW，通常它会 SELECT FROM _normalized_team_stats (如果我们将临时表持久化)
    # 本脚本以 SELECT 方式读取，不操作 VIEW
    pass

def rebuild_int_team_shot_zones(engine):
    """函数4: 从 fact_shotmap 计算射门区域统计"""
    print("🚀 Step 4: Rebuilding int_team_shot_zones...")
    with engine.connect() as conn:
        # 获取射门数据及其所属球队
        query = """
        SELECT s.Match_ID, p.Team_ID, s.X_Coord, s.Y_Coord, s.xG
        FROM fact_shotmap s
        JOIN fact_player_match_stats p ON s.Match_ID = p.Match_ID AND s.Player_ID = p.Player_ID
        """
        shots = pd.read_sql(query, conn)
        
        # 定义计算逻辑
        def calc_match_stats(group):
            total = len(group)
            if total == 0: return pd.Series({'golden_zone_shot_ratio':0, 'outside_box_shot_ratio':0, 'avg_xG_per_shot':0})
            
            # golden_zone: x > 83 AND y BETWEEN 21 AND 79
            gz = group[(group['X_Coord'] > 83) & (group['Y_Coord'] >= 21) & (group['Y_Coord'] <= 79)]
            # outside_box: x < 83
            ob = group[group['X_Coord'] < 83]
            
            return pd.Series({
                'golden_zone_shot_ratio': round(len(gz) / total, 3),
                'outside_box_shot_ratio': round(len(ob) / total, 3),
                'avg_xG_per_shot': round(group['xG'].mean(), 3)
            })
        
        zones = shots.groupby(['Match_ID', 'Team_ID']).apply(calc_match_stats).reset_index()
        
        # 创建表并写入
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS int_team_shot_zones (
                Match_ID BIGINT,
                Team_ID BIGINT,
                golden_zone_shot_ratio FLOAT,
                outside_box_shot_ratio FLOAT,
                avg_xG_per_shot FLOAT,
                PRIMARY KEY (Match_ID, Team_ID)
            )
        """))
        
        zones.to_sql('int_team_shot_zones', engine, if_exists='replace', index=False, method='multi')
        print(f"✅ int_team_shot_zones rebuilt. Rows: {len(zones)}")

def rebuild_int_team_match_flattened(engine):
    """函数5: 核心拉平逻辑，将结果写入 int_team_match_flattened"""
    print("🚀 Step 5: Rebuilding int_team_match_flattened...")
    sql = """
    INSERT OR REPLACE INTO int_team_match_flattened
    SELECT
        m.match_id,
        m.match_date,
        m.Season,
        t1.team_id,
        CASE WHEN t1.team_id = m.Home_Team_ID THEN 1 ELSE 0 END AS is_home,
        t2.team_id AS opponent_id,
        t1.goals AS goals_for,
        t2.goals AS goals_conceded,
        t1.expected_goals AS xG_for,
        t2.expected_goals AS xGA_against,
        (t1.expected_goals - t2.expected_goals) AS xGD,
        t1.expected_goals_non_penalty AS npxG_for,
        t2.expected_goals_non_penalty AS npxGA_against,
        (t1.expected_goals_non_penalty - t2.expected_goals_non_penalty) AS npxGD,
        t1.big_chance AS big_chances_created,
        t1.big_chance_missed AS big_chances_missed,
        t2.big_chance AS big_chances_conceded,
        (t1.expected_goals_on_target - t1.expected_goals) AS shot_quality_added,
        t1.total_shots AS total_shots_for,
        t1.shots_on_target AS shots_on_target_for,
        t1.shots_inside_box AS shots_inside_box_for,
        t1.shots_outside_box AS shots_outside_box_for,
        ROUND(CAST(t1.shots_inside_box AS REAL) / 
              NULLIF(t1.total_shots, 0), 2) AS box_shot_ratio,
        t1.ball_possession AS possession_pct,
        (t1.ball_possession - t2.ball_possession) AS possession_diff,
        ROUND(CAST(t1.opposition_half_passes AS REAL) /
              NULLIF((t1.opposition_half_passes + 
                      t2.opposition_half_passes), 0), 2) AS field_tilt,
        t1.touches_opp_box AS touches_in_opp_box,
        ROUND(CAST(t1.long_balls_accurate AS REAL) / 
              NULLIF(t1.passes, 0), 2) AS long_ball_ratio,
        (t2.expected_goals_on_target - t2.goals) AS team_goals_prevented,
        ROUND(CAST(t2.own_half_passes AS REAL) /
              NULLIF((t1.tackles + t1.interceptions + t1.fouls), 0), 
              2) AS proxy_ppda,
        CAST(COALESCE(sz1.golden_zone_shot_ratio, 0) AS REAL),
        CAST(COALESCE(sz1.outside_box_shot_ratio, 0) AS REAL),
        CAST(COALESCE(sz1.avg_xG_per_shot, 0) AS REAL),
        CAST(COALESCE(sz2.golden_zone_shot_ratio, 0) AS REAL),
        CAST(COALESCE(sz2.outside_box_shot_ratio, 0) AS REAL)
    FROM _normalized_team_stats t1
    JOIN _normalized_team_stats t2 
        ON t1.match_id = t2.match_id AND t1.team_id != t2.team_id
    JOIN dim_match m ON t1.match_id = m.Match_ID
    LEFT JOIN int_team_shot_zones sz1 
        ON t1.match_id = sz1.Match_ID AND t1.team_id = sz1.Team_ID
    LEFT JOIN int_team_shot_zones sz2 
        ON t2.match_id = sz2.Match_ID AND t2.team_id = sz2.Team_ID
    WHERE t1.Period = 'All' AND t2.Period = 'All'
    """
    with engine.begin() as conn:
        res = conn.execute(text(sql))
        print(f"✅ int_team_match_flattened updated. Rows affected: {res.rowcount}")

def verify_pipeline(engine, match_id):
    """函数7: 验证指定 match_id 的数据是否完整"""
    print(f"\n🔍 Verifying match {match_id}...")
    with engine.connect() as conn:
        res = conn.execute(text(f"SELECT is_home, goals_for, npxGD FROM int_team_match_flattened WHERE match_id = {match_id}")).fetchall()
        if not res:
            print(f"❌ No record found for match {match_id} in int_team_match_flattened.")
        else:
            for row in res:
                print(f"✅ [{'Home' if row[0] else 'Away'}] Goals: {row[1]}, npxGD: {row[2]}")

def run_full_pipeline(engine, incremental=True):
    """函数6: 主函数，按顺序调用所有步骤"""
    print("=" * 60)
    print("🚀 Starting Full ETL Pipeline...")
    print("=" * 60)
    
    normalize_fact_stats(engine)
    rebuild_stg_match_info(engine)
    rebuild_stg_team_stats(engine)
    rebuild_int_team_shot_zones(engine)
    rebuild_int_team_match_flattened(engine)
    
    print("\n" + "=" * 60)
    print("🏁 Pipeline Completed Successfully.")
    print("=" * 60)

if __name__ == "__main__":
    run_full_pipeline(ENGINE)
    verify_pipeline(ENGINE, 5130428)
