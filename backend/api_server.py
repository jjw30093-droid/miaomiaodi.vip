import sqlite3
from fastapi import FastAPI, HTTPException, Header, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
from pydantic import BaseModel
import logging
from typing import List
import os
import json
import difflib
from cdk_router import router as cdk_router
from report_router import router as report_router  # 仅用于 /reports/latest 等列表接口
from auth_router import router as auth_router
from sync_router import router as sync_router
from wechat_auth_router import router as wechat_auth_router
from review_router import router as review_router
from user_router import router as user_router
from model_health_router import router as model_health_router
from products_router import router as products_router
from orders_router import router as orders_router
from auth_deps import get_current_user, CurrentUser
from fastapi import Depends
from db_migrate import run_migrations
from calibration_engine import CalibrationEngine
from predict_engine import PredictEngine
from name_translator import translate_team, translate_player

# ==========================================
# 🛡️ 动态球队实体映射引擎 (Dynamic Entity Mapper)
# ==========================================
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "football_uk.db"))
PORT = 8000

MAPPING_FILE = os.path.join(os.path.dirname(DB_PATH), "team_mapping.json")
KNOWN_DB_TEAMS = []
ALIAS_MAP = {}


def init_team_mapper():
    """在 API 启动时，自动加载外挂字典，并嗅探数据库中真实的球队名单"""
    global KNOWN_DB_TEAMS, ALIAS_MAP

    # 1. 挂载外部特殊字典
    if os.path.exists(MAPPING_FILE):
        try:
            with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
                ALIAS_MAP = json.load(f)
            logging.info(f"✅ 成功加载外部球队映射字典: {len(ALIAS_MAP)} 条规则")
        except Exception as e:
            logging.error(f"❌ 加载 team_mapping.json 失败: {e}")

    # 2. 从数据库动态提取官方户口本名单
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DISTINCT Home_Team_Name FROM dim_match UNION SELECT DISTINCT Away_Team_Name FROM dim_match")
        KNOWN_DB_TEAMS = [row[0] for row in cursor.fetchall() if row[0]]
        conn.close()
        logging.info(f"✅ 成功从底层数据库加载 {len(KNOWN_DB_TEAMS)} 支官方注册球队")
    except Exception as e:
        logging.error(f"❌ 初始化数据库球队名单失败: {e}")


def normalize_team_name(fotmob_name: str) -> str:
    """4 级降级匹配机制，彻底消灭实体命名漂移"""
    clean_input = fotmob_name.strip()

    # 级别 1: 命中外挂手工字典 (最高优先级，解决纯粹的别名如 Spurs)
    if clean_input in ALIAS_MAP:
        return ALIAS_MAP[clean_input]

    # 级别 2: 数据库完全命中 (直接放行)
    if clean_input in KNOWN_DB_TEAMS:
        return clean_input

    # 级别 3: 智能子串包含 (解决 Bournemouth -> AFC Bournemouth 的问题)
    core_name = clean_input.replace(" FC", "").replace(" AFC", "").lower()
    for db_team in KNOWN_DB_TEAMS:
        if core_name == db_team.lower():
            return db_team
        if len(core_name) > 4 and core_name in db_team.lower():
            return db_team

    # 级别 4: Difflib 模糊算法兜底 (容忍拼写错误或空格差异)
    closest = difflib.get_close_matches(clean_input, KNOWN_DB_TEAMS, n=1, cutoff=0.65)
    if closest:
        return closest[0]

    return clean_input


# 触发初始化
import db_migrate as _dm
print(f"[DEBUG] api_server.__file__={__file__}")
print(f"[DEBUG] api_server.DB_PATH={DB_PATH}, exists={os.path.exists(DB_PATH)}")
print(f"[DEBUG] db_migrate.DB_PATH={_dm.DB_PATH}, exists={os.path.exists(_dm.DB_PATH)}")
init_team_mapper()
run_migrations()

# ==========================================
# ⚙️ 配置区
# ==========================================
app = FastAPI(title="足球量化调度车间 - 数据总线", version="9.0-Opta-Flawless")

# CORS 配置：从环境变量读取允许的源列表
# 生产环境（AWS）必须在 PM2 ecosystem / .env 中设置：
#   ALLOWED_ORIGINS=https://miaomiaodi.cc,https://www.miaomiaodi.cc
# 本地开发不设置时，仅允许 localhost 常用端口
_raw_origins = os.environ.get("ALLOWED_ORIGINS", "")
if _raw_origins:
    origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
