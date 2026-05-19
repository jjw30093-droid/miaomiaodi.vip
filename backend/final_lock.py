"""
final_lock.py
=============
T-30 定稿管线：在开球前 30 分钟（±2.5min 窗口）自动执行以下步骤：
  1. 抓取最新赔率（NowGoal 单场刷新）
  2. 用最新赔率 + ML 重算推荐方向（轻量，不跑 4-Agent LLM）
  3. 更新本地 report_store.pipeline_status = 'FINAL_REPORT_READY'
  4. 回推云端 AWS

被 pm2 job-final-lock（*/5 * * * *）每 5 分钟调用一次；
非 T-30 窗口的 tick 快速退出，不做任何操作。

支持 dry_run 模式（不写库、不推云）：
    python3 final_lock.py --dry-run
"""

import os
import sys
import json
import sqlite3
import logging
import argparse
from datetime import datetime, date

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

DB_PATH       = os.path.join(PROJECT_ROOT, "football_uk.db")
SCHEDULE_FILE = os.path.join(PROJECT_ROOT, "schedule", "target_matches.json")
ODDS_PATH     = os.path.join(PROJECT_ROOT, "odds", "match_odds_data.json")
REPORTS_DIR   = os.path.join(PROJECT_ROOT, "reports")
LOGS_DIR      = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# T-30 窗口定义（分钟）：与 5-min cron 对齐，留 ±2.5min 容忍区间
LOCK_WIN_MIN = 27.5   # 触发下边界
LOCK_WIN_MAX = 32.5   # 触发上边界


def _refresh_odds_for_match(m: dict) -> bool:
    """
    用 titan_odds_spider.fetch_single_match_odds 刷新单场赔率，
    并将结果就地更新到 match_odds_data.json。
    返回 True 表示赔率刷新成功（失败时保留旧赔率，不中断流程）。
    """
    try:
        from titan_odds_spider import fetch_single_match_odds
    except ImportError as e:
        log.warning(f"  ⚠️ 无法导入 titan_odds_spider: {e}，跳过赔率刷新")
        return False

    mid       = str(m["match_id"])
    name_parts = m.get("match_name", "").split(" vs ", 1)
    home_en   = name_parts[0].strip() if name_parts else ""
    away_en   = name_parts[1].strip() if len(name_parts) > 1 else ""
    kickoff   = m.get("kickoff_time", "")[:10]   # YYYY-MM-DD

    try:
        new_odds = fetch_single_match_odds(mid, kickoff, home_en, away_en)
        if not new_odds:
            log.warning(f"  ⚠️ 赔率刷新返回空，保留旧赔率")
            return False

        # 就地更新 match_odds_data.json
        odds_list: list = []
        if os.path.exists(ODDS_PATH):
            with open(ODDS_PATH, encoding="utf-8") as f:
                odds_list = json.load(f)

        updated = False
        for entry in odds_list:
            if str(entry.get("fotmob_id")) == mid:
                entry["odds"] = new_odds
                updated = True
                break
        if not updated:
            odds_list.append({
                "fotmob_id": str(mid),
                "titan_id":  "",
                "match_name": m.get("match_name", ""),
                "odds": new_odds,
            })

        with open(ODDS_PATH, "w", encoding="utf-8") as f:
            json.dump(odds_list, f, ensure_ascii=False, indent=2)

        log.info(f"  ✅ 赔率已刷新并写入 match_odds_data.json")
        return True

    except Exception as e:
        log.error(f"  ❌ 赔率刷新异常: {e}，保留旧赔率继续")
        return False


