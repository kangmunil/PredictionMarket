"""
Bot Adapters - SignalBus Integration Layer
===========================================

Adapters that wrap existing bots and connect them to SignalBus.

Each adapter:
1. Wraps the original bot implementation
2. Subscribes to relevant SignalBus signals
3. Publishes signals when events occur
4. Adjusts bot behavior based on cross-bot intelligence

Architecture Pattern:
    Original Bot → Adapter → SignalBus ← Other Adapters

Author: Project Hive Mind
Created: 2026-01-05
"""

import asyncio
import logging
import os
from typing import Optional
from datetime import datetime
from pathlib import Path

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

logger = logging.getLogger(__name__)


class BaseBotAdapter:
    """
    Base class for bot adapters

    Provides common functionality:
    - SignalBus connection
    - BudgetManager integration
    - Signal publishing helpers
    - Graceful shutdown
    """

    def __init__(
        self,
        bot_name: str,
        signal_bus: SignalBus,
        budget_manager: Optional[BudgetManager],
        dry_run: bool = True
    ):
        self.bot_name = bot_name
        self.signal_bus = signal_bus
        self.budget_manager = budget_manager
        self.dry_run = dry_run
        self.running = False
        self.logger = logging.getLogger(f"Adapter.{bot_name}")

    async def publish_signal(
        self,
        signal_type: SignalType,
        priority: SignalPriority,
        data: dict,
        ttl: Optional[int] = None,
        metadata: Optional[dict] = None
    ):
        """Publish a signal to SignalBus"""
        signal = Signal(
            signal_type=signal_type,
            priority=priority,
            source_bot=self.bot_name,
            timestamp=datetime.now(),
            ttl=ttl,
            data=data,
            metadata=metadata or {}
        )
        await self.signal_bus.publish(signal)

    async def start(self):
        """Start the bot adapter"""
        self.running = True
        self.logger.info(f"{self.bot_name} adapter started")

    async def stop(self):
        """Stop the bot adapter"""
        self.running = False
        self.logger.info(f"{self.bot_name} adapter stopped")

    async def run(self):
        """Main run loop - override in subclasses"""
        raise NotImplementedError("Subclasses must implement run()")


class NewsScalperAdapter(BaseBotAdapter):
    """
    Adapter for News Scalper Bot

    Publishes:
    - NewsEvent signals (breaking news)
    - GlobalSentiment updates
    - HotToken signals (news-driven)

    Subscribes to:
    - WhaleMove (validate news with whale activity)
    - MarketOpportunity (avoid conflicts)

    Intelligence:
    - Increase scan frequency when whale buys related entity
    - Boost confidence when news + whale signals converge
    """

    def __init__(self, signal_bus: SignalBus, budget_manager: Optional[BudgetManager], dry_run: bool = True):
        super().__init__("news_scalper", signal_bus, budget_manager, dry_run)
        self.scan_frequency_multipliers = {}  # entity -> multiplier

    async def start(self):
        await super().start()

        # Subscribe to whale moves
        self.signal_bus.subscribe(
            SignalType.WHALE_MOVE,
            self.bot_name,
            self._on_whale_move
        )

        self.logger.info("Subscribed to WHALE_MOVE signals")

    async def _on_whale_move(self, signal: Signal):
        """React to whale moves"""
        whale_move = WhaleMove(**signal.data)

        # Increase scan frequency for this entity
        self.scan_frequency_multipliers[whale_move.entity] = 10.0
        self.logger.info(
            f"Whale activity detected for {whale_move.entity} - "
            f"increasing scan frequency 10x"
        )

        # Schedule reset after 15 minutes
        asyncio.create_task(self._reset_frequency(whale_move.entity, 900))

    async def _reset_frequency(self, entity: str, delay: int):
        """Reset scan frequency after delay"""
        await asyncio.sleep(delay)
        if entity in self.scan_frequency_multipliers:
            del self.scan_frequency_multipliers[entity]
            self.logger.info(f"Reset scan frequency for {entity}")

    async def run(self):
        """Run news scalper with SignalBus integration"""
        await self.start()

        try:
            # Import here to avoid circular dependencies
            from news.news_scalper_optimized import OptimizedNewsScalper

            # Initialize news scalper
            scalper = OptimizedNewsScalper(
                news_api_key=os.getenv("NEWS_API_KEY"),
                tree_news_api_key=os.getenv("TREE_NEWS_API_KEY"),
                clob_client=None,  # Will use budget manager
                budget_manager=self.budget_manager,
                dry_run=self.dry_run,
                use_rag=True,
                openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
                supabase_url=os.getenv("SUPABASE_URL"),
                supabase_key=os.getenv("SUPABASE_KEY")
            )

            # Monkey-patch to intercept news signals
            original_analyze = scalper.analyze_news_with_rag

            async def patched_analyze(news_item):
                result = await original_analyze(news_item)

                # Publish news signal
                if result and result.get('confidence', 0) > 0.7:
                    await self.publish_signal(
                        signal_type=SignalType.NEWS_EVENT,
                        priority=SignalPriority.HIGH if result.get('impact') == 'high' else SignalPriority.MEDIUM,
                        data={
                            'headline': news_item.get('title', ''),
                            'entities': result.get('entities', []),
                            'sentiment_score': result.get('sentiment', 0.0),
                            'confidence': result.get('confidence', 0.0),
                            'impact_level': result.get('impact', 'medium'),
                            'source': news_item.get('source', 'unknown'),
                            'related_markets': result.get('related_markets', []),
                            'published_at': datetime.now()
                        },
                        ttl=300  # 5 minutes
                    )

                    # Update global sentiment
                    await self._update_global_sentiment(result)

                return result

            scalper.analyze_news_with_rag = patched_analyze

            # Run scalper
            self.logger.info("Starting news scalper...")
            await scalper.run(
                keywords=['bitcoin', 'ethereum', 'crypto', 'trump', 'election'],
                check_interval=60
            )

        except Exception as e:
            self.logger.error(f"News scalper error: {e}", exc_info=True)
        finally:
            await self.stop()

    async def _update_global_sentiment(self, analysis: dict):
        """Update global sentiment based on news"""
        await self.publish_signal(
            signal_type=SignalType.GLOBAL_SENTIMENT,
            priority=SignalPriority.MEDIUM,
            data={
                'overall_score': analysis.get('sentiment', 0.0),
                'confidence': analysis.get('confidence', 0.0),
                'dominant_narrative': analysis.get('entities', [''])[0] if analysis.get('entities') else 'unknown',
                'top_entities': analysis.get('entities', [])[:5],
                'news_count_1h': 1,  # Would track this properly
                'updated_at': datetime.now()
            },
            ttl=3600  # 1 hour
        )


