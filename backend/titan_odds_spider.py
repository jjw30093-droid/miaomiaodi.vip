import os
import sys
import json
import time
import random
import requests
from datetime import datetime, timedelta

# 失败日志 helper（写 ingest_failure_log；永不抛异常）
from scripts.ingest_failure_helper import record_failure

# Phase 2 Pillar A: 统一球队名解析
PROJECT_ROOT_SPIDER = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT_SPIDER)
try:
    from team_resolver import resolve_nowgoal_match
    _RESOLVER_AVAILABLE = True
except ImportError:
    _RESOLVER_AVAILABLE = False


class Colors:
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    RESET = '\033[0m'


# ==========================================
# ⚙️ 核心配置区
# ==========================================
# 精准锁定项目根目录
PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))

# 动态创建 odds 文件夹 (存放输出的赔率)
ODDS_DIR = os.path.join(PROJECT_ROOT, "odds")
os.makedirs(ODDS_DIR, exist_ok=True)

# 输入与输出路径
SCHEDULE_FILE    = os.path.join(PROJECT_ROOT, "schedule", "target_matches.json")
ODDS_OUTPUT_PATH = os.path.join(ODDS_DIR, "match_odds_data.json")

# 优先选取的博彩公司 CID (3=Crown皇冠亚洲标杆, 8=Bet365欧洲标杆, 31=Sbobet)
TARGET_CIDS = [8, 31]

# 🚨 管理员后门：填入 FotMob Match ID，强制单独重爬这些比赛的赔率
FORCE_RETRY_IDS = []

HEADERS = {
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9",
    "referer": "https://www.nowgoal26.com/football/fixture",
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
}


def get_titan_id_via_nowgoal(date_str, home_team_en, away_team_en):
    """
    跨库映射：完美脱壳 JSON 字典结构 + 3日雷达防漏 + 模糊匹配
    """
    # 🚨 核心修复 1：弹性日期解析引擎 (兼容 YYYY-MM-DD 和 YYYYMMDD)
    try:
        if "-" in date_str:
            target_date = datetime.strptime(date_str, "%Y-%m-%d")
        else:
            target_date = datetime.strptime(date_str, "%Y%m%d")
    except Exception as e:
        print(f"      {Colors.RED}[系统] 日期解析失败 '{date_str}': {e}{Colors.RESET}")
        record_failure("titan_odds_spider", match_id=None, step="parse", error_msg=f"date {date_str}: {e}")
        return None, False

    dates_to_check = [
        target_date,
        target_date - timedelta(days=1),
        target_date + timedelta(days=1)
    ]

    best_match_id = None
    highest_score = 0.0

    def _calc_overlap(team_name, target_text):
        """旧版 calculate_overlap（保留为 legacy fallback）"""
        words = [w.lower() for w in team_name.split() if
                 len(w) > 2 and w.lower() not in ['fc', 'afc', 'united', 'city']]
        if not words: return 0
        hits = sum(1 for w in words if w in target_text)
        return hits / len(words)

    def _match_score(home_team_en, away_team_en, titan_home, titan_away):
        """
        Phase 2: 优先用 team_resolver.resolve_nowgoal_match；
        失败时降级到旧版 _calc_overlap（保证向后兼容）。
        返回 (score, is_swapped)
        """
        if _RESOLVER_AVAILABLE:
            try:
                return resolve_nowgoal_match(home_team_en, away_team_en, titan_home, titan_away)
            except Exception:
                pass
        # Legacy fallback
        h_score  = _calc_overlap(home_team_en, titan_home)
        a_score  = _calc_overlap(away_team_en, titan_away)
        avg_normal = (h_score + a_score) / 2
        h_score_swap = _calc_overlap(home_team_en, titan_away)
        a_score_swap = _calc_overlap(away_team_en, titan_home)
        avg_swap = (h_score_swap + a_score_swap) / 2
        if avg_normal >= avg_swap:
            return avg_normal, False
        return avg_swap, True

    for d in dates_to_check:
        formatted_date = d.strftime("%Y-%m-%d")
        flesh_val = random.random()
        url = f"https://www.nowgoal26.com/ajax/SoccerAjax?type=6&date={formatted_date}&order=time&timezone=8&flesh={flesh_val}"

        print(f"      {Colors.YELLOW}[雷达] 正在扫描 {formatted_date} 的底层赛程数据库...{Colors.RESET}")

        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue

            # 精准剥离 JSON 字典中的 Data 字段
            try:
                json_obj = resp.json()
                if isinstance(json_obj, dict) and "Data" in json_obj:
                    raw_data = json_obj["Data"]
                elif isinstance(json_obj, str):
                    raw_data = json_obj
                else:
                    raw_data = resp.text
            except Exception:
                raw_data = resp.text

            # 统一格式化换行符
            raw_data = raw_data.replace('\r\n', '\n').replace('\r', '\n')

            # WAF 预警
            if "Just a moment" in raw_data or "cloudflare" in raw_data.lower():
                print(f"      {Colors.RED}[雷达] 💥 触发了 Cloudflare 防火墙拦截！{Colors.RESET}")
                continue

            a_count = 0
            best_is_swapped = False
            for line in raw_data.split('\n'):
                line = line.strip()
                if line.startswith('A['):
                    a_count += 1
                    try:
                        content = line.split('=')[1].strip()
                        parts = content.split("'")

                        if len(parts) >= 5:
                            titan_id = parts[0].strip('[').split(',')[0]
                            titan_home = parts[1].lower()
                            titan_away = parts[3].lower()

                            # Phase 2: 统一走 _match_score（优先 team_resolver，降级 legacy）
                            avg, is_swap = _match_score(home_team_en, away_team_en, titan_home, titan_away)

                            if avg > highest_score and avg >= 0.5:
                                highest_score = avg
                                best_match_id = titan_id
                                best_is_swapped = is_swap
                    except Exception:
                        continue

            # 找到完美匹配(1.0)时可提前退出，否则继续扫描其他日期取最优
            if highest_score >= 1.0:
                break

        except Exception as e:
            print(f"      {Colors.RED}[雷达] 请求异常: {e}{Colors.RESET}")
            record_failure("titan_odds_spider", match_id=locals().get('mid') or locals().get('match_id'), step="parse", error_msg=str(e))
            continue

    if best_match_id:
        swap_tag = f" [⚠️ 主客互换，赔率将自动反转]" if best_is_swapped else ""
        print(f"      {Colors.GREEN}[雷达] ✅ 锁定成功！NowGoal ID: {best_match_id} (score={highest_score:.2f}){swap_tag}{Colors.RESET}")
    return best_match_id, best_is_swapped