else:
    origins = [
        "http://localhost:3000",   # Next.js dev
        "http://localhost:5173",   # Vite dev
        "http://localhost:8000",   # FastAPI static
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cdk_router)
app.include_router(auth_router)
app.include_router(sync_router)
app.include_router(wechat_auth_router)
app.include_router(review_router)
app.include_router(user_router)
app.include_router(model_health_router)
app.include_router(products_router, prefix="/api/v1", tags=["Products"])
app.include_router(orders_router, prefix="/api/v1", tags=["Orders"])


# ==========================================
# 🧹 后台任务：定期清理过期登录 session（避免内存泄漏）
# ==========================================
@app.on_event("startup")
async def _start_session_cleanup_loop():
    import asyncio
    from wechat_auth_router import _cleanup_sessions, _sessions

    async def _loop():
        while True:
            try:
                before = len(_sessions)
                _cleanup_sessions()
                after = len(_sessions)
                if before != after:
                    import logging
                    logging.getLogger(__name__).info(
                        f"[SessionGC] cleaned {before - after} expired codes, active={after}"
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"[SessionGC] 异常: {e}")
            await asyncio.sleep(300)  # 每 5 分钟巡检一次

    asyncio.create_task(_loop())

# 用户头像等静态资源
_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# 旧版研报接口（/api/v1/report/{id}）— 已废弃，返回 410 Gone
# 防止有客户端仍在调用时意外暴露数据
from fastapi import Path as FPath
from fastapi.responses import JSONResponse

@app.get("/api/v1/report/{match_id}", tags=["Deprecated"])
async def deprecated_report_endpoint(match_id: str = FPath(...)):
    return JSONResponse(
        status_code=410,
        content={
            "detail": "此接口已废弃。请使用 /api/v1/sync/match_payload/{match_id}",
            "match_id": match_id,
        },
    )

# report_router: /reports/latest, /reports/daily_free_id, /reports/archive 等列表接口
# 注意：/report/{match_id} 已被上方 410 stub 优先拦截，report_router 中该路由不会生效
app.include_router(report_router)

# ── 微信回调 alias（兼容微信后台配置的旧 URL）──────────────────────────────
# 微信后台配置的 URL 是 /api/v1/wechat/callback，
# 实际 handler 在 wechat_auth_router 的 /api/v1/auth/wechat/webhook
from wechat_auth_router import (
    wechat_webhook_verify as _wx_verify,
    wechat_webhook_message as _wx_message,
)
from fastapi.responses import PlainTextResponse as _PlainText
from fastapi import Query as _Q

@app.get("/api/v1/wechat/callback", response_class=_PlainText, tags=["WeChat"])
async def wechat_callback_verify(
    signature: str = _Q(...), timestamp: str = _Q(...),
    nonce: str = _Q(...), echostr: str = _Q(...),
):
    """微信服务器 URL 验证（alias → /api/v1/auth/wechat/webhook）"""
    return await _wx_verify(signature=signature, timestamp=timestamp,
                            nonce=nonce, echostr=echostr)

@app.post("/api/v1/wechat/callback", response_class=_PlainText, tags=["WeChat"])
async def wechat_callback_message(
    request: Request,
    signature: str = _Q(...), timestamp: str = _Q(...), nonce: str = _Q(...),
):
    """微信消息接收（alias → /api/v1/auth/wechat/webhook）"""
    return await _wx_message(request=request, signature=signature,
                             timestamp=timestamp, nonce=nonce)

# ── 初始化推理引擎 (单例) ──
_MODEL_VERSION = os.environ.get("MODEL_VERSION", "v4")
MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"models_{_MODEL_VERSION}")
predict_engine = PredictEngine(db_path=DB_PATH, model_dir=MODELS_DIR)
logging.info(f"[ENGINE] MODEL_VERSION={_MODEL_VERSION}, model_dir={MODELS_DIR}")

def reload_engine():
    global predict_engine, MODELS_DIR, _MODEL_VERSION
    _MODEL_VERSION = os.environ.get("MODEL_VERSION", "v4")
    MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"models_{_MODEL_VERSION}")
    predict_engine = PredictEngine(db_path=DB_PATH, model_dir=MODELS_DIR)
    logging.info(f"🚀 推理引擎已重载: MODEL_VERSION={_MODEL_VERSION}, model_dir={MODELS_DIR}")

_ADMIN_TOKEN = os.environ.get("ADMIN_SECRET_TOKEN", "")

