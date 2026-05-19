"""
bankroll_simulator.py
=====================
资金管理 + 盈亏模拟器
"""

import sqlite3
import json
import math
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

KELLY_FRACTION = {'HIGH': 0.30, 'MEDIUM': 0.15, 'LOW': 0.00}
MAX_BET_RATIO = 0.05
MIN_EDGE_THRESHOLD = 0.03

@dataclass
class BetDecision:
    match_id: str
    match_name: str
    bet_type: str
    bet_pick: str
    ml_prob: float
    market_odds: float
    implied_prob: float
    edge: float
    confidence: str
    kelly_full: float
    kelly_actual: float
    bet_amount: float
    skip_reason: str = ''

@dataclass
class MatchResult:
    decision: BetDecision
    actual_outcome: str
    is_win: bool
    pnl: float
    bankroll_after: float

class KellyEngine:
    @staticmethod
    def calculate_kelly(p, o):
        if o <= 1.0 or p <= 0 or p >= 1: return 0.0
        b = o - 1
        q = 1 - p
        return max((p * b - q) / b, 0.0)

    @staticmethod
    def calculate_bet_size(kf, conf, bank, edge):
        if edge < MIN_EDGE_THRESHOLD: return 0.0
        ka = kf * KELLY_FRACTION.get(conf, 0.0)
        ka = min(ka, MAX_BET_RATIO)
        return round(bank * ka, 2)

class BetAdvisor:
    def __init__(self): self.kelly = KellyEngine()
    def advise(self, mid, name, ml, odds, bank):
        decisions = []
        wdl, ou, conf = ml['wdl_prob'], ml['ou_prob'], ml['confidence']
        
        # WDL
        candidates = []
        om = {'home_win': odds.get('eu_home', 0), 'draw': odds.get('eu_draw', 0), 'away_win': odds.get('eu_away', 0)}
        for dr, o in om.items():
            if o <= 1.0: continue
            ml_p = wdl[dr]
            ep = 1/o
            edge = ml_p - ep
            if edge > 0:
                kf = self.kelly.calculate_kelly(ml_p, o)
                amt = self.kelly.calculate_bet_size(kf, conf['wdl'], bank, edge)
                candidates.append(BetDecision(mid, name, 'wdl', dr, ml_p, o, ep, edge, conf['wdl'], kf, amt/bank if bank>0 else 0, amt))
        if candidates: decisions.append(max(candidates, key=lambda x: x.edge))
        
        # O/U
        pk = 'over' if ou['over'] > 0.5 else 'under'
        o_o = odds.get('ou_over', 0) if pk == 'over' else odds.get('ou_under', 0)
        if o_o > 1.0:
            ml_p = ou[pk]
            ep = 1/o_o
            edge = ml_p - ep
            kf = self.kelly.calculate_kelly(ml_p, o_o) if edge > 0 else 0
            amt = self.kelly.calculate_bet_size(kf, conf['ou'], bank, edge) if edge > 0 else 0
            decisions.append(BetDecision(mid, name, 'ou', pk, ml_p, o_o, ep, edge, conf['ou'], kf, amt/bank if bank>0 else 0, amt))
        return decisions

class BacktestSimulator:
    def __init__(self, db_path):
        self.db_path = db_path
        self.advisor = BetAdvisor()

    def run(self, initial_bankroll=10000.0, start_date=None, end_date=None):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        # Refactored JOIN logic
        query = """
            SELECT pa.*, 
                   fo.eu_home, fo.eu_draw, fo.eu_away,
                   fo.ou_over, fo.ou_under
            FROM prediction_audit pa
            LEFT JOIN (
                SELECT dm.Match_ID, 
                       o."B365H" as eu_home, o."B365D" as eu_draw, o."B365A" as eu_away,
                       o."B365>2.5" as ou_over, o."B365<2.5" as ou_under
                FROM raw_footballdata_odds o
                JOIN dim_match dm ON o.HomeTeam = dm.Home_Team_Name 
                    AND o.AwayTeam = dm.Away_Team_Name AND o.Date = dm.Date
            ) fo ON pa.match_id = fo.Match_ID
            WHERE pa.actual_wdl IS NOT NULL
        """
        params = []
        if start_date: query += " AND pa.match_date >= ?"; params.append(start_date)
        if end_date: query += " AND pa.match_date <= ?"; params.append(end_date)
        query += " ORDER BY pa.match_date ASC"

        matches = conn.execute(query, params).fetchall()
        conn.close()
        
        bankroll = initial_bankroll
        all_results = []
        for m in matches:
            mid, name = m['match_id'], f"{m['home_name']} vs {m['away_name']}"
            ml = {'wdl_prob': {'home_win': m['pred_wdl_home'], 'draw': m['pred_wdl_draw'], 'away_win': m['pred_wdl_away']},
                  'ou_prob': {'over': m['pred_ou_over'], 'under': 1 - m['pred_ou_over']},
                  'confidence': {'wdl': m['confidence_wdl'], 'ou': m['confidence_ou']}}
            odds = {'eu_home': m['eu_home'] or 0, 'eu_draw': m['eu_draw'] or 0, 'eu_away': m['eu_away'] or 0, 'ou_over': m['ou_over'] or 0, 'ou_under': m['ou_under'] or 0}
            
            if not any(odds.values()): continue
            decisions = self.advisor.advise(mid, name, ml, odds, bankroll)
            for d in decisions:
                if d.bet_amount <= 0: continue
                is_win = (d.bet_pick == m['actual_wdl']) if d.bet_type == 'wdl' else (d.bet_pick == m['actual_ou'])
                pnl = d.bet_amount * (d.market_odds - 1) if is_win else -d.bet_amount
                bankroll += pnl
                all_results.append(MatchResult(d, m['actual_wdl'] if d.bet_type == 'wdl' else m['actual_ou'], is_win, round(pnl, 2), round(bankroll, 2)))
        
        return {'final_bankroll': bankroll, 'total_bets': len(all_results)}

def print_backtest_report(result):
    print(f"Final Bankroll: ¥{result['final_bankroll']:,.2f}, Total Bets: {result['total_bets']}")
