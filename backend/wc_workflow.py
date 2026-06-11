"""
wc_workflow.py
==============
世界杯研报 LangGraph 4-Agent 生成工作流。

与联赛 workflow.py **硬隔离**：
  - 自定义 WC 专属提示词（允许 WDL；OU 仅展示；AH 仅幅度；无 xG/shotmap/球员数据）
  - 复用 build_agent_node / build_workflow 节点构造器（[REUSE-IMPORT]，不改 workflow.py）
  - 自定义 WcMatchReportState（无 lineup_data/xG 字段；有 wc_team_stats / ou_display / ah_info）

禁语护栏（运行期 grep 可验证）：
  - 无 跟单稳赚 / 胜率保证 / 热钱信号
  - 无 market-80 历史准确率（54.5% / 61%）
  - 无 "前 N 场回归" 话术
  - OU 必须带 "历史基线建立中，2026实盘滚动验证"
  - AH 仅幅度，绝不胜率
"""

import json
import logging
import re
from typing import TypedDict, Optional

log = logging.getLogger(__name__)

# ── LangGraph imports ──
try:
    from langgraph.graph import StateGraph, END
    from langchain_core.messages import HumanMessage
    from langchain_core.language_models import BaseChatModel
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False
    log.warning("[wc_workflow] langgraph not installed")

# [REUSE-IMPORT] 复用联赛 workflow 节点构造器（只读，不改 workflow.py）
from workflow import build_agent_node  # type: ignore


# ══════════════════════════════════════════════════════════════════════════════
# Section 1: WC State
# ══════════════════════════════════════════════════════════════════════════════

class WcMatchReportState(TypedDict):
    """LangGraph 状态：WC 专属字段（无 xG/shotmap/球员/lineup_impact）"""

    # ── 输入 ──
    match_id:   str
    match_info: dict      # {home_name, away_name, match_time, league, fixture_id}

    wc_ml_output: dict    # wc_predict() 返回值
                          # {wdl:{home,draw,away}, ou:{...}, divergence, n_books_wdl, source}

    wc_team_stats: dict   # wc_statistics 原始聚合（~40 类）
                          # {home: {Shots,ShotsOnTarget,InsideBox,OutsideBox,BCC,DangerousAttacks,Possession,...},
                          #  away: {...}}
                          # BCC=None 表示缺失（条件渲染，不插值）

    ou_display: dict      # ou_consensus（仅展示）
                          # {line, over, under, n_books, split, baseline_disclaimer}

    ah_info: dict         # ah_implied（仅信息）
                          # {line, magnitude, n_books}  绝无胜率

    single_pick: dict     # wc_select_single_pick() 返回值
                          # {picked_market, picked_direction, picked_odds,
                          #  picked_confidence, inference, caution_text}
                          # SKIP 场次 = {}

    prebuilt_quant_section: str  # Python 生成的 WDL/OU/AH 数值段（不让 LLM 重算）

    # ── cc 站增强数据（可能为空 dict/list，agent 必须容错）──
    cc_predictions:  dict   # Sportmonks 模型预测 {fulltime_result, over_under_2_5, btts, ...}
    predicted_lineup: list  # 预计首发 [{team_sportmonks_id, player_name, player_name_zh,
                            #             jersey_number, position, formation_position, confidence}...]
    home_recent:     list   # 主队近 N 场 [{match_label, starting_at, state_short_name, ...}...]
    away_recent:     list   # 客队近 N 场
    recent_compare:  dict   # 近期对比 {windows, home, away}
    h2h:             list   # 历史交锋
    cc_home_team_id: int    # 主队 Sportmonks ID（用于 lineup 分组）
    cc_away_team_id: int    # 客队 Sportmonks ID

    # ── Agent 中间输出 ──
    agent1_output: str
    agent2_output: str
    agent3_output: str

    # ── 最终输出 ──
    final_report: str


# ══════════════════════════════════════════════════════════════════════════════
# Section 2: WC Agent System Prompts
# ══════════════════════════════════════════════════════════════════════════════