def fetch_and_parse_json_odds(titan_id, max_retries=3):
    """请求 NowGoal 底层 JSON 赔率 API (增加反制防火墙的弹性重试机制)"""

    for attempt in range(max_retries):
        flesh_val = random.random()
        url = f"https://www.nowgoal26.com/ajax/soccerajax?type=14&t=1&id={titan_id}&h=0&s=0&flesh={flesh_val}"

        try:
            # 🚨 核心修复 2：将超时时间提升到 15 秒，给海外服务器留足余量
            resp = requests.get(url, headers=HEADERS, timeout=15)

            if resp.status_code != 200:
                print(
                    f"      {Colors.YELLOW}[警告] 状态码 {resp.status_code}，准备重试 ({attempt + 1}/{max_retries})...{Colors.RESET}")
                time.sleep(random.uniform(2.0, 4.0))
                continue

            # 防御 WAF 误杀
            if "Just a moment" in resp.text or "cloudflare" in resp.text.lower():
                print(
                    f"      {Colors.YELLOW}[警告] 触发防火墙盾牌，正在冷却重试 ({attempt + 1}/{max_retries})...{Colors.RESET}")
                time.sleep(random.uniform(3.0, 6.0))
                continue

            data = resp.json()
            mixodds = data.get("Data", {}).get("mixodds", [])
            if not mixodds:
                return None

            def format_market(m_data, is_euro=False):
                if not m_data: return None
                f = m_data.get('f', {})
                l = m_data.get('l', {})
                # 🚨 修复：检查值是否真实非空（防止 {'u': '', 'g': '', 'd': ''} 被接受）
                if not f or not l: return None
                if not any(str(v).strip() for v in f.values()): return None

                if is_euro:
                    return {
                        "initial": {"home": f.get('u'), "draw": f.get('g'), "away": f.get('d')},
                        "latest": {"home": l.get('u'), "draw": l.get('g'), "away": l.get('d')}
                    }
                else:
                    return {
                        "initial": {"over_or_home": f.get('u'), "line": f.get('g'), "under_or_away": f.get('d')},
                        "latest": {"over_or_home": l.get('u'), "line": l.get('g'), "under_or_away": l.get('d')}
                    }

            def bookie_has_valid_odds(b):
                """检查某家博彩公司是否有真实赔率数据（至少一个市场非空）"""
                for key in ['euro', 'ah', 'ou']:
                    mkt = b.get(key) or {}
                    f = mkt.get('f') or {}
                    if any(str(v).strip() for v in f.values()):
                        return True
                return False

            # 按优先顺序找有效数据的博彩公司
            target_bookie = None
            for cid in TARGET_CIDS:
                candidate = next((b for b in mixodds if b.get("cid") == cid), None)
                if candidate and bookie_has_valid_odds(candidate):
                    target_bookie = candidate
                    break

            # 首选 CID 无数据 → 遍历所有公司找第一家有数据的
            if not target_bookie:
                target_bookie = next((b for b in mixodds if bookie_has_valid_odds(b)), None)

            # 全部无数据 → 所有公司赔率均已清除，放弃
            if not target_bookie:
                print(f"      {Colors.YELLOW}[数据] mixodds 中 {len(mixodds)} 家公司赔率均为空，数据源已清除{Colors.RESET}")
                return None

            return {
                "provider": target_bookie.get("cn"),
                "asian_handicap": format_market(target_bookie.get("ah")),
                "over_under": format_market(target_bookie.get("ou")),
                "european_1x2": format_market(target_bookie.get("euro"), is_euro=True)
            }

        except requests.exceptions.ReadTimeout:
            print(
                f"      {Colors.YELLOW}[网络拥堵] 遭遇 Read timed out，正在重新请求 ({attempt + 1}/{max_retries})...{Colors.RESET}")
            time.sleep(random.uniform(2.0, 4.0))
        except Exception as e:
            print(f"      {Colors.RED}[异常] JSON 赔率请求失败: {e}{Colors.RESET}")
            record_failure("titan_odds_spider", match_id=locals().get('mid') or locals().get('match_id'), step="fetch", error_msg=str(e))
            time.sleep(random.uniform(1.0, 2.0))

    # 如果重试 3 次依然失败，返回 None 放弃该场比赛
    return None


