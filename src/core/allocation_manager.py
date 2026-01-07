"""
Portfolio allocation helper that combines on-chain balances and
Polymarket market data (via MCP) to size trades per wallet exposure.
"""

from __future__ import annotations

import asyncio
import logging
import os
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

try:
    from web3 import Web3
except Exception:  # pragma: no cover - optional dependency
    Web3 = None  # type: ignore

from .config import Config
from .market_registry import market_registry

logger = logging.getLogger(__name__)

USDC_DEFAULT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    }
]


class AllocationManager:
    """
    Periodically refreshes USDC balances + Polymarket positions and
    provides per-market allocation caps that respect wallet exposure.
    """

    def __init__(self, refresh_ttl_seconds: int = 60, enable_onchain: bool = True):
        self.config = Config()
        self._refresh_ttl = timedelta(seconds=refresh_ttl_seconds)
        self._last_refresh: Optional[datetime] = None
        self._usdc_balance = Decimal("0")
        self._positions: List[Dict] = []
        self._lock = asyncio.Lock()
        self._data_api_url = os.getenv(
            "POLYMARKET_DATA_API_URL", "https://clob.polymarket.com/positions"
        )
        self._data_api_key = os.getenv("POLYMARKET_DATA_API_KEY")

        self._web3 = None
        self._usdc_contract = None
        if enable_onchain and Web3 and self.config.FUNDER_ADDRESS:
            try:
                self._web3 = Web3(Web3.HTTPProvider(self.config.RPC_URL))
                self._usdc_contract = self._web3.eth.contract(
                    address=Web3.to_checksum_address(
                        os.getenv("USDC_CONTRACT_ADDRESS", USDC_DEFAULT)
                    ),
                    abi=USDC_ABI,
                )
            except Exception as exc:
                logger.warning(f"⚠️ Unable to initialize Web3 allocator: {exc}")
                self._web3 = None

    async def allocate_for_market(
        self,
        token_id: str,
        desired_usd: float,
        allocation_pct: float = 0.3,
        per_market_pct: float = 0.1,
    ) -> float:
        """
        Compute the dollar budget that can be deployed into `token_id`
        while respecting wallet balance and existing exposure.
        """
        desired = Decimal(str(max(desired_usd, 0.0)))
        if desired <= 0:
            return 0.0

        await self._ensure_state()

        total_budget = self._usdc_balance * Decimal(str(allocation_pct))
        used_budget = self._current_total_exposure()
        available_budget = max(total_budget - used_budget, Decimal("0"))

        per_market_cap = self._usdc_balance * Decimal(str(per_market_pct))
        existing_market_exposure = self._market_exposure(token_id)
        remaining_for_market = max(per_market_cap - existing_market_exposure, Decimal("0"))

        allowance = min(desired, available_budget, remaining_for_market)
        if allowance <= 0:
            logger.info(
                f"⚠️ Allocation blocked: token {token_id[:12]} budget exhausted "
                f"(avail ${available_budget:.2f}, market cap ${remaining_for_market:.2f})"
            )
            return 0.0

        logger.debug(
            "💰 AllocationManager granted $%.2f (avail %.2f / market %.2f)",
            float(allowance),
            float(available_budget),
            float(remaining_for_market),
        )
        return float(allowance)

    async def refresh(self):
        """Force-refresh wallet state."""
        async with self._lock:
            await self._refresh_locked(force=True)

    async def _ensure_state(self):
        async with self._lock:
            await self._refresh_locked(force=False)

    async def _refresh_locked(self, force: bool):
        if not force and self._last_refresh and datetime.now() - self._last_refresh < self._refresh_ttl:
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._refresh_state)

    def _refresh_state(self):
        self._usdc_balance = self._fetch_usdc_balance()
        self._positions = self._fetch_positions()
        self._last_refresh = datetime.now()

    def _fetch_usdc_balance(self) -> Decimal:
        if not self._web3 or not self._usdc_contract or not self.config.FUNDER_ADDRESS:
            return Decimal("0")
        try:
            checksum = self._web3.to_checksum_address(self.config.FUNDER_ADDRESS)
            balance_wei = self._usdc_contract.functions.balanceOf(checksum).call()
            return Decimal(balance_wei) / Decimal(10**6)
        except Exception as exc:
            logger.error(f"❌ USDC balance fetch failed: {exc}")
            return Decimal("0")

    def _fetch_positions(self) -> List[Dict]:
        if not self._data_api_key or not self.config.FUNDER_ADDRESS:
            return []

        headers = {"Authorization": f"Bearer {self._data_api_key}"}
        params = {"address": self.config.FUNDER_ADDRESS}
        try:
            resp = requests.get(self._data_api_url, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                data = data.get("positions", [])
            if isinstance(data, list):
                for market in data:
                    market_registry.register_market(market)
                return data
        except Exception as exc:
            logger.error(f"❌ Failed to fetch positions: {exc}")
        return []

    def _current_total_exposure(self) -> Decimal:
        exposure = Decimal("0")
        for position in self._positions:
            exposure_value = (
                position.get("exposure_usd")
                or position.get("exposure")
                or position.get("value")
                or 0
            )
            try:
                exposure += Decimal(str(abs(exposure_value)))
            except Exception:
                continue
        return exposure

    def _market_exposure(self, token_id: str) -> Decimal:
        token_keys = ("token_id", "tokenId", "tokenID")
        exposure = Decimal("0")
        for position in self._positions:
            position_token = None
            for key in token_keys:
                if key in position:
                    position_token = str(position[key])
                    break
            if not position_token:
                continue
            if position_token != token_id:
                continue
            exposure_value = (
                position.get("exposure_usd")
                or position.get("exposure")
                or position.get("value")
                or 0
            )
            try:
                exposure += Decimal(str(abs(exposure_value)))
            except Exception:
                continue
        return exposure
