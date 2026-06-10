"""
password_utils.py — 密码 hash/验证/规则共享模块

被 auth_router.py 和 user_router.py 同时引用，避免循环导入。
"""

import re
from typing import Optional

try:
    import bcrypt as _bcrypt_lib
    _BCRYPT_AVAILABLE = True
except ImportError:
    _bcrypt_lib = None
    _BCRYPT_AVAILABLE = False

PASSWORD_MIN_LEN = 6
_PWD_HAS_LOWER = re.compile(r'[a-z]')
_PWD_HAS_UPPER = re.compile(r'[A-Z]')


def validate_password(pwd: str) -> Optional[str]:
    if not pwd or len(pwd) < PASSWORD_MIN_LEN:
        return f"密码长度不能少于 {PASSWORD_MIN_LEN} 个字符"
    if not _PWD_HAS_LOWER.search(pwd):
        return "密码必须包含小写英文字母"
    if not _PWD_HAS_UPPER.search(pwd):
        return "密码必须包含大写英文字母"
    return None


def hash_password(password: str) -> str:
    if not _BCRYPT_AVAILABLE:
        raise RuntimeError("bcrypt 未安装，请先 pip install bcrypt")
    salt = _bcrypt_lib.gensalt(rounds=10)
    return _bcrypt_lib.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    if not _BCRYPT_AVAILABLE:
        return False
    try:
        return _bcrypt_lib.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False
