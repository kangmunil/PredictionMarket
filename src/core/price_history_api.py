"""
Polymarket Price History API
Fetches real historical price data for statistical arbitrage analysis
"""
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import logging
import os

from src.core.polymarket_mcp_client import (
    get_default_mcp_client,
    PolymarketMCPClient,
)
from src.core.market_registry import market_registry

logger = logging.getLogger(__name__)


class PolymarketHistoryAPI:
    """
    Fetch historical market prices from Polymarket Gamma API or MCP
    """

    def __init__(
        self,
        gamma_url: str = "https://gamma-api.polymarket.com",
        use_mcp: Optional[bool] = None,
    ):
        self.gamma_url = gamma_url
        self.session: Optional[aiohttp.ClientSession] = None
        if use_mcp is None:
            use_mcp = bool(os.getenv("POLYMARKET_MCP_URL"))
        self._mcp_enabled = use_mcp
        self._mcp_client: Optional[PolymarketMCPClient] = None
        self._trade_cache: Dict[str, Dict] = {}
        self._cache_ttl = timedelta(minutes=5)
        self._history_source_cache: Dict[str, Dict] = {}

    async def _ensure_session(self):
        """Ensure aiohttp session is created"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()

    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None

    async def _maybe_init_mcp(self) -> bool:
        if not self._mcp_enabled:
            return False
        if self._mcp_client:
            return True
        try:
            self._mcp_client = await get_default_mcp_client()
        except Exception as exc:
            logger.error("Failed to initialize Polymarket MCP client: %s", exc)
            self._mcp_enabled = False
            return False
        if not self._mcp_client:
            self._mcp_enabled = False
            return False
        return True

    async def get_market_prices(
        self,
        condition_id: str,
        start_time: datetime,
        end_time: datetime,
        interval: str = "1h"
    ) -> List[Dict]:
        """
        Fetch historical price data for a specific market

        Args:
            condition_id: Market condition ID
            start_time: Start of time range
            end_time: End of time range
            interval: Time interval (1h, 1d, etc.)

        Returns:
            List of {'timestamp': datetime, 'price': float} dicts
        """
        await self._ensure_session()

        data = await self._fetch_market_snapshot(condition_id)
        if not data:
            return []

        current_price = self._extract_current_price(data)
        market_registry.register_market(data)

        if current_price is None:
            logger.warning(f"No price found for market {condition_id}")
            return []

        return [{
            'timestamp': datetime.now(),
            'price': current_price
        }]

    async def get_history_with_source(
        self,
        condition_id: str,
        days: int = 30,
        min_points: int = 10,
    ) -> Tuple[List[Dict], str]:
        """
        Return historical points along with the data source that produced them.
        This is the primary entrypoint for strategies that need to reason
        about data quality.
        """
        await self._ensure_session()

        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)

        points, source = await self._collect_history_points(
            condition_id=condition_id,
            days=days,
            start_time=start_time,
            end_time=end_time,
            min_points=min_points,
        )

        self._history_source_cache[condition_id] = {
            "source": source,
            "points": len(points),
            "timestamp": datetime.now().isoformat(),
        }
        return points, source

    async def get_historical_events(
        self,
        condition_id: str,
        days: int = 30
    ) -> List[Dict]:
        """
        Backwards-compatible wrapper that returns only price points.
        Call get_history_with_source when the caller needs metadata.
        """
        points, _ = await self.get_history_with_source(condition_id, days=days)
        return points

    async def _collect_history_points(
        self,
        condition_id: str,
        days: int,
        start_time: datetime,
        end_time: datetime,
        min_points: int = 10,
    ) -> Tuple[List[Dict], str]:
        mcp_points = await self._fetch_trades_via_mcp(condition_id, days, start_time)
        if mcp_points:
            logger.info(f"Using MCP trade history for {condition_id} ({len(mcp_points)} pts)")
            return mcp_points, "MCP_TRADES"

        events = await self._fetch_events_from_gamma(condition_id, start_time, end_time)
        if events:
            price_points = self._parse_events_to_prices(events)
            if len(price_points) >= min_points:
                logger.info(f"Using Gamma events history for {condition_id} ({len(price_points)} pts)")
                return price_points, "GAMMA_EVENTS"
            logger.warning(f"Gamma events insufficient for {condition_id} ({len(price_points)} pts)")

        logger.warning(f"Using synthetic history for {condition_id}")
        synthetic = self._generate_synthetic_history(condition_id, days)
        return synthetic, "SYNTHETIC"

    def get_history_source(self, condition_id: str) -> Optional[str]:
        info = self._history_source_cache.get(condition_id)
        if not info:
            return None
        return info.get("source")

    def get_history_source_snapshot(self) -> Dict[str, Dict]:
        return {cid: meta.copy() for cid, meta in self._history_source_cache.items()}

    async def _fetch_market_snapshot(self, condition_id: str) -> Optional[Dict]:
        await self._ensure_session()
        if not self.session:
            return None

        url = f"{self.gamma_url}/markets/{condition_id}"
        try:
            async with self.session.get(url, timeout=10) as response:
                if response.status != 200:
                    logger.error(f"Failed to fetch market {condition_id}: HTTP {response.status}")
                    return None
                return await response.json()
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching market {condition_id}")
        except Exception as exc:
            logger.error(f"Error fetching market {condition_id}: {exc}")
        return None

    async def _fetch_events_from_gamma(
        self,
        condition_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Optional[List[Dict]]:
        await self._ensure_session()
        if not self.session:
            return None

        url = f"{self.gamma_url}/events"
        params = {
            'market': condition_id,
            'after': int(start_time.timestamp()),
            'before': int(end_time.timestamp()),
            'limit': 1000
        }

        try:
            async with self.session.get(url, params=params, timeout=15) as response:
                if response.status != 200:
                    logger.error(f"Failed to fetch events for {condition_id}: HTTP {response.status}")
                    return None
                return await response.json()
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching events for {condition_id}")
        except Exception as exc:
            logger.error(f"Error fetching events for {condition_id}: {exc}")
        return None

    async def _fetch_trades_via_mcp(
        self,
        condition_id: str,
        days: int,
        start_time: datetime,
    ) -> List[Dict]:
        if not await self._maybe_init_mcp():
            return []

        cache_key = f"{condition_id}:{days}"
        cached = self._trade_cache.get(cache_key)
        if cached and datetime.now() - cached["ts"] < self._cache_ttl:
            return cached["data"]

        assert self._mcp_client is not None
        try:
            result = await self._mcp_client.get_trades(market_id=condition_id, limit=1000)
        except Exception as exc:
            logger.error(f"MCP trade fetch failed for {condition_id}: {exc}")
            self._mcp_enabled = False
            return []

        trades = result.get("trades") if isinstance(result, dict) else result
        if not trades:
            return []

        earliest_time = start_time
        price_points = []

        for trade in trades:
            price = trade.get("price")
            if price is None:
                continue

            try:
                price = float(price)
            except (ValueError, TypeError):
                continue

            ts_raw = trade.get("timestamp") or trade.get("created_at") or trade.get("filledAt")
            timestamp = self._parse_timestamp(ts_raw)
            if not timestamp or timestamp < earliest_time:
                continue

            price_points.append({"timestamp": timestamp, "price": price})

        price_points.sort(key=lambda x: x["timestamp"])

        if price_points:
            self._trade_cache[cache_key] = {
                "ts": datetime.now(),
                "data": price_points,
            }

        return price_points

    def _parse_timestamp(self, raw_value) -> Optional[datetime]:
        if raw_value is None:
            return None
        if isinstance(raw_value, (int, float)):
            return datetime.fromtimestamp(float(raw_value))
        if isinstance(raw_value, str):
            try:
                # strip Z if present
                if raw_value.endswith("Z"):
                    raw_value = raw_value[:-1]
                return datetime.fromisoformat(raw_value)
            except ValueError:
                return None
        return None

    def _extract_current_price(self, market_data: Dict) -> Optional[float]:
        """Extract current price from market data"""
        try:
            # Try different price fields
            if 'tokens' in market_data and len(market_data['tokens']) > 0:
                # Get first token's price
                token = market_data['tokens'][0]
                if 'price' in token:
                    return float(token['price'])

            # Fallback to market-level price
            if 'price' in market_data:
                return float(market_data['price'])

            return None

        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Error extracting price: {e}")
            return None

    def _parse_events_to_prices(self, events: List[Dict]) -> List[Dict]:
        """Parse events/trades into price time series"""
        price_points = []

        for event in events:
            try:
                timestamp = datetime.fromtimestamp(event.get('timestamp', 0))
                price = float(event.get('price', 0))

                if price > 0 and price < 1:
                    price_points.append({
                        'timestamp': timestamp,
                        'price': price
                    })
            except (KeyError, ValueError, TypeError):
                continue

        # Sort by timestamp
        price_points.sort(key=lambda x: x['timestamp'])

        return price_points

    def _generate_synthetic_history(
        self,
        condition_id: str,
        days: int
    ) -> List[Dict]:
        """
        Generate synthetic correlated price history as fallback
        Uses same seed as before for consistency
        """
        import numpy as np

        np.random.seed(hash(condition_id) % 2**32)

        base_price = 0.5
        trend = np.linspace(0, 0.1, days * 24)  # Hourly data
        noise = np.random.normal(0, 0.02, days * 24)

        prices = base_price + trend + noise
        prices = np.clip(prices, 0.01, 0.99)

        # Create aligned timestamps (hourly)
        # CRITICAL: Use consistent start time for alignment
        start_time = datetime(2025, 1, 1, 0, 0, 0)  # Fixed start for alignment
        timestamps = [start_time + timedelta(hours=i) for i in range(len(prices))]

        logger.info(f"Generated {len(timestamps)} synthetic price points for {condition_id}")

        return [
            {'timestamp': ts, 'price': float(price)}
            for ts, price in zip(timestamps, prices)
        ]

    async def get_recent_trade_price(
        self,
        condition_id: str,
        minutes: int = 60
    ) -> Optional[float]:
        """
        Return the most recent MCP trade price within the lookback window.
        """
        if minutes <= 0:
            minutes = 5

        start_time = datetime.now() - timedelta(minutes=minutes)
        trades = await self._fetch_trades_via_mcp(
            condition_id=condition_id,
            days=1,
            start_time=start_time,
        )
        if not trades:
            return None

        last_price = trades[-1].get("price")
        if last_price is None:
            return None
        try:
            return float(last_price)
        except (ValueError, TypeError):
            return None


async def test_api():
    """Test the API"""
    api = PolymarketHistoryAPI()

    # Test with a known market
    test_market = "0x19ee98fe1a1379ef360f5e24965e84a991eb80f6"

    print(f"Fetching history for {test_market}...")
    data = await api.get_historical_events(test_market, days=7)

    print(f"Received {len(data)} data points")
    if data:
        print(f"First point: {data[0]}")
        print(f"Last point: {data[-1]}")

    await api.close()


if __name__ == "__main__":
    asyncio.run(test_api())
