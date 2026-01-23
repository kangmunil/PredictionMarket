"""
NewsAPI Client for Breaking News
=================================

Fetches breaking news from NewsAPI.org for news scalping strategy.

Features:
- Real-time news fetching
- Keyword filtering
- Source prioritization
- Rate limit handling

Author: ArbHunter
Created: 2026-01-03
"""

import logging
import time
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import requests

logger = logging.getLogger(__name__)


import json
import asyncio
import websockets

class TreeNewsStreamClient:
    """
    WebSocket client for Tree News (news.treeofalpha.com).
    Provides real-time news streaming with < 100ms latency.
    """

    def __init__(self, api_key: Optional[str] = None):
        import os
        self.api_key = api_key or os.getenv("TREE_NEWS_API_KEY")
        self.ws_url = "wss://news.treeofalpha.com/ws"
        self.is_running = False

    async def stream_news(self):
        """
        Connect to Tree News WebSocket and yield news items.
        """
        if not self.api_key:
            logger.error("❌ TREE_NEWS_API_KEY missing. Cannot start WebSocket stream.")
            return

        logger.info(f"🔌 Connecting to Tree News WebSocket: {self.ws_url}")
        
        backoff = 5
        self.last_heartbeat = time.time()
        
        while True:
            try:
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=30,  # Send pings every 30s
                    ping_timeout=10,   # Wait 10s for pong
                    close_timeout=5
                ) as ws:
                    logger.info("✅ Connected to Tree News WebSocket")
                    backoff = 5 # Reset on success
                    
                    while True:
                        try:
                            # Wait for message with timeout to check aliveness
                            message = await asyncio.wait_for(ws.recv(), timeout=45)
                            self.last_heartbeat = time.time()
                            
                        except asyncio.TimeoutError:
                            # It's been 45s since last message.
                            # websockets lib handles ping/pong automatically with ping_interval,
                            # so if we are here, connection MIGHT be idle but alive.
                            # Check for silence (no messages for 15 mins)
                            # This handles "zombie" connections that don't fail pings but send no data
                            if time.time() - self.last_heartbeat > 900:
                                logger.warning("⚠️ Tree News WS silent for 15 mins. Forcing reconnect.")
                                break
                            continue
                            
                        except websockets.exceptions.ConnectionClosed:
                            logger.warning("⚠️ Tree News WS connection closed. Reconnecting...")
                            break
                        
                        try:
                            data = json.loads(message)
                        except json.JSONDecodeError:
                            continue
                        
                        # Tree News WS sends various message types
                        if isinstance(data, dict) and data.get("title"):
                            # logger.info(f"📨 WS Received: {data.get('title')[:50]}...")
                            processed = {
                                "title": data.get("title", ""),
                                "description": data.get("content", ""),
                                "url": data.get("url", ""),
                                "source": {"name": data.get("source", "TreeNews")},
                                "publishedAt": datetime.now().isoformat(),
                                "content": data.get("content", ""),
                                "fetched_at": datetime.now().isoformat(),
                                "is_realtime": True
                            }
                            yield processed
                            
            except Exception as e:
                logger.error(f"❌ WebSocket connection error: {e}. Retrying in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

class TreeNewsClient:
    """
    Client for news.treeofalpha.com (Tree News).
    Highly recommended for high-frequency crypto news.
    """

    def __init__(self, api_key: Optional[str] = None):
        import os
        self.api_key = api_key or os.getenv("TREE_NEWS_API_KEY")
        self.base_url = "https://news.treeofalpha.com/api/news"

        if not self.api_key:
            logger.warning("⚠️ No TREE_NEWS_API_KEY found. Using Tree News will not work.")

    def get_breaking_news(self, keywords: List[str], max_results: int = 20) -> List[Dict]:
        """Fetch news from Tree News API"""
        if not self.api_key:
            return []

        # Tree News uses api_key as a query parameter
        params = {
            "api_key": self.api_key,
            "limit": 50
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json() # List of news items
            
            processed = []
            for item in data:
                # Filter by keywords in title
                title = item.get("title", "").lower()
                content = item.get("content", "").lower()
                
                if any(kw.lower() in title or kw.lower() in content for kw in keywords):
                    processed.append({
                        "title": item.get("title", ""),
                        "description": item.get("content", ""),
                        "url": item.get("url", ""),
                        "source": {"name": item.get("source", "TreeNews")},  # Match NewsAPI format
                        "publishedAt": datetime.fromtimestamp(item.get("time", 0)/1000).isoformat() if item.get("time") else datetime.now().isoformat(),
                        "content": item.get("content", ""),
                        "fetched_at": datetime.now().isoformat()
                    })
            
            return processed[:max_results]
        except Exception as e:
            logger.error(f"❌ Tree News error: {e}")
            return []

class NewsAPIClient:
    """
    Client for fetching breaking news from NewsAPI.org.

    Free tier: 100 requests/day
    Paid tier: 250 requests/day ($449/month)

    For testing, use free tier with smart caching.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize NewsAPI client.

        Args:
            api_key: NewsAPI key (get from newsapi.org)
                     If None, will try to read from environment
        """
        import os
        self.api_key = api_key or os.getenv("NEWS_API_KEY")

        if not self.api_key:
            logger.warning("⚠️ No NEWS_API_KEY found. News scalping will not work.")
            logger.warning("   Get a free key from https://newsapi.org")

        self.base_url = "https://newsapi.org/v2"
        self.cache = {}  # Simple cache to avoid duplicate requests
        self.cache_ttl = 60  # Cache for 60 seconds

        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = 1.0  # 1 second between requests (conservative)

    def get_breaking_news(
        self,
        keywords: List[str],
        sources: Optional[List[str]] = None,
        language: str = "en",
        max_results: int = 20
    ) -> List[Dict]:
        """
        Fetch breaking news matching keywords.

        Args:
            keywords: List of keywords to search (e.g., ["bitcoin", "ethereum"])
            sources: Optional list of sources (e.g., ["bloomberg", "reuters"])
            language: Language code (default: "en")
            max_results: Maximum number of results to return

        Returns:
            List of news articles with metadata
        """
        if not self.api_key:
            logger.error("❌ No API key configured")
            return []

        # Build query
        query = " OR ".join(keywords)
        cache_key = f"{query}_{sources}_{language}"

        # Check cache
        if cache_key in self.cache:
            cached_time, cached_results = self.cache[cache_key]
            if time.time() - cached_time < self.cache_ttl:
                logger.debug(f"📦 Returning cached results for: {query}")
                return cached_results

        # Rate limiting
        self._wait_for_rate_limit()

        # Make API request
        url = f"{self.base_url}/everything"
        params = {
            "q": query,
            "apiKey": self.api_key,
            "sortBy": "popularity",  # 인기도(조회수/인용수 기반) 높은 순으로 변경
            "language": language,
            "pageSize": min(max_results, 100)  # API max is 100
        }

        if sources:
            params["sources"] = ",".join(sources)

        try:
            logger.debug(f"📡 Fetching news for: {query}")
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if data.get("status") != "ok":
                logger.error(f"❌ NewsAPI error: {data.get('message', 'Unknown error')}")
                return []

            articles = data.get("articles", [])
            processed = [self._process_article(a) for a in articles]

            # Cache results
            self.cache[cache_key] = (time.time(), processed)

            logger.info(f"✅ Fetched {len(processed)} articles for: {query}")
            return processed

        except requests.exceptions.RequestException as e:
            response = getattr(e, "response", None)
            if response is not None and response.status_code == 429:
                raise
            logger.error(f"❌ Network error: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            return []

    def get_headlines(
        self,
        category: Optional[str] = None,
        country: str = "us",
        max_results: int = 20
    ) -> List[Dict]:
        """
        Fetch top headlines (faster, less quota usage).

        Args:
            category: Category (business, technology, etc.)
            country: Country code (us, gb, etc.)
            max_results: Maximum number of results

        Returns:
            List of headline articles
        """
        if not self.api_key:
            logger.error("❌ No API key configured")
            return []

        cache_key = f"headlines_{category}_{country}"

        # Check cache
        if cache_key in self.cache:
            cached_time, cached_results = self.cache[cache_key]
            if time.time() - cached_time < self.cache_ttl:
                return cached_results

        # Rate limiting
        self._wait_for_rate_limit()

        url = f"{self.base_url}/top-headlines"
        params = {
            "apiKey": self.api_key,
            "country": country,
            "pageSize": min(max_results, 100)
        }

        if category:
            params["category"] = category

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if data.get("status") != "ok":
                logger.error(f"❌ NewsAPI error: {data.get('message')}")
                return []

            articles = data.get("articles", [])
            processed = [self._process_article(a) for a in articles]

            # Cache results
            self.cache[cache_key] = (time.time(), processed)

            logger.info(f"✅ Fetched {len(processed)} headlines")
            return processed

        except Exception as e:
            logger.error(f"❌ Error fetching headlines: {e}")
            return []

    def _process_article(self, article: dict) -> Dict:
        """Process and normalize article data"""
        return {
            "title": article.get("title", ""),
            "description": article.get("description", ""),
            "url": article.get("url", ""),
            "source": article.get("source", {}).get("name", "Unknown"),
            "published_at": article.get("publishedAt", ""),
            "author": article.get("author"),
            "content": article.get("content", ""),
            # Add timestamp for freshness tracking
            "fetched_at": datetime.now().isoformat()
        }

    def _wait_for_rate_limit(self):
        """Ensure minimum interval between requests"""
        now = time.time()
        time_since_last = now - self.last_request_time

        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            logger.debug(f"⏳ Rate limiting: waiting {sleep_time:.2f}s")
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def is_article_fresh(self, article: Dict, max_age_minutes: int = 30) -> bool:
        """
        Check if article is recent enough to trade on.

        Args:
            article: Article dict with 'published_at' field
            max_age_minutes: Maximum age in minutes (default: 30)

        Returns:
            True if article is fresh enough
        """
        try:
            published_at = datetime.fromisoformat(
                article["published_at"].replace("Z", "+00:00")
            )
            age = datetime.now(published_at.tzinfo) - published_at
            return age < timedelta(minutes=max_age_minutes)
        except Exception as e:
            logger.debug(f"Error checking article freshness: {e}")
            return False


# Standalone test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test with dummy key (won't work, but shows structure)
    client = NewsAPIClient(api_key="test_key")

    print("\n📰 Testing NewsAPI Client\n")
    print("=" * 60)

    # Test 1: Get breaking news
    print("\n1. Fetching Bitcoin news...")
    articles = client.get_breaking_news(
        keywords=["bitcoin", "btc"],
        max_results=5
    )

    if articles:
        for i, article in enumerate(articles[:3], 1):
            print(f"\n{i}. {article['title']}")
            print(f"   Source: {article['source']}")
            print(f"   Published: {article['published_at']}")
    else:
        print("   ❌ No articles found (check API key)")

    # Test 2: Get headlines
    print("\n2. Fetching tech headlines...")
    headlines = client.get_headlines(
        category="technology",
        max_results=5
    )

    if headlines:
        for i, article in enumerate(headlines[:3], 1):
            print(f"\n{i}. {article['title']}")
            print(f"   Source: {article['source']}")
    else:
        print("   ❌ No headlines found (check API key)")

    print("\n" + "=" * 60)
    print("✅ Test complete!")
    print("\nTo use this client:")
    print("1. Get a free API key from https://newsapi.org")
    print("2. Set NEWS_API_KEY environment variable")
    print("3. Run: python src/news/news_client.py")
