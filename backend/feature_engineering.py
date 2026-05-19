"""
feature_engineering.py — Phase 2: 数据湖特征工程模块
=====================================================
职责: 从 Fact Layer 原始数据衍生出 ML Engine (Phase 3) 所需的全部高阶特征,
      写入 Intelligence Layer 扩展表。

新增特征清单:
  1. shot_pace          — 射门事件密度 (大小球节奏基线)
  2. game_state_xg      — 领先/落后/平局状态下的 xG 拆分
  3. elo_rating          — 动态 Elo (连续型对手实力度量)
  4. rest_days_diff      — 休息天数差值 (疲劳因子)
  5. opp_adj_npxgd       — 对手实力加权 npxGD
  6. defensive_contrib   — 球员防守贡献基线 (Phase 3/4 伤停核算用)

设计原则:
  - 每个 compute_* 方法返回 pd.DataFrame, 互不耦合
  - run_pipeline() 串联全流程, 幂等可重跑
  - 支持 roll_5 / roll_10 双窗口滚动

已知限制:
  - 乌龙球不在 shotmap 中, game_state 重建以 Team_Stats goals 兜底
  - Elo 冷启动: 新赛季首场使用上赛季末 Elo 或默认 1500
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional
import logging
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("feature_engineering")

# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------
ELO_INIT = 1500          # 初始 Elo
ELO_K    = 32            # K-factor, 偏高以增强近期敏感度
ROLL_WINDOWS = [3, 5, 7, 10, 14, 30]   # v5: includes optimal windows from Phase A2

# ---------------------------------------------------------------------------
#  DDL: 新表定义
# ---------------------------------------------------------------------------
DDL_MATCH_FEATURES = """
CREATE TABLE IF NOT EXISTS int_match_features_extended (
    match_id      TEXT,
    team_id       INTEGER,
    -- shot pace
    shots_for           INTEGER,
    shots_against       INTEGER,
    shot_pace           REAL,
    -- game state xG
    xg_when_leading     REAL,
    xg_when_trailing    REAL,
    xg_when_level       REAL,
    trailing_xg_ratio   REAL,
    level_xg_ratio      REAL,
    -- elo
    pre_match_elo       REAL,
    opp_pre_match_elo   REAL,
    -- rest
    rest_days           INTEGER,
    rest_days_diff      INTEGER,
    -- opponent-adjusted
    match_npxgd             REAL,
    opp_adj_npxgd           REAL,
    PRIMARY KEY (match_id, team_id)
);
"""

DDL_ELO_HISTORY = """
CREATE TABLE IF NOT EXISTS int_team_elo_history (
    team_id       INTEGER,
    match_id      TEXT,
    match_date    TEXT,
    pre_match_elo REAL,
    post_match_elo REAL,
    elo_delta     REAL,
    PRIMARY KEY (team_id, match_id)
);
"""

DDL_PLAYER_DEF_CONTRIB = """
CREATE TABLE IF NOT EXISTS int_player_defensive_contrib (
    player_id       TEXT,
    team_id         INTEGER,
    matches_played  INTEGER,
    avg_clearances      REAL,
    avg_interceptions   REAL,
    avg_tackles         REAL,
    avg_shot_blocks     REAL,
    avg_aerials_won     REAL,
    defensive_score     REAL,
    def_contribution_pct REAL,
    PRIMARY KEY (player_id, team_id)
);
"""

DDL_ROLLING_EXTENDED = """
CREATE TABLE IF NOT EXISTS int_team_rolling_extended (
    match_id            TEXT,
    team_id             INTEGER,
    window_size         INTEGER,
    roll_shot_pace          REAL,
    roll_trailing_xg_ratio  REAL,
    roll_level_xg_ratio     REAL,
    roll_opp_adj_npxgd      REAL,
    roll_rest_days          REAL,
    PRIMARY KEY (match_id, team_id, window_size)
);
"""


class FeatureEngineer:
    """Phase 2 特征工程主类"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        logger.info(f"Connected to {db_path}")

    # ===================================================================
    #  Schema
    # ===================================================================
    def create_tables(self):
        """创建/迁移扩展特征表 (幂等)"""
        for ddl in [DDL_MATCH_FEATURES, DDL_ELO_HISTORY,
                     DDL_PLAYER_DEF_CONTRIB, DDL_ROLLING_EXTENDED]:
            self.conn.execute(ddl)
        self.conn.commit()
        logger.info("Extended feature tables created/verified.")

    # ===================================================================
    #  Feature 1: Shot Pace (射门事件密度)
    # ===================================================================
    def compute_shot_pace(self) -> pd.DataFrame:
        """
        shot_pace = (本队射门 + 对手射门) / 90
        含义: 每分钟产生的射门数, 越高代表比赛越开放
        数据源: fact_team_match_stats.total_shots
        """
        query = """
        SELECT
            a.Match_ID as match_id,
            a.Team_ID as team_id,
            a.total_shots   AS shots_for,
            b.total_shots   AS shots_against,
            CAST(a.total_shots + b.total_shots AS REAL) / 90.0 AS shot_pace
        FROM fact_team_match_stats a
        JOIN fact_team_match_stats b
            ON a.Match_ID = b.Match_ID
            AND a.Team_ID != b.Team_ID
        WHERE a.Period = 'All' AND b.Period = 'All'
        """
        df = pd.read_sql(query, self.conn, dtype={"match_id": str})
        logger.info(f"Shot pace computed: {len(df)} rows")
        return df

    # ===================================================================
    #  Feature 2: Game State xG (比赛状态 xG 拆分)
    # ===================================================================
    def compute_game_state_xg(self) -> pd.DataFrame:
        """
        将每支球队的 xG 按比赛状态拆分:
          - xg_when_leading:  领先时的 xG (锁死比赛能力)
          - xg_when_trailing: 落后时的 xG (追分意愿)
          - xg_when_level:    平局时的 xG (僵局破解力)
          - trailing_xg_ratio = xg_when_trailing / total_xG

        逻辑链: shotmap(minute+xG) + goals(minute+team) -> game_state -> 聚合

        已知限制: 乌龙球不在 shotmap, 若 shotmap 进球数 < Team_Stats 进球数,
        差值视为乌龙球, 按最后缺失分钟插入对方进球事件。
        """
        # --- 1. 加载 shotmap ---
        shots_df = pd.read_sql("""
            SELECT Match_ID as match_id, Player_ID as player_id, Minute as minute, xG as xg, Outcome as outcome
            FROM fact_shotmap
        """, self.conn, dtype={"player_id": str, "match_id": str})

        # --- 2. 加载 player -> team 映射 ---
        player_team = pd.read_sql("""
            SELECT DISTINCT Match_ID as match_id, Player_ID as player_id, Team_ID as team_id
            FROM fact_player_match_stats
        """, self.conn, dtype={"player_id": str, "match_id": str})

        shots_df = shots_df.merge(
            player_team, on=["match_id", "player_id"], how="left"
        )

        # --- 3. 加载实际比分 (用于乌龙球兜底) ---
        actual_goals = pd.read_sql("""
            SELECT Match_ID as match_id, Team_ID as team_id, Goals as goals
            FROM fact_team_match_stats
            WHERE period = 'All'
        """, self.conn, dtype={"match_id": str})

        results = []
        for match_id, match_shots in tqdm(shots_df.groupby("match_id"), desc="Processing Game State xG"):
            teams = match_shots["team_id"].dropna().unique()
            if len(teams) < 2:
                logger.warning(f"Match {match_id}: <2 teams in shotmap, skip")
                continue

            # 提取 shotmap 中的进球事件
            goal_events = (
                match_shots[match_shots["outcome"] == "Goal"]
                .sort_values("minute")
                [["minute", "team_id"]]
                .to_dict("records")
            )

            # 乌龙球兜底: 对比实际比分
            actual = actual_goals[actual_goals["match_id"] == match_id]
            for _, row in actual.iterrows():
                tid = row["team_id"]
                actual_g = int(row["goals"])
                sm_g = sum(1 for g in goal_events if g["team_id"] == tid)
                if actual_g > sm_g:
                    for _ in range(actual_g - sm_g):
                        goal_events.append({"minute": 89, "team_id": tid})
                        logger.debug(
                            f"Match {match_id}: OG inferred for team {tid}"
                        )
            goal_events.sort(key=lambda x: x["minute"])

            # --- 4. 对每支球队的每次射门打 game_state 标签 ---
            for team_id in teams:
                opp_id = [t for t in teams if t != team_id][0]
                team_shots_only = match_shots[match_shots["team_id"] == team_id]
                total_xg = team_shots_only["xg"].sum()

                xg_states = {"leading": 0.0, "trailing": 0.0, "level": 0.0}

                for _, shot in team_shots_only.iterrows():
                    t_score = sum(
                        1 for g in goal_events
                        if g["team_id"] == team_id and g["minute"] < shot["minute"]
                    )
                    o_score = sum(
                        1 for g in goal_events
                        if g["team_id"] == opp_id and g["minute"] < shot["minute"]
                    )

                    if t_score > o_score:
                        xg_states["leading"] += shot["xg"]
                    elif t_score < o_score:
                        xg_states["trailing"] += shot["xg"]
                    else:
                        xg_states["level"] += shot["xg"]

                results.append({
                    "match_id": match_id,
                    "team_id": team_id,
                    "xg_when_leading": round(xg_states["leading"], 4),
                    "xg_when_trailing": round(xg_states["trailing"], 4),
                    "xg_when_level": round(xg_states["level"], 4),
                    "trailing_xg_ratio": (
                        round(xg_states["trailing"] / total_xg, 4)
                        if total_xg > 0 else 0.0
                    ),
                    "level_xg_ratio": (
                        round(xg_states["level"] / total_xg, 4)
                        if total_xg > 0 else 0.0
                    ),
                })

        df = pd.DataFrame(results)
        logger.info(f"Game-state xG computed: {len(df)} rows")
        return df

    # ===================================================================
    #  Feature 3: Elo Rating (动态实力评分)
    # ===================================================================
    def compute_elo_ratings(self) -> pd.DataFrame:
        """
        基于历史赛果计算每支球队的动态 Elo rating.
        输出 pre_match_elo (赛前) 用作 LightGBM 特征.
        K=32, 初始值 1500, 支持跨赛季继承.
        """
        matches = pd.read_sql("""
            SELECT
                m.Match_ID as match_id,
                m.Date   AS match_date,
                m.Home_Team_ID      AS home_team_id,
                m.Away_Team_ID      AS away_team_id,
                m.home_score,
                m.away_score
            FROM dim_match m
            WHERE m.status = 'Finish'
              AND m.Home_Team_ID IS NOT NULL
              AND m.Away_Team_ID IS NOT NULL
            ORDER BY m.Date ASC
        """, self.conn, dtype={"match_id": str})

        elo = {}
        history = []

        for _, row in tqdm(matches.iterrows(), total=len(matches), desc="Calculating Elo Ratings"):
            h_id  = row["home_team_id"]
            a_id  = row["away_team_id"]
            mid   = row["match_id"]
            mdate = row["match_date"]

            h_elo = elo.get(h_id, ELO_INIT)
            a_elo = elo.get(a_id, ELO_INIT)

            if row["home_score"] > row["away_score"]:
                h_result, a_result = 1.0, 0.0
            elif row["home_score"] < row["away_score"]:
                h_result, a_result = 0.0, 1.0
            else:
                h_result, a_result = 0.5, 0.5

            h_expected = 1.0 / (1.0 + 10 ** ((a_elo - h_elo) / 400))
            a_expected = 1.0 - h_expected

            h_new = h_elo + ELO_K * (h_result - h_expected)
            a_new = a_elo + ELO_K * (a_result - a_expected)

            for tid, pre, post in [
                (h_id, h_elo, h_new), (a_id, a_elo, a_new)
            ]:
                history.append({
                    "team_id": tid,
                    "match_id": mid,
                    "match_date": mdate,
                    "pre_match_elo": round(pre, 2),
                    "post_match_elo": round(post, 2),
                    "elo_delta": round(post - pre, 2),
                })

            elo[h_id] = h_new
            elo[a_id] = a_new

        df = pd.DataFrame(history)
        logger.info(f"Elo ratings computed: {len(df)} rows, {len(elo)} teams")
        return df

    # ===================================================================
    #  Feature 4: Rest Days (休息天数差值)
    # ===================================================================
    def compute_rest_days(self) -> pd.DataFrame:
        """
        rest_days: 距上一场比赛的天数 (首场默认 7)
        rest_days_diff: home_rest - away_rest (正=主队更充沛)
        """
        matches = pd.read_sql("""
            SELECT
                Match_ID as match_id,
                Date AS match_date,
                Home_Team_ID    AS home_team_id,
                Away_Team_ID    AS away_team_id
            FROM dim_match
            WHERE Home_Team_ID IS NOT NULL
              AND Away_Team_ID IS NOT NULL
            ORDER BY Date ASC
        """, self.conn, dtype={"match_id": str})

        matches["match_date"] = pd.to_datetime(matches["match_date"], errors='coerce')
        matches = matches.dropna(subset=["match_date"])

        team_last_match = {}
        records = []

        for _, row in tqdm(matches.iterrows(), total=len(matches), desc="Calculating Rest Days"):
            mid   = row["match_id"]
            mdate = row["match_date"]
            rest  = {}

            for side, tid in [("home", row["home_team_id"]),
                              ("away", row["away_team_id"])]:
                last = team_last_match.get(tid)
                if last is not None:
                    delta = (mdate - last).days
                else:
                    delta = 7
                rest[side] = delta
                team_last_match[tid] = mdate

                records.append({
                    "match_id": mid,
                    "team_id": tid,
                    "rest_days": delta,
                })

            diff = rest["home"] - rest["away"]
            for r in records[-2:]:
                if r["team_id"] == row["home_team_id"]:
                    r["rest_days_diff"] = diff
                else:
                    r["rest_days_diff"] = -diff

        df = pd.DataFrame(records)
        logger.info(f"Rest days computed: {len(df)} rows")
        return df

    # ===================================================================
    #  Feature 5: Opponent-Adjusted npxGD
    # ===================================================================
    def compute_opp_adjusted_npxgd(
        self, elo_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        opp_adj_npxgd = match_npxgd * (opp_elo / league_avg_elo)

        效果: 对弱队刷出的 npxGD 打折, 对强队拿到的 npxGD 加权.
        """
        npxgd = pd.read_sql("""
            SELECT
                a.Match_ID as match_id,
                a.Team_ID as team_id,
                (CAST(a.expected_goals_non_penalty AS REAL)
                 - CAST(b.expected_goals_non_penalty AS REAL)) AS match_npxgd
            FROM fact_team_match_stats a
            JOIN fact_team_match_stats b
                ON a.Match_ID = b.Match_ID AND a.Team_ID != b.Team_ID
            WHERE a.Period = 'All' AND b.Period = 'All'
        """, self.conn, dtype={"match_id": str})

        elo_slim = elo_df[["match_id", "team_id", "pre_match_elo"]].copy()
        npxgd = npxgd.merge(elo_slim, on=["match_id", "team_id"], how="left")

        opp_elo = elo_slim.copy().rename(columns={
            "team_id": "opp_team_id",
            "pre_match_elo": "opp_pre_match_elo",
        })

        opp_map = pd.read_sql("""
            SELECT
                a.Match_ID as match_id, a.Team_ID as team_id, b.Team_ID AS opp_team_id
            FROM fact_team_match_stats a
            JOIN fact_team_match_stats b
                ON a.Match_ID = b.Match_ID AND a.Team_ID != b.Team_ID
            WHERE a.Period = 'All' AND b.Period = 'All'
        """, self.conn, dtype={"match_id": str})

        npxgd = npxgd.merge(
            opp_map[["match_id", "team_id", "opp_team_id"]],
            on=["match_id", "team_id"], how="left",
        )
        npxgd = npxgd.merge(
            opp_elo, on=["match_id", "opp_team_id"], how="left",
        )

        league_avg_elo = elo_slim["pre_match_elo"].mean()
        if league_avg_elo == 0:
            league_avg_elo = ELO_INIT

        npxgd["opp_adj_npxgd"] = (
            npxgd["match_npxgd"]
            * (npxgd["opp_pre_match_elo"] / league_avg_elo)
        ).round(4)

        result = npxgd[[
            "match_id", "team_id", "match_npxgd",
            "pre_match_elo", "opp_pre_match_elo", "opp_adj_npxgd",
        ]]
        logger.info(f"Opp-adjusted npxGD computed: {len(result)} rows")
        return result

    # ===================================================================
    #  Feature 6: Defensive Contribution Baseline (球员防守贡献)
    # ===================================================================
    def compute_defensive_contribution(self) -> pd.DataFrame:
        """
        为每位球员计算防守贡献基线 (Phase 3/4 伤停核算输入).

        defensive_score = 加权(抢断 + 拦截 + 封堵 + 解围 + 争顶)
        def_contribution_pct = 球员 defensive_score / 球队总 defensive_score

        注意: 这里只算基线, 具体 "缺阵后 xGA 变化" 在 Phase 3 ML 模型中处理。
        """
        query = """
        SELECT
            Player_ID as player_id,
            Team_ID as team_id,
            COUNT(*)                        AS matches_played,
            AVG(COALESCE(clearances, 0))     AS avg_clearances,
            AVG(COALESCE(interceptions, 0))  AS avg_interceptions,
            AVG(COALESCE("matchstats.headers.tackles", 0)) AS avg_tackles,
            AVG(COALESCE(shot_blocks, 0))    AS avg_shot_blocks,
            AVG(COALESCE(aerials_won, 0))    AS avg_aerials_won
        FROM fact_player_match_stats
        WHERE minutes_played >= 45
        GROUP BY player_id, team_id
        HAVING matches_played >= 3
        """
        df = pd.read_sql(query, self.conn, dtype={"player_id": str})

        df["defensive_score"] = (
            df["avg_tackles"] * 1.2
            + df["avg_interceptions"] * 1.3
            + df["avg_shot_blocks"] * 1.5
            + df["avg_clearances"] * 0.8
            + df["avg_aerials_won"] * 0.7
        ).round(3)

        team_total = df.groupby("team_id")["defensive_score"].transform("sum")
        df["def_contribution_pct"] = (
            (df["defensive_score"] / team_total).fillna(0).round(4)
        )

        logger.info(f"Defensive contribution computed: {len(df)} players")
        return df

    # ===================================================================
    #  Rolling Aggregation (滚动窗口)
    # ===================================================================
    def compute_rolling_features(
        self, features_df: pd.DataFrame, windows: list[int] = None
    ) -> pd.DataFrame:
        """
        对 int_match_features_extended 做滚动聚合.
        支持 roll_5 / roll_10 双窗口.
        """
        if windows is None:
            windows = ROLL_WINDOWS

        if "match_date" not in features_df.columns:
            dates = pd.read_sql("""
                SELECT Match_ID as match_id, Date AS match_date FROM dim_match
            """, self.conn, dtype={"match_id": str})
            features_df = features_df.merge(dates, on="match_id", how="left")

        features_df["match_date"] = pd.to_datetime(features_df["match_date"], errors='coerce')
        features_df = features_df.dropna(subset=["match_date"])
        features_df = features_df.sort_values(["team_id", "match_date"])

        roll_cols = [
            ("shot_pace", "roll_shot_pace"),
            ("trailing_xg_ratio", "roll_trailing_xg_ratio"),
            ("level_xg_ratio", "roll_level_xg_ratio"),
            ("opp_adj_npxgd", "roll_opp_adj_npxgd"),
            ("rest_days", "roll_rest_days"),
        ]

        all_results = []
        for w in windows:
            rolled = features_df.copy()
            for src, dst in roll_cols:
                if src in rolled.columns:
                    rolled[dst] = (
                        rolled.groupby("team_id")[src]
                        .transform(
                            lambda s: s.rolling(w, min_periods=max(1, w // 2))
                            .mean()
                        )
                        .round(4)
                    )
                else:
                    rolled[dst] = np.nan

            rolled["window_size"] = w
            all_results.append(rolled[[
                "match_id", "team_id", "window_size",
                *[dst for _, dst in roll_cols],
            ]])

        df = pd.concat(all_results, ignore_index=True)
        logger.info(
            f"Rolling features computed: {len(df)} rows "
            f"(windows={windows})"
        )
        return df

    # ===================================================================
    #  Pipeline Orchestrator
    # ===================================================================
    def run_pipeline(self):
        """
        全量特征工程 Pipeline (幂等, 可重跑).

        执行顺序:
          1. create tables
          2. shot_pace
          3. game_state_xg
          4. elo_ratings
          5. rest_days
          6. opp_adjusted_npxgd (依赖 elo)
          7. defensive_contribution
          8. merge -> int_match_features_extended
          9. rolling -> int_team_rolling_extended
        """
        logger.info("=" * 60)
        logger.info("Phase 2 Feature Engineering Pipeline START")
        logger.info("=" * 60)

        self.create_tables()

        shot_pace   = self._normalize_ids(self.compute_shot_pace())
        game_state  = self._normalize_ids(self.compute_game_state_xg())
        elo_df      = self._normalize_ids(self.compute_elo_ratings())
        rest_days   = self._normalize_ids(self.compute_rest_days())
        opp_adj     = self._normalize_ids(self.compute_opp_adjusted_npxgd(elo_df))
        def_contrib = self.compute_defensive_contribution()

        self._save_df(elo_df, "int_team_elo_history")
        self._save_df(def_contrib, "int_player_defensive_contrib")

        # --- 合并到 int_match_features_extended ---
        merged = shot_pace[["match_id", "team_id",
                            "shots_for", "shots_against", "shot_pace"]]

        if not game_state.empty:
            merged = merged.merge(
                game_state, on=["match_id", "team_id"], how="left"
            )

        merged = merged.merge(
            opp_adj[["match_id", "team_id", "match_npxgd",
                      "pre_match_elo", "opp_pre_match_elo", "opp_adj_npxgd"]],
            on=["match_id", "team_id"], how="left",
        )

        merged = merged.merge(
            rest_days[["match_id", "team_id", "rest_days", "rest_days_diff"]],
            on=["match_id", "team_id"], how="left",
        )

        self._save_df(merged, "int_match_features_extended")

        rolling = self.compute_rolling_features(merged)
        self._save_df(rolling, "int_team_rolling_extended")

        logger.info("=" * 60)
        logger.info("Phase 2 Feature Engineering Pipeline COMPLETE")
        logger.info(f"  int_match_features_extended: {len(merged)} rows")
        logger.info(f"  int_team_rolling_extended:    {len(rolling)} rows")
        logger.info(f"  int_team_elo_history:         {len(elo_df)} rows")
        logger.info(f"  int_player_defensive_contrib: {len(def_contrib)} rows")
        logger.info("=" * 60)

        return {
            "match_features": merged,
            "rolling_features": rolling,
            "elo_history": elo_df,
            "defensive_contrib": def_contrib,
        }

    @staticmethod
    def _normalize_ids(df: pd.DataFrame) -> pd.DataFrame:
        """统一 match_id/team_id 类型, 避免 merge 时 int vs str 报错"""
        if df.empty:
            return df
        if "match_id" in df.columns:
            df["match_id"] = df["match_id"].astype(str)
        if "team_id" in df.columns:
            df = df.dropna(subset=["team_id"]).copy()
            df["team_id"] = df["team_id"].astype(int)
        return df

    def _save_df(self, df: pd.DataFrame, table_name: str):
        """写入 SQLite (replace 模式, 幂等)"""
        _pk = {
            "int_match_features_extended": ["match_id", "team_id"],
            "int_team_rolling_features":   ["match_id", "team_id"],
            "int_team_rolling_extended":   ["match_id", "team_id", "window_size"],
        }
        if table_name in _pk:
            df = df.drop_duplicates(subset=_pk[table_name], keep="last")
        df.to_sql(table_name, self.conn, if_exists="replace", index=False)
        _idx = {
            "int_match_features_extended": ("uidx_ext_match_team", "match_id, team_id"),
            "int_team_rolling_features":   ("uidx_roll_match_team", "match_id, team_id"),
        }
        if table_name in _idx:
            iname, icols = _idx[table_name]
            try:
                self.conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {iname} ON {table_name}({icols})")
            except Exception:
                pass
        logger.info(f"  -> {table_name}: {len(df)} rows saved")

    def close(self):
        self.conn.close()
        logger.info("Connection closed.")


# -----------------------------------------------------------------------
#  Excel Demo Loader (用 demo xlsx 构建测试用 SQLite)
# -----------------------------------------------------------------------
def load_demo_to_sqlite(
    xlsx_path: str, db_path: str = "/home/claude/demo_football.db"
) -> str:
    """
    将 Excel demo 数据导入临时 SQLite, 用于验证 pipeline.
    """
    conn = sqlite3.connect(db_path)

    sheet_table_map = {
        "Match_Info":   "dim_match",
        "Team_Stats":   "fact_team_match_stats",
        "Player_Stats": "fact_player_match_stats",
        "Shot_Map":     "shot_map",
    }

    column_renames = {
        "Match_ID": "match_id", "Season": "season",
        "League_ID": "league_id", "Date": "match_time",
        "Home_Team_ID": "home_id", "Away_Team_ID": "away_id",
        "Home_Team_Name": "home_name", "Away_Team_Name": "away_name",
        "Match_Round": "match_round",
        "Team_ID": "team_id", "Period": "period",
        "Goals": "goals", "BallPossesion": "possession",
        "Player_ID": "player_id", "Minute": "minute",
        "X_Coord": "x_coord", "Y_Coord": "y_coord",
        "xG": "xg", "xGOT": "xgot",
        "Situation": "situation", "Outcome": "outcome",
    }

    for sheet_name, table_name in sheet_table_map.items():
        df = pd.read_excel(xlsx_path, sheet_name=sheet_name)
        df = df.rename(columns=column_renames)
        df.columns = [c.lower() if c not in column_renames.values() else c
                       for c in df.columns]

        if table_name == "dim_match":
            ts = pd.read_excel(xlsx_path, sheet_name="Team_Stats")
            ts = ts.rename(columns=column_renames)
            scores = ts[ts["period"] == "All"][["match_id", "team_id", "goals"]]
            for _, row in df.iterrows():
                mid = row["match_id"]
                h_g = scores[
                    (scores["match_id"] == mid)
                    & (scores["team_id"] == row["home_id"])
                ]["goals"].values
                a_g = scores[
                    (scores["match_id"] == mid)
                    & (scores["team_id"] == row["away_id"])
                ]["goals"].values
                df.loc[df["match_id"] == mid, "home_score"] = (
                    int(h_g[0]) if len(h_g) else 0
                )
                df.loc[df["match_id"] == mid, "away_score"] = (
                    int(a_g[0]) if len(a_g) else 0
                )
            df["status"] = "Finished"

        df.to_sql(table_name, conn, if_exists="replace", index=False)
        logger.info(f"Demo: {sheet_name} -> {table_name} ({len(df)} rows)")

    conn.commit()
    conn.close()
    return db_path


# -----------------------------------------------------------------------
#  Main: Demo 验证
# -----------------------------------------------------------------------
if __name__ == "__main__":
    import os as _os
    PROJECT_ROOT = _os.environ.get("PROJECT_ROOT", _os.path.dirname(_os.path.abspath(__file__)))
    DB_PATH = _os.environ.get("DB_PATH", _os.path.join(PROJECT_ROOT, "football_uk.db"))

    logger.info(f"Production mode: DB={DB_PATH}")
    fe = FeatureEngineer(DB_PATH)
    results = fe.run_pipeline()
    fe.close()
    logger.info("Done.")
