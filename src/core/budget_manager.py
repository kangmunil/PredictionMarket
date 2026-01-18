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
    Optimized for 'Unified Sniper Pool' mode.
    All strategies share a single capital pool.
    """

    def __init__(self, total_capital: float = 1000.0):
        # State
        self.total_capital = Decimal(str(total_capital))
        self.allocations: Dict[str, Decimal] = {} # active allocations (ID -> Amount)
        self.locked_funds = Decimal("0") # Total currently allocated
        self._lock = asyncio.Lock()
        
        logger.info(f"💰 BudgetManager initialized with Unified Pool: ${self.total_capital:.2f}")

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

            # 2. Check Affordability
            if amount > available_funds:
                logger.warning(f"❌ Allocation Denied ({strategy}): Requested ${amount:.2f} > Avail ${available_funds:.2f}")
                return None

            # 3. Approve
            self.locked_funds += amount
            
            allocation_id = f"{strategy}:{time.time()}"
            self.allocations[allocation_id] = amount
            
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
        """
        async with self._lock:
            if allocation_id not in self.allocations:
                return

            allocated_amount = self.allocations.pop(allocation_id)
            
            # Since we just track "locked" vs "free", we verify what happened
            # If we allocated $10 and spent $5:
            # Locked decreases by $10 (the reservation is gone)
            # Total Capital decreases by $5 (the money is gone/converted to asset)
            # Wait, BudgetManager tracks "Cash". 
            # If I spent $5, I have $5 less cash.
            # So Total Capital should be updated? 
            # Usually BudgetManager tracks 'Allowable Spend'. 
            # Let's keep it simple: We just unlock the amount. 
            # The 'actual_spent' argument implies the caller used some.
            # If we used it, it's no longer 'free cash'.
            # BUT, the PnL/Balance sync (hydrate) updates self.total_capital separately usually.
            
            # For this simple manager:
            # We treat 'allocations' as temporary reservations.
            # When released, we assume the transaction is done.
            # We decrement locked_funds by the original allocated amount.
            # We update total_capital based on "unused" part? No.
            # The calling agents (clob_client) don't update budget manager with PnL.
            # run_swarm.py updates total_capital via _hydrate or fetching balance.
            # So here, we simply release the lock.
            
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
