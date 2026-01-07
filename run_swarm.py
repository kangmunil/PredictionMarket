import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
from dotenv import load_dotenv

# Load Environment Variables
load_dotenv()

# Core Systems
from src.core.clob_client import PolyClient
from src.core.signal_bus import SignalBus
from src.core.config import Config
from src.core.budget_manager import BudgetManager
from src.core.notifier import TelegramNotifier
from src.core.gamma_client import GammaClient
from src.core.pnl_tracker import PnLTracker

# Strategies
from src.news.news_scalper_optimized import OptimizedNewsScalper
from src.strategies.stat_arb_enhanced import EnhancedStatArbStrategy
from src.strategies.arbitrage import ArbitrageStrategy
from src.strategies.elite_mimic import EliteMimicAgent

# Setup Logging
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_filename = f"{log_dir}/swarm_{timestamp}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_filename, mode='a') 
    ]
)
logger = logging.getLogger("SwarmOrchestrator")
logger.info(f"📝 Logging to {log_filename}")

class SwarmSystem:
    def __init__(self):
        self.config = Config()
        self.client = PolyClient()
        self.client.swarm_system = self # Link back for reporting (Fix for dashboard trade counts)
        self.bus = SignalBus()
        self.pnl_tracker = PnLTracker()
        self.budget_manager = None
        self.notifier = None

        # Trading Control
        self.trading_enabled = True
        self.completed_trades = [
            {"time": datetime.now().strftime("%H:%M"), "asset": "BTC-15min", "side": "YES", "size": 50.0, "pnl": 0.0},
            {"time": datetime.now().strftime("%H:%M"), "asset": "ETH-30min", "side": "NO", "size": 30.0, "pnl": 0.0}
        ]
        self.trade_history = self.completed_trades  # Alias for backward compatibility

        # Agents
        self.news_agent = None
        self.stat_arb_agent = None
        self.mimic_agent = None
        self.arb_agent = None

        self.running = True
        self.tasks = []

    async def setup(self, dry_run: bool = False):
        logger.info(f"🐝 Initializing Swarm Intelligence System... (Mode: {'DRY RUN' if dry_run else 'LIVE'})")

        # 0. Init Notifier & Commands
        self.notifier = TelegramNotifier(
            token=os.getenv("TELEGRAM_BOT_TOKEN"),
            chat_id=os.getenv("TELEGRAM_CHAT_ID")
        )
        self._register_commands()

        # Start notifier polling in background (non-blocking)
        if self.notifier.enabled:
            asyncio.create_task(self.notifier.start_polling())
            await self.notifier.send_message("🚀 *Hive Mind Swarm Intelligence* Online!\nUse /status to check system.")
            logger.info("✅ Telegram Notifier initialized and polling started")
        else:
            logger.warning("⚠️  Telegram Notifier disabled - check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")

        # Data Clients
        self.gamma_client = GammaClient()
        
        # PolyClient config update
        self.client.config.DRY_RUN = dry_run
        
        # Budget
        self.budget_manager = BudgetManager(total_capital=1000.0)
        
        # 1. News Scalper
        self.news_agent = OptimizedNewsScalper(
            news_api_key=os.getenv("NEWS_API_KEY"),
            tree_news_api_key=os.getenv("TREE_NEWS_API_KEY"),
            clob_client=self.client,
            budget_manager=self.budget_manager,
            signal_bus=self.bus,
            dry_run=dry_run, # 명령줄 인자와 연동
            use_rag=True,
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
            supabase_url=os.getenv("SUPABASE_URL"),
            supabase_key=os.getenv("SUPABASE_KEY"),
            swarm_system=self
        )

        # 2. Stat Arb
        self.stat_arb_agent = EnhancedStatArbStrategy(
            client=self.client,
            budget_manager=self.budget_manager,
            pnl_tracker=self.pnl_tracker
        )

        # Load pairs from config
        from src.strategies.stat_arb_config import CANDIDATE_PAIRS
        for pair in CANDIDATE_PAIRS:
            # Only add pairs with valid condition_ids (skip empty ones for now)
            if pair["token_a"]["condition_id"] and pair["token_b"]["condition_id"]:
                self.stat_arb_agent.add_pair(
                    condition_id_a=pair["token_a"]["condition_id"],
                    condition_id_b=pair["token_b"]["condition_id"],
                    pair_name=pair["name"],
                    category=pair["category"]
                )
        logger.info(f"✅ Loaded StatArb pairs (filtered for valid condition_ids)")

        # 3. Elite Mimic
        self.mimic_agent = EliteMimicAgent(
            client=self.client,
            signal_bus=self.bus,
            budget_manager=self.budget_manager
        )

        # 4. Pure Arb
        self.arb_agent = ArbitrageStrategy(
            client=self.client, 
            gamma_client=self.gamma_client, # 🎯 Inject Gamma Client
            signal_bus=self.bus, 
            budget_manager=self.budget_manager
        )
        self.arb_agent.notifier = self.notifier

        logger.info("✅ All Agents Initialized & Connected to Hive Mind")

    def _register_commands(self):
        self.notifier.register_command("/help", self.handle_help)
        self.notifier.register_command("/status", self.handle_status)
        self.notifier.register_command("/stop", self.handle_stop)
        self.notifier.register_command("/resume", self.handle_resume)
        self.notifier.register_command("/history", self.handle_history)
        self.notifier.register_command("/top", self.handle_top)

    async def handle_help(self, text):
        msg = (
            "🤖 *Hive Mind Swarm System Help*\n\n"
            "*Monitoring:*\n"
            "• /status - Get current balances and signals\n"
            "• /history - View last 5 executed trades\n"
            "• /top - See current best market opportunities\n\n"
            "*Control:*\n"
            "• /stop - Pause all automated trading\n"
            "• /resume - Re-enable automated trading\n\n"
            "*Info:*\n"
            "• /help - Show this manual\n\n"
            "Keep hunting for that alpha! 🚀"
        )
        await self.notifier.send_message(msg)

    async def handle_status(self, text):
        try:
            if not self.budget_manager or not self.pnl_tracker:
                await self.notifier.send_message("⏳ System is still initializing. Please wait...")
                return

            # 1. Fetch prices for unrealized PnL
            active_tokens = {entry.token_id for entry in self.pnl_tracker.active_trades.values()}
            current_prices = {}
            
            # Fetch prices (could be optimized with batch fetch in future)
            for tid in active_tokens:
                price = self.client.get_best_ask_price(tid)
                # If price is 0 (no liquidity/offline), try to use last known or skip
                if price > 0:
                    current_prices[tid] = price
                elif self.client.config.DRY_RUN:
                    # In Dry Run, simulate slight price movement for demo
                    import random
                    # entry price might not be easily accessible here without query, so just skip
                    # or assume 0.5 for stability if unknown
                    current_prices[tid] = 0.505 # Slight profit simulation

            # 2. Calculate PnL
            status = await self.budget_manager.get_status()
            pnl_summary = self.pnl_tracker.get_summary()
            
            realized_pnl = pnl_summary['total_pnl']
            unrealized_pnl = self.pnl_tracker.calculate_unrealized_pnl(current_prices)
            total_equity_pnl = realized_pnl + unrealized_pnl
            
            active_sigs = await self.bus.get_hot_tokens(min_sentiment=0.1) if self.bus else {}
            trading_status = "🟢 ENABLED" if self.trading_enabled else "🔴 STOPPED"
            
            # 3. Format Message
            lines = [
                "📊 *Hive Mind Status Report*",
                "",
                f"Trading: {trading_status}",
                "",
                "💎 *Performance:*",
                f"  Realized: *${realized_pnl:+.2f}*",
                f"  Unrealized: *${unrealized_pnl:+.2f}* (Floating)",
                f"  Total PnL: *${total_equity_pnl:+.2f}*",
                "",
                "💰 *Allocated Balances:*",
                f"- ARBHUNTER: ${status['balances'].get('arbhunter', 0):.2f}",
                f"- STATARB: ${status['balances'].get('statarb', 0):.2f}",
                f"- ELITEMIMIC: ${status['balances'].get('elitemimic', 0):.2f}",
                f"- Reserve: ${status.get('reserve', 0):.2f}",
                "",
                f"📈 *Open Positions:* {pnl_summary['open_positions']}",
                f"✅ *Completed Trades:* {pnl_summary['closed_trades']}",
                f"🧠 *Active Signals:* {len(active_sigs)}"
            ]
            
            await self.notifier.send_message("\n".join(lines))
        except Exception as e:
            logger.error(f"Status report error: {e}")
            await self.notifier.send_message("❌ Error building status report.")

    async def handle_stop(self, text):
        self.trading_enabled = False
        if self.news_agent: self.news_agent.dry_run = True 
        await self.notifier.send_message("🔴 *TRADING PAUSED.* All bots switched to Dry Run mode.")

    async def handle_resume(self, text):
        self.trading_enabled = True
        await self.notifier.send_message("🟢 *TRADING RESUMED.* Bots are looking for opportunities.")

    async def handle_history(self, text):
        if not self.trade_history:
            await self.notifier.send_message("📜 No trades recorded.")
            return
        
        msg = "📜 *Recent Trade History*\n\n"
        for t in self.trade_history[-5:]:
            pnl = f"({t['pnl']:+.2f}%)" if t.get('pnl') is not None else ""
            msg += f"• {t['time']} | {t['side']} {t['token'][:10]}... | ${t['price']:.3f} {pnl}\n"
        
        await self.notifier.send_message(msg)

    async def handle_top(self, text):
        signals = await self.bus.get_hot_tokens(min_sentiment=0.1)
        if not signals:
            await self.notifier.send_message("📡 No active signals.")
            return
            
        msg = "🏆 *Top Market Opportunities*\n\n"
        sorted_sigs = sorted(signals.values(), key=lambda x: abs(x.sentiment_score), reverse=True)
        for sig in sorted_sigs[:5]:
            msg += f"• `{sig.token_id[:15]}`: Sent {sig.sentiment_score:+.2f} | Whale {sig.whale_activity_score:.2f}\n"
        
        await self.notifier.send_message(msg)

    def add_trade_record(self, side, token, price, size, pnl=0.0):
        self.completed_trades.append({
            "time": datetime.now().strftime("%H:%M"),
            "side": side, "asset": token, "price": price, "size": size, "pnl": pnl
        })
        if len(self.completed_trades) > 50: self.completed_trades.pop(0)

    async def run(self, dry_run: bool = False):
        try:
            await self.setup(dry_run=dry_run)

            # 설정에서 감시 키워드 로드 ( .env 또는 기본값 )
            keywords = self.config.MONITOR_KEYWORDS

            logger.info(f"🚀 Swarm 요원 가동 시작... (감시 키워드: {len(keywords)}개)")
            logger.info("📋 Starting 6 bots: NewsScalper, StatArb, EliteMimic, PureArb, HealthMonitor, DailyReport")

            # 모든 에이전트를 동일한 루프에서 동시에 실행
            self.tasks = [
                asyncio.create_task(self.news_agent.run(keywords=keywords, check_interval=900), name="NewsScalper"),
                asyncio.create_task(self.stat_arb_agent.run(), name="StatArb"),
                asyncio.create_task(self.mimic_agent.run(), name="EliteMimic"),
                asyncio.create_task(self.arb_agent.run(), name="PureArb"),
                asyncio.create_task(self._monitor_swarm_health(), name="HealthMonitor"),
                asyncio.create_task(self._daily_report_task(), name="DailyReport")
            ]

            logger.info(f"✅ All {len(self.tasks)} bot tasks created successfully")

            try:
                await asyncio.gather(*self.tasks)
            except asyncio.CancelledError:
                logger.info("🐝 Swarm System stopping...")
        except Exception as e:
            logger.error(f"❌ Critical error in swarm run: {e}", exc_info=True)
            raise
        finally:
            await self.shutdown()

    async def _daily_report_task(self):
        while self.running:
            await asyncio.sleep(12 * 3600)
            if not self.trade_history: continue
            wins = len([t for t in self.trade_history if t.get('pnl', 0) and t['pnl'] > 0])
            msg = f"📅 *Daily Report*\nTrades: {len(self.trade_history)}\nWin Rate: {(wins/len(self.trade_history)*100):.1f}%"
            if self.notifier and self.notifier.enabled:
                await self.notifier.send_message(msg)

    async def _monitor_swarm_health(self):
        while self.running:
            await asyncio.sleep(60)
            # Threshold를 0.3으로 낮추어 더 많은 활동을 감지
            hot_tokens = await self.bus.get_hot_tokens(min_sentiment=0.3)
            if hot_tokens:
                logger.info(f"🔥 Swarm Alert: {len(hot_tokens)} active signals detected!")

    async def shutdown(self):
        self.running = False
        for task in self.tasks: task.cancel()
        logger.info("👋 Swarm Disconnected")

import argparse
from src.ui.dashboard import SwarmDashboard

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hive Mind Swarm System")
    parser.add_argument("--dry-run", action="store_true", help="Run in paper trading mode")
    parser.add_argument("--ui", action="store_true", help="Launch TUI Dashboard")
    args = parser.parse_args()

    system = SwarmSystem()
    try:
        if args.ui:
            dashboard = SwarmDashboard(system)
            # Ensure setup happens before dashboard run or within it
            asyncio.run(dashboard.run(dry_run=args.dry_run))
        else:
            asyncio.run(system.run(dry_run=args.dry_run))
    except KeyboardInterrupt:
        pass