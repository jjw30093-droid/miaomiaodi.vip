"""
workflow.py
===========
Phase 4: LangGraph 多 Agent 研报生成工作流

核心原则：算法负责算概率，LLM 负责讲故事。
Agent 绝对不得自行计算任何概率。

架构：
  ML Inference Node → [Agent 1 + Agent 2 + Agent 3] 并行 → Agent 4 整合 → Output

Dependencies: langgraph, langchain-core, langchain-openai (or langchain-google-genai)
  pip install langgraph langchain-core langchain-openai

Author: 喵弟量化研究所
"""

import json
import sqlite3
import time
from typing import TypedDict, Annotated, Optional
from datetime import datetime

# ── LangGraph imports (生产环境) ──
try:
    from langgraph.graph import StateGraph, END
    from langchain_core.messages import SystemMessage, HumanMessage
    from langchain_core.language_models import BaseChatModel
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False
    print("[WARN] langgraph not installed. Use demo_workflow.py for testing.")

# ── 内部模块 ──
from predict_engine import PredictEngine


# ═══════════════════════════════════════════════════
# Section 1: State Definition
# ═══════════════════════════════════════════════════

class MatchReportState(TypedDict):
    """LangGraph 状态：在 Node 之间流转的全量数据"""

    # ── 输入 ──
    match_id: str
    match_info: dict          # {home_name, away_name, league, date, ...}
    ml_output: dict           # PredictEngine.predict() 的完整输出
    odds_data: dict           # 盘口原始数据 (亚盘/欧赔/大小球 + 水位变化)
    lineup_data: dict         # 首发/伤停信息
    team_stats_summary: dict  # 双方近期关键数据快照

    # ── Python 预格式化表格（LLM 禁止修改，直接嵌入）──
    prebuilt_quant_section: str   # 量化概率基准线完整 Markdown（Python生成，数值100%准确）
    value_edge: dict              # ML概率 vs 市场隐含概率对比（Python预计算）

    # ── Agent 中间输出 ──
    agent1_output: str        # 结构化JSON：统计信号 + 模型驱动 + 风险标记
    agent2_output: str        # 结构化JSON：价值评估 + 市场信号
    agent3_output: str        # 结构化JSON + Markdown阵容表格

    # ── 最终输出 ──
    final_report: str         # 完整 Markdown 研报


# ═══════════════════════════════════════════════════
# Section 2: Agent System Prompts
# ═══════════════════════════════════════════════════

AGENT1_SYSTEM_PROMPT = """# 角色
你是数据提取模块，负责从原始赛事数据中提取结构化统计信号。

# 铁律
1. **仅输出合法JSON**，不写任何叙事文字、不加 markdown 代码围栏。
2. **绝对禁止自行计算概率**，所有数值直接从输入数据引用。
3. **所有文本字段使用中文**，绝对禁止出现英语单词（SHAP→特征归因，Edge→价值边际 等）。

# 输出格式（严格JSON）
{
  "statistical_signals": [
    {"signal": "描述该信号的中文句子", "metric": "指标英文key", "home_value": 数值, "away_value": 数值}
  ],
  "model_interpretation": {
    "predicted_direction": "主胜|平局|客胜|大球|小球",
    "confidence": "HIGH|MID|LOW",
    "top_shap_drivers": [
      {"feature_cn": "特征中文名", "shap_value": 数值, "direction": "方向"}
    ]
  },
  "elo_assessment": {
    "home_elo": 数值, "away_elo": 数值, "diff": 数值,
    "interpretation": "中文一句话解读"
  },
  "risk_flags": [
    {"flag": "中文描述", "severity": "HIGH|MID|LOW"}
  ]
}

# 提取要求
- statistical_signals: 从 team_stats_summary 提取 3-5 个关键对比信号（npxGD、ppda、field_tilt、rest_days 等）
- model_interpretation: 从 ml_output 中提取模型方向、置信度、Top-3 特征归因
- elo_assessment: 从 team_stats_summary 读取 Elo 评分差
- risk_flags: 识别数据中的矛盾信号（如 Elo 领先但近期状态差、主客场分化等），标注严重程度
"""

