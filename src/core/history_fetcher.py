"""
Polymarket Historical Data Fetcher
===================================

Fetches real OHLCV (Open/High/Low/Close/Volume) data from Polymarket
for statistical arbitrage analysis.

Data Sources:
1. Polymarket CLOB API - Real-time and historical prices
2. Gamma Markets API - Alternative historical data source
3. Local cache - Reduce API calls

Author: ArbHunter V2.0
Created: 2026-01-02
"""

import asyncio
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import time

import aiohttp
import pandas as pd
import numpy as np

from src.core.rate_limiter import get_rate_limiter
from src.core.circuit_breaker import get_polymarket_circuit

logger = logging.getLogger(__name__)


class HistoryFetcher:
    """
    Fetch historical price data from Polymarket for time-series analysis.

    Provides data for:
    - Statistical arbitrage cointegration testing
    - Trend analysis
    - Volatility estimation
    - Backtesting strategies
    """

    def __init__(
        self,
        base_url: str = "https://clob.polymarket.com",
        gamma_url: str = "https://gamma-api.polymarket.com",
        cache_hours: int = 24
    ):
        self.base_url = base_url
        self.gamma_url = gamma_url
        self.cache_hours = cache_hours

        # Local cache to reduce API calls
        self.price_cache: Dict[str, pd.DataFrame] = {}
        self.cache_timestamps: Dict[str, datetime] = {}

    async def get_yes_token_id(self, condition_id: str) -> Optional[str]:
        """
        Resolve condition_id to YES token_id.

        Args:
            condition_id: Hexadecimal condition_id (0x...)

        Returns:
            YES token_id or None if failed
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/markets/{condition_id}"

                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.error(f"Failed to get market details for {condition_id}: {resp.status}")
                        return None

                    data = await resp.json()

                    # Extract YES token_id
                    tokens = data.get('tokens', [])
                    for token in tokens:
                        if token.get('outcome', '').lower() == 'yes':
                            return token['token_id']

                    logger.error(f"No YES token found for {condition_id}")
                    return None

        except Exception as e:
            logger.error(f"Error resolving condition_id {condition_id}: {e}")
            return None

    async def get_market_prices(
        self,
        token_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        interval: str = "1h"
    ) -> pd.DataFrame:
        """
        Get historical price data for a market token.

        Args:
            token_id: Polymarket condition_id (0x...) or token_id (numeric)
            start_time: Start timestamp (default: 30 days ago)
            end_time: End timestamp (default: now)
            interval: Candle interval ("1m", "5m", "15m", "1h", "1d")

        Returns:
            DataFrame with columns: timestamp, price, volume
        """
        # If token_id looks like a condition_id (starts with 0x), resolve to YES token_id
        if token_id.startswith('0x'):
            logger.debug(f"Resolving condition_id to token_id: {token_id}")
            yes_token_id = await self.get_yes_token_id(token_id)
            if not yes_token_id:
                logger.error(f"Failed to resolve condition_id: {token_id}")
                return pd.DataFrame()
            token_id = yes_token_id
            logger.debug(f"Using YES token_id: {token_id}")

        # Check cache first
        cache_key = f"{token_id}:{interval}"
        if cache_key in self.price_cache:
            if datetime.now() - self.cache_timestamps[cache_key] < timedelta(hours=self.cache_hours):
                logger.debug(f"Using cached data for {token_id}")
                return self.price_cache[cache_key]

        # Set default time range (max 14 days due to CLOB API limit)
        if end_time is None:
            end_time = datetime.now()
        if start_time is None:
            start_time = end_time - timedelta(days=14)

        # Convert to Unix timestamps
        start_ts = int(start_time.timestamp())
        end_ts = int(end_time.timestamp())

        # Try Polymarket CLOB API first
        df = await self._fetch_from_clob(token_id, start_ts, end_ts, interval)

        # Fallback to Gamma API if CLOB fails
        if df.empty:
            logger.warning(f"CLOB API failed for {token_id}, trying Gamma API...")
            df = await self._fetch_from_gamma(token_id, start_ts, end_ts, interval)

        # Cache the result
        if not df.empty:
            self.price_cache[cache_key] = df
            self.cache_timestamps[cache_key] = datetime.now()
            logger.info(f"✅ Fetched {len(df)} candles for {token_id} ({interval})")
        else:
            logger.error(f"❌ Failed to fetch data for {token_id}")

        return df

    async def _fetch_from_clob(
        self,
        token_id: str,
        start_ts: int,
        end_ts: int,
        interval: str
    ) -> pd.DataFrame:
        """
        Fetch from Polymarket CLOB API.

        Endpoint: GET /prices-history
        """
        circuit = get_polymarket_circuit()

        try:
            async def make_request():
                async with aiohttp.ClientSession() as session:
                    url = f"{self.base_url}/prices-history"

                    params = {
                        'market': token_id,
                        'startTs': start_ts,
                        'endTs': end_ts,
                        'interval': interval
                    }

                    async with session.get(
                        url,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as resp:
                        if resp.status != 200:
                            logger.error(f"CLOB API error: {resp.status}")
                            return pd.DataFrame()

                        data = await resp.json()
                        return self._parse_clob_response(data)

            # Use circuit breaker
            return await circuit.call(make_request)

        except Exception as e:
            logger.error(f"Failed to fetch from CLOB: {e}")
            return pd.DataFrame()

    async def _fetch_from_gamma(
        self,
        token_id: str,
        start_ts: int,
        end_ts: int,
        interval: str
    ) -> pd.DataFrame:
        """
        Fetch from Gamma Markets API (fallback).

        Endpoint: GET /markets/{token_id}/prices
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.gamma_url}/markets/{token_id}/prices"

                params = {
                    'from': start_ts,
                    'to': end_ts,
                    'resolution': interval
                }

                async with session.get(
                    url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"Gamma API error: {resp.status}")
                        return pd.DataFrame()

                    data = await resp.json()
                    return self._parse_gamma_response(data)

        except Exception as e:
            logger.error(f"Failed to fetch from Gamma: {e}")
            return pd.DataFrame()

    def _parse_clob_response(self, data: Dict) -> pd.DataFrame:
        """
        Parse CLOB API response to DataFrame.

        Expected format:
        {
            "history": [
                {"t": timestamp, "p": price, "v": volume},
                ...
            ]
        }
        """
        if 'history' not in data or not data['history']:
            return pd.DataFrame()

        records = []
        for candle in data['history']:
            records.append({
                'timestamp': pd.to_datetime(candle['t'], unit='s'),
                'price': float(candle.get('p', 0)),
                'volume': float(candle.get('v', 0))
            })

        df = pd.DataFrame(records)
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)

        return df

    def _parse_gamma_response(self, data: Dict) -> pd.DataFrame:
        """
        Parse Gamma API response to DataFrame.

        Expected format:
        {
            "prices": [
                {"timestamp": ts, "price": p, "volume": v},
                ...
            ]
        }
        """
        if 'prices' not in data or not data['prices']:
            return pd.DataFrame()

        records = []
        for point in data['prices']:
            records.append({
                'timestamp': pd.to_datetime(point['timestamp']),
                'price': float(point.get('price', 0)),
                'volume': float(point.get('volume', 0))
            })

        df = pd.DataFrame(records)
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)

        return df

    async def get_orderbook_snapshot(
        self,
        token_id: str
    ) -> Dict:
        """
        Get current orderbook snapshot for a token.

        Args:
            token_id: Market token ID

        Returns:
            Dict with bids and asks
        """
        circuit = get_polymarket_circuit()

        try:
            async def fetch_orderbook():
                async with aiohttp.ClientSession() as session:
                    url = f"{self.base_url}/book"
                    params = {'token_id': token_id}

                    async with session.get(url, params=params, timeout=10) as resp:
                        if resp.status != 200:
                            return {'bids': [], 'asks': []}

                        return await resp.json()

            return await circuit.call(fetch_orderbook)

        except Exception as e:
            logger.error(f"Failed to fetch orderbook for {token_id}: {e}")
            return {'bids': [], 'asks': []}

    async def get_market_info(
        self,
        condition_id: str
    ) -> Dict:
        """
        Get market metadata (question, end date, tokens, etc.)

        Args:
            condition_id: Polymarket condition ID

        Returns:
            Dict with market info
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.gamma_url}/markets/{condition_id}"

                async with session.get(url, timeout=10) as resp:
                    if resp.status != 200:
                        logger.error(f"Failed to fetch market info: {resp.status}")
                        return {}

                    return await resp.json()

        except Exception as e:
            logger.error(f"Failed to fetch market info: {e}")
            return {}

    async def search_markets(
        self,
        query: str,
        limit: int = 50,
        active_only: bool = True
    ) -> List[Dict]:
        """
        Search for markets by keyword.

        Args:
            query: Search query (e.g., "Bitcoin", "Trump")
            limit: Max results to return
            active_only: Only return active markets

        Returns:
            List of market dicts
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.gamma_url}/markets"

                # Sort by volume to find liquid markets first, but fetch more to filter later
                params = {
                    'q': query,
                    'limit': limit,
                    'closed': 'false' if active_only else 'true',
                    'order': 'volume',
                    'ascending': 'false'
                }

                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        return []

                    data = await resp.json()
                    if isinstance(data, list):
                        return data
                    return data.get('markets', [])

        except Exception as e:
            logger.error(f"Failed to search markets: {e}")
            return []

    def calculate_returns(self, df: pd.DataFrame) -> pd.Series:
        """Calculate log returns from price series"""
        if 'price' not in df.columns:
            return pd.Series()

        return np.log(df['price'] / df['price'].shift(1)).dropna()

    def calculate_volatility(
        self,
        df: pd.DataFrame,
        window: int = 24
    ) -> float:
        """
        Calculate rolling volatility (annualized).

        Args:
            df: Price DataFrame
            window: Rolling window size

        Returns:
            Annualized volatility
        """
        returns = self.calculate_returns(df)
        if returns.empty:
            return 0.0

        # Rolling std * sqrt(periods per year)
        # For hourly data: 24 hours * 365 days = 8760
        vol = returns.std() * np.sqrt(8760)
        return float(vol)

    async def get_correlation_matrix(
        self,
        token_ids: List[str],
        days: int = 30
    ) -> pd.DataFrame:
        """
        Calculate correlation matrix for multiple tokens.

        Args:
            token_ids: List of token IDs
            days: Lookback period

        Returns:
            Correlation matrix DataFrame
        """
        # Fetch data for all tokens
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)

        price_data = {}

        for token_id in token_ids:
            df = await self.get_market_prices(token_id, start_time, end_time)
            if not df.empty:
                price_data[token_id] = df['price']

        # Create combined DataFrame
        if not price_data:
            return pd.DataFrame()

        combined_df = pd.DataFrame(price_data)

        # Calculate correlation
        corr_matrix = combined_df.corr()

        return corr_matrix


# Singleton instance
_history_fetcher_instance = None


def get_history_fetcher() -> HistoryFetcher:
    """Get or create global HistoryFetcher instance"""
    global _history_fetcher_instance

    if _history_fetcher_instance is None:
        _history_fetcher_instance = HistoryFetcher()

    return _history_fetcher_instance
