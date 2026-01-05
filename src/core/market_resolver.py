import logging
from typing import List, Dict, Optional
from src.core.history_fetcher import get_history_fetcher

logger = logging.getLogger(__name__)

class MarketResolver:
    """
    Automatically resolves search queries into valid Polymarket Condition IDs.
    Filters by volume and active status to ensure liquidity.
    """
    def __init__(self):
        self.fetcher = get_history_fetcher()

    async def resolve_pair(self, query_a: str, query_b: str) -> Optional[Dict]:
        """
        Finds two related markets.
        Example: resolve_pair("Bitcoin", "Ethereum")
        """
        logger.info(f"🔍 Resolving dynamic pair: {query_a} vs {query_b}")
        
        market_a = await self._search_best_market(query_a)
        market_b = await self._search_best_market(query_b)
        
        if market_a and market_b:
            return {
                "id_a": market_a['condition_id'],
                "id_b": market_b['condition_id'],
                "title_a": market_a['question'],
                "title_b": market_b['question']
            }
        return None

    async def _search_best_market(self, query: str) -> Optional[Dict]:
        """Search for top volume active market for a query"""
        results = await self.fetcher.search_markets(query, limit=10, active_only=True)
        
        if not results:
            return None
            
        # Filter for quality: Must have a condition_id and decent volume
        # We also want to avoid 'Group' markets for Stat Arb usually, unless calibrated
        valid_results = [
            m for m in results 
            if m.get('condition_id') and float(m.get('volume', 0)) > 1000
        ]
        
        if not valid_results:
            return None
            
        # Return the one with highest liquidity/volume
        best = max(valid_results, key=lambda x: float(x.get('volume', 0)))
        logger.info(f"   🎯 TARGET MATCH: {best['question']} (ID: {best['condition_id'][:10]}...)")
        return best

# Singleton
_resolver_instance = None
def get_market_resolver():
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = MarketResolver()
    return _resolver_instance
