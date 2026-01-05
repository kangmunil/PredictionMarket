"""
Unified Risk Management - Swarm-Wide Risk Controls
===================================================

Monitors and enforces risk limits across the entire bot swarm.

Features:
- Portfolio-level position limits
- Correlation-based exposure management
- Circuit breaker (auto-pause on large losses)
- Signal quality monitoring
- Emergency stop mechanisms

Author: Project Hive Mind
Created: 2026-01-05
"""

import asyncio
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from collections import defaultdict, deque

from src.core.signal_bus import SignalBus, Signal, SignalType, SignalPriority

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Risk limit configuration"""
    max_position_size_usd: Decimal = Decimal("200")      # Per position
    max_total_exposure_usd: Decimal = Decimal("800")     # Total across all bots
    max_entity_exposure_usd: Decimal = Decimal("400")    # Per entity (e.g., Bitcoin)
    max_positions_per_bot: int = 5                       # Position count limit
    max_daily_loss_usd: Decimal = Decimal("100")         # Daily loss limit
    max_correlation_exposure: float = 0.7                # Max correlated positions
    min_signal_quality: float = 0.6                      # Min signal strength


@dataclass
class Position:
    """Active position tracking"""
    bot_name: str
    market_id: str
    token_id: str
    entity: str
    side: str
    size_usd: Decimal
    entry_price: float
    current_price: float
    pnl: Decimal
    opened_at: datetime

    @property
    def exposure_usd(self) -> Decimal:
        """Current exposure value"""
        return self.size_usd * Decimal(str(self.current_price / self.entry_price))


class SwarmRiskManager:
    """
    Centralized risk management for bot swarm

    Responsibilities:
    - Track all open positions across bots
    - Enforce position/exposure limits
    - Monitor PnL and circuit breaker
    - Detect over-concentration
    - Emergency stop coordination

    Usage:
        risk_mgr = SwarmRiskManager(signal_bus, limits)
        await risk_mgr.start()

        # Check if trade is allowed
        if await risk_mgr.check_trade_risk(bot_name, entity, size_usd):
            execute_trade()
    """

    def __init__(
        self,
        signal_bus: SignalBus,
        limits: Optional[RiskLimits] = None
    ):
        self.signal_bus = signal_bus
        self.limits = limits or RiskLimits()

        # Position tracking
        self.positions: Dict[str, Position] = {}  # position_id -> Position
        self.bot_positions: Dict[str, List[str]] = defaultdict(list)  # bot -> position_ids
        self.entity_positions: Dict[str, List[str]] = defaultdict(list)  # entity -> position_ids

        # PnL tracking
        self.daily_pnl: Decimal = Decimal("0")
        self.total_pnl: Decimal = Decimal("0")
        self.pnl_history: deque = deque(maxlen=1000)

        # Circuit breaker
        self.circuit_breaker_active = False
        self.circuit_breaker_reason = ""

        # Running state
        self.running = False
        self._monitor_task = None

    async def start(self):
        """Start risk manager"""
        self.running = True

        # Subscribe to position updates
        self.signal_bus.subscribe(
            SignalType.POSITION_UPDATE,
            "risk_manager",
            self._on_position_update
        )

        # Start monitoring task
        self._monitor_task = asyncio.create_task(self._monitor_risk())

        logger.info("SwarmRiskManager started")
        self._log_limits()

    async def stop(self):
        """Stop risk manager"""
        self.running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("SwarmRiskManager stopped")

    def _log_limits(self):
        """Log risk limits"""
        logger.info("Risk Limits:")
        logger.info(f"  Max Position Size: ${self.limits.max_position_size_usd}")
        logger.info(f"  Max Total Exposure: ${self.limits.max_total_exposure_usd}")
        logger.info(f"  Max Entity Exposure: ${self.limits.max_entity_exposure_usd}")
        logger.info(f"  Max Positions/Bot: {self.limits.max_positions_per_bot}")
        logger.info(f"  Max Daily Loss: ${self.limits.max_daily_loss_usd}")

    async def _on_position_update(self, signal: Signal):
        """Handle position update signals"""
        data = signal.data
        action = data.get('action')  # 'open' | 'close' | 'update'

        if action == 'open':
            await self._add_position(data)
        elif action == 'close':
            await self._close_position(data)
        elif action == 'update':
            await self._update_position(data)

    async def _add_position(self, data: dict):
        """Add new position"""
        position_id = f"{data['bot_name']}_{data['market_id']}_{datetime.now().timestamp()}"

        position = Position(
            bot_name=data['bot_name'],
            market_id=data['market_id'],
            token_id=data['token_id'],
            entity=data['entity'],
            side=data['side'],
            size_usd=Decimal(str(data['size_usd'])),
            entry_price=data['entry_price'],
            current_price=data['entry_price'],
            pnl=Decimal("0"),
            opened_at=datetime.now()
        )

        self.positions[position_id] = position
        self.bot_positions[data['bot_name']].append(position_id)
        self.entity_positions[data['entity']].append(position_id)

        logger.info(
            f"Position opened: {data['bot_name']} - {data['entity']} - "
            f"{data['side']} ${data['size_usd']}"
        )

    async def _close_position(self, data: dict):
        """Close position"""
        position_id = data.get('position_id')
        if not position_id or position_id not in self.positions:
            logger.warning(f"Position not found: {position_id}")
            return

        position = self.positions[position_id]
        pnl = Decimal(str(data.get('pnl', 0)))

        # Update PnL
        self.daily_pnl += pnl
        self.total_pnl += pnl
        self.pnl_history.append({
            'timestamp': datetime.now(),
            'pnl': pnl,
            'bot': position.bot_name,
            'entity': position.entity
        })

        # Remove position
        del self.positions[position_id]
        self.bot_positions[position.bot_name].remove(position_id)
        self.entity_positions[position.entity].remove(position_id)

        logger.info(
            f"Position closed: {position.bot_name} - {position.entity} - "
            f"PnL: ${pnl:.2f}"
        )

        # Check circuit breaker
        await self._check_circuit_breaker()

    async def _update_position(self, data: dict):
        """Update position current price"""
        position_id = data.get('position_id')
        if not position_id or position_id not in self.positions:
            return

        position = self.positions[position_id]
        position.current_price = data.get('current_price', position.current_price)

        # Calculate unrealized PnL
        price_change = (position.current_price - position.entry_price) / position.entry_price
        if position.side == 'SELL':
            price_change = -price_change

        position.pnl = position.size_usd * Decimal(str(price_change))

    async def _monitor_risk(self):
        """Background risk monitoring"""
        while self.running:
            try:
                # Update unrealized PnL
                self._calculate_unrealized_pnl()

                # Check limits
                await self._check_exposure_limits()
                await self._check_correlation()
                await self._check_circuit_breaker()

                # Log status every 5 minutes
                await asyncio.sleep(300)
                self._log_status()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Risk monitor error: {e}", exc_info=True)
                await asyncio.sleep(60)

    def _calculate_unrealized_pnl(self):
        """Calculate total unrealized PnL"""
        unrealized = sum(
            pos.pnl for pos in self.positions.values()
        )
        # Don't update daily_pnl here (only on close)
        logger.debug(f"Unrealized PnL: ${unrealized:.2f}")

    async def _check_exposure_limits(self):
        """Check if exposure limits are breached"""
        # Total exposure
        total_exposure = sum(
            pos.exposure_usd for pos in self.positions.values()
        )

        if total_exposure > self.limits.max_total_exposure_usd:
            await self._trigger_alert(
                f"Total exposure limit breached: "
                f"${total_exposure:.2f} > ${self.limits.max_total_exposure_usd}"
            )

        # Per-entity exposure
        for entity, position_ids in self.entity_positions.items():
            entity_exposure = sum(
                self.positions[pid].exposure_usd for pid in position_ids
            )

            if entity_exposure > self.limits.max_entity_exposure_usd:
                await self._trigger_alert(
                    f"Entity exposure limit breached ({entity}): "
                    f"${entity_exposure:.2f} > ${self.limits.max_entity_exposure_usd}"
                )

    async def _check_correlation(self):
        """Check for over-correlated positions"""
        # Group positions by entity
        entity_counts = {
            entity: len(pids)
            for entity, pids in self.entity_positions.items()
        }

        total_positions = len(self.positions)
        if total_positions == 0:
            return

        # Check if too many positions in same entity
        for entity, count in entity_counts.items():
            correlation = count / total_positions

            if correlation > self.limits.max_correlation_exposure:
                await self._trigger_alert(
                    f"Over-concentration in {entity}: "
                    f"{correlation*100:.1f}% of positions"
                )

    async def _check_circuit_breaker(self):
        """Check if circuit breaker should trigger"""
        if self.circuit_breaker_active:
            return

        # Check daily loss
        if self.daily_pnl < -self.limits.max_daily_loss_usd:
            await self._trigger_circuit_breaker(
                f"Daily loss limit exceeded: ${self.daily_pnl:.2f}"
            )

        # Check rapid loss (>50% of daily limit in 15 minutes)
        recent_pnl = sum(
            entry['pnl'] for entry in self.pnl_history
            if (datetime.now() - entry['timestamp']).total_seconds() < 900
        )

        if recent_pnl < -(self.limits.max_daily_loss_usd * Decimal("0.5")):
            await self._trigger_circuit_breaker(
                f"Rapid loss detected: ${recent_pnl:.2f} in 15 minutes"
            )

    async def _trigger_alert(self, message: str):
        """Trigger risk alert"""
        logger.warning(f"RISK ALERT: {message}")

        await self.signal_bus.publish(Signal(
            signal_type=SignalType.RISK_ALERT,
            priority=SignalPriority.HIGH,
            source_bot="risk_manager",
            timestamp=datetime.now(),
            ttl=300,
            data={
                'severity': 'high',
                'message': message,
                'positions_count': len(self.positions),
                'daily_pnl': float(self.daily_pnl),
                'total_pnl': float(self.total_pnl)
            }
        ))

    async def _trigger_circuit_breaker(self, reason: str):
        """Trigger circuit breaker (pause all trading)"""
        self.circuit_breaker_active = True
        self.circuit_breaker_reason = reason

        logger.critical(f"CIRCUIT BREAKER TRIGGERED: {reason}")

        await self.signal_bus.publish(Signal(
            signal_type=SignalType.RISK_ALERT,
            priority=SignalPriority.CRITICAL,
            source_bot="risk_manager",
            timestamp=datetime.now(),
            ttl=None,  # Never expires until manually reset
            data={
                'severity': 'critical',
                'message': f"CIRCUIT BREAKER: {reason}",
                'action': 'STOP_ALL_TRADING',
                'positions_count': len(self.positions),
                'daily_pnl': float(self.daily_pnl),
                'total_pnl': float(self.total_pnl)
            }
        ))

    def _log_status(self):
        """Log current risk status"""
        logger.info("\n" + "=" * 80)
        logger.info("RISK MANAGER STATUS")
        logger.info("=" * 80)

        logger.info(f"Circuit Breaker: {'ACTIVE' if self.circuit_breaker_active else 'INACTIVE'}")
        if self.circuit_breaker_active:
            logger.info(f"  Reason: {self.circuit_breaker_reason}")

        logger.info(f"\nPnL:")
        logger.info(f"  Daily: ${self.daily_pnl:.2f}")
        logger.info(f"  Total: ${self.total_pnl:.2f}")

        logger.info(f"\nPositions: {len(self.positions)}")
        for bot_name, position_ids in self.bot_positions.items():
            logger.info(f"  {bot_name}: {len(position_ids)}")

        total_exposure = sum(pos.exposure_usd for pos in self.positions.values())
        logger.info(f"\nTotal Exposure: ${total_exposure:.2f} / ${self.limits.max_total_exposure_usd}")

        logger.info("=" * 80 + "\n")

    # ========================================================================
    # Public Interface
    # ========================================================================

    async def check_trade_risk(
        self,
        bot_name: str,
        entity: str,
        size_usd: Decimal,
        signal_strength: float = 0.5
    ) -> bool:
        """
        Check if a trade passes risk checks

        Args:
            bot_name: Bot requesting trade
            entity: Entity being traded
            size_usd: Trade size in USD
            signal_strength: Signal quality (0-1)

        Returns:
            True if trade is allowed, False otherwise
        """
        # Circuit breaker check
        if self.circuit_breaker_active:
            logger.warning(f"{bot_name} trade blocked: Circuit breaker active")
            return False

        # Signal quality check
        if signal_strength < self.limits.min_signal_quality:
            logger.warning(
                f"{bot_name} trade blocked: Low signal quality "
                f"({signal_strength:.2f} < {self.limits.min_signal_quality})"
            )
            return False

        # Position size check
        if size_usd > self.limits.max_position_size_usd:
            logger.warning(
                f"{bot_name} trade blocked: Position too large "
                f"(${size_usd} > ${self.limits.max_position_size_usd})"
            )
            return False

        # Position count check
        bot_position_count = len(self.bot_positions.get(bot_name, []))
        if bot_position_count >= self.limits.max_positions_per_bot:
            logger.warning(
                f"{bot_name} trade blocked: Too many positions "
                f"({bot_position_count} >= {self.limits.max_positions_per_bot})"
            )
            return False

        # Total exposure check
        total_exposure = sum(pos.exposure_usd for pos in self.positions.values())
        if total_exposure + size_usd > self.limits.max_total_exposure_usd:
            logger.warning(
                f"{bot_name} trade blocked: Total exposure limit "
                f"(${total_exposure + size_usd:.2f} > ${self.limits.max_total_exposure_usd})"
            )
            return False

        # Entity exposure check
        entity_exposure = sum(
            self.positions[pid].exposure_usd
            for pid in self.entity_positions.get(entity, [])
        )
        if entity_exposure + size_usd > self.limits.max_entity_exposure_usd:
            logger.warning(
                f"{bot_name} trade blocked: Entity exposure limit for {entity} "
                f"(${entity_exposure + size_usd:.2f} > ${self.limits.max_entity_exposure_usd})"
            )
            return False

        # All checks passed
        logger.info(f"{bot_name} trade approved: {entity} ${size_usd:.2f}")
        return True

    async def reset_circuit_breaker(self):
        """Manually reset circuit breaker"""
        if not self.circuit_breaker_active:
            logger.info("Circuit breaker is not active")
            return

        logger.warning(
            f"Resetting circuit breaker (was triggered by: {self.circuit_breaker_reason})"
        )

        self.circuit_breaker_active = False
        self.circuit_breaker_reason = ""

        await self.signal_bus.publish(Signal(
            signal_type=SignalType.RISK_ALERT,
            priority=SignalPriority.HIGH,
            source_bot="risk_manager",
            timestamp=datetime.now(),
            ttl=300,
            data={
                'severity': 'info',
                'message': 'Circuit breaker reset - Trading resumed',
                'action': 'RESUME_TRADING'
            }
        ))

    def get_status(self) -> dict:
        """Get comprehensive status"""
        total_exposure = sum(pos.exposure_usd for pos in self.positions.values())
        unrealized_pnl = sum(pos.pnl for pos in self.positions.values())

        return {
            'circuit_breaker_active': self.circuit_breaker_active,
            'circuit_breaker_reason': self.circuit_breaker_reason,
            'positions_count': len(self.positions),
            'total_exposure_usd': float(total_exposure),
            'daily_pnl': float(self.daily_pnl),
            'total_pnl': float(self.total_pnl),
            'unrealized_pnl': float(unrealized_pnl),
            'limits': {
                'max_position_size': float(self.limits.max_position_size_usd),
                'max_total_exposure': float(self.limits.max_total_exposure_usd),
                'max_entity_exposure': float(self.limits.max_entity_exposure_usd),
                'max_daily_loss': float(self.limits.max_daily_loss_usd)
            }
        }
