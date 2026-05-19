#!/usr/bin/env python3
"""
diagnose_v5_drift.py — v5 模型退化根因诊断脚本
# Cron: 手动触发

用法：
  cd /home/ubuntu/app/backend
  venv/bin/python scripts/diagnose_v5_drift.py

输出：backend/docs/v5_drift_diagnostic_YYYYMMDD.md
"""

import os
import sys
import sqlite3
import json
from datetime import datetime, timezone

# ── 路径设置 ──────────────────────────────────────────────────────────────────
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BACKEND_DIR, "football_uk.db")
DOCS_DIR = os.path.join(BACKEND_DIR, "docs")
TODAY = datetime.now(timezone.utc).strftime("%Y%m%d")
REPORT_PATH = os.path.join(DOCS_DIR, f"v5_drift_diagnostic_{TODAY}.md")

os.makedirs(DOCS_DIR, exist_ok=True)


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def q(conn, sql, params=()):
    """执行 SQL 返回 Row 列表。"""
    return conn.execute(sql, params).fetchall()


def fmt_pct(v):
    if v is None:
        return "N/A"
    return f"{v:.1f}%"


def fmt_f(v, d=4):
    if v is None:
        return "N/A"
    return f"{v:.{d}f}"


# ── Section A：v4 vs v5 多窗口对比 ────────────────────────────────────────────
def section_a(conn):
    lines = ["## A. v4 vs v5 多时间窗口对比\n"]
    sql = """
SELECT
  CASE WHEN model_version_active='v4' THEN 'v4' ELSE 'v5' END AS mv,
  COUNT(*) AS n,
  ROUND(100.0*SUM(wdl_correct)/NULLIF(COUNT(*),0), 2) AS wdl_acc,
  ROUND(100.0*SUM(ou_correct)/NULLIF(COUNT(CASE WHEN ou_correct IS NOT NULL THEN 1 END),0), 2) AS ou_acc,
  ROUND(AVG(brier_wdl), 4) AS brier
FROM prediction_audit
WHERE match_date >= date('now', ?)
  AND actual_wdl IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC
"""
    for label, offset in [("近 30 天", "-30 days"), ("近 14 天", "-14 days"), ("近 7 天", "-7 days")]:
        rows = q(conn, sql, (offset,))
        lines.append(f"### {label}\n")
        lines.append("| 版本 | 样本数 | WDL准确率 | OU准确率 | Brier WDL |")
        lines.append("|------|--------|-----------|----------|-----------|")
        for r in rows:
            lines.append(f"| {r['mv']} | {r['n']} | {fmt_pct(r['wdl_acc'])} | {fmt_pct(r['ou_acc'])} | {fmt_f(r['brier'])} |")
        if not rows:
            lines.append("| — | 无数据 | — | — | — |")
        lines.append("")
    return "\n".join(lines)


# ── Section B：按联赛拆分 ──────────────────────────────────────────────────────
def section_b(conn):
    lines = ["## B. 近 14 天按联赛拆分（n≥5）\n"]
    sql = """
SELECT
  CASE WHEN pa.model_version_active='v4' THEN 'v4' ELSE 'v5' END AS mv,
  dm.League_ID AS league_id,
  COUNT(*) AS n,
  ROUND(100.0*SUM(pa.wdl_correct)/NULLIF(COUNT(*),0), 2) AS wdl_acc
FROM prediction_audit pa
JOIN dim_match dm ON CAST(dm.Match_ID AS TEXT) = CAST(pa.match_id AS TEXT)
WHERE pa.match_date >= date('now', '-14 days')
  AND pa.actual_wdl IS NOT NULL
GROUP BY 1, 2
HAVING COUNT(*) >= 5
ORDER BY 2, 1 DESC
"""
    rows = q(conn, sql)
    lines.append("| 版本 | 联赛ID | 样本数 | WDL准确率 |")
    lines.append("|------|--------|--------|-----------|")
    for r in rows:
        lines.append(f"| {r['mv']} | {r['league_id']} | {r['n']} | {fmt_pct(r['wdl_acc'])} |")
    if not rows:
        lines.append("| — | 无满足条件数据 | — | — |")
    lines.append("")

    # 找 v5 崩盘联赛（<40%）
    bad = [r for r in rows if r['mv'] == 'v5' and r['wdl_acc'] is not None and r['wdl_acc'] < 40]
    if bad:
        lines.append(f"⚠️ **v5 WDL<40% 的联赛**：{', '.join(str(r['league_id']) for r in bad)}\n")
    else:
        lines.append("✅ 无 v5 WDL<40% 的联赛（样本≥5）\n")
    return "\n".join(lines)