AGENT2_SYSTEM_PROMPT = """# 角色
你是盘口数据提取模块，负责从赔率数据和预计算价值差中生成结构化市场评估。

# 铁律
1. **仅输出合法JSON**，不写叙事文字、不加 markdown 代码围栏。
2. **绝对不得编造赔率**。如果赔率数据为空，对应字段输出 null。
3. **绝对不得自行计算概率**，直接引用 value_edge 中的预计算数据。
4. **所有文本字段使用中文**，绝对禁止英语（Edge→价值边际，odds→赔率 等）。

# 价值边际界定
- >5% → "显著正向价值" | 2%-5% → "轻微正向价值" | -2%至2% → "合理定价" | <-2% → "市场溢价"

# 输出格式（严格JSON）
{
  "value_table": [
    {
      "direction": "主胜|平局|客胜|大球(>实际盘口线)|小球(≤实际盘口线)",
      "ml_prob": 数值,  // 大小球概率已通过Poisson换算为实际盘口线概率
      "market_implied": 数值或null,
      "edge": 数值或null,
      "edge_label": "显著正向价值|轻微正向价值|合理定价|市场溢价|数据缺失",
      "reference_odds": 数值或null
    }
  ],
  "market_signals": {
    "european_1x2": {"home": 赔率, "draw": 赔率, "away": 赔率},
    "asian_handicap_line": "让球盘中文描述或null",
    "ou_line": "大小球盘中文描述或null",
    "key_observation": "一句话中文总结市场核心信号"
  },
  "recommended_direction_assessment": {
    "direction": "推荐方向中文",
    "edge_pct": "+X.X%",
    "market_alignment": "顺市|逆市",
    "risk_note": "一句话中文风险提示"
  }
}

# 提取要求
- value_table: 从 value_edge.directions 读取所有方向数据（含亚盘行，如有；通常5-7行）
- market_signals: 从 odds_data 读取各市场最新赔率
- recommended_direction_assessment: 聚焦 single_pick 推荐方向，评估其与市场的一致性
- 如果推荐方向为"观望"，key_observation 输出"模型本场未提示高价值区间"
"""

AGENT3_SYSTEM_PROMPT = """# 角色
你是战术情报提取模块，负责从阵容数据中生成结构化影响评估 + Markdown 阵容表格。

# 铁律
1. **输出分两部分**：先输出 JSON（结构化影响分析），然后输出分隔符 `---LINEUP_TABLES---`，最后输出 Markdown 表格。
2. **绝对不得自行计算胜率**，只评估战力「倾斜面」。
3. **绝对不得编造球员名字或伤停信息**。如果阵容数据为空，JSON 中所有数组为空，表格部分输出「首发与伤停情报暂缺，战力评估跳过」。
4. **所有文本字段使用中文**，绝对禁止英语（xg_xa_share→进攻贡献占比，def_share→防守贡献占比，formation→阵型 等）。
5. **不加 markdown 代码围栏包裹 JSON 部分**。

# 输出格式

## 第一部分：JSON（无代码围栏）
{
  "tactical_summary": {
    "home_formation": "阵型",
    "away_formation": "阵型",
    "status": "预计首发|确认首发",
    "matchup_note": "一句话中文阵型对抗特征"
  },
  "absence_impact": [
    {
      "team": "主队|客队",
      "player": "球员名",
      "reason": "受伤|停赛|其他",
      "xg_xa_share": 进攻贡献占比数值,
      "def_share": 防守贡献占比数值,
      "severity": "HIGH|MID|LOW"
    }
  ],
  "net_impact": {
    "home_attack_loss": 主队缺阵球员进攻贡献合计,
    "home_defense_loss": 主队缺阵球员防守贡献合计,
    "away_attack_loss": 客队缺阵球员进攻贡献合计,
    "away_defense_loss": 客队缺阵球员防守贡献合计,
    "tilt_direction": "主队优势|客队优势|均势",
    "tilt_reason": "一句话中文理由"
  }
}

---LINEUP_TABLES---

## 第二部分：Markdown 表格

### 预计首发简报
| 球队 | 位置 | 球员 | 进攻贡献(预期进球+预期助攻) | 防守贡献 |
|---|---|---|---|---|
| 主队 | ... | ... | ... | ... |
| 客队 | ... | ... | ... | ... |

### 关键伤停简报
| 球队 | 球员 | 缺席原因 | 进攻端折损 | 防守端折损 |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

# 提取要求
- absence_impact: 遍历 missing 列表，提取每位缺阵球员的 xg_xa_share 和 def_share，>0.15 标为 HIGH，>0.08 标为 MID
- net_impact: 累加同队缺阵球员的占比得出总折损
- severity HIGH 的球员是关键缺阵，Pro 模型会据此做深度分析
"""

