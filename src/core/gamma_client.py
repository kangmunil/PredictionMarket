import aiohttp
import logging
import os
import time
from datetime import datetime, timedelta
from typing import List, Optional
from src.core.health_monitor import PROM_API_REQUESTS, PROM_API_ERRORS, PROM_LATENCY

from .polymarket_mcp_client import get_default_mcp_client, PolymarketMCPClient
from .market_registry import market_registry

from .config import Config

logger = logging.getLogger(__name__)

class GammaClient:
    """
    Client for Polymarket's Gamma API (Query Layer).
    Used to efficiently filter markets by volume, category, etc.
    Endpoint: https://gamma-api.polymarket.com
    """
    BASE_URL = "https://gamma-api.polymarket.com"

    def __init__(self, use_mcp: Optional[bool] = None, config: Optional[Config] = None):
        self.config = config or Config()
        # Auto-enable MCP if URL configured
        if use_mcp is None:
            use_mcp = bool(os.getenv("POLYMARKET_MCP_URL"))
        self._mcp_enabled = use_mcp
        self._mcp_client: Optional[PolymarketMCPClient] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_active_markets(self, limit=None, volume_min=1000, max_hours_to_close: Optional[int] = None, order: str = "volume"):
        """
        Fetch active markets with significant volume.
        Query: Active, sorted by volume desc.
        """
        if limit is None:
            limit = self.config.GLOBAL_MONITOR_LIMIT
            
        PROM_API_REQUESTS.labels(service="gamma").inc()
        start_time = time.time()
        
        all_markets = []
        current_offset = 0
        max_batch_size = self.config.DISCOVERY_BATCH_SIZE
        
        # 1. Try MCP first (Higher speed)
        if await self._maybe_init_mcp():
            res = await self._get_active_markets_via_mcp(limit, volume_min, max_hours_to_close)
            all_markets = res
        else:
            # 2. Fallback to Paginated Gamma API
            session = await self._ensure_session()
            while len(all_markets) < limit:
                batch_limit = min(max_batch_size, limit - len(all_markets))
                url = f"{self.BASE_URL}/markets"
                params = {
                    "active": "true",
                    "closed": "false",
                    "order": order,
                    "ascending": "false",
                    "limit": batch_limit,
                    "offset": current_offset
                }
                
                try:
                    async with session.get(url, params=params) as resp:
                        PROM_LATENCY.labels(service="gamma").observe(time.time() - start_time)
                        if resp.status == 200:
                            data = await resp.json()
                            if not data:
                                break # No more markets
                                
                            for market in data:
                                market_registry.register_market(market)
                                
                            # Filter and add
                            filtered = [m for m in data if float(m.get('volume', 0)) >= volume_min]
                            if max_hours_to_close:
                                filtered = [m for m in filtered if self._within_hours(m, max_hours_to_close)]
                            
                            all_markets.extend(filtered)
                            current_offset += len(data) # Move offset by actual results received
                            
                            if len(data) < batch_limit:
                                break # End of results
                        else:
                            PROM_API_ERRORS.labels(service="gamma", error_type=str(resp.status)).inc()
                            logger.error(f"Gamma API Error: {resp.status}")
                            break
                except Exception as e:
                    PROM_API_ERRORS.labels(service="gamma", error_type="exception").inc()
                    logger.error(f"Gamma Fetch Error: {e}")
                    break
        
        return all_markets[:limit]

    async def search_markets(self, query: str, limit: int = 10) -> list:
        """
        Search for markets by keyword.
        """
        PROM_API_REQUESTS.labels(service="gamma_search").inc()
        start_time = time.time()

        if await self._maybe_init_mcp():
            res = await self._search_markets_via_mcp(query, limit)
            PROM_LATENCY.labels(service="gamma_search_mcp").observe(time.time() - start_time)
            return res

        url = f"{self.BASE_URL}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "query": query
        }

        session = await self._ensure_session()
        try:
            async with session.get(url, params=params) as resp:
                PROM_LATENCY.labels(service="gamma_search").observe(time.time() - start_time)
                if resp.status == 200:
                    data = await resp.json()
                    for market in data:
                        market_registry.register_market(market)
                    # Only return markets that are tradeable on CLOB
                    return [m for m in data if m.get('enableOrderBook')]
                return []
        except Exception as e:
            PROM_API_ERRORS.labels(service="gamma_search", error_type="exception").inc()
            logger.error(f"Gamma Search Error: {e}")
            return []

    async def get_market(self, condition_id: str) -> Optional[dict]:
        """Fetch a single market by condition ID."""
        PROM_API_REQUESTS.labels(service="gamma_get_market").inc()
        url = f"{self.BASE_URL}/markets"
        params = {"condition_id": condition_id}
        
        session = await self._ensure_session()
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list) and len(data) > 0:
                        market = data[0]
                        market_registry.register_market(market)
                        return market
                return None
        except Exception as e:
            logger.error(f"Gamma GetMarket Error: {e}")
            return None

    async def get_price_markets_by_tag(self, tag_id: int, limit: int = 50) -> List[dict]:
        """
        Fetch markets by tag ID.
        """
        PROM_API_REQUESTS.labels(service="gamma_tag").inc()
        start_time = time.time()
        
        # We don't have an MCP specialized for tags yet, use direct API
        url = f"{self.BASE_URL}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "limit": limit,
            "tag_id": tag_id,
        }

        session = await self._ensure_session()
        try:
            async with session.get(url, params=params) as resp:
                PROM_LATENCY.labels(service="gamma_tag").observe(time.time() - start_time)
                if resp.status == 200:
                    data = await resp.json()
                    for market in data:
                        market_registry.register_market(market)
                    return data
                return []
        except Exception as e:
            PROM_API_ERRORS.labels(service="gamma_tag", error_type="exception").inc()
            logger.error(f"Gamma Tag Fetch Error: {e}")
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

    async def _get_active_markets_via_mcp(self, limit: int, volume_min: float, max_hours_to_close: Optional[int]) -> List[dict]:
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
            markets = result or []
            if max_hours_to_close:
                markets = [m for m in markets if self._within_hours(m, max_hours_to_close)]
            return markets
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

    def _within_hours(self, market: dict, max_hours: int) -> bool:
        ends_at = market.get("ends_at")
        if not ends_at:
            return False
        try:
            ts = ends_at.replace("Z", "+00:00") if ends_at.endswith("Z") else ends_at
            end_dt = datetime.fromisoformat(ts)
            now = datetime.now(end_dt.tzinfo) if end_dt.tzinfo else datetime.utcnow()
            return now < end_dt <= now + timedelta(hours=max_hours)
        except Exception:
            return False


    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("✅ GammaClient session closed")
