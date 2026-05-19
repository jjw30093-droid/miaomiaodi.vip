"""
review_service.py — 赛后 AI 自动复盘核心服务

流程：
  1. 从 report_store 查询所有待复盘比赛（match_status='finished' & review=NULL）
  2. 调用 fetch_actual_match_data() 拉取真实赛后数据（爬虫接入前用 Mock）
  3. 组装 Prompt，调用通义千问（Qwen via DashScope）生成复盘 Markdown
  4. 回写 post_match_shots + post_match_review 到数据库

环境变量（必须配置）：
  DASHSCOPE_API_KEY — 阿里云百炼 / DashScope API Key（.env 自动加载）
  DB_PATH           — SQLite 数据库路径（与其他模块共享）
  QWEN_REVIEW_MODEL — 默认 qwen3.6-plus
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random

# 加载 .env（与 config.py 保持一致，避免 load_dotenv 兼容问题）
if not os.getenv("DASHSCOPE_API_KEY"):
    _env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(_env_path):
        with open(_env_path) as _f:
            for _line in _f:
                if "=" in _line and not _line.startswith("#"):
                    _k, _v = _line.strip().split("=", 1)
                    os.environ[_k] = _v

# 2026-04-26 起：复盘 LLM 由 Gemini → 通义千问（DashScope OpenAI-compatible）
from openai import OpenAI as _OpenAI

from review_models import (
    ActualMatchData,
    PendingReview,
    fetch_pending_reviews,
    write_review_result,
)

log = logging.getLogger(__name__)

DB_PATH         = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "football_uk.db"))
DASHSCOPE_KEY   = os.environ.get("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE  = os.environ.get("DASHSCOPE_BASE_URL",
                                 "https://dashscope.aliyuncs.com/compatible-mode/v1")
# CLAUDE.md §A5：默认避开已耗尽的 qwen3.6-* 系列；env 可覆盖
QWEN_MODEL          = os.environ.get("QWEN_REVIEW_PRIMARY",
                                     os.environ.get("QWEN_REVIEW_MODEL", "deepseek-v4-flash"))
QWEN_FALLBACK_MODEL = os.environ.get("QWEN_REVIEW_FALLBACK", "deepseek-v4-flash")
MAX_TOKENS      = 4096


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — 外部数据拉取（Mock，待真实爬虫接入后替换函数体）
# ─────────────────────────────────────────────────────────────────────────────

def _generate_shot_coords(n: int, x_range: tuple[float, float], y_range: tuple[float, float]) -> list[dict]:
    """生成 n 个落在指定区域内、带 xg 值的射门坐标点。"""
    shots = []
    for _ in range(n):
        x   = round(random.uniform(*x_range), 1)
        y   = round(random.uniform(*y_range), 1)
        # 距离球门越近 xg 越高，简单用距离倒数模拟
        dist = ((x - 105) ** 2 + (y - 34) ** 2) ** 0.5
        xg   = round(max(0.02, min(0.85, 2.5 / (dist + 1))), 3)
        shots.append({"x": x, "y": y, "xg": xg, "on_target": random.random() > 0.5})
    return shots


async def fetch_actual_match_data(match_id: str, home_team: str, away_team: str) -> ActualMatchData:
    """
    【占位 Mock — 待爬虫接入后替换】
    模拟从外部数据源异步拉取真实比分、npxG 和射门坐标。
    数据结构与真实接口保持一致，方便后续无缝替换。
    """
    # 模拟网络延迟
    await asyncio.sleep(random.uniform(0.3, 0.8))

    home_score = random.randint(0, 3)
    away_score = random.randint(0, 3)
    home_npxg  = round(random.uniform(0.4, 2.8), 2)
    away_npxg  = round(random.uniform(0.3, 2.2), 2)

    # 生成赛场坐标系 (105×68) 下的射门点
    # 主队攻向右侧球门 (x≈105)，客队攻向左侧球门 (x≈0)
    home_shots_raw = _generate_shot_coords(random.randint(5, 18), (75, 104), (10, 58))
    away_shots_raw = _generate_shot_coords(random.randint(4, 15), (1, 30),  (10, 58))

    post_match_shots = {
        "homeTeam": {"name": home_team, "shots": home_shots_raw, "npxg": home_npxg},
        "awayTeam": {"name": away_team, "shots": away_shots_raw, "npxg": away_npxg},
    }

    log.info(f"[ReviewService] Mock data fetched for {match_id}: {home_score}-{away_score}")

    return ActualMatchData(
        match_id         = match_id,
        home_score       = home_score,
        away_score       = away_score,
        home_npxg        = home_npxg,
        away_npxg        = away_npxg,
        home_possession  = round(random.uniform(38, 62), 1),
        away_possession  = 0.0,  # 由下方计算
        home_shots_total = len(home_shots_raw),
        away_shots_total = len(away_shots_raw),
        post_match_shots = post_match_shots,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Prompt 工厂
# ─────────────────────────────────────────────────────────────────────────────

def build_review_prompt(pending: PendingReview, actual: ActualMatchData) -> str:
    """
    将赛前推演结论与赛后真实数据组合为结构化 Prompt。
    风格要求：极其客观、冷静的量化分析师，杜绝情绪化表达。
    """
    pre_prob_summary = (
        f"主胜概率 {pending.home_prob:.1f}% / "
        f"平局概率 {pending.draw_prob:.1f}% / "
        f"客胜概率 {pending.away_prob:.1f}%"
        if all(v is not None for v in [pending.home_prob, pending.draw_prob, pending.away_prob])
        else "（赛前概率数据缺失）"
    )

    actual_result = (
        f"{actual.home_score} - {actual.away_score} "
        f"（{'主胜' if actual.home_score > actual.away_score else '客胜' if actual.away_score > actual.home_score else '平局'}）"
    )

    return f"""你是一名极其严苛、客观的足球量化模型审计师。你的任务是对以下比赛进行赛后数据复盘。
