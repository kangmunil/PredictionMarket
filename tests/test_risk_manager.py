
import pytest
from unittest.mock import MagicMock
from src.core.risk_manager import RiskManager

class TestRiskManager:
    def setup_method(self):
        self.rm = RiskManager(total_capital=100.0)
        # Ensure fixed mode defaults (as set in code)
        self.rm.fixed_size_mode = True
        self.rm.fixed_size_amount = 5.0

    def test_fixed_size_high_confidence(self):
        """Test fixed $5.00 return when confidence is high enough"""
        # params: prob_win, current_price, portfolio_balance
        size = self.rm.calculate_position_size(
            prob_win=0.7, # > 0.6
            current_price=0.5,
            portfolio_balance=100.0,
            confidence=1.0
        )
        assert size == 5.0

    def test_fixed_size_low_confidence(self):
        """Test gating: return $0.00 when confidence is low"""
        size = self.rm.calculate_position_size(
            prob_win=0.55, # < 0.6
            current_price=0.5,
            portfolio_balance=100.0
        )
        assert size == 0.0

    def test_fixed_size_insufficient_capital(self):
        """Test blocking if balance < $5.00"""
        size = self.rm.calculate_position_size(
            prob_win=0.8,
            current_price=0.5,
            portfolio_balance=2.0 # < 5.0
        )
        assert size == 0.0

    def test_fallback_to_kelly(self):
        """Test Kelly criterion when fixed mode is disabled"""
        self.rm.fixed_size_mode = False
        
        # Le's just verify it returns > 0
        size = self.rm.calculate_position_size(
            prob_win=0.8,
            current_price=0.5,
            portfolio_balance=100.0
        )
        assert size > 0.0
        assert size != 5.0 # Should be dynamic
