"""
sync_router.py — 云端接收层 v1.0

职责：接收本地 Mac 推送的复合 Payload（研报 + 图表数据），
      执行 Upsert 写入 match_payloads 表。

架构说明：
  本项目统一使用 sqlite3 裸驱动（见 report_router.py / auth_router.py）。
  未引入 SQLAlchemy，原因：
    1. SQLite 不支持 JSONB，ORM 优势有限；
    2. 避免引入 Session/engine 二次管理复杂度；
    3. 与现有代码风格保持一致。
  Pydantic BaseModel 承担"SQLAlchemy Model"的数据校验职责。

鉴权：请求头 X-Sync-Token 必须与环境变量 INTERNAL_SYNC_TOKEN 一致。
"""

import os
import re
import json
import sqlite3
import logging
import glob
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Depends, Request
from pydantic import BaseModel, field_validator
from auth_deps import get_optional_user, get_current_user, CurrentUser, UserTier

# ──────────────────────────────────────────
# 🧹 Markdown 去重工具函数
# ──────────────────────────────────────────
_STRIP_PATTERNS = [
    # 标题行 (# 对阵双方：...)
    r'^# 对阵双方.*?\n(?:>.*?\n)*',
    # 量化概率基准线 (整个 ## 段落，含子标题)
    r'## 🔬 量化概率基准线.*?(?=\n## |\Z)',
    # 预计首发简报 (已提取到 lineup_brief)
    r'### 预计首发简报.*?(?=\n### |\n## |\Z)',
    # 关键伤停简报 (已提取到 lineup_brief)
    r'### 关键伤停简报.*?(?=\n### |\n## |\Z)',
    # 决策端最终结论 (旧版字段，已提取到 inference)
    r'## 🎯 决策端最终结论.*?(?=\n## |\Z)',
    # 综合结论 (新版结构化输出，已提取到 verdict_summary 卡片)
    r'## 综合结论.*?(?=\n## |\Z)',
    # 尾部免责声明
    r'---\s*>\s*⚠️.*$',
]
def strip_widget_sections(md: str) -> str:
    """
    移除 report_markdown 中已由结构化字段覆盖的段落，
    保留纯分析叙述（基础数据特征面 / 市场交易价值 / 战术分析）。
    """
    if not md:
        return md
    result = md
    for pat in _STRIP_PATTERNS:
        result = re.sub(pat, '', result, flags=re.DOTALL | re.MULTILINE)
    # 清理连续空行
    result = re.sub(r'\n{3,}', '\n\n', result).strip()
    return result

log = logging.getLogger(__name__)



# ──────────────────────────────────────────
# 📊 P0: 市场隐含概率 + 综合判断卡 — 数据聚合 helper
# ──────────────────────────────────────────
def get_market_implied_prob(conn: sqlite3.Connection, match_id: str):
    """
    从 silver_match_odds 取该场最新一条 1x2 fair_* 概率（已 vig 归一化）。
    返回百分比字典 {home, draw, away} 或 None。
    """
    try:
        r = conn.execute("""
            SELECT fair_home, fair_draw, fair_away
            FROM silver_match_odds
            WHERE CAST(match_id AS TEXT) = CAST(? AS TEXT)
              AND market = '1x2'
              AND fair_home IS NOT NULL
              AND fair_draw IS NOT NULL
              AND fair_away IS NOT NULL
            ORDER BY scraped_at DESC
            LIMIT 1
        """, [match_id]).fetchone()
    except Exception as e:
        log.warning(f"[market_implied_prob] DB error mid={match_id}: {e}")
        return None
    if not r:
        return None
    return {
        "home": round(r["fair_home"] * 100, 1),
        "draw": round(r["fair_draw"] * 100, 1),
        "away": round(r["fair_away"] * 100, 1),
    }


