"""
Market Matcher - News to Polymarket
====================================

Matches news articles to relevant Polymarket markets.

Uses:
- Entity extraction (Bitcoin, Trump, Fed, etc.)
- Keyword matching
- Fuzzy text similarity
- Market volume/liquidity filtering

Author: ArbHunter
Created: 2026-01-03
"""

import logging
import re
from typing import List, Dict, Optional, Tuple
from difflib import SequenceMatcher
import requests
import asyncio
import json
import os

from src.core.polymarket_mcp_client import (
    get_default_mcp_client,
    PolymarketMCPClient,
)
from src.core.market_registry import market_registry

logger = logging.getLogger(__name__)


class MarketMatcher:
    """
    Matches news to relevant Polymarket markets.

    Strategy:
    1. Extract entities from news (Bitcoin, Trump, etc.)
    2. Search Gamma API for markets with those entities
    3. Score matches by relevance
    4. Return top N most relevant markets
    """

    # Entity patterns (expandable)
    ENTITY_PATTERNS = {
        "crypto": [
            r"\bbitcoin\b", r"\bbtc\b",
            r"\bethereum\b", r"\beth\b",
            r"\bsolana\b", r"\bsol\b",
            r"\bripple\b", r"\bxrp\b",
            r"\bcrypto(?:currency)?\b",
            r"\bdefi\b", r"\bnft\b"
        ],
        "politics": [
            r"\btrump\b", r"\bbiden\b",
            r"\belection\b", r"\bpresident(?:ial)?\b",
            r"\bdemocrat(?:ic|s)?\b", r"\brepublican(?:s)?\b",
            r"\bcongress\b", r"\bsenate\b"
        ],
        "economy": [
            r"\bfed(?:eral reserve)?\b", r"\bfomc\b",
            r"\binterest rate\b", r"\binflation\b",
            r"\brecession\b", r"\bgdp\b",
            r"\bunemployment\b"
        ],
        "general": [
            r"\bstock\b", r"\bmarket\b",
            r"\bprice\b", r"\bvalue\b",
            r"\bincrease\b", r"\bdecrease\b",
            r"\brally\b", r"\bcrash\b"
        ]
    }

    def __init__(
        self,
        gamma_api_url: str = "https://gamma-api.polymarket.com",
        use_mcp: Optional[bool] = None,
    ):
        self.gamma_api_url = gamma_api_url
        self.cache = {}  # Cache market searches
        if use_mcp is None:
            use_mcp = bool(os.getenv("POLYMARKET_MCP_URL"))
        self._mcp_enabled = use_mcp
        self._mcp_client: Optional[PolymarketMCPClient] = None

    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """
        Extract entities from text.

        Args:
            text: News headline or article text

        Returns:
            Dict of category -> [matched_entities]

        Example:
            >>> matcher = MarketMatcher()
            >>> entities = matcher.extract_entities("Bitcoin and Ethereum rally")
            >>> print(entities)
            {'crypto': ['bitcoin', 'ethereum']}
        """
        text_lower = text.lower()
        entities = {}

        for category, patterns in self.ENTITY_PATTERNS.items():
            matches = []
            for pattern in patterns:
                found = re.findall(pattern, text_lower, re.IGNORECASE)
                matches.extend(found)

            if matches:
                # Deduplicate and keep unique
                entities[category] = list(set(matches))

        return entities

    async def find_matching_markets(
        self,
        news_text: str,
        min_volume: float = 10.0,
        max_results: int = 5,
        override_keywords: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Find Polymarket markets matching news.

        Args:
            news_text: News headline or article text
            min_volume: Minimum market volume (USD)
            max_results: Maximum markets to return
            override_keywords: Optional list of keywords to use (skips internal extraction)

        Returns:
            List of markets sorted by relevance score
        """
        # Use override keywords if provided (e.g. from LLM), otherwise extract using regex
        if override_keywords:
            keywords = override_keywords
            logger.debug(f"Using provided keywords: {keywords}")
        else:
            # Extract entities from news
            entities = self.extract_entities(news_text)
            
            if not entities:
                logger.debug("No entities found in news text")
                return []

            # Build search keywords
            keywords = []
            for category_entities in entities.values():
                keywords.extend(category_entities)

        # Remove duplicates
        keywords = list(set(keywords))

        logger.debug(f"Extracted keywords: {keywords}")

        # Search markets
        markets = await self._search_markets(keywords, min_volume)
        for market in markets:
            market_registry.register_market(market)

        # Score and rank
        scored_markets = []
        for market in markets:
            score = self._calculate_relevance_score(
                news_text,
                market.get("question", ""),
                keywords
            )
            scored_markets.append({
                **market,
                "relevance_score": score
            })

        # Sort by score (descending)
        scored_markets.sort(key=lambda m: m["relevance_score"], reverse=True)

        return scored_markets[:max_results]

    # Prioritized mapping for high-speed matching
    TOPIC_MAPPING = {
        "bitcoin": ["bitcoin", "btc", "price"],
        "ethereum": ["ethereum", "eth", "price"],
        "solana": ["solana", "sol", "price"],
        "trump": ["trump", "president", "election"],
        "fed": ["fed", "rate", "cut", "hike"],
        "sec": ["sec", "crypto", "regulation"]
    }

    async def _search_markets(
        self,
        keywords: List[str],
        min_volume: float
    ) -> List[Dict]:
        """
        Hyper-relaxed search for news trading.
        """
        if not keywords: return []

        search_queries = set()
        for kw in keywords:
            kw_l = kw.lower()
            search_queries.add(kw_l)
            if kw_l in self.TOPIC_MAPPING:
                search_queries.update(self.TOPIC_MAPPING[kw_l])

        if await self._maybe_init_mcp():
            markets = await self._search_markets_via_mcp(search_queries, min_volume)
            if markets is not None:
                return markets

        return await self._search_markets_via_gamma(search_queries, min_volume)

    async def _maybe_init_mcp(self) -> bool:
        if not self._mcp_enabled:
            return False
        if self._mcp_client:
            return True
        try:
            self._mcp_client = await get_default_mcp_client()
        except Exception as exc:
            logger.error("MarketMatcher MCP init failed: %s", exc)
            self._mcp_enabled = False
            return False
        if not self._mcp_client:
            self._mcp_enabled = False
            return False
        return True

    async def _search_markets_via_gamma(self, search_queries: set, min_volume: float) -> List[Dict]:
        url = f"{self.gamma_api_url}/markets"

        async def fetch_query(q):
            params = {"active": "true", "closed": "false", "limit": 100, "query": q}
            try:
                loop = asyncio.get_event_loop()
                resp = await loop.run_in_executor(None, lambda: requests.get(url, params=params, timeout=10))
                return resp.json() if resp.status_code == 200 else []
            except Exception:
                return []

        tasks = [fetch_query(q) for q in list(search_queries)[:5]]
        results = await asyncio.gather(*tasks)

        unique_markets = {}
        for market_list in results:
            if isinstance(market_list, dict):
                market_list = market_list.get("data", [])
            for market in market_list or []:
                m_id = market.get("condition_id") or market.get("id")
                if not m_id or m_id in unique_markets:
                    continue
                try:
                    clob_ids = market.get("clobTokenIds", [])
                    if isinstance(clob_ids, str):
                        clob_ids = json.loads(clob_ids)
                    standard_tokens = market.get("tokens", [])
                    if (clob_ids and len(clob_ids) >= 2) or (len(standard_tokens) >= 2):
                        unique_markets[m_id] = market
                except Exception:
                    continue

        logger.debug("💎 Total unique market candidates: %d", len(unique_markets))
        return list(unique_markets.values())

    async def _search_markets_via_mcp(self, queries: set, min_volume: float) -> Optional[List[Dict]]:
        assert self._mcp_client
        tasks = []
        for q in list(queries)[:5]:
            tasks.append(self._mcp_client.search_markets(query=q, limit=50, closed=False))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        unique_markets: Dict[str, Dict] = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error("MCP search error: %s", result)
                continue
            markets = result
            if isinstance(result, dict):
                markets = result.get("markets", [])

            for market in markets or []:
                m_id = market.get("condition_id") or market.get("id")
                if not m_id or m_id in unique_markets:
                    continue
                try:
                    volume = float(market.get("volume", 0))
                except (TypeError, ValueError):
                    volume = 0
                if volume < min_volume:
                    continue
                unique_markets[m_id] = market
                market_registry.register_market(market)
                market_registry.register_market(market)

        if not unique_markets:
            self._mcp_enabled = False
            logger.warning("MCP returned no candidates, reverting to Gamma API")
            return None

        logger.debug("💎 MCP supplied %d unique market candidates", len(unique_markets))
        return list(unique_markets.values())

    def _calculate_relevance_score(
        self,
        news_text: str,
        market_question: str,
        keywords: List[str]
    ) -> float:
        """
        Calculate relevance score (0.0 to 1.0).

        Factors:
        - Text similarity (news vs market question)
        - Keyword overlap
        - Entity importance
        """
        news_lower = news_text.lower()
        question_lower = market_question.lower()

        # Factor 1: Text similarity (using SequenceMatcher)
        similarity = SequenceMatcher(None, news_lower, question_lower).ratio()

        # Factor 2: Keyword overlap
        keyword_count = sum(1 for kw in keywords if kw.lower() in question_lower)
        keyword_score = min(keyword_count / len(keywords), 1.0) if keywords else 0.0

        # Factor 3: Exact keyword match bonus
        exact_matches = sum(1 for kw in keywords if f" {kw.lower()} " in f" {question_lower} ")
        exact_bonus = 0.2 if exact_matches > 0 else 0.0

        # Weighted average
        score = (
            similarity * 0.4 +
            keyword_score * 0.4 +
            exact_bonus * 0.2
        )

        return score

    def get_best_match(
        self,
        news_text: str,
        markets: List[Dict],
        min_score: float = 0.3
    ) -> Optional[Dict]:
        """
        Get single best matching market.

        Args:
            news_text: News text
            markets: List of candidate markets
            min_score: Minimum relevance score

        Returns:
            Best matching market or None
        """
        if not markets:
            return None

        # Find highest scored market
        best = max(markets, key=lambda m: m.get("relevance_score", 0.0))

        if best.get("relevance_score", 0.0) >= min_score:
            return best

        return None


# Standalone test
if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)

    async def test():
        print("\n" + "=" * 70)
        print("🔍 Market Matcher - Test Suite")
        print("=" * 70)

        matcher = MarketMatcher()

        # Test headlines
        test_cases = [
            "Bitcoin hits new all-time high of $100,000",
            "Trump leads Biden in latest polls",
            "Fed announces interest rate cut",
            "Ethereum network upgrade goes live"
        ]

        for headline in test_cases:
            print(f"\n📰 News: \"{headline}\"")

            # Extract entities
            entities = matcher.extract_entities(headline)
            print(f"   Entities: {entities}")

            # Find matching markets
            markets = await matcher.find_matching_markets(
                headline,
                min_volume=10.0,
                max_results=3
            )

            if markets:
                print(f"   ✅ Found {len(markets)} relevant markets:")
                for i, market in enumerate(markets, 1):
                    print(f"   {i}. {market.get('question', 'Unknown')[:60]}...")
                    print(f"      Relevance: {market.get('relevance_score', 0):.2%}")
                    print(f"      Volume: ${market.get('volume', 0):,.0f}")
            else:
                print("   ❌ No matching markets found")

        print("\n" + "=" * 70)
        print("✅ Test complete!")

    asyncio.run(test())