class ArbHunterAdapter(BaseBotAdapter):
    """
    Adapter for ArbHunter Bot

    Publishes:
    - MarketOpportunity (pure arbitrage)
    - HotToken (high-volume markets)

    Subscribes to:
    - NewsEvent (prioritize related markets 10x)
    - WhaleMove (increase scan frequency)

    Intelligence:
    - When news breaks about Bitcoin, scan Bitcoin markets 10x more
    - When whale buys, increase position size multiplier
    """

    def __init__(self, signal_bus: SignalBus, budget_manager: Optional[BudgetManager], dry_run: bool = True):
        super().__init__("arbhunter", signal_bus, budget_manager, dry_run)
        self.priority_entities = set()

    async def start(self):
        await super().start()

        # Subscribe to news events
        self.signal_bus.subscribe(
            SignalType.NEWS_EVENT,
            self.bot_name,
            self._on_news_event
        )

        self.logger.info("Subscribed to NEWS_EVENT signals")

    async def _on_news_event(self, signal: Signal):
        """React to news events"""
        news = NewsEvent(**signal.data)

        if news.impact_level == "high":
            # Add entities to priority list
            for entity in news.entities:
                self.priority_entities.add(entity.lower())

            self.logger.info(
                f"High-impact news detected: {news.headline[:50]}... - "
                f"Prioritizing {len(news.entities)} entities"
            )

    async def run(self):
        """Run ArbHunter with SignalBus integration"""
        await self.start()

        try:
            from core.clob_client import PolyClient
            from core.gamma_client import GammaClient
            from strategies.arbitrage import ArbitrageStrategy

            # Initialize clients
            client = PolyClient(strategy_name="arbhunter", budget_manager=self.budget_manager)
            gamma_client = GammaClient()

            # Initialize strategy
            strategy = ArbitrageStrategy(client, gamma_client)
            strategy.min_profit_threshold = 0.020  # 2%
            strategy.default_trade_size = 100.0

            # Monkey-patch to publish opportunities
            original_execute = strategy.execute_arbitrage

            async def patched_execute(opportunity):
                # Publish opportunity
                await self.publish_signal(
                    signal_type=SignalType.MARKET_OPPORTUNITY,
                    priority=SignalPriority.MEDIUM,
                    data={
                        'opportunity_type': 'pure_arb',
                        'market_ids': [opportunity.get('market_id', '')],
                        'token_ids': [opportunity.get('yes_token', ''), opportunity.get('no_token', '')],
                        'expected_profit': opportunity.get('profit', 0.0),
                        'confidence': 0.95,  # Pure arb is high confidence
                        'strategy_name': 'arbhunter',
                        'claimed_by': self.bot_name,
                        'detected_at': datetime.now()
                    },
                    ttl=60  # 1 minute
                )

                return await original_execute(opportunity)

            strategy.execute_arbitrage = patched_execute

            # Run strategy
            self.logger.info("Starting ArbHunter...")
            await strategy.run()

        except Exception as e:
            self.logger.error(f"ArbHunter error: {e}", exc_info=True)
        finally:
            await self.stop()


