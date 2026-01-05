"""
Circuit Breaker Pattern V2.0
==============================

Prevents cascading failures from external service outages.

Pattern States:
1. CLOSED: Normal operation (requests allowed)
2. OPEN: Service failing (requests blocked)
3. HALF_OPEN: Testing recovery (limited requests)

Prevents:
- Wasted API calls to failing services
- Resource exhaustion from retries
- Cascading failures across bot fleet

Use Cases:
- Polymarket API outages
- Redis connection failures
- OpenAI API timeouts
- News API rate limits

Author: ArbHunter V2.0 Upgrade
Created: 2026-01-02
"""

import asyncio
import logging
import time
from typing import Callable, Optional, Any
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Service failed, blocking requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitMetrics:
    """Circuit breaker performance metrics"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rejected_requests: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None

    @property
    def failure_rate(self) -> float:
        """Calculate failure rate (0.0 to 1.0)"""
        total = self.successful_requests + self.failed_requests
        if total == 0:
            return 0.0
        return self.failed_requests / total

    @property
    def success_rate(self) -> float:
        """Calculate success rate (0.0 to 1.0)"""
        return 1.0 - self.failure_rate


class CircuitBreaker:
    """
    Circuit breaker for protecting external service calls.

    State Transitions:
    - CLOSED → OPEN: When failure_threshold consecutive failures occur
    - OPEN → HALF_OPEN: After recovery_timeout seconds
    - HALF_OPEN → CLOSED: When success_threshold consecutive successes occur
    - HALF_OPEN → OPEN: On any failure

    Example:
    --------
    breaker = CircuitBreaker(
        name="polymarket_api",
        failure_threshold=5,
        recovery_timeout=60,
        success_threshold=2
    )

    # Protect API call
    try:
        result = await breaker.call(make_api_request)
    except CircuitBreakerOpenError:
        # Service is down, use fallback
        result = use_cached_data()
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 2,
        timeout: int = 30
    ):
        """
        Initialize circuit breaker.

        Args:
            name: Identifier for this circuit (e.g., "polymarket_api")
            failure_threshold: Consecutive failures to open circuit
            recovery_timeout: Seconds to wait before testing recovery
            success_threshold: Consecutive successes to close circuit
            timeout: Max seconds for each protected call
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.timeout = timeout

        # State
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.opened_at: Optional[datetime] = None

        # Metrics
        self.metrics = CircuitMetrics()

        logger.info(
            f"🔌 Circuit Breaker '{name}' initialized "
            f"(fail_threshold={failure_threshold}, "
            f"recovery_timeout={recovery_timeout}s)"
        )

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Async function to execute
            *args, **kwargs: Arguments to pass to func

        Returns:
            Result from func

        Raises:
            CircuitBreakerOpenError: If circuit is OPEN
            TimeoutError: If func exceeds timeout
            Exception: Original exception from func (when circuit is CLOSED/HALF_OPEN)
        """
        self.metrics.total_requests += 1

        # Check circuit state
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout elapsed
            if self.should_attempt_reset():
                logger.info(f"🔄 Circuit '{self.name}': OPEN → HALF_OPEN (testing recovery)")
                self.state = CircuitState.HALF_OPEN
            else:
                self.metrics.rejected_requests += 1
                raise CircuitBreakerOpenError(
                    f"Circuit '{self.name}' is OPEN (service unavailable)"
                )

        # Execute call with timeout
        try:
            result = await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=self.timeout
            )

            # Success
            await self.on_success()
            return result

        except asyncio.TimeoutError as e:
            logger.error(f"⏱️ Circuit '{self.name}': Timeout after {self.timeout}s")
            await self.on_failure()
            raise TimeoutError(f"Circuit '{self.name}' call timeout") from e

        except Exception as e:
            logger.error(f"❌ Circuit '{self.name}': Call failed - {e}")
            await self.on_failure()
            raise

    async def on_success(self):
        """Handle successful call"""
        self.consecutive_failures = 0
        self.consecutive_successes += 1
        self.metrics.successful_requests += 1
        self.metrics.last_success_time = datetime.now()

        if self.state == CircuitState.HALF_OPEN:
            if self.consecutive_successes >= self.success_threshold:
                logger.info(
                    f"✅ Circuit '{self.name}': HALF_OPEN → CLOSED "
                    f"({self.consecutive_successes} successes)"
                )
                self.state = CircuitState.CLOSED
                self.consecutive_successes = 0

    async def on_failure(self):
        """Handle failed call"""
        self.consecutive_successes = 0
        self.consecutive_failures += 1
        self.metrics.failed_requests += 1
        self.metrics.last_failure_time = datetime.now()

        if self.state == CircuitState.HALF_OPEN:
            # Any failure in HALF_OPEN → back to OPEN
            logger.warning(f"🔴 Circuit '{self.name}': HALF_OPEN → OPEN (recovery failed)")
            self.state = CircuitState.OPEN
            self.opened_at = datetime.now()
            self.consecutive_failures = 0

        elif self.state == CircuitState.CLOSED:
            if self.consecutive_failures >= self.failure_threshold:
                logger.error(
                    f"🔴 Circuit '{self.name}': CLOSED → OPEN "
                    f"({self.consecutive_failures} consecutive failures)"
                )
                self.state = CircuitState.OPEN
                self.opened_at = datetime.now()
                self.consecutive_failures = 0

    def should_attempt_reset(self) -> bool:
        """Check if enough time passed to attempt recovery"""
        if self.state != CircuitState.OPEN or not self.opened_at:
            return False

        elapsed = datetime.now() - self.opened_at
        return elapsed >= timedelta(seconds=self.recovery_timeout)

    def reset(self):
        """Manually reset circuit to CLOSED (use with caution)"""
        logger.info(f"🔄 Circuit '{self.name}': Manual reset to CLOSED")
        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.opened_at = None

    def get_state(self) -> str:
        """Get current circuit state"""
        return self.state.value

    def get_metrics(self) -> dict:
        """Get circuit metrics"""
        return {
            'name': self.name,
            'state': self.state.value,
            'total_requests': self.metrics.total_requests,
            'successful_requests': self.metrics.successful_requests,
            'failed_requests': self.metrics.failed_requests,
            'rejected_requests': self.metrics.rejected_requests,
            'failure_rate': self.metrics.failure_rate,
            'success_rate': self.metrics.success_rate,
            'consecutive_failures': self.consecutive_failures,
            'consecutive_successes': self.consecutive_successes,
            'opened_at': self.opened_at.isoformat() if self.opened_at else None
        }


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is OPEN and blocks request"""
    pass


class CircuitBreakerRegistry:
    """
    Global registry for circuit breakers.

    Allows sharing circuit state across multiple bot instances via Redis.
    """

    def __init__(self, redis=None):
        self.redis = redis
        self.breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 2,
        timeout: int = 30
    ) -> CircuitBreaker:
        """Get existing circuit or create new one"""
        if name not in self.breakers:
            self.breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                success_threshold=success_threshold,
                timeout=timeout
            )

        return self.breakers[name]

    async def get_all_metrics(self) -> dict:
        """Get metrics for all registered circuits"""
        return {
            name: breaker.get_metrics()
            for name, breaker in self.breakers.items()
        }

    async def save_to_redis(self):
        """Persist circuit states to Redis (for multi-bot coordination)"""
        if not self.redis:
            return

        for name, breaker in self.breakers.items():
            key = f"circuit:{name}"
            metrics = breaker.get_metrics()

            # Store as JSON
            import json
            await self.redis.set(key, json.dumps(metrics))

    async def load_from_redis(self):
        """Load circuit states from Redis"""
        if not self.redis:
            return

        import json

        for name, breaker in self.breakers.items():
            key = f"circuit:{name}"
            data = await self.redis.get(key)

            if data:
                try:
                    metrics = json.loads(data)

                    # Restore state
                    breaker.state = CircuitState(metrics['state'])
                    breaker.consecutive_failures = metrics['consecutive_failures']
                    breaker.consecutive_successes = metrics['consecutive_successes']

                    if metrics['opened_at']:
                        from dateutil import parser
                        breaker.opened_at = parser.parse(metrics['opened_at'])

                    logger.info(f"🔄 Restored circuit '{name}' from Redis (state={breaker.state.value})")

                except Exception as e:
                    logger.error(f"Failed to restore circuit '{name}': {e}")


# Global registry
_circuit_registry = None


def get_circuit_registry(redis=None) -> CircuitBreakerRegistry:
    """Get global circuit breaker registry"""
    global _circuit_registry

    if _circuit_registry is None:
        _circuit_registry = CircuitBreakerRegistry(redis)

    return _circuit_registry


# Pre-configured circuit breakers for common services
def get_polymarket_circuit(redis=None) -> CircuitBreaker:
    """Get circuit breaker for Polymarket API"""
    registry = get_circuit_registry(redis)
    return registry.get_or_create(
        name="polymarket_api",
        failure_threshold=5,
        recovery_timeout=120,  # 2 minutes
        success_threshold=3,
        timeout=30
    )


def get_openai_circuit(redis=None) -> CircuitBreaker:
    """Get circuit breaker for OpenAI API"""
    registry = get_circuit_registry(redis)
    return registry.get_or_create(
        name="openai_api",
        failure_threshold=3,
        recovery_timeout=60,  # 1 minute
        success_threshold=2,
        timeout=60  # OpenAI can be slow
    )


def get_redis_circuit(redis=None) -> CircuitBreaker:
    """Get circuit breaker for Redis"""
    registry = get_circuit_registry(redis)
    return registry.get_or_create(
        name="redis",
        failure_threshold=3,
        recovery_timeout=30,
        success_threshold=2,
        timeout=10
    )


def get_news_api_circuit(redis=None) -> CircuitBreaker:
    """Get circuit breaker for News API"""
    registry = get_circuit_registry(redis)
    return registry.get_or_create(
        name="news_api",
        failure_threshold=5,
        recovery_timeout=300,  # 5 minutes (rate limit recovery)
        success_threshold=2,
        timeout=30
    )