WC_AGENT1_SYSTEM_PROMPT = """# 角色
你是世界杯数据提取模块。提取原始队伍统计信号，输出结构化 JSON 供后续分析使用。

# 铁律
1. **仅输出合法 JSON**，不写叙事文字，不加 markdown 围栏。
2. **绝对禁止自行计算概率**，所有数值直接引用输入。
3. **所有文本字段使用中文**。
4. **BCC（BigChancesCreated）字段如果为 null，必须在 signals 里注明"大机会数据缺失"，绝对不得插值估算**。
5. 世界杯没有 xG / NPXGD / 射门坐标数据，禁止提及或引用。

# 输入数据
wc_team_stats: 双方队伍统计（Shots/ShotsOnTarget/InsideBox/OutsideBox/BCC/DangerousAttacks/Possession）
match_info: 比赛基本信息

# 输出格式（严格 JSON）
{
  "home_signals": {
    "shots_total": <number|null>,
    "shots_on_target": <number|null>,
    "inside_box": <number|null>,
    "outside_box": <number|null>,
    "big_chances": <number|"缺失"|null>,
    "dangerous_attacks": <number|null>,
    "possession_pct": <number|null>
  },
  "away_signals": { <同上> },
  "key_observations": ["最多 4 条，每条 20 字内，纯中文，直接引用数值，禁止估算 BCC 缺失项"],
  "bcc_available": <true|false>,
  "data_notes": "<如有数据缺失或异常，一句话说明；否则写 null>"
}"""

WC_AGENT2_SYSTEM_PROMPT = """# 角色
你是世界杯盘口解读模块。分析 WDL 市场共识、OU/AH 盘口信息、以及第三方模型预测，输出结构化 JSON。

# 铁律
1. **仅输出合法 JSON**，不写叙事文字，不加 markdown 围栏。
2. **绝对禁止自行计算概率**，数值全部引用输入。
3. **OU 必须标注** "历史基线建立中，2026实盘滚动验证"，绝对禁止引用历史准确率。
4. **AH 仅幅度信息（market 让球幅度=N球）**，绝对禁止给出 AH 胜率或推荐。
5. **WDL 推荐** 只能来自 single_pick 字段，不可自行判断方向。
6. 禁止任何"热钱信号 / 资金流向 / 庄家意图"等话术。
7. **cc_predictions 字段是第三方模型预测**，仅作参考视角展示，不得用它覆盖或替换市场共识。
8. 所有文本字段使用中文。

# 输入数据
wc_ml_output: WDL 市场共识概率 + 书商数量 + 离散度
ou_display: OU Goal Line 展示数据（含免责声明）
ah_info: AH 市场隐含让球幅度（仅幅度，无胜率）
single_pick: WC 单推选择结果（可能为 {} 代表 SKIP）
cc_predictions: 第三方模型预测数据（若为空 dict 则跳过模型对标分析）
  - fulltime_result: {home, draw, away} 模型 WDL 概率（%）
  - over_under_2_5: {over, under} 大小球概率
  - both_teams_to_score: {yes, no} 双方进球概率

# 输出格式（严格 JSON）
{
  "wdl_analysis": {
    "market_consensus": "<一句话描述三方向概率分布，带具体数值，中文>",
    "n_books": <number>,
    "divergence_level": "<低|中|高>",
    "recommended_direction": "<主胜|平局|客胜|观望>",
    "confidence_label": "<HIGH|MID|LOW|SKIP>"
  },
  "ou_analysis": {
    "line": "<线值，如 2.5 或 2.0/2.5>",
    "over_prob": <number|null>,
    "under_prob": <number|null>,
    "note": "历史基线建立中，2026实盘滚动验证",
    "commentary": "<一句话说明进球趋势预期，20 字内>"
  },
  "ah_analysis": {
    "line": <number|null>,
    "magnitude": <number|null>,
    "commentary": "<一句话描述市场让球幅度含义，20 字内，严禁给出 AH 胜率>"
  },
  "model_vs_market": {
    "available": <true|false>,
    "model_home_pct": <number|null>,
    "model_draw_pct": <number|null>,
    "model_away_pct": <number|null>,
    "market_home_pct": <number|null>,
    "gap_summary": "<一句话描述模型与市场最大分歧方向及幅度，如有 available=false 写 null>",
    "btts_model_pct": <number|null>,
    "disclaimer": "第三方模型预测，2026实盘待验证，仅供参考"
  },
  "market_vs_model_edge": "<一句话说明市场共识与单推逻辑的契合度，20 字内>"
}"""

