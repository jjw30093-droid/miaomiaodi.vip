"""
config.py — 历史 Gemini LLM 工厂（已废弃）

⚠️ 已弃用：所有 LLM 调用请走 `qwen_client.get_flash() / get_pro() / get_review()`。
保留这个文件仅为向后兼容（万一有遗漏的 import）；模块级不再 init LLM，
避免 import 时立刻触发 Google API 客户端构造（CLAUDE.md §A3 上线前修复）。
"""
from __future__ import annotations

import os
import warnings

# Avoid load_dotenv() bug in 3.13
if not os.getenv("DASHSCOPE_API_KEY"):
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                if "=" in line:
                    key, val = line.strip().split("=", 1)
                    os.environ[key] = val


def get_llm():
    """⚠️ 已废弃：请直接 `from qwen_client import get_flash`。

    保留此函数返回千问 flash（含 fallback），让任何残留 caller 不会立刻崩溃；
    但每次调用打 DeprecationWarning，方便排查并迁移。
    """
    warnings.warn(
        "config.get_llm() 已废弃，请改用 qwen_client.get_flash() / get_pro() / get_review()",
        DeprecationWarning,
        stacklevel=2,
    )
    from qwen_client import get_flash
    return get_flash()


# ⚠️ 历史代码会 `from config import llm` —— 保留惰性属性（lazy）避免 import 时立刻 init
def __getattr__(name):
    if name == "llm":
        return get_llm()
    raise AttributeError(f"module 'config' has no attribute {name!r}")