# T-30 narrative 重写专用 prompt（直接生成 markdown 段落，不走 4-Agent 链路）
_NARRATIVE_REFRESH_PROMPT = """# 角色
你是「喵弟量化研究所」的首席策略分析师，正在为已生成的研报做 T-30 定稿前的「亚盘」「大小球」段落刷新。

# 上下文
原研报在赛前 6 小时基于 opening 赔率生成。现在距开球 30 分钟，我们拿到了 closing 赔率与（如有）确认首发，需要用最新数据重写两段正文，让用户看到的赔率/伤停/首发分析与最终行情一致。

# 铁律
1. **绝对禁止编造事实**，所有数值必须来源于输入的 ml_output / odds_data / team_stats / lineup_data。
2. **绝对禁止英语单词**：xG→预期进球、PPDA→防守压迫强度、npxGD→非罚预期净胜球、Edge→价值边际、ML→算法模型。
3. **禁止极端表述**：不用"100%""绝对""必胜""毫无悬念"。
4. **不要做胜平负方向预测**。本系统只出亚盘和大小球推荐。
5. **必须使用 closing 赔率数值**（输入 odds_data 的 latest 字段就是 closing）。
6. 段落字数：每段 250-400 字。

# 输出格式（严格遵循，前端按 H2 字符串匹配）
你必须**只输出 2 段 Markdown**，每段以 `## ` 开头，不要任何其他内容（不输出 # 标题、不写综述/总结、不要 disclaimer、不要其他章节）：

## 亚盘分析

[250-400 字。说明当前盘口（如"主让0.5"或"平手盘"）、模型覆盖率、为什么模型认为能/不能覆盖。
用具体数据支撑：双方近5场 npxGD、防守压迫强度、阵地推进。
若 lineup_data 里有 severity=HIGH 的缺阵球员，1 句话指出对盘口的影响。
若 lineup_data 中存在确认首发，使用真实首发名单内容（不要写"预测首发"）。]

## 大小球分析

[250-400 字。说明当前大小球盘口（如"2.25球"）、模型预测的大球概率（百分比）、为什么看好大球或小球。
用具体数据支撑：双方近5场场均进失球、射门节奏、对战历史进球数。
结合 lineup_data 中前锋/前场核心是否缺阵，说明对进球数预期的影响。]
"""


def _extract_section(md: str, title_keyword: str) -> str:
    """从 LLM 输出的 markdown 里抽取「## ...亚盘...」或「## ...大小球...」段落正文。

    返回不含标题的纯正文。匹配失败返回空串。
    """
    import re as _re
    pattern = rf'##\s*[^\n]*?{title_keyword}[^\n]*\n(.*?)(?=\n##|\Z)'
    m_obj = _re.search(pattern, md, flags=_re.DOTALL)
    return (m_obj.group(1).strip() if m_obj else "").strip()