WC_AGENT3_SYSTEM_PROMPT = """# 角色
你是世界杯战力评估模块。基于队伍统计和市场共识，综合评估双方攻防战力。

# 铁律
1. **仅输出合法 JSON**，不写叙事文字，不加 markdown 围栏。
2. **世界杯无 xG / NPXGD / 射门坐标 / 球员级数据**，禁止提及这些指标。
3. **BCC 缺失时**，攻击星级评估必须注明"基于 Shots/DangerousAttacks（BCC 数据缺失）"，不得给满星。
4. 所有评分 1-5 分，根据输入数值相对比较得出，不得编造。
5. 所有文本字段使用中文。
6. 禁止出现 跟单稳赚 / 胜率保证 / 前 N 场回归 等话术。

# 输入数据
agent1_output: 队伍统计信号（JSON）
agent2_output: 盘口分析（JSON）

# 输出格式（严格 JSON）
{
  "home_power": {
    "attack_rating": <1-5 整数>,
    "defense_rating": <1-5 整数>,
    "form_label": "<上升期|稳定期|低迷期>",
    "attack_basis": "<评分依据一句话，引用具体数值，20 字内>"
  },
  "away_power": {
    "attack_rating": <1-5 整数>,
    "defense_rating": <1-5 整数>,
    "form_label": "<上升期|稳定期|低迷期>",
    "attack_basis": "<评分依据一句话，引用具体数值，20 字内>"
  },
  "relative_edge": "<一句话描述哪方在哪个维度占优，20 字内>",
  "bcc_disclaimer": "<true=有 BCC 数据；false=BCC 缺失，需免责声明>",
  "power_summary": "<一句话综合战力对比，25 字内，不提 xG>"
}"""