@app.post("/api/v1/calibrate/train", tags=["Admin"])
async def train_calibrator(
    background_tasks: BackgroundTasks,
    x_admin_token: str = Header(..., alias="X-Admin-Token"),
):
    """异步触发概率校准器训练（需 X-Admin-Token）"""
    if not _ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="ADMIN_SECRET_TOKEN 未配置，Admin 接口不可用。")
    if x_admin_token != _ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="X-Admin-Token 鉴权失败。")

    def run_training():
        ce = CalibrationEngine(db_path=DB_PATH)
        success = ce.train(limit=1000)
        if success:
            reload_engine()

    background_tasks.add_task(run_training)
    return {"status": "success", "message": "已在后台启动校准器训练，完成后将自动刷新推理引擎。"}

logging.basicConfig(level=logging.INFO)

def _run_query(query: str, params: tuple = ()):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        result = cursor.fetchall()
        conn.close()
        return [dict(row) for row in result]
    except Exception as e:
        logging.error(f"SQL Error: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Football Data Lake API v2.5"}


# -------------------------------------------------------------------
# 📊 核心接口 1: 赛前量化基本面特征提取 (全容错架构 + 修复版实体映射)
# -------------------------------------------------------------------
@app.get("/api/v1/quant/{match_id}")
def get_quant_data(
    match_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),  # 2026-04-27 上线前硬隔离：未登录 → 401
):
    from rate_limit import hit as _rl, client_ip as _cip
    _rl("quant", _cip(request), 60)  # 60 req/min per IP（浏览 10 场比赛绰绰有余）
    try:
        project_root = os.path.dirname(os.path.abspath(__file__))
        schedule_file = os.path.join(project_root, "schedule", "target_matches.json")
        odds_file = os.path.join(project_root, "odds", "match_odds_data.json")

        home_name, away_name = "主队", "客队"
        found = False

        # 1. 解析赛程与盘口 JSON
        if os.path.exists(schedule_file):
            with open(schedule_file, "r", encoding="utf-8") as f:
                all_matches = json.load(f)
            match_obj = next((item for item in all_matches if
                              str(item.get("match_id")) == str(match_id) or str(item.get("fotmob_id")) == str(
                                  match_id)), None)
            if match_obj:
                match_name = match_obj.get("match_name", "")
                if " vs " in match_name:
                    home_name, away_name = match_name.split(" vs ")[0].strip(), match_name.split(" vs ")[1].strip()
                    found = True

        if not found and os.path.exists(odds_file):
            with open(odds_file, "r", encoding="utf-8") as f:
                all_odds = json.load(f)
            match_obj = next((item for item in all_odds if str(item.get("fotmob_id")) == str(match_id)), None)
            if match_obj:
                match_name = match_obj.get("match_name", "")
                if " vs " in match_name:
                    home_name, away_name = match_name.split(" vs ")[0].strip(), match_name.split(" vs ")[1].strip()

        # 2. 🚀 启用全局动态映射引擎（铲除局部硬编码函数）
        safe_home_name = normalize_team_name(home_name)
        safe_away_name = normalize_team_name(away_name)

        def get_team_id_from_db(normalized_name):
            # 先精确匹配，防同城死敌混淆
            q_exact = """
                SELECT Home_Team_ID as t_id FROM dim_match WHERE Home_Team_Name = ?
                UNION
                SELECT Away_Team_ID as t_id FROM dim_match WHERE Away_Team_Name = ?
                LIMIT 1
            """
            res = _run_query(q_exact, (normalized_name, normalized_name))
            if res: return res[0]['t_id']

            # 兜底模糊匹配
            q_like = """
                SELECT Home_Team_ID as t_id FROM dim_match WHERE Home_Team_Name LIKE ?
                UNION
                SELECT Away_Team_ID as t_id FROM dim_match WHERE Away_Team_Name LIKE ?
                LIMIT 1
            """
            res_like = _run_query(q_like, (f"%{normalized_name}%", f"%{normalized_name}%"))
            return res_like[0]['t_id'] if res_like else None

        home_id = get_team_id_from_db(safe_home_name)
        away_id = get_team_id_from_db(safe_away_name)

        print(
            f"\n📡 抽取最新战力: FotMob[{home_name} vs {away_name}] -> DB[{safe_home_name} vs {safe_away_name}] [ID: {home_id} vs {away_id}]")

        # 3. 🎯 彻底避开 Match_ID 悖论：通过 Team_ID 独立抽取最新滚动战绩
        def get_latest_form(t_id):
            if not t_id: return None
            q = """
                SELECT * FROM int_team_rolling_features 
                WHERE CAST(team_id AS TEXT) = ? 
                ORDER BY match_date DESC LIMIT 1
            """
            res = _run_query(q, (str(t_id),))
            return res[0] if res else None

        hf = get_latest_form(home_id) or {}
        af = get_latest_form(away_id) or {}

        # 4. 安全计算差值
        def safe_diff(val1, val2, precision=2):
            if val1 is not None and val2 is not None:
                return round(val1 - val2, precision)
            return "缺乏数据"

        response_data = {
            "match_info": {
                "Match_ID": match_id,
                "Home_Team_Name": translate_team(safe_home_name),
                "Away_Team_Name": translate_team(safe_away_name)
            },
            "matchup_differentials": {
                "form_npxGD_diff": safe_diff(hf.get("roll_5_npxGD"), af.get("roll_5_npxGD"), 2),
                "control_tilt_diff": safe_diff(hf.get("roll_5_field_tilt"), af.get("roll_5_field_tilt"), 2),
                "penetration_diff": safe_diff(hf.get("roll_5_golden_zone_ratio"), af.get("roll_5_golden_zone_ratio"), 4)
            },
            "home_team_form_last_5": {
                "npxGD": hf.get("roll_5_npxGD", "无数据"),
                "ppda_pressing": hf.get("roll_5_ppda", "无数据"),
                "field_tilt": hf.get("roll_5_field_tilt", "无数据"),
                "golden_zone_ratio": hf.get("roll_5_golden_zone_ratio", "无数据"),
                "goals_prevented": hf.get("roll_5_team_goals_prevented", "无数据"),
                "home_split_npxG": hf.get("roll_5_split_npxG_for", "无数据")
            },
            "away_team_form_last_5": {
                "npxGD": af.get("roll_5_npxGD", "无数据"),
                "ppda_pressing": af.get("roll_5_ppda", "无数据"),
                "field_tilt": af.get("roll_5_field_tilt", "无数据"),
                "golden_zone_ratio": af.get("roll_5_golden_zone_ratio", "无数据"),
                "goals_prevented": af.get("roll_5_team_goals_prevented", "无数据"),
                "away_split_npxG": af.get("roll_5_split_npxG_for", "无数据")
            }
        }
        return response_data
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


