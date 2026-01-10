"""
Risk Manager - Dynamic Position Sizing & Safety
===============================================

Implements Kelly Criterion for optimal position sizing and advanced risk filters.
Acts as the 'Gatekeeper' for all trade sizing decisions.

Features:
- Fractional Kelly Criterion (Quarter Kelly)
- Volatility Penalty
- Correlation Risk Checks (Placeholder)
- Daily Loss Circuit Breaker

Author: Risk Control Module
Created: 2026-01-07
"""

import logging
from decimal import Decimal
from typing import Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

class RiskManager:
    """
    Centralized Risk Management Module.
    Calculates optimal bet sizes and enforces safety limits.
    """

    def __init__(
        self,
        total_capital: float = 1000.0,
        risk_multiplier: float = 0.25,
        max_bet_usd: Optional[float] = None,
    ):
        self.total_capital = float(total_capital)
        self.risk_multiplier = risk_multiplier # Quarter Kelly (0.25)
        self.max_bet_cap_pct = 0.10  # Max 10% of portfolio per trade
        self.max_daily_loss_pct = 0.03 # 3% daily loss limit
        self.max_bet_usd = float(max_bet_usd) if max_bet_usd is not None else None
        
        # State tracking
        self.daily_start_capital = self.total_capital
        self.daily_pnl = 0.0
        self.last_reset_date = datetime.now().date()
        self.circuit_breaker_active = False
        
        # Correlation tracking (Simplified: just counts per category)
        self.active_positions_count = {
            "crypto": 0,
            "politics": 0,
            "economics": 0,
            "sports": 0
        }

    def calculate_position_size(
        self, 
        prob_win: float, 
        current_price: float, 
        category: str = "general",
        volatility_score: float = 0.0
    ) -> float:
        """
        Calculate safe position size using Kelly Criterion and risk filters.
        
        Args:
            prob_win: AI confidence/probability (0.0 - 1.0)
            current_price: Current market price (0.0 - 1.0)
            category: Market category for correlation check
            volatility_score: 0.0 (stable) to 1.0 (highly volatile/wide spread)
            
        Returns:
            Float amount in USD to bet. Returns 0.0 if trade is rejected.
        """
        # 1. Circuit Breaker Check
        if self._check_circuit_breaker():
            logger.warning("⛔ RiskManager: Trade rejected (Circuit Breaker Active)")
            return 0.0

        # 2. Basic Validation
        if prob_win <= current_price:
            logger.debug(f"⚠️ RiskManager: Negative EV (Prob {prob_win:.2f} <= Price {current_price:.2f})")
            return 0.0
            
        if current_price <= 0 or current_price >= 1:
            return 0.0

        # 3. Kelly Criterion Calculation
        # b = Net Odds = (1 - price) / price
        # f* = (bp - q) / b
        # Simplified for binary options: f = (p - price) / (1 - price) ? No.
        # Let's stick to the standard formula:
        # Win Gain (W) = (1 - price)
        # Loss (L) = price
        # Edge = p * W - (1-p) * L = p(1-price) - (1-p)price = p - p*price - price + p*price = p - price
        # Kelly Fraction = Edge / Odds = (p - price) / ((1-price)/price)? 
        # Actually simpler for "bet 1 to win 1/price": 
        # f = p/price - (1-p)/(1-price) ... no that's complex.
        
        # Using the standard: f = (bp - q) / b
        b = (1.0 - current_price) / current_price
        q = 1.0 - prob_win
        kelly_fraction = (b * prob_win - q) / b
        
        if kelly_fraction <= 0:
            return 0.0

        # 4. Conservative Sizing (Fractional Kelly)
        safe_fraction = kelly_fraction * self.risk_multiplier
        
        # 5. Volatility Penalty
        # If volatility is high (e.g., spread > 5%), reduce size
        if volatility_score > 0.5:
            penalty = 0.5 # 50% reduction
            safe_fraction *= (1.0 - penalty)
            logger.info(f"📉 Volatility Penalty Applied: -50% size")

        # 6. Correlation Penalty
        # If we already have positions in this category, reduce size
        active_count = self.active_positions_count.get(category, 0)
        if active_count >= 2:
            correlation_penalty = 0.5 # Reduce by half if 2+ positions exist
            safe_fraction *= correlation_penalty
            logger.info(f"🔗 Correlation Penalty Applied: -50% size (Category: {category})")

        # 7. Hard Cap (Max % of Portfolio)
        final_fraction = min(safe_fraction, self.max_bet_cap_pct)
        
        # 8. Calculate Dollar Amount
        bet_amount = self.total_capital * final_fraction
        
        if self.max_bet_usd is not None and bet_amount > self.max_bet_usd:
            logger.info(f"🔒 Absolute Bet Cap Applied: ${bet_amount:.2f} → ${self.max_bet_usd:.2f}")
            bet_amount = self.max_bet_usd

        logger.info(f"⚖️ Risk Sizing: P({prob_win:.2f}) vs Price({current_price:.2f}) -> Kelly({kelly_fraction:.2%}) -> Safe({final_fraction:.2%}) -> ${bet_amount:.2f}")
        
        return max(bet_amount, 0.0)

    def update_pnl(self, pnl_amount: float):
        """Update P&L to track daily limits"""
        self._check_daily_reset()
        
        self.daily_pnl += pnl_amount
        self.total_capital += pnl_amount # Update total capital for compounding
        
        logger.info(f"📊 RiskManager: Daily P&L ${self.daily_pnl:.2f} | Total Cap ${self.total_capital:.2f}")
        
        self._check_circuit_breaker()

    def _check_circuit_breaker(self) -> bool:
        """Returns True if trading should be halted"""
        self._check_daily_reset()
        
        loss_pct = (self.daily_pnl / self.daily_start_capital)
        if loss_pct <= -self.max_daily_loss_pct:
            if not self.circuit_breaker_active:
                logger.error(f"🚨 CIRCUIT BREAKER TRIGGERED: Daily Loss {loss_pct:.2%} exceeds limit {-self.max_daily_loss_pct:.2%}")
                self.circuit_breaker_active = True
            return True
            
        return False

    def _check_daily_reset(self):
        """Reset daily stats at midnight"""
        today = datetime.now().date()
        if today > self.last_reset_date:
            logger.info("🔄 RiskManager: Resetting daily P&L stats")
            self.daily_pnl = 0.0
            self.daily_start_capital = self.total_capital
            self.last_reset_date = today
            self.circuit_breaker_active = False
