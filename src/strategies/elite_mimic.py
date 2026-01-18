import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Optional
from src.core.clob_client import PolyClient
from src.core.wallet_watcher_v2 import EnhancedWalletWatcher as WalletWatcher
from src.news.news_scalper_optimized import OptimizedNewsScalper
from src.core.config import Config

logger = logging.getLogger(__name__)


class EliteMimicAgent:
    """
    The Ultimate Shadow Trader: EliteMimic Agent.
    Integrated with Optimized News Scalper for Dual-Trigger Trading.
    """

    def __init__(self, client: PolyClient, signal_bus=None, budget_manager=None, swarm_system=None):
        self.config = Config()
        self.client = client
        self.signal_bus = signal_bus
        self.budget_manager = budget_manager
        self.swarm_system = swarm_system  # Link to central system for notifications

        self._signal_history: Dict[str, datetime] = {}
        self._signal_cooldown = timedelta(
            minutes=float(getattr(self.config, "MIMIC_SIGNAL_COOLDOWN_MINUTES", 10) or 10)
        )
        self._min_signal_score = float(getattr(self.config, "MIMIC_MIN_SIGNAL_SCORE", 0.50) or 0.50)
        self._max_position_usd = getattr(self.config, "MAX_POSITION_SIZE", 10.0)
        self._signal_poll_interval = int(getattr(self.config, "MIMIC_SIGNAL_POLL_SECONDS", 30) or 30)

        # Initialize the Super Brain
        if self.signal_bus:
            logger.info("🧠 EliteMimic connected to SignalBus (Hive Mind)")
            self.news_brain = None
        else:
            self.news_brain = OptimizedNewsScalper(
                news_api_key=self.config.NEWS_API_KEY,
                tree_news_api_key=self.config.TREE_NEWS_API_KEY,
                clob_client=client,
                dry_run=True
            )

        # Initialize Watchers
        self.wallet_watcher = WalletWatcher(client, agent=self, config=self.config)
        self.mimic_logs: List[Dict] = []

    async def run(self):
        """Main run loop for EliteMimic agent."""
        logger.info("🌑 EliteMimic Agent Started")

        tasks = [
            asyncio.create_task(self.wallet_watcher.run(), name="WalletWatcher"),
            asyncio.create_task(self._status_loop(), name="MimicStatusLoop")
        ]

        if self.news_brain:
            monitor_keywords = ["bitcoin", "ethereum", "trump", "crypto", "polymarket"]
            tasks.append(asyncio.create_task(self.news_brain.run(keywords=monitor_keywords), name="NewsBrain"))
        elif self.signal_bus:
            logger.info("🔁 EliteMimic: enabling SignalBus mirror mode")
            tasks.append(asyncio.create_task(self._run_signal_bridge(), name="EliteMimicSignalBridge"))

        logger.info("✅ EliteMimic: All systems GO.")

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            logger.info("EliteMimic shutting down...")
        except Exception as e:
            logger.error(f"EliteMimic crash: {e}", exc_info=True)
        finally:
            for task in tasks:
                task.cancel()

    async def _status_loop(self):
        """Periodic status reporting."""
        while True:
            await asyncio.sleep(60)
            self.report_status()

    def report_status(self):
        """Outputs the summary of activities."""
        logger.info("--- EliteMimic Agent Status Report ---")
        if not self.mimic_logs:
            logger.info("No mimic trades executed yet.")
        else:
            for entry in self.mimic_logs:
                logger.info(f"[MIMIC] {entry['details']} | {entry['status']}")

        if self.news_brain:
            self.news_brain._print_stats()

    def add_log(self, trader_id, tx_details, ai_result, recommendation):
        """Add a log entry for a mimic trade."""
        entry = {
            "trader": trader_id,
            "details": tx_details,
            "ai_result": ai_result,
            "recommendation": recommendation,
            "status": "EXECUTED" if "COPY" in recommendation else "SKIPPED"
        }
        self.mimic_logs.append(entry)
        logger.info(f"📝 New Mimic Log: {entry}")

    async def _run_signal_bridge(self):
        """Mirror high-confidence SignalBus alerts."""
        logger.info("🤝 EliteMimic: SignalBus bridge online")
        while True:
            try:
                hot = await self.signal_bus.get_hot_tokens(min_sentiment=self._min_signal_score)
                now = datetime.now()
                for token_id, sig in hot.items():
                    last = self._signal_history.get(token_id)
                    if last and (now - last) < self._signal_cooldown:
                        continue
                    await self._mirror_signal(token_id, sig)
                    self._signal_history[token_id] = now
                await asyncio.sleep(self._signal_poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"EliteMimic bridge error: {exc}", exc_info=True)
                await asyncio.sleep(5)

    async def _mirror_signal(self, token_id, signal):
        """Convert aggregated signal into a lightweight mimic trade/log."""
        side = "BUY" if signal.sentiment_score >= 0 else "SELL"
        intensity = abs(signal.sentiment_score)

        # Dynamic Risk Sizing
        portfolio_balance = 0.0
        try:
            balance_str = await self.client.get_usdc_balance()
            if balance_str:
                portfolio_balance = float(balance_str)
        except Exception:
            pass

        risk_pct = getattr(self.config, "RISK_PER_TRADE_PERCENT", 0.02)

        # Micro-Cap Optimization Logic
        dynamic_cap = portfolio_balance * risk_pct
        floor_size = 5.0

        if dynamic_cap < floor_size:
            if portfolio_balance * 0.20 >= floor_size:
                target_cap = floor_size
            else:
                target_cap = max(1.0, portfolio_balance * 0.10)
        else:
            target_cap = dynamic_cap

        target_cap = min(target_cap, self._max_position_usd)

        size = round(target_cap * min(1.0, intensity), 2)
        if size < 5.0:
            logger.debug(f"EliteMimic: Size ${size} below $5 minimum, skipping")
            return  # Skip below Polymarket minimum

        # Budget guard
        allocation_id = None
        if self.budget_manager:
            allocation_id = await self.budget_manager.request_allocation(
                "elitemimic",
                Decimal(str(size)),
                priority="normal"
            )
            if not allocation_id:
                logger.debug("EliteMimic: budget denied")
                return

        details = f"Mirror {side} {token_id[:10]}... ${size:.2f} (Score {signal.sentiment_score:.2f})"

        # 🔥 ACTUALLY EXECUTE THE TRADE (Not just log!)
        order_result = None
        actual_spent = Decimal("0")
        dry_run = getattr(self.config, "DRY_RUN", True)
        
        if not dry_run:
            try:
                logger.info(f"🚀 EliteMimic LIVE ORDER: {side} {size} shares of {token_id[:12]}...")
                order_result = await self.client.place_market_order(token_id, side, size)
                if order_result:
                    actual_spent = Decimal(str(size))
                    logger.info(f"✅ EliteMimic Order Filled: {order_result}")
                else:
                    logger.warning(f"⚠️ EliteMimic Order Failed for {token_id[:12]}")
            except Exception as e:
                logger.error(f"❌ EliteMimic Order Error: {e}", exc_info=True)
        else:
            logger.info(f"📝 [DRY RUN] EliteMimic would {side} ${size:.2f} of {token_id[:12]}")

        self.add_log(
            trader_id=token_id,
            tx_details=details,
            ai_result=f"Score {signal.sentiment_score}",
            recommendation="COPY" if order_result or dry_run else "FAILED"
        )
        self.wallet_watcher.trades_executed += 1

        # Report to Swarm Orchestrator (Trigger Telegram)
        if self.swarm_system:
            self.swarm_system.add_trade_record(
                side, token_id, 0.0, size,
                condition_id="",
                brain_score=intensity
            )

        if allocation_id:
            await self.budget_manager.release_allocation("elitemimic", allocation_id, actual_spent)

    async def shutdown(self):
        """Gracefully close internal components"""
        logger.info("🎬 Shutting down EliteMimicAgent...")
        try:
            if hasattr(self, 'wallet_watcher') and self.wallet_watcher:
                await self.wallet_watcher.shutdown()
            
            # If news_brain exists and has a shutdown, call it
            if hasattr(self, 'news_brain') and self.news_brain and hasattr(self.news_brain, 'shutdown'):
                await self.news_brain.shutdown()
                
            logger.info("✅ EliteMimicAgent resources closed")
        except Exception as e:
            logger.error(f"Error during EliteMimicAgent shutdown: {e}")