def _rerun_narrative_sections(mid: str, m: dict, odds_index: dict,
                              lineup_data: dict | None) -> bool:
    """T-30 用 closing 赔率 + 确认首发重写「## 亚盘分析」「## 大小球分析」段落。

    设计要点（CLAUDE.md §B3 上线前修复）：
      - 单次 LLM 调用（Flash + 内置 fallback），生成 2 段 markdown
      - 失败保留旧段落，不阻断 final_lock 后续 step
      - 失败 → log.error + record_failure（CLAUDE.md §17 防御）
    """
    try:
        from generate_match_report import (
            load_models, get_team_features, build_feature_row,
        )
        from report_section_editor import replace_handicap_section, replace_ou_section
        from langchain_core.messages import HumanMessage
        from qwen_client import get_flash
        import pandas as pd

        # ── 1. 计算 ML（与 update_odds_pick.refresh_pick_for_match 一致）
        odds_data = odds_index.get(mid, {})
        eu = odds_data.get("european_1x2", {}).get("latest", {})
        eu_h, eu_d, eu_a = (
            float(eu.get("home", 0) or 0),
            float(eu.get("draw", 0) or 0),
            float(eu.get("away", 0) or 0),
        )
        ah = odds_data.get("asian_handicap", {}).get("latest", {})
        ah_line = float(ah.get("line", 0) or 0)
        ah_home = float(ah.get("over_or_home", 0) or 0)
        ah_away = float(ah.get("under_or_away", 0) or 0)
        is_cup = 1 if m.get("league_id", 0) in {42, 73, 10216, 132, 133, 134, 138, 141, 209} else 0

        model_wdl, model_ou, FEATURES = load_models()

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            h_feat = get_team_features(conn, m["home_id"], date.today())
            a_feat = get_team_features(conn, m["away_id"], date.today())
        finally:
            conn.close()

        row = build_feature_row(h_feat, a_feat, eu_h, eu_d, eu_a,
                                is_cup=is_cup, ah_line=ah_line,
                                ah_home=ah_home, ah_away=ah_away)
        X = pd.DataFrame([row])[FEATURES].fillna(0)
        wdl_arr = model_wdl.predict(X)[0]
        ou_val  = float(model_ou.predict(X)[0])

        # ── 2. 组装精简 user_data（一份 JSON 喂给 LLM）
        match_parts = m.get("match_name", "").split(" vs ", 1)
        home_team = match_parts[0].strip() if match_parts else ""
        away_team = match_parts[1].strip() if len(match_parts) > 1 else ""

        # 简化版 lineup（只取关键字段，避免 token 爆炸）
        ld_brief = {}
        if lineup_data:
            for side in ("home", "away"):
                _side = lineup_data.get(side, {}) or {}
                ld_brief[side] = {
                    "formation": _side.get("formation"),
                    "starters_count": len(_side.get("starters", [])),
                    "missing": [
                        {"name": p.get("name"), "reason": p.get("reason"),
                         "severity": p.get("severity"),
                         "xg_xa_share": p.get("xg_xa_share"),
                         "def_share":   p.get("def_share")}
                        for p in (_side.get("missing", []) or [])
                    ][:8],  # 最多 8 个伤停
                }
            ld_brief["status"] = lineup_data.get("status")

        user_data = {
            "match_info": {
                "home_name": home_team,
                "away_name": away_team,
                "league":    m.get("league", ""),
                "kickoff":   m.get("kickoff_time", ""),
            },
            "ml_output": {
                "wdl": {
                    "home": round(float(wdl_arr[0]), 4),
                    "draw": round(float(wdl_arr[1]), 4),
                    "away": round(float(wdl_arr[2]), 4),
                },
                "ou_over_25": round(ou_val, 4),
            },
            "odds_data_closing": {
                "asian_handicap": odds_data.get("asian_handicap", {}).get("latest", {}),
                "over_under":     odds_data.get("over_under",     {}).get("latest", {}),
                "european_1x2":   odds_data.get("european_1x2",   {}).get("latest", {}),
            },
            "team_stats": {
                "home_elo":         round(h_feat["elo"], 1),
                "away_elo":         round(a_feat["elo"], 1),
                "elo_diff":         round(h_feat["elo"] - a_feat["elo"], 1),
                "home_rest_days":   h_feat["rest"],
                "away_rest_days":   a_feat["rest"],
                "home_npxGD":       round(h_feat["rf"].get("roll_5_npxGD", 0) or 0, 3),
                "away_npxGD":       round(a_feat["rf"].get("roll_5_npxGD", 0) or 0, 3),
                "home_ppda":        round(h_feat["rf"].get("roll_5_ppda", 0) or 0, 3),
                "away_ppda":        round(a_feat["rf"].get("roll_5_ppda", 0) or 0, 3),
                "home_field_tilt":  round(h_feat["rf"].get("roll_5_field_tilt", 0) or 0, 3),
                "away_field_tilt":  round(a_feat["rf"].get("roll_5_field_tilt", 0) or 0, 3),
                "home_shot_pace":   round(h_feat["rf"].get("roll_shot_pace", 0) or 0, 3),
                "away_shot_pace":   round(a_feat["rf"].get("roll_shot_pace", 0) or 0, 3),
            },
            "lineup_data": ld_brief,
        }

        # ── 3. 单次 LLM 调用生成两段 markdown
        log.info(f"  🧠 重写正文（亚盘 + 大小球，单次 LLM）...")
        llm = get_flash()
        prompt_text = (
            f"系统提示：{_NARRATIVE_REFRESH_PROMPT}\n\n"
            f"请基于以下数据重写两段正文：\n\n"
            f"```json\n{json.dumps(user_data, ensure_ascii=False, indent=2)}\n```"
        )
        response = llm.invoke([HumanMessage(content=prompt_text)])
        full_md = (response.content or "").strip()

        # ── 4. 提取两个段落
        ah_text = _extract_section(full_md, "亚盘")
        ou_text = _extract_section(full_md, "大小球")

        if not ah_text and not ou_text:
            log.warning(f"  ⚠️ LLM 输出未匹配到段落，保留旧内容. 输出片段: {full_md[:200]!r}")
            return False

        # ── 5. 段落替换 .md 文件
        report_date = m.get("kickoff_time", "")[:10]
        report_path = os.path.join(REPORTS_DIR, f"report_{report_date}_{mid}.md")
        if not os.path.exists(report_path):
            import glob
            found = glob.glob(os.path.join(REPORTS_DIR, f"report_*_{mid}.md"))
            if found:
                found.sort(key=os.path.getmtime, reverse=True)
                report_path = found[0]
                log.info(f"  💡 跨日期兜底匹配报告: {os.path.basename(report_path)}")

        if not os.path.exists(report_path):
            log.warning(f"  ⚠️ 找不到 .md 报告文件，跳过段落替换")
            return False

        ok_ah = replace_handicap_section(report_path, ah_text) if ah_text else False
        ok_ou = replace_ou_section(report_path, ou_text) if ou_text else False
        log.info(f"  📝 段落替换：亚盘={ok_ah} 大小球={ok_ou}")

        if not (ok_ah or ok_ou):
            return False

        # ── 6. 同步 markdown_content 到 report_store
        with open(report_path, encoding="utf-8") as f:
            new_md = f.read()
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                "UPDATE report_store SET markdown_content = ? WHERE match_id = ?",
                [new_md, mid],
            )
            conn.commit()
        finally:
            conn.close()
        log.info(f"  💾 markdown_content 已同步到 report_store [{mid}]")

        # ── 7. 重新推送到 AWS S3（之前 refresh_pick_for_match 推的是旧 markdown）
        try:
            from scripts.aws_pusher import push_match_payload
            push_match_payload(mid)
            log.info(f"  🚀 narrative 更新后 AWS 推送完成 [{mid}]")
        except Exception as e:
            log.warning(f"  ⚠️ AWS 二次推送失败（不阻断）: {e}")

        return True

    except Exception as e:
        log.error(f"  ❌ T-30 段落重写失败 [{mid}]: {e}")
        # 沿用 §17 防御：失败入 ingest_failure_log，但不阻断
        try:
            from ingest_failure_helper import record_failure
            record_failure(
                script_name="final_lock",
                match_id=mid,
                step="rerun_narrative",
                error_msg=str(e),
            )
        except Exception:
            pass  # record_failure 不可用时也不能再嵌套 raise
        return False


