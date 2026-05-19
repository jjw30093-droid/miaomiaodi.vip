"""
update_odds_pick.py
===================
轻量级赔率刷新脚本（不重跑 Agent，不爬阵容）

使用场景：
  研报已生成后，赔率发生变化 → 只重算推荐方向 + 更新 inference → 推送 AWS

流程：
  1. 读取最新 odds/match_odds_data.json
  2. 对每场未开球的比赛，重算 ML 输出 + single_pick
  3. 更新本地 report_store.inference
  4. 推送 AWS（完整 payload 保留现有报告内容，只替换 inference）

用法：
  python3 update_odds_pick.py                    # 刷新所有未开球比赛
  python3 update_odds_pick.py 5205791 5205793    # 只刷新指定 match_id
"""

import os
import sys
import json
import sqlite3
import logging
from datetime import datetime, date

import pandas as pd

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

DB_PATH   = os.path.join(PROJECT_ROOT, "football_uk.db")
MODEL_DIR = os.path.join(PROJECT_ROOT, "models_v4")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

from generate_match_report import load_models, load_ah_predictor, get_team_features, build_feature_row
from run_tonight_reports import _select_single_pick, _get_reference_odds, _predict_bp
from ah_model import LAMBDA_FEATURES
from aws_pusher import push_match_payload


def _build_inference_str(sp: dict, wdl: dict) -> str:
    home_prob = round(wdl["home"] * 100, 1)
    draw_prob = round(wdl["draw"] * 100, 1)
    away_prob = round(wdl["away"] * 100, 1)
    # B6：前端不显示置信等级；SKIP 场景也强制给出推荐（内部分层仅后端可见）
    odds_str = f" @{sp['odds']}" if sp.get("odds") else ""
    prob_str = f"{round(sp.get('ml_prob', 0) * 100, 1)}%"
    out = f"{sp['label']}{odds_str} {prob_str}  ({home_prob}%/{draw_prob}%/{away_prob}%)"
    if sp.get("secondary"):
        s2 = sp["secondary"]
        o2 = f" @{s2['odds']}" if s2.get("odds") else ""
        p2 = f"{round(s2.get('ml_prob', 0) * 100, 1)}%"
        out += f"  +  {s2['label']}{o2} {p2}"
    return out


