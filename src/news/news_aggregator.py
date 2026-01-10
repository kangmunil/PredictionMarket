"""
Multi-Source News Aggregator
============================

Combines multiple news sources for maximum speed and coverage:
- NewsAPI (general news)
- Tree News (crypto-specific, faster)

Strategy: Query both sources, deduplicate, return fastest/best matches

Author: ArbHunter
Created: 2026-01-03
"""

import asyncio
import logging
from typing import List, Dict, Set, Optional
from datetime import datetime
import feedparser
import aiohttp
import time

from .news_client import NewsAPIClient, TreeNewsClient

logger = logging.getLogger(__name__)


class NewsAggregator:
    """
    Multi-source news aggregator.
    Now with FREE RSS Feed support!
    """

    # 2026년 검증된 신뢰 소스 (크립토 + 금융 매체)
    TRUSTED_SOURCES = [
        "Bloomberg", "Reuters", "Financial Times", "Wall Street Journal",
        "CoinDesk", "The Block", "Cointelegraph", "Decrypt", "DL News",
        "Binance", "Coinbase", "Kraken",
        "Unchained", "CryptoSlate", "Bitcoin Magazine", "CryptoPanic"
    ]

    # FREE RSS Feeds (Unrestricted access)
    RSS_FEEDS = {
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "Cointelegraph": "https://cointelegraph.com/rss",
        "The Block": "https://www.theblock.co/rss.xml",
        "Decrypt": "https://decrypt.co/feed",
        "Bitcoin Magazine": "https://bitcoinmagazine.com/.rss/full/",
        "CryptoPanic": "https://cryptopanic.com/news/rss/"
    }

    def __init__(self, news_api_key: str = None, tree_api_key: str = None,
                 enable_source_filter: bool = False):
        self.sources = {}
        self.enable_source_filter = enable_source_filter
        self._rss_session: Optional[aiohttp.ClientSession] = None
        self.newsapi_cooldown_until: Optional[float] = None

        if news_api_key:
            self.sources['newsapi'] = NewsAPIClient(api_key=news_api_key)
            logger.info("✅ NewsAPI source enabled")

        if tree_api_key:
            self.sources['tree'] = TreeNewsClient(api_key=tree_api_key)
            logger.info("✅ Tree News source enabled")

        logger.info(f"📡 RSS Feeds enabled ({len(self.RSS_FEEDS)} sources)")
        self.seen_urls = set()

    async def get_breaking_news(
        self,
        keywords: List[str],
        max_results: int = 50, # Increased for RSS
        use_all_sources: bool = True
    ) -> List[Dict]:
        """Fetch news from API + RSS in parallel"""
        tasks = []

        # 1. API Sources
        if 'tree' in self.sources:
            tasks.append(self._fetch_from_tree(keywords, 20))
        if 'newsapi' in self.sources and not self._newsapi_in_cooldown():
            tasks.append(self._fetch_from_newsapi(keywords, 20))

        # 2. RSS Sources (Always available & FREE)
        tasks.append(self._fetch_all_rss(keywords))

        # Run in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_articles = []
        for result in results:
            if isinstance(result, list):
                all_articles.extend(result)
            elif isinstance(result, Exception):
                logger.error(f"Source error: {result}")

        # Deduplicate
        unique_articles = self._deduplicate(all_articles)

        # Filter by credibility
        if self.enable_source_filter:
            unique_articles = self._filter_by_credibility(unique_articles)

        # Sort by freshness
        unique_articles.sort(key=lambda x: x.get('publishedAt', ''), reverse=True)

        final_articles = unique_articles[:max_results]
        logger.info(f"📰 Aggregated {len(final_articles)} unique articles (API + RSS)")

        return final_articles

    async def _fetch_all_rss(self, keywords: List[str]) -> List[Dict]:
        """Fetch from all RSS feeds concurrently"""
        tasks = [self._fetch_single_rss(name, url, keywords) for name, url in self.RSS_FEEDS.items()]
        results = await asyncio.gather(*tasks)
        return [item for sublist in results for item in sublist]

    async def _fetch_single_rss(self, source_name: str, url: str, keywords: List[str]) -> List[Dict]:
        """Fetch and parse a single RSS feed"""
        articles = []
        try:
            session = await self._ensure_rss_session()
            async with session.get(url, timeout=10) as response:
                content = await response.text()
                feed = feedparser.parse(content)
                
                for entry in feed.entries[:30]:
                    title = entry.get('title', '')
                    summary = entry.get('summary', '') or entry.get('description', '')
                    link = entry.get('link', '')
                    
                    # Filter by keywords (Simple case-insensitive match)
                    if any(kw.lower() in title.lower() or kw.lower() in summary.lower() for kw in keywords):
                        articles.append({
                            "source": {"name": source_name},
                            "title": title,
                            "description": summary,
                            "url": link,
                            "publishedAt": entry.get('published', datetime.now().isoformat()),
                            "content": summary
                        })
        except Exception as e:
            logger.debug(f"RSS error ({source_name}): {e}")
        return articles

    async def _fetch_from_newsapi(self, keywords: List[str], limit: int) -> List[Dict]:
        # ... (same as original newsapi fetch) ...
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: self.sources['newsapi'].get_breaking_news(keywords=keywords, max_results=limit)
            )
        except Exception as e:
            error_text = str(e).lower()
            if any(keyword in error_text for keyword in ("429", "too many requests", "rate limit")):
                backoff_seconds = 300
                self.newsapi_cooldown_until = time.time() + backoff_seconds
                logger.warning(
                    "🛑 NewsAPI rate limit detected (via exception). Backing off for %ss",
                    backoff_seconds,
                )
            else:
                logger.error(f"NewsAPI fetch error: {e}")
            return []

    async def _fetch_from_tree(self, keywords: List[str], limit: int) -> List[Dict]:
        # ... (same as original tree news fetch) ...
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: self.sources['tree'].get_breaking_news(keywords=keywords, max_results=limit)
            )
        except: return []

    def _deduplicate(self, articles: List[Dict]) -> List[Dict]:
        unique = []
        seen_in_batch = set()
        for article in articles:
            url = article.get('url', '')
            if not url or url in seen_in_batch or url in self.seen_urls:
                continue
            unique.append(article)
            seen_in_batch.add(url)
            self.seen_urls.add(url)
        return unique

    def _filter_by_credibility(self, articles: List[Dict]) -> List[Dict]:
        trusted = []
        for article in articles:
            source_info = article.get('source', {})
            source_name = source_info.get('name', '') if isinstance(source_info, dict) else str(source_info)
            if any(ts.lower() in source_name.lower() for ts in self.TRUSTED_SOURCES):
                trusted.append(article)
        return trusted

    def get_stats(self) -> Dict:
        return {"sources": list(self.sources.keys()) + ["RSS"], "total_seen": len(self.seen_urls)}

    async def _ensure_rss_session(self) -> aiohttp.ClientSession:
        if self._rss_session is None or self._rss_session.closed:
            self._rss_session = aiohttp.ClientSession()
        return self._rss_session

    async def close(self):
        if self._rss_session and not self._rss_session.closed:
            await self._rss_session.close()
            logger.info("✅ NewsAggregator RSS session closed")

    def _newsapi_in_cooldown(self) -> bool:
        return (
            self.newsapi_cooldown_until is not None
            and time.time() < self.newsapi_cooldown_until
        )


