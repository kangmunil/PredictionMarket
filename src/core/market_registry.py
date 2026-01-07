"""
Simple in-memory registry that tracks Polymarket markets we've seen so
we can map between condition IDs (used throughout the legacy code) and
slugs (required by the MCP API).
"""

from __future__ import annotations

from threading import RLock
from typing import Dict, Optional


class MarketRegistry:
    def __init__(self):
        self._lock = RLock()
        self._condition_to_slug: Dict[str, str] = {}
        self._slug_to_condition: Dict[str, str] = {}

    def register_market(self, market: Dict) -> None:
        condition_id = market.get("condition_id") or market.get("id")
        slug = market.get("slug")
        if not condition_id or not slug:
            return
        condition_id = str(condition_id)
        slug = str(slug)

        with self._lock:
            self._condition_to_slug[condition_id] = slug
            self._slug_to_condition[slug] = condition_id

    def get_slug(self, condition_id: str) -> Optional[str]:
        with self._lock:
            return self._condition_to_slug.get(str(condition_id))

    def get_condition_id(self, slug: str) -> Optional[str]:
        with self._lock:
            return self._slug_to_condition.get(str(slug))


market_registry = MarketRegistry()