_VERDICT_LINE_PATTERNS = {
    "attack":      r"进攻面评估[：:]\s*主队[\s,，]*([0-9])\s*星[\s,，、]+客队[\s,，]*([0-9])\s*星",
    "defense":     r"防守面评估[：:]\s*主队[\s,，]*([0-9])\s*星[\s,，、]+客队[\s,，]*([0-9])\s*星",
    "form":        r"状态判断[：:]\s*主队[\s,，]*([\u4e00-\u9fa5/]+?)[\s,，、]+客队[\s,，]*([\u4e00-\u9fa5/]+?)\s*$",
    "core_logic":  r"推荐理由的核心逻辑[：:]\s*(.+?)\s*$",
}

def parse_verdict_section(md: str):
    """
    解析 markdown 里的「## 综合结论」段，返回结构化 dict 或 None。
    LLM 输出的格式（每条独立成行）：
      进攻面评估：主队 4 星，客队 2 星
      防守面评估：主队 3 星，客队 3 星
      状态判断：主队 上升期，客队 连败
      推荐方向：主胜
      推荐理由的核心逻辑：客队核心后卫缺阵 + 主队主场不败
    """
    if not md:
        return None
    m = re.search(r"## 综合结论\s*\n(.+?)(?=\n## |\Z)", md, re.DOTALL)
    if not m:
        return None
    body = m.group(1)

    out = {
        "attack_rating":  None,
        "defense_rating": None,
        "form_label":     None,
        "core_logic":     None,
    }
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue

        m_a = re.search(_VERDICT_LINE_PATTERNS["attack"], line, re.MULTILINE)
        if m_a:
            out["attack_rating"] = {"home": int(m_a.group(1)), "away": int(m_a.group(2))}
            continue

        m_d = re.search(_VERDICT_LINE_PATTERNS["defense"], line, re.MULTILINE)
        if m_d:
            out["defense_rating"] = {"home": int(m_d.group(1)), "away": int(m_d.group(2))}
            continue

        m_f = re.search(_VERDICT_LINE_PATTERNS["form"], line, re.MULTILINE)
        if m_f:
            out["form_label"] = {"home": m_f.group(1).strip(), "away": m_f.group(2).strip()}
            continue

        m_c = re.search(_VERDICT_LINE_PATTERNS["core_logic"], line, re.MULTILINE)
        if m_c:
            out["core_logic"] = m_c.group(1).strip()
            continue

    # If everything is None, the section was empty/malformed → return None for graceful degradation
    if not any(out.values()):
        return None
    return out


router = APIRouter(prefix="/api/v1", tags=["sync"])

# ──────────────────────────────────────────
# ⚙️ 配置
# ──────────────────────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH") or os.path.join(_THIS_DIR, "football_uk.db")
# 在 AWS 上通过 PM2 ecosystem 或 .env 注入此变量
INTERNAL_SYNC_TOKEN = os.environ.get("INTERNAL_SYNC_TOKEN") or ""


# ──────────────────────────────────────────
# 📐 Pydantic 请求模型（Schema）
# ──────────────────────────────────────────
class MatchPayload(BaseModel):
    """
    复合 Payload：本地计算完成后推送到云端的完整数据包。

    字段对应数据库表 match_payloads：
      match_id        TEXT  PRIMARY KEY
      report_markdown TEXT  — 完整研报 Markdown
      npxg_trend      TEXT  — JSON 序列化的 npxGD 时序数据
      shot_map_data   TEXT  — JSON 序列化的射门分布数据
      updated_at      TEXT  — ISO-8601 时间戳（客户端提供，默认为服务端时间）
      match_meta      dict  — 可选：携带比赛元数据，用于自动 UPSERT report_store
                              字段：title, home_team, away_team, home_icon, away_icon,
                                    home_prob, away_prob, draw_prob, league, match_time,
                                    status, inference, pipeline_status, preview_content
    """
    match_id:            str
    report_markdown:     str
    npxg_trend:          Any        # list[dict] 或 dict，序列化后存 TEXT
    shot_map_data:       Any        # list[dict] 或 dict，序列化后存 TEXT
    updated_at:          str | None = None
    match_meta:          dict | None = None   # 比赛元数据（可选，向后兼容）
    lineup_impact_data:  Any        = None    # LineupImpact JSON（可选，向后兼容）

    @field_validator("match_id")
    @classmethod
    def match_id_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("match_id 不能为空")
        return v

    @field_validator("npxg_trend", "shot_map_data", mode="before")
    @classmethod
    def coerce_json(cls, v: Any) -> Any:
        """允许客户端传 JSON 字符串或已解析的对象，统一内部处理。"""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError as e:
                raise ValueError(f"JSON 解析失败: {e}")
        return v


