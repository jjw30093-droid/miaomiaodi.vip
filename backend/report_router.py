import os
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from minio_service import MinioUploader, process_markdown_images
from db import get_conn
from name_translator import translate_team
from auth_deps import get_optional_user, get_current_user, CurrentUser
router = APIRouter(prefix="/api/v1", tags=["Premium Reports"])

DB_PATH    = os.environ.get("DB_PATH") or "/home/ubuntu/app/backend/football_uk.db"
WC_DB_PATH = os.environ.get("WC_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "worldcup.db"))
_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.environ.get("REPORTS_DIR", os.path.join(_THIS_DIR, "reports"))

# 单例 MinIO 服务
minio_uploader = MinioUploader()

def get_db_conn():
    return get_conn(DB_PATH)

@router.get("/report/{match_id}")
async def get_premium_report(
    match_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """登录即可查看研报全文（过渡期：CDKey 闸门暂停，登录 = 解锁）。"""
    target_path = _find_report_file(match_id)
    if not target_path:
        raise HTTPException(status_code=404, detail=f"未找到 match_id 为 {match_id} 的研报文档")

    with open(target_path, "r", encoding="utf-8") as f:
        content = f.read()

    polished_md = process_markdown_images(content, match_id, minio_uploader)
    return {
        "match_id": match_id,
        "status": "success",
        "is_unlocked": True,
        "content": polished_md,
    }


def _find_report_file(match_id: str) -> Optional[str]:
    """在 REPORTS_DIR 及其 archive/ 子目录中查找 *_{match_id}.md 文件。"""
    if not os.path.exists(REPORTS_DIR):
        return None
    for fn in os.listdir(REPORTS_DIR):
        if fn.endswith(f"_{match_id}.md"):
            return os.path.join(REPORTS_DIR, fn)
    archive_base = os.path.join(REPORTS_DIR, "archive")
    if os.path.exists(archive_base):
        for month_dir in os.listdir(archive_base):
            month_path = os.path.join(archive_base, month_dir)
            if os.path.isdir(month_path):
                for fn in os.listdir(month_path):
                    if fn.endswith(f"_{match_id}.md"):
                        return os.path.join(month_path, fn)
    return None
def _parse_match_time(match_time_str: str) -> datetime | None:
    """将 'MM-DD HH:MM' 或 'YYYY-MM-DD HH:MM:SS' 格式统一解析为 datetime。"""
    if not match_time_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m-%d %H:%M"):
        try:
            dt = datetime.strptime(match_time_str, fmt)
            # 无年份时补当前年份
            if dt.year == 1900:
                dt = dt.replace(year=datetime.now().year)
            return dt
        except ValueError:
            continue
    return None


def _classify_match(match_time_str: str) -> tuple[str, str]:
    """
    返回 (display_category, iso_time)。
    - display_category: 'UPCOMING' | 'ARCHIVE'
    - iso_time: ISO 8601 UTC 字符串（'YYYY-MM-DDTHH:MM:SSZ'）
      前端用 new Date(iso_time) 解析后转为用户浏览器本地时区显示。
    """
    dt = _parse_match_time(match_time_str)
    if dt is None:
        return "UPCOMING", match_time_str
    # 比赛时间以 UTC 存储，归档判断用 UTC 比较（开球后 2 小时归档）
    now_utc = datetime.utcnow()
    category = "ARCHIVE" if now_utc > (dt + timedelta(minutes=120)) else "UPCOMING"
    # 返回标准 UTC ISO 8601，前端自行转本地时区，不在服务端硬编码 +8h
    iso_time = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return category, iso_time


def _get_wc_cards(user) -> list:
    """
    从 worldcup.db.wc_reports 拉取世界杯比赛卡片，混入 /reports/latest。
    GUEST 档脱敏与联赛一致（无 inference/概率）。
    worldcup.db 不可用时静默返回 []，不影响联赛卡片。
    """
    try:
        conn = sqlite3.connect(WC_DB_PATH, timeout=5)
        conn.row_factory = sqlite3.Row
        # JOIN wc_fixtures → wc_teams 取队徽 image_path
        rows = conn.execute("""
            SELECT wr.match_id, wr.home_team, wr.away_team, wr.match_time,
                   wr.home_prob, wr.draw_prob, wr.away_prob,
                   wr.inference, wr.pipeline_status, wr.match_status, wr.is_free,
                   ht.image_path AS home_icon,
                   at_t.image_path AS away_icon,
                   pa.picked_correct
            FROM wc_reports wr
            LEFT JOIN wc_fixtures f ON f.sportmonks_id = wr.fixture_sportmonks_id
            LEFT JOIN wc_teams ht ON ht.sportmonks_id = f.home_team_sportmonks_id
            LEFT JOIN wc_teams at_t ON at_t.sportmonks_id = f.away_team_sportmonks_id
            LEFT JOIN wc_prediction_audit pa ON pa.match_id = wr.match_id
            WHERE wr.home_team IS NOT NULL
              AND wr.away_team IS NOT NULL
              AND wr.pipeline_status NOT IN ('TEST', 'PLACEHOLDER')
              AND wr.home_team NOT LIKE '%Group%'
              AND wr.away_team NOT LIKE '%Group%'
              AND wr.home_team NOT LIKE 'TBD%'
              AND wr.away_team NOT LIKE 'TBD%'
            ORDER BY wr.match_time DESC
            LIMIT 20
        """).fetchall()
        conn.close()
    except Exception:
        return []

    cards = []
    for r in rows:
        mid = str(r["match_id"])
        _, iso_time = _classify_match(r["match_time"] or "")
        home_icon = r["home_icon"] or None
        away_icon = r["away_icon"] or None

        if user.is_guest:
            display_category_g, _ = _classify_match(r["match_time"] or "")
            if display_category_g == "ARCHIVE":
                cards.append({
                    "id": mid,
                    "league": "世界杯",
                    "time": iso_time,
                    "display_category": "ARCHIVE",
                    "status": r["pipeline_status"] or "",
                    "pipeline_status": r["pipeline_status"],
                    "inference": r["inference"] or "",
                    "homeTeam": {"name": r["home_team"] or "", "icon": home_icon, "prob": r["home_prob"]},
                    "awayTeam": {"name": r["away_team"] or "", "icon": away_icon, "prob": r["away_prob"]},
                    "drawProb": r["draw_prob"],
                    "is_daily_free": bool(r["is_free"]),
                    "is_pinned": False,
                    "tournament_type": "wc",
                    "picked_correct": r["picked_correct"],
                })
            else:
                cards.append({
                    "id": mid,
                    "league": "世界杯",
                    "time": iso_time,
                    "display_category": "GATED",
                    "status": "GATED",
                    "pipeline_status": None,
                    "inference": "",
                    "homeTeam": {"name": r["home_team"] or "", "icon": home_icon, "prob": None},
                    "awayTeam": {"name": r["away_team"] or "", "icon": away_icon, "prob": None},
                    "drawProb": None,
                    "is_daily_free": bool(r["is_free"]),
                    "is_pinned": False,
                    "tournament_type": "wc",
                })
        else:
            display_category, _ = _classify_match(r["match_time"] or "")
            cards.append({
                "id": mid,
                "league": "世界杯",
                "time": iso_time,
                "display_category": display_category,
                "status": r["pipeline_status"] or "",
                "pipeline_status": r["pipeline_status"],
                "inference": r["inference"] or "",
                "homeTeam": {"name": r["home_team"] or "", "icon": home_icon,
                             "prob": r["home_prob"]},
                "awayTeam": {"name": r["away_team"] or "", "icon": away_icon,
                             "prob": r["away_prob"]},
                "drawProb": r["draw_prob"],
                "is_daily_free": bool(r["is_free"]),
                "is_pinned": False,
                "tournament_type": "wc",
                "picked_correct": r["picked_correct"] if display_category == "ARCHIVE" else None,
            })
    return cards


@router.get("/reports/latest")
async def get_latest_reports(user: CurrentUser = Depends(get_optional_user)):
    """
    获取首页展示的全部研报。三档脱敏：
      - GUEST（未登录）：仅 id + 队名 + 队徽 + time + league，其它字段一律置空/默认
      - REGISTERED（登录非 VIP）：完整字段，仅付费场 inference='' 截断
      - VIP：所有字段全展示
    """
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        # 1) 先算 daily_free_id（提前到循环前，避免顺序耦合）
        now_cst = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)
        utc_start = (now_cst.replace(hour=0, minute=0, second=0) - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
        utc_end   = (now_cst.replace(hour=23, minute=59, second=59) - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
        free_row = conn.execute("""
            SELECT match_id FROM report_store
            WHERE match_time BETWEEN ? AND ?
              AND home_team != 'Home' AND away_team != 'Away'
            ORDER BY match_time ASC LIMIT 1
        """, [utc_start, utc_end]).fetchone()
        daily_free_id = str(free_row["match_id"]) if free_row else None

        # 2) 拉数据
        cursor.execute("""
            SELECT
                rs.match_id as id, rs.title, rs.home_team, rs.away_team,
                rs.home_icon, rs.away_icon, rs.home_prob, rs.away_prob, rs.draw_prob,
                rs.league, rs.match_time, rs.status, rs.inference, rs.pipeline_status,
                COALESCE(rs.is_pinned, 0) as is_pinned,
                pa.picked_correct
            FROM report_store rs
            LEFT JOIN prediction_audit pa ON CAST(pa.match_id AS TEXT) = CAST(rs.match_id AS TEXT)
            WHERE rs.home_team != 'Home' AND rs.away_team != 'Away'
            ORDER BY rs.match_time DESC
            LIMIT 150
        """)
        rows = cursor.fetchall()

        matches = []
        for r in rows:
            mid = str(r["id"])
            is_free = (mid == daily_free_id)

            # ─── GUEST 档：已结束比赛全量返回；未开赛场次一律置空 ───
            if user.is_guest:
                display_category, iso_time = _classify_match(r["match_time"])
                if display_category == "ARCHIVE":
                    matches.append({
                        "id": mid,
                        "league": r["league"],
                        "time": iso_time,
                        "display_category": "ARCHIVE",
                        "status": r["pipeline_status"] or r["status"],
                        "pipeline_status": r["pipeline_status"],
                        "inference": r["inference"] or "",
                        "homeTeam": {
                            "name": translate_team(r["home_team"]),
                            "icon": r["home_icon"],
                            "prob": r["home_prob"],
                        },
                        "awayTeam": {
                            "name": translate_team(r["away_team"]),
                            "icon": r["away_icon"],
                            "prob": r["away_prob"],
                        },
                        "drawProb": r["draw_prob"],
                        "is_daily_free": False,
                        "is_pinned": False,
                        "picked_correct": r["picked_correct"],
                    })
                else:
                    matches.append({
                        "id": mid,
                        "league": r["league"],
                        "time": iso_time,
                        "display_category": "GATED",
                        "status": "GATED",
                        "pipeline_status": None,
                        "inference": "",
                        "homeTeam": {
                            "name": translate_team(r["home_team"]),
                            "icon": r["home_icon"],
                            "prob": None,
                        },
                        "awayTeam": {
                            "name": translate_team(r["away_team"]),
                            "icon": r["away_icon"],
                            "prob": None,
                        },
                        "drawProb": None,
                        "is_daily_free": False,
                        "is_pinned": False,
                    })
                continue

            # ─── REGISTERED / VIP 档：完整字段，登录即看全量 inference ───
            display_category, iso_time = _classify_match(r["match_time"])
            inference_to_send = r["inference"]
            matches.append({
                "id": mid,
                "league": r["league"],
                "time": iso_time,
                "display_category": display_category,
                "status": r["pipeline_status"] or r["status"],
                "pipeline_status": r["pipeline_status"],
                "inference": inference_to_send,
                "homeTeam": {
                    "name": translate_team(r["home_team"]),
                    "icon": r["home_icon"],
                    "prob": r["home_prob"],
                },
                "awayTeam": {
                    "name": translate_team(r["away_team"]),
                    "icon": r["away_icon"],
                    "prob": r["away_prob"],
                },
                "drawProb": r["draw_prob"],
                "is_daily_free": is_free,
                "is_pinned": bool(r["is_pinned"]),
                "picked_correct": r["picked_correct"] if display_category == "ARCHIVE" else None,
            })

        # ── 合并世界杯卡片（从 worldcup.db 拉取，失败静默）────────────────
        wc_cards = _get_wc_cards(user)
        if wc_cards:
            # 去重：wc_19609130 和 report_store 里的 19609130 是同一场，保留 WC 卡
            wc_numeric_ids = {c["id"][3:] for c in wc_cards if c["id"].startswith("wc_")}
            matches = [m for m in matches if str(m["id"]) not in wc_numeric_ids]
            matches = wc_cards + matches
            # 按 match_time 排序（WC 6 月场次自然排前）
            def _sort_key(m: dict) -> str:
                return m.get("time") or ""
            matches.sort(key=_sort_key, reverse=True)

        return matches
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/reports/daily_free_id")
async def get_daily_free_id(user: CurrentUser = Depends(get_current_user)):
    """返回今日免费场次 match_id（当天 match_time 最早的 UPCOMING 比赛）。需登录访问。"""
    conn = get_db_conn()
    try:
        now_cst = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)
        today_str = now_cst.strftime("%Y-%m-%d")
        # match_time 以 UTC 存储，用 UTC 窗口等效本日 CST 范围
        # CST 今日 00:00 = UTC 前一天 16:00; CST 今日 23:59 = UTC 今天 15:59
        utc_start = (now_cst.replace(hour=0, minute=0, second=0) - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
        utc_end   = (now_cst.replace(hour=23, minute=59, second=59) - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
        row = conn.execute("""
            SELECT match_id FROM report_store
            WHERE match_time BETWEEN ? AND ?
              AND home_team != 'Home' AND away_team != 'Away'
            ORDER BY match_time ASC
            LIMIT 1
        """, [utc_start, utc_end]).fetchone()
        return {"free_match_id": str(row["match_id"]) if row else None}
    finally:
        conn.close()


@router.get("/strategies/equity_curves")
async def get_equity_curves(
    user: CurrentUser = Depends(get_current_user),  # 2026-04-29 P0 修复：登录才可访问（注册用户即可，无需 VIP）
):
    """
    返回 V4 模型 OOS 权益曲线数据，供首页策略展示图表使用。
    数据来源：models_v4/equity_curves.json（由 fixed_stake_backtest.py 生成）
    """
    # 路径：相对于 DB_PATH 所在目录的 models_v4/
    base_dir   = os.path.dirname(os.path.abspath(DB_PATH))
    curve_path = os.path.join(base_dir, "models_v4", "equity_curves.json")
    if not os.path.exists(curve_path):
        raise HTTPException(status_code=404, detail="equity_curves.json 尚未生成，请先运行 fixed_stake_backtest.py")
    with open(curve_path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.get("/reports/archive/leagues")
async def get_archive_leagues(
    user: CurrentUser = Depends(get_current_user),
):
    """归档库中所有出现过的联赛名称（用于前端下拉选择器）。"""
    _ = user
    conn = get_db_conn()
    try:
        rows = conn.execute("""
            SELECT DISTINCT league FROM report_store
            WHERE is_archived = 1 AND league IS NOT NULL AND league != ''
            ORDER BY league
        """).fetchall()
        return [r["league"] for r in rows]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/reports/archive")
async def get_archived_reports(
    page: int = 1,
    per_page: int = 20,
    league: Optional[str] = None,       # 联赛筛选
    start_date: Optional[str] = None,   # 开赛日期起（YYYY-MM-DD，含）
    end_date: Optional[str] = None,     # 开赛日期止（YYYY-MM-DD，含）
    user: CurrentUser = Depends(get_current_user),
):
    """归档研报列表（is_archived=1），按 match_time 倒序。支持联赛和日期区间筛选。

    权限（2026-04-27 上线前硬隔离）：
      - GUEST → 401（Depends(get_current_user) 自动拒绝）
      - REGISTERED / VIP → 200，含 inference
    """
    _ = user  # 强制鉴权，user 对象本身列表查询不需要
    conn = get_db_conn()
    cursor = conn.cursor()
    try:
        # 动态拼 WHERE 条件
        conditions: list[str] = ["is_archived = 1"]
        params: list = []

        if league:
            # 支持逗号分隔多值（用于把"J联赛"映射到 East+West 两个英文变体）
            league_list = [s.strip() for s in league.split(",") if s.strip()]
            if len(league_list) == 1:
                conditions.append("league = ?")
                params.append(league_list[0])
            elif len(league_list) > 1:
                placeholders = ",".join(["?"] * len(league_list))
                conditions.append(f"league IN ({placeholders})")
                params.extend(league_list)
        if start_date:
            conditions.append("DATE(match_time) >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("DATE(match_time) <= ?")
            params.append(end_date)

        where = " AND ".join(conditions)
        offset = (page - 1) * per_page

        cursor.execute(
            f"SELECT COUNT(*) as n FROM report_store WHERE {where}",
            params,
        )
        total = cursor.fetchone()["n"]

        cursor.execute(
            f"""SELECT match_id as id, home_team, away_team, home_icon, away_icon,
                       league, match_time, status, inference, pipeline_status, created_at
                FROM report_store
                WHERE {where}
                ORDER BY match_time DESC
                LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        )
        rows = cursor.fetchall()
        return {
            "total": total, "page": page, "perPage": per_page,
            "data": [{
                "id":              r["id"],
                "league":          r["league"],
                "time":            r["match_time"],
                "createdAt":       r["created_at"],
                "status":          r["pipeline_status"] or r["status"],
                "pipeline_status": r["pipeline_status"],
                "inference":       r["inference"],
                "homeTeam":        {"name": translate_team(r["home_team"]), "icon": r["home_icon"]},
                "awayTeam":        {"name": translate_team(r["away_team"]), "icon": r["away_icon"]},
            } for r in rows]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
