#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性脚本：写入「荷兰 vs 日本」世界杯研报到 worldcup.db。

方向由站长给定（双方进球 / BTTS Yes），赔率由站长给定 @1.78。
正文数据分析师视角手写，非 LLM 管线产物。
WDL / BTTS 概率取自 worldcup.db 的 wc_odds（devig 市场共识）。

运行（服务器，后端 venv）：
    cd /home/ubuntu/app/backend
    venv/bin/python3 scripts/seed_ned_jpn_report.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wc_store  # noqa: E402

DB_PATH = "/home/ubuntu/app/backend/worldcup.db"
MATCH_ID = "wc_19609138"
FIXTURE_ID = 19609138

MD = """# 荷兰 vs 日本 · 世界杯 2026

> 这不是一场实力悬殊的对话。市场把荷兰摆在约 48% 的胜率，日本 26%、平局 27%——荷兰是热门，但只是“谨慎的热门”。两支球队都带着能进球的前场而来，本文论证“双方进球”的价值。

## 量化概率基准线

**胜平负 · 市场共识**（综合 20 家机构报价，已剔除水位，离散度 1.0%）

| 荷兰 主胜 | 平局 | 日本 客胜 |
|:---:|:---:|:---:|
| **47.6%** | **26.7%** | **25.7%** |

**进球相关 · 市场隐含**（已剔除水位）

| 市场 | 倾向 |
|:---:|:---:|
| 大小球 2.5（主线） | 大 49% / 小 51% |
| 双方进球 | **是 ≈53% / 否 ≈47%** |

荷兰是热门，但优势有限（胜率不到五成）；大小球主线落在 2.5，双方进球市场已略偏“是”（约 53%）。换句话说，书商预期这是一场你来我往、两边都可能破门的比赛。推荐方向“双方进球”与市场共识同向，@1.78 的报价提供了合理补偿。

## 双方进球分析

判断“双方进球”，要分别回答两个问题：荷兰会进球吗？日本会进球吗？两个都大概率“会”，这注就成立。

**荷兰几乎一定会进。** 作为净胜概率近五成的热门，荷兰前场火力充足——德佩预选赛打入 8 球、并列助攻王（4 次），是欧洲区效率最高的攻击点之一。荷兰世界杯历史胜率 54.5%、距离队史第 100 个世界杯进球只差 4 个。对阵一支需要前压抢分的日本，荷兰的进球只是时间问题。

**日本对强队的进球能力被低估。** 这是本推荐的关键支点。日本预选赛打入 51 球，是亚洲区进球最多的球队；久保建英、伊东纯也、上田绮世组成的攻击群效率不俗。更关键的是过往战绩：2022 卡塔尔世界杯，日本先后击败德国与西班牙、2-1 掀翻德国，2018 年又 2-1 力克哥伦比亚——面对欧洲强队，日本不仅能防，更能破门。他们不是来摆大巴混平局的球队，而是会主动反击、并且真的进得了球。

**荷兰的防线稳，但不是铁桶。** 荷兰近 16 场小组赛不败（12 胜 4 平），防守组织扎实，但“不败”不等于“零封”。面对日本的速度与边路冲击，荷兰后防被打穿一球的剧本完全在射程之内。

## 风险与反方

诚实地讲，“双方进球”不是稳赚。

**荷兰可能零封。** 16 场不败里荷兰交出过多场零封，如果他们控制住中场、压缩日本的反击空间，日本未必能把球送进网窝。一旦荷兰打出 2-0、1-0 的控制型胜利，这注就输了。

**比赛可能偏闷。** 大小球主线 2.5、且市场略偏小球（51%），说明书商并不认为这是一场必然的进球大战。日本若选择稳守反击、压低节奏，总进球与破门概率都会被拉低。0-0、1-0 都是“双方进球”的对立面。

**日本的临门一脚。** 能创造机会不等于能把握机会——面对荷兰这一档的防线，日本的射正转化率可能打折。

## 盘口机制

“双方进球（是）”的结算很直接：

- 两队各进至少 1 球（1-1、2-1、3-2…）：赢
- 任意一队零进球（1-0、2-0、0-0…）：输

与比分大小、谁输谁赢无关，只看两边是否都破门。

## 推荐

**双方进球（是）@1.78** · 仅供参考

荷兰会进球几乎没有悬念，真正的赌注在日本能否破门——而日本恰恰是一支用行动证明过“能在强队身上进球”的队伍。市场已略偏“双方进球”，@1.78 在此基础上给出合理补偿。最大的风险，是荷兰打出一场克制的零封胜。
"""

BEGINNER = (
    "荷兰是热门、几乎肯定会进球；日本虽然实力稍逊，但是一支敢打敢拼、"
    "而且真的能在强队身上进球的队伍（曾掀翻德国和西班牙）。"
    "我们押“两队都进球”这一边。最大的担心是荷兰踢得很稳、把日本完全摁住，"
    "自己赢球却让对手一球未进。"
)

KEY_RISK = "荷兰零封日本（如2-0/1-0/0-0），双方进球不成立即输"

KEY_VARS = [
    "荷兰前场火力足、几乎必进球",
    "日本能在强队身上破门",
    "荷兰防线稳但并非铁桶",
]

PREVIEW = (
    "Opta 与市场都把荷兰摆在“谨慎热门”的位置——赢面不到五成，日本并非鱼腩。"
    "两支球队都带着能进球的前场而来：荷兰有德佩领衔的高效攻击线，"
    "日本则用掀翻德国、西班牙的战绩证明了自己能在强队身上破门。"
    "本文从双方攻防成色出发，拆解“双方进球”的价值与最大风险。解锁查看完整推荐与赔率。"
)

INFERENCE = "【推荐】双方进球 @1.78 · 仅供参考"


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
            home_team="荷兰",
            away_team="日本",
            match_time="2026-06-14 20:00:00",
            league="World Cup",
            is_free=0,
            home_prob=47.6,
            draw_prob=26.7,
            away_prob=25.7,
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
