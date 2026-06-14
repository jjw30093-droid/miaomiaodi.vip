#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性脚本：写入「科特迪瓦 vs 厄瓜多尔」世界杯研报到 worldcup.db。

方向由站长给定（小球）。盘口与赔率取自 worldcup.db 的 wc_odds
（devig 市场共识 + 最新报价）：主线 2.5，小球 @1.41。
正文数据分析师视角手写，非 LLM 管线产物。

运行（服务器，后端 venv）：
    cd /home/ubuntu/app/backend
    venv/bin/python3 scripts/seed_civ_ecu_report.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wc_store  # noqa: E402

DB_PATH = "/home/ubuntu/app/backend/worldcup.db"
MATCH_ID = "wc_19609157"
FIXTURE_ID = 19609157

MD = """# 科特迪瓦 vs 厄瓜多尔 · 世界杯 2026

> 这是一场两条顶级防线的碰撞。科特迪瓦预选赛 10 场全部零封、一球未失；厄瓜多尔 18 场仅丢 5 球，是南美区最稳的后防。市场把胜负定为接近五五开、平局概率高达三成，进球数被一致看低——本文论证小球的价值。

## 量化概率基准线

**胜平负 · 市场共识**（综合 18 家机构报价，已剔除水位，离散度 0.8%）

| 科特迪瓦 主胜 | 平局 | 厄瓜多尔 客胜 |
|:---:|:---:|:---:|
| **26.6%** | **33.8%** | **39.6%** |

市场略偏厄瓜多尔、平局概率高达 33.8%（Opta 模型则给出更接近的 38.6% / 27.0% / 34.4%，科特迪瓦微弱领先）。无论哪个口径，结论一致：这是一场势均力敌、谁也奈何不了谁的硬仗。

**大小球 · 市场隐含**（已剔除水位）

| 盘口 | 小球隐含 | 小球报价 |
|:---:|:---:|:---:|
| 2.5 | **约 67%** | @1.41 |
| 2.25 | 约 62% | @1.52 |
| 2.0 | 约 55% | @1.69 |

整条大小球被压得很低，小球在每一档都是市场多数共识——书商笃定这是一场低进球的比赛。

## 大小球分析

这条小球逻辑的地基，是两条赛季级的顶级防线。

**科特迪瓦：预选 10 场，0 失球。** 整个非洲区预选赛，科特迪瓦 10 场比赛一球未失、场场零封，是 CAF 仅有的两支零失球球队之一。这不是偶然的运气，而是一套成型、纪律严明的防守体系。

**厄瓜多尔：南美最稳后防 + 顶级门将。** 厄瓜多尔在 18 场南美区预选赛只丢了 5 球，是 CONMEBOL 失球最少的球队；门将加林德斯扑救阻止了 3.8 个预期失球，是所有晋级球队门将里最高的。厄瓜多尔的踢法本就保守——预选赛只打入 14 球，明显是一支“先求不失、再图进取”的球队。

**两套低产进攻撞上两条铁闸。** 科特迪瓦预选赛打入 25 球、非洲区最多，火力看似不俗；但面对厄瓜多尔这条后防，进攻效率会被显著压制。而厄瓜多尔本身的进攻就有限。当两支以防守立身的球队相遇，比赛极易陷入中场缠斗、机会稀少的格局——这正是小球最理想的土壤。

盘口选择上，小 2.5（总进球 ≤2 全赢）是最干净的表达，@1.41 反映了高确定性；若想要更高赔率，小 2.25（@1.52）在两条铁防的背景下同样具备说服力。

## 风险与反方

诚实地讲，小球也有翻车的剧本。

**一粒定位球或个人失误。** 防守再稳，世界杯的紧张加上一次定位球、一次单防失位，都可能打破僵局；一旦先丢球，落后方压上，比赛反而可能开放、总进球被推高。

**科特迪瓦的进攻并非摆设。** 25 个预选赛进球说明他们有真火力，若厄瓜多尔被迫前压抢分，科特迪瓦的反击质量足以把比分带到 2-1、2-2 这类击穿小球的区间。

**越低的盘口，容错越小。** 小 2.5 只要总进球到 3 就全输，没有缓冲。两条强防固然压低期望，但单场样本的方差始终存在。

## 盘口机制

小 2.5 的结算：

- 总进球 ≤ 2（0-0、1-0、1-1、2-0…）：全赢
- 总进球 ≥ 3：全输

无半赢、无退水，干净利落。理想剧本是 0-0、1-0、1-1 这类典型的防守拉锯。

## 推荐

**小球 2.5 @1.41** · 仅供参考

两条本届最稳的防线相遇，配上高达三成的平局概率，这场比赛的基因就写着“低进球”。市场已重押小球，而两队预选赛近乎零封的防守数据，让我们认为真实的低进球概率比盘口还要更高。最大的风险，是一次定位球打破僵局后的开放对攻。
"""

BEGINNER = (
    "这两支球队都是防守极硬的类型——科特迪瓦预选赛一个球都没丢过，"
    "厄瓜多尔的后防和门将也是南美最稳的。两条铁防相遇，加上他们进攻本就不算犀利，"
    "比赛很可能踢得沉闷、进球很少，所以我们押“总进球少”这一边。"
    "最大的担心是一个定位球或失误打破平衡，之后双方对攻把球数推上去。"
)

KEY_RISK = "一粒定位球打破僵局后转为对攻，总进球到3即输"

KEY_VARS = [
    "科特迪瓦预选10场零封无失球",
    "厄瓜多尔南美失球最少+顶级门将",
    "两队进攻产量均有限",
]

PREVIEW = (
    "科特迪瓦预选赛 10 场零封、一球未失；厄瓜多尔则是南美失球最少的球队，"
    "门将数据冠绝所有晋级队。当本届最稳的两条防线相遇，比赛的基因就写着低进球。"
    "本文从双方防守成色、进攻产量与市场盘口三个维度，拆解小球的价值与最大风险。"
    "解锁查看完整推荐盘口与赔率。"
)

INFERENCE = "【推荐】小球 2.5 @1.41 · 仅供参考"


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
            home_team="科特迪瓦",
            away_team="厄瓜多尔",
            match_time="2026-06-14 23:00:00",
            league="World Cup",
            is_free=0,
            home_prob=26.6,
            draw_prob=33.8,
            away_prob=39.6,
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