WC_AGENT4_SYSTEM_PROMPT = """# 角色
你是一名有十年经验的足球记者，同时兼任付费订阅用户的赛前分析顾问。
你的任务：把数据信号转化成一篇**有观点、有温度**的赛前分析，让用户觉得是行家在跟他说话，而不是在读机器报告。

# 写作铁律
1. **口吻**：直接、简练、有主见。不用套话开头，不用"综合来看""值得注意的是""不难发现"。
   - ✗ "本场市场共识呈现典型的三方胶着格局"
   - ✓ "赔率基本三分天下，盘口没给出明确方向"
2. **禁用词**（出现即视为错误）：价值边际、算法模型、第三方算法、主流资金、认知鸿沟、定价、隐含概率、量化、建模、数据驱动、市场隐含、统计显著
3. 若有独立预测机构的概率数据与盘口存在明显差距，**用一句话自然带出即可**，不要把它渲染成分析核心，更不要用"价值边际""模型低估"等词。
4. **推荐**由 single_pick 决定，正文必须与 inference 字段完全一致：
   - wdl → 主胜/平局/客胜 + 赔率
   - ah → "{队} 让 N 球 @赔率"，加一句"亚盘参考，不构成投注建议"
   - SKIP → 说清楚为什么不好下，建议观望
5. 全文中文，球队名用输入提供的中文名，禁止英文单词（包括队名）。
6. 禁止出现 xG / NPXGD / 期望进球 / 射门坐标。
7. **绝对不放表格**，数据卡片已在前端单独展示。
8. 不引用任何历史胜率 / 热钱信号 / 跟单话术。
9. 各段之间**不加 ---**。

# 输入数据说明
- agent1_output: 队伍统计信号 JSON
- agent2_output: 盘口分析 JSON（含 model_vs_market / wdl_analysis / ou_analysis / ah_analysis）
- agent3_output: 战力评估 JSON（含 home_power / away_power / power_summary）
- prebuilt_quant_section: Python 生成的概率基准线（直接粘贴，不修改任何数字）
- match_info: 比赛基本信息
- single_pick: 推荐结果（picked_market / picked_direction / picked_odds / inference）

# 研报结构（严格按顺序）

## {主队} vs {客队} · 世界杯 {日期}

> 一句话赛前判断，口语化，带明确倾向（或"局势不明，观望为宜"）

## 量化概率基准线

{直接插入 prebuilt_quant_section，一字不改}

## 赛前分析

[150-230 字，纯文字，不放表格。写法自由，像分析师直接说话：
  - 先说本场最有说服力的判断依据（盘口走势、双方近况、关键伤停、主客场因素等）
  - 带出双方近期表现的关键事实（具体比分、连胜/连败、明显的攻防优劣）
  - 若有独立预测概率与盘口出入较大，一句话带过，不要展开
  - 最后落到推荐方向和核心逻辑，干脆利落
  - 只说最有力的理由，宁可少写，不写废话]

## 进球数参考

[若 prebuilt_quant_section 无进球数表格，**整段跳过，什么都不写**；
 有数据时：40-70 字，说清楚为什么偏大球或小球，末尾加"进球数模型暂无历史战绩背书，仅供参考"]

## 综合结论

进攻面：主队 [N] 星，客队 [N] 星
防守面：主队 [N] 星，客队 [N] 星
状态：主队 [上升期/稳定期/低迷期]，客队 [同]
推荐：[与 single_pick.inference 完全一致；SKIP 写"观望"]
理由：[20 字内，直接点明核心逻辑；SKIP 写"局势不明，风险大"]

```json_meta
{
  "beginner_summary": "一句话，像朋友发微信：直接说为什么推这个，带一个具体数字，不超过 40 字",
  "chart_insights": {
    "npxgd": "一句话描述双方近期攻守趋势，30 字内",
    "shotmap": null,
    "lineup_compare": "若有首发信息，一句话说阵容影响；否则写 null",
    "injuries": null,
    "player_contribution": null
  },
  "key_variables": [
    "本场最关键变量 1，不超过 20 字",
    "本场最关键变量 2，不超过 20 字",
    "本场最关键变量 3，不超过 20 字"
  ],
  "key_risk": "推荐最大风险，不超过 30 字，具体"
}
```

# 格式约束
1. json_meta 代码块保留 ```json_meta 和 ``` 标记，后端解析用。
2. json_meta 内 JSON 严格合法（双引号，无尾逗号）。
3. key_variables 恰好 3 条；shotmap / injuries / player_contribution 固定写 null。
"""


# ══════════════════════════════════════════════════════════════════════════════
# Section 3: WC Agent Context Builder
# ══════════════════════════════════════════════════════════════════════════════

