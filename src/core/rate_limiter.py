"""
API Rate Limiter - Global Request Throttling
=============================================

Prevents Polymarket API rate limit violations across 3 concurrent bots.

Polymarket Rate Limits:
- REST API: 100 requests per 10 seconds
- Order Creation: 10 orders per second

Uses Redis Token Bucket algorithm for distributed rate limiting.

Author: ArbHunter V2.0 Upgrade
Created: 2026-01-02
"""

import asyncio
import time
import logging
from collections import deque

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token Bucket algorithm-based rate limiter using Redis.

    Shared across all bots to prevent collective API abuse.

    Example Usage:
    --------------
    rate_limiter = RateLimiter(redis, max_requests=100, window_seconds=10)

    # Before making API call
    if await rate_limiter.acquire("get_orderbook"):
        result = await api_call()
    else:
        # Wait and retry
        await rate_limiter.acquire_with_wait("get_orderbook")
        result = await api_call()
    """

    def __init__(
        self,
        redis,
        max_requests: int = 100,
        window_seconds: int = 10
    ):
        self.redis = redis
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.key = "rate_limiter:polymarket_api"

    async def acquire(self, endpoint: str = "default") -> bool:
        """
        Acquire permission to make API request.

        Uses Redis sorted set to track requests within sliding window.

        Args:
            endpoint: API endpoint name (for debugging)

        Returns:
            True: Permission granted
            False: Rate limited (wait required)
        """
        now = time.time()
        window_start = now - self.window_seconds

        # Clean old requests outside window
        await self.redis.zremrangebyscore(
            self.key,
            '-inf',
            window_start
        )

        # Count requests in current window
        request_count = await self.redis.zcard(self.key)

        if request_count >= self.max_requests:
            # Rate limited
            oldest = await self.redis.zrange(self.key, 0, 0, withscores=True)
            if oldest:
                retry_after = oldest[0][1] + self.window_seconds - now
                logger.warning(
                    f"⚠️ API Rate Limit reached ({request_count}/{self.max_requests}). "
                    f"Retry in {retry_after:.1f}s"
                )
            return False

        # Add current request to window
        request_id = f"{now}:{endpoint}"
        await self.redis.zadd(self.key, {request_id: now})

        return True

    async def acquire_with_wait(
        self,
        endpoint: str = "default",
        max_wait: int = 30
    ) -> bool:
        """
        Acquire with automatic retry until success or timeout.

        Args:
            endpoint: API endpoint name
            max_wait: Maximum wait time in seconds

        Returns:
            True: Acquired successfully
            False: Timeout exceeded

        Raises:
            TimeoutError: If max_wait exceeded
        """
        start = time.time()

        while time.time() - start < max_wait:
            if await self.acquire(endpoint):
                return True

            # Exponential backoff (max 5s)
            elapsed = time.time() - start
            backoff = min(2 ** (elapsed / 5), 5)
            await asyncio.sleep(backoff)

        raise TimeoutError(
            f"Rate limiter timeout after {max_wait}s for {endpoint}"
        )

    async def get_current_rate(self) -> dict:
        """
        Get current request rate statistics.

        Returns:
            dict: {
                'requests_in_window': int,
                'max_requests': int,
                'utilization': float (0-1),
                'requests_per_second': float
            }
        """
        now = time.time()
        window_start = now - self.window_seconds

        # Clean old requests
        await self.redis.zremrangebyscore(
            self.key,
            '-inf',
            window_start
        )

        # Count current requests
        request_count = await self.redis.zcard(self.key)

        # Calculate utilization
        utilization = request_count / self.max_requests if self.max_requests > 0 else 0

        # Calculate requests per second
        requests_per_second = request_count / self.window_seconds if self.window_seconds > 0 else 0

        return {
            'requests_in_window': request_count,
            'max_requests': self.max_requests,
            'utilization': utilization,
            'requests_per_second': requests_per_second,
            'window_seconds': self.window_seconds
        }

    async def reset(self):
        """Reset rate limiter (clear all tracked requests)"""
        await self.redis.delete(self.key)
        logger.info("🔄 Rate limiter reset")


class MultiEndpointRateLimiter:
    """
    Manages multiple rate limiters for different endpoints.

    Polymarket has different limits for:
    - General API (100 req/10s)
    - Order creation (10 req/s)
    - Order cancellation (20 req/s)
    """

    def __init__(self, redis):
        self.redis = redis

        self.limiters = {
            'api': RateLimiter(redis, max_requests=100, window_seconds=10),
            'order_create': RateLimiter(redis, max_requests=10, window_seconds=1),
            'order_cancel': RateLimiter(redis, max_requests=20, window_seconds=1),
        }

    async def acquire(self, endpoint_type: str = 'api', endpoint_name: str = 'default'):
        """
        Acquire permission for specific endpoint type.

        Args:
            endpoint_type: 'api', 'order_create', or 'order_cancel'
            endpoint_name: Specific endpoint name (for logging)
        """
        limiter = self.limiters.get(endpoint_type, self.limiters['api'])
        return await limiter.acquire(endpoint_name)

    async def acquire_with_wait(
        self,
        endpoint_type: str = 'api',
        endpoint_name: str = 'default',
        max_wait: int = 30
    ):
        """Acquire with automatic wait"""
        limiter = self.limiters.get(endpoint_type, self.limiters['api'])
        return await limiter.acquire_with_wait(endpoint_name, max_wait)

    async def get_stats(self) -> dict:
        """Get stats for all rate limiters"""
        stats = {}
        for name, limiter in self.limiters.items():
            stats[name] = await limiter.get_current_rate()
        return stats


# Singleton instance
_rate_limiter_instance = None


async def get_rate_limiter(redis) -> MultiEndpointRateLimiter:
    """Get or create global RateLimiter instance"""
    global _rate_limiter_instance

    if _rate_limiter_instance is None:
        _rate_limiter_instance = MultiEndpointRateLimiter(redis)
        logger.info("✅ Global Rate Limiter initialized")

    return _rate_limiter_instance
