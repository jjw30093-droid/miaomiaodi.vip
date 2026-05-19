"""
backfill_odds_final.py
======================
回填 prediction_audit.odds_final_* 字段，供 daily_backtest 计算 PnL。

优先级：
  1. report_store.inference 中含 WDL pick + @X.XX 赔率 → 直接提取
  2. 其余：用模型概率 pred_wdl_home/draw/away 加 5% 水反推隐含赔率
"""
import os, re, sqlite3, logging

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "football_uk.db"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

MARGIN = 1.05   # 博彩商综合水率（用于模型概率→隐含赔率）

# WDL label → pick key
WDL_LABELS = {
    '主胜': 'home_win', '客胜': 'away_win', '平局': 'draw',
}


def _parse_wdl_odds_from_inference(inference: str) -> tuple[str | None, float | None]:
    """
    从 inference 字符串提取 (wdl_direction, odds)。
    仅当 inference 是 WDL pick（主胜/客胜/平局）时才有效。
    返回 (None, None) 表示不是 WDL pick 或无法提取。
    """
    if not inference or inference.strip() in ('—', 'AI 分析中...'):
        return None, None
    # 找 WDL 中文标签
    for label, direction in WDL_LABELS.items():
        if label in inference:
            # 尝试提取 @X.XX
            m = re.search(r'@([\d.]+)', inference)
            odds = float(m.group(1)) if m else None
            return direction, odds
    return None, None


def _implied_odds(prob: float) -> float | None:
    """概率 → 隐含赔率（加水）"""
    if not prob or prob <= 0:
        return None
    return round(1.0 / (prob * MARGIN), 3)


def run(target_dates=('2026-04-17', '2026-04-18'), dry_run=False):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    placeholders = ','.join('?' * len(target_dates))
    rows = conn.execute(f"""
        SELECT pa.match_id, pa.match_date, pa.home_name, pa.away_name,
               pa.pred_wdl_pick,
               pa.pred_wdl_home, pa.pred_wdl_draw, pa.pred_wdl_away,
               rs.inference
        FROM prediction_audit pa
        LEFT JOIN report_store rs ON rs.match_id = pa.match_id
        WHERE pa.match_date IN ({placeholders})
          AND pa.actual_wdl IS NOT NULL
          AND pa.odds_final_home IS NULL
    """, target_dates).fetchall()

    log.info(f"需要回填 {len(rows)} 场")
    updated = 0

    for r in rows:
        mid       = r['match_id']
        pick      = r['pred_wdl_pick']    # home_win / draw / away_win
        p_home    = r['pred_wdl_home']
        p_draw    = r['pred_wdl_draw']
        p_away    = r['pred_wdl_away']
        inference = r['inference'] or ''

        # 尝试从 inference 提取 WDL 赔率
        inf_dir, inf_odds = _parse_wdl_odds_from_inference(inference)

        # 计算三列赔率
        if inf_dir and inf_odds:
            # inference 是 WDL pick，用提取到的赔率放到对应列，其余用概率推算
            o_home = inf_odds if inf_dir == 'home_win' else _implied_odds(p_home)
            o_draw = inf_odds if inf_dir == 'draw'     else _implied_odds(p_draw)
            o_away = inf_odds if inf_dir == 'away_win' else _implied_odds(p_away)
            src = f'inference({inf_dir}@{inf_odds}) + prob'
        else:
            # 全部用概率推算
            o_home = _implied_odds(p_home)
            o_draw = _implied_odds(p_draw)
            o_away = _implied_odds(p_away)
            src = 'prob-implied'

        log.info(f"  {r['home_name']:12} vs {r['away_name']:12} | pick={pick:8} | "
                 f"H:{o_home} D:{o_draw} A:{o_away} | src={src}")

        if not dry_run:
            conn.execute("""
                UPDATE prediction_audit
                SET odds_final_home = ?,
                    odds_final_draw = ?,
                    odds_final_away = ?
                WHERE match_id = ?
            """, (o_home, o_draw, o_away, mid))
            updated += 1

    if not dry_run:
        conn.commit()
    conn.close()
    log.info(f"回填完成：{'[DRY RUN] ' if dry_run else ''}{updated} 场")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--dates', nargs='+', default=['2026-04-17', '2026-04-18'])
    args = parser.parse_args()
    run(target_dates=tuple(args.dates), dry_run=args.dry_run)
