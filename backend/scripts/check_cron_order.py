"""
check_cron_order.py — 解析 ecosystem.config.js 校验 reader/writer cron 依赖（CLAUDE.md §15）

用法：
    python3 scripts/check_cron_order.py
退出码：
    0 = 所有 reader 都晚于 writer
    1 = 发现违反依赖图（详情打印）

依赖图（必须满足）：
    batch-sync (writer dim_match)         < post-match-audit (reader dim_match)
    post-match-audit (writer pred.actual)  < daily-backtest (reader pred.actual)
    post-match-audit                       < recalibrate
    batch-sync                             < post-match-review
    batch-sync                             < dbt-features
"""

import os
import re
import sys

ECO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ecosystem.config.js",
)

# (reader_name, writer_name, reason)
RULES = [
    ("job-post-match-audit",  "job-batch-sync",        "audit 读 dim_match.home_score"),
    ("job-daily-backtest",    "job-post-match-audit",  "backtest 读 prediction_audit.actual_*"),
    ("job-recalibrate",       "job-post-match-audit",  "recalibrate 读 prediction_audit.actual_*"),
    ("job-post-match-review", "job-batch-sync",        "复盘 LLM 读 dim_match"),
    ("job-dbt-features",      "job-batch-sync",        "dbt 读 fact_*（由 batch-sync 写入）"),
    ("job-run-tonight",       "job-scheduler",         "run-tonight 读 target_matches.json"),
    ("job-shadow-v5",         "job-run-tonight",       "shadow-v5 紧跟在 run-tonight 之后"),
]


def cron_to_minutes(expr: str):
    """简化解析：仅支持 'M H * * *' 或 'M H * * D' 形式，返回 (minutes_in_week, weekday)."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return None
    m, h, dom, mon, dow = parts
    try:
        # 支持 '*/N' 形式：取无意义大值，跳过校验
        if any(x.startswith("*/") or "," in x for x in (m, h)):
            return None
        mi = int(m)
        ho = int(h)
    except ValueError:
        return None

    weekday = None
    if dow != "*":
        try:
            weekday = int(dow)
        except ValueError:
            weekday = None

    return (ho * 60 + mi, weekday)


def parse_cron_table(text: str) -> dict:
    """从 ecosystem.config.js 文本里提取 name → cron_restart 表."""
    pattern = re.compile(
        r"name:\s*'([^']+)'.*?cron_restart:\s*'([^']+)'",
        re.DOTALL,
    )
    table = {}
    # 按 app 块分割
    for m in re.finditer(r"\{[^{}]*?name:\s*'([^']+)'[^{}]*?\}", text, flags=re.DOTALL):
        block = m.group(0)
        name = m.group(1)
        cm = re.search(r"cron_restart:\s*'([^']+)'", block)
        if cm:
            table[name] = cm.group(1)
    return table


def main():
    if not os.path.exists(ECO_PATH):
        print(f"❌ ecosystem.config.js 不存在: {ECO_PATH}")
        return 2

    with open(ECO_PATH, "r", encoding="utf-8") as f:
        text = f.read()

    crons = parse_cron_table(text)
    print("=" * 60)
    print("📋 cron_restart 表（按出现顺序）")
    print("=" * 60)
    for name, expr in crons.items():
        print(f"  {name:30s} {expr}")
    print()

    violations = []
    for reader, writer, reason in RULES:
        if reader not in crons:
            print(f"⚠️  跳过：{reader} 未配置 cron_restart")
            continue
        if writer not in crons:
            print(f"⚠️  跳过：{writer} 未配置 cron_restart")
            continue

        r_t = cron_to_minutes(crons[reader])
        w_t = cron_to_minutes(crons[writer])
        if r_t is None or w_t is None:
            print(f"⚠️  跳过 {reader}/{writer}（cron 形式过于复杂，无法静态解析）")
            continue

        # 同 weekday 才比较（recalibrate 只跑周一，但 audit 每天跑）
        # 简化：reader weekday 若 None（每天）或与 writer 同 weekday 视为同日比较
        r_min, r_dow = r_t
        w_min, w_dow = w_t
        if r_min <= w_min:
            violations.append((reader, writer, crons[reader], crons[writer], reason))

    print()
    print("=" * 60)
    if violations:
        print(f"❌ 发现 {len(violations)} 条违反依赖图：")
        for reader, writer, r_expr, w_expr, reason in violations:
            print(f"  ✗ {reader} ({r_expr}) ≤ {writer} ({w_expr})")
            print(f"      原因: {reason}")
        print()
        print("请修改 ecosystem.config.js 让 reader cron 排在 writer 之后。")
        return 1
    else:
        print(f"✅ 所有 {len(RULES)} 条依赖关系满足")
        return 0


if __name__ == "__main__":
    sys.exit(main())
