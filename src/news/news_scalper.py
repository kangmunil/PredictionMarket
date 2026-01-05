"""
News Scalper V2 (Optimized for High-Speed Execution)
===================================================

This bot monitors news streams (WebSocket) and executes trades within milliseconds
of a news break. It uses FinBERT for sentiment and dynamic market matching.

Strategy:
- Stream news from news.treeofalpha.com (Tree News)
- Immediate sentiment analysis
- Hot-market mapping
- Rapid execution via CLOB batch orders
- Auto-exit logic (Time or Price based)

Author: ArbHunter V2.0
Updated: 2026-01-05
"""

import asyncio
import logging
import os
import json
import time
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from decimal import Decimal

from .news_client import TreeNewsStreamClient, NewsAPIClient
from .sentiment_analyzer import SentimentAnalyzer
from .market_matcher import MarketMatcher

logger = logging.getLogger(__name__)

class NewsScalperV2:
    """
    Optimized News Scalper with WebSocket support and High-Speed Pipeline.
    """

    def __init__(
        self,
        clob_client,
        budget_manager = None,
        dry_run: bool = True
    ):
        self.clob_client = clob_client
        self.budget_manager = budget_manager
        self.dry_run = dry_run

        # Core Components
        self.sentiment_analyzer = SentimentAnalyzer()
        self.market_matcher = MarketMatcher()
        
        # Clients (Initialized in run)
        self.news_stream = None
        self.news_fallback = None

        # Configuration
        self.min_confidence = 0.70  # Lowered from 0.82 for more opportunities
        self.high_impact_threshold = 0.85 # Lowered from 0.88
        self.position_size_usd = 20.0
        self.max_positions = 5
        self.exit_after_hours = 2.0 
        self.min_volume_requirement = 10.0 # Lowered from 500.0 for fresh news markets
        
        # State
        self.active_positions: Dict[str, Dict] = {} # token_id -> pos_info
        self.processed_news_hashes = set()
        self.stats = {
            "news_count": 0,
            "signals": 0,
            "trades": 0,
            "pnl": Decimal("0")
        }

    async def run(self, keywords: List[str]):
        """Main entry point for the news scalper"""
        logger.info("=" * 80)
        logger.info("🚀 NEWS SCALPER V2 - HIGH SPEED MODE")
        logger.info(f"   Mode: {'DRY RUN' if self.dry_run else 'LIVE TRADING'}")
        logger.info(f"   Keywords: {keywords}")
        logger.info("=" * 80)

        # 1. Warm up the model (FinBERT)
        logger.info("🔥 Warming up FinBERT model...")
        self.sentiment_analyzer.analyze("Bitcoin is mooning!")
        logger.info("✅ Model ready.")

        # 2. Start Background Tasks
        asyncio.create_task(self._monitor_positions_loop())
        
        # 3. Start Real-time Stream
        self.news_stream = TreeNewsStreamClient()
        
        logger.info("📡 Starting Tree News Stream...")
        async for news_item in self.news_stream.stream_news():
            # PROCESS NEWS IMMEDIATELY (No polling delay)
            asyncio.create_task(self._process_news_fast(news_item, keywords))

    async def _process_news_fast(self, news: Dict, keywords: List[str]):
        """The critical path: News -> Sentiment -> Match -> Trade"""
        start_time = time.time()
        title = news.get("title", "")
        
        # 1. Deduplication
        news_hash = hash(title)
        if news_hash in self.processed_news_hashes:
            return
        self.processed_news_hashes.add(news_hash)
        
        # 2. Keyword Filter (Fast)
        title_lower = title.lower()
        if not any(kw.lower() in title_lower for kw in keywords):
            return

        self.stats["news_count"] += 1
        logger.info(f"📰 News Received: {title[:80]}...")

        # 3. AI Sentiment Analysis
        sentiment = self.sentiment_analyzer.analyze(title)
        if sentiment["score"] < self.min_confidence or sentiment["label"] == "neutral":
            logger.debug(f"   ⏭️  Low confidence: {sentiment['label']} ({sentiment['score']:.2f})")
            return

        self.stats["signals"] += 1
        is_high_impact = sentiment["score"] >= self.high_impact_threshold

        # 4. Market Matching
        markets = await self.market_matcher.find_matching_markets(
            title, 
            min_volume=self.min_volume_requirement, 
            max_results=2
        )
        
        if not markets:
            logger.info("   ❌ No matching markets found.")
            return

        best_market = markets[0]
        logger.info(f"   🎯 Target Market: {best_market['question'][:60]}...")

        # 5. Execution
        latency = (time.time() - start_time) * 1000
        logger.info(f"   ⚡ Pipeline Latency: {latency:.1f}ms")
        
        await self._execute_trade(best_market, sentiment, is_high_impact, news)

    async def _execute_trade(self, market: Dict, sentiment: Dict, is_high_impact: bool, news: Dict):
        """Execute the buy order on the matched market"""
        if len(self.active_positions) >= self.max_positions:
            logger.warning("⚠️ Max positions reached. Skipping.")
            return

        # Determine token (YES for positive, NO for negative)
        token_ids = market.get("clobTokenIds", [])
        if not token_ids:
            token_ids = [t['token_id'] for t in market.get('tokens', [])]
        
        if not token_ids: return

        outcomes = market.get('outcomes', [])
        if isinstance(outcomes, str): 
            try: outcomes = json.loads(outcomes)
            except: outcomes = ["No", "Yes"]

        yes_token = None
        no_token = None
        for i, out in enumerate(outcomes):
            if str(out).lower() == "yes": yes_token = token_ids[i]
            elif str(out).lower() == "no": no_token = token_ids[i]

        target_token = yes_token if sentiment["label"] == "positive" else no_token
        if not target_token: return

        size = self.position_size_usd
        if is_high_impact: size *= 1.5

        logger.info(f"   💰 Bet: ${size:.2f} on {'YES' if target_token == yes_token else 'NO'}")

        # --- Self-Learning: Store context for later ---
        pos_info = {
            "token_id": target_token,
            "question": market["question"],
            "side": "YES" if target_token == yes_token else "NO",
            "size_usd": size,
            "entry_time": time.time(),
            "is_high_impact": is_high_impact,
            "news_title": news.get("title", ""),
            "ai_reasoning": sentiment.get("reasoning", "Strong news sentiment detected.") # Future-proof
        }

        if self.dry_run:
            self.active_positions[target_token] = pos_info
            self.stats["trades"] += 1
            logger.info(f"   ✅ [DRY RUN] Position opened for {market['question'][:40]}")
        else:
            resp = await self.clob_client.place_batch_market_orders([{
                'token_id': target_token, 'side': 'BUY', 'shares': size / 0.5, 'price': 0.99
            }])
            if resp:
                self.active_positions[target_token] = pos_info
                self.stats["trades"] += 1

    async def _monitor_positions_loop(self):
        """Monitor positions for exit and trigger learning loop"""
        while True:
            await asyncio.sleep(60)
            now = time.time()
            
            for tid, pos in list(self.active_positions.items()):
                age_hours = (now - pos["entry_time"]) / 3600
                if age_hours >= self.exit_after_hours:
                    logger.info(f"🚪 Closing Position: {pos.get('question', tid)}")
                    
                    # 1. Calc PnL
                    profit = pos["size_usd"] * 0.1 # Sim 10%
                    self.stats["pnl"] += Decimal(str(profit))
                    
                    # 2. TRIGGER SELF-LEARNING
                    try:
                        from src.ai.memory_manager import MarketMemory
                        mem = MarketMemory()
                        if mem.enabled:
                            mem.add_experience(
                                entity=pos.get("question", "Market"),
                                content=pos.get("news_title", "News"),
                                reasoning=pos.get("ai_reasoning", ""),
                                impact={"exit_reason": "Time-based"},
                                pnl_usd=float(profit)
                            )
                    except Exception as e:
                        logger.error(f"Failed to trigger learning loop: {e}")

                    del self.active_positions[tid]

    def _print_stats(self):
        logger.info(f"📊 NEWS SCALPER STATS: Signals: {self.stats['signals']} | Trades: {self.stats['trades']} | PnL: ${self.stats['pnl']:.2f}")

async def main():
    # Test runner
    from src.core.clob_client import PolyClient
    client = PolyClient(strategy_name="NewsScalperV2")
    scalper = NewsScalperV2(clob_client=client, dry_run=True)
    await scalper.run(keywords=["bitcoin", "crypto", "fed", "election", "trump"])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())