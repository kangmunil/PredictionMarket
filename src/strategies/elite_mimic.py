import asyncio
import logging
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
