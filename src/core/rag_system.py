"""
RAG System for News Analysis V2.0
===================================

Retrieval-Augmented Generation system for analyzing news impact on prediction markets.

Architecture:
1. News Ingestion: RSS feeds, NewsAPI, Twitter
2. Vector Store: ChromaDB for semantic search
3. LLM Analysis: OpenAI GPT-4 for event interpretation
4. EV Adjustment: Probability updates based on news
5. Persistence: Supabase for historical tracking

Use Cases:
- Breaking news → Immediate market impact assessment
- Historical pattern matching → Similar past events
- Entity tracking → Monitor specific players/companies
- Sentiment analysis → Market mood shifts

Author: ArbHunter V2.0
Created: 2026-01-02
"""

import asyncio
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
from dataclasses import dataclass
import json
import hashlib

# Vector store
import chromadb
from chromadb.config import Settings

# LLM
from openai import AsyncOpenAI

# News fetching
import feedparser
import aiohttp

# Supabase
from supabase import create_client, Client

logger = logging.getLogger(__name__)


@dataclass
class NewsEvent:
    """Structured news event"""
    event_id: str  # Hash of content
    title: str
    content: str
    source: str
    published_at: datetime
    entities: List[str]  # Extracted entities (companies, people, etc.)
    category: str  # "sports", "politics", "crypto", etc.
    url: Optional[str] = None
    sentiment: Optional[float] = None  # -1.0 (negative) to 1.0 (positive)

    def to_dict(self):
        return {
            'event_id': self.event_id,
            'title': self.title,
            'content': self.content,
            'source': self.source,
            'published_at': self.published_at.isoformat(),
            'entities': self.entities,
            'category': self.category,
            'url': self.url,
            'sentiment': self.sentiment
        }


@dataclass
class MarketImpact:
    """Assessed impact of news on market"""
    market_id: str  # Polymarket condition_id
    current_price: Decimal
    suggested_price: Decimal
    confidence: float  # 0.0 to 1.0
    reasoning: str
    similar_events: List[Dict]  # Historical parallels
    trade_recommendation: str  # "buy", "sell", "hold"
    expected_value: Decimal  # EV after news adjustment

    def to_dict(self):
        return {
            'market_id': self.market_id,
            'current_price': float(self.current_price),
            'suggested_price': float(self.suggested_price),
            'confidence': self.confidence,
            'reasoning': self.reasoning,
            'similar_events': self.similar_events,
            'trade_recommendation': self.trade_recommendation,
            'expected_value': float(self.expected_value)
        }


