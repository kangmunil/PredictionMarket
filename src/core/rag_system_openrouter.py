"""
RAG System with OpenRouter Integration
=======================================

Multi-model RAG system using OpenRouter for cost optimization.

Supported Models:
- Entity Extraction: Claude 3 Haiku (빠르고 저렴)
- Market Analysis: Claude 3.5 Sonnet (강력한 추론)
- Embeddings: OpenAI text-embedding-3-small

OpenRouter Benefits:
- 여러 AI 모델 통합 (Claude, GPT-4, Gemini, Llama 등)
- 비용 최적화 (모델별 가격 비교)
- Fallback 지원 (모델 장애 시 자동 전환)
- 사용량 추적

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
import os
import re

# Vector store (Optional - gracefully handle if unavailable)
CHROMADB_AVAILABLE = False
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    chromadb = None
    Settings = None
    logging.warning("ChromaDB not available - vector similarity search will be disabled")

# LLM (OpenRouter compatible)
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
    event_id: str
    title: str
    content: str
    source: str
    published_at: datetime
    entities: List[str]
    category: str
    url: Optional[str] = None
    sentiment: Optional[float] = None

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
    market_id: str
    current_price: Decimal
    suggested_price: Decimal
    confidence: float
    reasoning: str
    similar_events: List[Dict]
    trade_recommendation: str
    expected_value: Decimal
    model_used: str  # Which AI model was used

    def to_dict(self):
        return {
            'market_id': self.market_id,
            'current_price': float(self.current_price),
            'suggested_price': float(self.suggested_price),
            'confidence': self.confidence,
            'reasoning': self.reasoning,
            'similar_events': self.similar_events,
            'trade_recommendation': self.trade_recommendation,
            'expected_value': float(self.expected_value),
            'model_used': self.model_used
        }


class OpenRouterRAGSystem:
    """
    RAG System with OpenRouter multi-model support.

    Model Strategy:
    - Entity Extraction: Fast, cheap model (Claude 3 Haiku)
    - Market Analysis: Powerful reasoning (Claude 3.5 Sonnet)
    - Embeddings: OpenAI (best quality/price ratio)
    """

    def __init__(
        self,
        openrouter_api_key: str,
        supabase_url: str,
        supabase_key: str,
        chroma_path: str = "./data/chromadb",
        openai_api_key: Optional[str] = None  # For embeddings
    ):
        # OpenRouter client (for Claude, GPT-4, etc.)
        self.openrouter_client = AsyncOpenAI(
            api_key=openrouter_api_key,
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        )

        # OpenAI client (for embeddings only)
        self.openai_client = None
        if openai_api_key:
            self.openai_client = AsyncOpenAI(api_key=openai_api_key)

        # Model selection from environment
        self.entity_model = os.getenv("AI_MODEL_ENTITY", "anthropic/claude-3-haiku")
        self.analysis_model = os.getenv("AI_MODEL_ANALYSIS", "anthropic/claude-3.5-sonnet")
        self.embedding_model = os.getenv("AI_MODEL_EMBEDDING", "openai/text-embedding-3-small")

        # Supabase client
        self.supabase: Client = create_client(supabase_url, supabase_key)

        # ChromaDB (Optional - gracefully handle if unavailable)
        self.chroma_available = False
        self.chroma_client = None
        self.news_collection = None

        if CHROMADB_AVAILABLE:
            try:
                # New ChromaDB 0.4+ client initialization
                # Disable telemetry to avoid background thread exceptions
                from chromadb.config import Settings
                self.chroma_client = chromadb.PersistentClient(
                    path=chroma_path,
                    settings=Settings(anonymized_telemetry=False)
                )
                
                self.news_collection = self.chroma_client.get_or_create_collection(
                    name="news_events",
                    metadata={"description": "Historical news events with embeddings"}
                )
                self.chroma_available = True
                logger.info("✅ ChromaDB initialized (Persistent)")
                logger.info(f"   News events indexed: {self.news_collection.count()}")
            except Exception as e:
                logger.warning(f"⚠️  ChromaDB initialization failed: {e}")
                logger.warning(f"   RAG will work without historical pattern matching")
        else:
            logger.warning("⚠️  ChromaDB not available (import failed)")
            logger.warning("   RAG will work without vector similarity search")

        logger.info("✅ OpenRouter RAG System initialized")
        logger.info(f"   Entity Model: {self.entity_model}")
        logger.info(f"   Analysis Model: {self.analysis_model}")
        logger.info(f"   Embedding Model: {self.embedding_model}")

    async def fetch_news_rss(self, feed_url: str, category: str) -> List[NewsEvent]:
        """Fetch news from RSS feed (same as original)"""
        try:
            feed = feedparser.parse(feed_url)
            events = []

            for entry in feed.entries[:20]:
                event_id = hashlib.md5(
                    (entry.title + entry.link).encode()
                ).hexdigest()

                try:
                    published_at = datetime(*entry.published_parsed[:6])
                except:
                    published_at = datetime.now()

                content = entry.get('summary', entry.get('description', ''))

                event = NewsEvent(
                    event_id=event_id,
                    title=entry.title,
                    content=content,
                    source=feed.feed.get('title', 'RSS Feed'),
                    published_at=published_at,
                    entities=[],
                    category=category,
                    url=entry.link
                )

                events.append(event)

            logger.info(f"📰 Fetched {len(events)} events from {feed_url}")
            return events

        except Exception as e:
            logger.error(f"Failed to fetch RSS feed: {e}")
            return []

    async def fetch_news_api(
        self,
        query: str,
        api_key: str,
        category: str,
        lookback_hours: int = 24
    ) -> List[NewsEvent]:
        """Fetch news from NewsAPI (same as original)"""
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

                    logger.info(f"📰 Fetched {len(events)} events from NewsAPI")
                    return events

        except Exception as e:
            logger.error(f"Failed to fetch from NewsAPI: {e}")
            return []

    async def extract_entities(self, event: NewsEvent) -> List[str]:
        """
        Extract entities using OpenRouter (Claude 3 Haiku for speed/cost).

        Uses fast, cheap model for simple extraction task.
        """
        try:
            response = await self.openrouter_client.chat.completions.create(
                model=self.entity_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Extract named entities (people, companies, locations, events) "
                            "from news. Return only a JSON array of strings."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"Title: {event.title}\n\nContent: {event.content}"
                    }
                ],
                temperature=0.3,
                max_tokens=500
            )

            content = response.choices[0].message.content

            # Clean markdown code blocks if present
            if "```" in content:
                # Remove ```json and ``` or just ```
                content = content.replace("```json", "").replace("```", "").strip()

            # Try to parse as JSON
            try:
                result = json.loads(content)
                if isinstance(result, dict):
                    entities = result.get('entities', [])
                elif isinstance(result, list):
                    entities = result
                else:
                    entities = []
            except:
                # Fallback: extract from text
                entities = content.strip('[]').replace('"', '').split(',')
                entities = [e.strip() for e in entities if e.strip()]

            logger.debug(f"Extracted {len(entities)} entities using {self.entity_model}")
            return entities[:10]  # Limit to 10 entities

        except Exception as e:
            logger.error(f"Failed to extract entities: {e}")
            return []

    async def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embeddings using OpenAI (best quality).

        Falls back to OpenRouter if OpenAI not available.
        """
        try:
            # Try OpenAI first (better embeddings)
            if self.openai_client:
                response = await self.openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=text
                )
                return response.data[0].embedding

            # Fallback to OpenRouter
            response = await self.openrouter_client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            return response.data[0].embedding

        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            # Return zero vector on failure
            return [0.0] * 1536

    async def store_news_event(self, event: NewsEvent):
        """Store news event in ChromaDB and Supabase"""
        try:
            # Store in ChromaDB (if available)
            if self.chroma_available:
                embedding = await self.generate_embedding(
                    f"{event.title}\n\n{event.content}"
                )

                self.news_collection.add(
                    embeddings=[embedding],
                    documents=[f"{event.title}\n\n{event.content}"],
                    metadatas=[
                        {
                            'event_id': event.event_id,
                            'title': event.title,
                            'source': event.source,
                            'category': event.category,
                            'published_at': event.published_at.isoformat(),
                            'entities': json.dumps(event.entities)
                        }
                    ],
                    ids=[event.event_id]
                )

            # Store in Supabase (always)
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
            logger.error(f"Failed to store event: {e}")

    async def find_similar_events(
        self,
        event: NewsEvent,
        top_k: int = 5
    ) -> List[Dict]:
        """Find similar historical events using vector similarity"""
        # Skip if ChromaDB not available
        if not self.chroma_available:
            logger.debug("ChromaDB not available, skipping similarity search")
            return []

        try:
            query_embedding = await self.generate_embedding(
                f"{event.title}\n\n{event.content}"
            )

            results = self.news_collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={"category": event.category}
            )

            similar_events = []
            if results['ids']:
                for i, event_id in enumerate(results['ids'][0]):
                    similar_events.append({
                        'event_id': event_id,
                        'title': results['metadatas'][0][i]['title'],
                        'similarity': 1 - results['distances'][0][i],
                        'published_at': results['metadatas'][0][i]['published_at']
                    })

            return similar_events

        except Exception as e:
            logger.error(f"Failed to find similar events: {e}")
            return []

    def _build_impact_analysis_prompt(
        self,
        event: NewsEvent,
        market_question: str,
        current_price: Decimal,
        similar_events: List[Dict]
    ) -> str:
        """Build analysis prompt (Optimized for decisiveness)"""
        similar_context = ""
        if similar_events:
            similar_context = "\n\nHistorically similar events:\n"
            for sim in similar_events:
                similar_context += f"- {sim['title']} (similarity: {sim['similarity']:.0%})\n"

        return f"""
Analyze this news impact on the prediction market.

**Market Question:** {market_question}
**Current Price:** {current_price:.3f} (probability: {float(current_price)*100:.1f}%)

**News Event:**
Title: {event.title}
Content: {event.content}
Source: {event.source}
Published: {event.published_at.isoformat()}
{similar_context}

Return JSON ONLY:
{{
    "suggested_price": 0.XX (new probability 0.0-1.0),
    "confidence": 0.XX (confidence 0.0-1.0),
    "reasoning": "Brief explanation",
    "trade_recommendation": "buy" | "sell" | "hold"
}}

Rules:
- Be calibrated. If news directly affects the outcome, reflect the probability shift accurately.
- Do not default to HOLD if there is actionable information.
- If the news is irrelevant to the market, set confidence to 0.0.
- If the news confirms the current trend, suggest a price movement in that direction.
"""

    async def analyze_market_impact(
        self,
        event: NewsEvent,
        market_id: str,
        current_price: Decimal,
        market_question: str
    ) -> MarketImpact:
        """
        Analyze market impact using 2-stage pipeline for cost optimization.
        """
        # Ensure event is stored in DB first
        await self.store_news_event(event)

        if not event.entities:
            logger.debug(f"💰 Extracting entities with cheap model: {self.entity_model}")
            event.entities = await self.extract_entities(event)

        similar_events = await self.find_similar_events(event, top_k=3)
        prompt = self._build_impact_analysis_prompt(
            event, market_question, current_price, similar_events
        )

        try:
            logger.info(f"🎯 Running market analysis with premium model: {self.analysis_model}")

            response = await self.openrouter_client.chat.completions.create(
                model=self.analysis_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert prediction market analyst. Return JSON only."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3, # Lower temperature for more consistent JSON
                max_tokens=1000
            )

            content = response.choices[0].message.content.strip()

            # Robust JSON Parsing
            try:
                # 1. Try direct parse
                result = json.loads(content)
            except json.JSONDecodeError:
                # 2. Try regex extraction
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
                else:
                    raise ValueError(f"Could not parse JSON from: {content[:100]}...")

            suggested_price = Decimal(str(result.get('suggested_price', current_price)))
            confidence = float(result.get('confidence', 0.0))
            reasoning = result.get('reasoning', "No reasoning provided")
            trade_rec = result.get('trade_recommendation', 'hold').lower()

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
                expected_value=expected_value,
                model_used=self.analysis_model
            )

            logger.info(f"\n{'='*60}")
            logger.info(f"📊 MARKET IMPACT ANALYSIS ({self.analysis_model})")
            logger.info(f"{ '='*60}")
            logger.info(f"Market: {market_question[:50]}...")
            logger.info(f"Event: {event.title[:50]}...")
            logger.info(f"Current: {current_price:.3f} → Suggested: {suggested_price:.3f}")
            logger.info(f"Confidence: {confidence:.0%} | Trade: {trade_rec.upper()}")
            logger.info(f"EV: {expected_value:.4f}")
            logger.info(f"{ '='*60}\n")

            await self._store_market_analysis(event, impact, market_question)

            return impact

        except Exception as e:
            logger.error(f"Failed to analyze market impact: {e}")
            return MarketImpact(
                market_id=market_id,
                current_price=current_price,
                suggested_price=current_price,
                confidence=0.0,
                reasoning=f"Analysis failed: {str(e)}",
                similar_events=[],
                trade_recommendation="hold",
                expected_value=Decimal("0"),
                model_used="error"
            )

    async def _store_market_analysis(
        self,
        event: NewsEvent,
        impact: MarketImpact,
        market_question: str
    ):
        """Store analysis in Supabase"""
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
                'analyzed_at': datetime.now().isoformat(),
                'model_used': impact.model_used
            }).execute()
        except Exception as e:
            logger.error(f"Failed to store analysis: {e}")

    async def process_news_pipeline(
        self,
        sources: Dict[str, List[str]],
        news_api_key: Optional[str] = None
    ) -> List[NewsEvent]:
        """Run complete news ingestion pipeline"""
        all_events = []

        for category, feeds in sources.items():
            for feed in feeds:
                if feed.startswith('http'):
                    events = await self.fetch_news_rss(feed, category)
                elif news_api_key:
                    events = await self.fetch_news_api(feed, news_api_key, category)
                else:
                    continue

                for event in events:
                    event.entities = await self.extract_entities(event)

                for event in events:
                    await self.store_news_event(event)

                all_events.extend(events)

        logger.info(f"✅ Processed {len(all_events)} news events")
        return all_events


# Singleton
_openrouter_rag_instance = None


async def get_openrouter_rag(
    openrouter_api_key: str,
    supabase_url: str,
    supabase_key: str,
    openai_api_key: Optional[str] = None
) -> OpenRouterRAGSystem:
    """Get or create OpenRouter RAG instance"""
    global _openrouter_rag_instance

    if _openrouter_rag_instance is None:
        _openrouter_rag_instance = OpenRouterRAGSystem(
            openrouter_api_key=openrouter_api_key,
            supabase_url=supabase_url,
            supabase_key=supabase_key,
            openai_api_key=openai_api_key
        )

    return _openrouter_rag_instance