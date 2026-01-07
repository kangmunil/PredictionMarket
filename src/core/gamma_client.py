import aiohttp
import logging
import os
from typing import List, Optional

from .polymarket_mcp_client import get_default_mcp_client, PolymarketMCPClient
from .market_registry import market_registry

logger = logging.getLogger(__name__)

class GammaClient:
    """
    Client for Polymarket's Gamma API (Query Layer).
    Used to efficiently filter markets by volume, category, etc.
    Endpoint: https://gamma-api.polymarket.com
    """
    BASE_URL = "https://gamma-api.polymarket.com"

    def __init__(self, use_mcp: Optional[bool] = None):
        # Auto-enable MCP if URL configured
        if use_mcp is None:
            use_mcp = bool(os.getenv("POLYMARKET_MCP_URL"))
        self._mcp_enabled = use_mcp
        self._mcp_client: Optional[PolymarketMCPClient] = None

    async def get_active_markets(self, limit=50, volume_min=1000):
        """
        Fetch active markets with significant volume.
        Query: Active, sorted by volume desc.
        """
        if await self._maybe_init_mcp():
            return await self._get_active_markets_via_mcp(limit, volume_min)

        url = f"{self.BASE_URL}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "order": "volume",
            "ascending": "false",
            "limit": limit,
            "offset": 0
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for market in data:
                            market_registry.register_market(market)
                        # Filter by volume threshold locally if API doesn't support range
                        markets = [m for m in data if float(m.get('volume', 0)) >= volume_min]
                        return markets
                    else:
                        logger.error(f"Gamma API Error: {resp.status}")
                        return []
            except Exception as e:
                logger.error(f"Gamma Fetch Error: {e}")
                return []

    async def search_markets(self, query: str, limit: int = 10) -> list:
        """
        Search for markets by keyword.
        """
        if await self._maybe_init_mcp():
            return await self._search_markets_via_mcp(query, limit)

        url = f"{self.BASE_URL}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "query": query
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for market in data:
                            market_registry.register_market(market)
                        # Only return markets that are tradeable on CLOB
                        return [m for m in data if m.get('enableOrderBook')]
                    return []
            except Exception as e:
                logger.error(f"Gamma Search Error: {e}")
                return []

    async def _maybe_init_mcp(self) -> bool:
        if not self._mcp_enabled:
            return False
        if self._mcp_client:
            return True
        try:
            self._mcp_client = await get_default_mcp_client()
        except Exception as exc:
            logger.error("Failed to init Polymarket MCP client: %s", exc)
            self._mcp_enabled = False
            return False
        if not self._mcp_client:
            self._mcp_enabled = False
            return False
        return True

    async def _get_active_markets_via_mcp(self, limit: int, volume_min: float) -> List[dict]:
        assert self._mcp_client
        try:
            result = await self._mcp_client.search_markets(
                limit=limit,
                order="volume",
                ascending=False,
                closed=False,
                volume_min=volume_min,
            )
            if isinstance(result, dict):
                result = result.get("markets", [])
            for market in result or []:
                market_registry.register_market(market)
            return result or []
        except Exception as exc:
            logger.error("MCP active market fetch failed, falling back: %s", exc)
            self._mcp_enabled = False
            return await self.get_active_markets(limit, volume_min)

    async def _search_markets_via_mcp(self, query: str, limit: int) -> List[dict]:
        assert self._mcp_client
        try:
            result = await self._mcp_client.search_markets(
                query=query,
                limit=limit,
                closed=False,
            )
            if isinstance(result, dict):
                result = result.get("markets", [])
            filtered = [m for m in (result or []) if m.get("enableOrderBook")]
            for market in filtered:
                market_registry.register_market(market)
            return filtered
        except Exception as exc:
            logger.error("MCP market search failed, falling back: %s", exc)
            self._mcp_enabled = False
            return await self.search_markets(query, limit)
