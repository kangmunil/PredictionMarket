import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from .signal_bus import SignalBus

logger = logging.getLogger(__name__)


@dataclass
class DeltaAllowance:
    """Represents the result of a delta limit evaluation."""

    allowed: bool
    reason: str = ""
    reduce_only: bool = False
    projected_delta: float = 0.0
    current_delta: float = 0.0
    group: str = "DEFAULT"
    hard_limit: Optional[float] = None
    soft_limit: Optional[float] = None


class DeltaTracker:
    """
    Tracks per-token exposure (delta), aggregates exposure per market group,
    and provides guard-rail checks before new trades.
    """

    def __init__(self, signal_bus: SignalBus, delta_limits: Optional[dict] = None):
        self.signal_bus = signal_bus
        self._positions: Dict[str, Dict] = {}
        self._group_deltas: Dict[str, float] = {}
        self._lock = asyncio.Lock()
        self.delta_limits = self._normalize_limits(delta_limits or {})

    def _normalize_limits(self, limits: Dict[str, dict]) -> Dict[str, Dict[str, Optional[float]]]:
        normalized: Dict[str, Dict[str, Optional[float]]] = {}
        for key, value in limits.items():
            if not isinstance(value, dict):
                continue
            normalized[str(key).upper()] = {
                "hard": float(value["hard"]) if value.get("hard") is not None else None,
                "soft": float(value["soft"]) if value.get("soft") is not None else None,
            }

        if "DEFAULT" not in normalized:
            normalized["DEFAULT"] = {"hard": 800.0, "soft": 600.0}
        return normalized

    def _resolve_group(self, explicit: Optional[str], existing: Optional[str]) -> str:
        if explicit:
            return explicit.upper()
        if existing:
            return existing
        return "DEFAULT"

    def _get_limits(self, group: str) -> Dict[str, Optional[float]]:
        return self.delta_limits.get(group, self.delta_limits["DEFAULT"])

    def _resolve_key(self, token_id: Optional[str], condition_id: Optional[str]) -> str:
        if condition_id:
            return str(condition_id)
        if token_id:
            return str(token_id)
        return "UNSPECIFIED"

    async def check_allowance(
        self,
        token_id: str,
        side: str,
        size: float,
        *,
        market_group: Optional[str] = None,
        condition_id: Optional[str] = None,
    ) -> DeltaAllowance:
        """
        Evaluate whether a proposed trade keeps exposure within configured limits.
        """
        if size <= 0:
            return DeltaAllowance(True, reason="zero-size", group="DEFAULT")

        side = side.upper()
        delta_change = size if side == "BUY" else -size

        async with self._lock:
            exposure_key = self._resolve_key(token_id, condition_id)
            pos = self._positions.get(exposure_key)
            current_group = self._resolve_group(market_group, pos.get("market_group") if pos else None)
            group_delta = self._group_deltas.get(current_group, 0.0)
            projected_group = group_delta + delta_change
            limits = self._get_limits(current_group)
            hard = limits.get("hard")
            soft = limits.get("soft")

            if hard is not None and abs(projected_group) > hard:
                return DeltaAllowance(
                    allowed=False,
                    reason=f"Hard delta limit |{projected_group:.2f}| > {hard}",
                    projected_delta=projected_group,
                    current_delta=group_delta,
                    group=current_group,
                    hard_limit=hard,
                    soft_limit=soft,
                )

            if soft is not None and abs(projected_group) > soft:
                if abs(projected_group) < abs(group_delta):
                    return DeltaAllowance(
                        allowed=True,
                        reason="Soft limit reduce-only",
                        reduce_only=True,
                        projected_delta=projected_group,
                        current_delta=group_delta,
                        group=current_group,
                        hard_limit=hard,
                        soft_limit=soft,
                    )
                else:
                    return DeltaAllowance(
                        allowed=False,
                        reason=f"Soft delta limit |{projected_group:.2f}| > {soft}",
                        projected_delta=projected_group,
                        current_delta=group_delta,
                        group=current_group,
                        hard_limit=hard,
                        soft_limit=soft,
                    )

            return DeltaAllowance(
                allowed=True,
                projected_delta=projected_group,
                current_delta=group_delta,
                group=current_group,
                hard_limit=hard,
                soft_limit=soft,
            )

    async def record_trade(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
        *,
        condition_id: Optional[str] = None,
        market_name: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        market_group: Optional[str] = None,
    ):
        if size <= 0:
            return

        side = side.upper()

        exposure_key = self._resolve_key(token_id, condition_id)

        async with self._lock:
            pos = self._positions.setdefault(
                exposure_key,
                {
                    "long_size": 0.0,
                    "long_notional": 0.0,
                    "short_size": 0.0,
                    "short_notional": 0.0,
                    "condition_id": condition_id,
                    "market_name": market_name,
                    "expires_at": expires_at,
                    "market_group": market_group or "DEFAULT",
                    "token_ids": set(),
                },
            )

            if token_id:
                pos["token_ids"].add(token_id)
            pos["market_group"] = self._resolve_group(market_group, pos.get("market_group"))
            group_key = pos["market_group"]
            prev_delta = pos["long_size"] - pos["short_size"]

            if market_name:
                pos["market_name"] = market_name
            if condition_id:
                pos["condition_id"] = condition_id
            if expires_at:
                pos["expires_at"] = expires_at

            if side == "BUY":
                pos["long_size"] += size
                pos["long_notional"] += price * size
            else:
                pos["short_size"] += size
                pos["short_notional"] += price * size

            delta = pos["long_size"] - pos["short_size"]
            delta_change = delta - prev_delta
            self._group_deltas[group_key] = self._group_deltas.get(group_key, 0.0) + delta_change

            avg_long = (
                pos["long_notional"] / pos["long_size"] if pos["long_size"] > 0 else 0.0
            )
            avg_short = (
                pos["short_notional"] / pos["short_size"] if pos["short_size"] > 0 else 0.0
            )
            spread = avg_long - avg_short if (avg_long and avg_short) else 0.0

            metadata = {
                "market_group": group_key,
                "group_delta": self._group_deltas.get(group_key, 0.0),
            }
            if pos.get("market_name"):
                metadata["market_name"] = pos["market_name"]
            if pos.get("condition_id"):
                metadata["condition_id"] = pos["condition_id"]
            if pos.get("expires_at"):
                metadata["expires_at"] = (
                    pos["expires_at"].isoformat()
                    if isinstance(pos["expires_at"], datetime)
                    else pos["expires_at"]
                )

        mid_price = None
        if avg_long and avg_short and avg_long > 0 and avg_short > 0:
            mid_price = (avg_long + avg_short) / 2.0

        await self.signal_bus.update_market_metrics(
            token_id=token_id,
            delta_exposure=delta,
            long_avg_price=avg_long,
            short_avg_price=avg_short,
            spread=spread,
            metadata=metadata,
            mid_price=mid_price,
        )

    def get_snapshot(self) -> Dict[str, Dict]:
        """Return current per-token delta snapshot (for debugging/tests)."""
        snapshot = {}
        for key, value in self._positions.items():
            entry = value.copy()
            tokens = entry.get("token_ids")
            if isinstance(tokens, set):
                entry["token_ids"] = list(tokens)
            snapshot[key] = entry
        return snapshot

    def get_group_snapshot(self) -> Dict[str, float]:
        """Return aggregated delta per market group."""
        return self._group_deltas.copy()
