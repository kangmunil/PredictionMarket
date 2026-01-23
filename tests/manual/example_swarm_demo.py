#!/usr/bin/env python3
"""
Project Hive Mind - Interactive Demo
=====================================

Demonstrates swarm intelligence with realistic signal flow.

This script simulates:
1. Breaking news events
2. Whale wallet activity
3. Cross-bot signal propagation
4. Position size adjustments
5. Budget coordination

Author: Project Hive Mind
Created: 2026-01-05
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.core.signal_bus import (
    SignalBus,
    Signal,
    SignalType,
    SignalPriority,
    get_signal_bus
)


async def simulate_news_event(bus: SignalBus):
    """Simulate breaking news event"""
    print("\n" + "=" * 80)
    print("📰 BREAKING NEWS: SEC Approves Bitcoin ETF!")
    print("=" * 80)

    # News Scalper publishes news signal
    await bus.publish(Signal(
        signal_type=SignalType.NEWS_EVENT,
        priority=SignalPriority.HIGH,
        source_bot="news_scalper",
        timestamp=datetime.now(),
        ttl=300,  # 5 minutes
        data={
            'headline': 'SEC Approves First Bitcoin Spot ETF',
            'entities': ['Bitcoin', 'ETF', 'SEC'],
            'sentiment_score': 0.95,
            'confidence': 0.9,
            'impact_level': 'high',
            'source': 'Reuters',
            'related_markets': ['bitcoin_100k', 'crypto_adoption'],
            'published_at': datetime.now()
        }
    ))

    print("✅ News signal published to SignalBus")
    print("   - Signal Type: NEWS_EVENT")
    print("   - Priority: HIGH")
    print("   - Sentiment: 0.95 (very bullish)")
    print("   - Impact: high")

    # Update global sentiment
    await bus.publish(Signal(
        signal_type=SignalType.GLOBAL_SENTIMENT,
        priority=SignalPriority.MEDIUM,
        source_bot="news_scalper",
        timestamp=datetime.now(),
        ttl=3600,
        data={
            'overall_score': 0.85,
            'confidence': 0.9,
            'dominant_narrative': 'Bitcoin ETF Approval',
            'top_entities': ['Bitcoin', 'ETF', 'SEC', 'BlackRock', 'Crypto'],
            'news_count_1h': 47,
            'updated_at': datetime.now()
        }
    ))

    print("✅ Global sentiment updated")
    print("   - Overall Score: 0.85 (bullish)")
    print("   - Narrative: Bitcoin ETF Approval")

    await asyncio.sleep(1)


async def simulate_whale_activity(bus: SignalBus):
    """Simulate whale wallet buying"""
    print("\n" + "=" * 80)
    print("🐋 WHALE ALERT: distinct-baguette buying Bitcoin markets!")
    print("=" * 80)

    # EliteMimic detects whale buy
    await bus.publish(Signal(
        signal_type=SignalType.WHALE_MOVE,
        priority=SignalPriority.HIGH,
        source_bot="elitemimic",
        timestamp=datetime.now(),
        ttl=1800,  # 30 minutes
        data={
            'wallet_address': '0xe00740bce98a594e26861838885ab310ec3b548c',
            'wallet_name': 'distinct-baguette',
            'market_id': 'bitcoin_100k_by_2025',
            'token_id': 'yes_token_123',
            'side': 'BUY',
            'amount_usd': 150000.0,
            'price': 0.72,
            'entity': 'Bitcoin',
            'detected_at': datetime.now()
        }
    ))

    print("✅ Whale move signal published")
    print("   - Wallet: distinct-baguette (top trader)")
    print("   - Action: BUY")
    print("   - Amount: $150,000")
    print("   - Price: $0.72")
    print("   - Entity: Bitcoin")

    await asyncio.sleep(1)


async def demonstrate_signal_convergence(bus: SignalBus):
    """Demonstrate signal strength calculation"""
    print("\n" + "=" * 80)
    print("🧠 SIGNAL CONVERGENCE ANALYSIS")
    print("=" * 80)

    # Calculate aggregate signal strength
    signal_strength = bus.get_signal_strength('Bitcoin')

    print(f"\nAggregate Signal Strength for Bitcoin: {signal_strength:.2f}")
    print("\nBreakdown:")
    print(f"  📰 News Sentiment (40% weight): 0.95 → {0.95 * 0.4:.2f}")
    print(f"  🐋 Whale Activity (30% weight): 1.0 (BUY) → {1.0 * 0.3:.2f}")
    print(f"  🌍 Global Sentiment (20% weight): 0.85 → {0.85 * 0.2:.2f}")
    print(f"  🔥 Hot Token Bonus (10% weight): 0.5 → {0.5 * 0.1:.2f}")

    # Position size multiplier
    multiplier = bus.get_position_size_multiplier('Bitcoin')

    print(f"\n💰 Position Size Multiplier: {multiplier:.2f}x")
    print(f"\nExample: Standard trade = $100")
    print(f"         Enhanced trade = ${100 * multiplier:.2f}")
    print(f"         Increase: +{(multiplier - 1) * 100:.0f}%")

    # Scan frequency decision
    should_increase = bus.should_increase_scan_frequency('Bitcoin')

    print(f"\n🔍 Increase Scan Frequency: {'YES' if should_increase else 'NO'}")
    if should_increase:
        print("   ArbHunter will scan Bitcoin markets 10x more frequently")
        print("   Normal: Every 60s")
        print("   Enhanced: Every 6s")

    await asyncio.sleep(2)


async def demonstrate_bot_reactions(bus: SignalBus):
    """Show how each bot reacts to signals"""
    print("\n" + "=" * 80)
    print("🤖 BOT REACTIONS TO SIGNAL CONVERGENCE")
    print("=" * 80)

    print("\n🎯 ArbHunter:")
    print("   ✓ Received NEWS_EVENT signal")
    print("   ✓ Bitcoin added to priority scan list")
    print("   ✓ Scan frequency: 60s → 6s (10x increase)")
    print("   ✓ Position size: $100 → $175 (1.75x multiplier)")

    await asyncio.sleep(1)

    print("\n📊 StatArb:")
    print("   ✓ Received NEWS_EVENT signal")
    print("   ✓ Received WHALE_MOVE signal")
    print("   ✓ Z-score threshold lowered: 2.0 → 1.5")
    print("   ✓ Easier entry for Bitcoin pairs")
    print("   ✓ Position size: $100 → $175 (1.75x multiplier)")

    await asyncio.sleep(1)

    print("\n🐋 EliteMimic:")
    print("   ✓ Detected whale buy + positive news")
    print("   ✓ SIGNAL CONVERGENCE confirmed")
    print("   ✓ Copy trade with 2x position size")
    print("   ✓ Standard copy: $100 → Enhanced: $200")

    await asyncio.sleep(1)

    print("\n📰 News Scalper:")
    print("   ✓ Received WHALE_MOVE signal")
    print("   ✓ Validates news with whale activity")
    print("   ✓ Confidence boost: 0.80 → 0.95")
    print("   ✓ Position size: $100 → $175 (1.75x multiplier)")

    await asyncio.sleep(1)

    print("\n🧠 PolyAI:")
    print("   ✓ Received all signals (meta-analysis)")
    print("   ✓ News + Whale + Sentiment = HIGH CONFIDENCE")
    print("   ✓ Validates opportunities from other bots")
    print("   ✓ Recommends: LONG Bitcoin markets")

    await asyncio.sleep(1)

    print("\n⚡ Pure Arbitrage:")
    print("   ✓ Received NEWS_EVENT signal")
    print("   ✓ Bitcoin markets prioritized")
    print("   ✓ Scan frequency increased")
    print("   ✓ Position size boosted on Bitcoin arb opportunities")


async def demonstrate_hot_token_tracking(bus: SignalBus):
    """Demonstrate hot token detection"""
    print("\n" + "=" * 80)
    print("🔥 HOT TOKEN DETECTION")
    print("=" * 80)

    # ArbHunter publishes hot token
    await bus.publish(Signal(
        signal_type=SignalType.HOT_TOKEN,
        priority=SignalPriority.MEDIUM,
        source_bot="arbhunter",
        timestamp=datetime.now(),
        ttl=3600,
        data={
            'token_id': 'btc_100k_yes',
            'condition_id': 'btc_condition_123',
            'market_name': 'Bitcoin > $100k by Dec 2025',
            'volume_1h': 287500.0,
            'price_velocity': 3.2,  # % per minute
            'volatility': 0.18,
            'reason': 'news_spike + whale_buy',
            'detected_at': datetime.now()
        }
    ))

    print("✅ Hot token detected:")
    print("   Market: Bitcoin > $100k by Dec 2025")
    print("   Volume (1h): $287,500")
    print("   Price Velocity: 3.2% per minute")
    print("   Reason: news_spike + whale_buy")

    print("\n📈 All bots now prioritize this token:")
    print("   - Faster scanning")
    print("   - Higher position sizes")
    print("   - More aggressive entry thresholds")

    await asyncio.sleep(1)


async def demonstrate_market_opportunity(bus: SignalBus):
    """Demonstrate opportunity claiming"""
    print("\n" + "=" * 80)
    print("💎 MARKET OPPORTUNITY DETECTION")
    print("=" * 80)

    # ArbHunter finds pure arbitrage
    await bus.publish(Signal(
        signal_type=SignalType.MARKET_OPPORTUNITY,
        priority=SignalPriority.MEDIUM,
        source_bot="arbhunter",
        timestamp=datetime.now(),
        ttl=60,
        data={
            'opportunity_type': 'pure_arb',
            'market_ids': ['btc_100k_market'],
            'token_ids': ['yes_token', 'no_token'],
            'expected_profit': 2.3,  # %
            'confidence': 0.95,
            'strategy_name': 'pure_arbitrage',
            'claimed_by': 'arbhunter',
            'detected_at': datetime.now()
        }
    ))

    print("✅ Pure arbitrage opportunity found:")
    print("   Market: Bitcoin > $100k")
    print("   Type: YES + NO < $1.00")
    print("   Expected Profit: 2.3%")
    print("   Claimed by: arbhunter")

    print("\n🔒 Opportunity Claiming:")
    print("   - ArbHunter claimed this opportunity")
    print("   - Other bots see it's claimed and skip")
    print("   - Prevents multiple bots from trading same opportunity")
    print("   - Eliminates internal competition")

    await asyncio.sleep(1)


async def demonstrate_metrics(bus: SignalBus):
    """Display SignalBus metrics"""
    print("\n" + "=" * 80)
    print("📊 SIGNALBUS PERFORMANCE METRICS")
    print("=" * 80)

    metrics = bus.get_metrics()

    print(f"\nSignals:")
    print(f"  Published: {metrics['signals_published']}")
    print(f"  Delivered: {metrics['signals_delivered']}")

    print(f"\nPerformance:")
    print(f"  Average Latency: {metrics['avg_latency_ms']:.1f}ms")
    print(f"  Max Latency: {metrics['max_latency_ms']:.1f}ms")
    print(f"  Target: <100ms ✓" if metrics['avg_latency_ms'] < 100 else "  Target: <100ms ✗")

    print(f"\nActive State:")
    print(f"  Hot Tokens: {metrics['hot_tokens_count']}")
    print(f"  Whale Moves (recent): {metrics['whale_moves_count']}")
    print(f"  News Events (recent): {metrics['news_events_count']}")
    print(f"  Opportunities: {metrics['opportunities_count']}")

    print(f"\nSubscribers:")
    print(f"  Active: {metrics['active_subscribers']}")

    await asyncio.sleep(1)


async def demonstrate_state_queries(bus: SignalBus):
    """Demonstrate state query methods"""
    print("\n" + "=" * 80)
    print("🔍 STATE QUERY EXAMPLES")
    print("=" * 80)

    # Global sentiment
    sentiment = bus.get_global_sentiment()
    if sentiment:
        print(f"\nGlobal Sentiment:")
        print(f"  Score: {sentiment.overall_score:.2f}")
        print(f"  Narrative: {sentiment.dominant_narrative}")
        print(f"  Top Entities: {', '.join(sentiment.top_entities[:3])}")

    # Hot tokens
    hot_tokens = bus.get_hot_tokens(top_n=3)
    if hot_tokens:
        print(f"\nTop Hot Tokens:")
        for i, token in enumerate(hot_tokens, 1):
            print(f"  {i}. {token.market_name}")
            print(f"     Volume: ${token.volume_1h:,.0f}")
            print(f"     Reason: {token.reason}")

    # Recent whale moves
    whale_moves = bus.get_whale_moves(minutes=60)
    if whale_moves:
        print(f"\nRecent Whale Moves:")
        for move in whale_moves:
            print(f"  • {move.wallet_name}: {move.side} {move.entity}")
            print(f"    Amount: ${move.amount_usd:,.0f}")

    # Related news
    related_news = bus.get_related_news('Bitcoin', minutes=60)
    if related_news:
        print(f"\nBitcoin-Related News:")
        for news in related_news:
            print(f"  • {news.headline[:60]}...")
            print(f"    Sentiment: {news.sentiment_score:.2f}")

    await asyncio.sleep(1)


async def main():
    """Run complete demonstration"""
    print("\n" + "=" * 80)
    print("PROJECT HIVE MIND - Interactive Swarm Intelligence Demo")
    print("=" * 80)
    print("\nThis demo simulates realistic signal flow through the swarm.")
    print("Watch how bots coordinate and amplify signals when they converge.")
    print("\nPress Ctrl+C at any time to exit.")

    # Get SignalBus instance
    bus = await get_signal_bus()

    try:
        # Simulate events
        await simulate_news_event(bus)
        await simulate_whale_activity(bus)
        await demonstrate_signal_convergence(bus)
        await demonstrate_bot_reactions(bus)
        await demonstrate_hot_token_tracking(bus)
        await demonstrate_market_opportunity(bus)
        await demonstrate_metrics(bus)
        await demonstrate_state_queries(bus)

        # Final summary
        print("\n" + "=" * 80)
        print("✅ DEMO COMPLETE")
        print("=" * 80)

        print("\n📚 Key Takeaways:")
        print("   1. SignalBus enables real-time bot coordination")
        print("   2. Signal convergence amplifies trading decisions")
        print("   3. Cross-bot intelligence increases win rates")
        print("   4. Latency stays under 100ms for fast execution")
        print("   5. Opportunity claiming prevents internal conflicts")

        print("\n🚀 Next Steps:")
        print("   1. Read SWARM_ARCHITECTURE.md for full details")
        print("   2. Run: python3 run_swarm.py --dry-run")
        print("   3. Monitor signal flow in real markets")
        print("   4. Start live trading with small budget")

        print("\n" + "=" * 80)

        # Stop SignalBus
        await bus.stop()

    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user")
        await bus.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