def _build_wc_agent_context(state: WcMatchReportState, agent_key: str) -> dict:
    """WC 专属：按 Agent 类型从 state 切片提取数据。"""
    base = {"match_info": state.get("match_info", {})}

    if agent_key == "agent1_output":
        return {
            **base,
            "wc_team_stats": state.get("wc_team_stats", {}),
        }
    elif agent_key == "agent2_output":
        return {
            **base,
            "wc_ml_output":  state.get("wc_ml_output", {}),
            "ou_display":    state.get("ou_display", {}),
            "ah_info":       state.get("ah_info", {}),
            "single_pick":   state.get("single_pick", {}),
            "cc_predictions": state.get("cc_predictions", {}),  # 第三方模型预测
        }
    elif agent_key == "agent3_output":
        return {
            **base,
            "agent1_output": state.get("agent1_output", ""),
            "agent2_output": state.get("agent2_output", ""),
        }
    elif agent_key == "final_report":
        # 首发数据：按 cc_home/away_team_id 分组，仅传 11 名首发
        predicted_lineup = state.get("predicted_lineup") or []
        home_tid = state.get("cc_home_team_id") or 0
        away_tid = state.get("cc_away_team_id") or 0
        home_starters = [p for p in predicted_lineup if p.get("team_sportmonks_id") == home_tid][:11]
        away_starters = [p for p in predicted_lineup if p.get("team_sportmonks_id") == away_tid][:11]

        # 近期表现：各取最近 5 场
        home_recent = (state.get("home_recent") or [])[:5]
        away_recent = (state.get("away_recent") or [])[:5]

        return {
            **base,
            "agent1_output":          state.get("agent1_output", ""),
            "agent2_output":          state.get("agent2_output", ""),
            "agent3_output":          state.get("agent3_output", ""),
            "prebuilt_quant_section": state.get("prebuilt_quant_section", ""),
            "wc_ml_output":           state.get("wc_ml_output", {}),
            "ou_display":             state.get("ou_display", {}),
            "ah_info":                state.get("ah_info", {}),
            "single_pick":            state.get("single_pick", {}),
            # ── cc 富数据 ────────────────────────────────────────────────────
            "predicted_lineup_home":  home_starters,
            "predicted_lineup_away":  away_starters,
            "home_recent":            home_recent,
            "away_recent":            away_recent,
        }
    return base


# ══════════════════════════════════════════════════════════════════════════════
# Section 4: WC Agent Node (wraps build_agent_node with WC context)
# ══════════════════════════════════════════════════════════════════════════════

def _build_wc_agent_node(llm: "BaseChatModel", system_prompt: str, output_key: str):
    """
    WC 专属 Agent 节点：使用 WC state 结构，但调用复用的 LangChain 模式。
    """
    def node(state: WcMatchReportState) -> dict:
        log.info(f"[wc_workflow] Running {output_key}...")
        user_data = _build_wc_agent_context(state, output_key)

        messages = [
            HumanMessage(
                content=(
                    f"系统提示：{system_prompt}\n\n"
                    f"请基于以下数据完成分析任务：\n\n"
                    f"```json\n{json.dumps(user_data, ensure_ascii=False, indent=2)}\n```"
                )
            )
        ]

        _model_name = (
            getattr(llm, "model", None)
            or getattr(getattr(llm, "runnable", None), "model", "qwen")
        )
        log.info(f"  [{output_key}] invoking {_model_name}...")
        response = llm.invoke(messages)
        content = response.content

        # 鲁棒：处理 list 类型 content（DashScope 偶发）
        if isinstance(content, list):
            parts = [p["text"] if isinstance(p, dict) else p for p in content if p]
            content = "".join(str(p) for p in parts)

        # 清理 Flash 输出 markdown 围栏（agent1/2/3 输出纯 JSON，不需要围栏）
        if output_key in ("agent1_output", "agent2_output", "agent3_output"):
            content = re.sub(r"^```(?:json)?\s*\n?", "", content.strip())
            content = re.sub(r"\n?```\s*$", "", content.strip())

        log.info(f"  [{output_key}] done ({len(content)} chars)")
        return {output_key: content}

    return node


# ══════════════════════════════════════════════════════════════════════════════
# Section 5: Graph Construction
# ══════════════════════════════════════════════════════════════════════════════

def build_wc_workflow(llm_flash: "BaseChatModel", llm_pro: "BaseChatModel"):
    """
    构建 WC LangGraph 工作流（Flash×3 + Pro×1，无 ML inference 节点）。

    Args:
        llm_flash: qwen-plus / qwen-turbo（Agents 1-3 数据提取）
        llm_pro:   qwen-max-latest（Agent 4 叙事整合）

    Returns:
        编译后的 LangGraph 可执行图
    """
    if not HAS_LANGGRAPH:
        raise RuntimeError("langgraph not installed. Run: pip install langgraph langchain-core")

    graph = StateGraph(WcMatchReportState)

    graph.add_node("wc_agent1_stats",     _build_wc_agent_node(llm_flash, WC_AGENT1_SYSTEM_PROMPT, "agent1_output"))
    graph.add_node("wc_agent2_odds",      _build_wc_agent_node(llm_flash, WC_AGENT2_SYSTEM_PROMPT, "agent2_output"))
    graph.add_node("wc_agent3_power",     _build_wc_agent_node(llm_flash, WC_AGENT3_SYSTEM_PROMPT, "agent3_output"))
    graph.add_node("wc_agent4_synthesis", _build_wc_agent_node(llm_pro,   WC_AGENT4_SYSTEM_PROMPT, "final_report"))

    graph.set_entry_point("wc_agent1_stats")
    graph.add_edge("wc_agent1_stats",     "wc_agent2_odds")
    graph.add_edge("wc_agent2_odds",      "wc_agent3_power")
    graph.add_edge("wc_agent3_power",     "wc_agent4_synthesis")
    graph.add_edge("wc_agent4_synthesis", END)

    return graph.compile()