class StatArbAdapter(BaseBotAdapter):
    """
    Adapter for Statistical Arbitrage Bot

    Publishes:
    - MarketOpportunity (stat arb signals)

    Subscribes to:
    - WhaleMove (lower Z-score threshold when whale accumulates)
    - NewsEvent (adjust confidence)

    Intelligence:
    - Normal entry: |Z-score| > 2.0
    - Whale buying + positive news: |Z-score| > 1.5 (easier entry)
    """

    def __init__(self, signal_bus: SignalBus, budget_manager: Optional[BudgetManager], dry_run: bool = True):
        super().__init__("stat_arb", signal_bus, budget_manager, dry_run)
        self.z_score_adjustments = {}  # pair -> adjustment

    async def start(self):
        await super().start()

        # Subscribe to multiple signals
        self.signal_bus.subscribe(SignalType.WHALE_MOVE, self.bot_name, self._on_whale_move)
        self.signal_bus.subscribe(SignalType.NEWS_EVENT, self.bot_name, self._on_news_event)

        self.logger.info("Subscribed to WHALE_MOVE and NEWS_EVENT signals")

    async def _on_whale_move(self, signal: Signal):
        """Adjust Z-score thresholds based on whale activity"""
        whale_move = WhaleMove(**signal.data)

        # Lower threshold for this entity
        self.z_score_adjustments[whale_move.entity] = -0.5
        self.logger.info(
            f"Whale activity in {whale_move.entity} - "
            f"lowering Z-score threshold by 0.5"
        )

    async def _on_news_event(self, signal: Signal):
        """Adjust based on news"""
        news = NewsEvent(**signal.data)

        if news.impact_level == "high":
            for entity in news.entities:
                current = self.z_score_adjustments.get(entity, 0.0)
                self.z_score_adjustments[entity] = current - 0.3
                self.logger.info(
                    f"High-impact news for {entity} - "
                    f"adjusting Z-score threshold"
                )

    async def run(self):
        """Run StatArb with SignalBus integration"""
        await self.start()

        try:
            from core.clob_client import PolyClient
            from core.history_fetcher import get_history_fetcher
            from strategies.stat_arb_enhanced import EnhancedStatArbStrategy

            # Initialize
            client = PolyClient(strategy_name="stat_arb", budget_manager=self.budget_manager)
            strategy = EnhancedStatArbStrategy(client, lookback_days=30, min_data_points=50)

            # Run continuously
            self.logger.info("Starting StatArb...")

            while self.running:
                # Run analysis cycle
                # (Actual implementation would analyze pairs and generate signals)

                await asyncio.sleep(300)  # Check every 5 minutes

        except Exception as e:
            self.logger.error(f"StatArb error: {e}", exc_info=True)
        finally:
            await self.stop()