# ──────────────────────────────────────────
# 🗄️ 数据库工具
# ──────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_table(conn: sqlite3.Connection):
    """首次运行自动建表（幂等）。包含 lineup_impact_data 列的幂等迁移。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS match_payloads (
            match_id            TEXT PRIMARY KEY,
            report_markdown     TEXT NOT NULL,
            npxg_trend          TEXT NOT NULL DEFAULT '[]',
            shot_map_data       TEXT NOT NULL DEFAULT '[]',
            lineup_impact_data  TEXT NOT NULL DEFAULT '{}',
            updated_at          TEXT NOT NULL
        )
    """)
    # Idempotent migration: add column if it was missing from an older schema
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(match_payloads)")}
    if "lineup_impact_data" not in existing_cols:
        conn.execute(
            "ALTER TABLE match_payloads ADD COLUMN lineup_impact_data TEXT NOT NULL DEFAULT '{}'"
        )
        log.info("[ensure_table] Migrated: added lineup_impact_data column to match_payloads")
    conn.commit()


# ──────────────────────────────────────────
# 🔐 鉴权依赖
# ──────────────────────────────────────────
def verify_sync_token(x_sync_token: str = Header(..., alias="X-Sync-Token")):
    """
    校验内部同步令牌。
    Header 名：X-Sync-Token
    来源：环境变量 INTERNAL_SYNC_TOKEN
    """
    if not INTERNAL_SYNC_TOKEN:
        # 服务端未配置 token —— 拒绝所有请求，防止裸奔
        raise HTTPException(
            status_code=503,
            detail="服务端未配置 INTERNAL_SYNC_TOKEN，同步接口暂不可用"
        )
    if x_sync_token != INTERNAL_SYNC_TOKEN:
        raise HTTPException(status_code=401, detail="X-Sync-Token 鉴权失败")


# ──────────────────────────────────────────
# 📊 Best Recent Stat — 新手版战绩卡择优展示
# ──────────────────────────────────────────
def calc_best_recent_stat(conn: sqlite3.Connection):
    """
    从 prediction_audit 中计算 4 窗口 × 2 类型 = 8 候选，
    返回命中率最高的一个组合（用于新手版战绩卡）。

    选择规则（严格遵循 spec）:
      1. sample size >= 5
      2. hit rate >= 50%
      3. highest hit rate
      4. tie → larger sample wins
      5. still tie → AH (亚盘) preferred
      6. all candidates fail → None (前端隐藏整张卡)

    Push 处理（spec B 方案 / 业内惯例）:
      picked_correct IS NULL (push) 完全排除，不计入分子也不计入分母。
      （SQL 已通过 picked_correct IS NOT NULL 过滤）

    分类（基于实际表 schema）:
      picked_market = 'ah' → 亚盘
      picked_market = 'ou' → 大小球
      picked_market = 'wdl' → skip
    """
    rows = conn.execute("""
        SELECT picked_market, picked_correct, match_date
        FROM prediction_audit
        WHERE actual_wdl IS NOT NULL
          AND picked_market IN ('ah', 'ou')
          AND picked_direction IS NOT NULL
          AND picked_correct IS NOT NULL
        ORDER BY match_date DESC
    """).fetchall()

    ah_results = [r for r in rows if r["picked_market"] == "ah"]
    ou_results = [r for r in rows if r["picked_market"] == "ou"]

    candidates = []
    for label, results in (("亚盘", ah_results), ("大小球", ou_results)):
        for window in (5, 10, 15, 20):
            subset = results[:window]
            if len(subset) < 5:
                continue
            wins = sum(1 for r in subset if r["picked_correct"] == 1)
            hit_rate = round(wins * 100.0 / len(subset), 1)
            if hit_rate < 50.0:
                continue
            candidates.append({
                "label":          label,
                "window":         len(subset),
                "wins":           wins,
                "total":          len(subset),
                "hit_rate":       hit_rate,
                "emoji_sequence": ["hit" if r["picked_correct"] == 1 else "miss" for r in subset],
            })

    if not candidates:
        return None

    return max(candidates, key=lambda c: (
        c["hit_rate"],
        c["total"],
        1 if c["label"] == "亚盘" else 0,
    ))