# ══════════════════════════════════════════════════════════════════════════════
# Section 6: Prebuilt Quant Section (Python-generated, LLM must NOT modify)
# ══════════════════════════════════════════════════════════════════════════════

def build_prebuilt_quant_section(
    home_name: str,
    away_name: str,
    wdl: dict,
    ou: dict | None,
    ah: dict | None,
    single_pick: dict | None,
) -> str:
    """
    生成 LLM 必须原封不动插入的量化概率基准线 Markdown。
    所有数值均在 Python 层计算，不交给 LLM 处理。
    """
    lines = []

    # WDL 三宫格
    h_pct  = round(wdl.get("home", 0) * 100, 1)
    d_pct  = round(wdl.get("draw", 0) * 100, 1)
    a_pct  = round(wdl.get("away", 0) * 100, 1)
    n_wdl  = wdl.get("n_books", 0)
    div    = wdl.get("divergence", 0.0)
    if div < 0.01:
        div_desc = "各家口径高度一致"
    elif div < 0.025:
        div_desc = "各家看法基本一致"
    else:
        div_desc = "各家存在一定分歧"
    lines.append(f"**市场共识** · 综合 {n_wdl} 家主流机构报价（已剔除水位），{div_desc}")
    lines.append("")
    lines.append(f"| {home_name} 主胜 | 平局 | {away_name} 客胜 |")
    lines.append("|:---:|:---:|:---:|")
    lines.append(f"| **{h_pct}%** | **{d_pct}%** | **{a_pct}%** |")
    lines.append("")

    # OU（仅展示，无数据时跳过整块）
    if ou and ou.get("over") is not None and ou.get("n_books", 0) > 0:
        o_pct  = round(ou["over"]  * 100, 1)
        u_pct  = round(ou["under"] * 100, 1)
        line_v = ou.get("line", "—")
        split  = "（四分盘）" if ou.get("split") == "quarter" else ""
        n_ou   = ou.get("n_books", 0)
        lines.append(f"**进球数参考 · {line_v} 球盘{split}（{n_ou} 家机构，仅作展示）**")
        lines.append("")
        lines.append(f"| 过 {line_v} | 不过 {line_v} |")
        lines.append("|:---:|:---:|")
        lines.append(f"| {o_pct}% | {u_pct}% |")
        lines.append("> ⚠️ 进球数模型暂无历史战绩背书，仅供参考，不作推荐")
        lines.append("")

    # AH（仅幅度）
    if ah and ah.get("magnitude") is not None:
        line_ah = ah.get("line", 0)
        mag     = ah.get("magnitude", 0)
        n_ah    = ah.get("n_books", 0)
        fav     = home_name if line_ah < 0 else away_name
        lines.append(f"**让球盘**：主流机构开 {fav} 让 {mag} 球（{n_ah} 家口径，仅供参考）")
        lines.append("")

    # 单推
    if single_pick and single_pick.get("inference"):
        lines.append(f"**{single_pick['inference']}**")
        if single_pick.get("caution_text"):
            lines.append(f"> ⚠️ {single_pick['caution_text']}")
    else:
        lines.append("**【观望】数据指向不明确**")
    lines.append("")

    return "\n".join(lines)