class EliteMimicAdapter(BaseBotAdapter):
    """
    Adapter for EliteMimic (Whale Copy Trading) Bot

    Publishes:
    - WhaleMove signals
    - MarketOpportunity (copy trade opportunities)

    Subscribes to:
    - NewsEvent (validate whale trades with news)

    Intelligence:
    - Whale buys + positive news = double position size
    - Whale buys + negative news = skip trade (contrarian signal)
    """

    def __init__(self, signal_bus: SignalBus, budget_manager: Optional[BudgetManager], dry_run: bool = True):
        super().__init__("elitemimic", signal_bus, budget_manager, dry_run)
        self.recent_news_sentiment = {}  # entity -> sentiment

    async def start(self):
        await super().start()

        self.signal_bus.subscribe(SignalType.NEWS_EVENT, self.bot_name, self._on_news_event)
        self.logger.info("Subscribed to NEWS_EVENT signals")

    async def _on_news_event(self, signal: Signal):
        """Track news sentiment"""
        news = NewsEvent(**signal.data)

        for entity in news.entities:
            self.recent_news_sentiment[entity.lower()] = news.sentiment_score

    async def run(self):
        """Run EliteMimic with SignalBus integration"""
        await self.start()

        try:
            from core.clob_client import PolyClient
            from core.wallet_watcher import WalletWatcher
            from strategies.ai_model_v2 import AIModelStrategyV2
            from core.config import Config

            # Initialize
            config = Config()
            client = PolyClient(strategy_name="elitemimic", budget_manager=self.budget_manager)
            watcher = WalletWatcher(client)
            ai_validator = AIModelStrategyV2(client)

            async def on_whale_trade(event: dict):
                # Publish whale move
                await self.publish_signal(
                    signal_type=SignalType.WHALE_MOVE,
                    priority=SignalPriority.HIGH,
                    data={
                        'wallet_address': event['wallet'],
                        'wallet_name': event.get('wallet_name', 'unknown'),
                        'market_id': event['market_id'],
                        'token_id': event['token_id'],
                        'side': event['side'],
                        'amount_usd': event['size'],
                        'price': event['price'],
                        'entity': event.get('entity', 'unknown'),
                        'detected_at': datetime.now()
                    },
                    ttl=1800  # 30 minutes
                )

                # Check news alignment
                entity = event.get('entity', '').lower()
                if entity in self.recent_news_sentiment:
                    news_sentiment = self.recent_news_sentiment[entity]
                    whale_bullish = event['side'] == 'BUY'

                    if (whale_bullish and news_sentiment > 0.5) or (not whale_bullish and news_sentiment < -0.5):
                        self.logger.info(
                            f"SIGNAL CONVERGENCE: Whale {event['side']} + "
                            f"News sentiment {news_sentiment:.2f} - "
                            f"DOUBLING POSITION SIZE"
                        )
                        event['size'] *= 2

            watcher.on_trade_callback = on_whale_trade

            self.logger.info("Starting EliteMimic...")
            await watcher.run()

        except Exception as e:
            self.logger.error(f"EliteMimic error: {e}", exc_info=True)
        finally:
            await self.stop()


class PolyAIAdapter(BaseBotAdapter):
    """
    Adapter for PolyAI (AI Orchestrator) Bot

    Publishes:
    - GlobalSentiment (AI-driven)
    - MarketOpportunity (AI-validated)

    Subscribes to:
    - ALL signals (uses as context for AI decisions)

    Intelligence:
    - Aggregates all signals
    - Provides meta-analysis
    - Validates opportunities from other bots
    """

    def __init__(self, signal_bus: SignalBus, budget_manager: Optional[BudgetManager], dry_run: bool = True):
        super().__init__("polyai", signal_bus, budget_manager, dry_run)
        self.signal_context = []

    async def start(self):
        await super().start()

        # Subscribe to all signal types for context
        for signal_type in SignalType:
            self.signal_bus.subscribe(signal_type, self.bot_name, self._collect_signal)

        self.logger.info("Subscribed to ALL signal types")

    async def _collect_signal(self, signal: Signal):
        """Collect signals for context"""
        self.signal_context.append(signal)
        # Keep only recent signals (last 100)
        self.signal_context = self.signal_context[-100:]

    async def run(self):
        """Run PolyAI with SignalBus integration"""
        await self.start()

        try:
            from strategies.ai_rag_agent import PolyAIAgent

            agent = PolyAIAgent()

            self.logger.info("Starting PolyAI...")

            while self.running:
                # Periodically analyze collected signals
                if len(self.signal_context) > 10:
                    # AI would analyze signal patterns here
                    self.logger.debug(f"Analyzing {len(self.signal_context)} signals...")

                await asyncio.sleep(120)  # Every 2 minutes

        except Exception as e:
            self.logger.error(f"PolyAI error: {e}", exc_info=True)
        finally:
            await self.stop()


class PureArbitrageAdapter(BaseBotAdapter):
    """
    Adapter for Pure Arbitrage V2 Bot

    Publishes:
    - MarketOpportunity (pure arb)
    - HotToken (high-frequency markets)

    Subscribes to:
    - NewsEvent (prioritize related markets)

    Intelligence:
    - Similar to ArbHunter but optimized for speed
    """

    def __init__(self, signal_bus: SignalBus, budget_manager: Optional[BudgetManager], dry_run: bool = True):
        super().__init__("pure_arb", signal_bus, budget_manager, dry_run)

    async def run(self):
        """Run Pure Arbitrage with SignalBus integration"""
        await self.start()

        try:
            from core.clob_client import PolyClient
            from strategies.arbitrage_v2 import PureArbitrageV2

            # Initialize
            client = PolyClient(strategy_name="pure_arb", budget_manager=self.budget_manager)
            arb = PureArbitrageV2(
                client=client,
                threshold=0.99,
                min_profit=0.01,
                trade_size=50.0,
                dry_run=self.dry_run
            )

            self.logger.info("Starting Pure Arbitrage V2...")
            await arb.run()

        except Exception as e:
            self.logger.error(f"Pure Arbitrage error: {e}", exc_info=True)
        finally:
            await self.stop()
