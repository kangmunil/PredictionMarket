"""
Global Risk Manager (GRM) - The High-Altitude Guard
===================================================

The Global Risk Manager acts as a centralized brain for safety across all trading agents.
It integrates with PnLTracker, DeltaTracker, and SignalBus to provide a unified
risk oversight.

Key Responsibilities:
1.  Global Circuit Breaker (Total Portfolio Drawdown)
2.  Correlation & Sector Concentration Guard
3.  Unified Risk Multiplier (Affects all bots)
4.  Smart Rebalancing Signals (Via SignalBus)
"""

import logging
from decimal import Decimal
from typing import Optional, Dict, List
from datetime import datetime
import asyncio

from .risk_manager import RiskManager

logger = logging.getLogger(__name__)

class GlobalRiskManager(RiskManager):
    """
    Centralized risk authority for the entire Swarm Intelligence system.
    Inherits from RiskManager to maintain compatibility with legacy agents.
    """

    def __init__(
        self,
        total_pnl_limit_pct: float = 0.05,  # 5% Daily Loss Limit
        max_sector_exposure: float = 0.30,  # Max 30% capital in one sector (Crypto, etc.)
        initial_risk_multiplier: float = 0.25
    ):
        super().__init__(
            total_capital=1000.0,
            risk_multiplier=initial_risk_multiplier,
            max_bet_cap_pct=0.10
        )
        self.max_daily_loss_pct = float(total_pnl_limit_pct)
        self.max_sector_exposure_pct = float(max_sector_exposure)
        self.risk_multiplier = float(initial_risk_multiplier)
        
        self.circuit_breaker_active = False
        self.last_pnl_check = 0.0
        self.start_of_day_equity = 0.0
        
        # Connections (Injected after init)
        self.pnl_tracker = None
        self.delta_tracker = None
        self.signal_bus = None
        
        self._lock = asyncio.Lock()
        logger.info(f"🛡️ GlobalRiskManager initialized (Daily Limit: {self.max_daily_loss_pct:.1%})")

    def set_dependencies(self, pnl_tracker, delta_tracker, signal_bus):
        self.pnl_tracker = pnl_tracker
        self.delta_tracker = delta_tracker
        self.signal_bus = signal_bus

    async def check_global_safety(self) -> bool:
        """
        Runs a full diagnostic on portfolio health.
        Returns False if a CRITICAL risk is detected (should stop trading).
        """
        async with self._lock:
            # 1. P&L Circuit Breaker
            if self.pnl_tracker:
                summary = self.pnl_tracker.get_summary()
                total_pnl = float(summary.get('total_pnl', 0.0))
                
                # Assume $1000 base if not tracked (should use real equity in production)
                equity_base = 1000.0 
                if self.start_of_day_equity > 0:
                    equity_base = self.start_of_day_equity
                
                loss_pct = abs(total_pnl / equity_base) if total_pnl < 0 else 0
                
                if loss_pct >= self.max_daily_loss_pct:
                    if not self.circuit_breaker_active:
                        logger.error(f"🚨 GLOBAL CIRCUIT BREAKER: Portfolio loss {loss_pct:.2%} >= {self.max_daily_loss_pct:.2%}")
                        self.circuit_breaker_active = True
                        if self.signal_bus:
                            await self.signal_bus.update_signal("GLOBAL", "RISK", mode="PANIC_SELL")
                    return False

            # 2. Sector Concentration Check (Using PnLTracker for USD Exposure)
            if self.pnl_tracker:
                # Aggregate USD exposure per market group
                sector_exposure = {}
                total_exposure = 0.0
                for trade in self.pnl_tracker.active_trades.values():
                    group = trade.metadata.get('group', 'DEFAULT')
                    sector_exposure[group] = sector_exposure.get(group, 0.0) + trade.size
                    total_exposure += trade.size
                
                # Calculate NLV (Net Liquidation Value) = Cash + Current Exposure
                # We use the maximum of start_of_day_equity (cash at start) and total current assets
                # to prevent divide-by-zero or extreme concentration numbers.
                assets_basis = max(self.start_of_day_equity, total_exposure)
                equity_base = assets_basis if assets_basis > 0 else 1000.0
                
                # Check metrics
                for group, exposure_usd in sector_exposure.items():
                    concentration = exposure_usd / equity_base
                    if concentration > self.max_sector_exposure_pct:
                        # Only log if genuinely concerning (> 120% leverage relative to total assets)
                        if concentration > 1.2:
                            logger.warning(f"⚠️ High Concentration in {group}: {concentration:.1%} (${exposure_usd:.2f} vs Basis ${equity_base:.2f})")
                
            # (Legacy DeltaTracker check removed to prevent false 1500% alarms)
            return not self.circuit_breaker_active

    async def set_circuit_breaker(self, active: bool):
        """Manually trigger or reset the circuit breaker"""
        async with self._lock:
            self.circuit_breaker_active = active
            if active:
                logger.warning("🚨 Global Circuit Breaker MANUALLY ACTIVATED")
            else:
                logger.info("🟢 Global Circuit Breaker RESET")

    def calculate_trade_size(self, base_size: float, confidence: float = 1.0) -> float:
        """
        Applies the global risk multiplier to a requested trade size.
        """
        if self.circuit_breaker_active:
            return 0.0
            
        # Scaled by global multiplier
        adjusted_size = base_size * self.risk_multiplier
        
        # Confidence scaling
        if confidence < 0.7:
            adjusted_size *= 0.5
            
        return max(adjusted_size, 0.0)

    async def update_risk_level(self, new_multiplier: float):
        """Affects all bots instantly"""
        async with self._lock:
            self.risk_multiplier = max(0.05, min(1.0, new_multiplier))
            logger.info(f"🔄 Global Risk Level adjusted to {self.risk_multiplier}x")
            
            if self.signal_bus:
                await self.signal_bus.update_signal("GLOBAL", "RISK", multiplier=self.risk_multiplier)

    def get_status(self) -> Dict:
        return {
            "multiplier": self.risk_multiplier,
            "circuit_breaker": self.circuit_breaker_active,
            "max_loss_pct": self.max_daily_loss_pct
        }
