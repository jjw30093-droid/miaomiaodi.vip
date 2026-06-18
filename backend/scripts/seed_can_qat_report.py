#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性脚本：写入「加拿大 vs 卡塔尔」世界杯研报（加拿大 -1.5 @1.93）。"""
import os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wc_store  # noqa: E402

DB_PATH = "/home/ubuntu/app/backend/worldcup.db"
MATCH_ID = "wc_19609170"; FIXTURE_ID = 19609170

MD = """# 加拿大 vs 卡塔尔 · 世界杯 2026 · B组次轮

> 加拿大是约 73% 胜率的大热门，本轮回到温哥华大本营、坐拥全队最实在的主场之利；对手卡塔尔则是 B 组进攻最贫弱的一队。本文论证加拿大 -1.5。

## 量化概率基准线

**胜平负 · 市场共识**（综合 19 家机构报价，已剔除水位）

| 加拿大 主胜 | 平局 | 卡塔尔 客胜 |
|:---:|:---:|:---:|
| **72.2%** | **18.5%** | **9.3%** |

与 Opta 超算高度一致（72.9% / 16.5% / 10.6%）。加拿大是这批比赛里最清晰的热门之一。

**让球盘 · 市场报价**

| 选项 | 即时水位 |
|:---:|:---:|
| 加拿大 -1.5（主让一球半，净胜≥2 才赢） | **@1.93** |

## 让球盘分析

**这才是真正的主场之利。** 加拿大首轮远赴多伦多后已回到温哥华大本营，剩余两场小组赛都在温哥华踢——“苦尽甘来”的一方。他们近 4 个温哥华主场全胜、打入 17 球仅失 2，主场统治力实打实。

**加拿大的进攻在 B 组是碾压级的。** 首轮逼平波黑的比赛里，他们控球 61%、37 次禁区触球，科内（Koné）送出 9 次穿透性传球领衔全场。若戴维斯（Alphonso Davies）此役复出，边路的爆破力会进一步放大。

**卡塔尔的进攻是 B 组垫底。** 首轮对瑞士，卡塔尔各项进攻数据全组最差：仅 6 脚射门、32% 控球、8 次禁区触球，最后靠一个乌龙才逼平，阿菲夫整场只创造 2 次机会。这样一条进攻线，很难指望它在客场顶住加拿大。Opta 也直接把 -1.5 列为“合理的分析判断”。

## 风险与反方

诚实地讲，-1.5 没有缓冲，一球小胜就要全输。

**卡塔尔若摆铁桶，加拿大可能只赢一球。** 弱旅客场死守、靠一两次反击搅局，是世界杯的常见剧本；一旦加拿大打成 1-0，-1.5 直接落空。加拿大自己的临门一脚若不够利落，净胜两球的难度也会上升。

**大赛单场方差。** 热门踢弱旅偶有翻车或久攻不下，温哥华的主场期待越高，踢不开时的心理压力也越大。

## 盘口机制

加拿大 -1.5（主让一球半）的结算：

- 加拿大净胜 ≥ 2 球（2-0、3-1…）：全赢
- 加拿大净胜 ≤ 1 球（1-0、含平局、输球）：全输

无走水、无半赢——赌的就是“加拿大主场净胜两球”。

## 推荐

**加拿大 主让1.5 @1.93** · 仅供参考

真主场、强进攻、对手 B 组最弱的攻击线，加上 Opta 的明确背书，加拿大净胜两球是中心情景。最大的风险，是卡塔尔客场摆铁桶、把比赛锁成一球小胜。
"""

BEGINNER = (
    "加拿大是大热门（约 73% 胜率），而且本轮回到温哥华大本营、是真正的主场作战（近 4 个主场全胜）。"
    "对手卡塔尔是本组进攻最差的球队（首轮只射门 6 次、靠乌龙才逼平瑞士）。"
    "我们押加拿大‘让一球半’——要赢两个球以上才算赢。"
    "最怕的是卡塔尔客场摆大巴死守，加拿大只赢一个球。"
)
KEY_RISK = "卡塔尔客场摆铁桶，加拿大只赢一球则全输"
KEY_VARS = ["加拿大温哥华真主场(近4主场全胜)", "卡塔尔B组进攻垫底", "Opta明确背书-1.5"]
PREVIEW = (
    "加拿大是约 73% 胜率的大热门，本轮回温哥华大本营坐拥真正的主场之利（近 4 主场全胜、进 17 失 2）；"
    "对手卡塔尔是 B 组进攻最贫弱的一队（首轮仅 6 射、靠乌龙逼平瑞士）。Opta 也把 -1.5 列为合理判断。"
    "本文从加拿大的主场与进攻、卡塔尔的弱攻出发，论证加拿大 -1.5 的价值与最大风险。解锁查看完整推荐与水位。"
)
INFERENCE = "【推荐】加拿大 主让1.5 @1.93 · 仅供参考"


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        wc_store.write_wc_report(conn, match_id=MATCH_ID, fixture_sportmonks_id=FIXTURE_ID, report_markdown=MD,
            payload_json={}, inference=INFERENCE, pipeline_status="FINAL_REPORT_READY",
            home_team="加拿大", away_team="卡塔尔", match_time="2026-06-18 22:00:00",
            league="World Cup", is_free=0, home_prob=72.2, draw_prob=18.5, away_prob=9.3,
            beginner_summary=BEGINNER, key_risk=KEY_RISK, key_variables=KEY_VARS,
            chart_insights=None, match_status="upcoming", preview_content=PREVIEW)
        conn.commit()
        print("WROTE:", conn.execute("SELECT match_id,is_free,home_prob,draw_prob,away_prob,inference,length(report_markdown) FROM wc_reports WHERE match_id=?", (MATCH_ID,)).fetchone())
    finally:
        conn.close()


if __name__ == "__main__":
    main()
