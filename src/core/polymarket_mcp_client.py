"""
Polymarket MCP Client
=====================

Thin async wrapper around the Polymarket MCP service so agents can query
markets, events, and trades without hitting hard-coded endpoints.

The client expects a JSON-RPC 2.0 compatible MCP gateway (such as the
`polymarket-mcp` server) and can be configured through environment
variables:
    POLYMARKET_MCP_URL       - Base URL for the MCP endpoint
    POLYMARKET_MCP_API_KEY   - Optional bearer token for auth

If the MCP endpoint is unavailable the caller should fall back to the
legacy Gamma client.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class PolymarketMCPClient:
    """Helper for invoking the polymarket MCP service."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 15.0,
    ):
        self.base_url = base_url or os.getenv("POLYMARKET_MCP_URL")
        self.api_key = api_key or os.getenv("POLYMARKET_MCP_API_KEY")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._sync_client: Optional[httpx.Client] = None

    async def __aenter__(self):
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _ensure_client(self):
        if not self.base_url:
            raise RuntimeError("POLYMARKET_MCP_URL not configured")
        if not self._client:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=headers,
            )

    def _ensure_sync_client(self):
        if not self.base_url:
            raise RuntimeError("POLYMARKET_MCP_URL not configured")
        if not self._sync_client:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._sync_client = httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=headers,
            )

    async def _call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        await self._ensure_client()
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params or {},
        }

        try:
            assert self._client is not None  # appease type checker
            resp = await self._client.post("", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("Polymarket MCP call failed (%s): %s", method, exc)
            raise

        if "error" in data:
            raise RuntimeError(f"MCP error ({method}): {data['error']}")

        return data.get("result")

    def _call_sync(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        self._ensure_sync_client()
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params or {},
        }

        try:
            assert self._sync_client is not None
            resp = self._sync_client.post("", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.error("Polymarket MCP sync call failed (%s): %s", method, exc)
            raise

        if "error" in data:
            raise RuntimeError(f"MCP error ({method}): {data['error']}")

        return data.get("result")

    async def search_markets(
        self,
        query: Optional[str] = None,
        limit: int = 50,
        order: str = "volume",
        ascending: bool = False,
        closed: bool = False,
        tag_id: Optional[int] = None,
        volume_min: Optional[float] = None,
        liquidity_min: Optional[float] = None,
    ) -> Any:
        params: Dict[str, Any] = {
            "limit": limit,
            "order": order,
            "ascending": ascending,
            "closed": closed,
        }
        if query:
            params["query"] = query
        if tag_id is not None:
            params["tag_id"] = tag_id
        if volume_min is not None:
            params["volume_min"] = volume_min
        if liquidity_min is not None:
            params["liquidity_min"] = liquidity_min

        return await self._call("search_markets", params)

    async def get_market(self, slug: str) -> Any:
        return await self._call("get_market", {"slug": slug})

    async def get_event(self, slug: str) -> Any:
        return await self._call("get_event", {"slug": slug})

    async def get_trades(
        self,
        market_id: Optional[str] = None,
        limit: int = 50,
        side: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> Any:
        params: Dict[str, Any] = {"limit": limit}
        if market_id:
            params["market"] = market_id
        if side:
            params["side"] = side
        if event_id:
            params["eventId"] = event_id

        return await self._call("get_trades", params)

    def get_market_sync(self, slug: str) -> Any:
        return self._call_sync("get_market", {"slug": slug})


_client_singleton: Optional[PolymarketMCPClient] = None
_client_lock = asyncio.Lock()


async def get_default_mcp_client() -> Optional[PolymarketMCPClient]:
    """Provide a singleton MCP client if the URL is configured."""
    global _client_singleton
    if _client_singleton:
        return _client_singleton

    async with _client_lock:
        if _client_singleton:
            return _client_singleton

        base = os.getenv("POLYMARKET_MCP_URL")
        if not base:
            return None

        _client_singleton = PolymarketMCPClient(base_url=base)
        return _client_singleton
