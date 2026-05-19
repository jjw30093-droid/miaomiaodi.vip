#!/usr/bin/env python3
"""
scripts/shadow_cup_wdl_v5.py
============================
V5 Lambda WDL Shadow for Cup/Euro Matches (Phase A: UCL/UEL)

流程：
  1. 读 schedule/target_matches.json → 过滤出今日杯赛/欧战场次
  2. 读 mart_prediction_matrix_v5 取特征行
  3. CORE_FEATURES 完整性检查：任一 NULL → 跳过，写 skip log
  4. CatBoost Ensemble → λ_h / λ_a → build_score_matrix → derive_wdl
  5. max_p ≥ MAX_P_THRESHOLD → 写 shadow_cup_wdl_recs（幂等）

用法：
    python3 scripts/shadow_cup_wdl_v5.py                # production
    python3 scripts/shadow_cup_wdl_v5.py --dry-run      # print only, no writes
    python3 scripts/shadow_cup_wdl_v5.py --leagues 42 73 141
    python3 scripts/shadow_cup_wdl_v5.py --date 2026-05-07 --dry-run

Column name mapping (mart_prediction_matrix_v5 actual names vs user spec):
    diff_roll5_shots_on_target  → diff_roll5_ShotsOnTarget  (camelCase in DB)
    diff_pi_off                 → pi_home_attack_adv        (offensive PI proxy)
    diff_pi_def                 → pi_net_advantage          (net advantage proxy)
    diff_elo                    → elo_diff                  (Elo differential)

CLAUDE.md refs:
    §3  唯一生产库 = football_uk.db
    §15 cron 05:15 UTC（job-run-tonight 04:40 之后）
    §18 predicted_outcome 短形式 H/D/A（shadow 专用，不进 prediction_audit）
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

# ─── Path setup ─────────────────────────────────────────────────────────────
PROJECT_ROOT = os.environ.get(
    "PROJECT_ROOT", str(Path(__file__).resolve().parent.parent)
)
DB_PATH = os.environ.get("DB_PATH", os.path.join(PROJECT_ROOT, "football_uk.db"))
MODEL_DIR = os.path.join(PROJECT_ROOT, "models_v5_lambda")
SCHEDULE_FILE = os.path.join(PROJECT_ROOT, "schedule", "target_matches.json")
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ─── Config ─────────────────────────────────────────────────────────────────

# Phase A: UCL (42) + UEL (73) only.
# expand to include domestic cups in Phase B after acc validation.
PHASE_A_LIDS: frozenset[int] = frozenset({42, 73})
ALL_CUP_LIDS: frozenset[int] = frozenset({42, 73, 10216, 132, 133, 134, 138, 141, 209})

# Configurable via env var or --min-max-p arg
MAX_P_THRESHOLD: float = float(os.environ.get("MAX_P_THRESHOLD", "0.50"))

MODEL_VERSION = "v5_lambda_wdl"  # Lambda CatBoost (not LightGBM; named for clarity)
ENSEMBLE_FULL = 0.6
ENSEMBLE_PURE = 0.4

# Core features required to be non-null; any null → skip match.
# Actual column names in mart_prediction_matrix_v5 (with mapping notes from spec):
CORE_FEATURES: list[str] = [
    "diff_roll5_expected_goals",    # spec: diff_roll5_expected_goals ✓
    "diff_roll5_ShotsOnTarget",     # spec: diff_roll5_shots_on_target (camelCase fix)
    "pi_home_attack_adv",           # spec: diff_pi_off (offensive PI proxy)
    "pi_net_advantage",             # spec: diff_pi_def (net advantage proxy)
    "elo_diff",                     # spec: diff_elo (name fix)
]


# ─── Model loading ──────────────────────────────────────────────────────────

def load_lambda_models() -> tuple:
    """Load 4 CatBoost models + rho.json from models_v5_lambda/.

    Returns (models_dict, feat_full, feat_pure, rho_dict).
    """
    try:
        from catboost import CatBoostRegressor
    except ImportError as e:
        log.error(f"catboost not installed: {e}")
        sys.exit(1)

    from v5_feature_engineering.inference_lambda import build_score_matrix, derive_wdl

    models: dict = {}
    for key, fname in [
        ("H_Full", "Model_H_Full.cbm"),
        ("H_Pure", "Model_H_Pure.cbm"),
        ("A_Full", "Model_A_Full.cbm"),
        ("A_Pure", "Model_A_Pure.cbm"),
    ]:
        path = os.path.join(MODEL_DIR, fname)
        if not os.path.exists(path):
            log.error(f"Model file missing: {path}")
            sys.exit(1)
        m = CatBoostRegressor()
        m.load_model(path)
        models[key] = m
        log.info(f"  Loaded {key} from {fname}")

    rho_path = os.path.join(MODEL_DIR, "rho.json")
    with open(rho_path) as f:
        rho_data = json.load(f)

    feat_full = list(models["H_Full"].feature_names_)
    feat_pure = list(models["H_Pure"].feature_names_)
    log.info(
        f"Models loaded. feat_full={len(feat_full)}, feat_pure={len(feat_pure)}, "
        f"rho_global={rho_data.get('rho_global', 0.0):.4f}"
    )
    return models, feat_full, feat_pure, rho_data


# ─── Feature loading ─────────────────────────────────────────────────────────

def load_features(match_id: int, conn: sqlite3.Connection):
    """Read feature row from mart_prediction_matrix_v5 for a given match_id.

    Returns DataFrame (1 row) or None if not found.
    """
    import pandas as pd

    df = pd.read_sql(
        "SELECT * FROM mart_prediction_matrix_v5 WHERE match_id = ? LIMIT 1",
        conn,
        params=(int(match_id),),
    )
    return df if not df.empty else None


def check_core_features(df, match_id: int) -> tuple[int, list[str]]:
    """Check CORE_FEATURES for nulls.

    Returns (score, missing_list).
    score = number of non-null core features (0–5).
    missing_list = list of null feature names.
    """
    missing = []
    for col in CORE_FEATURES:
        if col not in df.columns or df[col].isna().any():
            missing.append(col)
    score = len(CORE_FEATURES) - len(missing)
    return score, missing


# ─── Inference ───────────────────────────────────────────────────────────────

def run_inference(
    df,
    models: dict,
    feat_full: list,
    feat_pure: list,
    rho_data: dict,
    league_id: int,
) -> Optional[tuple[float, float, float, float, float, float]]:
    """Run V5 Lambda WDL inference on a feature row.

    Returns (p_home, p_draw, p_away, lam_h, lam_a, rho) or None on error.
    """
    import numpy as np
    from v5_feature_engineering.inference_lambda import build_score_matrix, derive_wdl

    try:
        import pandas as pd
        X_fh = df.reindex(columns=feat_full, fill_value=0)
        X_ph = df.reindex(columns=feat_pure, fill_value=0)

        # League_ID float bug防御 (P0.9 Bug 2 fix)
        for X in [X_fh, X_ph]:
            if "League_ID" in X.columns:
                X["League_ID"] = X["League_ID"].fillna(0).astype(int)

        lam_h_full = float(models["H_Full"].predict(X_fh)[0])
        lam_a_full = float(models["A_Full"].predict(X_fh)[0])
        lam_h_pure = float(models["H_Pure"].predict(X_ph)[0])
        lam_a_pure = float(models["A_Pure"].predict(X_ph)[0])
    except Exception as e:
        log.warning(f"CatBoost predict failed: {e}")
        return None

    lam_h = ENSEMBLE_FULL * lam_h_full + ENSEMBLE_PURE * lam_h_pure
    lam_a = ENSEMBLE_FULL * lam_a_full + ENSEMBLE_PURE * lam_a_pure

    # ρ: league-level first, then global fallback (cup leagues not in rho_by_league)
    rho_by_league = rho_data.get("rho_by_league", {})
    rho = rho_by_league.get(str(int(league_id)), rho_data.get("rho_global", 0.0))

    try:
        matrix = build_score_matrix(lam_h, lam_a, rho=rho, max_goals=10)
        p_home, p_draw, p_away = derive_wdl(matrix)
    except Exception as e:
        log.warning(f"derive_wdl failed: {e}")
        return None

    # Sanity checks
    for name, v in [("p_home", p_home), ("p_draw", p_draw), ("p_away", p_away)]:
        if v != v or not (0.0 <= v <= 1.001):
            log.warning(f"Invalid prob {name}={v}")
            return None

    return p_home, p_draw, p_away, lam_h, lam_a, rho


# ─── DB helpers ──────────────────────────────────────────────────────────────

CREATE_RECS_TABLE = """
CREATE TABLE IF NOT EXISTS shadow_cup_wdl_recs (
    match_id                   INTEGER PRIMARY KEY,
    league_id                  INTEGER,
    match_date                 TEXT,
    home_team_id               INTEGER,
    away_team_id               INTEGER,
    predicted_outcome          TEXT,   -- 'H' / 'D' / 'A'
    p_home                     REAL,
    p_draw                     REAL,
    p_away                     REAL,
    max_p                      REAL,
    model_version              TEXT,
    feature_completeness_score INTEGER,
    created_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_IDX_DATE = "CREATE INDEX IF NOT EXISTS idx_scwr_date   ON shadow_cup_wdl_recs(match_date);"
CREATE_IDX_LID  = "CREATE INDEX IF NOT EXISTS idx_scwr_league ON shadow_cup_wdl_recs(league_id);"

UPSERT_SQL = """
INSERT INTO shadow_cup_wdl_recs
    (match_id, league_id, match_date, home_team_id, away_team_id,
     predicted_outcome, p_home, p_draw, p_away, max_p,
     model_version, feature_completeness_score)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(match_id) DO UPDATE SET
    league_id                  = excluded.league_id,
    match_date                 = excluded.match_date,
    home_team_id               = excluded.home_team_id,
    away_team_id               = excluded.away_team_id,
    predicted_outcome          = excluded.predicted_outcome,
    p_home                     = excluded.p_home,
    p_draw                     = excluded.p_draw,
    p_away                     = excluded.p_away,
    max_p                      = excluded.max_p,
    model_version              = excluded.model_version,
    feature_completeness_score = excluded.feature_completeness_score;
"""


def ensure_tables(conn: sqlite3.Connection):
    conn.execute(CREATE_RECS_TABLE)
    conn.execute(CREATE_IDX_DATE)
    conn.execute(CREATE_IDX_LID)
    conn.commit()


# ─── Histogram helper ────────────────────────────────────────────────────────

def print_max_p_histogram(max_p_values: list[float], step: float = 0.05):
    """Print ASCII histogram of max_p distribution (0.05 step)."""
    if not max_p_values:
        print("  (no data)")
        return

    buckets: Counter = Counter()
    edges = [round(i * step, 2) for i in range(int(1.0 / step) + 1)]
    for v in max_p_values:
        bucket = round(math.floor(v / step) * step, 2)
        buckets[bucket] += 1

    max_count = max(buckets.values()) if buckets else 1
    bar_width = 30
    print(f"\n  {'max_p range':<16} {'count':>5}  {'bar'}")
    print(f"  {'-'*16} {'-'*5}  {'-'*bar_width}")
    for lo in edges[:-1]:
        hi = round(lo + step, 2)
        count = buckets.get(lo, 0)
        bar = "█" * int(count / max_count * bar_width)
        marker = " ← threshold" if abs(lo - MAX_P_THRESHOLD) < 1e-9 else ""
        print(f"  [{lo:.2f}, {hi:.2f})    {count:>5}  {bar}{marker}")
    print(f"\n  Total: {len(max_p_values)}  |  "
          f"≥ {MAX_P_THRESHOLD:.2f}: {sum(1 for v in max_p_values if v >= MAX_P_THRESHOLD)}  |  "
          f"mean: {sum(max_p_values)/len(max_p_values):.3f}  |  "
          f"max: {max(max_p_values):.3f}")


# ─── Core pipeline ───────────────────────────────────────────────────────────

def run(
    leagues: frozenset[int],
    target_date: Optional[str],
    dry_run: bool,
    min_max_p: float,
    conn_rw: sqlite3.Connection,
) -> dict:
    """Main pipeline. Returns stats dict."""
    import pandas as pd

    # Step 1: load schedule
    if not os.path.exists(SCHEDULE_FILE):
        log.error(f"schedule file not found: {SCHEDULE_FILE}")
        return {}

    with open(SCHEDULE_FILE, encoding="utf-8") as f:
        all_matches = json.load(f)

    cup_matches = [m for m in all_matches if m.get("league_id") in leagues]
    if target_date:
        cup_matches = [m for m in cup_matches if str(m.get("date", "")).startswith(target_date)]
    log.info(f"Schedule: total={len(all_matches)}, cup/euro in leagues={len(cup_matches)}")

    # Step 2: load models
    models, feat_full, feat_pure, rho_data = load_lambda_models()

    # Step 3: inference loop
    stats = {"total": 0, "no_feat_row": 0, "core_null": 0,
             "passed_feature_check": 0, "passed_max_p": 0, "final_output": 0}

    skip_records = []
    output_records = []
    all_max_p = []

    conn_ro = sqlite3.connect(DB_PATH)

    for m in cup_matches:
        mid = m.get("match_id")
        lid = int(m.get("league_id", 0))
        match_name = m.get("match_name", f"match_{mid}")
        match_date = str(m.get("date", ""))[:10]
        home_id = int(m.get("home_id", 0) or 0)
        away_id = int(m.get("away_id", 0) or 0)
        stats["total"] += 1

        # Load features from mart_prediction_matrix_v5
        df = load_features(mid, conn_ro)
        if df is None:
            log.warning(f"[SKIP] {match_name} (mid={mid}) not in mart_prediction_matrix_v5")
            stats["no_feat_row"] += 1
            skip_records.append({
                "match_id": mid, "reason": "no_feature_row", "match_name": match_name
            })
            continue

        # Core feature null check
        score, missing = check_core_features(df, mid)
        if missing:
            log.warning(
                f"[SKIP] {match_name} (mid={mid}) core feature null: {missing} "
                f"(completeness={score}/{len(CORE_FEATURES)})"
            )
            stats["core_null"] += 1
            skip_records.append({
                "match_id": mid, "reason": "core_feature_null",
                "match_name": match_name, "missing_features": missing,
                "completeness_score": score,
            })
            continue

        stats["passed_feature_check"] += 1

        # Inference
        result = run_inference(df, models, feat_full, feat_pure, rho_data, lid)
        if result is None:
            log.warning(f"[SKIP] {match_name} inference failed")
            skip_records.append({
                "match_id": mid, "reason": "inference_error", "match_name": match_name
            })
            continue

        p_home, p_draw, p_away, lam_h, lam_a, rho = result
        max_p = max(p_home, p_draw, p_away)
        all_max_p.append(max_p)

        outcome_map = {p_home: "H", p_draw: "D", p_away: "A"}
        predicted_outcome = outcome_map[max_p]

        log.info(
            f"  {match_name:<40} lid={lid:<6} "
            f"λ=({lam_h:.3f},{lam_a:.3f}) ρ={rho:.3f}  "
            f"WDL=({p_home:.3f},{p_draw:.3f},{p_away:.3f})  "
            f"→ {predicted_outcome} max_p={max_p:.3f}"
        )

        if max_p < min_max_p:
            log.info(f"    [FILTERED] max_p={max_p:.3f} < threshold={min_max_p:.3f}")
            continue

        stats["passed_max_p"] += 1
        output_records.append({
            "match_id": mid, "league_id": lid, "match_date": match_date,
            "home_team_id": home_id, "away_team_id": away_id,
            "predicted_outcome": predicted_outcome,
            "p_home": round(p_home, 4), "p_draw": round(p_draw, 4), "p_away": round(p_away, 4),
            "max_p": round(max_p, 4),
            "model_version": MODEL_VERSION,
            "feature_completeness_score": score,
        })

    conn_ro.close()

    # Step 4: print histogram in dry-run mode (always print if data exists)
    stats["final_output"] = len(output_records)
    print(f"\n{'='*60}")
    print(f"  shadow_cup_wdl_v5 {'DRY-RUN' if dry_run else 'PRODUCTION'} REPORT")
    print(f"  Date: {target_date or date.today().isoformat()}")
    print(f"  Leagues: {sorted(leagues)}")
    print(f"  MAX_P_THRESHOLD: {min_max_p}")
    print(f"{'='*60}")
    print(f"  total                  : {stats['total']}")
    print(f"  passed_feature_check   : {stats['passed_feature_check']}")
    print(f"    (no_feat_row={stats['no_feat_row']}, core_null={stats['core_null']})")
    print(f"  passed_max_p           : {stats['passed_max_p']}")
    print(f"  final_output           : {stats['final_output']}")
    print(f"{'='*60}")

    if all_max_p:
        print("\nmax_p distribution (all matches that passed feature check):")
        print_max_p_histogram(all_max_p)

    if output_records:
        print("\nPredictions passing threshold:")
        for r in output_records:
            print(
                f"  mid={r['match_id']} lid={r['league_id']} "
                f"{r['predicted_outcome']} "
                f"({r['p_home']:.3f}/{r['p_draw']:.3f}/{r['p_away']:.3f}) "
                f"max_p={r['max_p']:.3f}"
            )

    # Step 5: write skip log
    if skip_records:
        today_str = (target_date or date.today().isoformat()).replace("-", "")[:8]
        skip_log_path = os.path.join(REPORTS_DIR, f"shadow_cup_wdl_skipped_{today_str}.log")
        if not dry_run:
            with open(skip_log_path, "w", encoding="utf-8") as f:
                json.dump(skip_records, f, indent=2, ensure_ascii=False)
            log.info(f"Skip log written: {skip_log_path} ({len(skip_records)} entries)")
        else:
            print(f"\nSkipped matches ({len(skip_records)}):")
            for s in skip_records:
                reason = s.get("reason", "?")
                missing = s.get("missing_features", [])
                print(f"  mid={s['match_id']} {s.get('match_name','')} → {reason}"
                      + (f" missing={missing}" if missing else ""))

    # Step 6: write to DB (production only)
    if not dry_run and output_records:
        ensure_tables(conn_rw)
        for r in output_records:
            conn_rw.execute(UPSERT_SQL, (
                r["match_id"], r["league_id"], r["match_date"],
                r["home_team_id"], r["away_team_id"],
                r["predicted_outcome"],
                r["p_home"], r["p_draw"], r["p_away"], r["max_p"],
                r["model_version"], r["feature_completeness_score"],
            ))
        conn_rw.commit()
        stats["final_output"] = len(output_records)
        log.info(f"Wrote {len(output_records)} shadow recs to shadow_cup_wdl_recs")
    elif dry_run:
        print(f"\n[DRY-RUN] No writes to DB. Would write {len(output_records)} records.")

    return stats


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="V5 Lambda WDL Shadow for Cup/Euro Matches")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print predictions without writing to DB")
    parser.add_argument("--leagues", nargs="+", type=int, default=None,
                        help="League IDs to include (default: Phase A = 42 73)")
    parser.add_argument("--date", type=str, default=None,
                        help="Target date YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--min-max-p", type=float, default=MAX_P_THRESHOLD,
                        help=f"max_p threshold (default: {MAX_P_THRESHOLD})")
    args = parser.parse_args()

    leagues = frozenset(args.leagues) if args.leagues else PHASE_A_LIDS
    target_date = args.date
    min_max_p = args.min_max_p

    log.info(f"shadow_cup_wdl_v5 start | leagues={sorted(leagues)} | "
             f"dry_run={args.dry_run} | min_max_p={min_max_p} | date={target_date or 'today'}")

    conn_rw = sqlite3.connect(DB_PATH)
    try:
        stats = run(
            leagues=leagues,
            target_date=target_date,
            dry_run=args.dry_run,
            min_max_p=min_max_p,
            conn_rw=conn_rw,
        )
    finally:
        conn_rw.close()

    log.info(f"Done. stats={stats}")


if __name__ == "__main__":
    main()