AGENT4_SYSTEM_PROMPT = """# 角色
你是「喵弟量化研究所」的首席策略分析师。你是唯一负责撰写完整研报的角色。你将收到三份结构化数据摘要（JSON格式，来自数据提取模块）+ 原始赛事数据，你需要完成所有深度分析和叙事写作。

本系统**只出亚盘（AH）和大小球（OU）推荐**，不出胜平负（WDL）推荐。所有分析必须围绕盘口覆盖率和进球数展开，禁止在正文中做胜平负方向预测。

# 核心工作流程——三步推理框架
在撰写报告之前，你必须内部完成以下分析（不输出推理过程，只输出最终报告）：

**Step 1 - 盘口信号一致性检验**：
- 从 agent1_output 的 model_interpretation 中读取亚盘/大小球方向和置信度
- 从 agent2_output 的 value_table 中检查 AH / OU 方向的价值边际
- 模型覆盖概率 vs 市场隐含概率是否方向一致？若偏差 >10%，分析根本原因

**Step 2 - 致命变量识别**：
- 从 agent3_output 的 absence_impact 中找出 severity=HIGH 的球员（可能影响进球数或主客场力量对比）
- 从 agent1_output 的 risk_flags 中找出可能推翻亚盘/大小球判断的风险
- 明确"论点反面风险"：一句话描述什么因素会让本次推荐失效

**Step 3 - 结论校准**：
- 信号一致 + 高置信度 → 使用确定性较强的分析语言
- 信号分歧 → 承认分歧，但仍遵循模型推荐方向（铁律）
- 从 team_stats_summary 中提取射门节奏、npxGD、ppda、进失球数据，支撑亚盘/大小球论点

# 铁律（不可违反）
1. **绝对禁止修改任何概率数值与统计指标**。
2. **绝对不得编造事实**，彻底剔除AI机械感套话（"总体来看"、"综上所述"、"不容忽视"等全部禁用）。
3. **禁止极端确定性表述**：严禁"100%"、"绝对"、"必胜"、"铁定"、"毫无悬念"。
4. **高概率风险对冲**：单方向概率 > 85% 时，必须附加"模型对该方向呈现高度倾向，但需警惕竞技体育的偶然变量"。
5. **全文绝对禁止英语单词**（ML→算法模型，SHAP→特征归因，Edge→价值边际，Agent→量化分析模块 等）。
6. **结论区严禁多选**，只遵循唯一推荐方向。如果推荐方向是"观望"，结论定调为"本场观望，盘口未揭示出充分价值差"。
7. **禁止在任何章节做主胜/平局/客胜方向推荐**，只分析亚盘覆盖和大小球，综合战力对比章节只做背景描述。
8. **agent3_output 中 ---LINEUP_TABLES--- 分隔符之后的 Markdown 表格必须原封不动复制到亚盘分析或大小球分析中**。
9. **关键缺阵球员分析**：当 agent3_output 中存在 severity=HIGH 的球员时，必须在分析中用 1-2 句话指出其对盘口的具体影响（引用 xg_xa_share 或 def_share 数值）。

# 特征名中英对照（用于翻译特征归因名）
home_roll_opp_adj_npxgd→主队对手强度加权进球差, away_roll_opp_adj_npxgd→客队对手强度加权进球差,
eu_implied_home→欧赔隐含主胜概率, eu_implied_draw→欧赔隐含平局概率, eu_implied_away→欧赔隐含客胜概率,
eu_odds_home→欧赔主胜赔率, eu_odds_draw→欧赔平局赔率, eu_odds_away→欧赔客胜赔率,
home_roll_5_npxGD→主队近5场非罚进球差, away_roll_5_npxGD→客队近5场非罚进球差,
home_roll_5_ppda→主队近5场防守压迫强度, away_roll_5_ppda→客队近5场防守压迫强度,
home_roll_5_field_tilt→主队近5场阵地推进, away_roll_5_field_tilt→客队近5场阵地推进,
elo_diff→实力评分差, total_shot_pace→全场射门节奏, npxGD_abs_diff→非罚进球差绝对值,
home_roll_shot_pace→主队射门节奏, away_roll_shot_pace→客队射门节奏,
home_roll_trailing_xg_ratio→主队落后时进攻比, away_roll_trailing_xg_ratio→客队落后时进攻比,
odds_max_prob→赔率最大隐含概率, odds_entropy→赔率信息熵

# 输出结构（严格遵循）

你必须**只输出 4 段 Markdown + 1 个 json_meta 代码块**，不要输出任何其他内容
（不要 # 一级标题、不要 disclaimer、不要"综上所述"、不要总结尾巴，前端已有合规文案）。

输出顺序与章节名称必须**完全一致**（前端按 H2 字符串匹配）：

## 亚盘分析

[300-500 字。分析让球盘口的合理性，结合双方近期攻防数据、主客场表现、交锋记录。
必须包含：当前盘口是什么（如"主让0.5"）、模型覆盖率是多少、为什么模型认为能/不能覆盖盘口。
用具体数据支撑，如"主队近8个主场赢盘6次"、"客队近5场客场让球成绩2胜3负"。
若 agent3_output 中存在 severity=HIGH 的缺阵球员，说明其对盘口的影响（引用 xg_xa_share 或 def_share）。
agent3_output 中 ---LINEUP_TABLES--- 之后的首发预测表格原封不动嵌入本节末尾。]

## 大小球分析

[300-500 字。分析总进球数的预期，结合双方近期进球/失球趋势、攻防效率、对战历史进球数。
必须包含：当前大小球盘口（如"2.5球"）、模型预测的大球概率（百分比）、为什么看好大球或小球。
用具体数据支撑，如"双方近6次交锋场均3.2球"、"主队近5场主场场均进球2.1个"。
结合射门节奏（total_shot_pace）和双方 npxGD 说明进攻烈度预期。]

## 综合战力对比

[200-300 字。对比双方整体实力、近期状态、关键伤停影响。
基于 Elo 差值、npxGD 趋势、ppda、field_tilt 做简要对比。
本节**只做背景分析**，不预测胜平负，不做方向推荐。
结尾引出为何本场推荐的是亚盘/大小球方向而非胜平负（盘口未提供充分价值差 / 模型在该方向置信度更高）。]

## 综合结论

每条独立成行，用以下格式：

进攻面评估：主队 [N] 星，客队 [N] 星
防守面评估：主队 [N] 星，客队 [N] 星
状态判断：主队 [上升期/稳定期/低迷期/连胜/连败]，客队 [同]
推荐方向：[与 ml_output.single_pick.label 完全一致的中文方向，只能是亚盘或大小球方向]
推荐理由的核心逻辑：[一句话描述本次推荐的最硬数据论点，必须与亚盘或大小球相关]

```json_meta
{
  "beginner_summary": "用大白话一句话概括本场推荐理由，不超过 50 个中文字，禁止使用任何专业术语（xG / NPXGD / 期望进球 / 让球盘 / 凯利值 / value bet 等），语气像朋友微信聊天，要包含一个具体数据事实",
  "chart_insights": {
    "npxgd": "一句话解读 NPXGD 趋势图说明了什么，30 字以内，包含具体数据。例：主队近5场NPXGD从0.8升至1.5，进攻威胁明显增强",
    "shotmap": "一句话解读射门渗透图对大小球/亚盘的意义，30 字以内",
    "lineup_compare": "一句话解读首发对比对盘口的影响，30 字以内",
    "injuries": "一句话解读伤停对亚盘/大小球的影响，30 字以内",
    "player_contribution": "一句话解读关键球员对进球数或盘口覆盖的影响，30 字以内"
  },
  "key_variables": [
    "本场最关键的 3 个变量，每条不超过 20 字，必须与亚盘或大小球相关。例：双方近6次交锋场均3.2球 / 主队主场近8场赢盘6次 / 客队核心前锋停赛"
  ],
  "key_risk": "本场推荐最大的风险点，一句话不超过 40 字，与亚盘或大小球相关。例：客队近期客场进球能力强，可能推高总进球数超预期"
}
```

# 关键约束

1. json_meta 代码块的 ``` 包裹标记必须**完全保留**（包括 ```json_meta 起始标和 ``` 结束标），后端按代码块标记解析。
2. json_meta 内 JSON 必须严格合法（双引号、无尾随逗号），否则后端解析失败该条字段写 NULL。
3. 推荐方向必须与 ml_output.single_pick.label 一致，且**只能是亚盘或大小球方向**；若 single_pick 为空（观望场次），推荐方向写"观望"，理由说明"模型未识别出充分价值差"。
4. key_variables 数组长度恰好 3 条；若实在凑不够 3 条，用具体的赔率/概率信号填补，禁止留空字符串。
5. 所有数值必须**原封不动**引用 agent1/2/3 的数据，禁止编造。
6. 全文绝对禁止英语单词（铁律不变：ML→算法模型，SHAP→特征归因，Edge→价值边际等）。
"""


