"""
report_section_editor.py — 研报 Markdown 段落级替换工具

用于 final_lock.py 在 T-30 阶段用 closing 赔率重写「## 亚盘分析」「## 大小球分析」段落，
不影响其他段落（poll_lineup 改"## ⚔️ 战力评估"段落）。

设计原则：
  1. 段落 anchor 用宽容正则（覆盖 LLM 标题发散：⚖️/🎯/数字标题/简体繁体）
  2. 段落边界 = 下一个 `## ` 标题 或 `---` 分隔行 或 文末
  3. 匹配失败 → 不写回，保留旧段落（兜底，CLAUDE.md §17 防御）
  4. 调用方先写文件再 sync 到 report_store.markdown_content

CLAUDE.md §B2 上线前修复
"""
from __future__ import annotations

import logging
import os
import re

log = logging.getLogger(__name__)

# 段落结尾边界：下一个 ##（任意级别）/ --- 分隔 / 文末
_SECTION_END = r'(?=\n#{1,6}\s|\n---|\Z)'

# 亚盘标题（覆盖：## 亚盘分析 / ## ⚖️ 亚盘解读 / ## 1. 亚盘 / ## 让球分析）
_HANDICAP_TITLE = r'##\s*[^\n]*?(?:亚盘|让球|让分|亚指)[^\n]*\n'

# 大小球标题（覆盖：## 大小球分析 / ## 🎯 大小球 / ## 进球数预测）
_OU_TITLE = r'##\s*[^\n]*?(?:大小球|大小盘|进球数|总进球|大小球盘)[^\n]*\n'


def _do_section_replace(report_path: str, title_pattern: str,
                         new_body: str, canonical_title: str) -> bool:
    """通用段落替换。

    Args:
      report_path: .md 文件路径
      title_pattern: 标题正则（含 \n 结尾）
      new_body: 新段落正文（不含 ## 标题）
      canonical_title: 替换后统一使用的标题（含 ## 与换行）

    Returns:
      True = 替换成功并写盘；False = 未找到或写入失败（保留原文）
    """
    if not os.path.exists(report_path):
        log.warning(f"[section_editor] 报告文件不存在: {report_path}")
        return False

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        log.error(f"[section_editor] 读取失败 {report_path}: {e}")
        return False

    # 完整段落 = 标题 + 内容 + 边界（不消费边界）
    full_pattern = rf'({title_pattern})(.*?){_SECTION_END}'
    new_section = canonical_title + new_body.strip() + "\n"

    new_content, n = re.subn(full_pattern, new_section, content,
                             count=1, flags=re.DOTALL)

    if n == 0:
        log.warning(f"[section_editor] 未匹配到段落（pattern={title_pattern[:30]}…）"
                    f"，保留旧内容: {os.path.basename(report_path)}")
        return False

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    except Exception as e:
        log.error(f"[section_editor] 写入失败 {report_path}: {e}")
        return False


def replace_handicap_section(report_path: str, new_body: str,
                              canonical_title: str = "## 亚盘分析\n") -> bool:
    """替换「## 亚盘分析」段落。失败保留原文。"""
    return _do_section_replace(report_path, _HANDICAP_TITLE, new_body, canonical_title)


def replace_ou_section(report_path: str, new_body: str,
                        canonical_title: str = "## 大小球分析\n") -> bool:
    """替换「## 大小球分析」段落。失败保留原文。"""
    return _do_section_replace(report_path, _OU_TITLE, new_body, canonical_title)


# 别名：兼容计划文档里 _replace_handicap_section 的命名
_replace_handicap_section = replace_handicap_section
_replace_ou_section       = replace_ou_section


# ── 模块自检 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile

    sample = """# 研报标题

## 亚盘分析

旧的亚盘正文，提到 OU 3.25 球。

## 大小球分析

旧的大小球正文，市场隐含 51%。

## ⚔️ 战力评估

略

---

底部分隔后内容。
"""
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".md", encoding="utf-8") as f:
        f.write(sample)
        path = f.name

    print("== 测试 1: 替换亚盘 ==")
    ok = replace_handicap_section(path, "新的亚盘正文，OU 3.5 球。模型预测大球 78%。")
    print(f"  ok={ok}")

    print("== 测试 2: 替换大小球 ==")
    ok = replace_ou_section(path, "新的大小球正文，closing 2.25 vs opening 2.5。")
    print(f"  ok={ok}")

    print("== 替换后内容 ==")
    print(open(path).read())
    os.unlink(path)
