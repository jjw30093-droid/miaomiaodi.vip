"""
review_engine.py
================
复盘引擎：预测闭环反馈系统
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from typing import Optional
import numpy as np

DDL_AUDIT = """
CREATE TABLE IF NOT EXISTS prediction_audit (
    match_id        TEXT    PRIMARY KEY,
    match_date      TEXT,
    home_name       TEXT,
    away_name       TEXT,
    pred_wdl_home   REAL,
    pred_wdl_draw   REAL,
    pred_wdl_away   REAL,
    pred_ou_over    REAL,
    pred_wdl_pick   TEXT,
    pred_ou_pick    TEXT,
    confidence_wdl  TEXT,
    confidence_ou   TEXT,
    shap_wdl_top1   TEXT,
    shap_ou_top1    TEXT,
    -- Phase 2 Pillar C 新增字段
    pred_ou_line        REAL,    -- 预测时的大小球线（如 3.5）
    pred_ah_pick        TEXT,    -- 亚盘方向 'home'|'away'
    pred_ah_line        REAL,    -- 亚盘让球数（如 -0.25）
    prob_sanity_flag    TEXT,    -- NULL | 'EXTREME'
    actual_ou_line_used REAL,    -- 审计时实际使用的 line（留痕）
    -- Part B 单推审计字段（2026-04 新增）
    picked_market       TEXT,    -- 'wdl' | 'ou' | 'ah'
    picked_direction    TEXT,    -- 'home_win'|'draw'|'away_win'|'over'|'under'|'ah_home'|'ah_away'  (CLAUDE.md §18)
    picked_odds         REAL,    -- 推荐方向的实际赔率
    picked_confidence   TEXT,    -- 'HIGH'|'MID'|'LOW'|'SKIP'（仅后端可见，不暴露 UI）
    picked_correct      INT,     -- 1=赢 / 0=输 / -1=走水 / NULL=未结算或数据缺失
    actual_home_score   INT,
    actual_away_score   INT,
    actual_wdl      TEXT,
    actual_ou       TEXT,
    wdl_correct     INT,
    ou_correct      INT,
    brier_wdl       REAL,
    brier_ou        REAL,
    audit_time      TEXT
);