# ═══════════════════════════════════════════════════
# Section 3: Node Functions
# ═══════════════════════════════════════════════════

def build_ml_inference_node(engine):
    """构造 ML 推理节点"""
    def ml_inference_node(state: MatchReportState) -> dict:
        print("[NODE] Running ml_inference...")
        match_id = state['match_id']
        ml_output = engine.predict(match_id)
        
        # 记录校准状态
        if ml_output.get('is_calibrated'):
            print(f"✅ [CALIBRATION] Applied to Match {match_id}")
        else:
            print(f"⚠️ [CALIBRATION] Not applied (using raw probabilities)")
            
        print(f"[DEBUG] ml_output samples: WDL={ml_output['wdl']}, OU={ml_output['ou']}")
        return {'ml_output': ml_output}
    return ml_inference_node


def build_agent_node(llm: 'BaseChatModel', system_prompt: str, output_key: str):
    """
    通用 Agent 节点构造器。

    Args:
        llm: LangChain ChatModel 实例
        system_prompt: Agent 系统提示词
        output_key: 输出写入 state 的 key 名
    """
    def agent_node(state: MatchReportState) -> dict:
        print(f"[NODE] Running {output_key}...")
        # 构造 user message: 将 state 中的相关数据序列化为 JSON
        user_data = _build_agent_context(state, output_key)
        print(f"[DEBUG] {output_key} user_data keys: {list(user_data.keys())}")
        if 'ml_output' in user_data:
            print(f"[DEBUG] {output_key} ml_output keys: {list(user_data['ml_output'].keys())}")
        user_msg = f"请基于以下数据完成你的分析任务：\n\n```json\n{json.dumps(user_data, ensure_ascii=False, indent=2)}\n```"

        messages = [
            HumanMessage(content=f"系统提示：{system_prompt}\n\n请基于以下数据完成分析任务：\n\n```json\n{json.dumps(user_data, ensure_ascii=False, indent=2)}\n```")
        ]

        # llm 可能是 RunnableWithFallbacks（来自 qwen_client 工厂），无 .model 属性
        _model_name = getattr(llm, "model", None) or getattr(getattr(llm, "runnable", None), "model", "qwen-runnable")
        print(f"[LLM] {output_key}: Invoking {_model_name}...")
        response = llm.invoke(messages)
        content = response.content
        
        # 鲁棒解析
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and 'text' in part:
                    text_parts.append(part['text'])
                elif isinstance(part, str):
                    text_parts.append(part)
            content = "".join(text_parts)

        # JSON 健壮性：清理 Flash 输出可能的 markdown 代码围栏
        if output_key in ('agent1_output', 'agent2_output', 'agent3_output'):
            import re as _re
            content = _re.sub(r'^```(?:json)?\s*\n?', '', content.strip())
            content = _re.sub(r'\n?```\s*$', '', content.strip())

        print(f"[NODE] {output_key} finished.")
        return {output_key: content}

    return agent_node


