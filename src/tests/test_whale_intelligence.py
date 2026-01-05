"""
Test Suite for Whale Intelligence Module
=========================================
Comprehensive tests for bait detection, frontrunning analysis, and replication logic.

Author: Claude (Quantitative Trading Strategist)
Date: 2026-01-02
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from src.core.whale_intelligence import (
    WhaleIntelligence,
    TradeSignal,
    MarketState,
    WhaleProfile,
    BaitDetector,
    FrontRunningAnalyzer,
    WhaleProfiler,
    ReplicationStrategy
)


class TestBaitDetector:
    """Test bait trade detection logic"""

    def setup_method(self):
        self.detector = BaitDetector()
        self.whale = WhaleProfile(
            address="0xtest",
            username="test-whale",
            total_trades=100,
            winning_trades=60,
            losing_trades=40,
            avg_position_size=500.0
        )
        self.whale.preferred_markets = {"POLITICS": 40, "CRYPTO": 30, "SPORTS": 20}

    def test_oversized_position_detection(self):
        """Test detection of unusually large positions (potential bait)"""
        signal = TradeSignal(
            trader_address="0xtest",
            token_id="token1",
            side="BUY",
            detected_price=0.60,
            amount=2000.0,  # 4x normal size
            tx_hash="0xhash",
            detection_timestamp=datetime.now(),
            block_number=12345
        )

        market = MarketState(
            token_id="token1",
            current_price=0.60,
            bid_ask_spread=0.02,
            liquidity_depth_10=5000.0,
            recent_volume_24h=10000.0,
            price_volatility_24h=0.10,
            last_updated=datetime.now()
        )

        bait_score, flags = self.detector.analyze_signal(signal, self.whale, market)

        assert bait_score > 0.20, "Should detect oversized position"
        assert any("OVERSIZED" in flag for flag in flags), "Should flag as oversized"

    def test_low_liquidity_market_detection(self):
        """Test detection of trades in low-liquidity markets (manipulation risk)"""
        signal = TradeSignal(
            trader_address="0xtest",
            token_id="token1",
            side="BUY",
            detected_price=0.60,
            amount=500.0,
            tx_hash="0xhash",
            detection_timestamp=datetime.now(),
            block_number=12345
        )

        market = MarketState(
            token_id="token1",
            current_price=0.60,
            bid_ask_spread=0.08,  # Wide spread
            liquidity_depth_10=500.0,  # Low liquidity
            recent_volume_24h=1000.0,
            price_volatility_24h=0.10,
            last_updated=datetime.now()
        )

        bait_score, flags = self.detector.analyze_signal(signal, self.whale, market)

        assert bait_score > 0.40, "Should detect low liquidity bait trade"
        assert any("LOW_LIQUIDITY" in flag for flag in flags), "Should flag low liquidity"
        assert any("WIDE_SPREAD" in flag for flag in flags), "Should flag wide spread"

    def test_legitimate_trade_low_score(self):
        """Test that normal trades get low bait scores"""
        signal = TradeSignal(
            trader_address="0xtest",
            token_id="token1",
            side="BUY",
            detected_price=0.60,
            amount=500.0,  # Normal size
            tx_hash="0xhash",
            detection_timestamp=datetime.now(),
            block_number=12345
        )

        market = MarketState(
            token_id="token1",
            current_price=0.60,
            bid_ask_spread=0.02,  # Tight spread
            liquidity_depth_10=10000.0,  # Good liquidity
            recent_volume_24h=50000.0,
            price_volatility_24h=0.10,
            last_updated=datetime.now()
        )

        bait_score, flags = self.detector.analyze_signal(signal, self.whale, market)

        assert bait_score < 0.30, f"Legitimate trade should have low bait score, got {bait_score}"


class TestFrontRunningAnalyzer:
    """Test frontrunning risk detection"""

    def setup_method(self):
        self.analyzer = FrontRunningAnalyzer()

    def test_high_latency_detection(self):
        """Test detection of high latency (frontrunning risk)"""
        signal = TradeSignal(
            trader_address="0xtest",
            token_id="token1",
            side="BUY",
            detected_price=0.60,
            amount=500.0,
            tx_hash="0xhash",
            detection_timestamp=datetime.now(),
            block_number=12345,
            latency_ms=8000  # 8 seconds - very high
        )

        market = MarketState(
            token_id="token1",
            current_price=0.60,
            bid_ask_spread=0.02,
            liquidity_depth_10=5000.0,
            recent_volume_24h=10000.0,
            price_volatility_24h=0.10,
            last_updated=datetime.now()
        )

        signal.current_market_price = 0.60

        risk_level, confidence, warnings = self.analyzer.assess_frontrun_risk(
            signal, market, []
        )

        assert risk_level in ["MEDIUM", "HIGH"], f"Should detect high latency risk, got {risk_level}"
        assert any("HIGH_LATENCY" in w for w in warnings), "Should warn about latency"

    def test_price_movement_detection(self):
        """Test detection of price movement since whale trade (frontrunning indicator)"""
        signal = TradeSignal(
            trader_address="0xtest",
            token_id="token1",
            side="BUY",
            detected_price=0.60,
            amount=500.0,
            tx_hash="0xhash",
            detection_timestamp=datetime.now(),
            block_number=12345,
            latency_ms=2000
        )

        market = MarketState(
            token_id="token1",
            current_price=0.65,  # Price jumped 8.3%
            bid_ask_spread=0.02,
            liquidity_depth_10=5000.0,
            recent_volume_24h=10000.0,
            price_volatility_24h=0.10,
            last_updated=datetime.now()
        )

        signal.current_market_price = 0.65

        risk_level, confidence, warnings = self.analyzer.assess_frontrun_risk(
            signal, market, []
        )

        assert risk_level in ["HIGH", "CRITICAL"], f"Should detect price movement risk, got {risk_level}"
        assert any("PRICE_MOVED" in w for w in warnings), "Should warn about price movement"

    def test_low_risk_scenario(self):
        """Test that fast detection with minimal price movement gets low risk"""
        signal = TradeSignal(
            trader_address="0xtest",
            token_id="token1",
            side="BUY",
            detected_price=0.60,
            amount=500.0,
            tx_hash="0xhash",
            detection_timestamp=datetime.now(),
            block_number=12345,
            latency_ms=1500  # Fast detection
        )

        market = MarketState(
            token_id="token1",
            current_price=0.605,  # Minimal movement
            bid_ask_spread=0.02,
            liquidity_depth_10=5000.0,
            recent_volume_24h=10000.0,
            price_volatility_24h=0.10,
            last_updated=datetime.now()
        )

        signal.current_market_price = 0.605

        risk_level, confidence, warnings = self.analyzer.assess_frontrun_risk(
            signal, market, []
        )

        assert risk_level == "LOW", f"Fast detection with minimal movement should be low risk, got {risk_level}"


class TestWhaleProfiler:
    """Test whale behavior profiling"""

    def setup_method(self):
        self.profiler = WhaleProfiler()

    def test_profile_creation(self):
        """Test creation of new whale profiles"""
        profile = self.profiler.get_or_create_profile("0xwhale1", "whale1")

        assert profile.address == "0xwhale1"
        assert profile.username == "whale1"
        assert profile.total_trades == 0

    def test_win_rate_calculation(self):
        """Test win rate calculation from trade history"""
        profile = self.profiler.get_or_create_profile("0xwhale1", "whale1")

        # Add 20 trades (12 wins, 8 losses)
        for i in range(12):
            self.profiler.update_profile("0xwhale1", {"outcome": "WIN", "amount": 100, "market_type": "CRYPTO"})
        for i in range(8):
            self.profiler.update_profile("0xwhale1", {"outcome": "LOSS", "amount": 100, "market_type": "CRYPTO"})

        assert profile.total_trades == 20
        assert profile.winning_trades == 12
        assert profile.losing_trades == 8
        assert profile.recent_win_rate_20 == 0.60  # 12/20

    def test_strategy_shift_detection(self):
        """Test detection of strategy changes in whale behavior"""
        profile = self.profiler.get_or_create_profile("0xwhale1", "whale1")

        # First 20 trades: normal size, CRYPTO focus
        for i in range(20):
            self.profiler.update_profile("0xwhale1", {
                "outcome": "WIN" if i % 2 == 0 else "LOSS",
                "amount": 100,
                "market_type": "CRYPTO"
            })

        assert not profile.strategy_shift_detected, "Should not detect shift yet"

        # Next 20 trades: larger size, POLITICS focus (strategy shift)
        for i in range(20):
            self.profiler.update_profile("0xwhale1", {
                "outcome": "WIN" if i % 2 == 0 else "LOSS",
                "amount": 500,  # 5x larger
                "market_type": "POLITICS"  # Different market
            })

        assert profile.strategy_shift_detected, "Should detect strategy shift"

    def test_whale_validation_low_winrate(self):
        """Test rejection of whales with low win rates"""
        profile = self.profiler.get_or_create_profile("0xwhale1", "whale1")

        # Add trades with poor performance
        for i in range(30):
            outcome = "WIN" if i < 10 else "LOSS"  # 33% win rate
            self.profiler.update_profile("0xwhale1", {"outcome": outcome, "amount": 100, "market_type": "CRYPTO"})

        should_copy, reason, confidence = self.profiler.should_copy_whale("0xwhale1")

        assert not should_copy, "Should reject whale with low win rate"
        assert "LOW_WIN_RATE" in reason or "POOR_PERFORMANCE" in reason

    def test_whale_validation_good_performance(self):
        """Test approval of whales with good performance"""
        profile = self.profiler.get_or_create_profile("0xwhale1", "whale1")

        # Add trades with good performance
        for i in range(30):
            outcome = "WIN" if i < 20 else "LOSS"  # 67% win rate
            self.profiler.update_profile("0xwhale1", {"outcome": outcome, "amount": 100, "market_type": "CRYPTO"})

        should_copy, reason, confidence = self.profiler.should_copy_whale("0xwhale1")

        assert should_copy, f"Should approve whale with good win rate. Reason: {reason}"
        assert confidence > 0.5


class TestReplicationStrategy:
    """Test trade replication decision logic"""

    def setup_method(self):
        self.replicator = ReplicationStrategy(strategy_type="SELECTIVE", max_position_size=100.0)

    def test_reject_insufficient_ev(self):
        """Test rejection of trades with insufficient expected value"""
        signal = TradeSignal(
            trader_address="0xtest",
            token_id="token1",
            side="BUY",
            detected_price=0.60,
            amount=500.0,
            tx_hash="0xhash",
            detection_timestamp=datetime.now(),
            block_number=12345
        )

        market = MarketState(
            token_id="token1",
            current_price=0.60,
            bid_ask_spread=0.02,
            liquidity_depth_10=5000.0,
            recent_volume_24h=10000.0,
            price_volatility_24h=0.10,
            last_updated=datetime.now()
        )

        signal.current_market_price = 0.60

        should_copy, reason, params = self.replicator.should_copy_trade(
            signal=signal,
            bait_score=0.2,
            frontrun_risk="LOW",
            whale_verdict=(True, "VALIDATED", 0.8),
            ai_ev=0.01,  # Below 3% threshold
            market=market
        )

        assert not should_copy, "Should reject low EV trade"
        assert "INSUFFICIENT_EV" in reason

    def test_approve_high_quality_trade(self):
        """Test approval of high-quality trade signals"""
        signal = TradeSignal(
            trader_address="0xtest",
            token_id="token1",
            side="BUY",
            detected_price=0.60,
            amount=500.0,
            tx_hash="0xhash",
            detection_timestamp=datetime.now(),
            block_number=12345
        )

        market = MarketState(
            token_id="token1",
            current_price=0.60,
            bid_ask_spread=0.02,
            liquidity_depth_10=5000.0,
            recent_volume_24h=10000.0,
            price_volatility_24h=0.10,
            last_updated=datetime.now()
        )

        signal.current_market_price = 0.60

        should_copy, reason, params = self.replicator.should_copy_trade(
            signal=signal,
            bait_score=0.1,  # Low bait score
            frontrun_risk="LOW",
            whale_verdict=(True, "VALIDATED", 0.9),
            ai_ev=0.05,  # Good EV
            market=market
        )

        assert should_copy, f"Should approve high-quality trade. Reason: {reason}"
        assert "position_size" in params
        assert "delay_seconds" in params

    def test_position_sizing_selective(self):
        """Test position sizing logic for selective strategy"""
        signal = TradeSignal(
            trader_address="0xtest",
            token_id="token1",
            side="BUY",
            detected_price=0.60,
            amount=500.0,
            tx_hash="0xhash",
            detection_timestamp=datetime.now(),
            block_number=12345
        )
        signal.current_market_price = 0.60

        market = MarketState(
            token_id="token1",
            current_price=0.60,
            bid_ask_spread=0.02,
            liquidity_depth_10=5000.0,
            recent_volume_24h=10000.0,
            price_volatility_24h=0.10,
            last_updated=datetime.now()
        )

        # High confidence, high EV scenario
        size = self.replicator._calculate_position_size(
            signal=signal,
            whale_confidence=0.9,
            ai_ev=0.08,  # High EV
            market=market
        )

        assert size > 30, "Should size up for high-quality signal"
        assert size <= 100, "Should not exceed max position size"

        # Low confidence scenario
        size_low = self.replicator._calculate_position_size(
            signal=signal,
            whale_confidence=0.3,
            ai_ev=0.03,
            market=market
        )

        assert size_low < size, "Should size down for lower confidence"


@pytest.mark.asyncio
class TestWhaleIntelligenceIntegration:
    """Integration tests for complete whale intelligence system"""

    async def test_end_to_end_trade_analysis(self):
        """Test complete pipeline from signal detection to execution decision"""
        intel = WhaleIntelligence(strategy_type="SELECTIVE", max_position_size=100.0)

        # Setup whale profile
        whale = intel.profiler.get_or_create_profile("0xwhale1", "test-whale")
        for i in range(30):
            intel.profiler.update_profile("0xwhale1", {
                "outcome": "WIN" if i < 20 else "LOSS",  # 67% win rate
                "amount": 500,
                "market_type": "CRYPTO"
            })

        # Create trade signal
        signal = TradeSignal(
            trader_address="0xwhale1",
            token_id="token1",
            side="BUY",
            detected_price=0.58,
            amount=500.0,
            tx_hash="0xhash123",
            detection_timestamp=datetime.now(),
            block_number=12345,
            latency_ms=2000
        )
        signal.current_market_price = 0.60

        # Create market state
        market = MarketState(
            token_id="token1",
            current_price=0.60,
            bid_ask_spread=0.02,
            liquidity_depth_10=8000.0,
            recent_volume_24h=20000.0,
            price_volatility_24h=0.12,
            last_updated=datetime.now()
        )

        # Analyze signal
        should_copy, reason, params = await intel.analyze_trade_signal(
            signal=signal,
            market=market,
            ai_ev=0.05,  # Good EV
            recent_txs=[]
        )

        # Verify decision
        assert isinstance(should_copy, bool)
        assert isinstance(reason, str)
        assert isinstance(params, dict)

        if should_copy:
            assert "position_size" in params
            assert "delay_seconds" in params
            assert params["position_size"] > 0
            assert params["position_size"] <= 100


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