# ──────────────────────────────────────────
# 📬 POST /api/v1/sync/match_payload
# ──────────────────────────────────────────
@router.post("/sync/match_payload", dependencies=[Depends(verify_sync_token)])
async def sync_match_payload(payload: MatchPayload):
    """
    接收并持久化本地推送的研报复合数据包。

    逻辑：
      - match_id 已存在 → UPDATE（更新全部字段）
      - match_id 不存在 → INSERT
      即 SQLite UPSERT：INSERT OR REPLACE INTO ...

    同时联动更新 report_store（如果该 match_id 存在），
    保证首页 /reports/latest 能立即读到最新 markdown。
    """
    conn = None
    try:
        conn = get_db()
        ensure_table(conn)

        now = datetime.now(timezone.utc).isoformat()
        updated_at = payload.updated_at or now

        # 序列化 JSON 字段
        npxg_json          = json.dumps(payload.npxg_trend,         ensure_ascii=False)
        shot_map_json      = json.dumps(payload.shot_map_data,      ensure_ascii=False)
        lineup_impact_json = json.dumps(payload.lineup_impact_data or {}, ensure_ascii=False)

        # ── Upsert into match_payloads ──
        conn.execute("""
            INSERT INTO match_payloads
                (match_id, report_markdown, npxg_trend, shot_map_data, lineup_impact_data, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                report_markdown    = excluded.report_markdown,
                npxg_trend         = excluded.npxg_trend,
                shot_map_data      = excluded.shot_map_data,
                lineup_impact_data = excluded.lineup_impact_data,
                updated_at         = excluded.updated_at
        """, [payload.match_id, payload.report_markdown,
              npxg_json, shot_map_json, lineup_impact_json, updated_at])

        # ── 联动 UPSERT report_store ──────────────────────────────────────
        # 有 match_meta → INSERT OR REPLACE（新比赛自动创建行）
        # 无 match_meta → 仅 UPDATE markdown_content（向后兼容旧推送）
        m = payload.match_meta
        if m:
            conn.execute("""
                INSERT INTO report_store
                    (match_id, title, markdown_content, preview_content,
                     home_team, away_team, home_icon, away_icon,
                     home_prob, away_prob, draw_prob, league, match_time,
                     status, inference, pipeline_status, is_archived, is_public)
                VALUES (?,?,?,?, ?,?,?,?, ?,?,?,?,?, ?,?,?, 0, 1)
                ON CONFLICT(match_id) DO UPDATE SET
                    markdown_content = CASE
                        WHEN excluded.markdown_content IN ('暂无研报内容', '', '占位') THEN report_store.markdown_content
                        ELSE excluded.markdown_content
                    END,
                    preview_content  = CASE
                        WHEN excluded.preview_content IN ('暂无研报内容', '', '占位') THEN report_store.preview_content
                        ELSE excluded.preview_content
                    END,
                    home_prob        = excluded.home_prob,
                    away_prob        = excluded.away_prob,
                    draw_prob        = excluded.draw_prob,
                    inference        = excluded.inference,
                    pipeline_status  = excluded.pipeline_status
            """, [
                payload.match_id,
                m.get("title") or f"研报: {m.get('home_team','')} vs {m.get('away_team','')}",
                payload.report_markdown,
                m.get("preview_content") or payload.report_markdown[:800],
                m.get("home_team", ""), m.get("away_team", ""),
                m.get("home_icon", ""),  m.get("away_icon", ""),
                m.get("home_prob", 0.0), m.get("away_prob", 0.0),
                m.get("draw_prob", 0.0),
                m.get("league", ""),     m.get("match_time", ""),
                m.get("status", "FREE"), m.get("inference", ""),
                m.get("pipeline_status", "PRE_MATCH_READY"),
            ])
        else:
            # 兼容旧版推送：仅更新 markdown
            conn.execute("""
                UPDATE report_store SET markdown_content = ? WHERE match_id = ?
            """, [payload.report_markdown, payload.match_id])

        conn.commit()
        log.info(f"[SyncRouter] ✅ match_id={payload.match_id} upserted @ {updated_at}")

        return {
            "status":     "ok",
            "match_id":   payload.match_id,
            "updated_at": updated_at,
        }

    except sqlite3.Error as e:
        log.error(f"[SyncRouter] DB error for {payload.match_id}: {e}")
        raise HTTPException(status_code=500, detail=f"数据库写入失败: {e}")
    except Exception as e:
        log.error(f"[SyncRouter] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()


# ──────────────────────────────────────────
# 📖 GET /api/v1/sync/match_payload/{match_id}
# ──────────────────────────────────────────
# 三级权限接口：
#   GUEST      → 401 拒绝访问（不下发任何研报数据）
#   REGISTERED → 基础图表 + 出场名单；非免费场次的 report_markdown 物理清空
#   VIP        → 全量数据，包含 report_markdown
@router.get("/sync/match_payload/{match_id}")
async def get_match_payload(
    match_id: str,
    request: Request,
    user: CurrentUser = Depends(get_optional_user),
):
    """
    读取研报复合 Payload（前端图表消费用）。

    设计原则：
      - report_markdown 始终优先从本地 .md 文件读取（保证内容最新）
      - npxg_trend / shot_map_data 从 match_payloads 表读取（图表数据）
      - 元数据（队名、图标等）从 report_store 读取

    权限层（2026-04-27 上线前硬隔离）：
      - GUEST → 401（Depends(get_current_user) 自动拒绝）
      - REGISTERED + 付费场 → 200，但 report_markdown 物理清空
      - VIP / 免费场 → 200，全量数据
    """

    conn = None
    try:
        conn = get_db()
        ensure_table(conn)

        # ── 1. 从 match_payloads 读取图表及研报数据 ──────────────
        row = conn.execute(
            "SELECT report_markdown, npxg_trend, shot_map_data, lineup_impact_data, updated_at "
            "FROM match_payloads WHERE match_id = ?",
            [match_id]
        ).fetchone()

        md_content          = row["report_markdown"]    if row else ""
        npxg_trend          = row["npxg_trend"]         if row else "{}"
        shot_map_data       = row["shot_map_data"]      if row else "{}"
        lineup_impact_raw   = row["lineup_impact_data"] if row else "{}"
        updated_at          = row["updated_at"]         if row else ""

        # Parse lineup_impact JSON — default to None if empty/malformed
        try:
            lineup_impact_data = json.loads(lineup_impact_raw) if lineup_impact_raw and lineup_impact_raw != "{}" else None
        except (json.JSONDecodeError, TypeError):
            lineup_impact_data = None

        # ── 2. 多级回退读取 report markdown ──
        if not md_content:
            # 2a. 从 report_store.markdown_content 读取（本地推送写入的内容）
            rs_row = conn.execute(
                "SELECT markdown_content FROM report_store WHERE match_id = ?",
                [match_id]
            ).fetchone()
            if rs_row and rs_row["markdown_content"]:
                md_content = rs_row["markdown_content"]
                log.info(f"[SyncRouter] ✅ Read MD from report_store.markdown_content for {match_id}")

        if not md_content:
            # 2b. 从 reports/ 目录读取 .md 文件（手动模式回退）
            reports_dir = os.path.join(
                os.path.dirname(os.path.abspath(DB_PATH)), "reports"
            )
            pattern = os.path.join(reports_dir, f"*{match_id}.md")
            files = glob.glob(pattern)
            if files:
                try:
                    with open(files[0], "r", encoding="utf-8") as f:
                        md_content = f.read()
                    log.info(f"[SyncRouter] ✅ Read MD from file: {files[0]}")
                except Exception as e:
                    log.warning(f"[SyncRouter] Failed to read MD file for {match_id}: {e}")

        # ── 3. 元数据：从 report_store 读取（含 is_free / 概率 / 赛后数据）──
        meta = conn.execute(
            """SELECT home_team, away_team, home_icon, away_icon,
                      match_time, league, status, inference,
                      home_prob, away_prob, draw_prob,
                      match_status, post_match_review, post_match_shots,
                      pipeline_status, preview_content,
                      beginner_summary, chart_insights, key_variables, key_risk,
                      CASE WHEN status='FREE' THEN 1 ELSE is_free END AS is_free
               FROM report_store WHERE match_id = ?""",
            [match_id]
        ).fetchone()

        if not meta and not md_content:
            raise HTTPException(
                status_code=404, detail=f"match_id={match_id} 不存在"
            )

        # ── 3b. 首发确认状态：从 match_pipeline 读取 ────────────────────────
        lineup_status = "predicted"
        lineup_confirmed_at = None
        try:
            mp = conn.execute(
                "SELECT lineup_confirmed_at FROM match_pipeline WHERE match_id = ?",
                [match_id]
            ).fetchone()
            if mp and mp["lineup_confirmed_at"]:
                lineup_status = "confirmed"
                lineup_confirmed_at = mp["lineup_confirmed_at"]
        except Exception:
            pass  # match_pipeline 可能未建表，静默兜底

        # ── 提取公开首发/伤停简报（在权限截断之前）───────────────────────────
        lineup_brief = ""
        if md_content:
            parts = []
            m_lineup = re.search(
                r'(### 预计首发简报\s*\n(?:(?!###).)*)', md_content, re.DOTALL
            )
            m_injury = re.search(
                r'(### 关键伤停简报\s*\n(?:(?!###).)*)', md_content, re.DOTALL
            )
            if m_lineup:
                parts.append(m_lineup.group(1).strip())
            if m_injury:
                parts.append(m_injury.group(1).strip())
            lineup_brief = '\n\n'.join(parts)

        # ── 应用 strip，去除与结构化字段重复的段落 ───────────────────────
        report_narrative = strip_widget_sections(md_content) if md_content else ""

        # ── 权限截断 ────────────────────────────────────────────────────────────
        is_free_match = bool(meta["is_free"]) if meta else False
        _hide_probs = user.is_guest
        _allow_postmatch = user.is_vip

        _meta_inference = (meta["inference"] if meta else "") if not _hide_probs else ""
        _home_prob = (meta["home_prob"] if meta else None) if not _hide_probs else None
        _away_prob = (meta["away_prob"] if meta else None) if not _hide_probs else None
        _draw_prob = (meta["draw_prob"] if meta else None) if not _hide_probs else None

        # 非 VIP：赛后复盘数据不下发
        _post_review = (meta["post_match_review"] if meta else None) if _allow_postmatch else None
        _post_shots_raw = (meta["post_match_shots"] if meta else None) if _allow_postmatch else None

        # 默认拦截，按身份逐级判断放行
        is_gated = True
        unlock_reason = None

        if user.is_guest:
            access_level = "guest"
        elif user.is_vip:
            access_level = "vip"
        else:
            access_level = "registered"

        if is_free_match:
            is_gated = False
            unlock_reason = "free_match"
        elif user.is_vip:
            is_gated = False
            unlock_reason = "vip"
        elif not user.is_guest and user.user_id:
            unlock_row = conn.execute("""
                SELECT 1 FROM user_unlocks u
                JOIN users us ON us.username = u.username
                WHERE us.id = ? AND u.match_id = ?
                LIMIT 1
            """, [user.user_id, str(match_id)]).fetchone()
            if unlock_row:
                is_gated = False
                unlock_reason = "single_unlock"
                access_level = "unlocked"

        # ── 4. 球员 & 球队统计（从 fact 表实时拼入）──────────────────
        player_stats    = None
        team_match_stats = None
        try:
            mid_int = int(match_id)

            # 4a. dim_match → 区分主客队 Team_ID
            dm = conn.execute(
                "SELECT Home_Team_ID, Away_Team_ID FROM dim_match WHERE Match_ID = ?",
                [mid_int]
            ).fetchone()

            if dm:
                home_tid = dm["Home_Team_ID"]
                away_tid = dm["Away_Team_ID"]

                # 4b. 球队整场统计（Period='All'）
                def _team_stats(team_id):
                    r = conn.execute("""
                        SELECT BallPossesion, expected_goals, total_shots,
                               ShotsOnTarget, big_chance, yellow_cards,
                               CASE WHEN total_shots > 0
                                    THEN ROUND(ShotsOnTarget * 100.0 / total_shots, 1)
                                    ELSE 0 END AS shot_accuracy
                        FROM fact_team_match_stats
                        WHERE Match_ID = ? AND Team_ID = ? AND Period = 'All'
                    """, [mid_int, team_id]).fetchone()
                    if not r:
                        return None
                    return {
                        "possession":      round(r["BallPossesion"] or 0, 1),
                        "xg":              round(r["expected_goals"] or 0, 2),
                        "total_shots":     int(r["total_shots"] or 0),
                        "shots_on_target": int(r["ShotsOnTarget"] or 0),
                        "shot_accuracy":   round(r["shot_accuracy"] or 0, 1),
                        "big_chances":     int(r["big_chance"] or 0),
                        "corners":         0,
                        "yellow_cards":    int(r["yellow_cards"] or 0),
                    }

                home_ts = _team_stats(home_tid)
                away_ts = _team_stats(away_tid)
                if home_ts or away_ts:
                    team_match_stats = {
                        "home_team": home_ts or {},
                        "away_team": away_ts or {},
                    }

                # 4c. 球员列表
                POS_MAP = {1: "GK", 2: "DF", 3: "MF", 4: "FW", 5: "FW"}

                def _player_list(team_id):
                    rows = conn.execute("""
                        SELECT p.Player_ID, dp.player_name,
                               p.is_goalkeeper, p.position_id, p.usual_position,
                               p.shirt_number, p.is_captain,
                               p.minutes_played, p.rating_title,
                               p.goals, p.assists,
                               p.expected_goals, p.ShotsOnTarget
                        FROM fact_player_match_stats p
                        LEFT JOIN dim_player dp ON dp.player_id = CAST(p.Player_ID AS TEXT)
                        WHERE p.Match_ID = ? AND p.Team_ID = ? AND p.minutes_played > 0
                        ORDER BY p.minutes_played DESC
                    """, [mid_int, team_id]).fetchall()

                    result = []
                    for r in rows:
                        name = r["player_name"] or f"#{r['Player_ID']}"
                        # 推断位置
                        if r["is_goalkeeper"]:
                            pos = "GK"
                        elif r["position_id"] and r["position_id"] in POS_MAP:
                            pos = POS_MAP[r["position_id"]]
                        elif r["usual_position"]:
                            pos = str(r["usual_position"]).upper()[:2]
                        else:
                            pos = "MF"
                        result.append({
                            "player_id":       str(r["Player_ID"]),
                            "name":            name,
                            "shirt":           r["shirt_number"] or "",
                            "position":        pos,
                            "minutes":         int(r["minutes_played"] or 0),
                            "rating":          round(float(r["rating_title"] or 0), 2),
                            "goals":           int(r["goals"] or 0),
                            "assists":         int(r["assists"] or 0),
                            "xg":              round(float(r["expected_goals"] or 0), 2),
                            "shots_on_target": int(r["ShotsOnTarget"] or 0),
                            "is_captain":      bool(r["is_captain"]),
                        })
                    return result

                home_pl = _player_list(home_tid)
                away_pl = _player_list(away_tid)
                if home_pl or away_pl:
                    player_stats = {
                        "home_team": home_pl,
                        "away_team": away_pl,
                    }

        except Exception as e:
            log.warning(f"[SyncRouter] player/team stats query failed for {match_id}: {e}")

        # 📊 P0: 市场隐含概率（来自 silver_match_odds.fair_*）
        try:
            market_implied_prob = get_market_implied_prob(conn, str(match_id))
        except Exception as e:
            log.warning(f"[SyncRouter] market_implied_prob failed: {e}")
            market_implied_prob = None

        # 🧠 P0: 综合判断卡 — 解析 LLM 综合结论段 + key_variables + key_risk + inference
        try:
            _verdict_parsed = parse_verdict_section(md_content)
        except Exception as e:
            log.warning(f"[SyncRouter] parse_verdict_section failed: {e}")
            _verdict_parsed = None

        # 新手版结构化字段（解析 JSON 字符串列）
        _beginner_summary = meta["beginner_summary"] if meta else None
        try:
            _chart_insights = json.loads(meta["chart_insights"]) if (meta and meta["chart_insights"]) else None
        except (json.JSONDecodeError, TypeError):
            _chart_insights = None
        try:
            _key_variables = json.loads(meta["key_variables"]) if (meta and meta["key_variables"]) else None
        except (json.JSONDecodeError, TypeError):
            _key_variables = None
        _key_risk = meta["key_risk"] if meta else None

        # 📊 新手版战绩卡：择优近期亚盘/大小球
        try:
            best_recent_stat = calc_best_recent_stat(conn)
        except Exception as e:
            log.warning(f"[SyncRouter] calc_best_recent_stat failed: {e}")
            best_recent_stat = None

        payload = {
            "match_id":        match_id,
            "report_markdown": report_narrative if not is_gated else None,
            "report_narrative": report_narrative if not is_gated else None,
            "lineup_brief":    lineup_brief,
            "is_gated":        is_gated,
            "access_level":    access_level,
            "unlock_reason":   unlock_reason,
            "preview_content": meta["preview_content"] if meta else None,
            "is_free":         is_free_match,
            "npxg_trend":      npxg_trend,
            "shot_map_data":   shot_map_data,
            "updated_at":      updated_at,
            "home_team":       meta["home_team"]   if meta else "",
            "away_team":       meta["away_team"]   if meta else "",
            "home_icon":       meta["home_icon"]   if meta else "",
            "away_icon":       meta["away_icon"]   if meta else "",
            "match_time":      meta["match_time"]  if meta else "",
            "league":          meta["league"]      if meta else "",
            "inference":       _meta_inference,
            "home_prob":       _home_prob,
            "away_prob":       _away_prob,
            "draw_prob":       _draw_prob,
            "player_stats":    player_stats,
            "team_match_stats": team_match_stats,
            "match_status":      meta["match_status"] if meta else "upcoming",
            "pipeline_status":   meta["pipeline_status"] if meta else None,  # PRE_MATCH_READY / FINAL_REPORT_READY / ARCHIVED
            "post_match_review":  _post_review,
            "post_match_shots":   (
                json.loads(_post_shots_raw)
                if _post_shots_raw
                else None
            ),
            "lineup_impact_data": lineup_impact_data,  # LineupImpact | None (public, no VIP gate)
            "lineup_status":      lineup_status,        # "confirmed" | "predicted"
            "lineup_confirmed_at": lineup_confirmed_at, # ISO timestamp | None
            "best_recent_stat":   best_recent_stat,    # beginner card payload
            "beginner_summary":   _beginner_summary,   # LLM 大白话一句话（可能为 None，前端 fallback）
            "chart_insights":     _chart_insights,     # dict | None — 各图表解读
            "key_variables":      _key_variables,      # list[str] | None — 关键变量 3 条
            "key_risk":           _key_risk,           # str | None — 一句话风险点
            # 🆕 P0
            "market_implied_prob": market_implied_prob,  # {home,draw,away} % | None
            "verdict_summary":     _verdict_parsed,      # {attack/defense/form/core_logic} | None — 综合判断卡聚合字段
        }

        from name_translator import translate_team, translate_player_stats
        payload["home_team"] = translate_team(payload.get("home_team"))
        payload["away_team"] = translate_team(payload.get("away_team"))
        if "player_stats" in payload and payload["player_stats"]:
            if "home_team" in payload["player_stats"]:
                payload["player_stats"]["home_team"] = translate_player_stats(payload["player_stats"]["home_team"])
            if "away_team" in payload["player_stats"]:
                payload["player_stats"]["away_team"] = translate_player_stats(payload["player_stats"]["away_team"])
                
        return payload

    finally:
        if conn:
            conn.close()
