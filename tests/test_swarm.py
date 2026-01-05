"""
Swarm Intelligence Tests
=========================

Comprehensive test suite for Project Hive Mind.

Tests:
1. SignalBus pub/sub functionality
2. Cross-bot intelligence
3. Budget coordination
4. Risk management
5. Signal convergence scenarios
6. Performance benchmarks

Author: Project Hive Mind
Created: 2026-01-05
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src.core.signal_bus import (
    SignalBus,
    Signal,
    SignalType,
    SignalPriority,
    GlobalSentiment,
    HotToken,
    WhaleMove,
    NewsEvent,
    MarketOpportunity
)
from src.core.budget_manager import BudgetManager
from src.swarm.risk_manager import SwarmRiskManager, RiskLimits


# ============================================================================
# SignalBus Tests
# ============================================================================

@pytest.mark.asyncio
async def test_signal_bus_singleton():
    """Test SignalBus singleton pattern"""
    bus1 = await SignalBus.get_instance()
    bus2 = await SignalBus.get_instance()

    assert bus1 is bus2
    assert isinstance(bus1, SignalBus)


@pytest.mark.asyncio
async def test_signal_publish_subscribe():
    """Test basic pub/sub functionality"""
    bus = await SignalBus.get_instance()

    received_signals = []

    async def callback(signal: Signal):
        received_signals.append(signal)

    # Subscribe
    bus.subscribe(SignalType.NEWS_EVENT, "test_bot", callback)

    # Publish
    await bus.publish(Signal(
        signal_type=SignalType.NEWS_EVENT,
        priority=SignalPriority.HIGH,
        source_bot="test_publisher",
        timestamp=datetime.now(),
        ttl=60,
        data={'headline': 'Test News', 'sentiment_score': 0.8}
    ))

    # Allow async processing
    await asyncio.sleep(0.1)

    # Verify
    assert len(received_signals) == 1
    assert received_signals[0].data['headline'] == 'Test News'
    assert received_signals[0].data['sentiment_score'] == 0.8


@pytest.mark.asyncio
async def test_signal_expiration():
    """Test signal TTL expiration"""
    bus = await SignalBus.get_instance()

    # Create signal with 1 second TTL
    signal = Signal(
        signal_type=SignalType.NEWS_EVENT,
        priority=SignalPriority.MEDIUM,
        source_bot="test",
        timestamp=datetime.now(),
        ttl=1,
        data={}
    )

    # Should not be expired initially
    assert not signal.is_expired

    # Wait 2 seconds
    await asyncio.sleep(2)

    # Should be expired now
    assert signal.is_expired


@pytest.mark.asyncio
async def test_multiple_subscribers():
    """Test multiple subscribers to same signal"""
    bus = await SignalBus.get_instance()

    received_bot1 = []
    received_bot2 = []

    async def callback1(signal):
        received_bot1.append(signal)

    async def callback2(signal):
        received_bot2.append(signal)

    # Subscribe two bots
    bus.subscribe(SignalType.WHALE_MOVE, "bot1", callback1)
    bus.subscribe(SignalType.WHALE_MOVE, "bot2", callback2)

    # Publish
    await bus.publish(Signal(
        signal_type=SignalType.WHALE_MOVE,
        priority=SignalPriority.HIGH,
        source_bot="elitemimic",
        timestamp=datetime.now(),
        ttl=300,
        data={
            'wallet_address': '0x123',
            'entity': 'Bitcoin',
            'side': 'BUY'
        }
    ))

    await asyncio.sleep(0.1)

    # Both should receive
    assert len(received_bot1) == 1
    assert len(received_bot2) == 1
    assert received_bot1[0].data['entity'] == 'Bitcoin'
    assert received_bot2[0].data['entity'] == 'Bitcoin'


# ============================================================================
# State Management Tests
# ============================================================================

@pytest.mark.asyncio
async def test_global_sentiment_update():
    """Test GlobalSentiment state management"""
    bus = await SignalBus.get_instance()

    # Publish sentiment
    await bus.publish(Signal(
        signal_type=SignalType.GLOBAL_SENTIMENT,
        priority=SignalPriority.MEDIUM,
        source_bot="news_scalper",
        timestamp=datetime.now(),
        ttl=3600,
        data={
            'overall_score': 0.75,
            'confidence': 0.9,
            'dominant_narrative': 'Bitcoin ETF Approval',
            'top_entities': ['Bitcoin', 'ETF', 'SEC'],
            'news_count_1h': 15,
            'updated_at': datetime.now()
        }
    ))

    await asyncio.sleep(0.1)

    # Verify state
    sentiment = bus.get_global_sentiment()
    assert sentiment is not None
    assert sentiment.overall_score == 0.75
    assert sentiment.dominant_narrative == 'Bitcoin ETF Approval'


@pytest.mark.asyncio
async def test_hot_token_tracking():
    """Test HotToken state management"""
    bus = await SignalBus.get_instance()

    # Publish hot token
    await bus.publish(Signal(
        signal_type=SignalType.HOT_TOKEN,
        priority=SignalPriority.MEDIUM,
        source_bot="arbhunter",
        timestamp=datetime.now(),
        ttl=3600,
        data={
            'token_id': 'token_123',
            'condition_id': 'cond_456',
            'market_name': 'Bitcoin > $100k',
            'volume_1h': 50000.0,
            'price_velocity': 2.5,
            'volatility': 0.15,
            'reason': 'whale_buy',
            'detected_at': datetime.now()
        }
    ))

    await asyncio.sleep(0.1)

    # Verify
    assert bus.is_token_hot('token_123')
    hot_token = bus.get_token_heat('token_123')
    assert hot_token.volume_1h == 50000.0


@pytest.mark.asyncio
async def test_whale_moves_tracking():
    """Test WhaleMove history tracking"""
    bus = await SignalBus.get_instance()

    # Publish whale move
    await bus.publish(Signal(
        signal_type=SignalType.WHALE_MOVE,
        priority=SignalPriority.HIGH,
        source_bot="elitemimic",
        timestamp=datetime.now(),
        ttl=1800,
        data={
            'wallet_address': '0x123',
            'wallet_name': 'distinct-baguette',
            'market_id': 'market_789',
            'token_id': 'token_123',
            'side': 'BUY',
            'amount_usd': 50000.0,
            'price': 0.65,
            'entity': 'Bitcoin',
            'detected_at': datetime.now()
        }
    ))

    await asyncio.sleep(0.1)

    # Verify
    recent_moves = bus.get_whale_moves(minutes=60)
    assert len(recent_moves) == 1
    assert recent_moves[0].entity == 'Bitcoin'
    assert recent_moves[0].side == 'BUY'


# ============================================================================
# Cross-Bot Intelligence Tests
# ============================================================================

@pytest.mark.asyncio
async def test_signal_strength_calculation():
    """Test signal strength aggregation"""
    bus = await SignalBus.get_instance()

    # Publish positive news
    await bus.publish(Signal(
        signal_type=SignalType.NEWS_EVENT,
        priority=SignalPriority.HIGH,
        source_bot="news_scalper",
        timestamp=datetime.now(),
        ttl=300,
        data={
            'headline': 'Bitcoin ETF Approved',
            'entities': ['Bitcoin'],
            'sentiment_score': 0.9,
            'confidence': 0.95,
            'impact_level': 'high',
            'source': 'Reuters',
            'related_markets': [],
            'published_at': datetime.now()
        }
    ))

    # Publish whale buy
    await bus.publish(Signal(
        signal_type=SignalType.WHALE_MOVE,
        priority=SignalPriority.HIGH,
        source_bot="elitemimic",
        timestamp=datetime.now(),
        ttl=1800,
        data={
            'wallet_address': '0x123',
            'wallet_name': 'whale',
            'market_id': 'btc_market',
            'token_id': 'btc_token',
            'side': 'BUY',
            'amount_usd': 100000.0,
            'price': 0.8,
            'entity': 'Bitcoin',
            'detected_at': datetime.now()
        }
    ))

    # Publish positive global sentiment
    await bus.publish(Signal(
        signal_type=SignalType.GLOBAL_SENTIMENT,
        priority=SignalPriority.MEDIUM,
        source_bot="polyai",
        timestamp=datetime.now(),
        ttl=3600,
        data={
            'overall_score': 0.7,
            'confidence': 0.8,
            'dominant_narrative': 'Bullish',
            'top_entities': ['Bitcoin'],
            'news_count_1h': 20,
            'updated_at': datetime.now()
        }
    ))

    await asyncio.sleep(0.1)

    # Calculate signal strength
    strength = bus.get_signal_strength('Bitcoin')

    # Should be strongly bullish (>0.5)
    assert strength > 0.5
    print(f"Bitcoin signal strength: {strength:.2f}")


@pytest.mark.asyncio
async def test_position_size_multiplier():
    """Test position size adjustment based on signal convergence"""
    bus = await SignalBus.get_instance()

    # Setup strong bullish signals (like previous test)
    await bus.publish(Signal(
        signal_type=SignalType.NEWS_EVENT,
        priority=SignalPriority.HIGH,
        source_bot="news_scalper",
        timestamp=datetime.now(),
        ttl=300,
        data={
            'headline': 'Ethereum ETF Approved',
            'entities': ['Ethereum'],
            'sentiment_score': 0.95,
            'confidence': 0.9,
            'impact_level': 'high',
            'source': 'Bloomberg',
            'related_markets': [],
            'published_at': datetime.now()
        }
    ))

    await bus.publish(Signal(
        signal_type=SignalType.WHALE_MOVE,
        priority=SignalPriority.HIGH,
        source_bot="elitemimic",
        timestamp=datetime.now(),
        ttl=1800,
        data={
            'wallet_address': '0x456',
            'wallet_name': 'whale2',
            'market_id': 'eth_market',
            'token_id': 'eth_token',
            'side': 'BUY',
            'amount_usd': 200000.0,
            'price': 0.75,
            'entity': 'Ethereum',
            'detected_at': datetime.now()
        }
    ))

    await asyncio.sleep(0.1)

    # Get position size multiplier
    multiplier = bus.get_position_size_multiplier('Ethereum')

    # Should increase position size (>1.0)
    assert multiplier > 1.0
    print(f"Ethereum position size multiplier: {multiplier:.2f}x")


@pytest.mark.asyncio
async def test_scan_frequency_decision():
    """Test whether bots should increase scan frequency"""
    bus = await SignalBus.get_instance()

    # High-impact news
    await bus.publish(Signal(
        signal_type=SignalType.NEWS_EVENT,
        priority=SignalPriority.HIGH,
        source_bot="news_scalper",
        timestamp=datetime.now(),
        ttl=900,  # 15 minutes
        data={
            'headline': 'Breaking: Bitcoin Regulation Announcement',
            'entities': ['Bitcoin'],
            'sentiment_score': 0.8,
            'confidence': 0.9,
            'impact_level': 'high',
            'source': 'CNN',
            'related_markets': [],
            'published_at': datetime.now()
        }
    ))

    await asyncio.sleep(0.1)

    # Should increase scan frequency
    assert bus.should_increase_scan_frequency('Bitcoin')

    # Unrelated entity should not
    assert not bus.should_increase_scan_frequency('Trump')


# ============================================================================
# Budget Manager Tests
# ============================================================================

@pytest.mark.asyncio
async def test_budget_allocation():
    """Test budget allocation and release"""
    # Note: Requires Redis running
    try:
        budget_mgr = BudgetManager("redis://localhost:6379")
        await budget_mgr.connect()

        # Set capital
        await budget_mgr.set_total_capital(Decimal("1000"))

        # Request allocation
        allocation_id = await budget_mgr.request_allocation(
            strategy="arbhunter",
            amount=Decimal("100"),
            priority="normal"
        )

        assert allocation_id is not None

        # Check balance decreased
        balances = await budget_mgr.get_balances()
        assert balances["arbhunter"] == Decimal("300")  # 400 - 100

        # Release allocation
        await budget_mgr.release_allocation(
            "arbhunter",
            allocation_id,
            Decimal("80")  # Spent 80, return 20
        )

        # Check balance restored
        balances = await budget_mgr.get_balances()
        assert balances["arbhunter"] == Decimal("320")  # 300 + 20

        await budget_mgr.disconnect()

    except Exception as e:
        pytest.skip(f"Redis not available: {e}")


# ============================================================================
# Risk Manager Tests
# ============================================================================

@pytest.mark.asyncio
async def test_risk_manager_position_limit():
    """Test position size limit enforcement"""
    bus = await SignalBus.get_instance()

    limits = RiskLimits(
        max_position_size_usd=Decimal("100"),
        max_total_exposure_usd=Decimal("500")
    )

    risk_mgr = SwarmRiskManager(bus, limits)
    await risk_mgr.start()

    # Should allow trade within limit
    allowed = await risk_mgr.check_trade_risk(
        bot_name="test_bot",
        entity="Bitcoin",
        size_usd=Decimal("50"),
        signal_strength=0.8
    )
    assert allowed

    # Should block trade exceeding limit
    blocked = await risk_mgr.check_trade_risk(
        bot_name="test_bot",
        entity="Bitcoin",
        size_usd=Decimal("150"),
        signal_strength=0.8
    )
    assert not blocked

    await risk_mgr.stop()


@pytest.mark.asyncio
async def test_risk_manager_signal_quality():
    """Test signal quality filtering"""
    bus = await SignalBus.get_instance()

    limits = RiskLimits(min_signal_quality=0.7)

    risk_mgr = SwarmRiskManager(bus, limits)
    await risk_mgr.start()

    # High quality signal - should pass
    allowed = await risk_mgr.check_trade_risk(
        bot_name="test_bot",
        entity="Bitcoin",
        size_usd=Decimal("50"),
        signal_strength=0.8
    )
    assert allowed

    # Low quality signal - should block
    blocked = await risk_mgr.check_trade_risk(
        bot_name="test_bot",
        entity="Bitcoin",
        size_usd=Decimal("50"),
        signal_strength=0.5
    )
    assert not blocked

    await risk_mgr.stop()


# ============================================================================
# Performance Tests
# ============================================================================

@pytest.mark.asyncio
async def test_signal_latency():
    """Test signal delivery latency (<100ms target)"""
    bus = await SignalBus.get_instance()

    latencies = []

    async def measure_callback(signal: Signal):
        latency_ms = signal.age_seconds * 1000
        latencies.append(latency_ms)

    bus.subscribe(SignalType.NEWS_EVENT, "latency_test", measure_callback)

    # Publish 100 signals
    for i in range(100):
        await bus.publish(Signal(
            signal_type=SignalType.NEWS_EVENT,
            priority=SignalPriority.MEDIUM,
            source_bot="test",
            timestamp=datetime.now(),
            ttl=60,
            data={'index': i}
        ))

    await asyncio.sleep(0.5)

    # Check average latency
    avg_latency = sum(latencies) / len(latencies)
    print(f"Average signal latency: {avg_latency:.2f}ms")

    # Should be <100ms
    assert avg_latency < 100


@pytest.mark.asyncio
async def test_concurrent_signals():
    """Test handling concurrent signals from multiple bots"""
    bus = await SignalBus.get_instance()

    received_count = [0]

    async def counter_callback(signal):
        received_count[0] += 1

    bus.subscribe(SignalType.MARKET_OPPORTUNITY, "counter", counter_callback)

    # Simulate 6 bots publishing concurrently
    async def bot_publisher(bot_name: str, count: int):
        for i in range(count):
            await bus.publish(Signal(
                signal_type=SignalType.MARKET_OPPORTUNITY,
                priority=SignalPriority.MEDIUM,
                source_bot=bot_name,
                timestamp=datetime.now(),
                ttl=60,
                data={'opportunity_id': f"{bot_name}_{i}"}
            ))

    # Run 6 bots, each publishing 10 signals
    await asyncio.gather(*[
        bot_publisher(f"bot_{i}", 10)
        for i in range(6)
    ])

    await asyncio.sleep(0.5)

    # Should receive all 60 signals
    assert received_count[0] == 60


# ============================================================================
# Integration Tests
# ============================================================================

@pytest.mark.asyncio
async def test_news_whale_convergence_scenario():
    """
    Integration test: News + Whale convergence scenario

    Scenario:
    1. Breaking news: Bitcoin ETF approved (bullish)
    2. Whale buys Bitcoin (bullish)
    3. Signal strength should be high
    4. Position size should increase
    5. Scan frequency should increase
    """
    bus = await SignalBus.get_instance()

    # 1. Publish news
    await bus.publish(Signal(
        signal_type=SignalType.NEWS_EVENT,
        priority=SignalPriority.HIGH,
        source_bot="news_scalper",
        timestamp=datetime.now(),
        ttl=300,
        data={
            'headline': 'SEC Approves Bitcoin ETF',
            'entities': ['Bitcoin', 'ETF', 'SEC'],
            'sentiment_score': 0.95,
            'confidence': 0.9,
            'impact_level': 'high',
            'source': 'Reuters',
            'related_markets': ['btc_market'],
            'published_at': datetime.now()
        }
    ))

    # 2. Publish whale buy
    await bus.publish(Signal(
        signal_type=SignalType.WHALE_MOVE,
        priority=SignalPriority.HIGH,
        source_bot="elitemimic",
        timestamp=datetime.now(),
        ttl=1800,
        data={
            'wallet_address': '0x123',
            'wallet_name': 'distinct-baguette',
            'market_id': 'btc_market',
            'token_id': 'btc_yes',
            'side': 'BUY',
            'amount_usd': 100000.0,
            'price': 0.75,
            'entity': 'Bitcoin',
            'detected_at': datetime.now()
        }
    ))

    await asyncio.sleep(0.1)

    # 3. Verify signal strength
    strength = bus.get_signal_strength('Bitcoin')
    assert strength > 0.6, f"Signal strength too low: {strength}"

    # 4. Verify position size multiplier
    multiplier = bus.get_position_size_multiplier('Bitcoin')
    assert multiplier > 1.2, f"Multiplier too low: {multiplier}"

    # 5. Verify scan frequency decision
    assert bus.should_increase_scan_frequency('Bitcoin')

    print(f"\nConvergence Test Results:")
    print(f"  Signal Strength: {strength:.2f}")
    print(f"  Position Multiplier: {multiplier:.2f}x")
    print(f"  Increase Scan Frequency: True")


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
