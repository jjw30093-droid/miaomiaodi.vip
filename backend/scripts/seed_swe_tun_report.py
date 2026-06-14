#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性脚本：写入「瑞典 vs 突尼斯」世界杯研报到 worldcup.db。

方向由站长给定（让球盘 瑞典 -0.5 = 瑞典直胜，平/负输）。
盘口与赔率取自 worldcup.db 的 wc_odds（devig 共识 + 最新报价）：-0.5 @1.88。
正文数据分析师视角手写，非 LLM 管线产物。

运行（服务器，后端 venv）：
    cd /home/ubuntu/app/backend
    venv/bin/python3 scripts/seed_swe_tun_report.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wc_store  # noqa: E402

DB_PATH = "/home/ubuntu/app/backend/worldcup.db"
MATCH_ID = "wc_19609159"
FIXTURE_ID = 19609159

MD = """# 瑞典 vs 突尼斯 · 世界杯 2026

> 瑞典是市场与模型一致认可的热门（直胜约 50–52%），但突尼斯带着一条预选赛零失球的防线而来。让球盘 -0.5（瑞典直胜）即时报价约 1.88，本文论证瑞典一侧的让球价值，也直面它最大的对手——平局。

## 量化概率基准线

**胜平负 · 市场共识**（综合 20 家机构报价，已剔除水位，离散度 0.9%）

| 瑞典 主胜 | 平局 | 突尼斯 客胜 |
|:---:|:---:|:---:|
| **50.3%** | **27.7%** | **22.1%** |

市场与 Opta 高度一致（Opta：52.3% / 25.0% / 22.7%）：瑞典是热门，但只是“过半线”的热门，并非碾压。

**让球 / 进球 · 市场隐含**（已剔除水位）

| 市场 | 隐含 | 报价 |
|:---:|:---:|:---:|
| 瑞典 -0.5（直胜） | **约 51%** | @1.88 |
| 突尼斯 +0.5（不败） | 约 49% | @1.97 |
| 大小球 2.5（主线） | 小球 ≈57% | — |

让球 -0.5 把瑞典直胜定价成约五成出头，大小球则偏向小球——书商预期这是一场不那么开放、瑞典需要耐心攻坚的比赛。

## 让球盘分析

-0.5 赌的是一件事：瑞典能否赢下这场球。支撑这一判断的，是双方在“最后三十米”的质量落差。

**瑞典握有这场比赛最稀缺的资源——个人进攻能力。** 约凯雷斯（Gyökeres）在附加赛打入球队 6 球中的 4 球，并且为俱乐部和国家队连续 29 个点球全部命中；身边还有伊萨克（Isak）与埃兰加（Elanga）。面对一条会长时间退防的突尼斯后防，这种能在密集防守里凿开缺口的个人能力，正是打破僵局的关键。

**突尼斯的短板，恰恰在世界杯的舞台上。** 预选赛零失球确实亮眼，但把镜头拉到世界杯正赛：突尼斯 18 场仅 3 胜，胜率 16.7%。防守扎实不等于能拿分——他们历来缺乏在更高强度的舞台上把握机会、把均势转化为胜势的能力。

**瑞典的大赛底蕴。** 12 次世界杯揭幕战仅 2 负、近 4 次揭幕保持不败，他们知道如何在小组首战拿到结果。

让球读数上，-0.5 约 1.88、隐含瑞典直胜约 51%，接近五五开偏瑞典。我们认为这条进攻质量的鸿沟被市场低估，瑞典真实直胜概率高于这一档。

## 风险与反方

诚实地讲，这条让球最大的敌人不是输球，而是平局——而平局的概率并不低。

**突尼斯的防线是真的硬。** 预选赛一球未失，与科特迪瓦并列非洲区仅有的两支零失球球队，小组赛 30 分拿到 28（9 胜 1 平）。这是一条有组织、有纪律、专门用来拖住强队的防线。

**比赛大概率不开放。** 大小球主线 2.5、市场偏小球（约 57%），意味着低进球预期，而低进球的比赛平局概率被系统性推高。瑞典若久攻不下，0-0、1-1 的平局会直接吃掉 -0.5。

**首次交手 + 零退水容错。** 这是双方首次正式比赛，瑞典缺乏针对性经验；而 -0.5 没有平局退水，平或负全输，没有任何缓冲。

## 盘口机制

瑞典 -0.5（主让 0.5 球）的结算：

- 瑞典赢球（1-0、2-1、3-0…）：全赢
- 平局或瑞典输球：全输

无半赢、无退水，等价于“押瑞典直胜、不含平局保护”。

## 推荐

**瑞典 -0.5（主让 0.5 球）@1.88** · 仅供参考

瑞典拥有这场比赛里最稀缺的资源——能在密集防守里凿开缺口的个人能力（约凯雷斯、伊萨克、埃兰加）。市场把瑞典直胜定为约五成，我们认为这条进攻质量的鸿沟被低估。最大的风险清晰且唯一：突尼斯用一条零封过的防线，把比赛拖成平局。
"""

BEGINNER = (
    "瑞典整体更强，还有约凯雷斯、伊萨克这样的顶级前锋，是这场公认的热门。"
    "我们押“瑞典赢球”——让半球的意思就是必须瑞典赢下来，踢平也算输。"
    "最大的担心是突尼斯防守特别硬，预选赛一个球都没丢过，很可能死守把比赛拖成平局，"
    "那样这注就输了。"
)

KEY_RISK = "突尼斯死守拖成平局（如0-0/1-1），让0.5即输"

KEY_VARS = [
    "瑞典个人进攻质量明显占优",
    "突尼斯防线预选赛零失球",
    "低进球预期推高平局风险",
]

PREVIEW = (
    "瑞典是市场与 Opta 一致认可的热门，手握约凯雷斯、伊萨克、埃兰加组成的顶级攻击线；"
    "但突尼斯带着一条预选赛零失球的防线而来。让球盘 -0.5（瑞典直胜）的价值，"
    "正在于瑞典能否用个人能力凿穿这条铁防。本文从进攻质量、突尼斯的世界杯成色"
    "与平局风险三个维度展开。解锁查看完整推荐盘口与赔率。"
)

INFERENCE = "【推荐】瑞典 主让0.5 @1.88 · 仅供参考"


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        wc_store.write_wc_report(
            conn,
            match_id=MATCH_ID,
            fixture_sportmonks_id=FIXTURE_ID,
            report_markdown=MD,
            payload_json={},
            inference=INFERENCE,
            pipeline_status="FINAL_REPORT_READY",
            home_team="瑞典",
            away_team="突尼斯",
            match_time="2026-06-15 02:00:00",
            league="World Cup",
            is_free=0,
            home_prob=50.3,
            draw_prob=27.7,
            away_prob=22.1,
            beginner_summary=BEGINNER,
            key_risk=KEY_RISK,
            key_variables=KEY_VARS,
            chart_insights=None,
            match_status="upcoming",
            preview_content=PREVIEW,
        )
        conn.commit()
        row = conn.execute(
            "SELECT match_id, pipeline_status, match_status, is_free, "
            "home_prob, draw_prob, away_prob, inference, "
            "length(report_markdown) AS md_len, length(preview_content) AS pv_len "
            "FROM wc_reports WHERE match_id=?",
            (MATCH_ID,),
        ).fetchone()
        print("WROTE:", row)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
