"""
run_post_match_reviews.py
=========================
赛后复盘一键运行器：
  1. 将所有已过期的归档研报标记为 'finished'
  2. 从真实数据库（fact_shotmap / fact_team_match_stats / fact_player_match_stats）
     填充 post_match_shots 及球员关键数据
  3. 调用 Claude 生成量化赛后复盘 Markdown，写回 report_store.post_match_review

用法：
  python run_post_match_reviews.py              # 复盘所有待处理归档场次
  python run_post_match_reviews.py --dry-run    # 只打印，不写库，不调 API
  python run_post_match_reviews.py --ids 4837403 5231047  # 指定 match_id
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(PROJECT_ROOT))

# 加载 .env（与 config.py 保持一致）
_env_file = PROJECT_ROOT / ".env"
if not os.environ.get("DASHSCOPE_API_KEY") and _env_file.exists():
    with open(_env_file) as _f:
        for _line in _f:
            if "=" in _line and not _line.startswith("#"):
                _k, _v = _line.strip().split("=", 1)
                os.environ[_k] = _v

# 2026-04-26 起：复盘 LLM 由 Gemini → 通义千问（DashScope OpenAI-compatible）
# 与 run_tonight_reports.py 保持同一模型源
from openai import OpenAI as _OpenAI

DB_PATH         = str(PROJECT_ROOT / "football_uk.db")
DASHSCOPE_KEY   = os.environ.get("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE  = os.environ.get("DASHSCOPE_BASE_URL",
                                 "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL          = os.environ.get("QWEN_REVIEW_PRIMARY",
                                     os.environ.get("QWEN_REVIEW_MODEL", "deepseek-v4-flash"))
QWEN_FALLBACK_MODEL = os.environ.get("QWEN_REVIEW_FALLBACK", "deepseek-v4-flash")
MAX_TOKENS      = 4096

SYSTEM_PROMPT = (
    "你是喵弟量化实验室的首席模型审计 AI。"
    "你的职责是对足球赛前预测模型进行严格的赛后复盘审计，"
    "以极其客观、冷静的量化分析师风格输出结构化 Markdown 报告。"
    "你的分析必须基于数据，拒绝任何情绪化表达。"
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_targets(match_ids: list[str] | None = None) -> list[sqlite3.Row]:
    """
    返回需要复盘的研报列表：
    - is_archived=1
    - match_time < now（比赛已结束）
    - post_match_review IS NULL（尚未复盘）
    """
    conn = get_db()
    try:
        if match_ids:
            placeholders = ','.join('?' * len(match_ids))
            rows = conn.execute(f"""
                SELECT match_id, home_team, away_team, league, match_time,
                       inference, home_prob, away_prob, draw_prob, match_status
                FROM report_store
                WHERE match_id IN ({placeholders})
                  AND is_archived = 1
                  AND post_match_review IS NULL
                ORDER BY match_time DESC
            """, match_ids).fetchall()
        else:
            rows = conn.execute("""
                SELECT match_id, home_team, away_team, league, match_time,
                       inference, home_prob, away_prob, draw_prob, match_status
                FROM report_store
                WHERE is_archived = 1
                  AND match_time < datetime('now', '+8 hours')
                  AND post_match_review IS NULL
                ORDER BY match_time DESC
            """).fetchall()
        return list(rows)
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — 标记比赛状态 & 拉取真实数据
# ─────────────────────────────────────────────────────────────────────────────

def fetch_real_match_data(match_id: str) -> dict | None:
    """
    从 dim_match / fact_team_match_stats / fact_shotmap / fact_player_match_stats
    组装真实赛后数据。返回 None 表示数据不可用。
    """
    conn = get_db()
    try:
        mid = int(match_id)

        # ── dim_match 基础信息 ──────────────────────────────────────────────
        dm = conn.execute("""
            SELECT Home_Team_ID, Away_Team_ID, Home_Team_Name, Away_Team_Name,
                   home_score, away_score
            FROM dim_match WHERE Match_ID = ?
        """, (mid,)).fetchone()
        if not dm:
            return None

        home_team_id = dm["Home_Team_ID"]
        away_team_id = dm["Away_Team_ID"]
        home_score   = dm["home_score"]
        away_score   = dm["away_score"]

        # ── fact_team_match_stats ───────────────────────────────────────────
        def get_team_stats(team_id):
            row = conn.execute("""
                SELECT Goals, expected_goals, expected_goals_non_penalty,
                       BallPossesion, total_shots, ShotsOnTarget, big_chance
                FROM fact_team_match_stats
                WHERE Match_ID = ? AND Team_ID = ? AND Period = 'All'
            """, (mid, team_id)).fetchone()
            return row

        home_ts = get_team_stats(home_team_id)
        away_ts = get_team_stats(away_team_id)

        # ── fact_shotmap ────────────────────────────────────────────────────
        def get_shots(team_id):
            rows = conn.execute("""
                SELECT s.Player_ID, dp.player_name, s.Minute, s.Period,
                       s.X_Coord, s.Y_Coord, s.xG, s.xGOT, s.Situation,
                       s.Outcome, s.Shot_Type
                FROM fact_shotmap s
                LEFT JOIN dim_player dp ON dp.player_id = CAST(s.Player_ID AS TEXT)
                WHERE s.Match_ID = ? AND s.Team_ID = ?
                ORDER BY s.Minute
            """, (mid, team_id)).fetchall()
            return [
                {
                    "player_id":  r["Player_ID"],
                    "player":     r["player_name"] or f"Player#{r['Player_ID']}",
                    "minute":     r["Minute"],
                    "period":     r["Period"],
                    "x":          r["X_Coord"],
                    "y":          r["Y_Coord"],
                    "xg":         round(r["xG"] or 0, 4),
                    "xgot":       round(r["xGOT"] or 0, 4),
                    "situation":  r["Situation"],
                    "outcome":    r["Outcome"],
                    "shot_type":  r["Shot_Type"],
                    "on_target":  r["Outcome"] in ("AttemptSaved", "Goal"),
                }
                for r in rows
            ]

        home_shots = get_shots(home_team_id)
        away_shots = get_shots(away_team_id)

        # ── fact_player_match_stats 关键球员 ────────────────────────────────
        def get_top_players(team_id, limit=6):
            rows = conn.execute("""
                SELECT p.Player_ID, dp.player_name, p.minutes_played,
                       p.rating_title, p.xg_and_xa, p.goals, p.assists,
                       p.expected_goals, p.expected_assists, p.chances_created,
                       p.ShotsOnTarget, p.defensive_actions, p.recoveries,
                       p.is_goalkeeper
                FROM fact_player_match_stats p
                LEFT JOIN dim_player dp ON dp.player_id = CAST(p.Player_ID AS TEXT)
                WHERE p.Match_ID = ? AND p.Team_ID = ?
                ORDER BY COALESCE(p.xg_and_xa, 0) + COALESCE(p.goals, 0) * 0.5 DESC
                LIMIT ?
            """, (mid, team_id, limit)).fetchall()
            return [
                {
                    "player_id":   r["Player_ID"],
                    "name":        r["player_name"] or f"Player#{r['Player_ID']}",
                    "minutes":     r["minutes_played"],
                    "rating":      r["rating_title"],
                    "xg_xa":       round(r["xg_and_xa"] or 0, 3),
                    "goals":       r["goals"],
                    "assists":     r["assists"],
                    "xg":          round(r["expected_goals"] or 0, 3),
                    "xa":          round(r["expected_assists"] or 0, 3),
                    "chances":     r["chances_created"],
                    "sot":         r["ShotsOnTarget"],
                    "def_actions": r["defensive_actions"],
                    "recoveries":  r["recoveries"],
                    "is_gk":       bool(r["is_goalkeeper"]),
                }
                for r in rows
            ]

        home_players = get_top_players(home_team_id)
        away_players = get_top_players(away_team_id)

        # ── 汇总 ────────────────────────────────────────────────────────────
        home_npxg = sum(s["xg"] for s in home_shots)
        away_npxg = sum(s["xg"] for s in away_shots)

        return {
            "match_id":    match_id,
            "home_score":  home_score,
            "away_score":  away_score,
            "home_npxg":   round(home_npxg, 3),
            "away_npxg":   round(away_npxg, 3),
            "home_poss":   float(home_ts["BallPossesion"] or 0) if home_ts else 0,
            "away_poss":   float(away_ts["BallPossesion"] or 0) if away_ts else 0,
            "home_shots":  len(home_shots),
            "away_shots":  len(away_shots),
            "home_sot":    float(home_ts["ShotsOnTarget"] or 0) if home_ts else 0,
            "away_sot":    float(away_ts["ShotsOnTarget"] or 0) if away_ts else 0,
            "home_xg_ts":  float(home_ts["expected_goals"] or 0) if home_ts else home_npxg,
            "away_xg_ts":  float(away_ts["expected_goals"] or 0) if away_ts else away_npxg,
            "post_match_shots": {
                "homeTeam": {
                    "name":   dm["Home_Team_Name"],
                    "npxg":   round(home_npxg, 3),
                    "shots":  home_shots,
                },
                "awayTeam": {
                    "name":   dm["Away_Team_Name"],
                    "npxg":   round(away_npxg, 3),
                    "shots":  away_shots,
                },
            },
            "home_players": home_players,
            "away_players": away_players,
        }
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Prompt 构建（注入真实数据）
# ─────────────────────────────────────────────────────────────────────────────

def build_prompt(row: sqlite3.Row, data: dict) -> str:
    home_team  = row["home_team"]
    away_team  = row["away_team"]
    league     = row["league"] or "未知联赛"
    match_time = row["match_time"] or ""
    inference  = row["inference"] or "（无赛前 AI 推演文本）"

    home_prob = row["home_prob"]
    away_prob = row["away_prob"]
    draw_prob = row["draw_prob"]

    if all(v is not None for v in [home_prob, draw_prob, away_prob]):
        prob_line = f"主胜 {home_prob:.1f}% / 平局 {draw_prob:.1f}% / 客胜 {away_prob:.1f}%"
    else:
        prob_line = "（赛前概率数据缺失）"

    hs, as_ = data["home_score"], data["away_score"]
    if hs is None or as_ is None:
        result_line = "（比分数据缺失）"
        result_tag  = "未知"
    else:
        result_tag  = "主胜" if hs > as_ else "客胜" if as_ > hs else "平局"
        result_line = f"{hs} - {as_}（{result_tag}）"

    def fmt_players(players: list[dict], team_name: str) -> str:
        if not players:
            return f"{team_name}：（无球员数据）"
        lines = [f"**{team_name} 关键球员**（按 xG+xA 排序）"]
        for p in players:
            if p["is_gk"]:
                continue
            lines.append(
                f"  - {p['name']}：{p['minutes'] or '?'}分钟，"
                f"xG+xA={p['xg_xa']:.2f}，进球={p['goals'] or 0}，"
                f"助攻={p['assists'] or 0}，射正={p['sot'] or 0}，"
                f"评分={p['rating'] or '?'}"
            )
        return "\n".join(lines)

    home_player_block = fmt_players(data["home_players"], home_team)
    away_player_block = fmt_players(data["away_players"], away_team)

    return f"""你是喵弟量化实验室的首席模型审计 AI，风格极其客观冷静，数据驱动，拒绝情绪化表达。

