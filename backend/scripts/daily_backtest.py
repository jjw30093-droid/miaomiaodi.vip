"""
Daily backtest script — run at 05:30 UTC via pm2 cron.
Computes Fixed Stake and Kelly-half equity curves from prediction_audit
joined with raw_footballdata_odds, then writes equity_curves.json.
"""
import sqlite3
import json
import math
import argparse
from datetime import date, timedelta, datetime

DB          = "backend/football_uk.db"
OUTPUT_JSON = "backend/models_v4/equity_curves.json"


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var  = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std  = math.sqrt(var) if var > 0 else 1e-9
    return round(mean / std * math.sqrt(252), 3)


def _max_drawdown(equity: list[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = (v - peak) / peak if peak else 0
        max_dd = min(max_dd, dd)
    return round(max_dd, 4)


def _build_curves(rows, stake_mode: str) -> dict:
    """
    rows: list of (date, wdl_correct, ou_correct, pred_wdl_home, pred_ou_over,
                   odds_home, odds_draw, odds_away, odds_over, odds_under,
                   pred_ah_pick, ah_correct, pred_ah_line, ah_home_odds, ah_away_odds)
    Returns dict: {strategies: [...], sharpe, max_drawdown}
    """
    # Sort by date
    rows = sorted(rows, key=lambda r: r[0])

    wdl_equity = [1.0]
    ou_equity  = [1.0]
    comb_equity = [1.0]
    dates = []

    wdl_returns = []
    ou_returns  = []

    for row in rows:
        (match_date, wdl_correct, ou_correct,
         p_home, p_ou_over, wdl_pick,
         o_home, o_draw, o_away, o_over, o_under,
         ah_pick, ah_correct, ah_line, ah_home_odd, ah_away_odd) = row

        dates.append(match_date)

        # Map pick to correct odds and probability
        if wdl_pick == 'home_win':
            pick_odds = o_home
            pick_prob = p_home
        elif wdl_pick == 'away_win':
            pick_odds = o_away
            pick_prob = 1.0 - (p_home or 0.5) - 0.1  # rough away prob
        elif wdl_pick == 'draw':
            pick_odds = o_draw
            pick_prob = max(0.0, 1.0 - (p_home or 0.5) - 0.2)
        else:
            pick_odds = o_home
            pick_prob = p_home

        # --- WDL bet ---
        wdl_pnl = 0.0
        if wdl_correct is not None and pick_odds is not None:
            if stake_mode == "fixed":
                stake = 1.0
            else:
                p = max(0.05, pick_prob or 0.33)
                o = pick_odds
                f = max(0.0, (p * o - 1) / (o - 1)) * 0.5 if o > 1 else 0.0
                stake = f
            if stake > 0:
                if wdl_correct == 1:
                    wdl_pnl = stake * (pick_odds - 1)
                else:
                    wdl_pnl = -stake

        prev_wdl = wdl_equity[-1]
        wdl_equity.append(round(prev_wdl + wdl_pnl, 4))
        wdl_returns.append(wdl_pnl / prev_wdl if prev_wdl > 0 else 0)

        # --- OU bet ---
        ou_pnl = 0.0
        if ou_correct is not None and o_over is not None:
            p = p_ou_over if p_ou_over else 0.5
            o = o_over
            if stake_mode == "fixed":
                stake = 1.0
            else:
                f = max(0.0, (p * o - 1) / (o - 1)) * 0.5 if o > 1 else 0.0
                stake = f
            if stake > 0:
                if ou_correct == 1:
                    ou_pnl = stake * (o - 1)
                else:
                    ou_pnl = -stake

        prev_ou = ou_equity[-1]
        ou_equity.append(round(prev_ou + ou_pnl, 4))
        ou_returns.append(ou_pnl / prev_ou if prev_ou > 0 else 0)

        # Combined (WDL + OU average)
        prev_comb = comb_equity[-1]
        comb_pnl  = (wdl_pnl + ou_pnl) / 2
        comb_equity.append(round(prev_comb + comb_pnl, 4))

    # Build point lists (skip initial 1.0 anchor, pair with dates)
    def to_points(equity_list, date_list):
        return [{"date": d, "value": v} for d, v in zip(date_list, equity_list[1:])]

    strategies = [
        {"name": "WDL",  "color": "#00F0FF", "points": to_points(wdl_equity,  dates)},
        {"name": "OU",   "color": "#FF00E5", "points": to_points(ou_equity,   dates)},
        {"name": "合成", "color": "#00ffb7", "points": to_points(comb_equity, dates)},
    ]

    all_returns = wdl_returns + ou_returns
    sharpe = _sharpe(all_returns)
    max_dd = _max_drawdown(wdl_equity + ou_equity)

    return {
        "strategies": strategies,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
    }


def main(dry_run=False):
    conn = sqlite3.connect(DB)
    cur  = conn.cursor()

    cutoff = (date.today() - timedelta(days=365)).isoformat()

    # Use prediction_audit's own closing odds (odds_final_*) for WDL — always available.
    # For OU, fall back to raw_footballdata_odds where available, else NULL.
    # Use prediction_audit's own closing odds (odds_final_*) for WDL — always available.
    # For OU, fall back to raw_footballdata_odds where available, else NULL.
    cur.execute("""
        SELECT
            pa.match_date,
            pa.wdl_correct,
            pa.ou_correct,
            pa.pred_wdl_home,
            pa.pred_ou_over,
            pa.pred_wdl_pick,
            COALESCE(pa.odds_final_home, o.B365H)   AS o_home,
            COALESCE(pa.odds_final_draw, o.B365D)   AS o_draw,
            COALESCE(pa.odds_final_away, o.B365A)   AS o_away,
            "o"."B365>2.5"                          AS o_over,
            "o"."B365<2.5"                          AS o_under,
            pa.pred_ah_pick,
            pa.ah_correct,
            pa.pred_ah_line,
            o.B365AHH,
            o.B365AHA
        FROM prediction_audit pa
        LEFT JOIN raw_footballdata_odds o
          ON pa.home_name = o.HomeTeam
         AND pa.away_name = o.AwayTeam
         AND substr(pa.match_date,1,10) = substr(o.Date,1,10)
        WHERE pa.match_date >= ?
          AND pa.wdl_correct IS NOT NULL
        ORDER BY pa.match_date
    """, (cutoff,))
    rows = cur.fetchall()
    print(f"Backtest rows: {len(rows)}")

    if dry_run:
        print("--- DRY RUN: Fixed Stake ---")
        result = _build_curves(rows, "fixed")
        for s in result["strategies"]:
            pts = s["points"]
            print(f"  {s['name']}: {len(pts)} points, final={pts[-1]['value'] if pts else 'N/A'}")
        print(f"  Sharpe={result['sharpe']}, MaxDD={result['max_drawdown']}")

        print("--- DRY RUN: Kelly-Half ---")
        result = _build_curves(rows, "kelly_half")
        for s in result["strategies"]:
            pts = s["points"]
            print(f"  {s['name']}: {len(pts)} points, final={pts[-1]['value'] if pts else 'N/A'}")
        print(f"  Sharpe={result['sharpe']}, MaxDD={result['max_drawdown']}")
        conn.close()
        return

    fixed_result  = _build_curves(rows, "fixed")
    kelly_result  = _build_curves(rows, "kelly_half")
    now_iso       = datetime.utcnow().isoformat() + "Z"

    # Build output JSON (new schema; keep backward-compat strategies field for StrategyEquityChart)
    output = {
        "generated_at": now_iso,
        "description": "模型回测净值曲线 (Fixed Stake & Kelly-Half)",
        "period": {
            "start": rows[0][0] if rows else cutoff,
            "end":   rows[-1][0] if rows else date.today().isoformat(),
        },
        "equity": {
            "fixed":      fixed_result,
            "kelly_half": kelly_result,
            "updated_at": now_iso,
        },
        # Legacy field kept for StrategyEquityChart backward compat
        "strategies": {
            s["name"]: [{"date": p["date"], "cumPnl": (p["value"] - 1.0) * 10000}
                        for p in s["points"]]
            for s in fixed_result["strategies"]
        },
        "meta": {
            s["name"]: {
                "label": s["name"],
                "total_bets": len(s["points"]),
                "final_pnl": round((s["points"][-1]["value"] - 1.0) * 10000, 2) if s["points"] else 0,
            }
            for s in fixed_result["strategies"]
        },
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Written to {OUTPUT_JSON}")

    # Update model_health_log with today's snapshot
    today = date.today().isoformat()
    wdl_pts = fixed_result["strategies"][0]["points"]
    ou_pts  = fixed_result["strategies"][1]["points"]
    wdl_acc = sum(1 for r in rows if r[1] == 1) / len(rows) if rows else 0
    ou_acc  = sum(1 for r in rows if r[2] == 1) / len(rows) if rows else 0
    n       = len(rows)

    cur.execute("""
        INSERT OR REPLACE INTO model_health_log
          (log_date, window_size, wdl_accuracy, ou_accuracy, total_matches)
        VALUES (?, ?, ?, ?, ?)
    """, (today, 365, wdl_acc, ou_acc, n))
    conn.commit()
    conn.close()
    print(f"model_health_log updated for {today}: WDL={wdl_acc:.3f} OU={ou_acc:.3f} n={n}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
