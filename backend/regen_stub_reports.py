"""
regen_stub_reports.py
====================
紧急补全：为 LLM 叙事模块回退（stub）的报告重新生成完整叙事。
直接在服务器上调用 Gemini，不依赖本地 Mac pipeline。

运行方法：
  python regen_stub_reports.py                         # 处理所有 stub
  python regen_stub_reports.py --match_id 5173387      # 单场
"""
import os, sys, json, sqlite3, re, logging, argparse
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJECT_ROOT, "football_uk.db")

# 从 .env 加载 DASHSCOPE_API_KEY（迁移后入口）
if not os.getenv("DASHSCOPE_API_KEY"):
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ[k] = v

if not os.environ.get("DASHSCOPE_API_KEY"):
    raise RuntimeError("DASHSCOPE_API_KEY not set!")

# ─── LLM setup（迁移到千问，CLAUDE.md §A4） ─────────────────────────────────
from langchain_core.messages import HumanMessage, SystemMessage
from qwen_client import get_flash

llm = get_flash()  # 含 fallback + 关联网搜索

NARRATIVE_SYSTEM_PROMPT = """你是「喵弟量化研究所」的首席策略分析师，负责基于算法模型输出的量化数据撰写深度研报叙事。

# 铁律
1. **绝对禁止修改任何概率数值与统计指标**。
2. **绝对不得编造事实**，彻底剔除AI机械感套话（"总体来看"、"综上所述"、"不容忽视"等全部禁用）。
3. **禁止极端确定性表述**：严禁"100%"、"绝对"、"必胜"、"铁定"、"毫无悬念"。
4. **全文绝对禁止英语单词**。
5. **结论区严禁多选**，只遵循唯一推荐方向。
6. **所有数值必须原封不动从输入数据引用**，不得改动小数点后任何位数。

# 特征名中英对照
主队对手强度加权进球差/home_roll_opp_adj_npxgd→近期对手强度修正后的主客场进球差
客队对手强度加权进球差/away_roll_opp_adj_npxgd→客队对手强度修正后进球差
欧赔隐含客胜概率→市场赔率暗含的客队胜率
主队落后时进攻比→主队落后时进攻转化效率
非罚进球差绝对值→不含点球的进球差绝对值
大小球盘口/ah_away_odds→亚盘客队赔率信号
"""

def get_stub_matches(match_id: str = None) -> list:
    """获取所有 stub 报告（或指定 match_id）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if match_id:
        cur.execute("""
            SELECT rs.match_id, rs.home_team, rs.away_team, rs.league, rs.match_time,
                   rs.markdown_content, mp.npxg_trend, mp.shot_map_data
            FROM report_store rs
            LEFT JOIN match_payloads mp ON rs.match_id = mp.match_id
            WHERE rs.match_id = ?
        """, (match_id,))
    else:
        cur.execute("""
            SELECT rs.match_id, rs.home_team, rs.away_team, rs.league, rs.match_time,
                   rs.markdown_content, mp.npxg_trend, mp.shot_map_data
            FROM report_store rs
            LEFT JOIN match_payloads mp ON rs.match_id = mp.match_id
            WHERE rs.markdown_content LIKE '%LLM 叙事模块异常回退%'
        """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def format_npxg_summary(npxg_trend_json: str, home_team: str, away_team: str) -> str:
    """将 npxg_trend 格式化为可读摘要"""
    if not npxg_trend_json:
        return "近期数据暂缺"
    try:
        data = json.loads(npxg_trend_json) if isinstance(npxg_trend_json, str) else npxg_trend_json
        def format_team(team_data: dict, name: str) -> str:
            matches = team_data.get("matches", [])
            if not matches:
                return f"{name}：近期数据暂缺"
            lines = [f"{name} 近{len(matches)}场 npxGD 走势："]
            for m in matches[-5:]:
                opp = m.get("opponent", "?")
                diff = m.get("npxg_diff", 0)
                sign = "+" if diff >= 0 else ""
                lines.append(f"  vs {opp}: {sign}{diff:.2f}")
            return "\n".join(lines)
        
        home_lines = format_team(data.get("home_team", {}), home_team)
        away_lines = format_team(data.get("away_team", {}), away_team)
        return home_lines + "\n\n" + away_lines
    except Exception as e:
        log.warning(f"npxg_trend 解析失败: {e}")
        return "近期数据解析异常"

def build_prompt(match: dict) -> str:
    """构造 Gemini prompt，包含量化数据 + 叙事生成指令"""
    home = match["home_team"]
    away = match["away_team"]
    league = match["league"] or "未知联赛"
    match_time = match["match_time"] or ""
    stub_content = match["markdown_content"] or ""
    npxg_summary = format_npxg_summary(match.get("npxg_trend"), home, away)

    return f"""你将为以下比赛生成完整的深度量化研报叙事。

# 比赛信息
- **主队**: {home}
- **客队**: {away}
- **联赛**: {league}
- **开赛时间**: {match_time}

# 已有量化基准数据（原封不动保留到报告中）
{stub_content}

# 近期表现趋势
{npxg_summary}

# 任务要求
基于以上量化数据，生成一份完整的研报。要求：

1. **报告标题行**：
   `# {home} vs {away} · 深度量化研报`
   `> 📊 客观数据驱动 | 🤖 算法模型推演 | 🧪 关键特征归因解读`
   `> 📅 比赛时间：{match_time} | 赛事体系：{league}`
   `---`

