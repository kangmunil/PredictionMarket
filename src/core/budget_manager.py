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

logger = logging.getLogger(__name__)


class BudgetManager:
    """
    Centralized budget coordinator using In-Memory locking.
    Ideal for run_swarm.py single-process architecture.
    """

    def __init__(self, total_capital: float = 1000.0):
        # Strategy allocation percentages (total 90%, 10% reserve)
        self.allocations_pct = {
            "arbhunter": 0.40,    # 40% - High frequency needs capital
            "statarb": 0.35,      # 35% - Medium conviction trades (Renamed from polyai)
            "elitemimic": 0.25    # 25% - Copy trading
        }
        self.reserve_buffer_pct = 0.10

        # State
        self.total_capital = Decimal(str(total_capital))
        self.balances: Dict[str, Decimal] = {}
        self.allocations: Dict[str, Decimal] = {} # active allocations
        self._lock = asyncio.Lock()
        
        # Initialize
        self._initialize_budgets()

    def _initialize_budgets(self):
        """Distribute capital according to percentages"""
        # Reserve
        self.reserve_balance = self.total_capital * Decimal(str(self.reserve_buffer_pct))
        remaining_capital = self.total_capital - self.reserve_balance
        
        # Distribute
        for strategy, pct in self.allocations_pct.items():
            amount = remaining_capital * Decimal(str(pct))
            self.balances[strategy] = amount
            logger.info(f"💰 {strategy}: ${amount:.2f} ({pct*100:.0f}%)")
        
        logger.info(f"💰 Reserve: ${self.reserve_balance:.2f} ({self.reserve_buffer_pct*100:.0f}%)")

    async def connect(self):
        """Mock method for compatibility"""
        pass

    async def request_allocation(
        self,
        strategy: str,
        amount: Decimal,
        priority: str = "normal"
    ) -> Optional[str]:
        """
        Request capital allocation.
        """
        async with self._lock:
            if strategy not in self.balances:
                logger.warning(f"⚠️ Unknown strategy: {strategy}")
                return None

            current_balance = self.balances[strategy]
            
            # 1. Check Strategy Budget
            if amount <= current_balance:
                self.balances[strategy] -= amount
                
                allocation_id = f"{strategy}:{time.time()}"
                self.allocations[allocation_id] = amount
                
                logger.info(f"✅ Allocation Approved ({strategy}): ${amount:.2f}")
                return allocation_id

            # 2. Check Reserve (High Priority Only)
            if priority in ["high", "critical"]:
                if amount <= current_balance + self.reserve_balance:
                    deficit = amount - current_balance
                    self.reserve_balance -= deficit
                    self.balances[strategy] = Decimal("0") # Drained strategy budget
                    
                    allocation_id = f"{strategy}:{time.time()}"
                    self.allocations[allocation_id] = amount
                    
                    logger.warning(f"🚨 Reserve Used for {strategy}: ${deficit:.2f}")
                    return allocation_id

            logger.warning(f"❌ Allocation Denied ({strategy}): Requested ${amount:.2f}, Avail ${current_balance:.2f}")
            return None

    async def release_allocation(
        self,
        strategy: str,
        allocation_id: str,
        actual_spent: Decimal
    ):
        """
        Return unused funds.
        """
        async with self._lock:
            if allocation_id not in self.allocations:
                return

            allocated = self.allocations.pop(allocation_id)
            unused = allocated - actual_spent
            
            if unused > 0:
                if strategy in self.balances:
                    self.balances[strategy] += unused
                    logger.info(f"💸 Returned ${unused:.2f} to {strategy}")

    async def get_status(self) -> dict:
        return {
            "total_capital": float(self.total_capital),
            "reserve": float(self.reserve_balance),
            "balances": {k: float(v) for k, v in self.balances.items()}
        }