请使用冷静、精准的量化分析师语气，杜绝主观情绪表达，所有观点必须有数据支撑。

## 比赛信息
- 联赛：{pending.league}
- 赛事：{pending.home_team} vs {pending.away_team}
- 比赛时间：{pending.match_time}

## 赛前模型输出
### 胜率预测
{pre_prob_summary}

### 赛前 AI 推演结论（原文）
{pending.inference or "（无赛前推演文本）"}

## 赛后真实数据
- 最终比分：{actual_result}
- 主队真实 npxG：{actual.home_npxg}
- 客队真实 npxG：{actual.away_npxg}
- 主队控球率：{actual.home_possession:.1f}%
- 主队总射门：{actual.home_shots_total} 次
- 客队总射门：{actual.away_shots_total} 次

---

请严格按照以下三段式结构输出复盘 Markdown，不得遗漏任何段落，不得添加额外段落：

## 1. 推演结果核对

对赛前预测结论与最终结果进行逐条比对。哪些预判准确？哪些出现偏差？
给出一个客观的"预测准确度评级"（A/B/C/D），并说明依据。

## 2. 场面与数据归因（核心）

- **npxG 差值分析**：本场主队 npxG {actual.home_npxg} vs 客队 {actual.away_npxg}，差值 {actual.home_npxg - actual.away_npxg:+.2f}。请解读这一数字背后的场面控制逻辑。
- **比分 vs 期望值**：实际比分（{actual_result}）与 npxG 预期是否吻合？如存在偏差，列出可能的归因（如门将超常发挥、定位球、红牌等）。
- **射门质量评估**：结合射门次数与 npxG，评价双方的转化效率。

## 3. 模型校准与反思

- 如果预测出现偏差，请客观指出模型可能忽略的变量（伤停复出、主场优势、盘口异动等）。
- 本场对模型未来同类场景预测有何校准价值？给出 1-2 条具体的改进方向。
- 用一句话总结本场复盘的核心洞察。