# ── Section C：按置信度桶拆分 ──────────────────────────────────────────────────
def section_c(conn):
    lines = ["## C. 近 14 天按置信度桶（confidence_wdl）\n"]
    sql = """
SELECT
  CASE WHEN model_version_active='v4' THEN 'v4' ELSE 'v5' END AS mv,
  COALESCE(confidence_wdl, 'UNKNOWN') AS bucket,
  COUNT(*) AS n,
  ROUND(100.0*SUM(wdl_correct)/NULLIF(COUNT(*),0), 2) AS wdl_acc
FROM prediction_audit
WHERE match_date >= date('now', '-14 days')
  AND actual_wdl IS NOT NULL
GROUP BY 1, 2
ORDER BY 1 DESC, 2
"""
    rows = q(conn, sql)
    lines.append("| 版本 | 置信度桶 | 样本数 | WDL准确率 |")
    lines.append("|------|----------|--------|-----------|")
    for r in rows:
        flag = " ⚠️" if r['wdl_acc'] is not None and r['mv'] == 'v5' and r['wdl_acc'] < 40 else ""
        lines.append(f"| {r['mv']} | {r['bucket']} | {r['n']} | {fmt_pct(r['wdl_acc'])}{flag} |")
    if not rows:
        lines.append("| — | 无数据 | — | — |")
    lines.append("")

    # 分析 HIGH 桶
    v5_high = next((r for r in rows if r['mv'] == 'v5' and r['bucket'] == 'HIGH'), None)
    if v5_high:
        if v5_high['wdl_acc'] is not None and v5_high['wdl_acc'] < 40:
            lines.append(f"⚠️ **v5 HIGH桶崩盘**：{fmt_pct(v5_high['wdl_acc'])}（应 >55%）→ 强烈提示校准器问题\n")
        else:
            lines.append(f"ℹ️ v5 HIGH桶：{fmt_pct(v5_high['wdl_acc'])}（样本={v5_high['n']}）\n")
    else:
        lines.append("ℹ️ v5 HIGH桶无数据（近14天）\n")
    return "\n".join(lines)


# ── Section D：按预测方向偏斜 ───────────────────────────────────────────────────
def section_d(conn):
    lines = ["## D. 近 14 天按预测方向分布（检测偏斜）\n"]
    sql = """
SELECT
  CASE WHEN model_version_active='v4' THEN 'v4' ELSE 'v5' END AS mv,
  pred_wdl_pick AS predicted,
  COUNT(*) AS n,
  ROUND(100.0*SUM(wdl_correct)/NULLIF(COUNT(*),0), 2) AS acc
FROM prediction_audit
WHERE match_date >= date('now', '-14 days')
  AND actual_wdl IS NOT NULL
  AND pred_wdl_pick IS NOT NULL
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC
"""
    rows = q(conn, sql)
    lines.append("| 版本 | 预测方向 | 次数 | 准确率 |")
    lines.append("|------|----------|------|--------|")
    for r in rows:
        lines.append(f"| {r['mv']} | {r['predicted']} | {r['n']} | {fmt_pct(r['acc'])} |")
    if not rows:
        lines.append("| — | 无数据 | — | — |")
    lines.append("")

    # 检测偏斜：某方向占比 > 60%
    v5_rows = [r for r in rows if r['mv'] == 'v5']
    total_v5 = sum(r['n'] for r in v5_rows)
    if total_v5 > 0:
        for r in v5_rows:
            pct = 100.0 * r['n'] / total_v5
            if pct > 60:
                lines.append(f"⚠️ **v5 方向偏斜**：{r['predicted']} 占 {pct:.1f}%（>60%）→ 训练数据可能失衡\n")
                break
        else:
            lines.append("✅ v5 方向分布无严重偏斜\n")
    return "\n".join(lines)


