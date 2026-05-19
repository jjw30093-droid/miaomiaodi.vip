"""
研报生成器 v2.0
支持四种模式：
  pre_match    - T-48h 初稿（量化基本面 + 基础赔率），生成后释放免费预览
  deep_analysis- T-10h 深度解析（最新盘口变化 + 深度战术），付费墙内容
  final        - T-50min 终版（追加首发阵容分析），触发订阅推送
  review       - T+2h 复盘（预测 vs 实际，射门分布图），归档后公开
"""
import os, json, sqlite3, re
from datetime import datetime

PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
DB_PATH       = os.path.join(PROJECT_ROOT, "football_uk.db")
REPORTS_DIR   = os.path.join(PROJECT_ROOT, "reports")
SCHEDULE_FILE = os.path.join(PROJECT_ROOT, "schedule", "target_matches.json")
ODDS_FILE     = os.path.join(PROJECT_ROOT, "odds", "match_odds_data.json")
# 注：原 GOOGLE_API_KEY 已废弃，LLM 调用全走 qwen_client.get_flash()

os.makedirs(REPORTS_DIR, exist_ok=True)

# ──────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────
def _get_llm(model=None, temperature=0.2):
    """
    ⚠️ 已迁移：忽略 model/temperature 参数，统一走 qwen_client.get_flash()
    （原 Gemini 接入已废弃，CLAUDE.md §A4 上线前修复）
    """
    from qwen_client import get_flash
    return get_flash()

def _get_report_path(match_id: str) -> str | None:
    for f in os.listdir(REPORTS_DIR):
        if f.endswith(f"_{match_id}.md") and not f.startswith("_"):
            return os.path.join(REPORTS_DIR, f)
    return None

def _build_report_filename(match_id: str, match: dict) -> str:
    home = match.get("home_team", "Home").replace(" ", "_")
    away = match.get("away_team", "Away").replace(" ", "_")
    return os.path.join(REPORTS_DIR, f"研报_{home}_vs_{away}_{match_id}.md")

def _extract_preview(content: str, max_chars: int = 800) -> str:
    """
    提取免费预览内容：
    取研报第一个 H2 段落（## 开头）到第二个 ## 之间的内容
    若不足 max_chars 则取前 max_chars 字符
    """
    lines = content.split("\n")
    preview_lines = []
    h2_count = 0
    for line in lines:
        if line.startswith("## "):
            h2_count += 1
            if h2_count == 2:
                break
        preview_lines.append(line)
    preview = "\n".join(preview_lines)
    if len(preview) > max_chars:
        preview = preview[:max_chars] + "\n\n> *⚡ 完整深度解析需订阅喵弟量化实验室*"
    return preview

def _sync_to_report_store(match_id: str, match: dict, content: str,
                           mode: str, preview: str = ""):
    """将研报写入 report_store，同步 pipeline_status"""
    # 提取概率（从内容中解析，或使用默认值）
    diff_m = re.search(r"npxGD Diff\s*\(([\d\.\-]+)\)", content)
    diff   = float(diff_m.group(1)) if diff_m else 0.0
    home_prob = round(max(10, min(90, 50 + diff * 15)), 1)
    away_prob = round(max(10, min(90, 30 - diff * 5)), 1)

    # 提取推论 —— 优先抓「量化结论」，兜底抓判定段首句
    inference = "—"
    # 优先级1：量化结论（最准确的最终判定）
    quant_m = re.search(r"\*{0,2}(?:量化结论|量化预判)[：:]\*{0,2}\s*(.+?)(?:。|$)", content, re.MULTILINE)
    if quant_m:
        inference = "量化结论：" + quant_m.group(1).strip().split("。")[0] + "。"
    else:
        # 优先级2：喵弟模型判定段落的「量化结论」子行
        block_m = re.search(
            r"### \s*(?:\d+[\.\s]*)?喵弟模型判定.*?量化结论[：:]\s*(.+?)(?:。|$)",
            content, re.DOTALL | re.MULTILINE
        )
        if block_m:
            inference = "量化结论：" + block_m.group(1).strip().split("。")[0] + "。"
        else:
            # 兜底：取判定段首句（原逻辑）
            inf_m = re.search(r"### \s*(?:\d+[\.\s]*)?喵弟模型判定\s*\n+(.*)", content)
            if inf_m:
                inference = inf_m.group(1).strip().split("。")[0] + "。"

    league   = match.get("league", "UNKNOWN")
    home_id  = match.get("home_team_id", 0)
    away_id  = match.get("away_team_id", 0)
    kickoff  = match.get("kickoff_time", "")
    m_time   = kickoff[5:16] if kickoff and len(kickoff) > 16 else kickoff
    h_icon   = f"https://images.fotmob.com/image_resources/logo/teamlogo/{home_id}.png"
    a_icon   = f"https://images.fotmob.com/image_resources/logo/teamlogo/{away_id}.png"

    # HOT 状态判断：写死神户或首场 J 联赛
    report_status = "HOT" if str(match_id) == "5130428" else "FREE"

    conn = sqlite3.connect(DB_PATH)
    # 使用 OR REPLACE 保证幂等
    conn.execute("""
        INSERT OR REPLACE INTO report_store
            (match_id, title, markdown_content, preview_content,
             home_team, away_team, home_icon, away_icon,
             home_prob, away_prob, league, match_time,
             status, inference, pipeline_status, is_archived, is_public)
        VALUES (?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?, 0, 0)
    """, [
        str(match_id),
        f"研报: {match.get('home_team','Home')} vs {match.get('away_team','Away')}",
        content, preview,
        match.get("home_team","Home"), match.get("away_team","Away"),
        h_icon, a_icon,
        home_prob, away_prob,
        league, m_time,
        report_status, inference,
        {"pre_match": "PRE_MATCH_READY", "deep_analysis": "ANALYSIS_UPDATED",
         "final": "FINAL_REPORT_READY", "review": "REVIEW_GENERATED"}.get(mode, mode.upper())
    ])
    conn.commit()
    conn.close()

