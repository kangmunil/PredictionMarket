import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict
from src.core.clob_client import PolyClient
from src.core.wallet_watcher_v2 import EnhancedWalletWatcher as WalletWatcher
from src.strategies.arbitrage import ArbitrageStrategy
from src.strategies.stat_arb import StatArbStrategy
# from src.strategies.ai_model import AIModelStrategy # Deprecated
from src.news.news_scalper_optimized import OptimizedNewsScalper
from src.core.config import Config

logger = logging.getLogger(__name__)

class EliteMimicAgent:
    """
    The Ultimate Shadow Trader: EliteMimic Agent.
    Integrated with Optimized News Scalper for Dual-Trigger Trading.
    """
    def __init__(self, client: PolyClient, signal_bus=None, budget_manager=None):
        self.config = Config()
        self.client = client
        self.signal_bus = signal_bus
        self.budget_manager = budget_manager
        self._signal_history: Dict[str, datetime] = {}
        self._signal_cooldown = timedelta(
            minutes=float(getattr(self.config, "MIMIC_SIGNAL_COOLDOWN_MINUTES", 10) or 10)
        )
        self._min_signal_score = float(getattr(self.config, "MIMIC_MIN_SIGNAL_SCORE", 0.50) or 0.50)
        self._max_position_usd = float(getattr(self.config, "MIMIC_MAX_POSITION_USD", 2.0) or 2.0)
        self._signal_poll_interval = int(getattr(self.config, "MIMIC_SIGNAL_POLL_SECONDS", 30) or 30)
        
        # 1. Initialize the Super Brain
        # If signal_bus is provided (Swarm Mode), we don't need a separate NewsScalper instance
        if self.signal_bus:
            logger.info("🧠 EliteMimic connected to SignalBus (Hive Mind)")
            self.news_brain = None
        else:
            # Standalone Mode
            self.news_brain = OptimizedNewsScalper(
                news_api_key=self.config.NEWS_API_KEY,
                tree_news_api_key=self.config.TREE_NEWS_API_KEY,
                clob_client=client,
                dry_run=True 
            )
        
        # 2. Initialize Watchers & Strategies
        # Pass signal_bus to WalletWatcher for advanced validation
        self.wallet_watcher = WalletWatcher(
            client, 
            agent=self,
            config=self.config
        )
        
        self.mimic_logs: List[Dict] = []

    async def run(self):
        logger.info("🌑 EliteMimic Agent: '나는 고수들의 그림자를 따라가는 그림자 트레이더입니다.'")
        logger.info("🔥 System Upgrade: Integrating FinBERT & Tree News Scalper.")
        
        # Keywords to monitor for News Scalper
        monitor_keywords = ["bitcoin", "ethereum", "trump", "crypto", "polymarket"]
        
        # Run components concurrently
        tasks = [
            asyncio.create_task(self.wallet_watcher.run())
        ]
        
        # Only run local brain if not in swarm mode
        if self.news_brain:
             tasks.append(asyncio.create_task(self.news_brain.run(keywords=monitor_keywords)))
        elif self.signal_bus:
            logger.info("🔁 EliteMimic: enabling SignalBus mirror mode")
            tasks.append(asyncio.create_task(self._run_signal_bridge(), name="EliteMimicSignalBridge"))
        
        logger.info("✅ All systems GO. Monitoring Shadows (Whales) and Light (News).")
        
        try:
            while True:
                await asyncio.sleep(60)
                self.report_status()
        except asyncio.CancelledError:
            logger.info("Agent shutting down...")
        finally:
            for task in tasks:
                task.cancel()

    def report_status(self):
        """
        Outputs the summary of activities.
        """
        logger.info("--- EliteMimic Agent Status Report ---")
        if not self.mimic_logs:
            logger.info("No mimic trades executed yet.")
        else:
            for entry in self.mimic_logs:
                print(f"[MIMIC] Wallet: {entry['trader']} | Details: {entry['details']} | Result: {entry['ai_result']} | Status: {entry['status']}")
        
        # Also print News Scalper stats
        if self.news_brain:
            self.news_brain._print_stats()

    def add_log(self, trader_id, tx_details, ai_result, recommendation):
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
        """
        Dry-run activation path: mirror high-confidence SignalBus alerts
        when no whale fills arrive.
        """
        logger.info("🤝 EliteMimic: SignalBus bridge online (mirroring hot tokens)")
        while True:
            try:
                hot = await self.signal_bus.get_hot_tokens(min_sentiment=self._min_signal_score)
                logger.debug(f"EliteMimic bridge scanning {len(hot)} hot tokens (threshold {self._min_signal_score:.2f})")
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
        """
        Convert aggregated signal into a lightweight mimic trade/log.
        """
        side = "BUY" if signal.sentiment_score >= 0 else "SELL"
        intensity = abs(signal.sentiment_score)
        size = round(self._max_position_usd * min(1.0, intensity), 2)

        # Budget guard (best effort)
        allocation_id = None
        if self.budget_manager:
            allocation_id = await self.budget_manager.request_allocation(
                "elitemimic",
                Decimal(str(size)),
                priority="normal"
            )
            if not allocation_id:
                logger.info("EliteMimic: budget denied, skipping signal mirror")
                return

        details = f"SignalBus mirror {side} {token_id[:12]} size ${size:.2f}"
        self.add_log(
            trader_id=signal.token_id if hasattr(signal, "token_id") else token_id,
            tx_details=details,
            ai_result=f"Sentiment {signal.sentiment_score:+.2f}",
            recommendation="COPY" if intensity >= self._min_signal_score else "WATCH"
        )
        self.wallet_watcher.trades_executed += 1

        if allocation_id:
            await self.budget_manager.release_allocation("elitemimic", allocation_id, Decimal("0"))
