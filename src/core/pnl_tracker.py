"""
Unified P&L Logger
===================

Centralized tracker for realized Profit & Loss across all swarm strategies.
Tracks trade lifecycle (Entry -> Exit) and calculates performance metrics.

Author: Swarm Architect
Created: 2026-01-07
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass
from decimal import Decimal

logger = logging.getLogger(__name__)

@dataclass
class TradeEntry:
    trade_id: str
    strategy: str
    token_id: str
    side: str # BUY/SELL
    entry_price: float
    size: float
    entry_time: datetime
    
@dataclass
class TradeExit:
    trade_id: str
    exit_price: float
    exit_time: datetime
    pnl_amount: float
    pnl_percent: float
    reason: str

class PnLTracker:
    def __init__(self):
        self.active_trades: Dict[str, TradeEntry] = {}
        self.history: List[Dict] = []
        self.total_realized_pnl = 0.0
        self.strategy_pnl = {
            "arbhunter": 0.0,
            "statarb": 0.0,
            "elitemimic": 0.0,
            "news_scalper": 0.0
        }

    def record_entry(self, strategy: str, token_id: str, side: str, price: float, size: float) -> str:
        """
        Record a new trade entry. Returns a trade_id.
        """
        trade_id = f"{strategy}_{token_id}_{datetime.now().timestamp()}"
        entry = TradeEntry(
            trade_id=trade_id,
            strategy=strategy,
            token_id=token_id,
            side=side,
            entry_price=float(price),
            size=float(size),
            entry_time=datetime.now()
        )
        self.active_trades[trade_id] = entry
        logger.info(f"📝 [PnL] Entry Recorded: {strategy} {side} {token_id[:10]} @ ${price:.3f} (${size:.2f})")
        return trade_id

    def record_exit(self, trade_id: str, exit_price: float, reason: str = "Signal Close"):
        """
        Record a trade exit and calculate P&L.
        """
        entry = self.active_trades.get(trade_id)
        if not entry:
            logger.warning(f"⚠️ [PnL] Exit for unknown trade: {trade_id}")
            return

        exit_price = float(exit_price)
        
        # Calculate P&L
        # Long (BUY): (Exit - Entry) / Entry * Size
        # Short (SELL): (Entry - Exit) / Entry * Size (Assuming borrowing/shorting mechanics, 
        # but in Polymarket SELL usually means selling owned shares. 
        # If we 'SHORT' via 'NO', we 'BUY NO'. 
        # Here we assume side='BUY' means Long the outcome token. 
        # If we SELL the token we own: PnL = (Exit - Entry) * Shares
        # Shares = Size / Entry
        
        shares = entry.size / entry.entry_price if entry.entry_price > 0 else 0
        
        if entry.side.upper() == "BUY":
            pnl_amount = (exit_price - entry.entry_price) * shares
        else:
            # If we "Sold" to open (Short), profit if price drops
            # PnL = (Entry - Exit) * Shares
            pnl_amount = (entry.entry_price - exit_price) * shares

        pnl_percent = (pnl_amount / entry.size) * 100 if entry.size > 0 else 0.0

        # Update stats
        self.total_realized_pnl += pnl_amount
        if entry.strategy in self.strategy_pnl:
            self.strategy_pnl[entry.strategy] += pnl_amount
        
        # Archive
        record = {
            "trade_id": trade_id,
            "strategy": entry.strategy,
            "token_id": entry.token_id,
            "side": entry.side,
            "entry_price": entry.entry_price,
            "exit_price": exit_price,
            "size": entry.size,
            "pnl": pnl_amount,
            "pnl_pct": pnl_percent,
            "entry_time": entry.entry_time.isoformat(),
            "exit_time": datetime.now().isoformat(),
            "reason": reason
        }
        self.history.append(record)
        del self.active_trades[trade_id]

        logger.info(f"💰 [PnL] Exit Recorded: {entry.strategy} | PnL: ${pnl_amount:+.2f} ({pnl_percent:+.2f}%) | Total: ${self.total_realized_pnl:+.2f}")
        return pnl_amount

    def calculate_unrealized_pnl(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total unrealized PnL for all active positions.
        Args:
            current_prices: Dict mapping token_id -> current market price
        """
        total_unrealized = 0.0
        
        for trade_id, entry in self.active_trades.items():
            current_price = current_prices.get(entry.token_id)
            
            if current_price is None:
                # If price unavailable, assume no change (0 unrealized)
                # logger.debug(f"Price missing for {entry.token_id}, skipping unrealized calc")
                continue
                
            shares = entry.size / entry.entry_price if entry.entry_price > 0 else 0
            
            if entry.side.upper() == "BUY":
                # Long: (Current - Entry) * Shares
                trade_pnl = (current_price - entry.entry_price) * shares
            else:
                # Short: (Entry - Current) * Shares
                trade_pnl = (entry.entry_price - current_price) * shares
                
            total_unrealized += trade_pnl
            
        return total_unrealized

    def get_summary(self) -> Dict:
        return {
            "total_pnl": self.total_realized_pnl,
            "strategy_breakdown": self.strategy_pnl,
            "open_positions": len(self.active_trades),
            "closed_trades": len(self.history)
        }