# ── Section E：校准图数据（概率桶 vs 实际频率）──────────────────────────────────
def section_e(conn):
    lines = ["## E. 校准图数据（近 30 天，p_home 分桶 vs 实际主场胜率）\n"]
    sql = """
SELECT
  CASE WHEN model_version_active='v4' THEN 'v4' ELSE 'v5' END AS mv,
  ROUND(pred_wdl_home, 1) AS p_bucket,
  COUNT(*) AS n,
  ROUND(SUM(CASE WHEN actual_wdl='home_win' THEN 1.0 ELSE 0 END)/NULLIF(COUNT(*),0), 3) AS actual_freq
FROM prediction_audit
WHERE match_date >= date('now', '-30 days')
  AND actual_wdl IS NOT NULL
  AND pred_wdl_home IS NOT NULL
GROUP BY 1, 2
ORDER BY 1 DESC, 2
"""
    rows = q(conn, sql)
    lines.append("| 版本 | p_home桶 | 样本数 | 实际主胜率 | 偏差 |")
    lines.append("|------|----------|--------|------------|------|")
    for r in rows:
        if r['p_bucket'] is not None and r['actual_freq'] is not None:
            bias = r['actual_freq'] - r['p_bucket']
            flag = " ⚠️" if abs(bias) > 0.15 else ""
            lines.append(f"| {r['mv']} | {r['p_bucket']:.1f} | {r['n']} | {r['actual_freq']:.3f} | {bias:+.3f}{flag} |")
    if not rows:
        lines.append("| — | 无数据 | — | — | — |")
    lines.append("")
    lines.append("*偏差 = actual_freq - p_bucket，|偏差| > 0.15 标⚠️。系统性偏离对角线 → 校准坏了。*\n")
    return "\n".join(lines)


# ── Section F：训练快照检查 ────────────────────────────────────────────────────
def section_f(conn):
    lines = ["## F. 训练快照与健康日志\n"]

    # F1: model_training_snapshot
    snap_rows = q(conn, "SELECT * FROM model_training_snapshot ORDER BY trained_at DESC LIMIT 10")
    lines.append("### F1. model_training_snapshot（最近 10 条）\n")
    lines.append("| ID | trained_at | model_name | sample_count | accuracy | brier | notes |")
    lines.append("|----|-----------|------------|-------------|---------|-------|-------|")
    for r in snap_rows:
        lines.append(f"| {r['id']} | {r['trained_at']} | {r['model_name']} | {r['sample_count']} | {fmt_pct(r['accuracy'] and r['accuracy']*100)} | {fmt_f(r['brier'])} | {r['notes'] or ''} |")
    if not snap_rows:
        lines.append("| — | 无数据 | — | — | — | — | — |")
    lines.append("")

    # F2: model_health_log 趋势（最近 14 天）
    health_rows = q(conn, "SELECT * FROM model_health_log ORDER BY log_date DESC LIMIT 14")
    lines.append("### F2. model_health_log（最近 14 天）\n")
    lines.append("| 日期 | 窗口 | WDL准确率 | OU准确率 | Brier WDL | 漂移告警 | 重训触发 |")
    lines.append("|------|------|-----------|----------|-----------|----------|----------|")
    for r in health_rows:
        wdl_flag = " ⚠️" if r['wdl_accuracy'] and r['wdl_accuracy'] < 0.42 else ""
        lines.append(f"| {r['log_date']} | {r['window_size']} | {fmt_pct(r['wdl_accuracy'] and r['wdl_accuracy']*100)}{wdl_flag} | {fmt_pct(r['ou_accuracy'] and r['ou_accuracy']*100)} | {fmt_f(r['wdl_brier_avg'])} | {'🚨' if r['drift_alert'] else '—'} | {'✅' if r['retrain_triggered'] else '—'} |")
    if not health_rows:
        lines.append("| — | 无数据 | — | — | — | — | — |")
    lines.append("")

    # F3: calibration.json / calibrators.pkl 时间戳
    calib_path = os.path.join(BACKEND_DIR, "models_v4", "calibration.json")
    lines.append("### F3. 校准文件时间戳\n")
    for fpath in [
        os.path.join(BACKEND_DIR, "models_v4", "calibration.json"),
        os.path.join(BACKEND_DIR, "models_v4", "calibrators.pkl"),
    ]:
        if os.path.exists(fpath):
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath), tz=timezone.utc)
            lines.append(f"- `{os.path.basename(fpath)}`: 最后修改 **{mtime.strftime('%Y-%m-%d %H:%M:%S UTC')}**")
        else:
            lines.append(f"- `{os.path.basename(fpath)}`: ❌ 文件不存在")
    lines.append("")

    # F4: v5 上线时间估算（第一条 model_version_active IS NULL 的 audit_time）
    v5_first = q(conn, "SELECT MIN(audit_time) as first_at FROM prediction_audit WHERE model_version_active IS NULL AND actual_wdl IS NOT NULL")
    if v5_first and v5_first[0]['first_at']:
        lines.append(f"ℹ️ v5 首次审计记录时间（估算上线时间）：**{v5_first[0]['first_at']}**\n")
    else:
        lines.append("ℹ️ v5 首次审计记录：无数据\n")

    return "\n".join(lines)