# -------------------------------------------------------------------
# 📈 辅助接口与首发测算 (保持不变)
# -------------------------------------------------------------------
@app.get("/api/v1/market/{match_id}")
def get_market_data(
    match_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),  # 2026-04-27 上线前硬隔离：未登录 → 401
):
    from rate_limit import hit as _rl, client_ip as _cip
    _rl("market", _cip(request), 60)
    project_root = os.path.dirname(os.path.abspath(__file__))
    odds_file_path = os.path.join(project_root, "odds", "match_odds_data.json")
    if not os.path.exists(odds_file_path): return {"status": "error", "message": "找不到盘口文件"}
    with open(odds_file_path, "r", encoding="utf-8") as f:
        all_odds = json.load(f)
    match_odds = next((item.get("odds") for item in all_odds if str(item.get("fotmob_id")) == str(match_id)), None)
    return {"status": "success", "odds": match_odds} if match_odds else {"status": "no_odds"}


class LineupEvaluationRequest(BaseModel):
    team_name: str
    player_names: List[str]


@app.post("/api/v1/lineup_eval")
def evaluate_lineup(
    request: LineupEvaluationRequest,
    http_request: Request,
    user: CurrentUser = Depends(get_current_user),  # 2026-04-29 P0 修复：登录才可访问（注册用户即可，无需 VIP）
):
    from rate_limit import hit as _rl, client_ip as _cip
    _rl("lineup_eval", _cip(http_request), 30)  # 阵容评测较重，30/min per IP
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    evaluated_players = []
    total_xg_share_missing = 0.0

    for player_name in request.player_names:
        cursor.execute("""
            SELECT 
                p.player_name, COUNT(i.match_id) as apps,
                AVG(i.xg_xa_share) as avg_xg_share, AVG(i.chances_created_share) as avg_chance_share,
                AVG(i.recoveries_share) as avg_def_share, AVG(i.goals_prevented) as avg_gk_prevented
            FROM dim_player p
            JOIN int_player_influence i ON p.player_id = i.player_id
            WHERE p.player_name LIKE ? OR p.player_name LIKE ?
            GROUP BY p.player_id ORDER BY apps DESC LIMIT 1
        """, (f"%{player_name}%", f"%{player_name.split(' ')[-1]}%"))

        row = cursor.fetchone()

        if row and row['apps'] > 0:
            xg_share = round((row['avg_xg_share'] or 0) * 100, 1)
            def_share = round((row['avg_def_share'] or 0) * 100, 1)
            if xg_share >= 25.0:
                role = f"👑 [进攻大核] 包揽全队 {xg_share}% 的 xG+xA 输出"
                total_xg_share_missing += xg_share
            elif def_share >= 15.0:
                role = f"🧱 [防守中枢] 贡献全队 {def_share}% 的夺回球权"
            elif row['avg_gk_prevented'] and row['avg_gk_prevented'] > 0:
                role = f"🧤 [主力门将] 场均额外阻止 {round(row['avg_gk_prevented'], 2)} 球"
            else:
                role = "⚙️ [体系球员] 数据份额均衡"
            evaluated_players.append({"fotmob_name": player_name, "tactical_role": role})
        else:
            evaluated_players.append({"fotmob_name": player_name, "tactical_role": "❓ [盲区/轮换/新援]"})
            
    for p in evaluated_players:
        p["fotmob_name"] = translate_player(p["fotmob_name"])
        
    conn.close()
    return {
        "team_name": translate_team(request.team_name),
        "team_impact_warning": f"⚠️ 警告: 损失 {total_xg_share_missing:.1f}% 进攻火力！" if total_xg_share_missing >= 20.0 else "🟢 影响可控",
        "players_evaluation": evaluated_players
    }


