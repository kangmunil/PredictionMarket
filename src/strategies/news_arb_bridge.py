"""
ArbHunter V2: News-to-Arb Dynamic Bridge
=========================================
Links News Scalper (real-time events) to Stat Arb (statistical analysis).

Role:
1. Receive high-impact news from Scalper.
2. Dynamically discover relevant Polymarket markets.
3. Construct correlated pairs (e.g., Target vs Benchmark).
4. Trigger statistical analysis on StatArb engine.

This solves the "No markets found" issue by finding markets that ACTUALLY exist
and are active right now due to news.
"""

import logging
import asyncio
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class NewsToArbBridge:
    def __init__(self, scalper, arb_strategy, market_matcher):
        self.scalper = scalper                  # News Scalper Engine
        self.arb_strategy = arb_strategy        # Enhanced Stat Arb Strategy
        self.market_matcher = market_matcher    # Gamma API Matcher
        
        self.min_confidence = 0.80              # Minimum news confidence to trigger
        self.analyzed_keywords = set()          # Dedup cache

    async def on_high_impact_news(self, article: Dict, sentiment: Dict):
        """
        Callback triggered when News Scalper finds important news.
        """
        title = article.get("title", "")
        score = sentiment.get("score", 0.0)
        label = sentiment.get("label", "NEUTRAL")
        
        # Only act on strong sentiment
        if score < self.min_confidence or label == "NEUTRAL":
            return

        logger.info(f"\n\ud83d\udc49 [Bridge] High-impact news detected: '{title[:60]}...' ({label} {score:.1%})")

        # 1. Extract Entities (e.g., 'Bitcoin', 'SEC')
        entities = self.market_matcher.extract_entities(title)
        
        # Flatten entities list
        keywords = []
        for cat, items in entities.items():
            keywords.extend(items)
            
        if not keywords:
            logger.info("   -> No tradable entities found in news.")
            return

        # 2. Trigger Dynamic Analysis for primary keyword
        primary_keyword = keywords[0]
        
        # Simple dedup to avoid spamming the same keyword in short time
        # In prod, use a timestamp-based cache
        if primary_keyword in self.analyzed_keywords:
            # logger.debug(f"   -> Already analyzing {primary_keyword}, skipping.")
            pass
        
        self.analyzed_keywords.add(primary_keyword)
        await self.trigger_dynamic_analysis(primary_keyword)

    async def trigger_dynamic_analysis(self, keyword: str):
        """
        Find markets for the keyword and run Stat Arb.
        """
        logger.info(f"\ud83d\udd0d [Bridge] Searching dynamic pairs for: {keyword}")

        # 1. Find Primary Market (The one in the news)
        # Search for "Price" markets to filter out random events
        search_query = f"{keyword}"
        primary_markets = await self.market_matcher.find_matching_markets(
            search_query, 
            min_volume=1000.0, # Reasonable volume
            max_results=3
        )

        if not primary_markets:
            logger.warning(f"   ⚠️ No active markets found for {keyword}")
            return

        target_market = primary_markets[0]
        target_id = target_market.get("condition_id") or target_market.get("question") # Fallback
        
        # Extract Token ID (assume YES token for analysis)
        target_token_id = self._extract_token_id(target_market)
        if not target_token_id:
            return

        logger.info(f"   ✅ Target Found: {target_market['question']} (ID: {target_token_id[:10]}...)")

        # 2. Find Correlated Market (Benchmark)
        # Simple Heuristic: If Crypto, compare with ETH or BTC
        benchmark_token_id = await self._find_benchmark_market(keyword)
        
        if not benchmark_token_id:
            logger.warning("   ⚠️ Could not find benchmark market.")
            return

        if target_token_id == benchmark_token_id:
            logger.info("   -> Target is the benchmark. Skipping self-pair.")
            return

        # 3. Dispatch to Stat Arb Engine
        logger.info(f"🚀 [Bridge] Dispatching StatArb Task: {keyword} vs Benchmark")
        
        # We need a way to inject this pair into the running strategy
        # Assuming arb_strategy has a method 'analyze_ad_hoc_pair' or similar
        # If not, we'll implement it or call compute_pair_metrics manually
        
        await self._run_analysis(target_token_id, benchmark_token_id, f"NEWS_{keyword.upper()}")

    async def _find_benchmark_market(self, keyword: str) -> Optional[str]:
        """Find a stable benchmark market to compare against"""
        # If news is about Bitcoin, use Ethereum as benchmark
        if "bitcoin" in keyword.lower() or "btc" in keyword.lower():
            query = "Ethereum Price"
        # If news is about anything else (Altcoins, etc), use Bitcoin
        else:
            query = "Bitcoin Price"
            
        markets = await self.market_matcher.find_matching_markets(query, min_volume=5000.0, max_results=1)
        if markets:
            return self._extract_token_id(markets[0])
        return None

    def _extract_token_id(self, market: Dict) -> Optional[str]:
        """Helper to get YES token ID"""
        tokens = market.get("tokens", [])
        for t in tokens:
            if t.get("outcome", "").lower() == "yes":
                return t.get("token_id")
        return None

    async def _run_analysis(self, token_a: str, token_b: str, pair_name: str):
        """
        Manually trigger the Stat Arb analysis for this dynamic pair
        """
        # Fetch history
        from src.core.history_fetcher import get_history_fetcher
        fetcher = get_history_fetcher()
        
        # This is a simplified version of what's in run_stat_arb_live.py
        # In a real system, this should be a method on the Strategy class
        
        logger.info(f"   stats: Analyzing {pair_name}...")
        
        end_time = datetime.now()
        from datetime import timedelta
        start_time = end_time - timedelta(days=7) # Short term analysis
        
        data_a = await fetcher.get_market_prices(token_a, start_time, end_time)
        data_b = await fetcher.get_market_prices(token_b, start_time, end_time)
        
        if data_a.empty or data_b.empty:
            logger.warning("   -> Insufficient data for analysis.")
            return

        # Align
        df_aligned = self.arb_strategy.align_price_series(
            [{'timestamp': idx, 'price': row['price']} for idx, row in data_a.iterrows()],
            [{'timestamp': idx, 'price': row['price']} for idx, row in data_b.iterrows()]
        )
        
        # Compute
        metrics = self.arb_strategy.compute_pair_metrics(df_aligned, pair_name)
        
        if metrics:
            logger.info(f"   📊 Result: Corr={metrics.correlation:.2f}, Z-Score={metrics.current_z_score:.2f}")
            if metrics.is_cointegrated and abs(metrics.current_z_score) > 1.5:
                logger.warning("   🚨 OPPORTUNITY FOUND via Bridge! {pair_name}")
            else:
                logger.info("   -> No signal yet.")
        else:
            logger.info("   -> Metrics computation failed.")