2. **完整复制以下量化基准线部分**（必须原封不动，不改任何数字）：
   从"## 🔬 量化概率基准线"到"## ⚔️ 战力评估"结束（含战力评估中的首发/缺阵部分）。

3. **新增叙事分析段落**（按以下顺序，每段 150-250 字）：

## 💹 市场交易价值 · 盘口信号解读
分析：利用已有的胜平负概率（主胜{_extract_prob(stub_content, '主胜')}%、平局{_extract_prob(stub_content, '平局')}%、客胜{_extract_prob(stub_content, '客胜')}%），结合亚盘赔率（λ值），解读市场对两队实力的定价逻辑。分析是否存在价值错位，机构资金流向何方。

## ⚡ 战力对比 · 近期状态解读
分析：结合 Elo 评分差、npxGD 走势数据，深度解读两队近期真实竞技状态。重点关注主队Elo与近期npxGD是否一致，客队缺阵对战力的实际影响。

## 🎯 喵弟模型判定
基于所有数据，给出以下格式的最终判定：
- **推荐方向**：[从量化数据中读取的推荐方向]
- **量化结论**：[一句话结论，包含关键概率数据，不超过50字]
- **风险提示**：[一句话，描述最可能使本次推荐失效的因素]

---
> ⚠️ 免责声明：本研报由 ML 模型 + AI 叙事模块自动生成，概率仅供参考，不构成投注建议。
> 🏷️ 喵弟量化研究所 · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC
"""

def _extract_prob(content: str, direction: str) -> str:
    """从 stub 内容中提取概率数值"""
    try:
        # 匹配表格中的概率
        patterns = {
            '主胜': r'\|\s*\*\*胜平负\*\*\s*\|\s*([\d\.]+)%',
            '平局': r'\|\s*\*\*胜平负\*\*[^|]+\|\s*[\d\.]+%\s*\|\s*([\d\.]+)%',
            '客胜': r'\|\s*\*\*胜平负\*\*[^|]+\|\s*[\d\.]+%\s*\|\s*[\d\.]+%\s*\|\s*([\d\.]+)%',
        }
        m = re.search(patterns.get(direction, ''), content)
        return m.group(1) if m else "?"
    except Exception:
        return "?"

def generate_narrative(match: dict) -> str:
    """调用 Gemini 生成叙事"""
    prompt = build_prompt(match)
    log.info(f"  Calling Gemini for {match['match_id']} ({match['home_team']} vs {match['away_team']})...")
    
    try:
        resp = llm.invoke([
            SystemMessage(content=NARRATIVE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        return content.strip()
    except Exception as e:
        log.error(f"  Gemini failed: {e}")
        raise

def extract_inference(content: str) -> str:
    """从报告中提取 inference 字段"""
    patterns = [
        r'\*{0,2}量化结论[：:]\*{0,2}\s*(.+?)(?:。|$)',
        r'推荐方向[：:]\s*(.+?)(?:\n|$)',
    ]
    for pat in patterns:
        m = re.search(pat, content, re.MULTILINE)
        if m:
            return m.group(1).strip().split("。")[0] + "。"
    return "AI 分析中..."

def update_db(match_id: str, new_content: str, home_prob: float, away_prob: float):
    """更新 match_payloads 和 report_store"""
    now_iso = datetime.now(timezone.utc).isoformat()
    inference = extract_inference(new_content)
    
    conn = sqlite3.connect(DB_PATH)
    try:
        # 更新 match_payloads
        conn.execute("""
            UPDATE match_payloads SET report_markdown = ?, updated_at = ?
            WHERE match_id = ?
        """, (new_content, now_iso, str(match_id)))
        
        # 更新 report_store
        conn.execute("""
            UPDATE report_store 
            SET markdown_content = ?, inference = ?
            WHERE match_id = ?
        """, (new_content, inference, str(match_id)))
        
        conn.commit()
        log.info(f"  DB updated for {match_id} ({len(new_content)}c)")
    finally:
        conn.close()

def process_match(match: dict):
    mid = match["match_id"]
    home = match["home_team"]
    away = match["away_team"]
    log.info(f"\n{'='*55}")
    log.info(f"Processing {mid}: {home} vs {away}")
    log.info(f"  Current stub length: {len(match['markdown_content'] or '')}c")
    
    new_content = generate_narrative(match)
    if not new_content or len(new_content) < 500:
        log.error(f"  Generated content too short ({len(new_content)}c), skipping")
        return False
    
    log.info(f"  Generated {len(new_content)}c narrative")
    
    # Get probs from report_store
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT home_prob, away_prob FROM report_store WHERE match_id=?", (mid,)).fetchone()
    conn.close()
    home_prob = float(row["home_prob"] or 50) if row else 50.0
    away_prob = float(row["away_prob"] or 30) if row else 30.0
    
    update_db(mid, new_content, home_prob, away_prob)
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--match_id", help="单场比赛 ID")
    args = parser.parse_args()
    
    matches = get_stub_matches(args.match_id)
    if not matches:
        log.info("No stub reports found to process.")
        return
    
    log.info(f"Found {len(matches)} stub report(s) to regenerate:")
    for m in matches:
        log.info(f"  {m['match_id']}: {m['home_team']} vs {m['away_team']} ({m['match_time']})")
    
    success = 0
    for m in matches:
        try:
            if process_match(m):
                success += 1
        except Exception as e:
            log.error(f"  Failed {m['match_id']}: {e}")
    
    log.info(f"\n{'='*55}")
    log.info(f"Done: {success}/{len(matches)} reports regenerated.")

if __name__ == "__main__":
    main()
