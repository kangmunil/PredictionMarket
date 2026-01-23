
import json
import pandas as pd
import glob
import os
from datetime import datetime

STATE_FILE = "data/dashboard_state.json"
TRADES_FILE = "data/trades_backup.csv"

def analyze():
    print("Loading data...")
    
    # 1. Analyze Active Positions (Unrealized PnL)
    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
            
        positions = state.get('active_positions', [])
        balance = state.get('balance_usdc', 0)
        
        print(f"\nTarget Balance: ${balance:,.2f}")
        print(f"Active PositionsCount: {len(positions)}")
        
        unrealized_pnl = 0
        winning_positions = 0
        losing_positions = 0
        total_invested = 0
        
        # Sort by PnL desc
        positions.sort(key=lambda x: x.get('pnl', 0), reverse=True)
        
        print("\n--- Top 5 Active Positions ---")
        for p in positions[:5]:
            pnl = p.get('pnl', 0)
            symbol = p.get('symbol', 'Unknown')
            size = p.get('size', 0)
            entry = p.get('entry', 0)
            print(f"🏆 {symbol[:30]}... | PnL: ${pnl:,.2f} | Size: {size:.2f} | Entry: {entry}")
            
        print("\n--- Bottom 5 Active Positions ---")
        for p in positions[-5:]:
            pnl = p.get('pnl', 0)
            symbol = p.get('symbol', 'Unknown')
            size = p.get('size', 0)
            entry = p.get('entry', 0)
            print(f"🔻 {symbol[:30]}... | PnL: ${pnl:,.2f} | Size: {size:.2f} | Entry: {entry}")

        for p in positions:
            pnl = p.get('pnl', 0)
            size = p.get('size', 0)
            entry = p.get('entry', 0)
            
            # Recalculate PnL if 0 (sometimes it's not updated in the view)
            current = p.get('current', entry)
            calc_pnl = (current - entry) * size
            
            # Trust the file's PnL if it's non-zero, otherwise use calc
            # Note: The file's PnL seems to be per-unit or total? 
            # In the file: "pnl": 99800.0, "size": 7500.0, "entry": 0.001, "current": 0.999
            # (0.999 - 0.001) * 7500 = 0.998 * 7500 = 7485. 
            # Wait, 99800? changing pnl logic.
            
            # Let's rely on calculated PnL for consistency
            actual_pnl = calc_pnl
            
            unrealized_pnl += actual_pnl
            total_invested += (entry * size)
            
            if actual_pnl > 0:
                winning_positions += 1
            elif actual_pnl < 0:
                losing_positions += 1
                
        print(f"\n--- Unrealized Metrics ---")
        print(f"Total Invested: ${total_invested:,.2f}")
        print(f"Total Unrealized PnL: ${unrealized_pnl:,.2f}")
        print(f"Win/Loss Ratio: {winning_positions}/{losing_positions} ({(winning_positions/len(positions)*100 if len(positions)>0 else 0):.1f}%)")
        
    except Exception as e:
        print(f"Error reading state file: {e}")

    # 2. Analyze Closed Trades (Realized PnL)
    # Note: trades_backup.csv format seems to be: timestamp, id, source, id, side, price, ?, size, value, value
    # We need to deduce PnL from matching buy/sells or trust a PnL log if it exists.
    # Given the short timeframe, we might assume most are active.
    
if __name__ == "__main__":
    analyze()