# ── 开发测试：魔法链接登录（仅限 DEV_LOGIN_SECRET 持有者）──────────────────
# ⚠️ 默认禁用（ENABLE_DEV_LOGIN!=1 时路由根本不挂载）。
# 启用流程见 backend/CLAUDE.md §22。
_DEV_LOGIN_SECRET   = os.environ.get("DEV_LOGIN_SECRET", "")
_DEV_LOGIN_UID      = int(os.environ.get("DEV_LOGIN_UID", "11"))
_DEV_LOGIN_ENABLED  = os.environ.get("ENABLE_DEV_LOGIN", "0") == "1"
_DEV_LOGIN_ALLOWED_IPS = set(
    ip.strip()
    for ip in os.environ.get("DEV_LOGIN_ALLOWED_IPS", "127.0.0.1").split(",")
    if ip.strip()
)

from fastapi.responses import HTMLResponse as _HtmlResp

if _DEV_LOGIN_ENABLED:
  @app.get("/api/v1/auth/dev-login", tags=["Dev"], response_class=_HtmlResp)
  async def dev_magic_login(request: Request, secret: str = _Q(...)):
    """魔法链接：持有 DEV_LOGIN_SECRET 的人访问此 URL 后，
    浏览器自动写入 localStorage JWT 并跳转首页，无需微信。
    防御层：
      1) 路由仅在 ENABLE_DEV_LOGIN=1 时挂载（默认不挂）
      2) 仅允许 DEV_LOGIN_ALLOWED_IPS 中的 IP 访问（默认 127.0.0.1）
      3) secret 比较走 secrets.compare_digest（timing-safe）"""
    # 1) IP 白名单（CF-Connecting-IP → X-Real-IP → X-Forwarded-For）
    from rate_limit import client_ip as _client_ip
    real_ip = _client_ip(request) or ""
    if real_ip not in _DEV_LOGIN_ALLOWED_IPS:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="dev-login 仅限指定 IP")

    # 2) Secret 校验（timing-safe）
    import secrets as _secrets
    if not _DEV_LOGIN_SECRET or not _secrets.compare_digest(secret, _DEV_LOGIN_SECRET):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="无效 secret")

    from auth_deps import make_jwt
    import sqlite3 as _sq
    conn = _sq.connect(DB_PATH); conn.row_factory = _sq.Row
    u = conn.execute("SELECT * FROM users WHERE id=?", (_DEV_LOGIN_UID,)).fetchone()
    conn.close()
    if not u:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="测试用户不存在")

    token = make_jwt(u["id"], u["role"], nickname=u["nickname"])
    # 构造 zustand persist 格式并写入 localStorage，然后跳转首页
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>登录中...</title></head>
<body style="background:#000;color:#0ff;font-family:monospace;padding:40px">
<p>正在登录，请稍候...</p>
<script>
  const payload = JSON.stringify({{
    state: {{
      token: "{token}",
      user: (function(){{
        try {{
          const b = "{token}".split('.')[1];
          return JSON.parse(atob(b.replace(/-/g,'+').replace(/_/g,'/')));
        }} catch(e) {{ return null; }}
      }})()
    }},
    version: 0
  }});
  localStorage.setItem('auth-storage', payload);
  window.location.href = '/';
</script>
</body></html>"""
    return _HtmlResp(content=html)


if __name__ == "__main__":
    print("🚀 启动数据总线服务 (9.0 终极容错版)...")
    uvicorn.run(app, host="0.0.0.0", port=PORT)