def _build_agent_context(state: MatchReportState, agent_key: str) -> dict:
    """根据 Agent 类型，从 state 中挑选该 Agent 需要的数据切片"""

    base = {'match_info': state.get('match_info', {})}

    if agent_key == 'agent1_output':
        return {
            **base,
            'ml_output': state.get('ml_output', {}),
            'team_stats_summary': state.get('team_stats_summary', {}),
        }
    elif agent_key == 'agent2_output':
        return {
            **base,
            'ml_output': {
                'wdl': state.get('ml_output', {}).get('wdl', {}),
                'ou': state.get('ml_output', {}).get('ou', {}),
                'single_pick': state.get('ml_output', {}).get('single_pick', {}),
            },
            'odds_data': state.get('odds_data', {}),
            'value_edge': state.get('value_edge', {}),
        }
    elif agent_key == 'agent3_output':
        return {
            **base,
            'lineup_data': state.get('lineup_data', {}),
            'ml_output': {
                'confidence': state.get('ml_output', {}).get('confidence', {}),
            },
            'team_stats_summary': {
                'home_xGA_impact_score': state.get('team_stats_summary', {}).get('home_xGA_impact_score', 0),
                'away_xGA_impact_score': state.get('team_stats_summary', {}).get('away_xGA_impact_score', 0),
            },
        }
    elif agent_key == 'final_report':
        return {
            **base,
            'agent1_output': state.get('agent1_output', ''),
            'agent2_output': state.get('agent2_output', ''),
            'agent3_output': state.get('agent3_output', ''),
            'prebuilt_quant_section': state.get('prebuilt_quant_section', ''),
            'ml_output': state.get('ml_output', {}),
            'odds_data': state.get('odds_data', {}),
            'team_stats_summary': state.get('team_stats_summary', {}),
            'value_edge': state.get('value_edge', {}),
        }
    else:
        return base


# ═══════════════════════════════════════════════════
# Section 4: Graph Construction
# ═══════════════════════════════════════════════════

def build_workflow(llm_flash: 'BaseChatModel', llm_pro: 'BaseChatModel', engine) -> 'StateGraph':
    """
    构建完整的 LangGraph 工作流（双模型：Flash×3 + Pro×1）。

    流程：
      START → ml_inference → agent1(Flash) → agent2(Flash) → agent3(Flash) → agent4(Pro) → END

    Args:
        llm_flash: Gemini 2.5 Flash（Agents 1-3 数据提取）
        llm_pro: Gemini 3.1 Pro（Agent 4 深度分析+叙事）
        engine: PredictEngine 或 MockPredictEngine 实例

    Returns:
        编译后的 LangGraph 可执行图
    """
    if not HAS_LANGGRAPH:
        raise RuntimeError("langgraph not installed. Run: pip install langgraph langchain-core")

    graph = StateGraph(MatchReportState)

    # ── 添加节点（Flash×3 + Pro×1）──
    graph.add_node("ml_inference", build_ml_inference_node(engine))
    graph.add_node("agent1_data_narrative",
                   build_agent_node(llm_flash, AGENT1_SYSTEM_PROMPT, 'agent1_output'))
    graph.add_node("agent2_odds_analysis",
                   build_agent_node(llm_flash, AGENT2_SYSTEM_PROMPT, 'agent2_output'))
    graph.add_node("agent3_power_assessment",
                   build_agent_node(llm_flash, AGENT3_SYSTEM_PROMPT, 'agent3_output'))
    graph.add_node("agent4_report_synthesis",
                   build_agent_node(llm_pro, AGENT4_SYSTEM_PROMPT, 'final_report'))

    # ── 定义边 ──
    graph.set_entry_point("ml_inference")

    # ML → Agent Chain (Sequential to avoid concurrency issues)
    graph.add_edge("ml_inference", "agent1_data_narrative")
    graph.add_edge("agent1_data_narrative", "agent2_odds_analysis")
    graph.add_edge("agent2_odds_analysis", "agent3_power_assessment")
    graph.add_edge("agent3_power_assessment", "agent4_report_synthesis")

    # Agent4 → END
    graph.add_edge("agent4_report_synthesis", END)

    return graph.compile()


