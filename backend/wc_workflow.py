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
你是世界杯盘口解读模块。分析 WDL 市场共识与 OU/AH 盘口信息，输出结构化 JSON。

# 铁律
1. **仅输出合法 JSON**，不写叙事文字，不加 markdown 围栏。
2. **绝对禁止自行计算概率**，数值全部引用输入。
3. **OU 必须标注** "历史基线建立中，2026实盘滚动验证"，绝对禁止引用 market-80 的 54.5% 或 61% 等历史准确率。
4. **AH 仅幅度信息（market 让球幅度=N球）**，绝对禁止给出 AH 胜率或推荐。
5. **WDL 推荐** 只能来自 single_pick 字段，不可自行判断方向。
6. 禁止任何"热钱信号 / 资金流向 / 庄家意图"等话术。
7. 所有文本字段使用中文。

# 输入数据
wc_ml_output: WDL 市场共识概率 + 书商数量 + 离散度
ou_display: OU Goal Line 展示数据（含免责声明）
ah_info: AH 市场隐含让球幅度（仅幅度，无胜率）
single_pick: WC 单推选择结果（可能为 {} 代表 SKIP）

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
    "commentary": "<一句话说明进球趋势预期，20 字内，严禁引用 54.5%/61% 等历史准确率>"
  },
  "ah_analysis": {
    "line": <number|null>,
    "magnitude": <number|null>,
    "commentary": "<一句话描述市场让球幅度含义，20 字内，严禁给出 AH 胜率>"
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
你是世界杯研报撰写专家。整合前三个 Agent 的分析，生成一份完整的 Markdown 研报。

# 铁律（红线，任何条违反都是错误输出）
1. **推荐方向只能是 WDL（主胜/平局/客胜）**；绝对禁止给出亚盘推荐或大小球推荐（这不是联赛）。
2. **OU（进球数）仅展示分析，不出推荐**；必须带"历史基线建立中，2026实盘滚动验证"免责。
3. **AH 仅写市场隐含让球幅度**，绝对禁止给出 AH 胜率或 AH 方向推荐。
4. **禁止出现** xG / NPXGD / 期望进球 / 射门坐标等联赛专属指标（WC 无此数据）。
5. **BCC 缺失时**，对应行/格不显示数字（写"—"或隐藏），绝对不得插值估算。
6. **禁止出现** 跟单稳赚 / 胜率保证 / 热钱信号 / 前 N 场回归 等话术。
7. **禁止引用** market-80 历史准确率（54.5% / 61%）。
8. **所有概率数值必须** 原封不动引用 prebuilt_quant_section，不得重算或修改。
9. 全文使用中文，禁止英文单词（ML→算法模型，Edge→价值边际 等）。
10. **SKIP 场次**：推荐方向写"观望"，理由说明"市场共识分歧过大或样本不足"，不得强行给出方向。

# 研报 Markdown 结构（按此顺序，不得删改 H2 标题）

## {主队} vs {客队} · 世界杯 {日期}

> 一句话赛前定性（带推荐方向或"观望"）

---

## 量化概率基准线

{直接插入 prebuilt_quant_section，不修改任何数字}

---

## 原始攻防对比

| 指标 | {主队} | {客队} |
|------|--------|--------|
| 总射门 | | |
| 射正 | | |
| 禁区内 | | |
| 禁区外 | | |
| 大机会 | | |
| 危险进攻 | | |
| 控球率 | | |

> BCC 注：若 bcc_available=false，大机会行写"—（数据未覆盖）"。

---

## WDL 推荐分析

[基于市场共识和战力对比，说明推荐方向及核心逻辑。SKIP 时写观望理由。]

---

## 进球数（Goal Line）展示

[market7 共识概率，带 split 说明；必须包含 "历史基线建立中，2026实盘滚动验证" 免责声明；
严禁引用 54.5% / 61% 等历史准确率；OU 不出推荐]

---

## 市场让球参考（亚盘）

[仅写市场隐含让球幅度（N 球）和书商数量，不出 AH 推荐，不给 AH 胜率。]

---

## 综合结论

进攻面评估：主队 [N] 星，客队 [N] 星
防守面评估：主队 [N] 星，客队 [N] 星
状态判断：主队 [上升期/稳定期/低迷期]，客队 [同]
推荐方向：[与 single_pick.picked_direction 一致的中文方向，必须是 WDL；SKIP 写"观望"]
推荐理由的核心逻辑：[一句话，必须与 WDL 相关；SKIP 时写"书商分歧过大或数据不足，建议观望"]

```json_meta
{
  "beginner_summary": "用大白话一句话概括推荐理由（SKIP 时写'本场分析数据指向不明确，建议观望'），不超过 50 字，禁用专业术语，语气像朋友微信聊天，包含一个具体数据事实",
  "chart_insights": {
    "npxgd": "一句话描述本场每分钟危险进攻/射门趋势对 WDL 的意义，30 字内",
    "shotmap": null,
    "lineup_compare": null,
    "injuries": null,
    "player_contribution": null
  },
  "key_variables": [
    "本场最关键的 3 个 WDL 相关变量，每条不超过 20 字。例：主队主场近 4 场均胜 / 书商 N 家共识主胜 / 让球幅度 N 球偏向主队"
  ],
  "key_risk": "本场 WDL 推荐最大的风险点，一句话不超过 40 字。SKIP 时写'书商分歧超阈值，市场定价存在不确定性'"
}
```

# 关键约束
1. json_meta 代码块必须保留 ```json_meta 起始标和 ``` 结束标，后端按此解析。
2. json_meta 内 JSON 必须严格合法（双引号、无尾随逗号）。
3. key_variables 数组长度恰好 3 条；shotmap / lineup_compare / injuries / player_contribution 固定写 null（WC 无此数据）。
4. 所有数值原封不动引用输入，禁止编造或重算。
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
            "wc_ml_output": state.get("wc_ml_output", {}),
            "ou_display":   state.get("ou_display", {}),
            "ah_info":      state.get("ah_info", {}),
            "single_pick":  state.get("single_pick", {}),
        }
    elif agent_key == "agent3_output":
        return {
            **base,
            "agent1_output": state.get("agent1_output", ""),
            "agent2_output": state.get("agent2_output", ""),
        }
    elif agent_key == "final_report":
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
    lines.append(f"**市场共识（去水中位，{n_wdl} 家书商，离散度={div:.3f}）**")
    lines.append("")
    lines.append(f"| {home_name} 主胜 | 平局 | {away_name} 客胜 |")
    lines.append("|:---:|:---:|:---:|")
    lines.append(f"| **{h_pct}%** | **{d_pct}%** | **{a_pct}%** |")
    lines.append("")

    # OU（仅展示）
    if ou and ou.get("over") is not None:
        o_pct  = round(ou["over"]  * 100, 1)
        u_pct  = round(ou["under"] * 100, 1)
        line_v = ou.get("line", "—")
        split  = "（四分盘）" if ou.get("split") == "quarter" else ""
        n_ou   = ou.get("n_books", 0)
        disc   = ou.get("baseline_disclaimer", "历史基线建立中，2026实盘滚动验证")
        lines.append(f"**Goal Line {line_v}{split}（仅展示，{n_ou} 家，不出推荐）**")
        lines.append("")
        lines.append(f"| 过{line_v} | 不过{line_v} |")
        lines.append("|:---:|:---:|")
        lines.append(f"| {o_pct}% | {u_pct}% |")
        lines.append(f"> ⚠️ {disc}")
        lines.append("")

    # AH（仅幅度）
    if ah and ah.get("magnitude") is not None:
        line_ah = ah.get("line", 0)
        mag     = ah.get("magnitude", 0)
        n_ah    = ah.get("n_books", 0)
        fav     = home_name if line_ah < 0 else away_name
        lines.append(f"**市场让球（{n_ah} 家，仅幅度参考）**：{fav} 让 {mag} 球（仅信息，非推荐）")
        lines.append("")

    # 单推
    if single_pick and single_pick.get("inference"):
        lines.append(f"**推荐**：`{single_pick['inference']}`")
        if single_pick.get("caution_text"):
            lines.append(f"> ⚠️ {single_pick['caution_text']}")
    else:
        lines.append("**推荐**：`【SKIP】观望 — 数据指向不明确`")
    lines.append("")

    return "\n".join(lines)