# ── Section G：数据泄漏探测 ───────────────────────────────────────────────────
def section_g(conn):
    lines = ["## G. 数据泄漏探测\n"]

    # G1: v5 上线时间
    v5_first_row = q(conn, "SELECT MIN(audit_time) as first_at FROM prediction_audit WHERE model_version_active IS NULL AND actual_wdl IS NOT NULL")
    v5_deploy_time = v5_first_row[0]['first_at'] if v5_first_row else None

    # G2: training_snapshot 最新
    snap = q(conn, "SELECT MAX(trained_at) as last_train FROM model_training_snapshot")
    last_train = snap[0]['last_train'] if snap else None

    lines.append(f"- v5 估算上线时间：`{v5_deploy_time or 'N/A'}`")
    lines.append(f"- 最新训练快照时间：`{last_train or 'N/A'}`\n")

    # G3: 检查 prediction_audit 中有没有 match_date > 训练快照时间 的 v4 样本
    # （穿越特征的间接信号：如果模型训练时间 T，但某些 match_date > T 的场次预测特别准，可能有 leak）
    if last_train:
        future_rows = q(conn, """
SELECT COUNT(*) as cnt,
       ROUND(100.0*SUM(wdl_correct)/NULLIF(COUNT(*),0),2) as acc
FROM prediction_audit
WHERE match_date > ?
  AND actual_wdl IS NOT NULL
  AND model_version_active = 'v4'
""", (last_train[:10],))
        if future_rows and future_rows[0]['cnt']:
            lines.append(f"ℹ️ v4 训练后（{last_train[:10]}之后）预测样本：{future_rows[0]['cnt']} 场，WDL={fmt_pct(future_rows[0]['acc'])}（这是正常的模型推理，不是泄漏）\n")

    # G4: v5 行样本 match_date 分布（看是否有异常早的日期）
    v5_date_range = q(conn, """
SELECT MIN(match_date) as min_d, MAX(match_date) as max_d, COUNT(*) as n
FROM prediction_audit
WHERE model_version_active IS NULL AND actual_wdl IS NOT NULL
""")
    if v5_date_range and v5_date_range[0]['n']:
        r = v5_date_range[0]
        lines.append(f"ℹ️ v5 样本 match_date 范围：`{r['min_d']}` ~ `{r['max_d']}`（共 {r['n']} 场）\n")

    # G5: 检查 prob_sanity_flag 是否有异常
    sanity_rows = q(conn, """
SELECT prob_sanity_flag, COUNT(*) as cnt
FROM prediction_audit
WHERE model_version_active IS NULL
  AND prob_sanity_flag IS NOT NULL
GROUP BY 1
ORDER BY 2 DESC
LIMIT 10
""")
    if sanity_rows:
        lines.append("### G. prob_sanity_flag 分布（v5 行）\n")
        lines.append("| sanity_flag | 次数 |")
        lines.append("|------------|------|")
        for r in sanity_rows:
            lines.append(f"| {r['prob_sanity_flag']} | {r['cnt']} |")
        lines.append("")
    else:
        lines.append("ℹ️ v5 行无 prob_sanity_flag 记录\n")

    lines.append("""
**注意**：本脚本无法直接读取训练数据集中的 match_id 列表（未存 DB）。
若需完整数据泄漏检查，需人工对照 `model_training_snapshot.notes` 或训练日志。
""")
    return "\n".join(lines)