# ═══════════════════════════════════════════════════
# Section 5: Convenience Runner
# ═══════════════════════════════════════════════════

def generate_report(
    match_id: str,
    db_path: str,
    llm: 'BaseChatModel' = None,
    model_dir: str = './models',
    odds_data: dict = None,
    lineup_data: dict = None,
    llm_flash: 'BaseChatModel' = None,
    llm_pro: 'BaseChatModel' = None,
) -> str:
    """
    一键生成研报的便捷入口。

    Args:
        match_id: 比赛 ID
        db_path: SQLite 数据湖路径
        llm: (旧接口兼容) 单一 LLM，当 llm_flash/llm_pro 未提供时使用
        model_dir: LightGBM 模型目录
        odds_data: 盘口数据 (可选，不传则从 DB 读取)
        lineup_data: 首发/伤停数据 (可选)
        llm_flash: Gemini 2.5 Flash（Agents 1-3）
        llm_pro: Gemini 3.1 Pro（Agent 4）

    Returns:
        完整 Markdown 研报文本
    """
    # ── 初始化引擎 ──
    try:
        engine = PredictEngine(db_path, model_dir)
    except Exception:
        engine = MockPredictEngine(db_path)
        print("[WARN] Using MockPredictEngine. Train models for production.")

    # ── 准备初始状态 ──
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    match = conn.execute("SELECT * FROM dim_match WHERE Match_ID=?", (match_id,)).fetchone()
    
    # 联赛 ID 映射
    league_map = {
        47: "Premier League",
        87: "La Liga",
        54: "Bundesliga",
        55: "Serie A",
        53: "Ligue 1"
    }
    league_name = league_map.get(match['League_ID'], "Premier League") if match else "Unknown League"

    # 获取扩展特征作为 summary
    ext_feats = conn.execute("""
        SELECT * FROM int_match_features_extended WHERE match_id=?
    """, (match_id,)).fetchall()
    
    team_stats = {}
    if match:
        for ef in ext_feats:
            # Use team_id to determine side
            is_home = (ef['team_id'] == match['Home_Team_ID'])
            prefix = 'home' if is_home else 'away'
            
            team_stats[f'{prefix}_shot_pace'] = ef['shot_pace']
            team_stats[f'{prefix}_trailing_xG_ratio'] = ef['trailing_xg_ratio']
            team_stats[f'{prefix}_level_xG_ratio'] = ef['level_xg_ratio']
            team_stats[f'{prefix}_opp_adj_npxGD'] = ef['opp_adj_npxgd']
            # Default missing scores to 0
            team_stats[f'{prefix}_threat_pace'] = 0
            team_stats[f'{prefix}_xGA_impact_score'] = 0
    else:
        print(f"[WARN] Match {match_id} not found in dim_match.")

    conn.close()

    initial_state = {
        'match_id': match_id,
        'match_info': {
            'home_name': match['Home_Team_Name'] if match else 'Home Team',
            'away_name': match['Away_Team_Name'] if match else 'Away Team',
            'league': league_name,
            'date': match['Date'] if match else 'N/A',
        },
        'ml_output': {},  # 由 ml_inference 节点填充
        'odds_data': odds_data or {},
        'lineup_data': lineup_data or {},
        'team_stats_summary': team_stats,
        'agent1_output': '',
        'agent2_output': '',
        'agent3_output': '',
        'final_report': '',
    }

    # ── 执行顺序流 ──
    state = initial_state
    print("[FLOW] Running ML Inference...")
    ml_node = build_ml_inference_node(engine)
    state.update(ml_node(state))

    # ── 生成 prebuilt_quant_section（Python 精确构建，不依赖 LLM）──
    ml = state.get('ml_output', {})
    wdl = ml.get('wdl', {})
    ou = ml.get('ou', {})
    conf = ml.get('confidence', 'LOW')
    shap_wdl = ml.get('shap_wdl_top3', ml.get('attribution', []))
    shap_ou = ml.get('shap_ou_top3', [])

    h_pct = round(wdl.get('home', 0) * 100, 1)
    d_pct = round(wdl.get('draw', 0) * 100, 1)
    a_pct = round(wdl.get('away', 0) * 100, 1)

    # 优先用已换算到市场线的概率；若无则退回 >2.5 原始概率
    market_line = ou.get('market_line', 2.5)
    o_pct = round(ou.get('over_market', ou.get('over_25', 0)) * 100, 1)
    u_pct = round(ou.get('under_market', ou.get('under_25', 0)) * 100, 1)

    wdl_pick = max(wdl, key=wdl.get) if wdl else 'N/A'
    wdl_pick_cn = {'home': '主胜', 'draw': '平局', 'away': '客胜'}.get(wdl_pick, wdl_pick)
    ou_pick_cn = (f'大球(>{market_line})' if ou.get('over_market', ou.get('over_25', 0)) > 0.5
                  else f'小球(≤{market_line})')

    quant_md = f"""| 市场 | 主胜 | 平局 | 客胜 | 推荐方向 | 置信度 |
|------|------|------|------|----------|--------|
| **胜平负** | {h_pct}% | {d_pct}% | {a_pct}% | {wdl_pick_cn} | {conf} |

| 市场 | 大球(>{market_line}) | 小球(≤{market_line}) | 推荐方向 |
|------|-----------|-----------|----------|
| **大小球** | {o_pct}% | {u_pct}% | {ou_pick_cn} |"""

    state['prebuilt_quant_section'] = quant_md
    print(f"[FLOW] prebuilt_quant_section 已生成 ({len(quant_md)} chars)")

    print("[FLOW] Running Agent 1...")
    a1_node = build_agent_node(llm, AGENT1_SYSTEM_PROMPT, 'agent1_output')
    state.update(a1_node(state))

    print("[FLOW] Running Agent 2...")
    a2_node = build_agent_node(llm, AGENT2_SYSTEM_PROMPT, 'agent2_output')
    state.update(a2_node(state))

    print("[FLOW] Running Agent 3...")
    a3_node = build_agent_node(llm, AGENT3_SYSTEM_PROMPT, 'agent3_output')
    state.update(a3_node(state))

    print("[FLOW] Running Agent 4 (Synthesis)...")
    a4_node = build_agent_node(llm, AGENT4_SYSTEM_PROMPT, 'final_report')
    state.update(a4_node(state))

    # ── 后处理：用 Python 生成的精确量化板块替换 LLM 输出的整个量化段 ──
    import re
    report = state.get('final_report', '研报生成失败：最终节点未返回数据。')

    # 构建 SHAP Top-3 表格
    shap_wdl_md = ""
    if shap_wdl:
        # 特征名翻译映射
        feat_cn = {
            # 射门节奏 & 进攻效率
            'home_roll_shot_pace': '主队射门节奏', 'away_roll_shot_pace': '客队射门节奏',
            'total_shot_pace': '全场射门节奏',
            'home_roll_trailing_xg_ratio': '主队落后时进攻比', 'away_roll_trailing_xg_ratio': '客队落后时进攻比',
            'home_roll_level_xg_ratio': '主队平局时进攻比', 'away_roll_level_xg_ratio': '客队平局时进攻比',
            # 对手强度加权
            'home_roll_opp_adj_npxgd': '主队对手强度加权进球差', 'away_roll_opp_adj_npxgd': '客队对手强度加权进球差',
            # 休息天数
            'home_roll_rest_days': '主队近期休息天数', 'away_roll_rest_days': '客队近期休息天数',
            'home_rest_days': '主队休息天数', 'away_rest_days': '客队休息天数',
            'rest_days_diff': '双方休息天数差',
            # 近5场滚动统计
            'home_roll_5_npxGD': '主队近5场非罚进球差', 'away_roll_5_npxGD': '客队近5场非罚进球差',
            'home_roll_5_xGD': '主队近5场预期进球差', 'away_roll_5_xGD': '客队近5场预期进球差',
            'home_roll_5_ppda': '主队近5场防守压迫强度', 'away_roll_5_ppda': '客队近5场防守压迫强度',
            'home_roll_5_field_tilt': '主队近5场阵地推进', 'away_roll_5_field_tilt': '客队近5场阵地推进',
            'home_roll_5_box_shot_ratio': '主队近5场禁区射门占比', 'away_roll_5_box_shot_ratio': '客队近5场禁区射门占比',
            'home_roll_5_poss_diff': '主队近5场控球率差值', 'away_roll_5_poss_diff': '客队近5场控球率差值',
            'home_roll_5_big_chances_created': '主队近5场大机会创造', 'away_roll_5_big_chances_created': '客队近5场大机会创造',
            'home_roll_5_shot_quality_added': '主队近5场射门质量增益', 'away_roll_5_shot_quality_added': '客队近5场射门质量增益',
            # ELO & 综合差值
            'home_pre_match_elo': '主队赛前实力评分', 'away_pre_match_elo': '客队赛前实力评分',
            'elo_diff': '实力评分差', 'xGD_diff': '预期进球差差值',
            'ppda_diff': '防守压迫强度差', 'field_tilt_diff': '阵地推进比差值',
            'npxGD_abs_diff': '非罚进球差绝对值',
            # 欧赔
            'eu_implied_home': '欧赔隐含主胜概率', 'eu_implied_draw': '欧赔隐含平局概率',
            'eu_implied_away': '欧赔隐含客胜概率', 'eu_odds_home': '欧赔主胜赔率',
            'eu_odds_draw': '欧赔平局赔率', 'eu_odds_away': '欧赔客胜赔率',
            'odds_max_prob': '赔率最大隐含概率', 'odds_entropy': '赔率信息熵',
            # 亚盘
            'ah_line': '亚盘让球线', 'ah_home_odds': '亚盘主队赔率', 'ah_away_odds': '亚盘客队赔率',
            'ah_implied_home': '亚盘隐含主队概率', 'ah_line_abs': '亚盘让球绝对值',
            'ah_line_direction': '亚盘让球方向',
            # 其他
            'is_cup': '杯赛标识',
        }
        direction = shap_wdl[0].get('direction', wdl_pick_cn) if shap_wdl else wdl_pick_cn
        shap_wdl_md = f"\n**WDL 市场 Top-3 驱动特征（最强方向：{direction}）**\n"
        shap_wdl_md += "| 排名 | 特征（中文） | 归因值 |\n|---|---|---|\n"
        for i, s in enumerate(shap_wdl[:3]):
            fn = s.get('feature', '')
            cn = feat_cn.get(fn, fn)
            sv = s.get('shap_value', 0)
            shap_wdl_md += f"| {i+1} | {cn} | {sv} |\n"

    shap_ou_md = ""
    if shap_ou:
        direction = shap_ou[0].get('direction', ou_pick_cn) if shap_ou else ou_pick_cn
        shap_ou_md = f"\n**大小球市场 Top-3 驱动特征（最强方向：{direction}）**\n"
        shap_ou_md += "| 排名 | 特征（中文） | 归因值 |\n|---|---|---|\n"
        for i, s in enumerate(shap_ou[:3]):
            fn = s.get('feature', '')
            cn = feat_cn.get(fn, fn)
            sv = s.get('shap_value', 0)
            shap_ou_md += f"| {i+1} | {cn} | {sv} |\n"

    # 完整的量化板块（含归因小节标题）
    shap_section = ""
    if shap_wdl_md or shap_ou_md:
        shap_section = f"\n### 🔍 核心特征归因（算法决策驱动因素）\n{shap_wdl_md}{shap_ou_md}"
    full_quant = f"## 🔬 量化概率基准线\n\n{quant_md}{shap_section}"

    # 替换 LLM 输出中的整个量化段
    # 用纯文本查找替代 regex，避免 emoji 编码问题
    marker = '量化概率基准线'
    lines = report.split('\n')
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if marker in line and line.strip().startswith('#'):
            start_idx = i
        elif start_idx is not None and i > start_idx and line.strip().startswith('## ') and marker not in line:
            end_idx = i
            break
    if start_idx is not None:
        if end_idx is None:
            end_idx = len(lines)
        report = '\n'.join(lines[:start_idx]) + '\n' + full_quant + '\n\n' + '\n'.join(lines[end_idx:])
    else:
        # LLM 没输出量化标题，在报告开头第一个 ## 之前插入
        first_section = report.find('\n## ')
        if first_section > 0:
            report = report[:first_section] + '\n\n' + full_quant + '\n\n---\n' + report[first_section:]
        else:
            report = full_quant + '\n\n---\n\n' + report

    # 清理多余空行
    report = re.sub(r'\n{3,}', '\n\n', report)

    return report


# ═══════════════════════════════════════════════════
# Section 6: Prompt 导出 (供外部测试/调试)
# ═══════════════════════════════════════════════════

PROMPTS = {
    'agent1_data_narrative': AGENT1_SYSTEM_PROMPT,
    'agent2_odds_analysis': AGENT2_SYSTEM_PROMPT,
    'agent3_power_assessment': AGENT3_SYSTEM_PROMPT,
    'agent4_report_synthesis': AGENT4_SYSTEM_PROMPT,
}


def export_prompts(output_path: str = './prompts_export.json'):
    """导出所有 prompt 为 JSON 文件，方便版本管理和 A/B 测试"""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(PROMPTS, f, ensure_ascii=False, indent=2)
    print(f"[EXPORT] Prompts saved → {output_path}")
