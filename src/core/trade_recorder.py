import csv
import os
import logging
from datetime import datetime
from decimal import Decimal

logger = logging.getLogger(__name__)

class TradeRecorder:
    """
    Records simulated or real trades to a CSV file for analysis.
    """
    def __init__(self, filename="data/sim_trades.csv"):
        self.filename = filename
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        """Create CSV with headers if it doesn't exist"""
        os.makedirs(os.path.dirname(self.filename), exist_ok=True)
        
        if not os.path.exists(self.filename):
            with open(self.filename, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'pair_name', 'action', 
                    'price_a', 'price_b', 'z_score', 
                    'ai_confidence', 'ai_reason', 
                    'status', 'pnl'
                ])

    def log_entry(self, pair_name, action, price_a, price_b, z_score, ai_result):
        """Log a trade entry"""
        try:
            with open(self.filename, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().isoformat(),
                    pair_name,
                    action,
                    f"{price_a:.4f}",
                    f"{price_b:.4f}",
                    f"{z_score:.2f}",
                    f"{ai_result.get('confidence', 0):.2f}",
                    ai_result.get('reasoning', 'N/A').replace('\n', ' '),
                    'OPEN',
                    0.0
                ])
            logger.info(f"📝 Simulation Record Saved: {pair_name}")
        except Exception as e:
            logger.error(f"❌ Failed to log trade: {e}")

    def log_exit(self, pair_name, entry_price_a, entry_price_b, exit_price_a, exit_price_b, action):
        """
        Calculate and log PnL for a closed position.
        PnL logic: 
        - Long A: ExitA - EntryA
        - Short B: EntryB - ExitB
        """
        try:
            # Ensure float conversion
            entry_a, entry_b = float(entry_price_a), float(entry_price_b)
            exit_a, exit_b = float(exit_price_a), float(exit_price_b)
            
            pnl_a = 0
            pnl_b = 0
            
            if "LONG A" in action:
                # Buy A low, Sell A high
                pnl_a = exit_a - entry_a
                # Sell B high, Buy B low (Short)
                pnl_b = entry_b - exit_b
            elif "SHORT A" in action:
                # Sell A high, Buy A low (Short)
                pnl_a = entry_a - exit_a
                # Buy B low, Sell B high
                pnl_b = exit_b - entry_b
                
            total_pnl = pnl_a + pnl_b
            
            with open(self.filename, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().isoformat(),
                    pair_name,
                    "CLOSE",
                    f"{exit_a:.4f}",
                    f"{exit_b:.4f}",
                    "0.00", 
                    "N/A",
                    "Mean Reversion Exit",
                    'CLOSED',
                    f"{total_pnl:.4f}"
                ])
            logger.info(f"💰 Trade Closed. PnL: {total_pnl:.4f}")
            
        except Exception as e:
            logger.error(f"❌ Failed to log exit: {e}")

    def log_completed_trade(self, trade_data: dict, filename="data/trades_log.csv"):
        """
        Log a fully completed trade with rich metadata for analysis.
        Standardize fields for specialized analysis.
        """
        try:
            # Ensure dir exists
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            
            # Define headers
            headers = [
                'timestamp', 'market_question', 'tags', 'strategy', 
                'side', 'entry_price', 'exit_price', 'size', 
                'pnl', 'pnl_pct', 'reason'
            ]
            
            file_exists = os.path.exists(filename)
            
            with open(filename, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                if not file_exists:
                    writer.writeheader()
                
                # Filter/Prepare data
                row = {k: trade_data.get(k, '') for k in headers}
                # Ensure timestamp
                if not row['timestamp']: 
                    row['timestamp'] = datetime.now().isoformat()
                
                writer.writerow(row)
                
            logger.info(f"💾 Trade logged to {filename} (PnL: {trade_data.get('pnl', 0):.2f})")
            
        except Exception as e:
            logger.error(f"❌ Failed to log completed trade: {e}")