## 比赛信息
- 联赛：{league}
- 对阵：{home_team} vs {away_team}
- 时间：{match_time}

## 赛前模型预测
- 胜率预测：{prob_line}
- 赛前 AI 推演结论：
{inference}

## 赛后真实数据
- **最终比分：{result_line}**
- 主队 npxG：{data['home_npxg']:.3f}（射门 {data['home_shots']} 次，射正 {data['home_sot']:.0f} 次）
- 客队 npxG：{data['away_npxg']:.3f}（射门 {data['away_shots']} 次，射正 {data['away_sot']:.0f} 次）
- npxG 差值：{data['home_npxg'] - data['away_npxg']:+.3f}（正值=主队占优）
- 主队控球率：{data['home_poss']:.1f}%

{home_player_block}

{away_player_block}

---

请严格按以下三段式结构输出复盘 Markdown（不得遗漏段落，不得添加额外段落）：

## 1. 推演结果核对
逐条对比赛前预测（胜率、推演结论）与最终结果。哪些预判准确？哪些出现偏差？
给出客观的"预测准确度评级"（A=高度吻合 / B=基本吻合 / C=部分偏差 / D=严重偏差），并说明依据。

## 2. 场面与数据归因（核心）
- **npxG 差值分析**：{data['home_npxg']:.3f} vs {data['away_npxg']:.3f}（差值 {data['home_npxg'] - data['away_npxg']:+.3f}），解读场面控制逻辑。
- **比分 vs 期望值**：实际比分 {result_line} 与 npxG 预期是否吻合？如存在偏差，列举可能的归因（门将发挥、定位球、红牌、幸运球等）。
- **关键球员表现**：结合上方球员数据，点评 1-2 名对胜负影响最大的球员。
- **射门质量评估**：双方转化效率对比（xG/shot，实际进球 vs npxG）。

