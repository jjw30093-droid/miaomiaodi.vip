"""
poll_lineup.py
==============
赛前首发阵容轮询脚本（每 5 分钟由 cron 触发）

触发窗口：开球前 65 分钟 → 开球时
轮询逻辑：
  - 每次运行检查哪些比赛在窗口内且首发尚未确认
  - 调用 fetch_lineup() 抓取阵容
  - 若 status == "confirmed"：
      重跑 Agent 3（战力评估），替换研报中的「⚔️ 战力评估」段落
      推送 AWS，标记该比赛已确认，不再重复轮询
  - 若仍为 "predicted"：打印日志，等待下次 cron 触发

已确认状态持久化到 schedule/lineup_confirmed.json，避免重复更新

cron 设置（每 5 分钟运行）：
  */5 * * * * /opt/anaconda3/bin/python3 /Users/wanglujun/Desktop/Football_Data_Lake/poll_lineup.py >> /Users/wanglujun/Desktop/Football_Data_Lake/logs/poll_lineup.log 2>&1

用法：
  python3 poll_lineup.py           # 正常轮询
  python3 poll_lineup.py --force 5205791   # 强制对指定比赛抓一次（不受窗口限制）
"""

import os
import sys
import re
import json
import logging
import sqlite3
from datetime import datetime, date

import pandas as pd

PROJECT_ROOT  = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
REPORTS_DIR   = os.path.join(PROJECT_ROOT, "reports")
CONFIRMED_LOG = os.path.join(PROJECT_ROOT, "schedule", "lineup_confirmed.json")
LOGS_DIR      = os.path.join(PROJECT_ROOT, "logs")
DB_PATH       = os.path.join(PROJECT_ROOT, "football_uk.db")

