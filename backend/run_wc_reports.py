"""
run_wc_reports.py
=================
世界杯研报生成入口脚本。

Phase 1：手动触发（单场）
Phase 2：批量 / cron

用法：
  python backend/run_wc_reports.py --match-id wc_19609127
  python backend/run_wc_reports.py --match-id wc_19609127 --dry-run  # 仅打印，不写库

流程：
  1. 读 wc_fixtures + wc_statistics（worldcup.db）
  2. wc_devig: 去水共识（WDL/OU/AH）
  3. wc_predict: 市场共识 → WDL/OU 概率
  4. wc_confidence: 分级（HIGH/MID/LOW/SKIP）
  5. wc_select_single_pick（来自 wc_confidence）: 只产 WDL
  6. build_prebuilt_quant_section: Python 生成量化基准线（LLM 不得重算）
  7. wc_workflow: 4-Agent LLM 链 → report_markdown
  8. wc_store.write_wc_report: 写 wc_reports
  9. wc_store.write_wc_prediction_audit: 记录推荐审计

数据约束（已锁定）：
  - WC 只有队伍级统计，无 xG / shotmap / 球员级数据
  - WDL-only 推荐；OU 仅展示；AH 仅幅度信息
  - 所有概率来自市场共识（去水中位），非 ML 模型
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── 路径 ──────────────────────────────────────────────────────────────────────
_THIS_DIR    = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.environ.get("PROJECT_ROOT", _THIS_DIR)
WC_DB_PATH   = os.environ.get("WC_DB_PATH",  os.path.join(PROJECT_ROOT, "worldcup.db"))

# ── 加载 .env（DASHSCOPE_API_KEY 等）──────────────────────────────────────────
_env_path = os.path.join(PROJECT_ROOT, ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            if "=" in _line and not _line.strip().startswith("#"):
                _k, _v = _line.strip().split("=", 1)
                os.environ.setdefault(_k, _v)


# ──────────────────────────────────────────────────────────────────────────────
# 读取 wc_fixtures 信息
# ──────────────────────────────────────────────────────────────────────────────

def _load_fixture(conn: sqlite3.Connection, fixture_id: int) -> Optional[dict]:
    # A1 fix: home_team_name/away_team_name 不存在于 wc_fixtures，JOIN wc_teams 取名
    # match_label 兜底（占位赛程或团队名缺失时）
    row = conn.execute("""
        SELECT f.sportmonks_id,
               f.starting_at,
               f.home_team_sportmonks_id,
               f.away_team_sportmonks_id,
               COALESCE(ht.name, f.placeholder_home, f.match_label, '主队') AS home_team_name,
               COALESCE(at.name, f.placeholder_away, f.match_label, '客队') AS away_team_name,
               f.match_label,
               f.is_placeholder
        FROM   wc_fixtures f
        LEFT   JOIN wc_teams ht ON ht.sportmonks_id = f.home_team_sportmonks_id
        LEFT   JOIN wc_teams at ON at.sportmonks_id = f.away_team_sportmonks_id
        WHERE  f.sportmonks_id = ?
    """, (fixture_id,)).fetchone()
    return dict(row) if row else None


# ──────────────────────────────────────────────────────────────────────────────
# 读取 wc_statistics 并转换为 dict（约 40 个 type/value 对 → {home:{...},away:{...}}）
# ──────────────────────────────────────────────────────────────────────────────

def _load_team_stats(conn: sqlite3.Connection, fixture_id: int, fixture: dict) -> dict:
    rows = conn.execute("""
        SELECT team_sportmonks_id, type, value
        FROM   wc_statistics
        WHERE  fixture_sportmonks_id = ?
    """, (fixture_id,)).fetchall()

    home_tid = fixture.get("home_team_sportmonks_id")
    away_tid = fixture.get("away_team_sportmonks_id")

    home_stats: dict = {}
    away_stats: dict = {}

    for r in rows:
        tid  = r["team_sportmonks_id"]
        typ  = r["type"]
        val  = r["value"]
        # 尝试数值化
        try:
            numeric = float(val) if val is not None else None
        except (ValueError, TypeError):
            numeric = val

        if tid == home_tid:
            home_stats[typ] = numeric
        elif tid == away_tid:
            away_stats[typ] = numeric

    return {"home": home_stats, "away": away_stats}


# ──────────────────────────────────────────────────────────────────────────────
# 主生成逻辑
# ──────────────────────────────────────────────────────────────────────────────

def generate_wc_report(
    match_id: str,
    db_path: str = WC_DB_PATH,
    dry_run: bool = False,
) -> Optional[dict]:
    """
    生成单场 WC 研报并写库。
    返回 write_result dict 或 None（SKIP 场次）。
    """
    if not match_id.startswith("wc_"):
        raise ValueError(f"match_id must start with 'wc_', got: {match_id!r}")

    try:
        fixture_id = int(match_id[3:])
    except ValueError:
        raise ValueError(f"Cannot parse fixture_id from {match_id!r}")

    log.info(f"[run_wc_reports] === generating {match_id} (fixture={fixture_id}) ===")

    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row

    try:
        # ── 1. 读取 fixture + team stats ──────────────────────────────────────
        fixture = _load_fixture(conn, fixture_id)
        if not fixture:
            log.error(f"  fixture {fixture_id} not found in wc_fixtures")
            return None

        home_name = fixture.get("home_team_name") or "主队"
        away_name = fixture.get("away_team_name") or "客队"
        match_time = fixture.get("starting_at") or ""

        log.info(f"  {home_name} vs {away_name} @ {match_time}")

        team_stats = _load_team_stats(conn, fixture_id, fixture)

        # ── 2. 去水共识 ────────────────────────────────────────────────────────
        from wc_devig import devig_consensus  # type: ignore
        devig = devig_consensus(conn, fixture_id, period="opening")

        wdl_consensus = devig.get("wdl_consensus", {})
        ou_consensus  = devig.get("ou_consensus", {})
        ah_implied    = devig.get("ah_implied", {})

        if not wdl_consensus:
            log.error(f"  WDL consensus empty — cannot generate report")
            return None

        # ── 3. WDL 预测（市场共识即预测） ─────────────────────────────────────
        from wc_predict import wc_predict  # type: ignore
        prediction = wc_predict(wdl_consensus, ou_consensus or None)

        # ── 4. 置信分级 ───────────────────────────────────────────────────────
        from wc_confidence import grade, wc_select_single_pick  # type: ignore
        grade_result = grade(
            wdl_probs  = prediction["wdl"],
            divergence = prediction["divergence"],
            n_books    = prediction["n_books_wdl"],
        )

        # ── 5. 单推选择（WDL-only） ───────────────────────────────────────────
        single_pick = wc_select_single_pick(
            grade_result   = grade_result,
            wdl_probs      = prediction["wdl"],
            ah_implied     = ah_implied or None,
            closing_odds_row = None,   # opening 阶段无 closing 赔率
        )

        if grade_result.get("confidence") == "SKIP":
            log.info(f"  SKIP: {grade_result.get('skip_reason')}")
            # SKIP 不阻止生成研报，只是研报内不出推荐

        # ── 6. 量化基准线（Python 生成，LLM 不得重算） ───────────────────────
        from wc_workflow import build_prebuilt_quant_section  # type: ignore
        # 把 n_books/divergence 从 prediction 顶层补入 wdl dict，供 quant_section 显示
        wdl_for_quant = {
            **prediction["wdl"],
            "n_books":   prediction.get("n_books_wdl", 0),
            "divergence": prediction.get("divergence", 0.0),
        }
        quant_section = build_prebuilt_quant_section(
            home_name   = home_name,
            away_name   = away_name,
            wdl         = wdl_for_quant,
            ou          = prediction["ou"],
            ah          = ah_implied or None,
            single_pick = single_pick,
        )

        # ── 7. LLM 4-Agent 链 ─────────────────────────────────────────────────
        inference_str = single_pick["inference"] if single_pick else "【SKIP】观望"

        if not dry_run:
            from qwen_client import get_flash, get_pro  # type: ignore
            llm_flash = get_flash()
            llm_pro   = get_pro()

            from wc_workflow import build_wc_workflow, WcMatchReportState  # type: ignore
            wf = build_wc_workflow(llm_flash, llm_pro)

            initial_state: WcMatchReportState = {
                "match_id":   match_id,
                "match_info": {
                    "home_name":   home_name,
                    "away_name":   away_name,
                    "match_time":  match_time,
                    "league":      "World Cup 2026",
                    "fixture_id":  fixture_id,
                },
                "wc_ml_output": {
                    "wdl":         prediction["wdl"],
                    "n_books_wdl": prediction["n_books_wdl"],
                    "divergence":  prediction["divergence"],
                    "source":      prediction["source"],
                },
                "wc_team_stats":          team_stats,
                "ou_display":             prediction.get("ou") or {},
                "ah_info":                ah_implied or {},
                "single_pick":            single_pick or {},
                "prebuilt_quant_section": quant_section,
                "agent1_output":          "",
                "agent2_output":          "",
                "agent3_output":          "",
                "final_report":           "",
            }

            log.info("  [wf] invoking 4-agent chain...")
            result_state = wf.invoke(initial_state)
            report_markdown = result_state.get("final_report") or ""
            log.info(f"  [wf] done — {len(report_markdown)} chars")
        else:
            report_markdown = f"[DRY-RUN] Would generate report for {match_id}\n\n{quant_section}"
            log.info(f"  [DRY-RUN] skipping LLM chain")

        # ── 8. 解析 json_meta（从 LLM 输出中提取） ────────────────────────────
        beginner_summary, key_risk, key_variables, chart_insights = _parse_json_meta(report_markdown)

        # ── 9. 组装 payload_json（烘焙进库） ──────────────────────────────────
        payload_json = {
            "market_implied": {
                "wdl":    wdl_consensus,
                "ou":     ou_consensus,
                "ah":     ah_implied,
                "period": "opening",
            },
            "model_meta": prediction.get("model_meta", {}),
            "grade":      grade_result,
        }

        # ── 10. 写库 ─────────────────────────────────────────────────────────
        if not dry_run:
            from wc_store import write_wc_report, write_wc_prediction_audit  # type: ignore

            match_date = match_time[:10] if match_time else ""

            write_wc_report(
                conn,
                match_id               = match_id,
                fixture_sportmonks_id  = fixture_id,
                report_markdown        = report_markdown,
                payload_json           = payload_json,
                inference              = inference_str,
                pipeline_status        = "DRAFT",
                home_team              = home_name,
                away_team              = away_name,
                match_time             = match_time,
                league                 = "World Cup",
                is_free                = 0,
                home_prob              = prediction["wdl"]["home"],
                draw_prob              = prediction["wdl"]["draw"],
                away_prob              = prediction["wdl"]["away"],
                beginner_summary       = beginner_summary,
                key_risk               = key_risk,
                key_variables          = key_variables,
                chart_insights         = chart_insights,
                match_status           = "upcoming",
            )

            # 写审计（SKIP 时不写）
            if single_pick:
                write_wc_prediction_audit(
                    conn,
                    match_id          = match_id,
                    match_date        = match_date,
                    home              = home_name,
                    away              = away_name,
                    picked_market     = single_pick["picked_market"],
                    picked_direction  = single_pick["picked_direction"],
                    picked_odds       = single_pick.get("picked_odds"),
                    picked_confidence = single_pick["picked_confidence"],
                )

            log.info(f"  [run_wc_reports] {match_id} written ✅")
        else:
            log.info(f"  [DRY-RUN] would write {match_id} to wc_reports")
            log.info(f"  inference: {inference_str}")
            log.info(f"  quant section:\n{quant_section}")

        return {
            "match_id":    match_id,
            "inference":   inference_str,
            "confidence":  grade_result.get("confidence"),
            "dry_run":     dry_run,
        }

    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# json_meta 解析
# ──────────────────────────────────────────────────────────────────────────────

def _parse_json_meta(markdown: str):
    """
    从 LLM 输出的 Markdown 中提取 ```json_meta ... ``` 块并解析。
    返回 (beginner_summary, key_risk, key_variables, chart_insights)，
    解析失败时各字段返回 None。
    """
    import re
    m = re.search(r"```json_meta\s*\n(.*?)\n```", markdown, re.DOTALL)
    if not m:
        return None, None, None, None

    try:
        meta = json.loads(m.group(1))
    except Exception as e:
        log.warning(f"[run_wc_reports] json_meta parse failed: {e}")
        return None, None, None, None

    return (
        meta.get("beginner_summary"),
        meta.get("key_risk"),
        meta.get("key_variables"),
        meta.get("chart_insights"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate WC match report")
    parser.add_argument("--match-id",  required=True, help="e.g. wc_19609127")
    parser.add_argument("--db",        default=WC_DB_PATH, help="Path to worldcup.db")
    parser.add_argument("--dry-run",   action="store_true", help="Skip LLM + writes")
    args = parser.parse_args()

    result = generate_wc_report(
        match_id = args.match_id,
        db_path  = args.db,
        dry_run  = args.dry_run,
    )

    if result:
        log.info(f"Done: {result}")
    else:
        log.error("Generation failed")
        sys.exit(1)