def refresh_pick_for_match(mid: str, m: dict, conn, model_wdl, model_ou,
                           FEATURES, odds_index: dict, today,
                           ah_predictor=None) -> bool:
    """
    对单场比赛重算 single_pick + 更新 report_store.inference + 推送 AWS。
    供 main() 和 poll_lineup.py 调用。
    返回 True 表示成功。
    """
    odds_data = odds_index.get(mid, {})
    eu = odds_data.get("european_1x2", {}).get("latest", {})
    eu_h = float(eu.get("home", 0) or 0)
    eu_d = float(eu.get("draw", 0) or 0)
    eu_a = float(eu.get("away", 0) or 0)

    try:
        h_feat = get_team_features(conn, m["home_id"], today)
        a_feat = get_team_features(conn, m["away_id"], today)

        is_cup = 1 if m.get("league_id", 0) in {42, 73, 10216, 132, 133, 134, 138, 141, 209} else 0
        ah     = odds_data.get("asian_handicap", {}).get("latest", {})
        ah_line = float(ah.get("line", 0) or 0)
        ah_home = float(ah.get("over_or_home", 0) or 0)
        ah_away = float(ah.get("under_or_away", 0) or 0)
        row    = build_feature_row(h_feat, a_feat, eu_h, eu_d, eu_a, is_cup=is_cup,
                                   ah_line=ah_line, ah_home=ah_home, ah_away=ah_away)
        X      = pd.DataFrame([row])[FEATURES].fillna(0)
        wdl_arr = model_wdl.predict(X)[0]
        ou_val  = float(model_ou.predict(X)[0])
    except Exception as e:
        log.error(f"  ❌ ML 推理失败: {e}")
        return False

    wdl_dict = {"home": float(wdl_arr[0]), "draw": float(wdl_arr[1]), "away": float(wdl_arr[2])}
    ou_dict  = {"over_25": ou_val, "under_25": 1.0 - ou_val}

    # AH 独立预测（Dixon-Coles + xG）
    ah_pred = None
    if ah_predictor and ah_line is not None:
        try:
            feat_row_ah = {c: (row.get(c, 0) if row.get(c) is not None else 0)
                           for c in LAMBDA_FEATURES}
            ah_features = pd.DataFrame([feat_row_ah])
            match_parts = m.get("match_name", "").split(" vs ", 1)
            home_name = match_parts[0].strip() if len(match_parts) == 2 else ""
            away_name = match_parts[1].strip() if len(match_parts) == 2 else ""
            ah_pred = ah_predictor.predict_match(
                home_name, away_name, ah_features, ah_line
            )
        except Exception as _e:
            log.warning(f"  AH 预测失败: {_e}")

    league_id   = int(m.get("league_id", 0) or 0)

    # C3.1: BP 融合（T-30 刷新路径同步启用）
    bp_pred = None
    try:
        match_parts = m.get("match_name", "").split(" vs ", 1)
        _hn = match_parts[0].strip() if len(match_parts) == 2 else ""
        _an = match_parts[1].strip() if len(match_parts) == 2 else ""
        ou_line_for_bp = float(odds_data.get("over_under", {}).get("latest", {}).get("line", 2.5) or 2.5)
        ah_line_for_bp = ah_line if ah_line is not None else 0.0
        bp_pred = _predict_bp(_hn, _an, ou_line=ou_line_for_bp, ah_line=ah_line_for_bp)
    except Exception as _e:
        log.debug(f"  BP 预测跳过: {_e}")

    single_pick = _select_single_pick(wdl_dict, ou_dict, odds_data, ah_pred=ah_pred,
                                      league_id=league_id, bp_pred=bp_pred)
    inference   = _build_inference_str(single_pick, wdl_dict)

    log.info(f"  → {inference}")

    # T-30 定稿同时覆盖 home/draw/away_prob，避免前端"AI 推荐栏 vs 概率三宫格数字对不上"
    # （前端 page.tsx 概率三宫格读 home_prob/draw_prob/away_prob，inference 由 final_lock 重写，
    #  若不同步刷新概率列，用户在 T-30 之后会看到推荐 68% 但三宫格仍 04:40 旧的 73% 的诡异组合）
    conn.execute(
        "UPDATE report_store SET inference = ?, home_prob = ?, draw_prob = ?, away_prob = ? WHERE match_id = ?",
        [inference, round(float(wdl_arr[0]) * 100, 1), round(float(wdl_arr[1]) * 100, 1), round(float(wdl_arr[2]) * 100, 1), mid],
    )
    conn.commit()

    # ── 同步更新 prediction_audit（用定稿预测覆盖初版）──
    try:
        from review_engine import ReviewEngine
        _rev = ReviewEngine(DB_PATH)
        _rev.update_prediction(mid, {
            'home_win': float(wdl_arr[0]),
            'draw':     float(wdl_arr[1]),
            'away_win': float(wdl_arr[2]),
        }, ou_val)
        # B2：T-30 定稿也覆盖写 picked_* 字段（推荐方向可能随赔率变化）
        _picks = [{
            "market":     (single_pick.get("market") or "").lower(),
            "direction":  single_pick.get("direction"),
            "odds":       single_pick.get("odds"),
            "confidence": single_pick.get("confidence"),
        }]
        if single_pick.get("secondary"):
            s = single_pick["secondary"]
            _picks.append({
                "market":     (s.get("market") or "").lower(),
                "direction":  s.get("direction"),
                "odds":       s.get("odds"),
                "confidence": s.get("confidence"),
            })
        _rev.record_picked(mid, _picks)
        _rev.close()
        log.info(f"  📝 prediction_audit 已更新为定稿预测（含 picked_*）")
    except Exception as e:
        log.warning(f"  ⚠️ prediction_audit 更新失败（不影响研报）: {e}")

    try:
        push_match_payload(mid)
        log.info(f"  📡 AWS 推送完成")
    except Exception as e:
        log.error(f"  ❌ AWS 推送失败: {e}")

    return True


def main(force_ids: list[str] | None = None):
    now = datetime.now()

    # ── 1. 加载赛程 + 赔率 ──
    schedule_path = os.path.join(PROJECT_ROOT, "schedule", "target_matches.json")
    odds_path     = os.path.join(PROJECT_ROOT, "odds", "match_odds_data.json")

    with open(schedule_path, encoding="utf-8") as f:
        matches = json.load(f)
    with open(odds_path, encoding="utf-8") as f:
        odds_raw = json.load(f)
    odds_index = {str(o["fotmob_id"]): o.get("odds", {}) for o in odds_raw}

    # ── 2. 加载 ML 模型（一次性）──
    log.info("⚙️  加载 ML 模型...")
    model_wdl, model_ou, FEATURES = load_models()
    ah_predictor = load_ah_predictor()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    today = date.today()

    updated = []

    for m in matches:
        mid = str(m["match_id"])

        # 指定 ID 模式
        if force_ids and mid not in force_ids:
            continue

        # 跳过已开球比赛
        kickoff = datetime.strptime(m["kickoff_time"], "%Y-%m-%d %H:%M:%S")
        if kickoff <= now:
            log.info(f"⏭️  跳过已开球: {m['match_name']} [{m['kickoff_time']}]")
            continue

        log.info(f"🔄  刷新: {m['match_name']}")
        ok = refresh_pick_for_match(mid, m, conn, model_wdl, model_ou, FEATURES, odds_index, today,
                                    ah_predictor=ah_predictor)
        if ok:
            updated.append(m["match_name"])

    conn.close()

    log.info(f"\n{'='*50}")
    log.info(f"✅ 共刷新 {len(updated)} 场推荐方向：")
    for name in updated:
        log.info(f"  - {name}")


if __name__ == "__main__":
    # 支持命令行传入指定 match_id 列表
    force = [str(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else None
    main(force_ids=force)
