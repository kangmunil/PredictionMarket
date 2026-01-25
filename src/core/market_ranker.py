import logging
import asyncio
import time
from typing import List, Dict, Optional
from decimal import Decimal

logger = logging.getLogger(__name__)

class MarketRanker:
    """
    Alpha Heatmap Engine (Phase 7)
    Ranks Polymarket venues by 'Opportunity Score' to focus agent resources.
    
    Formula: Score = (24h_Volume * Spread_BPS) / Liquidity_Resistance
    """
    
    def __init__(self, gamma_client, signal_bus, limit: int = 50):
        self.gamma_client = gamma_client
        self.signal_bus = signal_bus
        self.limit = limit
        self.top_markets: List[Dict] = []
        self.last_update = 0
        self.is_running = False

    async def run_periodic_ranking(self, interval: int = 300):
        """Background loop to refresh the heatmap every 5 minutes."""
        self.is_running = True
        logger.info(f"🔥 Alpha Heatmap Ranker started (Interval: {interval}s)")
        
        while self.is_running:
            try:
                await self.update_ranks()
                logger.info(f"📊 Heatmap Updated: {len(self.top_markets)} 'Hot Zones' identified.")
            except Exception as e:
                logger.error(f"Heatmap update failed: {e}")
            
            await asyncio.sleep(interval)

    async def update_ranks(self):
        """
        Fetches active NegRisk markets and ranks them by opportunity score.
        """
        # 1. Fetch High Volume NegRisk Markets
        markets = await self.gamma_client.get_active_markets(
            limit=200, 
            neg_risk=True,
            volume_min=500 # Focus where there is at least some activity
        )
        
        scored_markets = []
        
        for m in markets:
            market_id = m.get("id")
            volume = float(m.get("volume24hr", m.get("volume", 0)))
            
            # Extract CLOB IDs
            clob_ids = self._extract_clob_ids(m)
            if not clob_ids:
                continue

            # 2. Get Real-time Inefficiency (Spread) from SignalBus
            total_spread_bps = 0.0
            active_signals = 0
            
            for tid in clob_ids:
                sig = await self.signal_bus.get_signal(tid)
                if sig and sig.spread_bps > 0:
                    total_spread_bps += sig.spread_bps
                    active_signals += 1
            
            # If no real-time signal yet, use a neutral default for ranking
            avg_spread = (total_spread_bps / active_signals) if active_signals > 0 else 50.0 # 50bps default
            
            # 3. Calculate Opportunity Score
            # Higher score = More volume hitting wider spreads (Alpha potential)
            # We add a small constant to volume to avoid zero-multiplication
            opportunity_score = (volume + 100) * (avg_spread / 100.0)
            
            scored_markets.append({
                "id": market_id,
                "question": m.get("question", "Unknown"),
                "clob_ids": clob_ids,
                "score": opportunity_score,
                "volume": volume,
                "spread_bps": avg_spread
            })

        # 4. Sort by Score DESC and truncate to limit
        scored_markets.sort(key=lambda x: x["score"], reverse=True)
        self.top_markets = scored_markets[:self.limit]
        self.last_update = time.time()
        
        return self.top_markets

    def get_top_token_ids(self) -> List[str]:
        """Returns a flattened list of all token IDs in the top ranked markets."""
        token_list = []
        for m in self.top_markets:
            token_list.extend(m.get("clob_ids", []))
        return list(set(token_list)) # Unique IDs only

    def _extract_clob_ids(self, market: Dict) -> List[str]:
        """Extracts token IDs from various Gamma response formats."""
        if 'clobTokenIds' in market:
            import json
            ids = market['clobTokenIds']
            return json.loads(ids) if isinstance(ids, str) else ids
        
        tokens = market.get('tokens', [])
        if tokens:
            return [t['token_id'] for t in tokens if 'token_id' in t]
            
        return []

    def stop(self):
        self.is_running = False
