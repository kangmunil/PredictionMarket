import csv
import pandas as pd
import numpy as np
from datetime import datetime

# Correct headers for the data rows
HEADERS = [
    'timestamp', 'market_question', 'tags', 'strategy', 
    'side', 'entry_price', 'exit_price', 'size', 
    'pnl', 'pnl_pct', 'reason'
]

def analyze_trades():
    file_path = 'data/trades_log.csv'
    
    try:
        # Read with correct headers, skipping the first row (bad header)
        df = pd.read_csv(file_path, names=HEADERS, skiprows=1)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    print(f"Loaded {len(df)} trades.")
    
    # Filter valid trades (ignore rows where pnl is empty or NaN)
    df = df.dropna(subset=['pnl'])
    
    # Convert numeric columns safely
    numeric_cols = ['entry_price', 'exit_price', 'size', 'pnl', 'pnl_pct']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        
    # 1. Overall Stats
    total_trades = len(df)
    winning_trades = df[df['pnl'] > 0]
    losing_trades = df[df['pnl'] <= 0]
    
    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0
    total_pnl = df['pnl'].sum()
    
    print("\n" + "="*50)
    print("📊 TRADE ANALYSIS REPORT")
    print("="*50)
    print(f"Total Trades: {total_trades}")
    print(f"Win Rate:     {win_rate:.2f}%")
    print(f"Total PnL:    ${total_pnl:,.2f}  (Includes Sim Data)")
    print(f"Winners:      {len(winning_trades)}")
    print(f"Losers:       {len(losing_trades)}")
    
    # 2. Loss Analysis
    print("\n" + "="*50)
    print("📉 LOSS ANALYSIS")
    print("="*50)
    
    if not losing_trades.empty:
        # Group by reason
        loss_reasons = losing_trades['reason'].value_counts()
        print("\nTop Reasons for Loss:")
        print(loss_reasons)
        
        # Avg loss duration (if timestamp exists)
        # TODO: Calculate hold time if exit ts was available, but we only have 1 timestamp.
        # Check reasons for 'Timeout' or 'Stop-Loss'
        
        timeouts = losing_trades[losing_trades['reason'].str.contains("Max hold", case=False, na=False)]
        pnl_timeouts = timeouts['pnl'].sum()
        print(f"\nLosses due to Timeout: {len(timeouts)} (PnL: ${pnl_timeouts:,.2f})")
        
        stops = losing_trades[losing_trades['reason'].str.contains("Stop-Loss", case=False, na=False)]
        pnl_stops = stops['pnl'].sum()
        print(f"Losses due to Stop-Loss: {len(stops)} (PnL: ${pnl_stops:,.2f})")
        
        shutdowns = losing_trades[losing_trades['reason'].str.contains("Shutdown", case=False, na=False)]
        print(f"Positions Closed on Shutdown: {len(shutdowns)}")

    # 3. Recommendations
    print("\n" + "="*50)
    print("💡 INSIGHTS")
    print("="*50)
    if not losing_trades.empty:
        if len(timeouts) > len(stops):
            print("• OBSERVATION: Most losses are from Timeouts (Max Hold).")
            print("  INSIGHT: The 1.5h hold time might be too short for these markets to mature,")
            print("           OR the entry logic selects low-momentum markets.")
        if len(shutdowns) > 0:
            print(f"• OBSERVATION: {len(shutdowns)} trades closed due to Bot Shutdown/Restart.")
            print("  INSIGHT: Frequent improvements/restarts are affecting PnL.")

if __name__ == "__main__":
    analyze_trades()