## 3. 模型校准与反思
- 若预测出现偏差，客观指出模型可能忽略的变量。
- 本场对同类场景预测有何校准价值？给出 1-2 条具体改进方向。
- 一句话总结本场复盘的核心洞察。

> 严格基于上方数据，不得凭空捏造数字或场景。"""


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — 调用通义千问（DashScope OpenAI-compatible）
# ─────────────────────────────────────────────────────────────────────────────

def _call_qwen_sync(prompt: str) -> str:
    """同步调用千问。

    流程：
      1. 主模型 QWEN_REVIEW_PRIMARY 调用，失败时对 503/429 等瞬时错误最多重试 4 次（指数退避）
      2. 主模型耗尽（包括重试也失败）后，切到 QWEN_REVIEW_FALLBACK 再试 2 次
      CLAUDE.md §A5 上线前修复——主模型耗额度时自动切备用，不阻塞复盘
    """
    import time as _time

    if not DASHSCOPE_KEY:
        raise EnvironmentError("DASHSCOPE_API_KEY 未配置，请检查 .env 文件。")

    client = _OpenAI(api_key=DASHSCOPE_KEY, base_url=DASHSCOPE_BASE, timeout=120)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": prompt},
    ]
    # extra_body 只关思维链；enable_search 不写 → 默认 False（省联网搜索账单）
    extra = {"enable_thinking": False}

    def _try_model(model_name: str, delays: list[int]) -> tuple[str | None, Exception | None]:
        last_exc: Exception | None = None
        for attempt, delay in enumerate([0] + delays):
            if delay:
                log.warning(f"   ⏳ 千问 [{model_name}] 暂时不可用，{delay}s 后重试（第 {attempt}/{len(delays)} 次）…")
                _time.sleep(delay)
            try:
                response = client.chat.completions.create(
                    model       = model_name,
                    messages    = messages,
                    max_tokens  = MAX_TOKENS,
                    temperature = 0.3,
                    extra_body  = extra,
                )
                return response.choices[0].message.content or "", None
            except Exception as exc:
                err_str = str(exc).lower()
                last_exc = exc
                # 瞬时错误退避重试（同模型）
                if any(tag in err_str for tag in (
                    "503", "unavailable", "429", "resource_exhausted",
                    "too many requests", "timeout", "timed out",
                )):
                    continue
                # 配额/认证类错误：直接 break，让外层切 fallback
                if any(tag in err_str for tag in (
                    "quota", "exhausted", "insufficient", "billing", "401", "403",
                )):
                    log.warning(f"   ⚠️ 千问 [{model_name}] 配额/认证类错误，立即切 fallback: {exc}")
                    break
                # 其他错误（如 400 参数错误）直接抛出
                raise
        return None, last_exc

    # 1) 主模型
    out, err = _try_model(QWEN_MODEL, [10, 30, 60, 120])
    if out is not None:
        return out

    # 2) 备用模型
    if QWEN_FALLBACK_MODEL:
        log.warning(f"   🔁 主模型 {QWEN_MODEL} 失败，切到 fallback {QWEN_FALLBACK_MODEL}")
        out2, err2 = _try_model(QWEN_FALLBACK_MODEL, [10, 30])
        if out2 is not None:
            return out2
        err = err2 or err

    raise RuntimeError(f"千问主备模型都失败（primary={QWEN_MODEL}, fallback={QWEN_FALLBACK_MODEL}）: {err}")


async def call_qwen(prompt: str) -> str:
    return await asyncio.to_thread(_call_qwen_sync, prompt)


# 兼容旧名（避免本文件其他地方引用断裂）
_call_gemini_sync = _call_qwen_sync
call_gemini       = call_qwen


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — 写库
# ─────────────────────────────────────────────────────────────────────────────

def write_results(match_id: str, data: dict, review_md: str) -> None:
    conn = get_db()
    try:
        conn.execute("BEGIN EXCLUSIVE TRANSACTION")
        conn.execute("""
            UPDATE report_store
            SET match_status      = 'finished',
                post_match_shots  = ?,
                post_match_review = ?
            WHERE match_id = ?
        """, (
            json.dumps(data["post_match_shots"], ensure_ascii=False),
            review_md,
            match_id,
        ))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_finished_only(match_id: str, data: dict) -> None:
    """dry-run 时只更新 match_status 与 post_match_shots，不写复盘。"""
    conn = get_db()
    try:
        conn.execute("""
            UPDATE report_store
            SET match_status = 'finished',
                post_match_shots = ?
            WHERE match_id = ?
        """, (
            json.dumps(data["post_match_shots"], ensure_ascii=False),
            match_id,
        ))
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────────────────────────────────────

async def main_async(dry_run: bool, match_ids: list[str] | None):
    targets = fetch_targets(match_ids)

    if not targets:
        log.info("✅ 无待复盘研报（已全部处理或无归档记录）。")
        return

    log.info(f"📋 找到 {len(targets)} 场待复盘研报：")
    for t in targets:
        log.info(f"   [{t['match_time']}] {t['home_team']} vs {t['away_team']} (id={t['match_id']})")

    succeeded = failed = skipped = 0

    for row in targets:
        mid       = row["match_id"]
        home_team = row["home_team"]
        away_team = row["away_team"]
        log.info(f"\n🔄 处理: {home_team} vs {away_team} (matchId={mid})")

        # ── 拉取真实数据 ─────────────────────────────────────────────────────
        data = fetch_real_match_data(mid)
        if not data:
            log.warning(f"   ⚠️ dim_match 无记录，跳过。")
            skipped += 1
            continue

        if data["home_score"] is None:
            log.warning(f"   ⚠️ 比分数据缺失（dim_match.home_score=NULL），跳过 LLM 复盘。")
            skipped += 1
            continue

        log.info(f"   ✅ 数据就绪：{data['home_score']}-{data['away_score']}，"
                 f"npxG {data['home_npxg']:.2f}-{data['away_npxg']:.2f}，"
                 f"shots {data['home_shots']}-{data['away_shots']}")

        if dry_run:
            log.info(f"   [DRY-RUN] 跳过 LLM 调用，仅写 match_status+post_match_shots。")
            mark_finished_only(mid, data)
            succeeded += 1
            continue

        # ── 调用千问（Qwen）──────────────────────────────────────────────────
        try:
            prompt      = build_prompt(row, data)
            review_md   = await call_qwen(prompt)
            write_results(mid, data, review_md)
            log.info(f"   ✅ 复盘已写入（{len(review_md)} 字符）。")
            succeeded += 1
        except EnvironmentError as e:
            log.critical(f"   ❌ 配置错误，中止：{e}")
            # 仍写 post_match_shots（不能因 LLM 失败而让射门图缺失）
            mark_finished_only(mid, data)
            break
        except Exception as e:
            log.error(f"   ❌ 千问失败，跳过复盘但保存射门数据：{e}", exc_info=False)
            # 确保 post_match_shots 先落库，下次 cron 可凭 post_match_review IS NULL 重试
            mark_finished_only(mid, data)
            failed += 1

    print(f"\n{'='*50}")
    print(f"🏁 复盘完成 —— 成功 {succeeded} / 跳过 {skipped} / 失败 {failed}")
    print(f"{'='*50}")

    # ── Server酱通知 ───────────────────────────────────────────────────
    try:
        from notify_utils import notify
        total = succeeded + failed
        if total > 0:                        # 静默：当天无需复盘时不打扰
            icon = "✅" if failed == 0 else ("⚠️" if succeeded > 0 else "❌")
            body_lines = [f"成功 {succeeded} · 跳过 {skipped} · 失败 {failed}"]
            if failed > 0:
                body_lines.append("失败场次可能因 Gemini 503，下次 cron 自动重试")
            notify(title=f"喵弟赛后复盘 {icon} {succeeded}/{total}场", msg="\n".join(body_lines))
    except Exception as _e:
        print(f"Server酱通知失败: {_e}")


def main():
    parser = argparse.ArgumentParser(description="赛后复盘一键运行器")
    parser.add_argument("--dry-run", action="store_true",
                        help="只填充 post_match_shots，不调用 Claude")
    parser.add_argument("--ids", nargs="+", metavar="MATCH_ID",
                        help="指定 match_id 列表")
    args = parser.parse_args()

    asyncio.run(main_async(dry_run=args.dry_run, match_ids=args.ids))


if __name__ == "__main__":
    main()
