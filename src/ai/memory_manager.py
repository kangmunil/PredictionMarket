import os
import logging
from typing import List, Dict, Optional
from supabase import create_client, Client
from openai import OpenAI

logger = logging.getLogger(__name__)

class MarketMemory:
    """
    Manages long-term memory for the AI Agent using Supabase (pgvector).
    Stores past news events and their market impacts to inform future decisions.
    """
    
    def __init__(self):
        # Load credentials
        self.supabase_url = os.getenv("SUPABASE_URL")
        self.supabase_key = os.getenv("SUPABASE_KEY")
        self.openai_key = os.getenv("OPENAI_API_KEY")
        
        if not all([self.supabase_url, self.supabase_key, self.openai_key]):
            logger.warning("⚠️ AI Memory disabled: Missing Supabase/OpenAI keys in .env")
            self.enabled = False
            return

        try:
            self.supabase: Client = create_client(self.supabase_url, self.supabase_key)
            self.openai = OpenAI(api_key=self.openai_key)
            self.enabled = True
            logger.info("🧠 AI Memory System Connected")
        except Exception as e:
            logger.error(f"❌ Failed to connect AI Memory: {e}")
            self.enabled = False

    def get_embedding(self, text: str) -> List[float]:
        """Convert text to vector using OpenAI"""
        if not self.enabled: return []
        
        try:
            text = text.replace("\n", " ")
            response = self.openai.embeddings.create(
                input=[text],
                model="text-embedding-3-small"
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return []

    def add_experience(self, entity: str, content: str, reasoning: str, impact: Dict, pnl_usd: float):
        """
        Store a self-learned experience (Closed-loop learning).
        Includes the original reasoning and the actual financial outcome.
        """
        if not self.enabled: return

        try:
            # Create a rich text for embedding that includes the outcome
            sentiment = "SUCCESSFUL" if pnl_usd > 0 else "FAILED"
            experience_text = f"[{entity}] Event: {content}. My Reasoning: {reasoning}. Result: {sentiment} with ${pnl_usd:.2f} PnL."
            
            vector = self.get_embedding(experience_text)
            
            data = {
                "category": "Experience",
                "entity": entity,
                "content": content,
                "embedding": vector,
                "market_impact": {
                    "original_reasoning": reasoning,
                    "actual_pnl": pnl_usd,
                    "initial_impact": impact
                },
                "source_url": "Self-Learning Loop"
            }
            
            self.supabase.table("market_memories").insert(data).execute()
            logger.info(f"🧠 Self-Learning: Experience saved for {entity} (${pnl_usd:+.2f} PnL)")
        except Exception as e:
            logger.error(f"Failed to save experience: {e}")

    def find_similar_events(self, entity: str, query: str, limit: int = 3) -> List[Dict]:
        """Find similar past events using RAG (Vector Search)"""
        if not self.enabled: return []

        try:
            query_vector = self.get_embedding(f"[{entity}] {query}")
            
            # Call Supabase RPC function
            response = self.supabase.rpc(
                "match_memories",
                {
                    "query_embedding": query_vector,
                    "match_threshold": 0.5, # Minimum similarity
                    "match_count": limit,
                    "filter_entity": entity
                }
            ).execute()
            
            return response.data
        except Exception as e:
            logger.error(f"RAG Search failed: {e}")
            return []