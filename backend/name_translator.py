"""
name_translator.py — 球队名/球员名 英文→中文 翻译层
原则：翻译在 API 响应层完成，数据库英文名保持不动
"""
import json
import os

_DIR = os.path.dirname(os.path.abspath(__file__))

def _load(filename: str) -> dict:
    path = os.path.join(_DIR, filename)
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)

_TEAM_ZH: dict = {}
_PLAYER_ZH: dict = {}

def _ensure_loaded():
    global _TEAM_ZH, _PLAYER_ZH
    if not _TEAM_ZH:
        _TEAM_ZH = _load('team_zh.json')
    if not _PLAYER_ZH:
        _PLAYER_ZH = _load('player_zh.json')

def translate_team(name: str | None) -> str:
    if not name:
        return name or ''
    _ensure_loaded()
    return _TEAM_ZH.get(name, name)

def translate_player(name: str | None) -> str:
    if not name:
        return name or ''
    _ensure_loaded()
    # 精确匹配
    if name in _PLAYER_ZH:
        return _PLAYER_ZH[name]
    # 尝试去掉 # 前缀（系统用 #PlayerID 作 fallback）
    if name.startswith('#'):
        return name
    # 姓氏匹配 fallback
    for en, zh in _PLAYER_ZH.items():
        if name.lower() in en.lower() or en.lower() in name.lower():
            return zh
    return name

def translate_match_meta(meta: dict) -> dict:
    """翻译一个包含 home_team/away_team 的 dict（原地修改副本）"""
    result = dict(meta)
    for key in ('home_team', 'away_team', 'Home_Team_Name', 'Away_Team_Name'):
        if key in result:
            result[key] = translate_team(result[key])
    return result

def translate_player_stats(stats: list[dict]) -> list[dict]:
    """翻译 player_stats 列表中每个 player 的 name 字段"""
    return [{**p, 'name': translate_player(p.get('name', ''))} for p in (stats or [])]