def main():
    print("=" * 60)
    print(f"{Colors.BLUE}🕸️ NowGoal 纯净 JSON 赔率雷达 (动态赛程接力版){Colors.RESET}")
    print("=" * 60)

    # 1. 从调度中心读取今日目标赛事
    if not os.path.exists(SCHEDULE_FILE):
        print(f"{Colors.RED}❌ 找不到赛程文件 {SCHEDULE_FILE}！请先运行 fotmob_scheduler.py{Colors.RESET}")
        return

    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            target_matches = json.load(f)
    except Exception as e:
        print(f"{Colors.RED}❌ 解析赛程 JSON 失败: {e}{Colors.RESET}")
        record_failure("titan_odds_spider", match_id=None, step="parse", error_msg=str(e))
        return

    if not target_matches:
        print(f"{Colors.YELLOW}⚠️ 今日目标联赛无焦点赛事，雷达进入休眠。{Colors.RESET}")
        record_failure("titan_odds_spider", match_id=None,
                       step="empty_target_matches",
                       error_msg=f"target_matches.json 为空（{SCHEDULE_FILE}）")
        return

    print(f"📡 接收到 {len(target_matches)} 场赛事指令，开始全网扫描盘口...\n")

    all_odds_results = []
    skipped_started = 0          # 已开赛跳过的场次（不应计入失败）

    now = datetime.now()

    # 2. 遍历赛程，动态查ID并抓取赔率
    for match in target_matches:
        kickoff_time = match.get("kickoff_time", "")
        if kickoff_time:
            kickoff_dt = datetime.strptime(kickoff_time, '%Y-%m-%d %H:%M:%S')
            if kickoff_dt <= now:
                print(f"{Colors.YELLOW}⏭️  跳过已开球/已结束: {match.get('match_name')} [{kickoff_time}]{Colors.RESET}")
                skipped_started += 1
                continue

        fotmob_id = match["match_id"]
        # 安全切分队名（防御性编程）
        try:
            home_team = match["match_name"].split(" vs ")[0]
            away_team = match["match_name"].split(" vs ")[1]
        except:
            home_team, away_team = match["match_name"], match["match_name"]

        league = match.get("league", "未知联赛")
        match_date = match.get("date", datetime.now().strftime("%Y-%m-%d"))

        print(f"{Colors.BLUE}🎯 [{league}] 正在处理: {home_team} vs {away_team} (ID:{fotmob_id}){Colors.RESET}")

        # 呼叫模糊匹配映射器
        titan_id, is_swapped = get_titan_id_via_nowgoal(match_date, home_team, away_team)

        if not titan_id:
            print(f"{Colors.RED}❌ 映射失败！NowGoal 数据库中未能找到该比赛。{Colors.RESET}\n")
            record_failure("titan_odds_spider", match_id=str(fotmob_id),
                           step="titan_id_lookup",
                           error_msg=f"NowGoal 未匹配到 {home_team} vs {away_team} ({match_date})")
            continue

        print(f"{Colors.GREEN} -> 🎯 正在请求 JSON 总线获取最新水位...{Colors.RESET}")

        # 获取赔率
        odds_data = fetch_and_parse_json_odds(titan_id)

        # ★ 主客颠倒修正：NowGoal的主队≠FotMob的主队时，反转赔率
        if odds_data and is_swapped:
            eu = odds_data.get("european_1x2")
            if eu:
                for period in ["initial", "latest"]:
                    if eu.get(period):
                        h, a = eu[period].get("home"), eu[period].get("away")
                        eu[period]["home"], eu[period]["away"] = a, h
            ah = odds_data.get("asian_handicap")
            if ah:
                for period in ["initial", "latest"]:
                    if ah.get(period):
                        h, a = ah[period].get("over_or_home"), ah[period].get("under_or_away")
                        ah[period]["over_or_home"], ah[period]["under_or_away"] = a, h
                        # 让球方向也要反转
                        line = ah[period].get("line")
                        if line is not None:
                            try:
                                ah[period]["line"] = str(-float(line))
                            except (ValueError, TypeError):
                                pass
            print(f"      {Colors.YELLOW}[修正] 已反转主客赔率（NowGoal主客顺序与FotMob不同）{Colors.RESET}")

        if odds_data:
            print(f"{Colors.GREEN}✅ 提取成功! 采用机构: {odds_data['provider']}{Colors.RESET}\n")
            all_odds_results.append({
                "fotmob_id": fotmob_id,
                "titan_id": titan_id,
                "match_name": match["match_name"],
                "odds": odds_data
            })
        else:
            print(f"{Colors.YELLOW}⚠️ 比赛尚未开盘或获取失败。{Colors.RESET}\n")
            record_failure("titan_odds_spider", match_id=str(fotmob_id),
                           step="empty_odds_response",
                           error_msg=f"fetch_and_parse_json_odds 返回 None (titan_id={titan_id}, {home_team} vs {away_team})")

        # 爬虫礼仪：暂停1-2秒，防止IP被封
        time.sleep(random.uniform(1.0, 2.0))

    # 3. 🚨 管理员后门：强制重爬指定比赛
    if FORCE_RETRY_IDS:
        print(f"\n{Colors.YELLOW}👑 [管理员后门] 启动！强制重爬 {len(FORCE_RETRY_IDS)} 场指定比赛...{Colors.RESET}")
        for retry_id in FORCE_RETRY_IDS:
            retry_match = next((m for m in target_matches if str(m["match_id"]) == str(retry_id)), None)
            if not retry_match:
                print(f"{Colors.RED}❌ 在赛程中找不到 ID={retry_id}，请检查 target_matches.json{Colors.RESET}")
                continue

            home_team = retry_match["match_name"].split(" vs ")[0]
            away_team = retry_match["match_name"].split(" vs ")[1]
            league = retry_match.get("league", "未知联赛")
            match_date = retry_match.get("date", datetime.now().strftime("%Y-%m-%d"))

            print(f"\n{Colors.BLUE}👑 [强制重爬] [{league}] {home_team} vs {away_team} (ID:{retry_id}){Colors.RESET}")

            titan_id, is_swapped = get_titan_id_via_nowgoal(match_date, home_team, away_team)
            if not titan_id:
                print(f"{Colors.RED}❌ 映射仍然失败，跳过。{Colors.RESET}")
                continue

            print(f"{Colors.GREEN} -> 🎯 正在请求 JSON 总线获取最新水位...{Colors.RESET}")
            odds_data = fetch_and_parse_json_odds(titan_id, max_retries=5)

            # 主客颠倒修正
            if odds_data and is_swapped:
                eu = odds_data.get("european_1x2")
                if eu:
                    for period in ["initial", "latest"]:
                        if eu.get(period):
                            h, a = eu[period].get("home"), eu[period].get("away")
                            eu[period]["home"], eu[period]["away"] = a, h
                ah = odds_data.get("asian_handicap")
                if ah:
                    for period in ["initial", "latest"]:
                        if ah.get(period):
                            h, a = ah[period].get("over_or_home"), ah[period].get("under_or_away")
                            ah[period]["over_or_home"], ah[period]["under_or_away"] = a, h
                            line = ah[period].get("line")
                            if line is not None:
                                try: ah[period]["line"] = str(-float(line))
                                except: pass
                print(f"      {Colors.YELLOW}[修正] 已反转主客赔率{Colors.RESET}")

            if odds_data:
                print(f"{Colors.GREEN}✅ 强制重爬成功! 采用机构: {odds_data['provider']}{Colors.RESET}")
                # 去重：如果之前已有该场数据则替换，没有则追加
                all_odds_results = [r for r in all_odds_results if str(r["fotmob_id"]) != str(retry_id)]
                all_odds_results.append({
                    "fotmob_id": retry_id,
                    "titan_id": titan_id,
                    "match_name": retry_match["match_name"],
                    "odds": odds_data
                })
            else:
                print(f"{Colors.YELLOW}⚠️ 强制重爬仍未获取到赔率。{Colors.RESET}")

            time.sleep(random.uniform(1.0, 2.0))

    # 4. 结果落库：与已有文件合并（不覆盖其他比赛的数据）
    existing_odds = []
    if os.path.exists(ODDS_OUTPUT_PATH):
        try:
            with open(ODDS_OUTPUT_PATH, "r", encoding="utf-8") as f:
                existing_odds = json.load(f)
        except Exception:
            existing_odds = []

    # 用新数据覆盖同 ID 的旧数据，保留其余
    new_ids = {str(r["fotmob_id"]) for r in all_odds_results}
    merged = [
        r for r in existing_odds
        if "fotmob_id" in r and str(r["fotmob_id"]) not in new_ids
    ] + all_odds_results

    if merged:
        with open(ODDS_OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=4)
        print("=" * 60)
        print(f"🏁 盘口数据接力完成！共入库 {len(merged)} 场比赛盘口。")
        print(f"📁 文件路径: {ODDS_OUTPUT_PATH}")
        print("=" * 60)

        # Phase 2.5: 追加 odds_snapshot_log（非致命）
        try:
            import sqlite3 as _sqlite3
            from silver_builder import _append_snapshot_log
            _db = os.path.join(PROJECT_ROOT, "football_uk.db")
            _db = os.environ.get("DB_PATH", _db)
            _sconn = _sqlite3.connect(_db)
            _sconn.row_factory = _sqlite3.Row
            _scount = _append_snapshot_log(_sconn)
            _sconn.close()
            print(f"📸 odds_snapshot_log: {_scount} 条快照写入")
        except Exception as _se:
            print(f"⚠️  snapshot append 失败（非致命）: {_se}")
    else:
        print(f"{Colors.YELLOW}⚠️ 所有比赛均未获取到赔率数据。{Colors.RESET}")