# ── 结论汇总 ────────────────────────────────────────────────────────────────────
def section_conclusion(conn):
    lines = ["## 结论：5 个诊断问题\n"]

    # Q1: v5 退化是否集中在 1-2 个联赛？
    league_rows = q(conn, """
SELECT
  dm.League_ID as league_id,
  COUNT(*) as n,
  ROUND(100.0*SUM(pa.wdl_correct)/NULLIF(COUNT(*),0), 2) as acc
FROM prediction_audit pa
JOIN dim_match dm ON CAST(dm.Match_ID AS TEXT) = CAST(pa.match_id AS TEXT)
WHERE pa.match_date >= date('now', '-14 days')
  AND pa.actual_wdl IS NOT NULL
  AND pa.model_version_active IS NULL
GROUP BY 1
HAVING COUNT(*) >= 3
ORDER BY acc ASC
LIMIT 5
""")
    bad_leagues = [r for r in league_rows if r['acc'] is not None and r['acc'] < 40]
    if bad_leagues and len(bad_leagues) <= 2:
        q1 = f"⚠️ **是**：退化集中在联赛 {[r['league_id'] for r in bad_leagues]}（acc<40%，n≥3）→ 可临时黑名单这些联赛"
    elif bad_leagues:
        q1 = f"⚠️ **部分是**：多个联赛 v5 acc<40%：{[r['league_id'] for r in bad_leagues]} → 全局问题信号"
    else:
        q1 = "✅ 否：退化非集中在单一联赛 → 全局问题（或样本太少无法判断）"

    # Q2: v5 HIGH 桶是否崩盘？
    high_row = q(conn, """
SELECT COUNT(*) as n, ROUND(100.0*SUM(wdl_correct)/NULLIF(COUNT(*),0),2) as acc
FROM prediction_audit
WHERE match_date >= date('now','-14 days')
  AND actual_wdl IS NOT NULL
  AND model_version_active IS NULL
  AND confidence_wdl = 'HIGH'
""")
    if high_row and high_row[0]['n'] > 0:
        acc = high_row[0]['acc']
        n = high_row[0]['n']
        if acc is not None and acc < 40:
            q2 = f"⚠️ **是**：v5 HIGH桶 {fmt_pct(acc)}（n={n}，应>55%）→ 校准器问题，建议立即 emergency recalibrate"
        else:
            q2 = f"✅ 否：v5 HIGH桶 {fmt_pct(acc)}（n={n}）→ 校准器基本正常"
    else:
        q2 = "⚠️ 无数据：v5 HIGH桶近14天样本不足"

    # Q3: v5 是否疯狂偏向某方向？
    dir_rows = q(conn, """
SELECT pred_wdl_pick, COUNT(*) as n
FROM prediction_audit
WHERE match_date >= date('now','-14 days')
  AND actual_wdl IS NOT NULL
  AND model_version_active IS NULL
  AND pred_wdl_pick IS NOT NULL
GROUP BY 1
""")
    total_v5 = sum(r['n'] for r in dir_rows)
    q3 = "⚠️ 无预测方向数据"
    if total_v5 > 0:
        for r in dir_rows:
            pct = 100.0 * r['n'] / total_v5
            if pct > 60:
                q3 = f"⚠️ **是**：{r['pred_wdl_pick']} 占 {pct:.1f}% → 训练数据可能失衡或损失函数 bug"
                break
        else:
            q3 = f"✅ 否：方向分布无严重偏斜（total={total_v5}）"

    # Q4: 校准图是否系统性偏离对角线？
    calib_rows = q(conn, """
SELECT ROUND(pred_wdl_home, 1) as pb,
       ROUND(SUM(CASE WHEN actual_wdl='home_win' THEN 1.0 ELSE 0 END)/NULLIF(COUNT(*),0),3) as freq
FROM prediction_audit
WHERE match_date >= date('now','-30 days')
  AND actual_wdl IS NOT NULL
  AND model_version_active IS NULL
  AND pred_wdl_home IS NOT NULL
GROUP BY 1
HAVING COUNT(*) >= 3
""")
    large_bias = [r for r in calib_rows if r['pb'] is not None and r['freq'] is not None and abs(r['freq'] - r['pb']) > 0.15]
    if len(large_bias) >= 2:
        q4 = f"⚠️ **是**：{len(large_bias)} 个概率桶偏差 >0.15 → 立刻跑 isotonic recalibrate 救急"
    elif calib_rows:
        q4 = "✅ 否：校准图无系统性偏离（或样本不足）"
    else:
        q4 = "⚠️ 无校准图数据（样本不足）"

    # Q5: 训练快照有没有数据泄漏信号？
    q5 = "ℹ️ 无法自动判定：需人工核对 model_training_snapshot 时间戳 vs v5 首次部署时间（见 Section F）"

    lines.append(f"| # | 问题 | 结论 |")
    lines.append(f"|---|------|------|")
    lines.append(f"| Q1 | v5 退化是否集中在 1-2 个联赛？ | {q1} |")
    lines.append(f"| Q2 | v5 HIGH 桶是否崩盘？ | {q2} |")
    lines.append(f"| Q3 | v5 是否疯狂偏向某方向？ | {q3} |")
    lines.append(f"| Q4 | v5 校准图是否系统性偏离对角线？ | {q4} |")
    lines.append(f"| Q5 | 训练快照有没有数据泄漏？ | {q5} |")
    lines.append("")

    # 三种结局判断
    high_bucket_crashed = "HIGH桶" in q2 and "是" in q2
    calib_biased = "是" in q4
    direction_skewed = "是" in q3 and "否" not in q3

    lines.append("### 三种结局判断\n")
    if direction_skewed:
        lines.append("**→ 结局 B：模型内核坏了**（方向偏斜 → 训练数据失衡或损失函数 bug）")
        lines.append("  建议：回滚 v5，修 bug，重训")
    elif high_bucket_crashed or calib_biased:
        lines.append("**→ 结局 A：校准坏了**（HIGH桶崩盘 / 校准图偏离 → 温度缩放或 isotonic 失效）")
        lines.append("  建议：立刻跑 `python -m recalibrate`，24h 后复查")
    else:
        lines.append("**→ 结局 C：合理的赛季末噪音**（小球队多/换帅多，无明确校准或方向信号）")
        lines.append("  建议：保持现状，WDL 阈值临时放宽到 38%，等下赛季重评")
    lines.append("")
    return "\n".join(lines)