> 注意：整个复盘必须建立在上方数据基础上，不得凭空捏造数据或场景描述。"""


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — 调用通义千问（DashScope OpenAI-compatible）生成复盘
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "你是喵弟量化实验室的首席模型审计 AI。"
    "你的职责是对足球赛前预测模型进行严格的赛后复盘审计，"
    "以极其客观、冷静的量化分析师风格输出结构化 Markdown 报告。"
    "你的分析必须基于数据，拒绝任何情绪化表达。"
)


def _call_qwen_sync(prompt: str) -> str:
    """同步调用千问（避免 aiohttp 版本兼容问题）。

    含 primary→fallback：QWEN_REVIEW_PRIMARY 失败（quota/超时/5xx/限流）时
    自动重试 QWEN_REVIEW_FALLBACK。CLAUDE.md §A5 上线前修复。
    """
    if not DASHSCOPE_KEY:
        raise EnvironmentError("DASHSCOPE_API_KEY 未配置，请检查 .env 文件。")

    client   = _OpenAI(api_key=DASHSCOPE_KEY, base_url=DASHSCOPE_BASE, timeout=120)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": prompt},
    ]
    # extra_body：关闭思维链，避免每次调用产生 500+ 推理 token 白白计费
    # 不写 enable_search → 默认 False（已迁移目标，省联网搜索账单）
    last_err = None
    for _model in (QWEN_MODEL, QWEN_FALLBACK_MODEL):
        if not _model:
            continue
        try:
            response = client.chat.completions.create(
                model       = _model,
                messages    = messages,
                max_tokens  = MAX_TOKENS,
                temperature = 0.3,
                extra_body  = {"enable_thinking": False},
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            log.warning(f"[ReviewService] 千问 {_model} 调用失败，尝试 fallback: {e}")
            last_err = e
    raise RuntimeError(f"所有千问模型均失败（primary={QWEN_MODEL}, fallback={QWEN_FALLBACK_MODEL}）: {last_err}")


async def call_qwen_for_review(prompt: str) -> str:
    """在 thread pool 中执行同步调用，对外保持 async 接口。"""
    try:
        return await asyncio.to_thread(_call_qwen_sync, prompt)
    except Exception as e:
        status = getattr(e, "status_code", None) or getattr(e, "code", None)
        if status == 429:
            log.warning(f"[ReviewService] 千问限流，60 秒后重试: {e}")
            await asyncio.sleep(60)
        elif status in (401, 403):
            log.error(f"[ReviewService] 千问认证失败，请检查 DASHSCOPE_API_KEY: {e}")
        else:
            log.error(f"[ReviewService] 千问 API 错误: {e}")
        raise


# 兼容旧名（保险，避免外部 import 断裂）
_call_gemini_sync       = _call_qwen_sync
call_gemini_for_review  = call_qwen_for_review


# ─────────────────────────────────────────────────────────────────────────────
# 主入口 — 批量复盘编排器
# ─────────────────────────────────────────────────────────────────────────────

async def generate_post_match_reviews(db_path: str = DB_PATH) -> dict:
    """
    主编排函数，由 FastAPI BackgroundTasks 调用。

    返回摘要字典，记录本次批次的处理结果，方便日志追踪。
    """
    log.info("[ReviewService] ▶ 开始批量赛后复盘任务...")

    # Step 1: 查询所有待复盘比赛
    pending_list = fetch_pending_reviews(db_path)
    if not pending_list:
        log.info("[ReviewService] ✅ 无待处理复盘任务，退出。")
        return {"processed": 0, "succeeded": 0, "failed": 0}

    log.info(f"[ReviewService] 发现 {len(pending_list)} 场待复盘比赛，开始逐一处理...")

    succeeded, failed = 0, 0

    for pending in pending_list:
        match_id = pending.match_id
        log.info(f"[ReviewService] 处理: [{match_id}] {pending.home_team} vs {pending.away_team}")

        try:
            # Step 2: 拉取赛后真实数据（Mock，待替换）
            actual = await fetch_actual_match_data(
                match_id  = match_id,
                home_team = pending.home_team,
                away_team = pending.away_team,
            )

            # Step 3: 组装 Prompt 并调用千问
            prompt = build_review_prompt(pending, actual)
            review_markdown = await call_qwen_for_review(prompt)

            # Step 4: 回写数据库（内含事务保护）
            write_review_result(
                db_path           = db_path,
                match_id          = match_id,
                post_match_shots  = actual.post_match_shots,
                post_match_review = review_markdown,
            )

            log.info(f"[ReviewService] ✅ [{match_id}] 复盘完成，已写入数据库。")
            succeeded += 1

        except EnvironmentError as e:
            # API Key 未配置，整批中止（无意义继续）
            log.critical(f"[ReviewService] 环境配置错误，中止批次: {e}")
            failed += len(pending_list) - succeeded
            break

        except Exception as e:
            # 单场失败不影响其他场次
            log.error(f"[ReviewService] ❌ [{match_id}] 处理失败，跳过: {e}", exc_info=True)
            failed += 1
            continue

    summary = {
        "processed": len(pending_list),
        "succeeded": succeeded,
        "failed":    failed,
    }
    log.info(f"[ReviewService] 批次完成: {summary}")
    return summary
