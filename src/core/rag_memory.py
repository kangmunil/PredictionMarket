import os
import logging
from typing import List, Dict
import chromadb
from chromadb.utils import embedding_functions
from langchain_openai import OpenAIEmbeddings
from datetime import datetime

logger = logging.getLogger(__name__)

class RAGMemory:
    """
    Vector Database for Financial News & Event History.
    Uses ChromaDB for storage and OpenAI for high-quality embeddings.
    """
    def __init__(self, persist_path: str = "./data/rag_db"):
        self.persist_path = persist_path
        
        # 1. Initialize Embedding Model from .env
        embedding_model = os.getenv("AI_MODEL_EMBEDDING", "openai/text-embedding-3-large")
        api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENROUTER_BASE_URL")
        
        self.embedding_func = OpenAIEmbeddings(
            model=embedding_model,
            dimensions=1024,
            openai_api_key=api_key,
            openai_api_base=base_url
        )

        # 2. Initialize Vector DB
        self.client = chromadb.PersistentClient(path=persist_path)
        
        # 3. Create/Get Collection
        self.collection = self.client.get_or_create_collection(
            name="financial_events",
            metadata={"hnsw:space": "cosine"} # Cosine similarity for semantic search
        )
        
        logger.info(f"🧠 RAG Memory initialized at {persist_path}")

    def add_event(self, text: str, metadata: Dict):
        """
        Save an event to memory.
        
        Args:
            text: The news headline or content
            metadata: {
                "date": "2024-05-20",
                "market_impact": "+5% BTC",
                "outcome": "Resolved YES",
                "category": "crypto"
            }
        """
        try:
            # Generate Embedding
            vector = self.embedding_func.embed_query(text)
            
            # Add to DB
            self.collection.add(
                documents=[text],
                embeddings=[vector],
                metadatas=[metadata],
                ids=[f"evt_{datetime.now().timestamp()}"]
            )
            logger.info(f"📥 Saved event: {text[:50]}...")
            
        except Exception as e:
            logger.error(f"❌ Failed to save event: {e}")

    def find_similar_events(self, query: str, n_results: int = 3) -> List[Dict]:
        """
        Find historically similar events.
        """
        try:
            vector = self.embedding_func.embed_query(query)
            
            results = self.collection.query(
                query_embeddings=[vector],
                n_results=n_results
            )
            
            # Parse results
            found_events = []
            if results['documents']:
                for i, doc in enumerate(results['documents'][0]):
                    meta = results['metadatas'][0][i]
                    found_events.append({
                        "content": doc,
                        "metadata": meta,
                        "distance": results['distances'][0][i] if results['distances'] else 0
                    })
            
            return found_events
            
        except Exception as e:
            logger.error(f"❌ Search failed: {e}")
            return []

# Singleton
_rag_instance = None

def get_rag_memory():
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = RAGMemory()
    return _rag_instance