def fetch_single_match_odds(fotmob_id, match_date: str, home_en: str, away_en: str) -> dict | None:
    """
    单场赔率抓取（closing_odds_watcher 专用）。
    返回赔率 dict（同 main() 中 odds_data 结构）或 None。
    """
    print(f"{Colors.BLUE}[单场抓取] {home_en} vs {away_en} (fotmob_id={fotmob_id}){Colors.RESET}")
    titan_id, is_swapped = get_titan_id_via_nowgoal(match_date, home_en, away_en)
    if not titan_id:
        print(f"{Colors.YELLOW}[单场抓取] NowGoal 未找到该比赛，放弃。{Colors.RESET}")
        return None

    odds_data = fetch_and_parse_json_odds(titan_id)
    if not odds_data:
        return None

    # 主客颠倒修正
    if is_swapped:
        eu = odds_data.get("european_1x2")
        if eu:
            for period in ["initial", "latest"]:
                if eu.get(period):
                    h, a = eu[period].get("home"), eu[period].get("away")
                    eu[period]["home"], eu[period]["away"] = a, h
        ah = odds_data.get("asian_handicap")
        if ah:
            for period in ["initial", "latest"]:
                if ah.get(period):
                    h, a = ah[period].get("over_or_home"), ah[period].get("under_or_away")
                    ah[period]["over_or_home"], ah[period]["under_or_away"] = a, h
                    line = ah[period].get("line")
                    if line is not None:
                        try:
                            ah[period]["line"] = str(-float(line))
                        except (ValueError, TypeError):
                            pass

    return odds_data


if __name__ == "__main__":
    main()