# ── 主入口 ──────────────────────────────────────────────────────────────────────
def main():
    print(f"[diagnose_v5_drift] 连接数据库：{DB_PATH}")
    conn = get_conn()

    report_lines = [
        f"# v5 模型退化根因诊断报告",
        f"",
        f"**生成时间**：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"",
        f"---",
        f"",
    ]

    sections = [
        ("A. v4 vs v5 多时间窗口对比", section_a),
        ("B. 按联赛拆分", section_b),
        ("C. 按置信度桶", section_c),
        ("D. 按预测方向偏斜", section_d),
        ("E. 校准图数据", section_e),
        ("F. 训练快照与健康日志", section_f),
        ("G. 数据泄漏探测", section_g),
        ("结论", section_conclusion),
    ]

    for title, fn in sections:
        print(f"  → {title}...")
        try:
            report_lines.append(fn(conn))
            report_lines.append("\n---\n")
        except Exception as e:
            report_lines.append(f"## ❌ {title}\n\n生成失败：{e}\n\n---\n")
            print(f"     ERROR: {e}")

    conn.close()

    report_content = "\n".join(report_lines)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"\n✅ 报告已写入：{REPORT_PATH}")
    print("   下一步：cat " + REPORT_PATH)
    return REPORT_PATH


if __name__ == "__main__":
    main()