def _ensure_match_in_schedule(match_id: str, match: dict):
    """确保 match 信息在 target_matches.json 中（workflow.py 需要读它）"""
    schedule = []
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                schedule = json.load(f)
        except Exception:
            schedule = []
            
    existing_ids = {str(m.get("match_id")) for m in schedule}
    if str(match_id) not in existing_ids:
        schedule.append({
            "match_id": match_id,
            "match_name": f"{match.get('home_team','Home')} vs {match.get('away_team','Away')}",
            "home_id":    match.get("home_team_id", 0),
            "away_id":    match.get("away_team_id", 0),
            "league":     match.get("league", "UNKNOWN"),
            "kickoff_time": match.get("kickoff_time", "")
        })
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(schedule, f, ensure_ascii=False, indent=2)

# ──────────────────────────────────────────
# 四种生成模式
# ──────────────────────────────────────────
def _mode_pre_match(match_id: str, match: dict) -> str:
    """T-48h：调用完整 workflow 生成初稿"""
    from workflow import app_graph
    _ensure_match_in_schedule(match_id, match)
    initial_state = {
        "match_id": str(match_id),
        "league":   match.get("league", "UNKNOWN"),
        "quant_data": "", "market_data": "", "context_data": "",
        "agent1_quant_res": "", "agent2_market_res": "",
        "agent3_context_res": "", "fotmob_details_data": "",
        "agent5_intel_res": "", "final_report": ""
    }
    result = app_graph.invoke(initial_state)
    return result.get("final_report", "")

def _mode_deep_analysis(match_id: str, match: dict, existing_content: str) -> str:
    """T-10h：读取最新盘口数据，追加深度解析段落"""
    # 读取最新赔率
    latest_odds = {}
    if os.path.exists(ODDS_FILE):
        with open(ODDS_FILE, "r", encoding="utf-8") as f:
            try:
                all_odds = json.load(f)
            except Exception:
                all_odds = []
        match_obj = next(
            (o for o in all_odds if str(o.get("fotmob_id")) == str(match_id)), None
        )
        if match_obj:
            latest_odds = match_obj.get("odds", {})

    odds_summary = json.dumps(latest_odds, ensure_ascii=False)[:1500] if latest_odds else "暂无最新盘口数据"

    prompt = f"""你是喵弟量化实验室的首席盘口分析师。
距比赛开球不足10小时，请基于以下最新赔率数据生成深度盘口解析（200字以内，中文，Markdown格式）：

最新赔率：
{odds_summary}

比赛：{match.get('home_team','主队')} vs {match.get('away_team','客队')}

生成格式：
## 🔬 深度盘口解析（T-10h 更新）· {datetime.now().strftime('%m-%d %H:%M')}

[分析内容，重点指出盘口变化信号和机构博弈迹象]

**核心结论：** [一句话判断]
"""
    llm = _get_llm()
    from langchain_core.messages import HumanMessage
    msg = llm.invoke([HumanMessage(content=prompt)])
    analysis = msg.content if isinstance(msg.content, str) else str(msg.content)
    return existing_content + "\n\n\n" + analysis