class RAGSystem:
    """
    Retrieval-Augmented Generation system for news-driven trading.

    Workflow:
    1. Fetch news from multiple sources
    2. Extract entities and categorize
    3. Store in vector database for semantic search
    4. Retrieve similar historical events
    5. Analyze with LLM (GPT-4)
    6. Calculate market impact and EV adjustment
    7. Generate trade recommendation
    """

    def __init__(
        self,
        openai_api_key: str,
        supabase_url: str,
        supabase_key: str,
        chroma_path: str = "./data/chromadb"
    ):
        self.openai_client = AsyncOpenAI(api_key=openai_api_key)

        # Supabase client
        self.supabase: Client = create_client(supabase_url, supabase_key)

        # ChromaDB for vector storage
        self.chroma_client = chromadb.Client(Settings(
            chroma_db_impl="duckdb+parquet",
            persist_directory=chroma_path
        ))

        # Collections
        self.news_collection = self.chroma_client.get_or_create_collection(
            name="news_events",
            metadata={"description": "Historical news events with embeddings"}
        )

        self.market_collection = self.chroma_client.get_or_create_collection(
            name="market_reactions",
            metadata={"description": "Historical market reactions to events"}
        )

        logger.info("✅ RAG System initialized")
        logger.info(f"   Vector store: {chroma_path}")
        logger.info(f"   News events indexed: {self.news_collection.count()}")
        logger.info(f"   Market reactions indexed: {self.market_collection.count()}")

    async def fetch_news_rss(self, feed_url: str, category: str) -> List[NewsEvent]:
        """
        Fetch news from RSS feed.

        Args:
            feed_url: RSS feed URL
            category: News category (sports, politics, crypto, etc.)

        Returns:
            List of NewsEvent objects
        """
        try:
            feed = feedparser.parse(feed_url)
            events = []

            for entry in feed.entries[:20]:  # Limit to 20 most recent
                # Generate unique ID
                event_id = hashlib.md5(
                    (entry.title + entry.link).encode()
                ).hexdigest()

                # Parse date
                try:
                    published_at = datetime(*entry.published_parsed[:6])
                except:
                    published_at = datetime.now()

                # Extract content
                content = entry.get('summary', entry.get('description', ''))

                event = NewsEvent(
                    event_id=event_id,
                    title=entry.title,
                    content=content,
                    source=feed.feed.get('title', 'RSS Feed'),
                    published_at=published_at,
                    entities=[],  # Will be extracted later
                    category=category,
                    url=entry.link
                )

                events.append(event)

            logger.info(f"📰 Fetched {len(events)} events from {feed_url}")
            return events

        except Exception as e:
            logger.error(f"Failed to fetch RSS feed {feed_url}: {e}")
            return []

    async def fetch_news_api(
        self,
        query: str,
        api_key: str,
        category: str,
        lookback_hours: int = 24
    ) -> List[NewsEvent]:
        """
        Fetch news from NewsAPI.

        Args:
            query: Search query (e.g., "Bitcoin", "Real Madrid")
            api_key: NewsAPI key
            category: News category
            lookback_hours: How far back to search

        Returns:
            List of NewsEvent objects
        """
        url = "https://newsapi.org/v2/everything"

        from_date = datetime.now() - timedelta(hours=lookback_hours)

        params = {
            'q': query,
            'from': from_date.isoformat(),
            'sortBy': 'publishedAt',
            'apiKey': api_key,
            'language': 'en',
            'pageSize': 20
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=30) as resp:
                    if resp.status != 200:
                        logger.error(f"NewsAPI error: {resp.status}")
                        return []

                    data = await resp.json()
                    events = []

                    for article in data.get('articles', []):
                        event_id = hashlib.md5(
                            (article['title'] + article['url']).encode()
                        ).hexdigest()

                        published_at = datetime.fromisoformat(
                            article['publishedAt'].replace('Z', '+00:00')
                        )

                        event = NewsEvent(
                            event_id=event_id,
                            title=article['title'],
                            content=article.get('description', ''),
                            source=article['source']['name'],
                            published_at=published_at,
                            entities=[],
                            category=category,
                            url=article['url']
                        )

                        events.append(event)

                    logger.info(f"📰 Fetched {len(events)} events from NewsAPI (query: {query})")
                    return events

        except Exception as e:
            logger.error(f"Failed to fetch from NewsAPI: {e}")
            return []

    async def extract_entities(self, event: NewsEvent) -> List[str]:
        """
        Extract named entities from news event using GPT-4.

        Args:
            event: NewsEvent to analyze

        Returns:
            List of entity names (companies, people, locations)
        """
        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o-mini",  # Faster and cheaper for entity extraction
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract named entities (people, companies, locations, events) "
                            "from the given news. Return only a JSON array of strings."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"Title: {event.title}\n\nContent: {event.content}"
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.3
            )

            result = json.loads(response.choices[0].message.content)
            entities = result.get('entities', [])

            logger.debug(f"Extracted {len(entities)} entities from '{event.title}'")
            return entities

        except Exception as e:
            logger.error(f"Failed to extract entities: {e}")
            return []

    async def store_news_event(self, event: NewsEvent):
        """
        Store news event in vector database and Supabase.

        Args:
            event: NewsEvent to store
        """
        # Generate embedding using OpenAI
        try:
            embedding_response = await self.openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=f"{event.title}\n\n{event.content}"
            )

            embedding = embedding_response.data[0].embedding

            # Store in ChromaDB
            self.news_collection.add(
                embeddings=[embedding],
                documents=[f"{event.title}\n\n{event.content}"],
                metadatas=[{
                    'event_id': event.event_id,
                    'title': event.title,
                    'source': event.source,
                    'category': event.category,
                    'published_at': event.published_at.isoformat(),
                    'entities': json.dumps(event.entities)
                }],
                ids=[event.event_id]
            )

            # Store in Supabase for persistence
            self.supabase.table('news_events').upsert({
                'event_id': event.event_id,
                'title': event.title,
                'content': event.content,
                'source': event.source,
                'published_at': event.published_at.isoformat(),
                'entities': event.entities,
                'category': event.category,
                'url': event.url,
                'sentiment': event.sentiment
            }).execute()

            logger.debug(f"✅ Stored event: {event.title[:50]}...")

        except Exception as e:
            logger.error(f"Failed to store event {event.event_id}: {e}")

    async def find_similar_events(
        self,
        event: NewsEvent,
        top_k: int = 5
    ) -> List[Dict]:
        """
        Find historically similar events using vector similarity.

        Args:
            event: Current event to find matches for
            top_k: Number of similar events to return

        Returns:
            List of similar events with metadata
        """
        try:
            # Generate embedding for query
            embedding_response = await self.openai_client.embeddings.create(
                model="text-embedding-3-small",
                input=f"{event.title}\n\n{event.content}"
            )

            query_embedding = embedding_response.data[0].embedding

            # Query ChromaDB
            results = self.news_collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={"category": event.category}  # Filter by category
            )

            similar_events = []
            if results['ids']:
                for i, event_id in enumerate(results['ids'][0]):
                    similar_events.append({
                        'event_id': event_id,
                        'title': results['metadatas'][0][i]['title'],
                        'similarity': 1 - results['distances'][0][i],  # Convert distance to similarity
                        'published_at': results['metadatas'][0][i]['published_at']
                    })

            return similar_events

        except Exception as e:
            logger.error(f"Failed to find similar events: {e}")
            return []

    async def analyze_market_impact(
        self,
        event: NewsEvent,
        market_id: str,
        current_price: Decimal,
        market_question: str
    ) -> MarketImpact:
        """
        Analyze how news event impacts a specific market.

        Uses GPT-4 + historical data to assess impact.

        Args:
            event: News event to analyze
            market_id: Polymarket condition_id
            current_price: Current market price (0.0-1.0)
            market_question: Market question text

        Returns:
            MarketImpact with recommendation
        """
        # Find similar historical events
        similar_events = await self.find_similar_events(event, top_k=3)

        # Construct prompt for GPT-4
        prompt = self._build_impact_analysis_prompt(
            event, market_question, current_price, similar_events
        )

        try:
            response = await self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert prediction market analyst. "
                            "Analyze news events and predict their impact on market prices. "
                            "Be conservative and data-driven. Return JSON only."
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.5
            )

            result = json.loads(response.choices[0].message.content)

            # Parse response
            suggested_price = Decimal(str(result['suggested_price']))
            confidence = result['confidence']
            reasoning = result['reasoning']
            trade_rec = result['trade_recommendation']

            # Calculate expected value
            edge = abs(suggested_price - current_price)
            expected_value = edge * Decimal(str(confidence))

            impact = MarketImpact(
                market_id=market_id,
                current_price=current_price,
                suggested_price=suggested_price,
                confidence=confidence,
                reasoning=reasoning,
                similar_events=similar_events,
                trade_recommendation=trade_rec,
                expected_value=expected_value
            )

            logger.info(f"\n{'='*60}")
            logger.info(f"📊 MARKET IMPACT ANALYSIS")
            logger.info(f"{'='*60}")
            logger.info(f"Market: {market_question[:50]}...")
            logger.info(f"Event: {event.title[:50]}...")
            logger.info(f"Current Price: {current_price:.3f}")
            logger.info(f"Suggested Price: {suggested_price:.3f}")
            logger.info(f"Confidence: {confidence:.0%}")
            logger.info(f"Trade: {trade_rec.upper()}")
            logger.info(f"Expected Value: {expected_value:.4f}")
            logger.info(f"Reasoning: {reasoning[:100]}...")
            logger.info(f"{'='*60}\n")

            # Store analysis in Supabase
            await self._store_market_analysis(event, impact, market_question)

            return impact

        except Exception as e:
            logger.error(f"Failed to analyze market impact: {e}")
            # Return neutral impact on error
            return MarketImpact(
                market_id=market_id,
                current_price=current_price,
                suggested_price=current_price,
                confidence=0.0,
                reasoning=f"Analysis failed: {str(e)}",
                similar_events=[],
                trade_recommendation="hold",
                expected_value=Decimal("0")
            )

    def _build_impact_analysis_prompt(
        self,
        event: NewsEvent,
        market_question: str,
        current_price: Decimal,
        similar_events: List[Dict]
    ) -> str:
        """Build prompt for GPT-4 market impact analysis"""
        similar_context = ""
        if similar_events:
            similar_context = "\n\nHistorically similar events:\n"
            for sim in similar_events:
                similar_context += f"- {sim['title']} (similarity: {sim['similarity']:.0%})\n"

        prompt = f"""
Analyze the impact of this news event on the prediction market.

**Market Question:** {market_question}
**Current Price:** {current_price:.3f} (implied probability: {float(current_price)*100:.1f}%)

**News Event:**
Title: {event.title}
Content: {event.content}
Source: {event.source}
Published: {event.published_at.isoformat()}
{similar_context}

Provide analysis in this JSON format:
{{
    "suggested_price": 0.XX (new probability between 0.0 and 1.0),
    "confidence": 0.XX (your confidence in this assessment, 0.0 to 1.0),
    "reasoning": "Brief explanation of why this news impacts the market",
    "trade_recommendation": "buy" or "sell" or "hold"
}}

Rules:
- Be conservative (don't move price more than 0.10 unless news is very significant)
- Higher confidence for direct evidence, lower for speculation
- Consider base rates and historical patterns
- If news is unrelated, return current price with confidence 0.0
"""
        return prompt

    async def _store_market_analysis(
        self,
        event: NewsEvent,
        impact: MarketImpact,
        market_question: str
    ):
        """Store market impact analysis in Supabase"""
        try:
            self.supabase.table('market_analyses').insert({
                'event_id': event.event_id,
                'market_id': impact.market_id,
                'market_question': market_question,
                'current_price': float(impact.current_price),
                'suggested_price': float(impact.suggested_price),
                'confidence': impact.confidence,
                'reasoning': impact.reasoning,
                'trade_recommendation': impact.trade_recommendation,
                'expected_value': float(impact.expected_value),
                'analyzed_at': datetime.now().isoformat()
            }).execute()
        except Exception as e:
            logger.error(f"Failed to store market analysis: {e}")

    async def process_news_pipeline(
        self,
        sources: Dict[str, List[str]],
        news_api_key: Optional[str] = None
    ) -> List[NewsEvent]:
        """
        Run complete news ingestion pipeline.

        Args:
            sources: Dict of {category: [feed_urls or queries]}
            news_api_key: NewsAPI key (optional)

        Returns:
            List of processed NewsEvent objects
        """
        all_events = []

        for category, feeds in sources.items():
            for feed in feeds:
                # Determine if RSS or NewsAPI query
                if feed.startswith('http'):
                    # RSS feed
                    events = await self.fetch_news_rss(feed, category)
                elif news_api_key:
                    # NewsAPI query
                    events = await self.fetch_news_api(
                        feed, news_api_key, category
                    )
                else:
                    continue

                # Extract entities
                for event in events:
                    event.entities = await self.extract_entities(event)

                # Store in database
                for event in events:
                    await self.store_news_event(event)

                all_events.extend(events)

        logger.info(f"✅ Processed {len(all_events)} news events")
        return all_events


# Singleton instance
_rag_system_instance = None


async def get_rag_system(
    openai_api_key: str,
    supabase_url: str,
    supabase_key: str
) -> RAGSystem:
    """Get or create global RAG system instance"""
    global _rag_system_instance

    if _rag_system_instance is None:
        _rag_system_instance = RAGSystem(
            openai_api_key=openai_api_key,
            supabase_url=supabase_url,
            supabase_key=supabase_key
        )

    return _rag_system_instance
