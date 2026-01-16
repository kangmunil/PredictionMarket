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
        max_bet_cap_pct: float = 0.10 
    ):
        self.total_capital = float(total_capital)
        self.risk_multiplier = risk_multiplier 
        self.max_bet_cap_pct = float(max_bet_cap_pct)  # Dynamic Risk Cap
        self.max_daily_loss_pct = 0.03 
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

    def set_risk_multiplier(self, multiplier: float):
        """Dynamically update risk multiplier via Telegram command"""
        if 0.05 <= multiplier <= 1.0:
            old = self.risk_multiplier
            self.risk_multiplier = multiplier
            logger.info(f"🔄 Risk Multiplier updated: {old} -> {multiplier}")
            return True
        logger.warning(f"⚠️ Invalid Risk Multiplier request: {multiplier}")
        return False

    def calculate_position_size(
        self, 
        prob_win: float, 
        current_price: float, 
        portfolio_balance: Optional[float] = None,
        category: str = "general",
        volatility_score: float = 0.0,
        confidence: float = 1.0
    ) -> float:
        """
        Calculate safe position size using Kelly Criterion and risk filters.
        
        Args:
            prob_win: AI confidence/probability (0.0 - 1.0)
            current_price: Current market price (0.0 - 1.0)
            category: Market category for correlation check
            volatility_score: 0.0 (stable) to 1.0 (highly volatile/wide spread)
            confidence: AI's confidence in its own prediction (0.0 - 1.0)
            
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
        b = (1.0 - current_price) / current_price
        q = 1.0 - prob_win
        kelly_fraction = (b * prob_win - q) / b
        
        if kelly_fraction <= 0:
            return 0.0

        # 4. Conservative Sizing (Fractional Kelly)
        safe_fraction = kelly_fraction * self.risk_multiplier
        
        # --- NEW: Win Rate Optimization (Confidence Scaling) ---
        if confidence < 0.7:
             logger.info(f"   🧊 RiskManager: Skipping trade due to low confidence ({confidence:.2%})")
             return 0.0
             
        conf_multiplier = 1.0
        if confidence < 0.8:
            conf_multiplier = 0.5
        elif confidence < 0.9:
            conf_multiplier = 0.8
            
        if conf_multiplier < 1.0:
            logger.info(f"   ⚖️ RiskManager: Applying confidence multiplier {conf_multiplier}x (Confidence: {confidence:.2%})")
            safe_fraction *= conf_multiplier
        # ------------------------------------------------------

        # 5. Volatility Penalty
        if volatility_score > 0.5:
            penalty = 0.5 # 50% reduction
            safe_fraction *= (1.0 - penalty)
            logger.info(f"📉 Volatility Penalty Applied: -50% size")

        # 6. Correlation Penalty
        active_count = self.active_positions_count.get(category, 0)
        if active_count >= 2:
            correlation_penalty = 0.5 # Reduce by half if 2+ positions exist
            safe_fraction *= correlation_penalty
            logger.info(f"🔗 Correlation Penalty Applied: -50% size (Category: {category})")

        # 7. Hard Cap (Max % of Portfolio)
        final_fraction = min(safe_fraction, self.max_bet_cap_pct)
        
        # 8. Calculate Dollar Amount
        capital_base = portfolio_balance if portfolio_balance is not None else self.total_capital
        bet_amount = capital_base * final_fraction
        
        if self.max_bet_usd is not None and bet_amount > self.max_bet_usd:
            logger.info(f"🔒 Absolute Bet Cap Applied: ${bet_amount:.2f} → ${self.max_bet_usd:.2f}")
            bet_amount = self.max_bet_usd

        logger.info(f"⚖️ Risk Sizing: Cap(${capital_base:.2f}) * Frac({final_fraction:.4f}) = ${bet_amount:.2f}")
        
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
            self.last_reset_date = today
            self.circuit_breaker_active = False

    def check_exit_conditions(
        self,
        entry_price: float,
        current_price: float,
        side: str,
        hold_duration_minutes: float = 0
    ) -> (bool, str):
        """
        Check if position should be closed based on PnL (Stop Loss / Take Profit).
        Returns: (should_exit, reason)
        """
        if entry_price <= 0: return False, ""
        
        # Calculate PnL %
        if side.upper() == "BUY":
            pnl_pct = (current_price - entry_price) / entry_price
        else: # SELL (Short)
            pnl_pct = (entry_price - current_price) / entry_price
        
        # 1. Hard Stop Loss (-15%)
        # Allow wider stop for volatile crypto markets?
        STOP_LOSS_PCT = -0.15 
        if pnl_pct <= STOP_LOSS_PCT:
            return True, f"Stop Loss Hit ({pnl_pct:.1%})"
            
        # 2. Take Profit (+25%)
        # Scalping strategy might want tighter TP? 
        # But for 'News' we want to ride big moves.
        TAKE_PROFIT_PCT = 0.25
        if pnl_pct >= TAKE_PROFIT_PCT:
            return True, f"Take Profit Hit ({pnl_pct:.1%})"
            
        return False, ""