CREATE TABLE IF NOT EXISTS model_health_log (
    log_date            TEXT    PRIMARY KEY,
    window_size         INT,
    wdl_accuracy        REAL,
    ou_accuracy          REAL,
    wdl_brier_avg       REAL,
    ou_brier_avg        REAL,
    high_conf_wdl_acc   REAL,
    total_matches       INT,
    drift_alert         INT,
    retrain_triggered   INT
);
"""

class ReviewEngine:
    # 漂移阈值（2026-05-04 收紧 + 加 AH）
    # 旧值 38/50/0.75 在 5/2 实测 WDL=40% OU=51% Brier=0.233 全擦边过关，永远不触发。
    # 新值贴近"硬币基线 + 2pp"——任何市场跌至接近随机就报警。
    WDL_ACC_THRESHOLD = 0.42  # 38% → 42%
    OU_ACC_THRESHOLD  = 0.48  # 50% → 48%（OU 是 binary，硬币 50%）
    AH_ACC_THRESHOLD  = 0.42  # 新增（AH binary，但有半胜半负稀释，留 8pp 空间）
    BRIER_WDL_THRESHOLD = 0.75
    ROLLING_WINDOW = 50
    RETRAIN_COOLDOWN_DAYS = 14
    AUTO_RECALIB_ON_DRIFT = True  # 漂移触发后是否自动调 recalibrate

    def __init__(self, db_path: str, model_dir: str = './models'):
        self.db_path, self.model_dir = db_path, model_dir
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript(DDL_AUDIT)
        # Part B 单推审计字段 —— 幂等 ALTER（旧库升级路径）
        _picked_cols = [
            ("picked_market",     "TEXT"),
            ("picked_direction",  "TEXT"),
            ("picked_odds",       "REAL"),
            ("picked_confidence", "TEXT"),
            ("picked_correct",    "INT"),
            ("ah_correct",        "INT"),   # audit_match 已写但旧库可能缺列
        ]
        for col, typ in _picked_cols:
            try:
                self.conn.execute(f"ALTER TABLE prediction_audit ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError:
                pass  # 已存在
        self.conn.commit()

    def record_picked(self, match_id: str, picks):
        """Part B: 写入单推/双推审计字段。

        picks: 单个 dict 或 list[dict]。每个 pick 至少包含:
               {market, direction, odds, confidence, label}
        策略：只覆盖 primary pick（picks[0]）到 prediction_audit 行；
              若有 picks[1]（双推），写入侧表 prediction_audit_extra_pick。
        """
        if picks is None:
            return
        if isinstance(picks, dict):
            picks = [picks]
        if not picks:
            return

        primary = picks[0]
        market    = primary.get("market")
        direction = primary.get("direction")
        odds      = primary.get("odds")
        conf      = primary.get("confidence")
        # 2026-05-04: ah_source 透传（v5_lambda / None）；非 AH 推荐留 None
        ah_source = primary.get("ah_source") if (market or "").lower() == "ah" else None
        # 2026-05-04 增补 #3: ou_source 透传；非 OU 推荐留 None
        ou_source = primary.get("ou_source") if (market or "").lower() == "ou" else None

        cur = self.conn.cursor()
        # 行必须已存在（log_prediction 之后调用）
        exists = cur.execute("SELECT 1 FROM prediction_audit WHERE match_id=?",
                             (match_id,)).fetchone()
        if not exists:
            # 兜底：即使没有 log_prediction 也插入一行，含队名（从 dim_match 查）
            dm = cur.execute(
                "SELECT Date, Home_Team_Name, Away_Team_Name FROM dim_match WHERE Match_ID=?",
                (match_id,)
            ).fetchone()
            fallback_date = dm['Date'] if dm else datetime.now().strftime('%Y-%m-%d')
            fallback_home = dm['Home_Team_Name'] if dm else None
            fallback_away = dm['Away_Team_Name'] if dm else None
            cur.execute("""INSERT OR IGNORE INTO prediction_audit
                           (match_id, match_date, home_name, away_name)
                           VALUES (?, ?, ?, ?)""",
                        (match_id, fallback_date, fallback_home, fallback_away))

        cur.execute("""
            UPDATE prediction_audit SET
                picked_market=?, picked_direction=?, picked_odds=?, picked_confidence=?,
                ah_source=?, ou_source=?
            WHERE match_id=?
        """, (market, direction, odds, conf, ah_source, ou_source, match_id))

        # 双推：写侧表
        if len(picks) >= 2:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS prediction_audit_extra_pick (
                    match_id          TEXT,
                    picked_market     TEXT,
                    picked_direction  TEXT,
                    picked_odds       REAL,
                    picked_confidence TEXT,
                    picked_correct    INT,
                    PRIMARY KEY (match_id, picked_market)
                )
            """)
            sec = picks[1]
            cur.execute("""
                INSERT OR REPLACE INTO prediction_audit_extra_pick
                (match_id, picked_market, picked_direction, picked_odds, picked_confidence)
                VALUES (?,?,?,?,?)
            """, (match_id, sec.get("market"), sec.get("direction"),
                  sec.get("odds"), sec.get("confidence")))
        self.conn.commit()

    def log_prediction(self, match_id: str, ml_output: dict,
                       match_date: str = None, home_name: str = None, away_name: str = None,
                       ou_line: float = None, ah_pick: str = None, ah_line: float = None,
                       picks: list = None, ah_pred_v5: dict = None, ah_line_v5: float = None):
        """记录赛前预测到 prediction_audit 表。

        优先使用显式传入的 match_date/home_name/away_name（赛前 dim_match 尚无记录时），
        兜底查 dim_match（赛后补录场景）。

        Phase 2 新增参数：
          ou_line  : 大小球线（如 3.5）—— 写入后 audit_match 用它而非硬编码 2.5
          ah_pick  : 亚盘推荐方向 'home'|'away'
          ah_line  : 亚盘让球数（如 -0.25）

        picks (CLAUDE.md §16 不变量):
          list[dict] 形如 [{"market","direction","odds","confidence"}, ...]
          若非 None，在同一事务内一并写入 picked_market / picked_direction /
          picked_odds / picked_confidence，避免与 record_picked 双写产生间隙。
          picks[1:] 写入侧表 prediction_audit_extra_pick（双推支持）。
        """
        cur = self.conn.cursor()

        # 优先用传入参数，兜底查 dim_match
        if not (match_date and home_name and away_name):
            match = cur.execute("SELECT * FROM dim_match WHERE Match_ID=?", (match_id,)).fetchone()
            if not match:
                return  # 既没传参也没 dim_match 记录，无法记录
            match_date = match_date or match['Date']
            home_name  = home_name  or match['Home_Team_Name']
            away_name  = away_name  or match['Away_Team_Name']

        wdl, ou, conf = ml_output['wdl_prob'], ml_output['ou_prob'], ml_output['confidence']
        shap_wdl = ml_output.get('shap_wdl', [])
        shap_ou = ml_output.get('shap_ou', [])
        pred_wdl_pick = max(wdl, key=wdl.get)
        pred_ou_pick = 'over' if ou['over'] > 0.5 else 'under'

        # Sanity flag：概率极端值预警
        ou_over_val = ou['over']
        sanity_flag = None
        if ou_over_val >= 0.95 or ou_over_val <= 0.05:
            sanity_flag = 'EXTREME'

        # 2026-05-18: v5 Lambda AH 概率序列化
        # pred_ah_pick_v5 存方向 'home'/'away'，pred_ah_cover_v5 存最佳方向覆盖概率
        # pred_ah_line_v5 存 Lambda 推理时传入的盘口（即 ah_line_v5 参数）
        pred_ah_pick_v5_val  = None
        pred_ah_cover_v5_val = None
        if ah_pred_v5 and isinstance(ah_pred_v5, dict):
            _cover = float(ah_pred_v5.get('ah_cover', 0) or 0)
            _away  = float(ah_pred_v5.get('ah_away_cover', 0) or 0)
            if _cover > 0 or _away > 0:  # 至少一个非零，避免无效数据写入
                pred_ah_pick_v5_val  = 'home' if _cover >= _away else 'away'
                pred_ah_cover_v5_val = round(max(_cover, _away), 4)

        # INSERT OR IGNORE so existing picked_market/direction/confidence (set by record_picked
        # in Phase 1) are NOT wiped. Then UPDATE only the ML prediction columns.
        cur.execute("""
            INSERT OR IGNORE INTO prediction_audit (match_id, match_date, home_name, away_name)
            VALUES (?,?,?,?)
        """, (match_id, match_date, home_name, away_name))
        cur.execute("""
            UPDATE prediction_audit SET
                match_date        = ?,
                home_name         = ?,
                away_name         = ?,
                pred_wdl_home     = ?,
                pred_wdl_draw     = ?,
                pred_wdl_away     = ?,
                pred_ou_over      = ?,
                pred_wdl_pick     = ?,
                pred_ou_pick      = ?,
                confidence_wdl    = ?,
                confidence_ou     = ?,
                shap_wdl_top1     = ?,
                shap_ou_top1      = ?,
                pred_ou_line      = ?,
                pred_ah_pick      = ?,
                pred_ah_line      = ?,
                prob_sanity_flag  = ?,
                pred_ah_pick_v5   = ?,
                pred_ah_line_v5   = ?,
                pred_ah_cover_v5  = ?
            WHERE match_id = ?
        """, (
            match_date,
            home_name,
            away_name,
            wdl['home_win'], wdl['draw'], wdl['away_win'],
            ou_over_val, pred_wdl_pick, pred_ou_pick,
            conf['wdl'], conf['ou'],
            (shap_wdl[0].get('feature_cn') or shap_wdl[0].get('feature', '')) if shap_wdl else '',
            (shap_ou[0].get('feature_cn') or shap_ou[0].get('feature', '')) if shap_ou else '',
            ou_line, ah_pick, ah_line, sanity_flag,
            pred_ah_pick_v5_val, ah_line_v5, pred_ah_cover_v5_val,
            match_id,
        ))

        # CLAUDE.md §16: 同事务内一并写 picks，杜绝 Phase 1/2 间隙
        if picks:
            primary = picks[0] if isinstance(picks, list) else picks
            if isinstance(primary, dict) and primary.get("market"):
                cur.execute("""
                    UPDATE prediction_audit SET
                        picked_market    = ?,
                        picked_direction = ?,
                        picked_odds      = ?,
                        picked_confidence= ?
                    WHERE match_id = ?
                """, (
                    (primary.get("market") or "").lower() or None,
                    primary.get("direction"),
                    primary.get("odds"),
                    primary.get("confidence"),
                    match_id,
                ))
            # 双推：写侧表（与 record_picked 同结构）
            if isinstance(picks, list) and len(picks) >= 2 and isinstance(picks[1], dict):
                sec = picks[1]
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS prediction_audit_extra_pick (
                        match_id          TEXT,
                        picked_market     TEXT,
                        picked_direction  TEXT,
                        picked_odds       REAL,
                        picked_confidence TEXT,
                        picked_correct    INT,
                        PRIMARY KEY (match_id, picked_market)
                    )
                """)
                cur.execute("""
                    INSERT OR REPLACE INTO prediction_audit_extra_pick
                    (match_id, picked_market, picked_direction, picked_odds, picked_confidence)
                    VALUES (?,?,?,?,?)
                """, (match_id, (sec.get("market") or "").lower() or None,
                      sec.get("direction"), sec.get("odds"), sec.get("confidence")))

        self.conn.commit()

    def save_final_odds(self, match_id: str, eu_h: float, eu_d: float, eu_a: float):
        """T-10 定稿时保存临场赔率（仅记录，不覆盖预测概率）。"""
        cur = self.conn.cursor()
        existing = cur.execute("SELECT 1 FROM prediction_audit WHERE match_id=?", (match_id,)).fetchone()
        if not existing:
            return  # 没有初始预测记录，无法附加赔率
        # 用一个独立字段或备注字段记录定稿赔率（如果后续需要可扩展表结构）
        # 当前最小改动：在 shap_ou_top1 末尾追加定稿赔率标记（不影响审计逻辑）
        cur.execute("""
            UPDATE prediction_audit SET
                shap_ou_top1 = COALESCE(shap_ou_top1, '') || ' [final_odds:' || ? || '/' || ? || '/' || ? || ']'
            WHERE match_id=? AND actual_wdl IS NULL
        """, (eu_h, eu_d, eu_a, match_id))
        self.conn.commit()

    def update_prediction(self, match_id: str, wdl_probs: dict, ou_over: float):
        """定稿时用最新模型输出覆盖 prediction_audit 中的概率和推荐方向。

        仅更新尚未审计（actual_wdl IS NULL）的记录，防止覆盖已有结果。
        """
        cur = self.conn.cursor()
        pred_wdl_pick = max(wdl_probs, key=wdl_probs.get)
        pred_ou_pick = 'over' if ou_over > 0.5 else 'under'
        conf_val = max(wdl_probs.values())
        conf = 'HIGH' if conf_val > 0.6 else ('MID' if conf_val > 0.45 else 'LOW')

        cur.execute("""
            UPDATE prediction_audit SET
                pred_wdl_home=?, pred_wdl_draw=?, pred_wdl_away=?,
                pred_ou_over=?, pred_wdl_pick=?, pred_ou_pick=?,
                confidence_wdl=?
            WHERE match_id=? AND actual_wdl IS NULL
        """, (
            wdl_probs.get('home_win', 0), wdl_probs.get('draw', 0), wdl_probs.get('away_win', 0),
            ou_over, pred_wdl_pick, pred_ou_pick, conf,
            match_id
        ))
        self.conn.commit()

    def audit_match(self, match_id: str):
        cur = self.conn.cursor()
        match = cur.execute("SELECT home_score, away_score FROM dim_match WHERE Match_ID=?", (match_id,)).fetchone()
        if not match or match['home_score'] is None: return

        hs, as_ = match['home_score'], match['away_score']
        actual_wdl = 'home_win' if hs > as_ else ('draw' if hs == as_ else 'away_win')

        pred = cur.execute("SELECT * FROM prediction_audit WHERE match_id=?", (match_id,)).fetchone()
        if not pred: return

        # ★ Phase 2 Pillar C 修复：动态 line，不再硬编码 2.5
        # 读取赛前记录的 pred_ou_line；如果为 NULL（旧行）则降级到 2.5 并留痕
        try:
            stored_line = pred['pred_ou_line']
        except IndexError:
            stored_line = None  # 旧表结构，列不存在
        used_line = stored_line if stored_line is not None else 2.5

        total_goals = hs + as_
        if total_goals > used_line:
            actual_ou = 'over'
        elif total_goals < used_line:
            actual_ou = 'under'
        else:
            actual_ou = 'push'  # 整数线且总进球 = line（如平局 3-0 vs 线 3.0）

        wdl_correct = 1 if pred['pred_wdl_pick'] == actual_wdl else 0
        # push 场景：ou_correct / brier_ou 记为 NULL，排除出 drift 计算
        ou_correct  = None if actual_ou == 'push' else (1 if pred['pred_ou_pick'] == actual_ou else 0)

        # Brier Score
        actual_vec = [
            1.0 if actual_wdl == 'home_win' else 0.0,
            1.0 if actual_wdl == 'draw'     else 0.0,
            1.0 if actual_wdl == 'away_win' else 0.0,
        ]
        pred_vec  = [pred['pred_wdl_home'], pred['pred_wdl_draw'], pred['pred_wdl_away']]

        # 若 prediction_audit 里预测向量缺失（崩溃遗留的占位行），跳过 brier，置 NULL
        if any(p is None for p in pred_vec):
            brier_wdl = None
            wdl_correct = None
        else:
            brier_wdl = sum((p - a) ** 2 for p, a in zip(pred_vec, actual_vec)) / 3

        # OU 同理：pred_ou_over 缺失则跳过
        if actual_ou == 'push' or pred['pred_ou_over'] is None:
            brier_ou = None
            ou_correct = None if actual_ou == 'push' else None
        else:
            brier_ou = (pred['pred_ou_over'] - (1.0 if actual_ou == 'over' else 0.0)) ** 2

        # AH correct — compute if pred_ah_pick and pred_ah_line are present
        ah_correct = None
        try:
            ah_pick = pred['pred_ah_pick']
            ah_line = pred['pred_ah_line']
            if ah_pick is not None and ah_line is not None:
                adj = hs - as_ - ah_line
                if adj > 0:
                    home_wins = 1
                elif adj < 0:
                    home_wins = 0
                else:
                    home_wins = None  # push → -1
                if home_wins is None:
                    ah_correct = -1  # push/void
                else:
                    ah_correct = 1 if (ah_pick == 'home' and home_wins == 1) or \
                                      (ah_pick == 'away' and home_wins == 0) else 0
        except (IndexError, TypeError, KeyError):
            pass

        # ── Part B: 计算 picked_correct（单推命中与否）──
        picked_correct = None
        try:
            picked_market    = pred['picked_market']
            picked_direction = pred['picked_direction']
        except (IndexError, KeyError):
            picked_market = picked_direction = None

        if picked_market and picked_direction:
            # CLAUDE.md §18：统一走共享 compute_picked_correct（双形式容错 + 未知值 ERROR）
            from pick_parser import compute_picked_correct
            try:
                aline = pred['pred_ah_line']
            except (IndexError, KeyError):
                aline = None
            try:
                oline = pred['pred_ou_line']
            except (IndexError, KeyError):
                oline = used_line
            picked_correct = compute_picked_correct(
                picked_market, picked_direction, hs, as_, aline, oline,
            )

        # SKIP 置信度同样计入结果（2026-04-27：低置信推荐也需要追踪命中与否）

        cur.execute("""
            UPDATE prediction_audit SET
                actual_home_score=?, actual_away_score=?,
                actual_wdl=?, actual_ou=?,
                wdl_correct=?, ou_correct=?,
                brier_wdl=?, brier_ou=?,
                actual_ou_line_used=?,
                ah_correct=?,
                picked_correct=?,
                audit_time=?
            WHERE match_id=?
        """, (
            hs, as_, actual_wdl, actual_ou,
            wdl_correct, ou_correct,
            round(brier_wdl, 4) if brier_wdl is not None else None,
            round(brier_ou, 4) if brier_ou is not None else None,
            used_line,
            ah_correct,
            picked_correct,
            datetime.now().isoformat(),
            match_id,
        ))
        self.conn.commit()

    def check_drift(self) -> dict:
        cur = self.conn.cursor()
        recent = cur.execute(
            f"""
            SELECT *
            FROM prediction_audit
            WHERE actual_wdl IS NOT NULL
            ORDER BY match_date DESC
            LIMIT {self.ROLLING_WINDOW}
            """
        ).fetchall()
        if len(recent) < 20: return {'status': 'insufficient_data', 'n': len(recent)}

        # None guard：占位行/异常行会把 wdl_correct/brier 置为 NULL；这些不应进入漂移计算
        wdl_vals = [r['wdl_correct'] for r in recent if r['wdl_correct'] is not None]
        wdl_acc = (sum(wdl_vals) / len(wdl_vals)) if wdl_vals else None

        # OU accuracy：排除 push 行（ou_correct=NULL）
        ou_rows = [r for r in recent if r['ou_correct'] is not None]
        ou_vals = [r['ou_correct'] for r in ou_rows if r['ou_correct'] is not None]
        ou_acc  = (sum(ou_vals) / len(ou_vals)) if ou_vals else None

        brier_vals = [r['brier_wdl'] for r in recent if r['brier_wdl'] is not None]
        brier_wdl = (sum(brier_vals) / len(brier_vals)) if brier_vals else None

        # AH accuracy（2026-05-04 新增）：从 picked_correct WHERE picked_market='ah' 取
        # 不能用 ah_correct——它对所有有 AH 预测的比赛都填值，包括没被 picked 的；
        # 用 picked_correct 才能反映"实际推荐给用户的 AH"命中率。
        ah_rows = [r for r in recent if r['picked_market'] == 'ah'
                   and r['picked_correct'] is not None]
        # picked_correct ∈ {0, 1, -1(半负)}；半负计 0.25 命中（保守），全胜 1，全负 0
        # CLAUDE.md §16：picked_correct 通常 0/1，AH 半胜半负是边缘情况
        def _ah_score(v):
            if v == 1: return 1.0
            if v == -1: return 0.25  # 半负退一半
            return 0.0
        ah_acc = (sum(_ah_score(r['picked_correct']) for r in ah_rows) / len(ah_rows)) \
                 if ah_rows else None

        drift = (
            (wdl_acc is not None and wdl_acc < self.WDL_ACC_THRESHOLD) or
            (ou_acc is not None and ou_acc < self.OU_ACC_THRESHOLD) or
            (ah_acc is not None and len(ah_rows) >= 10 and ah_acc < self.AH_ACC_THRESHOLD) or
            (brier_wdl is not None and brier_wdl > self.BRIER_WDL_THRESHOLD)
        )

        cur.execute("INSERT OR REPLACE INTO model_health_log (log_date, window_size, wdl_accuracy, ou_accuracy, wdl_brier_avg, total_matches, drift_alert) VALUES (?,?,?,?,?,?,?)",
                    (datetime.now().strftime('%Y-%m-%d'), len(recent), wdl_acc, ou_acc, brier_wdl, len(recent), 1 if drift else 0))
        self.conn.commit()

        # 漂移触发后真动作：subprocess 调 recalibrate（2026-05-04 新增）
        # 之前只写日志、打印"建议考虑重新训练"——是文档不是行动
        if drift and self.AUTO_RECALIB_ON_DRIFT:
            self._auto_recalibrate(wdl_acc, ou_acc, ah_acc, brier_wdl)

        return {'drift': drift, 'wdl_acc': wdl_acc, 'ou_acc': ou_acc,
                'ah_acc': ah_acc, 'ah_n': len(ah_rows),
                'brier_wdl': brier_wdl, 'n': len(recent)}

    def _auto_recalibrate(self, wdl_acc, ou_acc, ah_acc, brier_wdl):
        """漂移触发后立即调 recalibrate 子进程，并写 model_drift_log（Phase 2: 不再污染 ingest_failure_log）。"""
        import os, sys, subprocess

        # ── 1. spawn recalibrate 子进程 ───────────────────────────────────
        pid: int | None = None
        try:
            backend_dir = os.path.dirname(os.path.abspath(__file__))
            proc = subprocess.Popen(
                [sys.executable, "-m", "recalibrate"],
                cwd=backend_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            pid = proc.pid
        except Exception as e:
            print(f"[review_engine] auto-recalibrate spawn failed: {e}")

        # ── 2. 写 model_drift_log + 推 Server 酱（取代旧的 record_failure）─
        try:
            # 判断哪些指标触发
            triggered: list[str] = []
            if wdl_acc is not None and wdl_acc < self.WDL_ACC_THRESHOLD:
                triggered.append("WDL")
            if ou_acc is not None and ou_acc < self.OU_ACC_THRESHOLD:
                triggered.append("OU")
            if ah_acc is not None and ah_acc < self.AH_ACC_THRESHOLD:
                triggered.append("AH")
            if brier_wdl is not None and brier_wdl > self.BRIER_WDL_THRESHOLD:
                triggered.append("Brier")

            # 当前使用的模型版本（保守：从最近 prediction_audit 行推断）
            try:
                cur = self.conn.cursor()
                row = cur.execute(
                    "SELECT model_version_active FROM prediction_audit "
                    "ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
                mv = row["model_version_active"] or "v5" if row else "unknown"
            except Exception:
                mv = "unknown"

            from drift_notifier import record_drift_event
            record_drift_event(
                model_version=mv,
                wdl_acc=wdl_acc,
                ou_acc=ou_acc if ou_acc is not None else 0.0,
                ah_acc=ah_acc if ah_acc is not None else 0.0,
                brier=brier_wdl,
                window_size=self.ROLLING_WINDOW,
                triggered_metrics=triggered,
                recalibrate_pid=pid,
                status="spawned" if pid else "spawn_failed",
            )
        except Exception as e:
            print(f"[review_engine] drift_notifier failed: {e}")

    def close(self): self.conn.close()