def _mode_final(match_id: str, match: dict, existing_content: str) -> str:
    """T-50min：追加首发阵容分析"""
    # 读取首发数据
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT lineup_json FROM match_pipeline WHERE match_id=?", [str(match_id)]
    ).fetchone()
    conn.close()

    lineup = {}
    if row and row["lineup_json"]:
        try:
            lineup = json.loads(row["lineup_json"])
        except Exception:
            pass

    home_lineup = lineup.get("home", {})
    away_lineup = lineup.get("away", {})
    home_players = ", ".join(
        [p.get("name","") for p in home_lineup.get("players", [])[:11] if p.get("name")]
    ) or "首发数据待确认"
    away_players = ", ".join(
        [p.get("name","") for p in away_lineup.get("players", [])[:11] if p.get("name")]
    ) or "首发数据待确认"

    prompt = f"""分析以下首发阵容对比赛走势的影响（150字以内，中文，Markdown格式）：

{match.get('home_team','主队')} ({home_lineup.get('formation','N/A')})：{home_players}
{match.get('away_team','客队')} ({away_lineup.get('formation','N/A')})：{away_players}

关注点：关键球员缺阵/复出对 xG 的影响，阵型克制关系。
"""
    llm = _get_llm()
    from langchain_core.messages import HumanMessage
    msg = llm.invoke([HumanMessage(content=prompt)])
    analysis = msg.content if isinstance(msg.content, str) else str(msg.content)

    final_section = f"""

---

## ⚡ 终版首发分析（T-50min）· {datetime.now().strftime('%m-%d %H:%M')}

| 球队 | 阵型 | 首发 |
|------|------|------|
| {match.get('home_team','主队')} | {home_lineup.get('formation','N/A')} | {home_players} |
| {match.get('away_team','客队')} | {away_lineup.get('formation','N/A')} | {away_players} |

{analysis}
"""
    return existing_content + final_section

def _mode_review(match_id: str, match: dict, existing_content: str,
                 postmatch_data: dict) -> str:
    """T+2h：生成赛后复盘段落"""
    final_score  = postmatch_data.get("final_score", "? - ?")
    stats_text   = postmatch_data.get("stats_summary", "赛后数据整理中...")
    home_team    = match.get("home_team", "主队")
    away_team    = match.get("away_team", "客队")

    prompt = f"""你是喵弟量化实验室的复盘分析师。
最终比分：{home_team} {final_score} {away_team}

赛后统计：
{stats_text}

原始研报摘要（仅供参考）：
{existing_content[:1500]}

请生成复盘段落（250字以内，中文，Markdown格式），
重点分析：预测模型命中情况、关键数据偏差原因、模型改进方向。
"""
    llm = _get_llm(temperature=0.3)
    from langchain_core.messages import HumanMessage
    msg = llm.invoke([HumanMessage(content=prompt)])
    review = msg.content if isinstance(msg.content, str) else str(msg.content)

    return existing_content + f"""

---

## 📊 赛后复盘 · POST-MATCH REVIEW · {datetime.now().strftime('%m-%d %H:%M')}

**最终比分：{home_team} {final_score} {away_team}**

{review}

---
*复盘由 喵弟量化实验室 AI 自动生成 · 数据来源：FotMob*
"""

# ──────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────
def generate_report(match_id: str, match: dict, mode: str,
                    postmatch_data: dict = None):
    """
    统一入口，pipeline_manager 调用
    mode: 'pre_match' | 'deep_analysis' | 'final' | 'review'
    """
    print(f"\n{'='*50}")
    print(f"📝 [{match_id}] 模式: {mode.upper()}")
    print(f"🏟️  {match.get('home_team')} vs {match.get('away_team')}")

    existing_path    = _get_report_path(match_id)
    existing_content = ""
    if existing_path and os.path.exists(existing_path):
        with open(existing_path, "r", encoding="utf-8") as f:
            existing_content = f.read()

    if mode == "pre_match":
        content = _mode_pre_match(match_id, match)
    elif mode == "deep_analysis":
        if not existing_content:
            print(f"⚠️ [{match_id}] 无初稿，退化为 pre_match")
            content = _mode_pre_match(match_id, match)
        else:
            content = _mode_deep_analysis(match_id, match, existing_content)
    elif mode == "final":
        if not existing_content:
            print(f"⚠️ [{match_id}] 无初稿，退化为 pre_match")
            content = _mode_pre_match(match_id, match)
        else:
            content = _mode_final(match_id, match, existing_content)
    elif mode == "review":
        content = _mode_review(match_id, match, existing_content,
                               postmatch_data or {})
    else:
        raise ValueError(f"未知模式: {mode}")

    if not content.strip():
        raise ValueError(f"[{match_id}] 生成内容为空")

    # 保存文件
    filepath = existing_path or _build_report_filename(match_id, match)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ 研报已保存: {os.path.basename(filepath)}")

    # 提取预览（仅 pre_match 模式生成）
    preview = _extract_preview(content) if mode == "pre_match" else ""

    # 写入 report_store
    _sync_to_report_store(match_id, match, content, mode, preview)
    print(f"✅ [{match_id}] {mode.upper()} 完成")

if __name__ == "__main__":
    import sys
    mid  = sys.argv[1] if len(sys.argv) > 1 else "5130428"
    mode = sys.argv[2] if len(sys.argv) > 2 else "pre_match"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM match_pipeline WHERE match_id=?", [mid]
    ).fetchone()
    conn.close()
    m = dict(row) if row else {
        "home_team": "Vissel Kobe", "away_team": "Shimizu S-Pulse",
        "home_team_id": 4688, "away_team_id": 4426,
        "league": "J. LEAGUE", "kickoff_time": "2026-04-01 18:00:00"
    }
    generate_report(mid, m, mode)
