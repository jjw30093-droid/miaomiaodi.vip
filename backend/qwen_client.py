"""
qwen_client.py — 统一千问 LLM 工厂（含 fallback 链）

设计目标：
  1. 所有调用方（run_tonight / poll_lineup / review_service / final_lock 等）
     从这里取 LLM，不要自己 ChatOpenAI(...)
  2. 每个角色都有 primary + fallback，主模型失败时自动切到备用，
     调用方拿到的对象是 Runnable，invoke() / __call__ 行为不变
  3. 模型名通过 env 可调（用户充值/换模型时不改代码）

环境变量（默认值在 get_*() 内）：
  DASHSCOPE_API_KEY               # 必须
  DASHSCOPE_BASE_URL              # 默认 https://dashscope.aliyuncs.com/compatible-mode/v1
  QWEN_FLASH_PRIMARY              # 默认 qwen-plus（暂避开已耗尽的 qwen3.6-max-preview）
  QWEN_FLASH_FALLBACK             # 默认 qwen-turbo
  QWEN_PRO_PRIMARY                # 默认 qwen-max-latest（用户标注有额度）
  QWEN_PRO_FALLBACK               # 默认 qwen-plus
  QWEN_REVIEW_PRIMARY             # 默认 qwen-plus
  QWEN_REVIEW_FALLBACK            # 默认 qwen-turbo
  QWEN_ENABLE_SEARCH              # 默认 "0"（关联网搜索，省账单）；"1" 开启
"""
from __future__ import annotations

import os
from langchain_openai import ChatOpenAI

# ── 自动加载 .env（与 run_tonight_reports.py 一致）────────────────────────
_PROJECT_ROOT = os.environ.get("PROJECT_ROOT", os.path.dirname(os.path.abspath(__file__)))
_ENV_PATH = os.path.join(_PROJECT_ROOT, ".env")
if not os.environ.get("DASHSCOPE_API_KEY") and os.path.exists(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ── 全局常量 ──────────────────────────────────────────────────────────────
DASHSCOPE_BASE = os.environ.get(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
_KEY = os.environ.get("DASHSCOPE_API_KEY", "")

# enable_thinking=False：关思维链推理 token 计费
# enable_search 默认 False：联网搜索按次计费，pipeline 自带 FotMob 结构化数据无需 LLM 上网
_ENABLE_SEARCH = os.environ.get("QWEN_ENABLE_SEARCH", "0") == "1"
_EXTRA = {"enable_thinking": False, "enable_search": _ENABLE_SEARCH}


def _make(model: str, temperature: float, timeout: int = 180) -> ChatOpenAI:
    """构造单个 ChatOpenAI 实例（指向 DashScope 兼容模式）"""
    return ChatOpenAI(
        model=model,
        openai_api_key=_KEY,
        openai_api_base=DASHSCOPE_BASE,
        temperature=temperature,
        timeout=timeout,
        model_kwargs={"extra_body": _EXTRA},
    )


def get_flash():
    """快/便宜：用于 agent1/2/3、poll_lineup 战力评估等高频短任务

    返回带 fallback 的 Runnable：primary 抛异常（quota/rate limit/超时/5xx）
    时自动切换 fallback，调用方 invoke() 行为不变。
    """
    primary = _make(
        os.environ.get("QWEN_FLASH_PRIMARY", "deepseek-v4-flash"),
        temperature=0.2,
        timeout=180,
    )
    fallback = _make(
        os.environ.get("QWEN_FLASH_FALLBACK", "deepseek-v4-flash"),
        temperature=0.2,
        timeout=180,
    )
    return primary.with_fallbacks([fallback])


def get_pro():
    """高质量：用于 agent4 整合、长 prompt"""
    primary = _make(
        os.environ.get("QWEN_PRO_PRIMARY", "deepseek-v4-pro"),
        temperature=0.5,
        timeout=300,
    )
    fallback = _make(
        os.environ.get("QWEN_PRO_FALLBACK", "deepseek-v4-pro"),
        temperature=0.5,
        timeout=300,
    )
    return primary.with_fallbacks([fallback])


def get_review():
    """赛后复盘：与 review_service / run_post_match_reviews 用"""
    primary = _make(
        os.environ.get("QWEN_REVIEW_PRIMARY", "deepseek-v4-flash"),
        temperature=0.3,
        timeout=240,
    )
    fallback = _make(
        os.environ.get("QWEN_REVIEW_FALLBACK", "deepseek-v4-flash"),
        temperature=0.3,
        timeout=240,
    )
    return primary.with_fallbacks([fallback])


# ── 模块自检（python3 qwen_client.py 直接跑） ────────────────────────────
if __name__ == "__main__":
    print(f"DASHSCOPE_BASE = {DASHSCOPE_BASE}")
    print(f"DASHSCOPE_API_KEY  set? {'yes' if _KEY else 'NO (will fail at call time)'}")
    print(f"enable_search = {_ENABLE_SEARCH}")
    print()
    for name, fn in [("flash", get_flash), ("pro", get_pro), ("review", get_review)]:
        try:
            llm = fn()
            print(f"  [{name}] OK -> {type(llm).__name__}")
        except Exception as e:
            print(f"  [{name}] FAIL: {e}")
