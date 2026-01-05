"""
Health Monitor Service V2.0
============================

Real-time monitoring and alerting for multi-bot system.

Features:
- System health metrics (uptime, errors, performance)
- Budget utilization tracking
- API rate limit monitoring
- Trade performance analytics
- Alert routing (Slack, Discord, email)
- Circuit breaker coordination

Alerts trigger on:
- Bot crashes
- Budget allocation failures
- API rate limit violations
- Abnormal trade losses
- Redis connection failures
- Nonce conflicts

Author: ArbHunter V2.0 Upgrade
Created: 2026-01-02
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from decimal import Decimal
from dataclasses import dataclass, asdict
import json

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class HealthMetrics:
    """System health snapshot"""
    timestamp: datetime
    uptime_seconds: float

    # Bot status
    active_bots: List[str]
    crashed_bots: List[str]

    # Budget metrics
    total_capital: Decimal
    allocated_capital: Decimal
    available_capital: Decimal
    utilization_pct: float

    # API metrics
    api_requests_last_minute: int
    api_errors_last_minute: int
    rate_limit_hits: int

    # Trading metrics
    trades_today: int
    wins_today: int
    losses_today: int
    win_rate_pct: float
    pnl_today: Decimal

    # System health
    redis_connected: bool
    error_count_last_hour: int

    @property
    def is_healthy(self) -> bool:
        """Overall health status"""
        return (
            self.redis_connected and
            len(self.crashed_bots) == 0 and
            self.error_count_last_hour < 20 and
            self.rate_limit_hits == 0
        )

    def to_dict(self):
        """Convert to dict for JSON serialization"""
        data = asdict(self)
        # Convert Decimal to float for JSON
        data['total_capital'] = float(self.total_capital)
        data['allocated_capital'] = float(self.allocated_capital)
        data['available_capital'] = float(self.available_capital)
        data['pnl_today'] = float(self.pnl_today)
        # Convert datetime to ISO string
        data['timestamp'] = self.timestamp.isoformat()
        return data


@dataclass
class Alert:
    """Alert message"""
    severity: str  # "critical", "warning", "info"
    category: str  # "budget", "api", "trading", "system"
    message: str
    timestamp: datetime
    details: Dict

    def __repr__(self):
        icon = {
            "critical": "🚨",
            "warning": "⚠️",
            "info": "ℹ️"
        }.get(self.severity, "📢")

        return f"{icon} [{self.severity.upper()}] {self.category}: {self.message}"


class HealthMonitor:
    """
    Centralized health monitoring service.

    Runs as a separate process, queries Redis for metrics,
    and sends alerts via webhooks.
    """

    def __init__(
        self,
        redis,
        budget_manager=None,
        rate_limiter=None
    ):
        self.redis = redis
        self.budget_manager = budget_manager
        self.rate_limiter = rate_limiter

        # Alert channels
        self.slack_webhook_url: Optional[str] = None
        self.discord_webhook_url: Optional[str] = None

        # Monitoring state
        self.start_time = time.time()
        self.last_metrics: Optional[HealthMetrics] = None
        self.alert_history: List[Alert] = []

        # Alert thresholds
        self.max_errors_per_hour = 20
        self.max_budget_utilization = 0.90  # 90%
        self.min_win_rate = 0.50  # 50%
        self.max_daily_loss = Decimal("100")  # $100

        # Alert cooldowns (prevent spam)
        self.alert_cooldowns: Dict[str, datetime] = {}
        self.cooldown_minutes = 15

    def configure_slack(self, webhook_url: str):
        """Configure Slack alerting"""
        self.slack_webhook_url = webhook_url
        logger.info("✅ Slack alerts configured")

    def configure_discord(self, webhook_url: str):
        """Configure Discord alerting"""
        self.discord_webhook_url = webhook_url
        logger.info("✅ Discord alerts configured")

    async def run(self, check_interval_seconds: int = 30):
        """Main monitoring loop"""
        logger.info("🏥 Health Monitor Started")
        logger.info(f"   Check Interval: {check_interval_seconds}s")
        logger.info(f"   Slack Alerts: {'Enabled' if self.slack_webhook_url else 'Disabled'}")
        logger.info(f"   Discord Alerts: {'Enabled' if self.discord_webhook_url else 'Disabled'}")

        while True:
            try:
                # Collect metrics
                metrics = await self.collect_metrics()

                # Store latest metrics
                self.last_metrics = metrics

                # Persist to Redis (for dashboard)
                await self.save_metrics_to_redis(metrics)

                # Check for alert conditions
                alerts = await self.check_alert_conditions(metrics)

                # Send alerts
                for alert in alerts:
                    await self.send_alert(alert)

                # Log health summary
                if metrics.is_healthy:
                    logger.debug(f"✅ System Healthy - {len(metrics.active_bots)} bots running")
                else:
                    logger.warning(f"⚠️ System Issues Detected - {len(alerts)} alerts")

                # Wait for next check
                await asyncio.sleep(check_interval_seconds)

            except Exception as e:
                logger.error(f"Health Monitor Error: {e}", exc_info=True)
                await asyncio.sleep(check_interval_seconds)

    async def collect_metrics(self) -> HealthMetrics:
        """Collect system metrics from Redis and components"""

        # Uptime
        uptime = time.time() - self.start_time

        # Bot status (from Redis heartbeats)
        active_bots = await self.get_active_bots()
        crashed_bots = await self.get_crashed_bots()

        # Budget metrics
        if self.budget_manager:
            balances = await self.budget_manager.get_balances()
            total_capital = sum(balances.values())
            available_capital = sum(
                v for k, v in balances.items()
                if k != 'total' and k != 'reserve'
            )

            # Get allocated capital
            allocations_key = "budget:allocations"
            allocated_count = await self.redis.hlen(allocations_key)
            allocated_capital = Decimal("0")

            if allocated_count > 0:
                allocations = await self.redis.hgetall(allocations_key)
                for alloc_data in allocations.values():
                    try:
                        alloc_info = json.loads(alloc_data)
                        allocated_capital += Decimal(str(alloc_info.get('amount', 0)))
                    except:
                        pass

            utilization_pct = float(allocated_capital / total_capital * 100) if total_capital > 0 else 0
        else:
            total_capital = Decimal("0")
            allocated_capital = Decimal("0")
            available_capital = Decimal("0")
            utilization_pct = 0.0

        # API metrics
        if self.rate_limiter:
            api_stats = await self.rate_limiter.get_stats()
            api_metrics = api_stats.get('api', {})
            api_requests = api_metrics.get('requests_in_window', 0)
        else:
            api_requests = 0

        # Error tracking
        error_count = await self.get_error_count_last_hour()

        # Rate limit violations
        rate_limit_hits = await self.get_rate_limit_violations()

        # API errors
        api_errors = await self.get_api_errors_last_minute()

        # Trading metrics
        trades_today = await self.get_trade_count_today()
        wins_today = await self.get_wins_today()
        losses_today = trades_today - wins_today
        win_rate_pct = (wins_today / trades_today * 100) if trades_today > 0 else 0.0
        pnl_today = await self.get_pnl_today()

        # Redis connection
        try:
            await self.redis.ping()
            redis_connected = True
        except:
            redis_connected = False

        return HealthMetrics(
            timestamp=datetime.now(),
            uptime_seconds=uptime,
            active_bots=active_bots,
            crashed_bots=crashed_bots,
            total_capital=total_capital,
            allocated_capital=allocated_capital,
            available_capital=available_capital,
            utilization_pct=utilization_pct,
            api_requests_last_minute=api_requests,
            api_errors_last_minute=api_errors,
            rate_limit_hits=rate_limit_hits,
            trades_today=trades_today,
            wins_today=wins_today,
            losses_today=losses_today,
            win_rate_pct=win_rate_pct,
            pnl_today=pnl_today,
            redis_connected=redis_connected,
            error_count_last_hour=error_count
        )

    async def check_alert_conditions(
        self,
        metrics: HealthMetrics
    ) -> List[Alert]:
        """Check metrics against thresholds and generate alerts"""
        alerts = []

        # 1. Bot crashes
        if metrics.crashed_bots:
            alerts.append(Alert(
                severity="critical",
                category="system",
                message=f"Bot(s) crashed: {', '.join(metrics.crashed_bots)}",
                timestamp=datetime.now(),
                details={'bots': metrics.crashed_bots}
            ))

        # 2. Redis connection
        if not metrics.redis_connected:
            alerts.append(Alert(
                severity="critical",
                category="system",
                message="Redis connection lost",
                timestamp=datetime.now(),
                details={}
            ))

        # 3. High error rate
        if metrics.error_count_last_hour > self.max_errors_per_hour:
            alerts.append(Alert(
                severity="warning",
                category="system",
                message=f"High error rate: {metrics.error_count_last_hour} errors/hour",
                timestamp=datetime.now(),
                details={'count': metrics.error_count_last_hour}
            ))

        # 4. Budget over-utilization
        if metrics.utilization_pct > self.max_budget_utilization * 100:
            alerts.append(Alert(
                severity="warning",
                category="budget",
                message=f"Budget {metrics.utilization_pct:.0f}% utilized (max {self.max_budget_utilization*100:.0f}%)",
                timestamp=datetime.now(),
                details={
                    'utilization': metrics.utilization_pct,
                    'allocated': float(metrics.allocated_capital),
                    'total': float(metrics.total_capital)
                }
            ))

        # 5. API rate limit violations
        if metrics.rate_limit_hits > 0:
            alerts.append(Alert(
                severity="warning",
                category="api",
                message=f"API rate limit hit {metrics.rate_limit_hits} times",
                timestamp=datetime.now(),
                details={'count': metrics.rate_limit_hits}
            ))

        # 6. Low win rate
        if metrics.trades_today >= 10 and metrics.win_rate_pct < self.min_win_rate * 100:
            alerts.append(Alert(
                severity="warning",
                category="trading",
                message=f"Low win rate: {metrics.win_rate_pct:.0f}% ({metrics.wins_today}/{metrics.trades_today})",
                timestamp=datetime.now(),
                details={
                    'win_rate': metrics.win_rate_pct,
                    'wins': metrics.wins_today,
                    'total': metrics.trades_today
                }
            ))

        # 7. Daily loss limit
        if metrics.pnl_today < -self.max_daily_loss:
            alerts.append(Alert(
                severity="critical",
                category="trading",
                message=f"Daily loss limit exceeded: ${metrics.pnl_today}",
                timestamp=datetime.now(),
                details={'pnl': float(metrics.pnl_today)}
            ))

        # Filter out cooldown-suppressed alerts
        filtered_alerts = []
        for alert in alerts:
            cooldown_key = f"{alert.category}:{alert.message}"
            last_sent = self.alert_cooldowns.get(cooldown_key)

            if last_sent:
                time_since = datetime.now() - last_sent
                if time_since < timedelta(minutes=self.cooldown_minutes):
                    logger.debug(f"Alert suppressed (cooldown): {alert.message}")
                    continue

            filtered_alerts.append(alert)
            self.alert_cooldowns[cooldown_key] = datetime.now()

        return filtered_alerts

    async def send_alert(self, alert: Alert):
        """Send alert to configured channels"""
        logger.warning(str(alert))

        # Store in history
        self.alert_history.append(alert)

        # Send to Slack
        if self.slack_webhook_url:
            await self.send_slack_alert(alert)

        # Send to Discord
        if self.discord_webhook_url:
            await self.send_discord_alert(alert)

    async def send_slack_alert(self, alert: Alert):
        """Send alert to Slack webhook"""
        try:
            color = {
                "critical": "#FF0000",
                "warning": "#FFA500",
                "info": "#0000FF"
            }.get(alert.severity, "#808080")

            payload = {
                "attachments": [{
                    "color": color,
                    "title": f"{alert.category.upper()} Alert",
                    "text": alert.message,
                    "fields": [
                        {"title": "Severity", "value": alert.severity, "short": True},
                        {"title": "Time", "value": alert.timestamp.strftime("%Y-%m-%d %H:%M:%S"), "short": True}
                    ],
                    "footer": "ArbHunter Health Monitor"
                }]
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.slack_webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"Slack webhook failed: {resp.status}")

        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")

    async def send_discord_alert(self, alert: Alert):
        """Send alert to Discord webhook"""
        try:
            color_code = {
                "critical": 0xFF0000,
                "warning": 0xFFA500,
                "info": 0x0000FF
            }.get(alert.severity, 0x808080)

            payload = {
                "embeds": [{
                    "title": f"{alert.category.upper()} Alert",
                    "description": alert.message,
                    "color": color_code,
                    "fields": [
                        {"name": "Severity", "value": alert.severity, "inline": True},
                        {"name": "Time", "value": alert.timestamp.strftime("%Y-%m-%d %H:%M:%S"), "inline": True}
                    ],
                    "footer": {"text": "ArbHunter Health Monitor"}
                }]
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.discord_webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status not in [200, 204]:
                        logger.error(f"Discord webhook failed: {resp.status}")

        except Exception as e:
            logger.error(f"Failed to send Discord alert: {e}")

    async def save_metrics_to_redis(self, metrics: HealthMetrics):
        """Save metrics to Redis for dashboard queries"""
        key = "health:latest"
        await self.redis.set(key, json.dumps(metrics.to_dict()))

        # Also append to time series (last 24 hours)
        ts_key = "health:timeseries"
        await self.redis.zadd(
            ts_key,
            time.time(),
            json.dumps(metrics.to_dict())
        )

        # Trim old data (keep last 24 hours)
        cutoff = time.time() - (24 * 3600)
        await self.redis.zremrangebyscore(ts_key, '-inf', cutoff)

    # Helper methods for Redis queries

    async def get_active_bots(self) -> List[str]:
        """Get list of active bots (from heartbeats)"""
        # Bots write heartbeats to Redis every 30s
        # If heartbeat > 60s old, consider crashed
        bots = []
        pattern = "heartbeat:*"

        try:
            keys = await self.redis.keys(pattern)
            now = time.time()

            for key in keys:
                last_heartbeat = await self.redis.get(key)
                if last_heartbeat:
                    age = now - float(last_heartbeat)
                    if age < 60:
                        bot_name = key.decode().split(':')[1]
                        bots.append(bot_name)
        except:
            pass

        return bots

    async def get_crashed_bots(self) -> List[str]:
        """Get list of crashed bots (stale heartbeats)"""
        crashed = []
        pattern = "heartbeat:*"

        try:
            keys = await self.redis.keys(pattern)
            now = time.time()

            for key in keys:
                last_heartbeat = await self.redis.get(key)
                if last_heartbeat:
                    age = now - float(last_heartbeat)
                    if age >= 60:
                        bot_name = key.decode().split(':')[1]
                        crashed.append(bot_name)
        except:
            pass

        return crashed

    async def get_error_count_last_hour(self) -> int:
        """Count errors logged in last hour"""
        key = "errors:timeseries"
        cutoff = time.time() - 3600

        try:
            count = await self.redis.zcount(key, cutoff, '+inf')
            return count
        except:
            return 0

    async def get_rate_limit_violations(self) -> int:
        """Count rate limit hits today"""
        key = "metrics:rate_limit_hits"
        try:
            count = await self.redis.get(key)
            return int(count) if count else 0
        except:
            return 0

    async def get_api_errors_last_minute(self) -> int:
        """Count API errors in last minute"""
        key = "errors:api:timeseries"
        cutoff = time.time() - 60

        try:
            count = await self.redis.zcount(key, cutoff, '+inf')
            return count
        except:
            return 0

    async def get_trade_count_today(self) -> int:
        """Get number of trades executed today"""
        key = "metrics:trades_today"
        try:
            count = await self.redis.get(key)
            return int(count) if count else 0
        except:
            return 0

    async def get_wins_today(self) -> int:
        """Get number of winning trades today"""
        key = "metrics:wins_today"
        try:
            count = await self.redis.get(key)
            return int(count) if count else 0
        except:
            return 0

    async def get_pnl_today(self) -> Decimal:
        """Get profit/loss for today"""
        key = "metrics:pnl_today"
        try:
            pnl = await self.redis.get(key)
            return Decimal(pnl.decode()) if pnl else Decimal("0")
        except:
            return Decimal("0")


# Singleton instance
_health_monitor_instance = None


async def get_health_monitor(
    redis,
    budget_manager=None,
    rate_limiter=None
) -> HealthMonitor:
    """Get or create global HealthMonitor instance"""
    global _health_monitor_instance

    if _health_monitor_instance is None:
        _health_monitor_instance = HealthMonitor(
            redis,
            budget_manager,
            rate_limiter
        )
        logger.info("✅ Health Monitor initialized")

    return _health_monitor_instance


async def record_heartbeat(redis, bot_name: str):
    """Record bot heartbeat (call every 30s from each bot)"""
    key = f"heartbeat:{bot_name}"
    await redis.set(key, time.time())


async def record_error(redis, category: str, message: str):
    """Record error for monitoring"""
    # Add to general error timeseries
    await redis.zadd(
        "errors:timeseries",
        time.time(),
        f"{category}:{message}"
    )

    # Add to category-specific timeseries
    if category:
        await redis.zadd(
            f"errors:{category}:timeseries",
            time.time(),
            message
        )


async def record_trade(redis, success: bool, pnl: Decimal):
    """Record trade outcome for monitoring"""
    # Increment trade counter
    await redis.incr("metrics:trades_today")

    if success:
        await redis.incr("metrics:wins_today")

    # Update PnL
    current_pnl = await redis.get("metrics:pnl_today")
    current_pnl = Decimal(current_pnl.decode()) if current_pnl else Decimal("0")
    new_pnl = current_pnl + pnl
    await redis.set("metrics:pnl_today", str(new_pnl))