os.makedirs(LOGS_DIR,   exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# 轮询窗口（距开球分钟数）
POLL_START_MINS = 65   # 开球前 65 分钟开始轮询
POLL_END_MINS   = 30   # 开球前 30 分钟停止（T-30 之后交棒 final_lock.py）

# 5 大联赛 + 欧冠/欧联：必须等 FotMob 放出官方首发才触发 Agent 3 重跑
# 其余联赛（K/J/澳超等）如果到 T-30 仍无确认首发，final_lock.py 将以
# predicted 首发 + 最新赔率走 FINAL_REPORT_READY，不阻塞管线。
PRIORITY_LEAGUES = {47, 87, 54, 55, 53, 42, 73}   # EPL/LaLiga/Bundesliga/SerieA/Ligue1/UCL/UEL

# 从 .env 加载 DASHSCOPE_API_KEY（迁移到千问后）
if not os.getenv("DASHSCOPE_API_KEY") and os.path.exists(os.path.join(PROJECT_ROOT, ".env")):
    with open(os.path.join(PROJECT_ROOT, ".env")) as _f:
        for _line in _f:
            if "=" in _line and not _line.strip().startswith("#"):
                _k, _v = _line.strip().split("=", 1)
                os.environ[_k] = _v

from lineup_fetcher import fetch_lineup
from aws_pusher import push_match_payload
from qwen_client import get_flash
from workflow import build_agent_node, AGENT3_SYSTEM_PROMPT
from generate_match_report import load_models, get_team_features, build_feature_row
from update_odds_pick import refresh_pick_for_match


# ── 持久化：已确认首发的比赛集合 ──────────────────────────

def _load_confirmed() -> set:
    if os.path.exists(CONFIRMED_LOG):
        try:
            with open(CONFIRMED_LOG, encoding="utf-8") as f:
                return set(json.load(f).get("confirmed_ids", []))
        except Exception:
            pass
    return set()


def _save_confirmed(ids: set):
    with open(CONFIRMED_LOG, "w", encoding="utf-8") as f:
        json.dump({"confirmed_ids": list(ids), "updated_at": datetime.now().isoformat()}, f)


# ── 替换报告中的战力评估段落 ──────────────────────────────

def _build_fallback_lineup_tables(lineup_data: dict, home_name: str = "主队", away_name: str = "客队") -> str:
    """
    当 Agent 3 未能生成 Markdown 表格时（如 K 联赛球员统计指标缺失），
    直接从 lineup_data 生成基础首发名单表格（不依赖 LLM）。
    """
    lines = []
    lines.append("### 确认首发名单")
    lines.append("| 球队 | 位置 | 球员 | 进攻贡献 | 防守贡献 |")
    lines.append("|---|---|---|---|---|")

    for side_key, team_label in [("home", home_name), ("away", away_name)]:
        side = lineup_data.get(side_key, {})
        starters = side.get("starters", [])
        if not starters:
            lines.append(f"| {team_label} | — | 首发数据暂缺 | — | — |")
            continue
        for p in starters:
            name     = p.get("name", "—")
            pos      = p.get("position", "—") or "—"
            xg_xa    = p.get("xg_xa_share", 0.0)
            def_s    = p.get("def_share", 0.0)
            xg_str   = f"{xg_xa:.2f}" if xg_xa else "—"
            def_str  = f"{def_s:.2f}" if def_s else "—"
            lines.append(f"| {team_label} | {pos} | {name} | {xg_str} | {def_str} |")

    # 伤停名单（若有）
    any_missing = False
    for side_key, team_label in [("home", home_name), ("away", away_name)]:
        side = lineup_data.get(side_key, {})
        if side.get("missing"):
            any_missing = True
            break

    if any_missing:
        lines.append("")
        lines.append("### 缺阵情报")
        lines.append("| 球队 | 球员 | 缺席原因 | 进攻贡献 | 防守贡献 |")
        lines.append("|---|---|---|---|---|")
        for side_key, team_label in [("home", home_name), ("away", away_name)]:
            for p in lineup_data.get(side_key, {}).get("missing", []):
                name    = p.get("name", "—")
                reason  = p.get("reason", "—") or "—"
                xg_xa   = p.get("xg_xa_share", 0.0)
                def_s   = p.get("def_share", 0.0)
                xg_str  = f"{xg_xa:.2f}" if xg_xa else "—"
                def_str = f"{def_s:.2f}" if def_s else "—"
                lines.append(f"| {team_label} | {name} | {reason} | {xg_str} | {def_str} |")

    return "\n".join(lines)


def _format_agent3_for_report(new_agent3: str, lineup_data: dict = None,
                               home_name: str = "主队", away_name: str = "客队") -> str:
    """
    将 agent3 原始输出（JSON + ---LINEUP_TABLES--- + Markdown 表格）
    转换为报告可读格式，消灭原始 JSON 和分隔符明文：
    - JSON → 阵型摘要 + 倾斜方向 + 关键缺阵文字
    - ---LINEUP_TABLES--- 之后 → Markdown 表格
    - 若表格为空（如 K 联赛球员指标缺失）→ 用 lineup_data 直接生成兜底表格
    """
    sep = '---LINEUP_TABLES---'
    if sep in new_agent3:
        json_part, tables_part = new_agent3.split(sep, 1)
        tables_part = tables_part.strip()
    else:
        json_part   = new_agent3
        tables_part = ""

    # ── 解析 JSON → 战术摘要文字 ──────────────────────────
    prose_lines = []
    try:
        data      = json.loads(json_part.strip())
        ts        = data.get("tactical_summary", {})
        ni        = data.get("net_impact", {})
        absences  = data.get("absence_impact", [])

        h_form    = ts.get("home_formation", "N/A")
        a_form    = ts.get("away_formation", "N/A")
        matchup   = ts.get("matchup_note", "")
        tilt      = ni.get("tilt_direction", "均势")
        tilt_rsn  = ni.get("tilt_reason", "")

        prose_lines.append(
            f"阵型对抗：主队 **{h_form}** vs 客队 **{a_form}**。{matchup}"
        )
        prose_lines.append(f"战力倾斜：**{tilt}**。{tilt_rsn}")

        high_abs = [a for a in absences if a.get("severity") == "HIGH"]
        if high_abs:
            abs_strs = []
            for a in high_abs:
                team   = a.get("team", "")
                player = a.get("player", "")
                reason = a.get("reason", "")
                xg     = a.get("xg_xa_share", 0)
                dfs    = a.get("def_share", 0)
                abs_strs.append(
                    f"{team} **{player}**（{reason}，进攻 {xg:.0%}，防守 {dfs:.0%}）"
                )
            prose_lines.append("关键缺阵：" + "；".join(abs_strs))
    except Exception:
        # JSON 解析失败，直接保留原始文本
        prose_lines.append(json_part.strip())

    prose = "\n\n".join(prose_lines)

    # ── 表格部分（有则用，空则兜底）────────────────────────
    if tables_part:
        # 确认首发场景：把 Agent3 输出的「预计首发简报」标题改为「✅ 确认首发名单」
        tables_part = tables_part.replace('### 预计首发简报', '### ✅ 确认首发名单')
        return f"{prose}\n\n{tables_part}"

    # 兜底：直接从 lineup_data 生成基础表格
    if lineup_data:
        fallback = _build_fallback_lineup_tables(lineup_data, home_name, away_name)
        return f"{prose}\n\n{fallback}"

    return f"{prose}\n\n> ℹ️ 首发阵容统计指标暂缺，阵容表格跳过。"


def _replace_lineup_section(report_path: str, new_agent3: str,
                             lineup_data: dict = None,
                             home_name: str = "主队", away_name: str = "客队") -> bool:
    """
    把现有研报里「## ⚔️ 战力评估/战术及战力损耗」段落替换为确认首发分析。
    - 从 new_agent3 中提取格式化内容（无原始 JSON，无 ---LINEUP_TABLES--- 分隔符）
    - 若 Agent 3 未生成表格（K 联赛等数据缺失场景），从 lineup_data 生成兜底表格
    成功返回 True，失败返回 False。
    """
    if not os.path.exists(report_path):
        log.warning(f"  报告文件不存在: {report_path}")
        return False

    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 格式化 agent3 输出
    formatted = _format_agent3_for_report(new_agent3, lineup_data, home_name, away_name)

    # 匹配所有已知的"阵容/战力"段落标题，包含：
    #   - ## ⚔️ 战术及战力损耗  (run_tonight 初始研报正常输出)
    #   - ## ⚔️ 战力评估        (旧版/LLM 变体)
    #   - ## ⚔️ 预测首发·贡献对比 (LLM 偶发发散输出)
    #   - ## ⚔️ 阵容攻防影响分析  (已确认首发后的标题，防止重跑时匹配失败)
    # 确认首发后整段替换为「阵容攻防影响分析」
    pattern = r'(## ⚔️ (?:战力评估|战术及战力损耗|阵容攻防影响分析|预测首发[·・]贡献对比|预测首发·贡献对比)[^\n]*\n)(.*?)(\n---|\Z)'
    new_section = rf'## ⚔️ 阵容攻防影响分析\n{formatted}\3'
    new_content, n = re.subn(pattern, new_section, content, flags=re.DOTALL)

    if n == 0:
        # 兜底：匹配所有 ## ⚔️ 开头的段落（覆盖 LLM 任意发散标题）
        pattern_fallback = r'(## ⚔️ [^\n]*\n)(.*?)(\n---|\Z)'
        new_content, n = re.subn(pattern_fallback, new_section, content, flags=re.DOTALL)

    if n == 0:
        log.warning(f"  未找到任何 ## ⚔️ 段落，无法替换（报告可能格式异常）")
        return False

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    return True


# ── Agent 3 重跑 ──────────────────────────────────────────

def _rerun_agent3(mid: str, match_name: str, lineup_data: dict) -> str | None:
    """用确认首发数据重跑 Agent 3，返回新的战力评估段落文本。"""
    try:
        # 走统一千问工厂，自带 primary→fallback（避开已耗尽模型 + 关联网搜索）
        llm = get_flash()
        parts = match_name.split(" vs ")
        state = {
            "match_id":   mid,
            "lineup_data": lineup_data,
            "match_info": {
                "home_name": parts[0].strip(),
                "away_name": parts[1].strip() if len(parts) > 1 else "",
            },
            "ml_output":   {},
            "odds_data":   {},
            "team_stats_summary": {},
            "agent1_output": "",
            "agent2_output": "",
            "agent3_output": "",
            "final_report":  "",
        }
        agent3_fn = build_agent_node(llm, AGENT3_SYSTEM_PROMPT, "agent3_output")
        result    = agent3_fn(state)
        output    = result.get("agent3_output", "")
        return output if len(output) > 50 else None
    except Exception as e:
        log.error(f"  ❌ Agent 3 运行失败: {e}")
        return None


# ── 主流程 ────────────────────────────────────────────────

def main(force_ids: list[str] | None = None):
    now   = datetime.now()
    today = date.today()

    with open(os.path.join(PROJECT_ROOT, "schedule", "target_matches.json"), encoding="utf-8") as f:
        matches = json.load(f)

    # ── 预加载 ML 模型 + 赔率索引（仅在需要时使用） ──
    _models_loaded  = False
    model_wdl = model_ou = FEATURES = None
    odds_index: dict = {}

    def _ensure_models_and_odds():
        nonlocal _models_loaded, model_wdl, model_ou, FEATURES, odds_index
        if _models_loaded:
            return
        log.info("⚙️  首次加载 ML 模型 + 赔率数据...")
        model_wdl, model_ou, FEATURES = load_models()
        odds_path = os.path.join(PROJECT_ROOT, "odds", "match_odds_data.json")
        if os.path.exists(odds_path):
            with open(odds_path, encoding="utf-8") as f:
                odds_raw = json.load(f)
            odds_index = {}
            for o in odds_raw:
                if "fotmob_id" not in o:
                    log.warning(f"[odds_load] 跳过损坏记录（缺 fotmob_id），keys={list(o.keys())[:4]}")
                    continue
                odds_index[str(o["fotmob_id"])] = o.get("odds", {})
        _models_loaded = True

    confirmed_ids  = _load_confirmed()
    newly_confirmed = []

    for m in matches:
        mid     = str(m["match_id"])
        kickoff = datetime.strptime(m["kickoff_time"], "%Y-%m-%d %H:%M:%S")
        mins_to_kickoff = (kickoff - now).total_seconds() / 60

        # ── 强制模式：忽略时间窗口 ──
        if force_ids:
            if mid not in force_ids:
                continue
        else:
            # 检查是否在轮询窗口内
            if not (POLL_END_MINS <= mins_to_kickoff <= POLL_START_MINS):
                if mins_to_kickoff > POLL_START_MINS:
                    log.debug(f"⏳ 尚未到窗口: {m['match_name']} (还有 {mins_to_kickoff:.0f} 分钟)")
                else:
                    log.info(f"⏭️  已过开球时间: {m['match_name']}")
                continue

        # ── 已确认首发，跳过 ──
        if mid in confirmed_ids and not force_ids:
            log.info(f"✅ 首发已确认，跳过轮询: {m['match_name']}")
            continue

        log.info(f"🔍 轮询首发 [{mins_to_kickoff:.0f}分钟后开球]: {m['match_name']}")

        # ── 抓取阵容 ──
        try:
            lineup_data = fetch_lineup(mid) or {}
        except Exception as e:
            log.error(f"  ❌ 阵容抓取异常: {e}")
            continue

        if not lineup_data:
            log.warning(f"  ⚠️ 暂未获取到阵容，等待下次轮询")
            continue

        status = lineup_data.get("status", "predicted")
        h_cnt  = len(lineup_data.get("home", {}).get("starters", []))
        a_cnt  = len(lineup_data.get("away", {}).get("starters", []))
        log.info(f"  状态: {status}  主队首发: {h_cnt}人  客队首发: {a_cnt}人")

        if status != "confirmed":
            log.info(f"  ℹ️ 仍为预测首发，等待下次轮询")
            continue

        # ── 拿到确认首发：重跑 Agent 3 更新研报 ──
        log.info(f"  🎉 获取到赛前确认首发！开始更新报告...")

        new_agent3 = _rerun_agent3(mid, m["match_name"], lineup_data)
        if not new_agent3:
            log.warning(f"  ⚠️ Agent 3 未能生成有效内容，跳过本次更新")
            continue

        report_date = kickoff.strftime("%Y-%m-%d")
        expected_report_path = os.path.join(REPORTS_DIR, f"report_{report_date}_{mid}.md")
        
        report_path = expected_report_path

        # 补救逻辑：如果按开球日期找不到，尝试模糊搜索该 match_id 的任何报告
        if not os.path.exists(report_path):
            import glob
            pattern = os.path.join(REPORTS_DIR, f"report_*_{mid}.md")
            found_files = glob.glob(pattern)
            if found_files:
                # 按修改时间倒序，取最新的一份
                found_files.sort(key=os.path.getmtime, reverse=True)
                old_report_path = found_files[0]
                log.info(f"    💡 匹配到最新报告: {os.path.basename(old_report_path)}")
                # 跨天重命名旧研报：把找到的旧前缀日期重命名为开球日期，并将原文件删除
                if old_report_path != expected_report_path:
                    try:
                        os.rename(old_report_path, expected_report_path)
                        log.info(f"    🔄 已将跨天旧研报重命名为当前日期版本: {os.path.basename(expected_report_path)}")
                        # 删除旧版本可能产生的冗余，os.rename 内部就是覆盖或者删除旧的文件名
                    except Exception as e:
                        log.warning(f"    ⚠️ 重命名旧研报失败: {e}")
                
        parts = m["match_name"].split(" vs ")
        _home = parts[0].strip()
        _away = parts[1].strip() if len(parts) > 1 else "客队"
        # ── 持久化阵容数据到 report_store ──────────────────────────────
        try:
            _conn_lu = sqlite3.connect(DB_PATH)
            try:
                _conn_lu.execute("ALTER TABLE report_store ADD COLUMN lineup_data TEXT")
            except Exception:
                pass  # 列已存在
            _conn_lu.execute(
                "UPDATE report_store SET lineup_data=? WHERE match_id=?",
                (json.dumps(lineup_data, ensure_ascii=False), mid)
            )
            _conn_lu.commit()
            _conn_lu.close()
            log.info(f"  💾 阵容数据已持久化到 report_store (match_id={mid})")
        except Exception as _lu_e:
            log.warning(f"  ⚠️ 持久化阵容数据失败: {_lu_e}")

        if _replace_lineup_section(report_path, new_agent3,
                                    lineup_data=lineup_data,
                                    home_name=_home, away_name=_away):
            log.info(f"  ✅ 研报战力评估段落已替换")

            # ── 触发赔率刷新 + 重算推荐方向，定稿 ──
            _ensure_models_and_odds()
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            try:
                log.info(f"  🔄 触发赔率刷新 + 定稿推荐方向...")
                ok = refresh_pick_for_match(
                    mid, m, conn, model_wdl, model_ou,
                    FEATURES, odds_index, today
                )
                if ok:
                    log.info(f"  📡 赔率刷新 + AWS 推送完成（定稿）")
                else:
                    log.warning(f"  ⚠️ 赔率刷新失败，尝试直接推送原研报...")
                    try:
                        from scripts.aws_pusher import push_match_payload
                        push_match_payload(mid)
                    except Exception as pe:
                        log.error(f"  💥 仅推送原研报也失败: {pe}")
            finally:
                conn.close()

            # ── 实体文件物理上传及云端旧版本剔除 ──
            try:
                log.info(f"  🚀 开始将最新物理 .md 强制同步至 AWS...")
                pem_key = os.environ.get("AWS_PEM_KEY", "")
                if not pem_key:
                    log.warning("  ⚠️ AWS_PEM_KEY 未设置，跳过物理同步")
                    raise ValueError("AWS_PEM_KEY not configured")
                aws_host = "ubuntu@54.168.246.157"
                remote_dir = "/home/ubuntu/app/backend/reports"
                
                # 1. 尝试删除服务器上属于此比赛的其他旧日期文件
                del_cmd = f"ssh -i {pem_key} {aws_host} 'find {remote_dir} -name \"report_*_{mid}.md\" ! -name \"{os.path.basename(report_path)}\" -exec rm -f {{}} +'"
                os.system(del_cmd)
                
                # 2. 上传最新版本
                scp_cmd = f"scp -i {pem_key} {report_path} {aws_host}:{remote_dir}/"
                os.system(scp_cmd)
                log.info(f"  ✅ AWS 远端旧报告清除并上传新报告成功: {os.path.basename(report_path)}")
            except Exception as e:
                log.error(f"  💥 AWS 物理同步报错: {e}")

            confirmed_ids.add(mid)
            newly_confirmed.append(m["match_name"])
        else:
            log.warning(f"  ⚠️ 报告替换失败，不标记为已确认")

    # ── 保存更新后的确认状态 ──
    if newly_confirmed:
        _save_confirmed(confirmed_ids)

    log.info(f"\n{'='*50}")
    if newly_confirmed:
        log.info(f"🎉 本次新确认首发并更新研报：{newly_confirmed}")
    else:
        log.info(f"📋 本次轮询：无新确认首发")


if __name__ == "__main__":
    # 支持 --force match_id 参数
    force = None
    if "--force" in sys.argv:
        idx   = sys.argv.index("--force")
        force = [str(x) for x in sys.argv[idx + 1:]]
        log.info(f"[强制模式] 指定 match_id: {force}")

    main(force_ids=force)