def _load_lineup_data(mid: str) -> dict | None:
    """从 report_store.lineup_data 读取 JSON（poll_lineup 已写入）"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT lineup_data FROM report_store WHERE match_id=?", (mid,)
        ).fetchone()
        conn.close()
        if not row or not row["lineup_data"]:
            return None
        return json.loads(row["lineup_data"])
    except Exception as e:
        log.warning(f"  ⚠️ 读取 lineup_data 失败 [{mid}]: {e}")
        return None


def _mark_final_ready(mid: str) -> None:
    """将 report_store.pipeline_status 置为 FINAL_REPORT_READY。"""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "UPDATE report_store SET pipeline_status = 'FINAL_REPORT_READY' WHERE match_id = ?",
            (mid,)
        )
        conn.commit()
        log.info(f"  📌 pipeline_status → FINAL_REPORT_READY [{mid}]")
    finally:
        conn.close()


def process_match(m: dict, dry_run: bool = False) -> bool:
    """对单场比赛执行 T-30 定稿流程。"""
    mid  = str(m["match_id"])
    name = m.get("match_name", mid)
    log.info(f"🔒 定稿处理: {name} [{mid}]")

    # ── Step 1: 刷新赔率 ──────────────────────────────────────────────────
    _refresh_odds_for_match(m)   # 失败不中断，继续用旧赔率

    if dry_run:
        log.info(f"  [DRY RUN] 跳过 ML 重算、段落重写、DB 写入、AWS 推送")
        return True

    # 重载赔率（刚刚已刷新写入文件）—— Step 2 + Step 2.5 共用 odds_index
    try:
        with open(ODDS_PATH, encoding="utf-8") as f:
            odds_raw = json.load(f)
        odds_index = {}
        for o in odds_raw:
            if "fotmob_id" not in o:
                log.warning(f"[odds_load] 跳过损坏记录（缺 fotmob_id）")
                continue
            odds_index[str(o["fotmob_id"])] = o.get("odds", {})
    except Exception as e:
        log.error(f"  ❌ 加载 match_odds_data.json 失败: {e}")
        odds_index = {}

    # ── Step 2: 重算 ML + inference + 推 AWS（复用 update_odds_pick）──────
    try:
        from generate_match_report import load_models, load_ah_predictor
        from update_odds_pick import refresh_pick_for_match

        model_wdl, model_ou, FEATURES = load_models()
        ah_predictor = load_ah_predictor()

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            ok = refresh_pick_for_match(
                mid, m, conn,
                model_wdl, model_ou, FEATURES,
                odds_index, date.today(),
                ah_predictor=ah_predictor
            )
        finally:
            conn.close()

        if not ok:
            log.warning(f"  ⚠️ refresh_pick_for_match 返回 False，仍继续置状态")
    except Exception as e:
        log.error(f"  ❌ ML 重算异常: {e}")

    # ── Step 2.5: 用 closing 赔率 + 确认首发重写「亚盘」「大小球」段落 ──────
    # （CLAUDE.md §B3 上线前修复，独立失败不阻断 final_lock）
    lineup_data = _load_lineup_data(mid)
    _rerun_narrative_sections(mid, m, odds_index, lineup_data)

    # ── Step 3: 置 FINAL_REPORT_READY ────────────────────────────────────
    _mark_final_ready(mid)
    return True


def main(dry_run: bool = False):
    now = datetime.now()

    if not os.path.exists(SCHEDULE_FILE):
        log.warning(f"赛程文件不存在: {SCHEDULE_FILE}")
        return

    with open(SCHEDULE_FILE, encoding="utf-8") as f:
        matches = json.load(f)

    # ── 快速过滤：只处理当前 T-30 窗口内的比赛 ──────────────────────────
    targets = []
    for m in matches:
        kickoff_str = m.get("kickoff_time", "")
        if not kickoff_str:
            continue
        try:
            kickoff = datetime.strptime(kickoff_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

        mins_left = (kickoff - now).total_seconds() / 60
        if not (LOCK_WIN_MIN <= mins_left <= LOCK_WIN_MAX):
            continue

        mid = str(m["match_id"])

        # ── 跳过已定稿 ──────────────────────────────────────────────────
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT pipeline_status FROM report_store WHERE match_id = ?", (mid,)
            ).fetchone()
        finally:
            conn.close()

        if row and row["pipeline_status"] == "FINAL_REPORT_READY":
            log.info(f"⏭️  已定稿，跳过: {m.get('match_name', mid)}")
            continue

        # ── 跳过尚无研报的比赛（run_tonight 未生成）──
        if not row:
            log.info(f"⏭️  report_store 无记录（研报未生成），跳过: {m.get('match_name', mid)}")
            continue

        targets.append(m)

    if not targets:
        log.debug(f"[final_lock] 当前无 T-30 窗口比赛，退出")
        return

    log.info(f"🔔 T-30 定稿窗口命中 {len(targets)} 场：{[m.get('match_name', m['match_id']) for m in targets]}")

    for m in targets:
        try:
            process_match(m, dry_run=dry_run)
        except Exception as e:
            log.error(f"💥 定稿处理异常 [{m.get('match_name', m['match_id'])}]: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="T-30 定稿管线")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅打印命中场次，不执行 ML 重算 / DB 写入 / AWS 推送")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