# Standalone test
async def test_aggregator():
    """Test multi-source aggregation"""
    import os

    logging.basicConfig(level=logging.INFO)

    news_api_key = os.getenv("NEWS_API_KEY")
    tree_api_key = os.getenv("TREE_NEWS_API_KEY")

    print("\n" + "=" * 70)
    print("🌐 Multi-Source News Aggregator - Test")
    print("=" * 70)

    aggregator = NewsAggregator(
        news_api_key=news_api_key,
        tree_api_key=tree_api_key
    )

    stats = aggregator.get_stats()
    print(f"\n📊 Aggregator Stats:")
    print(f"   Sources enabled: {stats['sources_enabled']}")
    print(f"   Sources: {', '.join(stats['sources'])}")

    # Fetch Bitcoin news
    print(f"\n🔍 Fetching Bitcoin news from all sources...")

    articles = await aggregator.get_breaking_news(
        keywords=["bitcoin", "btc"],
        max_results=10
    )

    print(f"\n✅ Found {len(articles)} unique articles:\n")

    for i, article in enumerate(articles[:5], 1):
        print(f"{i}. {article['title'][:70]}...")
        print(f"   Source: {article['source']['name']}")
        if 'score' in article:
            print(f"   Score: {article['score']:.2f}")
        print(f"   URL: {article['url'][:50]}...")
        print()

    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_aggregator())
