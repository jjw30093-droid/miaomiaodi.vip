#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性脚本：写入「比利时 vs 埃及」世界杯研报到 worldcup.db。

方向由站长给定（小球 2.5）。赔率取自 worldcup.db 的 wc_odds（小2.5 @1.84）。
正文数据分析师视角手写，非 LLM 管线产物。结合前期对"Opta vs 市场"分歧的研究。

运行（服务器，后端 venv）：
    cd /home/ubuntu/app/backend
    venv/bin/python3 scripts/seed_bel_egy_report.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wc_store  # noqa: E402

DB_PATH = "/home/ubuntu/app/backend/worldcup.db"
MATCH_ID = "wc_19609139"
FIXTURE_ID = 19609139

MD = """# 比利时 vs 埃及 · 世界杯 2026

> 这场比赛的争论全在胜负盘——市场把比利时买成强热门，Opta 却给出近五五开。但真正确定性更高的，不是谁赢，而是这会是一场低进球的胶着。本文论证小 2.5。

## 量化概率基准线

**胜平负 · 市场共识**（综合 20 家机构报价，已剔除水位）

| 比利时 主胜 | 平局 | 埃及 客胜 |
|:---:|:---:|:---:|
| **57.9%** | **24.8%** | **17.3%** |

市场重押比利时（亚盘让一球），但 Opta 超算只给 37.2% / 27.3% / 35.5%——这是 Elo 模型在单场维度向五五开收敛的固有特性（同一套超算的实力评分其实是比利时 83.3 vs 埃及 67.7，认可比利时更强）。两套口径的共同点是：没人认为埃及会被打穿成筛子。

**大小球 2.5 · 市场隐含**（已剔除水位）

| 大 2.5 | 小 2.5 |
|:---:|:---:|
| 约 48% | **约 52%** |

主线就开在 2.5，小球一侧是市场多数共识，报价小 2.5 @1.84。

## 大小球分析

把胜负盘的噪音放一边，进球数这条线的逻辑反而干净。

**埃及是来防守的，而且防得住。** 预选赛埃及 10 场只丢 2 球、8 场零封，是非洲区最稳的后防之一。作为本场净胜概率不到两成的一方，埃及大概率摆出低位防线、收缩反击——这是一支主动求"不丢球"的球队，而非来对攻的。

**埃及的进攻是单点，且这个点在下滑。** 埃及预选进球高度依赖萨拉赫，但他刚经历利物浦生涯多年最差的一季（全赛事 32 场 9 球），比赛日已满 34 岁，身边缺乏第二攻击火力。指望埃及在比利时身上频繁破门并不现实——他们更可能整场只创造寥寥数次机会。

**连市场都不信比利时能大胜。** 这是关键一点：尽管 1X2 把比利时买成强热门（公众票面几乎一边倒），但让球盘很诚实——让一球(-1)的水位仍挂在 2.05 以上、部分书商只敢开 -0.5。也就是说，真正带钱的市场对"比利时净胜两球"并无把握。一个不被预期打出大比分的热门 + 一支主动龟缩且攻击贫乏的弱旅，总进球自然被压低。

## 风险与反方

诚实地讲，小球的对立面有两颗真实的火星。

**比利时的进攻是真的强。** 他们近 13 场不败、热身 5-0 血洗突尼斯（5 人破门）、预选打入 29 球；多库、德布劳内、卢卡库一旦联动，单场打进 3 球的能力完全具备。如果埃及低位防线被一次定位球或个人能力凿穿、随后被迫压上，比赛会瞬间打开。

**比利时的后防也是临时拼凑。** 加西亚的体系尚未磨合、中卫 Mechele 已 33 岁——这恰恰是萨拉赫、马尔穆什反击想要的空间。一旦互交白卷的僵局被打破，"你来我往"就可能把球数推过 2.5。换句话说，杀死小球的剧本不是埃及进攻爆发，而是比利时"赢得太开放"。

## 盘口机制

小 2.5 的结算：

- 总进球 ≤ 2（0-0、1-0、2-0、1-1…）：全赢
- 总进球 ≥ 3：全输

无半赢、无退水。理想剧本是比利时 1-0、2-0 的控制型小胜，或 1-1 的闷平。

## 推荐

**小球 2.5 @1.84** · 仅供参考

胜负盘的市场分歧很大，但进球数这条线，模型与盘口难得地同向——都指向一场不开放的比赛。埃及防守扎实且攻击单薄、主动龟缩，而连市场自己都不相信比利时能大胜。@1.84 押注的，就是这场被双方共同压低的总进球。最大的风险，是比利时用一场酣畅的大胜，证明自己配得上那个热门价。
"""

BEGINNER = (
    "比利时整体更强、是热门，但埃及防守很硬（预选赛十场只丢两球），"
    "而且打算龟缩防守、进攻几乎只靠萨拉赫一个人——可萨拉赫今年状态明显下滑了。"
    "更关键的是，连博彩市场自己都不太相信比利时能大比分赢。"
    "一支不被看好大胜的热门 + 一支专心防守、攻击又贫乏的弱旅，比赛大概率进球不多，"
    "所以我们押“总进球少”（小 2.5）。最大的担心是比利时火力全开，踢成一场对攻大胜。"
)

KEY_RISK = "比利时进攻爆发或后防漏球打成对攻，总进球到3即输"

KEY_VARS = [
    "埃及防守扎实且主动龟缩",
    "萨拉赫单点进攻且状态下滑",
    "市场让球盘亦不信比利时大胜",
]

PREVIEW = (
    "本场胜负盘争议极大——市场把比利时买成强热门，Opta 却给近五五开。"
    "但进球数这条线的逻辑反而清晰：埃及防守扎实（预选十场仅丢两球）、主动龟缩，"
    "进攻又高度依赖状态下滑的萨拉赫；而连博彩让球盘都不相信比利时能大胜。"
    "本文从双方攻防成色与市场盘口出发，论证小 2.5 的价值与最大风险。解锁查看完整推荐与赔率。"
)

INFERENCE = "【推荐】小球 2.5 @1.84 · 仅供参考"


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
            home_team="比利时",
            away_team="埃及",
            match_time="2026-06-15 19:00:00",
            league="World Cup",
            is_free=0,
            home_prob=57.9,
            draw_prob=24.8,
            away_prob=17.3,
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
