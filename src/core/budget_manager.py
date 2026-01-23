"""
Global Budget Manager - Memory-based Wallet Coordination
========================================================

Prevents race conditions when multiple agents share a single capital pool.
Optimized for Swarm System (Single Process).

Architecture:
- In-memory state (asyncio.Lock)
- Strategy-based allocation (40% ArbHunter, 35% StatArb, 25% EliteMimic)
- Reserve buffer (10%) for high-priority opportunities

Author: ArbHunter V2.0 Upgrade (Swarm Edition)
Created: 2026-01-06
"""

import asyncio
import time
import logging
from typing import Optional, Dict
from decimal import Decimal
from datetime import datetime
import os

logger = logging.getLogger(__name__)


class BudgetManager:
    """
    Centralized budget coordinator using In-Memory locking.
    Optimized for 'Unified Sniper Pool' mode.
    All strategies share a single capital pool.
    """

    def __init__(self, total_capital: float = 1000.0):
        # State
        self.total_capital = Decimal(str(total_capital))
        # Allocations: ID -> (Amount, Strategy)
        self.allocations: Dict[str, Tuple[Decimal, str]] = {} 
        self.locked_funds = Decimal("0") # Total currently allocated
        self._lock = asyncio.Lock()
        # Strategy Weights (Task 11: Multi-Strategy Weighting)
        # Default allocation caps
        self.strategy_weights = {
            "news_scalper": Decimal("0.40"),
            "statarb": Decimal("0.35"),
            "elitemimic": Decimal("0.25")
        }
        
        # Load min order value
        self.min_order_value = Decimal(str(os.getenv("MIN_ORDER_VALUE_USD", "1.0")))
        
        logger.info(f"💰 BudgetManager initialized with Unified Pool: ${self.total_capital:.2f}")
        logger.info(f"⚖️  Weights: News={self.strategy_weights['news_scalper']:.0%}, StatArb={self.strategy_weights['statarb']:.0%}, Mimic={self.strategy_weights['elitemimic']:.0%}")

    @property
    def is_low_capital(self) -> bool:
        """Check if available capital is below minimum order size"""
        return (self.total_capital - self.locked_funds) < self.min_order_value

    async def sync_with_real_pnl(self, realized_pnl: float, base_equity: float):
        """
        Synchronize total capital based on actual realized PnL.
        Total Capital = Base Equity + Realized PnL
        """
        async with self._lock:
            old_capital = self.total_capital
            self.total_capital = Decimal(str(base_equity)) + Decimal(str(realized_pnl))
            
            if self.total_capital != old_capital:
                logger.info(f"🔄 Budget Sync: ${old_capital:.2f} -> ${self.total_capital:.2f} (PnL: ${realized_pnl:+.2f})")

    async def connect(self):
        """Mock method for compatibility"""
        pass

    async def request_allocation(
        self,
        strategy: str,
        amount: Decimal,
        priority: str = "normal",
        confidence: float = 1.0 
    ) -> Optional[str]:
        """
        Request capital allocation from the shared pool.
        """
        async with self._lock:
            # Re-calculate available liquid funds
            # Available = Total - Locked
            available_funds = self.total_capital - self.locked_funds
            
            # 1. Sanity Check
            if available_funds < 0:
                available_funds = Decimal("0")

            # 2. Weighted Cap Check (Task 11)
            strategy_weight = self.strategy_weights.get(strategy, Decimal("0.1"))
            # For News Scalper, we might call it 'news_scalper' or 'arbhunter' (legacy)
            if strategy == "arbhunter": strategy_weight = self.strategy_weights.get("news_scalper")
            
            strategy_cap = self.total_capital * strategy_weight
            
            # Calculate current usage for this strategy
            current_usage = sum(amt for amt, s in self.allocations.values() if s == strategy or (s == "arbhunter" and strategy == "news_scalper"))
            
            if current_usage + amount > strategy_cap and priority != "high":
                logger.warning(f"⚠️  {strategy} cap reached (${strategy_cap:.2f}). Denying normal priority request.")
                return None

            # 3. Check Affordability
            if amount > available_funds:
                logger.warning(f"❌ Allocation Denied ({strategy}): Requested ${amount:.2f} > Avail ${available_funds:.2f}")
                return None

            # 3. Approve
            self.locked_funds += amount
            
            allocation_id = f"{strategy}:{time.time()}"
            # Store tuple (Amount, Owner) for validation
            self.allocations[allocation_id] = (amount, strategy)
            
            logger.info(f"✅ Allocation Approved ({strategy}): ${amount:.2f} | Remaining Pool: ${available_funds - amount:.2f}")
            return allocation_id

    async def release_allocation(
        self,
        strategy: str,
        allocation_id: str,
        actual_spent: Decimal
    ):
        """
        Return unused funds to the pool.
        Includes security check to ensure strategy owns the allocation.
        """
        async with self._lock:
            if allocation_id not in self.allocations:
                logger.debug(f"⚠️ Release ignored: Allocation {allocation_id} not found.")
                return

            allocated_amount, owner_strategy = self.allocations[allocation_id]
            
            # Security Check: Prevent Strategy A from releasing Strategy B's lock
            if owner_strategy != strategy:
                logger.error(f"🚨 Security Violation: {strategy} tried to release {owner_strategy}'s allocation {allocation_id}!")
                return

            # Clean up
            del self.allocations[allocation_id]
            
            self.locked_funds -= allocated_amount
            
            # Safety clamp
            if self.locked_funds < 0:
                self.locked_funds = Decimal("0")

            logger.info(f"🔓 Released Allocation {allocation_id} (Orig: ${allocated_amount:.2f}, Spent: ${actual_spent:.2f})")

    async def get_balances(self) -> Dict[str, Decimal]:
        """
        Get logical balances.
        For Unified mode, we report the same 'Available' for all strategies
        to indicate they have access to the pool.
        """
        async with self._lock:
            available = max(self.total_capital - self.locked_funds, Decimal("0"))
            return {
                "unified": available,
                "arbhunter": available,
                "statarb": available,
                "elitemimic": available,
                "reserve": available
            }

    async def get_status(self) -> dict:
        async with self._lock:
            available = max(self.total_capital - self.locked_funds, Decimal("0"))
            return {
                "total_capital": float(self.total_capital),
                "locked": float(self.locked_funds),
                "available": float(available),
                "balances": {
                    "unified_pool": float(available)
                }
            }

    def update_total_capital(self, new_total: float):
        """Called by orchestrator to sync with real wallet balance"""
        self.total_capital = Decimal(str(new_total))
