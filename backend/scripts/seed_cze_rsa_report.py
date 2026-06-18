#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性脚本：写入「捷克 vs 南非」世界杯研报（捷克 -0.5 @1.72）。"""
import os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wc_store  # noqa: E402

DB_PATH = "/home/ubuntu/app/backend/worldcup.db"
MATCH_ID = "wc_19609168"; FIXTURE_ID = 19609168

MD = """# 捷克 vs 南非 · 世界杯 2026 · A组次轮

> 两支首轮告负、都已退无可退的球队相遇。捷克是更强的一方，而南非中场刚被两张红牌掏空——本文论证捷克 -0.5（直胜）。

## 量化概率基准线

**胜平负 · 市场共识**（综合 19 家机构报价，已剔除水位）

| 捷克 主胜 | 平局 | 南非 客胜 |
|:---:|:---:|:---:|
| **56.1%** | **25.2%** | **18.7%** |

与 Opta 超算口径接近（52.9% / 23.8% / 23.3%）。捷克是热门，但平局概率有四分之一——这是 -0.5 唯一的敌人。

**让球盘 · 市场报价**

| 选项 | 即时水位 |
|:---:|:---:|
| 捷克 -0.5（主让半球，直胜） | **@1.72** |

## 让球盘分析

**南非的中场被红牌掏空了。** 首轮 0-2 不敌墨西哥，西索莱与兹瓦内双双染红停赛——一支本就在开局踢得乏力（全场仅 3 脚射门、0.07 预期进球）的球队，如今还要在中场少了两个主力。莫福肯、姆巴塔顶上，攻防强度与厚度同步下滑。

**捷克是更强、也更能跑的一方。** 首轮虽 1-2 不敌韩国，但克赖奇破门、状态在线；这支球队跑动量极大（首轮 108.3 公里、全场第二），对抗与定位球是他们的拿手戏。面对一支被迫敞开来踢的南非，捷克的整体质量更容易兑现成胜势。

**两队都退无可退，比赛不会被锁死。** 双双首轮失利，本场都输不起；南非没有摆大巴混平局的资本，必须压出来抢分。这种被迫打开的格局，恰恰利于实力更强的捷克在 90 分钟里分出胜负。

## 风险与反方

诚实地讲，-0.5 没有平局保护，平局就是它最大的敌人。

**两队都急，可能互相抵消。** 都背着出局压力、都求胜心切的比赛，有时反而踢得紧、谁也不敢先扑；捷克自己首轮也输了球，并非不可战胜。一旦演成 1-1、0-0 的平局，-0.5 全输。

**南非并非全无质量。** 莫科埃纳首轮对墨西哥送出 92.9% 的传球成功率，球队也有“糙但顶用”的一面；若捷克久攻不下、把握机会能力不足，比赛可能被拖住。

## 盘口机制

捷克 -0.5（主让半球）的结算：

- 捷克赢球：全赢
- 平局或捷克输球：全输

无走水、无半赢——等价于“押捷克直胜、不含平局保护”。

## 推荐

**捷克 主让0.5 @1.72** · 仅供参考

捷克更强、更能跑，对手又在中场少了两人、还必须压出来拼，捷克直胜是中心情景。最大的风险清晰且唯一：两支急于求分的球队互相消耗，把比赛拖成一场平局。
"""

BEGINNER = (
    "两队首轮都输了、都到了必须拿分的地步。捷克整体更强、跑动也猛，南非这边更惨——"
    "中场两名主力因红牌停赛，实力和厚度都掉了一档，而且必须压出来抢分。"
    "我们押捷克‘让半球’（也就是捷克直接赢球就算赢，踢平也算输）。"
    "最怕的是两队都太想赢、踢得拘谨，最后 1-1、0-0 收场。"
)
KEY_RISK = "两队都急于求分互相消耗，踢成平局则全输"
KEY_VARS = ["南非两名中场红牌停赛", "捷克更强且跑动量大", "两队均退无可退、比赛会打开"]
PREVIEW = (
    "两支首轮告负、都退无可退的球队相遇。捷克是更强、更能跑的一方，而南非中场刚被两张红牌掏空、"
    "还必须压出来抢分。本文从南非的减员、捷克的成色与两队的出线压力出发，"
    "论证捷克 -0.5（直胜）的价值与最大风险。解锁查看完整推荐与水位。"
)
INFERENCE = "【推荐】捷克 主让0.5 @1.72 · 仅供参考"


def main():
    conn = sqlite3.connect(DB_PATH)
    try:
        wc_store.write_wc_report(conn, match_id=MATCH_ID, fixture_sportmonks_id=FIXTURE_ID, report_markdown=MD,
            payload_json={}, inference=INFERENCE, pipeline_status="FINAL_REPORT_READY",
            home_team="捷克", away_team="南非", match_time="2026-06-18 16:00:00",
            league="World Cup", is_free=0, home_prob=56.1, draw_prob=25.2, away_prob=18.7,
            beginner_summary=BEGINNER, key_risk=KEY_RISK, key_variables=KEY_VARS,
            chart_insights=None, match_status="upcoming", preview_content=PREVIEW)
        conn.commit()
        print("WROTE:", conn.execute("SELECT match_id,is_free,home_prob,draw_prob,away_prob,inference,length(report_markdown) FROM wc_reports WHERE match_id=?", (MATCH_ID,)).fetchone())
    finally:
        conn.close()


if __name__ == "__main__":
    main()
