"""
News Scalping Trading Engine - OPTIMIZED VERSION
=================================================

Optimized for speed: Target latency < 2 seconds

Optimizations:
1. Parallel news processing (asyncio.gather)
2. Market pre-caching (Redis/memory)
3. Model pre-warming (FinBERT loaded on startup)
4. Batch sentiment analysis
5. Connection pooling

Author: ArbHunter V2 (Optimized)
Created: 2026-01-03
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta
from decimal import Decimal
import time
from collections import defaultdict
import os
import hashlib
import json
from contextlib import suppress
from dateutil import parser as date_parser

from .news_aggregator import NewsAggregator
from .sentiment_analyzer import SentimentAnalyzer
from .market_matcher import MarketMatcher
from src.core.risk_manager import RiskManager
from src.core.decision_logger import DecisionLogger
from src.core.allocation_manager import AllocationManager
from src.core.allocation_manager import AllocationManager
from src.core.config import Config
from src.core.fee_model import FeeModel
from src.core.aggression import seconds_to_expiry, aggression_profile
from src.core.trade_recorder import TradeRecorder

# RAG System (Advanced AI Analysis)
from src.core.rag_system_openrouter import OpenRouterRAGSystem, NewsEvent
RAG_AVAILABLE = True

logger = logging.getLogger(__name__)


from .news_client import TreeNewsStreamClient

class OptimizedNewsScalper:
    """
    Speed-optimized news scalper.
    """

    def __init__(
        self,
        news_api_key: str,
        tree_news_api_key: str,
        clob_client,
        gamma_api_url: str = "https://gamma-api.polymarket.com",
        budget_manager = None,
        dry_run: bool = True,
        use_rag: bool = True,
        openrouter_api_key: str = None,
        supabase_url: str = None,
        supabase_key: str = None,
        signal_bus = None,
        swarm_system = None,
        delta_tracker = None,
        market_specialist = None, # Added for feedback loop
        redis_client = None
    ):
        self.config = Config()
        self.news_api_key = news_api_key
        self.tree_news_api_key = tree_news_api_key
        self.market_specialist = market_specialist
        self.news_aggregator = NewsAggregator(
            news_api_key=news_api_key,
            tree_api_key=tree_news_api_key
        )
        
        # Connect to Hive Mind
        self.signal_bus = signal_bus
        self.swarm_system = swarm_system # 🐝 Reference to Orchestrator
        if self.signal_bus:
            logger.info("🧠 Connected to SignalBus (Hive Mind)")

        self.balance_allocator: Optional[AllocationManager] = None
        if os.getenv("ENABLE_BALANCE_ALLOCATOR", "false").lower() in ("1", "true", "yes", "on"):
            try:
                self.balance_allocator = AllocationManager()
                logger.info("💰 Balance-aware allocator enabled")
            except Exception as exc:
                logger.warning(f"⚠️ Could not enable balance allocator: {exc}")
        
        # Real-time Stream Client
        self.stream_client = TreeNewsStreamClient(api_key=tree_news_api_key)
        self.stream_task = None

        # Analysis Engine
        self.use_rag = use_rag and RAG_AVAILABLE
        # ... rest of init ...
        
        self.fee_model = FeeModel(taker_fee=self.config.TAKER_FEE)
        self.slippage_buffer = self.config.SLIPPAGE_BUFFER

        # Initialize Risk Manager (cap dry-run trades at $2, live at $50)
        max_bet = 2.0 if dry_run else 50.0
        risk_pct = getattr(self.config, "RISK_PER_TRADE_PERCENT", 0.02)
        self.risk_manager = RiskManager(
            max_bet_usd=max_bet,
            max_bet_cap_pct=risk_pct
        )
        
        # Initialize Decision Logger
        notifier = self.swarm_system.notifier if self.swarm_system else None
        self.decision_logger = DecisionLogger("NewsScalper", notifier=notifier)
        self.trade_recorder = TradeRecorder(filename="data/trades_log.csv")
        
        logger.info("🛡️ Risk Manager Initialized (Dynamic Kelly Sizing)")

        if self.use_rag:
            logger.info("🤖 Initializing RAG System (Advanced AI Analysis)...")
            self.rag_system = OpenRouterRAGSystem(
                openrouter_api_key=openrouter_api_key or os.getenv("OPENROUTER_API_KEY"),
                supabase_url=supabase_url or os.getenv("SUPABASE_URL"),
                supabase_key=supabase_key or os.getenv("SUPABASE_KEY")
            )
            self.sentiment_analyzer = None  # Not used in RAG mode
            logger.info("   ✅ RAG System initialized")
        else:
            logger.info("🧠 Using Basic FinBERT Sentiment Analysis...")
            self.sentiment_analyzer = SentimentAnalyzer()
            self.rag_system = None
            logger.info("   ✅ FinBERT initialized")

        self.market_matcher = MarketMatcher(gamma_api_url=gamma_api_url)
        self.clob_client = clob_client
        self.budget_manager = budget_manager
        self.dry_run = dry_run
        self.delta_tracker = delta_tracker
        self.redis = redis_client
        
        # Deduplication state
        self.processed_cache = set()
        self.processed_redis_key = "news:processed_ids"
        default_hold = "1.5"
        self.signal_cooldown = timedelta(
            minutes=float(os.getenv("NEWS_SIGNAL_COOLDOWN_MINUTES", "15"))
        )
        self.max_hold_hours = float(os.getenv("NEWS_MAX_HOLD_HOURS", default_hold))
        self.max_market_duration_days = float(os.getenv("NEWS_MAX_MARKET_DURATION_DAYS", "7.0"))

        # Bridge: Connects News to Stat Arb
        try:
            from src.strategies.stat_arb_enhanced import EnhancedStatArbStrategy
            from src.strategies.news_arb_bridge import NewsToArbBridge
            stat_strategy = EnhancedStatArbStrategy(client=clob_client)
            self.bridge = NewsToArbBridge(self, stat_strategy, self.market_matcher)
            logger.info("🌉 News-to-Arb Bridge initialized")
        except Exception as e:
            logger.warning(f"⚠️  Bridge not available: {e}")
            self.bridge = None

        # Trading config (OPTIMIZED FOR 50% PROBABILITY)
        self.min_confidence = 0.50       # 50% 확률이면 진입
        self.high_impact_threshold = 0.70 # 70% 이상이면 고영향 뉴스로 판단
        self.min_market_volume = 0.3     # 거래량 문턱 완화 (1.0 -> 0.3) - 더 많은 시장 매칭
        self.position_size = 6.0        # 기본 진입 금액 $6 (Polymarket 최소 주문 금액 $5 이상)
        self.max_positions = 5
        self.take_profit_pct = float(os.getenv("NEWS_TAKE_PROFIT_PCT", "0.05"))
        self.stop_loss_pct = float(os.getenv("NEWS_STOP_LOSS_PCT", "0.03"))
        self.trade_fee_rate = float(os.getenv("POLYMARKET_FEE_RATE", "0.001"))
        self.scale_in_multiplier = float(os.getenv("NEWS_SCALE_IN_MULTIPLIER", "0.5"))
        self.scale_in_min_usd = float(os.getenv("NEWS_SCALE_IN_MIN_USD", "5.0"))
        self.scale_in_max_usd = float(os.getenv("NEWS_SCALE_IN_MAX_USD", "15.0"))
        # Lower default EV floor to allow more trades (0.05 -> 0.025)
        self.efficient_ev_floor = float(os.getenv("NEWS_EFFICIENT_EV_FLOOR", "0.025"))
        self.inefficient_slippage_buffer = float(
            os.getenv("NEWS_INEFFICIENT_SLIPPAGE_BUFFER", "0.008")  # 0.01 -> 0.008 완화
        )
        self.phase_multipliers = {
            "EARLY": float(os.getenv("NEWS_PHASE_MULT_EARLY", "1.0")),
            "MID": float(os.getenv("NEWS_PHASE_MULT_MID", "1.2")),
            "LATE": float(os.getenv("NEWS_PHASE_MULT_LATE", "2.0")),
            "ENDGAME": float(os.getenv("NEWS_PHASE_MULT_ENDGAME", "3.0")),
        }
        self.inefficient_phase_boost = float(os.getenv("NEWS_PHASE_INEFF_BOOST", "1.2"))

        # Performance optimization: Market cache
        self.market_cache = {}  # keyword -> [markets]
        self.cache_ttl = 300  # 5 minutes
        self.cache_timestamps = {}

        # Performance optimization: Pre-loaded markets
        self.preloaded_markets = defaultdict(list)

        # State tracking
        self.positions = {}
        self.cooldown_until: Dict[str, datetime] = {}
        self.latest_signals: Dict[str, Dict[str, float]] = {}
        self.processed_news = set()
        self._subscribed_books: Set[str] = set()
        self.stats = {
            "news_checked": 0,
            "signals_generated": 0,
            "trades_executed": 0,
            "positions_opened": 0,
            "positions_closed": 0,
            "total_pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "avg_latency_ms": 0.0,
            "latencies": []
        }

        self.start_time = None
        self._is_warmed_up = False

    def _passes_cooldown_gate(
        self,
        token_id: str,
        signal_side: str,
        *,
        is_scale: bool = False,
        delta_ok: bool = False,
    ) -> bool:
        """
        Centralized cooldown enforcement. Scale-ins may bypass once the
        delta controller approves, while fresh entries remain throttle-bound.
        """
        cooldown_ts = self.cooldown_until.get(token_id)
        if not cooldown_ts:
            return True

        now = datetime.now()
        if now >= cooldown_ts:
            self.cooldown_until.pop(token_id, None)
            return True

        if is_scale and delta_ok:
            logger.info(
                "   🟢 Cooldown bypassed for scale-in (%s | side=%s)",
                token_id[:12],
                signal_side,
            )
            return True

        remaining = (cooldown_ts - now).total_seconds() / 60
        logger.info(
            "   ⏳ Cooldown active for %s (%.1fm left); skipping signal",
            token_id[:12],
            remaining,
        )
        return False

    async def _ensure_orderbook_subscription(self, token_id: str) -> None:
        """Guarantee that the SignalBus receives book data for the target token."""
        if not token_id or not self.clob_client:
            return
        if token_id in self._subscribed_books:
            return
        try:
            await self.clob_client.subscribe_orderbook([token_id])
            self._subscribed_books.add(token_id)
            logger.info("   📡 Orderbook stream subscribed for %s", token_id[:15])
            
            # ⏳ WAIT for WS Data (Race Condition Fix)
            await asyncio.sleep(2.0)
            
        except Exception as exc:
            logger.warning("   ⚠️ Failed to subscribe orderbook for %s: %s", token_id[:10], exc)

    def _set_cooldown(self, condition_id: str):
        """Set execution cooldown to prevent churn loops"""
        expiry = datetime.now() + timedelta(seconds=60)
        self.cooldowns[condition_id] = expiry
        logger.debug(f"   🧊 Cooldown set for {condition_id[:10]} until {expiry.strftime('%H:%M:%S')}")

    async def warmup(self, keywords: List[str]):
        """
        Pre-warm models and cache markets.

        This reduces first-request latency from 3-5s to <500ms.
        """
        logger.info("🔥 Warming up system...")

        # 1. Pre-load AI Model (RAG or FinBERT)
        if self.use_rag:
            logger.info("   Initializing RAG System (OpenRouter AI + ChromaDB + Supabase)...")
            start = time.time()
            # RAG System initialization (connects to Supabase, ChromaDB)
            # This is done in __init__, just log status
            logger.info(f"   ✅ RAG System ready ({time.time() - start:.1f}s)")
            logger.info(f"      - Entity Model: {os.getenv('AI_MODEL_ENTITY', 'claude-3-haiku')}")
            logger.info(f"      - Analysis Model: {os.getenv('AI_MODEL_ANALYSIS', 'claude-3.5-sonnet')}")
            logger.info(f"      - Vector Store: ChromaDB")
            logger.info(f"      - Database: Supabase")
        else:
            logger.info("   Loading FinBERT model...")
            start = time.time()
            self.sentiment_analyzer.analyze("Test headline for warming up")
            logger.info(f"   ✅ FinBERT loaded ({time.time() - start:.1f}s)")

        # 2. Pre-cache markets for keywords
        logger.info("   Pre-caching markets...")
        start = time.time()

        # Cache common markets
        for keyword in keywords:
            markets = await self.market_matcher.find_matching_markets(
                keyword,
                min_volume=10.0,  # Low threshold for caching
                max_results=20
            )
            if markets:
                self.preloaded_markets[keyword] = markets
                logger.info(f"      Cached {len(markets)} markets for '{keyword}'")

        logger.info(f"   ✅ Markets cached ({time.time() - start:.1f}s)")

        self._is_warmed_up = True
        mode = "RAG (Advanced AI)" if self.use_rag else "FinBERT (Basic)"
        logger.info(f"✅ Warmup complete! Mode: {mode}")

    async def validate_trade(self, market_id: str, outcome: str, price: float) -> bool:
        """
        AI Validator Interface for WalletWatcher.
        Checks if recent news supports this trade.
        """
        # 1. Fetch recent news for this market/topic
        # (Simplified: assumes market_id is related to monitored keywords or extracts entity)
        # For now, we do a quick sentiment check on Cached news or latest headlines
        
        # TODO: Extract entity from market_id properly
        entity = "bitcoin" # Placeholder: In real logic, query CLOB for market question
        
        # Quick sentiment check using cache or latest analysis
        # If we have positive sentiment in cache for this entity, APPROVED.
        
        # Check if we have active signals/positions for this entity in recent memory
        # Or re-run sentiment on latest news
        
        # For prototype: Return True if we have ANY positive signals recently
        if self.stats["signals_generated"] > 0:
             # Just an example logic: If scalper is finding signals, market is hot.
             # Real logic: specific entity matching.
             logger.info(f"   🧠 AI Brain: Market is active (Signals: {self.stats['signals_generated']}). Validation PASS.")
             return True
             
        # Fallback: Neutral
        return True # Default PASS for now to allow copy trading in demo

    async def run(
        self,
        keywords: List[str] = [],
        check_interval: int = 10,
        max_runtime: Optional[int] = None
    ):
        """Main monitoring loop with optimizations"""

        logger.info("=" * 80)
        logger.info("🚀 OPTIMIZED NEWS SCALPING BOT STARTED")
        logger.info("=" * 80)
        logger.info(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE TRADING'}")
        logger.info(f"Keywords: {keywords}")
        logger.info(f"Check Interval: {check_interval}s")
        logger.info("📡 Real-time WebSocket: ENABLED")
        logger.info("=" * 80)

        # Warmup first
        if not self._is_warmed_up:
            await self.warmup(keywords)

        self.start_time = datetime.now()
        end_time = None
        if max_runtime:
            end_time = self.start_time + timedelta(seconds=max_runtime)

        # START WebSocket Stream Task in Background
        self.stream_task = asyncio.create_task(self._run_news_stream(keywords))

        try:
            while True:
                if end_time and datetime.now() >= end_time:
                    logger.info(f"⏰ Reached max runtime ({max_runtime}s). Stopping.")
                    break

                # Check news (polling fallback)
                await self._check_news_parallel(keywords)

                # Monitor positions
                await self._monitor_positions()

                # Print stats
                self._print_stats()

                # Wait
                await asyncio.sleep(check_interval)

        except KeyboardInterrupt:
            logger.info("\n⚠️  Keyboard interrupt received. Shutting down...")
        except Exception as e:
            logger.error(f"❌ Fatal error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            # Stop stream task
            if self.stream_task:
                self.stream_task.cancel()
            await self._shutdown()

    async def _run_news_stream(self, keywords: List[str]):
        """
        Background task to process real-time news stream.
        """
        logger.info("🧵 Starting real-time news stream task...")
        try:
            async for article in self.stream_client.stream_news():
                # Filter by keywords (Tree News stream sends EVERYTHING)
                title = article.get("title", "").lower()
                content = article.get("content", "").lower()
                
                if any(kw.lower() in title or kw.lower() in content for kw in keywords):
                    logger.info(f"🔥 REAL-TIME NEWS DETECTED: {article.get('title')[:60]}...")
                    # Process immediately!
                    asyncio.create_task(self._process_article_optimized(article))
                else:
                    # Log ignored news at debug level
                    logger.debug(f"🔇 Ignored non-target news: {article.get('title')[:40]}...")
                    
        except asyncio.CancelledError:
            logger.info("🧵 Real-time news stream task cancelled")
        except Exception as e:
            logger.error(f"❌ Real-time news stream error: {e}")

    async def _check_news_parallel(self, keywords: List[str]):
        """
        OPTIMIZED: Process news articles in parallel from multiple sources.

        Speedup: 5-10x faster than sequential processing.
        Multi-source: NewsAPI + Tree News for redundancy and speed.
        """
        try:
            # Fetch news from all sources (NewsAPI + Tree News)
            articles = await self.news_aggregator.get_breaking_news(
                keywords=keywords,
                max_results=20
            )

            self.stats["news_checked"] += len(articles)

            if not articles:
                return

            logger.info(f"📰 Processing {len(articles)} articles in parallel...")

            # OPTIMIZATION: Process all articles concurrently
            tasks = [
                self._process_article_optimized(article)
                for article in articles
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Count successes
            successful = sum(1 for r in results if r and not isinstance(r, Exception))
            logger.info(f"   ✅ Processed {successful}/{len(articles)} articles")

        except Exception as e:
            logger.error(f"❌ Error checking news: {e}")

    async def _process_article_optimized(self, article: Dict) -> Optional[Dict]:
        """
        OPTIMIZED: Process article with timing and caching.

        Uses RAG System (Advanced AI) or FinBERT (Basic) depending on configuration.

        Target: < 2 seconds total
        """
        url = article.get("url", "")
        title = article.get("title", "")
        content = article.get("description", "") or article.get("content", "")

        if not url: return None

        # Robust Deduplication (Redis + SHA256)
        news_id = hashlib.sha256(url.encode()).hexdigest()
        if await self._is_processed(news_id):
            return None

        # Optimistically mark as processed (will unmark on error)
        await self._mark_processed(news_id)

        # Start latency timer
        start_time = time.time()

        try:
            # === RAG MODE: Advanced AI Analysis ===
            if self.use_rag:
                # 2. Convert article to NewsEvent
                # Safely handle source (TreeNews uses string, NewsAPI uses dict)
                source_data = article.get("source", "Unknown")
                source_name = source_data.get("name", "Unknown") if isinstance(source_data, dict) else str(source_data)

                # Use dateutil.parser for flexible date parsing
                try:
                    pub_date = date_parser.parse(article.get("publishedAt", ""))
                except:
                    pub_date = datetime.now()

                event = NewsEvent(
                    event_id=f"news_{hash(url)}",
                    title=title,
                    content=content,
                    source=source_name,
                    published_at=pub_date,
                    entities=[],  # Will be extracted by RAG
                    category="crypto",  # Default
                    url=url
                )

                # 2. Extract entities using LLM (Dynamic extraction)
                llm_entities = await self.rag_system.extract_entities(event)
                event.entities = llm_entities # Update event with extracted entities
                
                if not llm_entities:
                    logger.debug(f"   ⚠️  No entities extracted by AI for: {title[:30]}...")
                    # Optional: Fallback to regex is handled inside _find_markets_cached if override_keywords is None/Empty
                    # But here we explicitly pass what we got.
                
                # 3. Find relevant markets using AI-extracted keywords
                markets = await self._find_markets_cached(title, override_keywords=llm_entities)
                
                if not markets:
                    logger.debug(f"   ⚠️  No matching markets found for entities: {llm_entities}")
                    return None

                # 4. Analyze market impact with RAG System
                best_market = markets[0]
                relevance = best_market.get("relevance_score", 0.0)
                
                # 🛑 Optimization: Skip RAG if match quality is too low
                if relevance < 0.4:
                    logger.debug(f"   ⚠️  Skipping RAG: Match relevance too low ({relevance:.2f})")
                    return None
                    
                market_id = best_market.get("condition_id", "")
                market_question = best_market.get("question", "")

                # Get current price from market
                try:
                    outcome_prices = json.loads(best_market.get("outcomePrices", "[]")) if isinstance(best_market.get("outcomePrices"), str) else best_market.get("outcomePrices", [])
                    if outcome_prices and len(outcome_prices) > 0:
                        current_price = Decimal(str(outcome_prices[0]))
                    else:
                        current_price = Decimal("0.5")
                except:
                    current_price = Decimal("0.5")

                impact = await self.rag_system.analyze_market_impact(
                    event=event,
                    market_id=market_id,
                    current_price=current_price,
                    market_question=market_question
                )

                # 5. Check if tradeable
                if impact.confidence < self.min_confidence:
                    logger.info(f"   ⚠️  Low confidence: {impact.confidence:.1%}")
                    return None

                if impact.trade_recommendation == "hold":
                    logger.info(f"   ⚠️  Recommendation: HOLD - {impact.reasoning[:100]}")
                    return None

                # 6. Convert RAG output to trade signal
                label = impact.trade_recommendation.lower()  # "buy" or "sell"
                confidence = impact.confidence
                target_prob = float(impact.suggested_price) # Fair value predicted by AI
                
                is_high_impact = confidence >= self.high_impact_threshold

                # Record latency
                latency_ms = (time.time() - start_time) * 1000
                self.stats["latencies"].append(latency_ms)

                logger.info(f"   ✅ RAG SIGNAL! {label.upper()} (Prob {target_prob:.1%} | Conf {confidence:.1%}) - {latency_ms:.0f}ms")
                logger.info(f"      Market: {best_market.get('question', '')[:60]}...")
                logger.info(f"      Reasoning: {impact.reasoning[:100]}...")

                self.stats["signals_generated"] += 1
                
                # 🧠 HIVE MIND UPDATE: Broadcast signal to other bots
                if self.signal_bus:
                    token_id = None
                    # Try to get token ID for signal bus
                    try:
                        clob_ids = json.loads(best_market.get("clobTokenIds", "[]")) if isinstance(best_market.get("clobTokenIds"), str) else best_market.get("clobTokenIds", [])
                        if clob_ids: token_id = clob_ids[0]
                    except: pass
                    
                    if token_id:
                        asyncio.create_task(self.signal_bus.update_signal(
                            token_id=token_id,
                            source='NEWS',
                            score=target_prob if label == 'buy' else (1.0 - target_prob),
                            label=label
                        ))

                # 7. Execute trade with RAG-enhanced signal
                sentiment = {
                    "event_id": event.event_id,
                    "label": label,
                    "score": target_prob,    # Probability used for Kelly Criterion
                    "confidence": confidence, # Confidence used for risk scaling
                    "reasoning": impact.reasoning,
                    "model": impact.model_used,
                    "expected_value": float(impact.expected_value),
                    "suggested_price": target_prob,
                    "ensemble_verified": impact.ensemble_verified,
                    "validator_reasoning": impact.validator_reasoning,
                    "validator_model": impact.validator_model
                }

                # Log Ensemble Verdict
                if impact.ensemble_verified:
                    logger.info(f"   🛡️ [ENSEMBLLE APPROVED] Confirmed by {impact.validator_model}")
                elif impact.validator_model:
                     logger.warning(f"   ⚠️ [ENSEMBLE REJECTED] {impact.validator_model}: {impact.validator_reasoning[:100]}...")

                await self._execute_trade(
                    article=article,
                    sentiment=sentiment,
                    market=best_market,
                    is_high_impact=is_high_impact
                )

                return {"success": True, "latency_ms": latency_ms, "mode": "RAG"}

            # === BASIC MODE: FinBERT Sentiment Analysis ===
            else:
                # 1. Sentiment analysis (cached model)
                sentiment = self.sentiment_analyzer.analyze(title)
                label = sentiment["label"]
                score = sentiment["score"]

                # BRIDGE TRIGGER: Run Stat Arb analysis based on news sentiment
                if self.bridge and score >= self.min_confidence and label != "neutral":
                    # We run this in background to avoid blocking direct trade execution
                    asyncio.create_task(self.bridge.on_high_impact_news(article, sentiment))

                # Detailed debug logging for decision process
                if score < self.min_confidence:
                    logger.info(f"   ⏭️  Skipped '{title[:30]}...': Low confidence ({score:.1%} < {self.min_confidence:.0%})")
                    return None
                
                if label == "neutral":
                    logger.info(f"   ⏭️  Skipped '{title[:30]}...': Neutral sentiment")
                    return None

                # 2. Find markets (use cache if available)
                markets = await self._find_markets_cached(title)

                if not markets:
                    logger.info(f"   🔍 No matching markets for: '{title[:40]}...' (Score: {score:.1%})")
                    return None

                # 3. Execute trade
                is_high_impact = score >= self.high_impact_threshold
                best_market = markets[0]

                # Record latency
                latency_ms = (time.time() - start_time) * 1000
                self.stats["latencies"].append(latency_ms)

                logger.info(f"   ✅ SIGNAL! {label.upper()} ({score:.1%}) - {latency_ms:.0f}ms")
                logger.info(f"      Market: {best_market.get('question', '')[:60]}...")

                self.stats["signals_generated"] += 1

                # Execute trade
                await self._execute_trade(
                    article=article,
                    sentiment=sentiment,
                    market=best_market,
                    is_high_impact=is_high_impact
                )

                return {"success": True, "latency_ms": latency_ms, "mode": "FinBERT"}

        except Exception as e:
            # 🚨 CRITICAL: Unmark as processed so we retry
            await self._unmark_processed(news_id)
            logger.error(f"❌ Error processing article: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    async def _find_markets_cached(self, news_text: str, override_keywords: Optional[List[str]] = None) -> List[Dict]:
        """
        OPTIMIZED: Find markets using cache.

        Speedup: 10-100x (no API call if cached)
        """
        # Use provided keywords or extract using regex
        if override_keywords:
             search_keywords = override_keywords
             # Also try to extract categories for cache lookup (heuristic)
             entities = {"manual": override_keywords} 
        else:
            entities = self.market_matcher.extract_entities(news_text)
            search_keywords = []
            for kw_list in entities.values():
                search_keywords.extend(kw_list)

        # Helper to filter valid markets
        def _filter(mkts):
            valid = [m for m in mkts if self._is_valid_duration(m)]
            if len(mkts) != len(valid):
                logger.debug(f"   ⏳ Duration filter removed {len(mkts)-len(valid)} long-term markets")
            return valid

        # Check pre-loaded cache first
        for kw in search_keywords:
             if kw in self.preloaded_markets:
                 logger.debug(f"   💨 Cache hit for '{kw}'")
                 return _filter(self.preloaded_markets[kw])

        # Fallback to API search
        markets = await self.market_matcher.find_matching_markets(
            news_text,
            min_volume=self.min_market_volume,
            max_results=10, # Request more to allow for filtering
            override_keywords=override_keywords
        )

        # Apply duration filter
        markets = _filter(markets)

        # Cache result
        if markets and search_keywords:
            for kw in search_keywords:
                self.preloaded_markets[kw] = markets
                
        return markets[:3] # Return top 3 after filtering

    async def _execute_trade(
        self,
        article: Dict,
        sentiment: Dict,
        market: Dict,
        is_high_impact: bool
    ):
        """Execute trade with improved token ID extraction"""
        market_question = market.get('question', '')
        logger.info(f"🚀 [SCALPER] Entering _execute_trade for '{market_question[:30]}...'")
        market_group = self._infer_market_group(market)
        market_expiry = self._parse_market_expiry(market)
        expiry_seconds = seconds_to_expiry(market_expiry)
        
        # 🛡️ [ENSEMBLE GUARDRAIL] Phase 2
        # If ensemble is enabled and validator has rejected, we block execution.
        if self.config.ENABLE_ENSEMBLE_VERIFICATION:
            if sentiment.get("validator_model") and not sentiment.get("ensemble_verified"):
                logger.warning(f"✋ [EXECUTION BLOCKED] Ensemble validation failed for '{market_question[:30]}'")
                return
        # Initialize variables for finally block safety
        allocation_id: Optional[str] = None
        allocation_amount: Optional[Decimal] = None
        position_opened = False
        current_price: Optional[float] = None
        position_size: Optional[float] = None
        token_id: Optional[str] = None
        condition_id: Optional[str] = None
        
        try:
            # 🚀 유연한 레이블 처리 (AI 출력값 대응)
            raw_label = str(sentiment.get("label", "")).lower()
            logger.info(f"   🔍 Analyzing Signal Label: '{raw_label}'")
            
            if raw_label in ["positive", "buy"]:
                side = "BUY"
                label = "buy"
            elif raw_label in ["negative", "sell"]:
                side = "SELL"
                label = "sell"
            else:
                logger.info(f"   ⏭️  Skipping: Label '{raw_label}' is not actionable (HOLD)")
                return

            # 🛑 BLACKLIST CHECK
            # Explicitly block trading on ignored markets (e.g. unrealistic targets)
            ignored_markets = getattr(self.config, "IGNORED_MARKETS", [])
            if any(blk.lower() in market_question.lower() for blk in ignored_markets):
                logger.warning(f"   🛑 BLACKLISTED MARKET: '{market_question[:40]}...' - Skipping.")
                return

            # Robust Token ID extraction (matching market_matcher.py logic)
            token_id = None
            clob_ids_raw = market.get("clobTokenIds", [])
            
            if isinstance(clob_ids_raw, str) and clob_ids_raw:
                try:
                    import json
                    clob_ids = json.loads(clob_ids_raw)
                    if clob_ids: token_id = clob_ids[0]
                except: pass
            elif isinstance(clob_ids_raw, list) and clob_ids_raw:
                token_id = clob_ids_raw[0]

            # Fallback based on sentiment (Short logic)
            if not token_id:
                cid = market.get("condition_id") or market.get("id")
                if cid:
                    if label == "sell": # Short Logic
                         logger.debug(f"   🔍 Resolving NO Token (Short) for CID: {cid[:10]}")
                         token_id = self.clob_client.get_no_token_id(cid)
                         side = "BUY" # We BUY the NO token
                    else:
                         logger.debug(f"   🔍 Resolving YES Token (Long) for CID: {cid[:10]}")
                         token_id = self.clob_client.get_yes_token_id(cid)

            if not token_id:
                logger.warning(f"   ⚠️  [EXECUTION ABORTED] Could not extract valid Token ID for: {market_question[:30]}...")
                return

            logger.info(f"   ✅ Target Token Resolved: {token_id[:15]}... (group={market_group})")
            await self._ensure_orderbook_subscription(token_id)
            condition_id = market.get("condition_id") or market.get("id")

            if self.signal_bus and market_expiry:
                try:
                    await self.signal_bus.update_market_metrics(
                        token_id=token_id,
                        metadata={"expires_at": market_expiry.isoformat()},
                    )
                except Exception as exc:
                    logger.debug(f"SignalBus expiry update failed: {exc}")

            # Prevent overlapping positions or spam on identical market
            existing_position = self.positions.get(token_id)
            if existing_position:
                if existing_position["side"].upper() != side:
                    logger.info("   🔄 Opposite signal detected while position open; closing existing exposure.")
                    await self._close_position(token_id, existing_position, "SignalFlip")
                else:
                    current_price = await self._get_current_price(token_id, condition_id=condition_id)
                    if current_price is None or current_price <= 0:
                        current_price = 0.5
                    position_size = self.risk_manager.calculate_position_size(
                        prob_win=sentiment["score"],
                        current_price=current_price,
                        category="crypto",
                        volatility_score=0.1,
                        confidence=sentiment.get("confidence", 1.0)
                    )
                    if position_size <= 0:
                        logger.info(
                            "   🛑 [RISK REJECTED] Size: $%.2f | Reason: Low EV (Prob %.2f vs Price %.2f)",
                            position_size,
                            sentiment["score"],
                            current_price,
                        )
                        return
                    await self._refresh_position_signal(
                        token_id=token_id,
                        position=existing_position,
                        sentiment=sentiment,
                        article=article,
                        market=market,
                        current_price=current_price,
                        base_position_size=position_size,
                        market_group=market_group,
                        market_expiry=market_expiry,
                        condition_id=condition_id,
                        is_high_impact=is_high_impact,
                    )
                    return
                if token_id in self.positions:
                    return

            if not self._passes_cooldown_gate(token_id, side):
                return

            prev_signal = self.latest_signals.get(token_id)
            if prev_signal and prev_signal.get("label") != label:
                if prev_signal.get("score", 0.0) >= sentiment["score"]:
                    logger.info(
                        "   ↔️ Conflicting signal detected; existing higher-confidence directive in effect."
                    )
                    return
                logger.info("   🔁 Overriding weaker opposing signal with higher confidence trade.")

            # 🛡️ DYNAMIC POSITION SIZING (Kelly Criterion)
            # 🛡️ PRICE & SPREAD CHECK (Prevent "Stupid Losses")
            try:
                ask_p, ask_s = self.clob_client.get_best_ask(token_id)
                bid_p, bid_s = self.clob_client.get_best_bid(token_id)
            except Exception as e:
                logger.warning(f"   ⚠️ Failed to fetch orderbook: {e}")
                return

            if ask_p == 0 or bid_p == 0:
                logger.warning("   ⚠️ Orderbook incomplete (Zero Bid/Ask). Aborting.")
                return

            spread = ask_p - bid_p
            mid_p = (ask_p + bid_p) / 2
            spread_pct = spread / mid_p if mid_p > 0 else 1.0
            
            logger.info(f"   📊 Market: Bid ${bid_p:.3f} | Ask ${ask_p:.3f} | Spread {spread_pct:.1%}")

            MAX_SPREAD = 0.05 # 5% Limit
            if spread_pct > MAX_SPREAD:
                logger.warning(f"   🛑 Spread too wide ({spread_pct:.1%} > {MAX_SPREAD:.0%}). Aborting trade to avoid instant loss.")
                return

            # Set execution price based on SIDE (Taker Price)
            # 🛡️ SHORT SELLING LOGIC
            # If we are BUYING, we pay ASK.
            # If we were Selling YES (to close), we hit BID.
            # But now SELL signal -> BUY NO. So side is BUY.
            if side == "BUY":
                current_price = ask_p
            else:
                current_price = bid_p
            
            logger.info(f"   💲 Execution Price: ${current_price:.3f} ({side})")

            # Fallback (Should not happen if logic holds)
            if current_price <= 0:
                current_price = 0.5
            
                current_price = 0.5 # Safety fallback
            



            size_multiplier = 1.0
            if self.market_specialist:
                 size_multiplier = self.market_specialist.get_market_score(market)
                 if size_multiplier != 1.0:
                     logger.info(f"🧠 Specialist Adjusted Size: x{size_multiplier:.2f} based on history/backtest")

            # Fetch real wallet balance for dynamic sizing
            portfolio_balance = await self.clob_client.get_usdc_balance()
            if portfolio_balance is None or portfolio_balance <= 0:
                portfolio_balance = 1000.0 # Fallback for dry-run

            if position_size is None:
                position_size = self.risk_manager.calculate_position_size(
                    prob_win=sentiment["score"],
                    current_price=current_price,
                    portfolio_balance=portfolio_balance, # Dynamic Sizing
                    category="crypto", 
                    volatility_score=0.1,
                    confidence=sentiment.get("confidence", 1.0)
            )
            
            # Apply Specialist Multiplier
            position_size = position_size * size_multiplier
            
            # Additional logic for scaling in...
            # Enforce minimum order size (Polymarket requirement)
            if position_size > 0 and position_size < 5.0 and not self.dry_run:
                logger.info(f"   ⚠️ Enforcing minimum order size: ${position_size:.2f} -> $5.00")
                position_size = 5.0

            # 🛡️ MAX EXPOSURE CHECK (Moved here to ensure position_size is valid)
            # Calculate Total Equity (Cash + Positions)
            # portfolio_balance already fetched above
            
            
            # Calculate Value of controlled positions
            positions_value = sum(p["size"] * p.get("entry_price", current_price) for p in self.positions.values())
            
            total_equity = portfolio_balance + positions_value
            if total_equity <= 0: total_equity = 1000.0 # Dry run fallback
            
            # Current Exposure for THIS token
            current_exposure_val = 0.0
            existing = self.positions.get(token_id)
            if existing:
                current_exposure_val = existing["size"] * existing.get("entry_price", current_price)
            
            # Proposed New Exposure
            new_exposure_val = position_size
            total_exposure = current_exposure_val + new_exposure_val
            
            # 🛡️ Dynamic Risk Cap (Fix for Small Portfolios)
            # 20% Max Exposure or $5.50 minimum (to allow min bets on small account)
            MAX_EXPOSURE_PCT = 0.20 
            min_allowance_usd = 5.5
            allowed_exposure_usd = max(total_equity * MAX_EXPOSURE_PCT, min_allowance_usd)

            exposure_pct = total_exposure / total_equity # For logging

            if total_exposure > allowed_exposure_usd:
                logger.warning(
                    f"   🛑 RISK: Max Exposure Limit Reached! ({total_exposure:.2f} > {allowed_exposure_usd:.2f}). "
                    f"Holding ${current_exposure_val:.2f} of ${total_equity:.2f} ({exposure_pct:.1%}). Rejecting ADD."
                )
                return

            if position_size <= 0:
                logger.info(
                    "   🛑 [RISK REJECTED] Size: $%.2f | Reason: Low EV (Prob %.2f vs Price %.2f) or Volatility Penalty",
                    position_size,
                    sentiment["score"],
                    current_price,
                )
                return

            spread_for_ev = 0.0
            spread_regime = "UNKNOWN"
            spread_bps = 0.0
            expiry_phase = "EARLY"
            expiry_minutes = None
            if self.signal_bus:
                try:
                    market_signal = await self.signal_bus.get_signal(token_id)
                    spread_for_ev = getattr(market_signal, "spread", 0.0) or 0.0
                    spread_regime = (
                        getattr(market_signal, "spread_regime", "UNKNOWN") or "UNKNOWN"
                    )
                    spread_bps = getattr(market_signal, "spread_bps", 0.0) or 0.0
                    expiry_ctx = (market_signal.metadata or {}).get("expiry") or {}
                    expiry_phase = (expiry_ctx.get("phase") or "EARLY").upper()
                    expiry_minutes = expiry_ctx.get("minutes_remaining")
                except Exception as exc:
                    logger.debug(f"SignalBus lookup failed for EV check: {exc}")

            time_multiplier = self._time_phase_multiplier(expiry_phase)
            phase_reason = ""
            if (
                spread_regime.upper() == "INEFFICIENT"
                and expiry_phase in ("LATE", "ENDGAME")
            ):
                time_multiplier *= self.inefficient_phase_boost
                phase_reason = " + spread boost"
            if abs(time_multiplier - 1.0) > 1e-6:
                scaled_size = position_size * time_multiplier
                logger.info(
                    "   ⏱️ Time aggression %s (≈%s min) scaled size from $%.2f → $%.2f%s",
                    expiry_phase,
                    f"{expiry_minutes:.0f}" if expiry_minutes is not None else "?",
                    position_size,
                    scaled_size,
                    phase_reason,
                )
                position_size = scaled_size

            # Use RAG's calculated EV if available (More accurate)
            if isinstance(sentiment, dict) and "expected_value" in sentiment:
                expected_edge = float(sentiment["expected_value"])
                logger.info(f"   🧠 Using RAG-calculated EV: {expected_edge:.4f}")
            else:
                expected_edge = self._compute_expected_edge(sentiment["score"], current_price, side)
            regime_upper = (spread_regime or "UNKNOWN").upper()
            slippage_override = None
            if regime_upper == "EFFICIENT":
                if expected_edge < self.efficient_ev_floor:
                    logger.info(
                        "   🛑 Spread regime %s (≈%.0f bps) demands EV >= %.2f; edge %.4f → SKIP",
                        regime_upper,
                        spread_bps,
                        self.efficient_ev_floor,
                        expected_edge,
                    )
                    return
                logger.info(
                    "   ⚠️ Efficient book overridden because EV %.4f ≥ %.2f",
                    expected_edge,
                    self.efficient_ev_floor,
                )
            elif regime_upper == "INEFFICIENT":
                slippage_override = max(self.slippage_buffer, self.inefficient_slippage_buffer)
                logger.info(
                    "   ⚡ Inefficient regime detected (≈%.0f bps); slippage buffer elevated to %.4f",
                    spread_bps,
                    slippage_override,
                )

            if not self._passes_ev_filter(
                expected_edge,
                spread_for_ev,
                current_price,
                position_size,
                slippage_override=slippage_override,
            ):
                # 🔥 HIGH SENTIMENT BYPASS: Allow trades with very strong AI confidence
                sentiment_score = sentiment.get("score", 0.5) if isinstance(sentiment, dict) else 0.5
                if sentiment_score >= 0.70:
                    logger.info(
                        "   🔥 EV filter BYPASSED due to high sentiment (%.2f >= 0.70)",
                        sentiment_score
                    )
                else:
                    logger.info("   ⚠️ EV filter rejected trade (edge %.4f < threshold)", expected_edge)
                    return

            spread_multiplier = self._spread_multiplier_for_regime(regime_upper)
            if spread_multiplier <= 0:
                logger.info(
                    "   🧊 Spread regime %s (Δ=%.4f) indicates efficient book; standing down.",
                    spread_regime,
                    spread_for_ev,
                )
                return
            if spread_multiplier < 1.0:
                adjusted = position_size * spread_multiplier
                logger.info(
                    "   ⚖️ Spread regime %s scaled size from $%.2f → $%.2f",
                    spread_regime,
                    position_size,
                    adjusted,
                )
                position_size = adjusted

            agg_multiplier, agg_stage = aggression_profile(expiry_seconds)
            if agg_multiplier <= 0:
                logger.info("   🕒 Aggression stage %s suppressed trade (no exposure).", agg_stage)
                return
            if abs(agg_multiplier - 1.0) > 1e-6:
                scaled = position_size * agg_multiplier
                logger.info(
                    "   ⚡ Aggression stage %s (t=%.0fs) scaled size from $%.2f → $%.2f",
                    agg_stage,
                    expiry_seconds if expiry_seconds is not None else float("nan"),
                    position_size,
                    scaled,
                )
                position_size = scaled

            if self.delta_tracker:
                delta_decision = await self.delta_tracker.check_allowance(
                    token_id=token_id,
                    side=side,
                    size=position_size,
                    market_group=market_group,
                    condition_id=condition_id,
                )
                if not delta_decision.allowed:
                    limits_desc = f"hard={delta_decision.hard_limit} soft={delta_decision.soft_limit}"
                    logger.info(
                        "   🛑 Delta guard blocked trade (%s) [group=%s current=%.2f -> projected=%.2f | %s]",
                        delta_decision.reason,
                        delta_decision.group,
                        delta_decision.current_delta,
                        delta_decision.projected_delta,
                        limits_desc,
                    )
                    return
                elif delta_decision.reduce_only:
                    logger.info(
                        "   ⚠️ Delta reduce-only mode; proceeding because exposure shrinks (current=%.2f -> projected=%.2f)",
                        delta_decision.current_delta,
                        delta_decision.projected_delta,
                    )

            if self.balance_allocator:
                adjusted_size = await self.balance_allocator.allocate_for_market(
                    token_id,
                    position_size
                )
                if adjusted_size <= 0:
                    logger.info("   ⚠️ Allocation manager rejected trade for insufficient budget")
                    return
                position_size = adjusted_size

            # 💰 BUDGET ALLOCATION
            if self.budget_manager:
                allocation_amount = Decimal(str(position_size))
                allocation_id = await self.budget_manager.request_allocation(
                    strategy="arbhunter",
                    amount=allocation_amount,
                    priority="high" if is_high_impact else "normal"
                )
                if not allocation_id:
                    logger.warning(f"   ⚠️  Budget allocation denied. Skipping trade.")
                    return
                logger.debug(f"   💰 Allocation approved: {allocation_id}")

            # 🧠 Log Decision using centralized logger
            await self.decision_logger.log_decision(
                action=side,
                token=market_question[:40],
                confidence=sentiment["score"],
                reason=sentiment.get("reasoning", "High impact news detected"),
                factors={
                    "News": article.get("title", "")[:50],
                    "Price": f"${current_price:.3f}",
                    "Size": f"${position_size:.2f}",
                    "Model": sentiment.get("model", "FinBERT"),
                    "Token ID": token_id
                }
            )

            if self.dry_run:
                # PAPER TRADING: Get real entry price
                entry_price = await self._get_current_price(token_id, condition_id=condition_id)

                logger.info(f"   🧪 PAPER TRADING: Would execute slippage-protected {side} order")
                logger.info(f"      Entry price: ${entry_price:.4f}")
                logger.info(f"      Max slippage: 2.0%")
                logger.info(f"      Order type: IOC Limit")

                # Track position
                self.positions[token_id] = {
                    "token_id": token_id,
                    "market": market,
                    "side": side,
                    "size": position_size,
                    "entry_price": entry_price,  # Real market price
                    "entry_time": datetime.now(),
                    "sentiment": sentiment,
                    "article": article,
                    "is_high_impact": is_high_impact,
                    "allocation_id": allocation_id,
                    "allocation_amount": allocation_amount,
                    "condition_id": condition_id,
                    "market_group": market_group,
                    "expires_at": market_expiry,
                    "pnl_tids": [],
                }
                self.stats["trades_executed"] += 1
                self.stats["positions_opened"] += 1
                position_opened = True

                # 🐝 HIVE MIND HISTORY: Report to orchestrator
                if self.swarm_system:
                    self.swarm_system.add_trade_record(
                        side, token_id, entry_price, position_size, 
                        brain_score=size_multiplier
                    )
                    # 🚀 PnL Tracker 기록 추가
                    if hasattr(self.swarm_system, 'pnl_tracker'):
                        entry_tid = self.swarm_system.pnl_tracker.record_entry(
                            strategy="news_scalper",
                            token_id=token_id,
                            side=side,
                            price=entry_price,
                            size=position_size
                        )
                        self.positions[token_id]["pnl_tids"].append(entry_tid)
                await self._record_delta_trade(
                    token_id,
                    side,
                    position_size,
                    entry_price,
                    market,
                    condition_id,
                    market_group,
                )
                self.latest_signals[token_id] = {
                    "label": label,
                    "score": sentiment["score"]
                }
            else:
                disable_slippage = getattr(self.config, "DISABLE_SLIPPAGE_PROTECTION", False)

                if disable_slippage:
                    logger.warning("   🚨 Slippage protection disabled; sending aggressive IOC order")
                    order_result = await self.clob_client.place_unprotected_aggressive_order(
                        token_id=token_id,
                        side=side,
                        amount=position_size,
                        priority="high" if is_high_impact else "normal",
                    )
                else:
                    # LIVE MODE: Use slippage-protected order
                    logger.info(f"   🛡️  Using slippage protection (max 2%)")
                    
                    # Get AI's suggested price for fallback limit order
                    ai_suggested_price = sentiment.get("suggested_price") if isinstance(sentiment, dict) else None

                    order_result = await self.clob_client.place_limit_order_with_slippage_protection(
                        token_id=token_id,
                        side=side,
                        amount=position_size,
                        max_slippage_pct=2.0,  # Max 2% slippage
                        priority="high" if is_high_impact else "normal",
                        target_price=float(ai_suggested_price) if ai_suggested_price else None
                    )

                if order_result:
                    logger.info(f"   ✅ Order executed{' without protection' if disable_slippage else ' with slippage protection'}")
                    entry_price = float(order_result.get('price', 0.5))

                    if disable_slippage and current_price is not None:
                        intended_price = float(current_price)
                        slippage_cost = (
                            entry_price - intended_price
                            if side.upper() == "BUY"
                            else intended_price - entry_price
                        )
                        logger.warning(
                            "   💸 Unprotected fill deviated by %.4f (%+.2fbps)",
                            slippage_cost,
                            (slippage_cost / max(intended_price, 1e-6)) * 10000,
                        )

                    shares_filled = float(order_result.get('filled', position_size / entry_price if entry_price > 0 else 0))
                    
                    # Track position (Store SHARES not USD)
                    self.positions[token_id] = {
                        "token_id": token_id,
                        "market": market,
                        "side": side,
                        "size": shares_filled, # Storing SHARES now
                        "entry_price": entry_price,
                        "entry_time": datetime.now(),
                        "sentiment": sentiment,
                        "article": article,
                        "is_high_impact": is_high_impact,
                        "order_id": order_result.get('orderID'),
                        "allocation_id": allocation_id,
                        "allocation_amount": allocation_amount,
                        "condition_id": condition_id,
                        "market_group": market_group,
                        "expires_at": market_expiry,
                        "pnl_tids": [],
                    }
                    self.stats["trades_executed"] += 1
                    self.stats["positions_opened"] += 1
                    position_opened = True
                    
                    # 🚀 PnL Tracker 기록 추가 (Live)
                    if self.swarm_system and hasattr(self.swarm_system, 'pnl_tracker'):
                        entry_tid = self.swarm_system.pnl_tracker.record_entry(
                            strategy="news_scalper",
                            token_id=token_id,
                            side=side,
                            price=entry_price,
                            size=position_size
                        )
                        self.positions[token_id]["pnl_tids"].append(entry_tid)
                    await self._record_delta_trade(
                        token_id,
                        side,
                        position_size,
                        entry_price,
                        market,
                        condition_id,
                        market_group,
                    )
                    self.latest_signals[token_id] = {
                        "label": label,
                        "score": sentiment["score"]
                    }
                else:
                    logger.warning(f"   ⚠️  Order cancelled (slippage too high)")

        except Exception as e:
            logger.error(f"❌ Trade execution error: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        finally:
            if self.budget_manager and allocation_id and not position_opened:
                await self.budget_manager.release_allocation("arbhunter", allocation_id, Decimal("0"))
            
            # Ensure cooldown is strictly enforced even on error/abort
            if condition_id:
                self._set_cooldown(condition_id)

    async def hydrate_position(self, token_id: str, size: float, entry_price: float):
        """Called by Orchestrator on startup to load existing positions"""
        if token_id not in self.positions:
            self.positions[token_id] = {
                "size": size,
                "entry_price": entry_price,
                "side": "BUY", # Hydration assumes BUY (long) for now
                "entry_time": datetime.now()
            }
            logger.info(f"💧 Hydrated position for {token_id[:15]}... ({size} tokens @ ${entry_price})")
            
            # Start monitoring this position
            if self.delta_tracker:
                try:
                    # Infer group for delta tracking
                    group = self._infer_market_group({"clobTokenIds": json.dumps([token_id])})
                    # Add to delta tracker exposure
                    # Note: add_exposure usually handles (token_id, delta, market_group)
                    # We assume delta = size for simplicity in hydration
                    self.delta_tracker.add_exposure(token_id, size, group)
                except Exception as e:
                    logger.debug(f"Failed to add exposure to delta_tracker: {e}")

    async def _monitor_positions(self):
        """Monitor positions (same as original)"""
        if not self.positions:
            return

        logger.debug(f"🕵️ Monitoring {len(self.positions)} open positions for dynamic exits")

        for token_id, position in list(self.positions.items()):
            try:
                await self._check_position_exit(token_id, position)
            except Exception as e:
                logger.error(f"❌ Error monitoring position: {e}")

    def _parse_market_expiry(self, market: Optional[Dict]) -> Optional[datetime]:
        if not market:
            return None
        end_raw = (
            market.get("end_date")
            or market.get("endDate")
            or market.get("ends_at")
            or market.get("endDateISO")
        )
        if not end_raw:
            return None
        try:
            return date_parser.parse(end_raw)
        except Exception:
            return None

    def _is_valid_duration(self, market: Dict) -> bool:
        """Check if market duration is within limits (e.g. < 24h)"""
        expiry = self._parse_market_expiry(market)
        if not expiry:
            # If no expiry found, assume safe? No, safer to reject if strict.
            # But let's allow it for now to avoid blocking everything.
            return True
        
        # Calculate duration from now
        now = datetime.now(expiry.tzinfo)
        remaining = expiry - now
        
        # Check against constraint
        if remaining.total_seconds() > (self.max_market_duration_days * 86400):
            return False
            
        return True

    def _infer_market_group(self, market: Optional[Dict]) -> str:
        """Rudimentary classifier for delta guardrails."""
        if not market:
            return "DEFAULT"

        question = (market.get("question") or "").lower()
        tags = " ".join(map(str, market.get("tags", []))).lower()
        text = f"{question} {tags}"

        if any(key in text for key in ("15m", "15 m", "15-minute", "15 minute")):
            if "bitcoin" in text or "btc" in text:
                return "BTC_15M"
            if "eth" in text or "ethereum" in text:
                return "ETH_15M"

        if "bitcoin" in text or "btc" in text:
            return "CRYPTO"
        if "eth" in text or "ethereum" in text or "sol" in text:
            return "CRYPTO"
        return "DEFAULT"

    def _spread_multiplier_for_regime(self, regime: str) -> float:
        regime_key = (regime or "UNKNOWN").upper()
        mapping = {
            "INEFFICIENT": 1.0,
            "NEUTRAL": 0.6,
            "EFFICIENT": 0.0,
            "UNKNOWN": 1.0,
        }
        return mapping.get(regime_key, 1.0)

    def _time_phase_multiplier(self, phase: str) -> float:
        phase_key = (phase or "EARLY").upper()
        return self.phase_multipliers.get(phase_key, 1.0)

    async def _record_delta_trade(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
        market: Optional[Dict],
        condition_id: Optional[str],
        market_group: Optional[str],
    ):
        if not self.delta_tracker or not token_id:
            return

        if not market_group:
            market_group = self._infer_market_group(market)

        expires_at = self._parse_market_expiry(market)
        market_name = market.get("question") if market else None

        await self.delta_tracker.record_trade(
            token_id=token_id,
            side=side,
            size=float(size),
            price=float(price),
            condition_id=condition_id,
            market_name=market_name,
            expires_at=expires_at,
            market_group=market_group,
        )

    async def _refresh_position_signal(
        self,
        token_id: str,
        position: Dict,
        sentiment: Dict,
        article: Dict,
        market: Dict,
        current_price: float,
        base_position_size: float,
        market_group: str,
        market_expiry: Optional[datetime],
        condition_id: Optional[str],
        is_high_impact: bool,
    ):
        scale_candidate = base_position_size * self.scale_in_multiplier
        scale_candidate = max(scale_candidate, self.scale_in_min_usd)
        scale_candidate = min(scale_candidate, self.scale_in_max_usd)
        if scale_candidate <= 0:
            logger.info("   💤 Scale-in candidate size is zero; skipping refresh.")
            return

        addition_size = float(scale_candidate)
        delta_allows_scale = self.delta_tracker is None
        if self.delta_tracker:
            delta_decision = await self.delta_tracker.check_allowance(
                token_id=token_id,
                side=position["side"],
                size=addition_size,
                market_group=market_group,
                condition_id=condition_id,
            )
            if not delta_decision.allowed:
                logger.info(
                    "   🛑 Delta guard blocked scale-in (%s) [group=%s current=%.2f -> projected=%.2f]",
                    delta_decision.reason,
                    delta_decision.group,
                    delta_decision.current_delta,
                    delta_decision.projected_delta,
                )
                return
            elif delta_decision.reduce_only:
                logger.info(
                    "   ⚠️ Delta reduce-only active; scale-in skipped (current=%.2f -> projected=%.2f)",
                    delta_decision.current_delta,
                    delta_decision.projected_delta,
                )
                return
            else:
                delta_allows_scale = True

        if not self._passes_cooldown_gate(
            token_id,
            position["side"],
            is_scale=True,
            delta_ok=delta_allows_scale,
        ):
            return

        entry_price = current_price
        if entry_price is None or entry_price <= 0:
            entry_price = await self._get_current_price(token_id, condition_id=condition_id)
        if entry_price is None or entry_price <= 0:
            logger.warning("   ⚠️ Unable to fetch scale-in price; skipping.")
            return

        previous_size = float(position["size"])
        new_total_size = previous_size + addition_size
        if new_total_size <= 0:
            logger.warning("   ⚠️ Scale-in would reduce size below zero; skipping.")
            return

        weighted_price = (
            (position["entry_price"] * previous_size) + (entry_price * addition_size)
        ) / new_total_size
        position["size"] = new_total_size
        position["entry_price"] = weighted_price
        position.setdefault("scale_events", []).append(
            {
                "timestamp": datetime.now().isoformat(),
                "added_size": addition_size,
                "price": entry_price,
                "score": sentiment.get("score"),
            }
        )

        if self.swarm_system:
            self.swarm_system.add_trade_record("SCALE", token_id, entry_price, addition_size)
            if hasattr(self.swarm_system, 'pnl_tracker'):
                scale_tid = self.swarm_system.pnl_tracker.record_entry(
                    strategy="news_scalper_scale",
                    token_id=token_id,
                    side=position["side"],
                    price=entry_price,
                    size=addition_size
                )
                position.setdefault("pnl_tids", []).append(scale_tid)

        await self._record_delta_trade(
            token_id=token_id,
            side=position["side"],
            size=addition_size,
            price=entry_price,
            market=market,
            condition_id=condition_id,
            market_group=market_group,
        )

        logger.info(
            "   🔁 Scaled existing %s position by $%.2f (total $%.2f)",
            position["side"],
            addition_size,
            new_total_size,
        )
        self.stats["trades_executed"] += 1

    def _compute_expected_edge(self, sentiment_score: float, current_price: float, side: str) -> float:
        side = side.upper()
        if side == "BUY":
            return max(0.0, sentiment_score - current_price)
        return max(0.0, current_price - sentiment_score)

    def _passes_ev_filter(
        self,
        expected_edge: float,
        spread: float,
        price: float,
        size: float,
        slippage_override: Optional[float] = None,
    ) -> bool:
        fee_cost = self.fee_model.cost(price=price, size=size, is_taker=True)
        slippage_buffer = slippage_override if slippage_override is not None else self.slippage_buffer
        
        # --- NEW: Win Rate Optimization (2x Margin) ---
        # Ensure profit potential covers twice the execution friction (spread + fees)
        min_edge = (spread + fee_cost + slippage_buffer) * 2.0
        
        verdict = expected_edge > min_edge
        logger.debug(
            "[EV CHECK] edge=%.4f spread=%.4f fee=%.4f slip=%.4f min_required(2x)=%.4f -> %s",
            expected_edge,
            spread,
            fee_cost,
            slippage_buffer,
            min_edge,
            "EXECUTE" if verdict else "SKIP",
        )
        return verdict

    async def _check_position_exit(self, token_id: str, position: Dict):
        """
        Check position exit conditions.

        Checks in priority order:
        1. Stop-Loss (P&L based) - 급격한 손실 방지
        2. Time-based exit - 뉴스 재료 소멸 대응
        """
        # Robust key handling for both hydrated and new positions
        entry_time = position.get("entry_time") or position.get("timestamp")
        if isinstance(entry_time, str):
            try:
                entry_time = datetime.fromisoformat(entry_time)
            except:
                entry_time = datetime.now()
        
        if not entry_time:
            entry_time = datetime.now()

        entry_price = position["entry_price"]
        side = position["side"].upper()
        condition_id = position.get("condition_id") or position.get("market", {}).get("condition_id")
        current_price = await self._get_current_price(token_id, condition_id=condition_id)

        if current_price is None:
            return

        if side == "BUY":
            pnl_pct = (current_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - current_price) / entry_price

        exit_reason = None
        now = datetime.now()
        elapsed_seconds = (now - entry_time).total_seconds()

        if pnl_pct >= self.take_profit_pct:
            exit_reason = f"🎯 Take-Profit Reached ({pnl_pct:+.2%})"
        elif pnl_pct <= -self.stop_loss_pct:
            exit_reason = f"🛑 Stop-Loss Triggered ({pnl_pct:+.2%})"
        else:
            # Enforce minimum hold period (default 5 minutes) to avoid spread-churn exits.
            min_hold_seconds = getattr(self, "min_hold_seconds", 300)
            if elapsed_seconds < min_hold_seconds and pnl_pct < 0.02:
                logger.info(
                    "⏳ Holding %s (%.1fs elapsed < %ss); PnL %.2f%% not decisive yet.",
                    token_id[:12],
                    elapsed_seconds,
                    min_hold_seconds,
                    pnl_pct * 100,
                )
                return

            # Strict flip handling: only close on strong opposite signal or when already profitable.
            latest_signal = self.latest_signals.get(token_id)
            if latest_signal:
                signal_label = str(latest_signal.get("label", "")).upper()
                signal_side = "BUY" if signal_label in ("BUY", "POSITIVE") else "SELL" if signal_label in ("SELL", "NEGATIVE") else None
                if signal_side and signal_side != side:
                    confidence = float(latest_signal.get("score") or 0.0)
                    strong_flip = confidence >= 0.75
                    profitable = pnl_pct > 0
                    if strong_flip or profitable:
                        exit_reason = f"🔁 SignalFlip ({confidence:.0%} conf, PnL {pnl_pct:+.2%})"
                    else:
                        logger.info(
                            "[%s] Holding through weak flip (Conf %.2f, PnL %.2f%%)",
                            token_id[:12],
                            confidence,
                            pnl_pct * 100,
                        )
                        return

            hold_duration_hours = elapsed_seconds / 3600
            if hold_duration_hours >= self.max_hold_hours:
                exit_reason = f"⏰ Max hold time ({self.max_hold_hours}h) reached ({pnl_pct:+.2%})"

        if exit_reason:
            await self._close_position(
                token_id,
                position,
                exit_reason,
                exit_price=current_price
            )

    async def _get_current_price(self, token_id: str, condition_id: Optional[str] = None) -> float:
        """
        Get current market price for token.

        Uses CLOB orderbook to get best bid/ask price.
        """
        try:
            if self.clob_client and hasattr(self.clob_client, "get_real_market_price"):
                price = await self.clob_client.get_real_market_price(
                    token_id=token_id,
                    condition_id=condition_id
                )
                if price is not None:
                    return float(price)

            if self.clob_client and self.clob_client.rest_client:
                # Live mode: Use CLOB orderbook
                book = self.clob_client.rest_client.get_order_book(token_id)
                if book.bids and len(book.bids) > 0:
                    return float(book.bids[0].price)
                elif book.asks and len(book.asks) > 0:
                    return float(book.asks[0].price)

            # Fallback: Use mid-price from market data
            import requests
            url = f"https://clob.polymarket.com/price"
            params = {"token_id": token_id}
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: requests.get(url, params=params, timeout=5)
            )

            if response.status_code == 200:
                data = response.json()
                return float(data.get("price", 0.5))

            # Last resort: assume 50%
            return 0.5

        except Exception as e:
            logger.warning(f"⚠️  Failed to get current price for {token_id}: {e}")
            return 0.5

    async def _close_position(
        self,
        token_id: str,
        position: Dict,
        reason: str,
        exit_price: Optional[float] = None
    ):
        """
        Close position with REAL P&L calculation (Paper Trading).

        Queries actual market price to calculate realistic P&L.
        """
        try:
            logger.info(f"\n🚪 Closing position: {reason}")
            condition_id = position.get("condition_id") or position.get("market", {}).get("condition_id")
            current_price = exit_price

            if self.dry_run:
                if current_price is None:
                    current_price = await self._get_current_price(token_id, condition_id=condition_id)
                if current_price is None:
                    logger.warning("⚠️ Unable to fetch exit price; aborting close.")
                    return

                entry_price = position["entry_price"]
                size = position["size"]
                side = position["side"].upper()
                current_price = float(current_price)

                if side == "BUY":
                    price_change = current_price - entry_price
                    pnl = (price_change / entry_price) * size
                else:
                    price_change = entry_price - current_price
                    pnl = (price_change / entry_price) * size

                fee_cost = size * self.trade_fee_rate * 2
                pnl -= fee_cost

                if pnl > 0:
                    self.stats["wins"] += 1
                    result = "WIN"
                else:
                    self.stats["losses"] += 1
                    result = "LOSS"

                self.stats["total_pnl"] += pnl
                total_trades = self.stats["wins"] + self.stats["losses"]
                win_rate = (self.stats["wins"] / total_trades * 100) if total_trades > 0 else 0

                logger.info(f"   📊 Paper Trading Results:")
                logger.info(f"      Entry: ${entry_price:.4f}")
                logger.info(f"      Exit:  ${current_price:.4f}")
                logger.info(f"      Move:  {((current_price - entry_price) / entry_price * 100):+.2f}%")
                logger.info(f"      Fees:  ${fee_cost:.4f}")
                logger.info(f"      P&L:   ${pnl:+.2f} ({result})")
                logger.info(f"      Win Rate: {win_rate:.1f}% ({self.stats['wins']}/{total_trades})")
            else:
                if self.clob_client:
                    opposite_side = "SELL" if position["side"] == "BUY" else "BUY"
                    if current_price is None:
                        current_price = await self._get_current_price(token_id, condition_id=condition_id)
                    await self.clob_client.place_market_order(
                        token_id=token_id,
                        side=opposite_side,
                        size=position["size"] # Pass SHARES
                    )
                    logger.info("   ✅ Position closed")
                
                # Calculate PnL for recording even in live mode
                if current_price is None:
                    current_price = await self._get_current_price(token_id, condition_id=condition_id)
                
                if current_price:
                    entry_price = position["entry_price"]
                    size = position["size"]
                    side = position["side"].upper()
                    if side == "BUY":
                        pnl = (float(current_price) - entry_price) / entry_price * size
                    else:
                        pnl = (entry_price - float(current_price)) / entry_price * size
                    fee_cost = size * self.trade_fee_rate * 2
                    pnl -= fee_cost
                else:
                    pnl = 0.0

            closing_side = "SELL" if position["side"].upper() == "BUY" else "BUY"
            if current_price is not None:
                await self._record_delta_trade(
                    token_id,
                    closing_side,
                    position["size"],
                    current_price,
                    position.get("market"),
                    condition_id,
                    position.get("market_group"),
                )

            del self.positions[token_id]
            self.cooldown_until[token_id] = datetime.now() + self.signal_cooldown
            self.latest_signals.pop(token_id, None)
            self.stats["positions_closed"] += 1

            allocation_id = position.get("allocation_id")
            if self.budget_manager and allocation_id:
                await self.budget_manager.release_allocation(
                    "arbhunter",
                    allocation_id,
                    Decimal("0")
                )

            if self.swarm_system and hasattr(self.swarm_system, 'pnl_tracker'):
                exit_val = current_price if current_price is not None else exit_price
                tids = position.get("pnl_tids", [])
                if exit_val is not None:
                    for tid in tids:
                        self.swarm_system.pnl_tracker.record_exit(
                            trade_id=tid,
                            exit_price=float(exit_val),
                            reason=reason
                        )

            # 💾 RECORD COMPLETED TRADE FOR SPECIALIST ANALYSIS
            if pnl is not None:
                self.trade_recorder.log_completed_trade({
                    "timestamp": datetime.now().isoformat(),
                    "market_question": position.get("market", {}).get("question", "Unknown"),
                    "tags": str(position.get("market", {}).get("tags", [])), 
                    "strategy": "news_scalper",
                    "side": position["side"],
                    "entry_price": position["entry_price"],
                    "exit_price": current_price,
                    "size": position["size"],
                    "pnl": pnl,
                    "reason": reason
                })

                # 🧠 SELF-LEARNING (Phase 3): Log to RAG System
                if self.rag_system and "sentiment" in position:
                    event_id = position["sentiment"].get("event_id")
                    if event_id:
                        asyncio.create_task(self.rag_system.log_trade_outcome(
                            event_id=event_id,
                            market_question=position.get("market", {}).get("question", "Unknown"),
                            pnl=pnl,
                            exit_reason=reason
                        ))

        except Exception as e:
            logger.error(f"❌ Error closing position: {e}")

    def _print_stats(self):
        """Print stats with latency metrics"""
        runtime = (datetime.now() - self.start_time).total_seconds() / 60

        # Calculate average latency
        if self.stats["latencies"]:
            avg_latency = sum(self.stats["latencies"]) / len(self.stats["latencies"])
            self.stats["avg_latency_ms"] = avg_latency
        else:
            avg_latency = 0.0

        logger.debug(f"\n📈 Stats (Runtime: {runtime:.1f}m):")
        logger.debug(f"   News Checked: {self.stats['news_checked']}")
        logger.debug(f"   Signals: {self.stats['signals_generated']}")
        logger.debug(f"   Trades: {self.stats['trades_executed']}")
        logger.debug(f"   Open Positions: {len(self.positions)}")
        logger.debug(f"   Avg Latency: {avg_latency:.0f}ms")

    async def _shutdown(self):
        """Shutdown with performance report"""
        logger.info("\n" + "=" * 80)
        logger.info("🛑 SHUTTING DOWN")
        logger.info("=" * 80)

        # Close positions
        if self.positions:
            for token_id, position in list(self.positions.items()):
                await self._close_position(token_id, position, "Shutdown")

        # [NEW] Cleanup internal systems
        if self.news_aggregator and hasattr(self.news_aggregator, "close"):
            try:
                await self.news_aggregator.close()
                logger.info("✅ NewsAggregator closed")
            except Exception as e:
                logger.error(f"Error closing NewsAggregator: {e}")

        if self.rag_system and hasattr(self.rag_system, "close"):
            try:
                await self.rag_system.close()
                logger.info("✅ RAG System closed")
            except Exception as e:
                logger.error(f"Error closing RAG System: {e}")

        # Final stats
        runtime = (datetime.now() - self.start_time).total_seconds() / 60
        avg_latency = self.stats["avg_latency_ms"]

        # Calculate win rate
        total_trades = self.stats['wins'] + self.stats['losses']
        win_rate = (self.stats['wins'] / total_trades * 100) if total_trades > 0 else 0

        logger.info(f"\n📊 Final Performance Report:")
        logger.info(f"   Runtime: {runtime:.1f}m")
        logger.info(f"   News Checked: {self.stats['news_checked']}")
        logger.info(f"   Signals Generated: {self.stats['signals_generated']}")
        logger.info(f"   Trades Executed: {self.stats['trades_executed']}")
        logger.info(f"   Positions Closed: {self.stats['positions_closed']}")

        logger.info(f"\n💰 Trading Results:")
        logger.info(f"   Total P&L: ${self.stats['total_pnl']:+.2f}")
        logger.info(f"   Wins: {self.stats['wins']}")
        logger.info(f"   Losses: {self.stats['losses']}")
        logger.info(f"   Win Rate: {win_rate:.1f}%")
        if total_trades > 0:
            avg_pnl_per_trade = self.stats['total_pnl'] / total_trades
            logger.info(f"   Avg P&L per trade: ${avg_pnl_per_trade:+.2f}")

        logger.info(f"\n⚡ Performance:")
        logger.info(f"   Average Latency: {avg_latency:.0f}ms")
        logger.info(f"   Target: <2000ms")
        logger.info(f"   Status: {'✅ PASS' if avg_latency < 2000 else '⚠️  SLOW'}")
        logger.info("=" * 80)

    async def shutdown(self):
        """External shutdown hook for SwarmSystem."""
        if self.stream_task:
            self.stream_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.stream_task
            self.stream_task = None

        if self.start_time:
            with suppress(Exception):
                await self._shutdown()

    async def _is_processed(self, news_id: str) -> bool:
        """Check if news_id has been processed (Redis first, then local)"""
        # Local Fast Path
        if news_id in self.processed_cache:
            return True
            
        # Redis Slow Path
        if self.redis:
            try:
                 exists = await self.redis.sismember(self.processed_redis_key, news_id)
                 if exists:
                     self.processed_cache.add(news_id) # Backfill local
                     return True
            except Exception as e:
                logger.error(f"Redis dedupe check failed: {e}")
        
        return False

    async def _mark_processed(self, news_id: str):
        """Mark news_id as processed"""
        self.processed_cache.add(news_id)
             
        if self.redis:
            try:
                await self.redis.sadd(self.processed_redis_key, news_id)
            except Exception as e:
                logger.error(f"Redis dedupe set failed: {e}")

    async def _unmark_processed(self, news_id: str):
        """Unmark news_id (for retry on error)"""
        if news_id in self.processed_cache:
            self.processed_cache.remove(news_id)
            
        if self.redis:
            try:
                await self.redis.srem(self.processed_redis_key, news_id)
            except Exception as e:
                logger.error(f"Redis dedupe remove failed: {e}")
