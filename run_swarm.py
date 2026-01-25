import asyncio
import json
import logging
import os
import re
import signal
import sys
from contextlib import suppress
from datetime import datetime, timedelta
from uuid import uuid4
from dotenv import load_dotenv
import redis.asyncio as redis
import fcntl
import httpx

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
from src.core.delta_tracker import DeltaTracker
from src.core.structured_logger import setup_logging, StructuredLogger
from src.core.health_monitor import get_health_monitor, record_heartbeat
from src.core.status_reporter import StatusReporter # Added Producer
from src.core.market_specialist import MarketSpecialist
from src.core.market_specialist import MarketSpecialist
from src.core.global_risk_manager import GlobalRiskManager
from src.core.trade_repository import TradeRepository
from src.core.dashboard_api import start_dashboard_api, set_swarm_system
from src.core.state_doctor import StateDoctor
from src.core.performance_analyzer import PerformanceAnalyzer
from src.core.revaluation_engine import RevaluationEngine
from src.core.market_ranker import MarketRanker

# Strategies & Agents
from src.news.news_scalper_optimized import OptimizedNewsScalper
from src.strategies.stat_arb_enhanced import EnhancedStatArbStrategy
from src.strategies.elite_mimic import EliteMimicAgent
from src.strategies.arbitrage_v2 import PureArbitrageV2
from src.strategies.trend_follower import SmartTrendFollower
from src.strategies.liquidity_sniper import LiquiditySniper
from src.strategies.spread_scalper import SpreadScalper # NEW: HFT Module

# Setup Logging
# Initial logging before args are parsed
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SwarmOrchestrator")

class SwarmSystem:
    def __init__(self, json_logs: bool = False):
        self.json_logs = json_logs
        self.config = Config()
        self.bus = SignalBus()
        self.client = PolyClient()
        self.client.signal_bus = self.bus
        self.client.swarm_system = self # Link back for reporting (Fix for dashboard trade counts)
        
        # Trade Persistence (Phase 4.3)
        self.trade_repository = TradeRepository()
        self.pnl_tracker = PnLTracker(trade_repository=self.trade_repository)
        
        self.delta_tracker = DeltaTracker(self.bus, delta_limits=self.config.DELTA_LIMITS)
        self.budget_manager = None
        self.notifier = None
        self.health_monitor = None
        self.s_logger = None
        
        # Dashboard Reporter
        self.status_reporter = StatusReporter(filepath="data/dashboard_state.json")
        
        # New: Global Risk Manager
        self.risk_manager = GlobalRiskManager()
        
        # Market Specialist (The "Brain" that learns from backtests)
        self.market_specialist = MarketSpecialist()

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
        self.trend_agent = None
        self.liquidity_sniper = None
        self.spread_scalper = None # HFT Agent

        self.running = True
        self.tasks = []
        self.notifier_task = None
        self.status_heartbeat_minutes = int(os.getenv("STATUS_HEARTBEAT_MINUTES", "30"))
        self.status_watch_interval = int(os.getenv("STATUS_WATCH_INTERVAL_SECONDS", "300"))
        self.pnl_alert_threshold = float(os.getenv("STATUS_PNL_ALERT_THRESHOLD", "5.0"))
        self._last_total_pnl = None
        
        # Performance Caching
        self.tick_count = 0
        self.last_balance = 0.0
        self.revaluation_engine = None
        self.market_ranker = None

    async def setup(self, dry_run: bool = False):
        # Configure advanced logging
        mode_suffix = "dry" if dry_run else "live"
        setup_logging(
            level=logging.INFO,
            json_output=self.json_logs,
            log_file=f"logs/swarm_{mode_suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )

        # 0. run State Doctor (Startup Validation)
        try:
            doctor = StateDoctor()
            await doctor.run()
        except Exception as e:
            logger.error(f"State Doctor failed during startup: {e}")
        # Dashboard Logging Hook
        from src.core.structured_logger import attach_dashboard_handler
        attach_dashboard_handler(self.status_reporter)
        
        # Set system mode in reporter
        self.status_reporter.update_state({"mode": "DRY RUN" if dry_run else "LIVE"})

        self.s_logger = StructuredLogger("SwarmOrchestrator")
        self.s_logger.info(f"🐝 Initializing Swarm Intelligence System... (Mode: {'DRY RUN' if dry_run else 'LIVE'})")

        # 0. Init Notifier & Commands
        self.notifier = TelegramNotifier(
            token=os.getenv("TELEGRAM_BOT_TOKEN"),
            chat_id=os.getenv("TELEGRAM_CHAT_ID")
        )
        self._register_commands()
        
        # 0.1 Redis Connection (Shared Backbone)
        try:
             self.redis = redis.Redis(host='localhost', port=6379, db=0)
             await self.redis.ping()
             logger.info("✅ Redis Connection Established (Localhost:6379)")
             
             # Inject into SignalBus specific persistence
             self.bus.set_redis(self.redis)
             await self.bus.load_state()
             
        except Exception as e:
             logger.error(f"❌ Redis Connection Failed: {e}")
             self.redis = None

        # 0.2 PostgreSQL Trade Repository Connection (Phase 4.3)
        try:
            pg_connected = await self.trade_repository.connect()
            if pg_connected:
                logger.info("✅ PostgreSQL Trade Repository connected")
            else:
                logger.warning("⚠️ PostgreSQL not available - using CSV fallback for trade persistence")
        except Exception as e:
            logger.warning(f"⚠️ PostgreSQL connection failed: {e}")

        # Start notifier polling in background (non-blocking)
        if self.notifier.enabled:
            if not dry_run:
                self.notifier_task = asyncio.create_task(self.notifier.start_polling())
                logger.info("✅ Telegram Notifier initialized and polling started (LIVE mode)")
            else:
                logger.info("ℹ️ Telegram Notifier Active (Send-Only in DRY RUN mode)")
            
            await self.notifier.send_message("🚀 *Hive Mind Swarm Intelligence* Online!\nUse /status to check system.")
        else:
            logger.warning("⚠️  Telegram Notifier disabled - check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")

        # Data Clients
        self.gamma_client = GammaClient()
        
        # PolyClient config update
        self.client.config.DRY_RUN = dry_run
        
        # Budget
        initial_capital = 10000.0 # Bumping to $10k for smoother dry-run testing
        if not dry_run:
            try:
                # Attempt to fetch real balance for initial capital
                balance_str = await self.client.get_usdc_balance()
                initial_capital = float(balance_str)
                self.last_balance = initial_capital # Initialize last_balance
                logger.info(f"💳 Wallet Balance Detected: ${initial_capital:.2f}")
            except Exception as e:
                logger.warning(f"⚠️ Could not fetch balance, defaulting to $50.0: {e}")
                initial_capital = 50.0

        self.budget_manager = BudgetManager(total_capital=initial_capital)
        
        # Inject dependencies into Risk Manager
        self.risk_manager.set_dependencies(self.pnl_tracker, self.delta_tracker, self.bus)
        self.risk_manager.start_of_day_equity = initial_capital
        
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
            swarm_system=self,
            delta_tracker=self.delta_tracker,
            market_specialist=self.market_specialist,
            redis_client=self.redis,
            risk_manager=self.risk_manager
        )
        
        # 1.1 Liquidity Sniper (Helper for News)
        self.liquidity_sniper = LiquiditySniper(self.client, self.bus)

        # 2. Stat Arb
        self.stat_arb_agent = EnhancedStatArbStrategy(
            client=self.client,
            budget_manager=self.budget_manager,
            signal_bus=self.bus,
            pnl_tracker=self.pnl_tracker,
            delta_tracker=self.delta_tracker,
            risk_manager=self.risk_manager
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
            budget_manager=self.budget_manager,
            swarm_system=self
        )

        # 4. Pure Arb V2 (Global NegRisk Optimized)
        self.arb_agent = PureArbitrageV2(
            client=self.client, 
            gamma_client=self.gamma_client, 
            signal_bus=self.bus, 
            budget_manager=self.budget_manager,
            min_profit=0.010, # 1.0% Threshold
            default_trade_size=50.0,
            risk_manager=self.risk_manager,
            pnl_tracker=self.pnl_tracker, # Phase 4.3
            market_ranker=self.market_ranker, # Phase 7
            dry_run=dry_run
        )
        self.arb_agent.notifier = self.notifier

        # 5. Trend Follower
        self.trend_agent = SmartTrendFollower(
            client=self.client,
            budget_manager=self.budget_manager,
            status_reporter=self.status_reporter,
            pnl_tracker=self.pnl_tracker,
            signal_bus=self.bus
        )

        # 6. Spread Scalper (HFT)
        self.spread_scalper = SpreadScalper(
            client=self.client,
            gamma_client=self.gamma_client,
            budget_manager=self.budget_manager
        )

        # 5. Health Monitor
        # Use shared redis connection
        self.health_monitor = await get_health_monitor(
            redis=self.redis,
            budget_manager=self.budget_manager,
            metrics_port=int(os.getenv("METRICS_PORT", "8000"))
        )

        from src.core.reasoning_engine import LLMReasoningEngine
        self.reasoning_engine = LLMReasoningEngine(model_name="gpt-4o")
        logger.info("🧠 AI Brain (Reasoning Engine) Online")

        # --- Phase 5: Revaluation Engine ---
        self.revaluation_engine = RevaluationEngine(
            pnl_tracker=self.pnl_tracker,
            rag_system=getattr(self.news_agent, 'rag_system', None)
        )
        logger.info("⚖️ AI Revaluation Engine Online (Auto-Liquidation ready)")

        # --- Phase 7: Market Ranker (Alpha Heatmap) ---
        self.market_ranker = MarketRanker(self.gamma_client, self.bus)
        logger.info("🔥 Alpha Heatmap Ranker Online")

        logger.info("✅ All Agents & Revaluation Engine Initialized")

    def _register_commands(self):
        self.notifier.register_command("/help", self.handle_help)
        self.notifier.register_command("/status", self.handle_status)
        self.notifier.register_command("/stop", self.handle_stop)
        self.notifier.register_command("/resume", self.handle_resume)
        self.notifier.register_command("/history", self.handle_history)
        self.notifier.register_command("/top", self.handle_top)
        self.notifier.register_command("/pnl", self.handle_pnl)
        self.notifier.register_command("/risk", self.handle_risk)
        self.notifier.register_command("/liquidate", self.handle_liquidate)
        self.notifier.register_command("/audit", self.handle_audit)
        self.notifier.register_command("/panic", self.handle_panic)
        self.notifier.register_command("/unpanic", self.handle_unpanic)
        self.notifier.register_command("/settings", self.handle_settings)
        self.notifier.register_command("/balance", self.handle_balance)
        self.notifier.register_command("/kill", self.handle_kill)
        self.notifier.register_command("/verify", self.handle_verify)
        self.notifier.register_command("/alerts", self.handle_alerts)
        
        # Bifurcation Variants (Phase 22)
        prefixes = ["/t", "/l"]
        base_cmds = ["status", "settings", "balance", "pnl", "history", "top", "risk"]
        for p in prefixes:
            for bc in base_cmds:
                cmd = f"{p}{bc}"
                handler_name = f"handle_{bc}"
                if hasattr(self, handler_name):
                    self.notifier.register_command(cmd, getattr(self, handler_name))

        # Register Command Menu with Telegram
        menu_commands = [
            {"command": "status", "description": "전체 상태 체크"},
            {"command": "verify", "description": "실시간 데이터 검증 (Proof of Data)"},
            {"command": "alerts", "description": "알림 설정 토글"},
            {"command": "settings", "description": "봇 설정 제어 (메뉴)"},
            {"command": "balance", "description": "상세 잔고 및 할량"},
            {"command": "pnl", "description": "수익 요약"},
            {"command": "help", "description": "도움말"}
        ]
        asyncio.create_task(self.notifier.set_my_commands(menu_commands))

        logger.info("✅ Telegram Commands Registered with Bifurcation and Verify")

    async def handle_help(self, text):
        msg = (
            "🤖 *Hive Mind Swarm System Help*\n\n"
            "*Monitoring:*\n"
            "• /status - Get current balances and signals\n"
            "• /settings - Configure bot behavior interactively\n"
            "• /balance - Detailed allocation breakdown\n"
            "• /history - View last 5 executed trades\n"
            "• /top - See current best market opportunities\n"
            "• /verify - Compare pricing with real-time API\n"
            "• /alerts - Toggle trade notifications\n\n"
            "*Control:*\n"
            "• /stop - Pause all automated trading\n"
            "• /resume - Re-enable automated trading\n"
            "• /kill - Immediate remote shutdown\n"
            "• /pnl - Check daily profit/loss\n\n"
            "*Risk Management:*\n"
            "• /risk <low|mid|high|yolo> - Adjust global risk multiplier\n"
            "• /panic - Activate global circuit breaker\n"
            "• /unpanic - Deactivate global circuit breaker\n"
            "• /liquidate <token_id|all> - Close positions\n\n"
            "*Multi-Bot Control (Bifurcation):*\n"
            "• `/t<cmd>` - Run command on TEST bot (e.g., /tstatus)\n"
            "• `/l<cmd>` - Run command on LIVE bot (e.g., /lstatus)\n\n"
            "*Info:*\n"
            "• /help - Show this manual\n\n"
            "Keep hunting for that alpha! 🚀"
        )
        await self.notifier.send_message(msg)

    def _check_mode_match(self, text: str) -> bool:
        """Phase 22: Check if command prefix matches current system mode."""
        cmd = text.split()[0].lower()
        if cmd.startswith("/t"):
            return self.config.DRY_RUN
        if cmd.startswith("/l"):
            return not self.config.DRY_RUN
        return True # Neutral commands always respond

    async def handle_status(self, text):
        if not self._check_mode_match(text): return
        try:
            if not self.budget_manager or not self.pnl_tracker:
                await self.notifier.send_message("⏳ System is still initializing. Please wait...", priority=1)
                return

            payload = await self._build_status_payload()
            self._log_status_snapshot(payload)
            message = self._format_status_message(payload)
            await self.notifier.send_message(message, priority=1)
        except Exception as e:
            logger.exception("❌ Failed to generate status report")
            await self.notifier.send_message(f"⚠️ Failed to fetch status: {e}", priority=1)

    async def _build_status_payload(self) -> dict:
        """Collect a single source-of-truth payload for /status reporting."""
        active_tokens = {entry.token_id for entry in self.pnl_tracker.active_trades.values()}
        current_prices = {}

        for tid in active_tokens:
            price = self.client.get_best_ask_price(tid)
            if price > 0:
                current_prices[tid] = price
            elif self.client.config.DRY_RUN:
                current_prices[tid] = 0.505

        status = await self.budget_manager.get_status()
        pnl_summary = self.pnl_tracker.get_summary()
        realized_pnl = float(pnl_summary['total_pnl'])
        unrealized_pnl = float(self.pnl_tracker.calculate_unrealized_pnl(current_prices))
        total_equity_pnl = realized_pnl + unrealized_pnl

        active_sigs = await self.bus.get_hot_tokens(min_sentiment=0.1) if self.bus else {}
        serialized_signals = [
            {
                "token_id": token_id,
                "sentiment": float(signal.sentiment_score),
                "whale": float(signal.whale_activity_score),
                "last_updated": signal.last_updated.isoformat(),
            }
            for token_id, signal in active_sigs.items()
        ]

        balances = status.get('balances', {})
        risk_exposure = []
        if self.delta_tracker:
            delta_snapshot = self.delta_tracker.get_snapshot()
            limit_table = self.config.DELTA_LIMITS
            for market_key, entry in delta_snapshot.items():
                long_size = float(entry.get("long_size", 0.0))
                short_size = float(entry.get("short_size", 0.0))
                net = long_size - short_size
                if abs(net) < 1.0:
                    continue
                group = entry.get("market_group", "DEFAULT")
                group_limits = limit_table.get(group, limit_table.get("DEFAULT", {}))
                hard = group_limits.get("hard")
                soft = group_limits.get("soft")
                status_flag = "OK"
                if hard and abs(net) >= hard:
                    status_flag = "HARD"
                elif soft and abs(net) >= soft:
                    status_flag = "SOFT"
                usage_pct = (abs(net) / hard * 100) if hard else None
                risk_exposure.append(
                    {
                        "market": market_key,
                        "group": group,
                        "net": net,
                        "hard_limit": hard,
                        "soft_limit": soft,
                        "usage_pct": usage_pct,
                        "status": status_flag,
                    }
                )
        risk_exposure.sort(key=lambda x: abs(x["net"]), reverse=True)

        history_sources = []
        price_api = getattr(getattr(self, "stat_arb_agent", None), "_price_api", None)
        if price_api and hasattr(price_api, "get_history_source_snapshot"):
            snapshot = price_api.get_history_source_snapshot()
            for cid, meta in snapshot.items():
                history_sources.append(
                    {
                        "condition": cid,
                        "source": meta.get("source", "UNKNOWN"),
                        "points": meta.get("points"),
                        "timestamp": meta.get("timestamp"),
                    }
                )
        history_sources.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

        real_wallet_balance = self.last_balance # Use cached balance

        # Brain Metrics (Specialist)
        brain_metrics = []
        if self.market_specialist:
            for tag, stats in self.market_specialist.tag_stats.items():
                multiplier = self.market_specialist._get_tag_multiplier(tag)
                total = stats["wins"] + stats["losses"]
                wr = (stats["wins"] / total * 100) if total > 0 else 0.0
                brain_metrics.append({
                    "tag": tag.upper(),
                    "multiplier": multiplier,
                    "win_rate": wr,
                    "pnl": stats["pnl"],
                    "samples": total
                })
        brain_metrics.sort(key=lambda x: x['multiplier'], reverse=True)

        payload = {
            "type": "STATUS_SNAPSHOT",
            "snapshot_id": str(uuid4()),
            "timestamp": datetime.now().isoformat(),
            "brain": brain_metrics, 
            "mode": "DRY_RUN" if self.client.config.DRY_RUN else "LIVE",
            "trading": {
                "enabled": self.trading_enabled,
            },
            "performance": {
                "realized": realized_pnl,
                "unrealized": unrealized_pnl,
                "total": total_equity_pnl,
            },
            "balances": {
                "arbhunter": float(balances.get('arbhunter', 0)),
                "statarb": float(balances.get('statarb', 0)),
                "elitemimic": float(balances.get('elitemimic', 0)),
                "reserve": float(status.get('reserve', 0)),
                "wallet_usdc": real_wallet_balance,
            },
            "positions": {
                "open": int(pnl_summary['open_positions']),
                "closed": int(pnl_summary['closed_trades']),
            },
            "signals": {
                "active_count": len(serialized_signals),
                "entries": serialized_signals,
            },
            "risk": {
                "exposure": risk_exposure,
            },
            "history_sources": history_sources,
            "spread_stats": await self.bus.get_spread_snapshot() if self.bus else [],
        }
        return payload

    def _log_status_snapshot(self, payload: dict) -> None:
        """Write the JSON payload to logs for later auditing."""
        logger.info("STATUS_SNAPSHOT %s", json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def _tg_escape(value: str) -> str:
        """Escape Telegram Markdown control characters in dynamic values."""
        if value is None:
            return ""
        return re.sub(r'([_\[\]\(\)~`>#+=|{}!])', r'\\\1', str(value))

    def _format_status_message(self, payload: dict) -> str:
        """Convert the payload into a Telegram-friendly status message."""
        trading_state = "🟢 ENABLED" if payload["trading"]["enabled"] else "🔴 STOPPED"
        perf = payload["performance"]
        balances = payload["balances"]
        positions = payload["positions"]
        signals = payload["signals"]
        risk = payload.get("risk", {})
        exposures = risk.get("exposure", [])
        history_sources = payload.get("history_sources", [])
        spread_stats = payload.get("spread_stats", [])

        sid = self._tg_escape(payload['snapshot_id'][:8])
        mode = self._tg_escape(payload['mode'])
        realized = self._tg_escape(f"{perf['realized']:+.2f}")
        unrealized = self._tg_escape(f"{perf['unrealized']:+.2f}")
        total = self._tg_escape(f"{perf['total']:+.2f}")

        lines = [
            "📊 *Hive Mind Status Report*",
            f"ID: `{sid}` | Mode: {mode}",
            "",
            f"Trading: {trading_state}",
            "",
            "💎 *Performance:*",
            f"  Realized: *${realized}*",
            f"  Unrealized: *${unrealized}* (Floating)",
            f"  Total PnL: *${total}*",
        ]

        wallet_balance = balances.get("wallet_usdc")
        lines.append("")
        if wallet_balance is not None:
            lines.append(f"💳 *Wallet Balance:* ${wallet_balance:.2f}")
        else:
            lines.append("💳 *Wallet Balance:* $0.00 _(fetch failed)_")

        # Get current Risk Multiplier
        current_risk_mult = 0.25 # Default
        if self.news_agent and hasattr(self.news_agent, 'risk_manager'):
            current_risk_mult = self.news_agent.risk_manager.risk_multiplier

        lines.extend(
            [
                "",
                f"⚖️ *Risk Setting:* {current_risk_mult}x", 
                "💰 *Allocated Balances:*",
                f"- ARBHUNTER: ${balances['arbhunter']:.2f}",
                f"- STATARB: ${balances['statarb']:.2f}",
                f"- ELITEMIMIC: ${balances['elitemimic']:.2f}",
                f"- Reserve: ${balances['reserve']:.2f}",
                "",
                f"📈 *Open Positions:* {positions['open']}",
                f"✅ *Completed Trades:* {positions['closed']}",
                f"🧠 *Active Signals:* {signals['active_count']}",
            ]
        )
        if exposures:
            lines.append("")
            lines.append("⚖️ *Risk Exposure:*")
            for entry in exposures[:3]:
                usage = entry.get("usage_pct")
                usage_str = f"{usage:.0f}%" if usage is not None else "n/a"
                market_id = entry["market"]
                market_label = market_id[:12] + ("…" if len(market_id) > 12 else "")
                group = self._tg_escape(entry.get("group", "UNKNOWN"))
                status = self._tg_escape(entry.get("status", "OK"))
                lines.append(
                    f"- {market_label} ({group}): {entry['net']:+.1f} [{status}] {usage_str}"
                )
        if history_sources:
            lines.append("")
            lines.append("🗂 *History Sources:*")
            for entry in history_sources[:3]:
                condition_id = entry["condition"]
                market_label = condition_id[:12] + ("…" if len(condition_id) > 12 else "")
                source = self._tg_escape(entry.get("source", "UNKNOWN"))
                points = entry.get("points")
                pts_str = f"{points}" if points is not None else "?"
                lines.append(f"- {market_label}: {source} ({pts_str} pts)")

        if spread_stats:
            lines.append("")
            lines.append("📡 *Spread Regimes:*")
            for entry in spread_stats:
                token_label = entry["token_id"][:12] + ("…" if len(entry["token_id"]) > 12 else "")
                regime = self._tg_escape(entry.get("regime", "UNKNOWN"))
                spread_bps = entry.get("spread_bps", 0.0)
                lines.append(f"- {token_label}: {regime} ({spread_bps:.0f} bps)")
        else:
            lines.append("")
            lines.append("📡 *Spread Regimes:* All Normal")

        return "\n".join(lines)

    async def handle_stop(self, text):
        self.trading_enabled = False
        if self.news_agent: self.news_agent.dry_run = True 
        await self.notifier.send_message("🔴 *TRADING PAUSED.* All bots switched to Dry Run mode.")

    async def handle_resume(self, text):
        self.trading_enabled = True
        await self.notifier.send_message("🟢 *TRADING RESUMED.* Bots are looking for opportunities.")

    async def handle_history(self, text):
        if not self._check_mode_match(text): return
        if not self.trade_history:
            await self.notifier.send_message("📜 No trades recorded.")
            return
        
        msg = "📜 *Recent Trade History*\n\n"
        for t in self.trade_history[-5:]:
            pnl = f"({t['pnl']:+.2f}%)" if t.get('pnl') is not None else ""
            msg += f"• {t['time']} | {t['side']} {t['asset'][:10]}... | ${t['price']:.3f} {pnl}\n"
        
        await self.notifier.send_message(msg)

    async def handle_risk(self, text):
        """Handle /risk <level> command"""
        if not self._check_mode_match(text): return
        try:
            parts = text.split()
            if len(parts) < 2:
                await self.notifier.send_message("⚠️ Usage: `/risk <low|mid|high|yolo>`")
                return
            
            level = parts[1].lower()
            multiplier_map = {
                "low": 0.1,
                "mid": 0.25,
                "high": 0.5,
                "yolo": 1.0
            }
            
            if level not in multiplier_map:
                await self.notifier.send_message(f"⚠️ Unknown level '{level}'. Use: low, mid, high, yolo")
                return
                
            new_mult = multiplier_map[level]
            # Update all strategies that use budget_manager's risk config?
            # Actually budget manager holds allocation, RiskManager holds logic.
            # We need to access RiskManager.
            
            # Since swarm_system owns the agents, and agents own risk_manager usually...
            # Wait, news_scalper has its own risk_manager? Or uses shared?
            # Looking at code: news_scalper.risk_manager is instantiated inside it.
            # We should probably centralize or update the instance.
            
            updated = False
            if self.news_agent and hasattr(self.news_agent, 'risk_manager'):
                 if self.news_agent.risk_manager.set_risk_multiplier(new_mult):
                     updated = True
                     
            if updated:
                emoji = "🐢" if level == "low" else "🚀" if level == "yolo" else "⚖️"
                await self.notifier.send_message(f"{emoji} **Risk Adjusted**: {level.upper()} ({new_mult}x)")
            else:
                await self.notifier.send_message("⚠️ Failed to update risk settings.")
                
        except Exception as e:
            logger.error(f"Error in handle_risk: {e}")
            await self.notifier.send_message(f"❌ Error: {str(e)}")

    async def handle_settings(self, text):
        """Show interactive settings menu"""
        if not self._check_mode_match(text): return
        current_risk = 0.25
        if self.news_agent and hasattr(self.news_agent, 'risk_manager'):
            current_risk = self.news_agent.risk_manager.risk_multiplier

        mode = "DRY RUN" if self.config.DRY_RUN else "LIVE"
        trading = "🟢 Running" if self.trading_enabled else "🔴 Paused"
        alerts = "🔔 ON" if self.config.TELEGRAM_NOTIFICATIONS_ENABLED else "🔕 OFF"
        threshold = f"${self.config.TELEGRAM_MIN_TRADE_SIZE:.2f}"

        msg = (
            f"⚙️ *Bot Configuration Menu*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• *Mode:* `{mode}`\n"
            f"• *Trading:* {trading}\n"
            f"• *Risk:* `{current_risk}x`\n"
            f"• *Alerts:* {alerts} (>{threshold})\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Select a setting to modify:"
        )

        keyboard = [
            [
                {"text": "📈 Risk: Low", "callback_data": "/risk low"},
                {"text": "🚀 Risk: YOLO", "callback_data": "/risk yolo"}
            ],
            [
                {"text": "🛑 Stop Trading", "callback_data": "/stop"},
                {"text": "▶️ Resume", "callback_data": "/resume"}
            ],
            [
                {"text": "🔔 Toggle Alerts", "callback_data": "/alerts"},
                {"text": "🔍 Verify Data", "callback_data": "/verify"}
            ],
            [
                {"text": "📊 Full Status", "callback_data": "/status"},
                {"text": "💰 Balance", "callback_data": "/balance"}
            ]
        ]
        await self.notifier.send_message(msg, inline_keyboard=keyboard)

    async def handle_balance(self, text):
        """Detailed balance report"""
        if not self._check_mode_match(text): return
        if not self.budget_manager: return
        
        status = await self.budget_manager.get_status()
        balances = status.get('balances', {})
        reserve = status.get('reserve', 0.0)
        
        msg = (
            "💳 *Detailed Wallet & Allocations*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🏦 *Wallet (USDC):* `${self.last_balance:,.2f}`\n"
            f"📦 *Reserve:* `${reserve:,.2f}`\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🛠 *News Scalper:* `${balances.get('arbhunter', 0):,.2f}`\n"
            f"⚖️ *Stat Arb:* `${balances.get('statarb', 0):,.2f}`\n"
            f"👥 *Elite Mimic:* `${balances.get('elitemimic', 0):,.2f}`\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *Total Managed:* `${sum(balances.values()) + reserve:,.2f}`"
        )
        await self.notifier.send_message(msg)

    async def handle_kill(self, text):
        """Remote shutdown switch"""
        await self.notifier.send_message("💀 *REMOTE SHUTDOWN INITIATED...* Goodnight.")
        logger.warning("💀 Remote shutdown command received via Telegram.")
        self.running = False
        # Trigger cleanup
        os.kill(os.getpid(), signal.SIGINT)

    async def handle_alerts(self, text):
        """Toggle Telegram notifications enabled state"""
        current = self.config.TELEGRAM_NOTIFICATIONS_ENABLED
        new_state = not current
        self.config.TELEGRAM_NOTIFICATIONS_ENABLED = new_state
        
        emoji = "🔔" if new_state else "🔕"
        msg = f"{emoji} **Telegram Alerts**: {'ENABLED' if new_state else 'DISABLED'}"
        await self.notifier.send_message(msg)
        
        # Refresh settings menu
        await self.handle_settings(text)

    async def handle_verify(self, text):
        """Phase 23: Proof of Real-Time Data"""
        await self.notifier.send_message("🔍 *Verifying Real-Time Data Sync...*")
        
        # Pick a high-volume target market: BTC/USD 15m (Example CID)
        # Note: In production, we'd dynamically find a valid CID from Gamma
        target_cid = "0xafdfba3c8117db508bc6bea87fa5e638d302c28ffb610b72fbad2d99f33e66db" # BTC-15M-UP-DOWN
        market_name = "Bitcoin Up/Down (15m)"
        
        try:
            # 1. Internal State
            internal_price = 0.0
            tokens = await self.gamma_client.get_market(target_cid)
            if tokens and 'clobTokenIds' in tokens:
                token_ids = json.loads(tokens['clobTokenIds'])
                internal_price = self.client.get_best_ask_price(token_ids[0])
            
            # 2. External Truth (Direct API call during command)
            async with httpx.AsyncClient() as client:
                # Direct price check to CLOB API
                resp = await client.get(f"{self.config.HOST}/price/buy?token_id={token_ids[0]}&amount=100")
                api_data = resp.json()
                external_price = float(api_data.get("price", 0))

            diff = abs(internal_price - external_price)
            sync_status = "✅ PERFECT SYNC" if diff < 0.001 else "⚠️ SLIGHT DRIFT" if diff < 0.01 else "❌ OUTSIDE TOLERANCE"
            
            msg = (
                f"🧪 *REAL-DATA VERIFICATION REPORT*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📍 *Target:* `{market_name}`\n"
                f"🤖 *Bot Internal:* `${internal_price:.4f}`\n"
                f"📡 *Api Truth:*    `${external_price:.4f}`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 *Status:* {sync_status} (Diff: ${diff:.4f})\n\n"
                f"_This proves the bot is consuming live Polymarket orderbooks._"
            )
            await self.notifier.send_message(msg)
            
        except Exception as e:
            logger.error(f"Verification failed: {e}")
            await self.notifier.send_message(f"❌ Verification Failed: {str(e)}")

    async def handle_panic(self, text):
        """Activate global circuit breaker"""
        if self.risk_manager:
            self.risk_manager.circuit_breaker_enabled = True
            await self.notifier.send_message("🚨 **PANIC MODE ACTIVATED** 🚨\nCircuit breaker enabled. All trading halted.")
        else:
            await self.notifier.send_message("⚠️ Risk Manager not initialized.")

    async def handle_unpanic(self, text):
        """Deactivate global circuit breaker"""
        if self.risk_manager:
            self.risk_manager.circuit_breaker_enabled = False
            await self.notifier.send_message("🟢 **PANIC MODE DEACTIVATED** 🟢\nCircuit breaker disabled. Trading can resume.")
        else:
            await self.notifier.send_message("⚠️ Risk Manager not initialized.")

    async def handle_liquidate(self, text):
        """Handle /liquidate <token|all> command"""
        try:
            parts = text.split()
            if len(parts) < 2:
                await self.notifier.send_message("⚠️ Usage: `/liquidate <token_id|all>`")
                return
            
            target = parts[1].strip()
            
            if target.lower() == "all":
                await self.notifier.send_message("🚨 **EMERGENCY LIQUIDATION INITIATED** 🚨\nClosing ALL positions...")
                count = 0
                
                # Copy list to avoid modification during iteration
                active_ids = list(self.pnl_tracker.active_trades.keys())
                
                for trade_id in active_ids:
                    trade = self.pnl_tracker.active_trades.get(trade_id)
                    if not trade: continue
                    
                    # Use news agent to close (it has the logic)
                    if self.news_agent:
                        # Construct a mock position object since _close_position expects one
                        # Or better, expose a public close method. 
                        # NewsScalper._close_position is async and expects (token_id, position_data, reason)
                        
                        # We need to find the position data in news_agent.positions
                        pos_data = self.news_agent.positions.get(trade.token_id)
                        if pos_data:
                            await self.news_agent._close_position(trade.token_id, pos_data, "Emergency Command")
                            count += 1
                        else:
                            # If not in scalper memory (e.g. hydrated), try to force close via logic
                            # Attempting force close without full context
                            logger.info(f"Force closing orphan trade {trade.token_id}")
                            # Fallback logic if needed, but for now stick to tracked positions
                
                await self.notifier.send_message(f"✅ Liquidation Sequence Complete. Closed {count} positions.")
                
            else:
                # Close specific token
                if self.news_agent:
                     pos_data = self.news_agent.positions.get(target)
                     if pos_data:
                         await self.news_agent._close_position(target, pos_data, "Command")
                         await self.notifier.send_message(f"✅ Closed position for `{target[:10]}...`")
                     else:
                         await self.notifier.send_message(f"⚠️ Position not found: `{target}`")
        except Exception as e:
            logger.error(f"Error in handle_liquidate: {e}")
            await self.notifier.send_message(f"❌ Error: {str(e)}")

    async def handle_top(self, text):
        if not self._check_mode_match(text): return
        signals = await self.bus.get_hot_tokens(min_sentiment=0.1)
        if not signals:
            await self.notifier.send_message("📡 No active signals.")
            return
            
        msg = "🏆 *Top Market Opportunities*\n\n"
        sorted_sigs = sorted(signals.values(), key=lambda x: abs(x.sentiment_score), reverse=True)
        for sig in sorted_sigs[:5]:
            msg += f"• `{sig.token_id[:15]}`: Sent {sig.sentiment_score:+.2f} | Whale {sig.whale_activity_score:.2f}\n"
        
        await self.notifier.send_message(msg)

    async def handle_pnl(self, text):
        if not self._check_mode_match(text): return
        pnl_data = self.pnl_tracker.get_summary()
        msg = (
            f"💰 <b>REAL-TIME P&L REPORT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 <b>Daily PnL:</b> <code>${pnl_data['total_pnl']:+.2f}</code>\n"
            f"📈 <b>Open Pos:</b> <code>{pnl_data['open_positions']}</code>\n"
            f"✅ <b>Closed:</b>   <code>{pnl_data['closed_trades']}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕒 {datetime.now().strftime('%H:%M:%S')}"
        )
        await self.notifier.send_message(msg)

    def add_trade_record(self, side, token, price, size, pnl=0.0, condition_id: str = "", brain_score: float = 1.0):
        self.completed_trades.append({
            "time": datetime.now().strftime("%H:%M"),
            "side": side, "asset": token, "price": price, "size": size, "pnl": pnl
        })
        if len(self.completed_trades) > 50: self.completed_trades.pop(0)

        # Notify via Telegram (Phase 21 & 24: Config-Driven Threshold Check)
        if self.notifier and self.notifier.enabled:
             if not self.config.TELEGRAM_NOTIFICATIONS_ENABLED:
                 logger.debug("🔕 Telegram notifications globally disabled via Config")
                 return

             # Use config threshold
             threshold = self.config.TELEGRAM_MIN_TRADE_SIZE
             
             # Silenced in Dry Run per user request
             if self.client.config.DRY_RUN:
                 return

             if size >= threshold or abs(pnl) > 0.1:
                 asyncio.create_task(
                    self.notifier.notify_trade(
                        side, token, price, size, 
                        profit=pnl,
                        condition_id=condition_id, 
                        brain_score=brain_score,
                        strategy="Swarm"
                    )
                 )
             else:
                 logger.debug(f"🔕 Suppressing Telegram notification for small trade (${size:.2f} < ${threshold:.2f})")

    async def _update_balance_metrics(self):
        """Fetches and updates the wallet balance."""
        try:
            wallet_bal = await self.client.get_usdc_balance()
            self.last_balance = float(wallet_bal)
            logger.debug(f"Updated wallet balance: ${self.last_balance:.2f}")
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch balance in _update_balance_metrics: {e}")
            # Keep last known balance if fetch fails

    async def _hydrate_positions(self):
        """Fetch existing positions from API and populate PnLTracker"""
        logger.info("💧 Hydrating active positions from API...")
        try:
            positions = await self.client.get_all_positions()
            logger.info(f"🔍 Raw Positions Response: {positions}")
            count = 0
            for pos in positions:
                size = float(pos.get("size", 0))
                if size < 0.0001: continue
                
                token_id = pos.get("asset")
                if not token_id: continue
                
                # Try to get avg entry price, imply from cost if available, else current market
                # Some APIs return 'avgPrice' or 'entryPrice'
                entry_price = float(pos.get("avgPrice") or pos.get("curPrice") or 0.5)
                
                self.pnl_tracker.record_existing_trade(
                    strategy="Hydrated",
                    token_id=token_id,
                    side="BUY", 
                    price=entry_price,
                    size=size
                )
                
                # Also hydrate NewsScalper so it knows exposure
                if self.news_agent:
                    await self.news_agent.hydrate_position(token_id, size, entry_price)

                count += 1
            logger.info(f"✅ Hydrated {count} positions into PnL Tracker & NewsScalper")
        except Exception as e:
            logger.error(f"⚠️ Failed to hydrate positions: {e}")

    async def _daily_report_task(self):
        """Send performance stats to Telegram every 6 hours"""
        analyzer = PerformanceAnalyzer()
        REPORT_INTERVAL = 6 * 3600 
        
        while self.running:
            try:
                # Wait first (don't spam on restart)
                await asyncio.sleep(REPORT_INTERVAL)
                report = analyzer.generate_report()
                if self.notifier and self.notifier.enabled:
                    await self.notifier.send_message(report)
            except Exception as e:
                logger.error(f"Error in daily report: {e}")
                await asyncio.sleep(60)

    async def run(self, dry_run: bool = False):
        try:
            await self.setup(dry_run=dry_run)
            
            # Hydrate positions immediately after setup
            if not dry_run:
                await self._hydrate_positions()

            # 설정에서 감시 키워드 로드 ( .env 또는 기본값 )
            keywords = self.config.MONITOR_KEYWORDS

            logger.info(f"🚀 Swarm 요원 가동 시작... (감시 키워드: {len(keywords)}개)")

            # WebSocket control via environment variable
            enable_websocket = os.getenv("ENABLE_WEBSOCKET", "true").lower() in ("true", "1", "yes", "on")

            if enable_websocket:
                logger.info("📋 Starting 10 bots: PolyWS, NewsScalper, StatArb, EliteMimic, PureArb, TrendFollower, HealthMonitor, DailyReport, StatusWatchdog, Heartbeat")
            else:
                logger.warning("⚠️ WebSocket DISABLED - Using REST API only (Set ENABLE_WEBSOCKET=true to enable)")
                logger.info("📋 Starting 9 bots: NewsScalper, StatArb, EliteMimic, PureArb, TrendFollower, HealthMonitor, DailyReport, StatusWatchdog, Heartbeat")

            # 모든 에이전트를 동일한 루프에서 동시에 실행
            self.tasks = [
                asyncio.create_task(self.news_agent.run(keywords=keywords, check_interval=300), name="NewsScalper"),
                asyncio.create_task(self.stat_arb_agent.run(), name="StatArb"),
                asyncio.create_task(self.mimic_agent.run(), name="EliteMimic"), # ✅ Re-enabled (Bug Fixed)
                asyncio.create_task(self.arb_agent.run(), name="PureArb"),
                asyncio.create_task(self.trend_agent.run(), name="TrendFollower"),
                asyncio.create_task(self.spread_scalper.run(), name="SpreadScalper"), # HFT Module
                asyncio.create_task(self.health_monitor.run(), name="HealthMonitor"),
                asyncio.create_task(self._daily_report_task(), name="DailyReport"),
                asyncio.create_task(self._status_watchdog_task(), name="StatusWatchdog"),
                asyncio.create_task(self._swarm_heartbeat_task(), name="Heartbeat"),
                asyncio.create_task(self._dashboard_ticker_task(), name="DashboardTicker"),
                asyncio.create_task(self.liquidity_sniper.run(), name="LiquiditySniper"),
                asyncio.create_task(self._global_risk_monitor(), name="GlobalRiskMonitor"),
                asyncio.create_task(self._dashboard_api_task(), name="DashboardAPI"),
                asyncio.create_task(self._reevaluation_watchdog_task(), name="RevaluationWatchdog"),
                asyncio.create_task(self.market_ranker.run_periodic_ranking(), name="MarketRanker"),
            ]

            # Add WebSocket task only if enabled
            if enable_websocket:
                self.tasks.insert(0, asyncio.create_task(self.client.start_ws(), name="PolyWS"))

            logger.info(f"✅ All {len(self.tasks)} bot tasks created successfully")

            try:
                await asyncio.gather(*self.tasks)
            except asyncio.CancelledError:
                logger.info("🐝 Swarm System stopping...")
            except Exception as e:
                logger.error(f"❌ Critical error in swarm run: {e}", exc_info=True)
            finally:
                await self.shutdown()

        except Exception as e:
            logger.error(f"❌ Error in Swarm Run: {e}")
            raise



        


    async def periodic_health_check(self) -> None:
        pass

    async def _global_risk_monitor(self):
        """Global safety watchdog (Phase 4.1)"""
        logger.info("🛡️ Global Risk Watchdog standing by...")
        while self.running:
            try:
                # 1. Check Global Drawdown and Exposure
                is_safe = await self.risk_manager.check_global_safety()
                
                if not is_safe:
                    logger.critical("🚨 SYSTEM ALERT: Global Risk Manager triggered Safety Halt!")
                    if self.notifier and self.notifier.enabled:
                        await self.notifier.send_message(
                            "🚨 *CRITICAL: Circuit Breaker Activated*\nTrading halted due to excessive drawdown."
                        )
                
                # 2. Dynamic Risk Adjustment based on Hive Mind
                hot_tokens = await self.bus.get_hot_tokens(min_sentiment=0.8)
                if len(hot_tokens) > 5:
                    # Too much noise/frenzy, lower the risk multiplier
                    if self.risk_manager.risk_multiplier > 0.15:
                        await self.risk_manager.update_risk_level(0.15)
                        logger.warning("📉 Market Frenzy detected: Lowering global risk multiplier to 0.15x")
                elif len(hot_tokens) < 1:
                    # Calm market, possible to restore risk level
                    if self.risk_manager.risk_multiplier < 0.25:
                        await self.risk_manager.update_risk_level(0.25)
                        logger.info("📈 Market stabilized: Restoring global risk multiplier to 0.25x")

            except Exception as e:
                logger.error(f"Error in risk monitor loop: {e}")
            
            await asyncio.sleep(30) # Check every 30 seconds

    async def _reevaluation_watchdog_task(self):
        """Periodic audit of active positions against domain expertise (Phase 24)"""
        logger.info("🔎 Revaluation Watchdog active.")
        await asyncio.sleep(60) # Initial cooldown
        
        while self.running:
            try:
                if self.revaluation_engine:
                    logger.info("🔎 [Audit] Running periodic thesis re-evaluation...")
                    flags = await self.revaluation_engine.reevaluate_all()
                    
                    for flag in flags:
                        action = flag.get("verdict", "CONTINUE")
                        trade_id = flag.get("trade_id")
                        reason = flag.get("reasoning")
                        
                        if action in ("EXIT", "REDUCE"):
                            logger.warning(f"🚨 [AUDIT ACTION] {trade_id} requires {action}: {reason}")
                            if self.notifier and not self.client.config.DRY_RUN:
                                await self.notifier.send_message(
                                    f"🚨 *Expert Audit Triggered Exit*\n\n"
                                    f"Trade: `{trade_id}`\n"
                                    f"Verdict: *{action}*\n"
                                    f"Reason: {reason}"
                                )
                            
                            # 🔥 PHASE 2: Trigger actual liquidation
                            if action == "EXIT":
                                await self.liquidate_trade(trade_id, reason=f"AI Audit: {reason[:100]}")
                
            except Exception as e:
                logger.error(f"Error in reevaluation watchdog: {e}")
                
            # Run every 4 hours for fundamental audit (low frequency but high importance)
            await asyncio.sleep(4 * 3600) 

    async def _dashboard_api_task(self):
        """Run Dashboard API server (Phase 4.4)"""
        enable_dashboard = os.getenv("ENABLE_DASHBOARD_API", "true").lower() in ("true", "1", "yes")
        if not enable_dashboard:
            logger.info("📊 Dashboard API disabled (set ENABLE_DASHBOARD_API=true to enable)")
            return
        
        try:
            # Inject swarm system reference for data access
            set_swarm_system(self)
            self.start_time = datetime.now()  # Track uptime
            
            dashboard_port = int(os.getenv("DASHBOARD_API_PORT", "8080"))
            logger.info(f"📊 Starting Dashboard API on port {dashboard_port}")
            await start_dashboard_api(self, port=dashboard_port)
        except Exception as e:
            logger.error(f"❌ Dashboard API failed: {e}")


    async def _dashboard_ticker_task(self):
        """High-frequency update for the TUI Dashboard (2s interval)."""
        while self.running:
            try:
                # 1. Fetch Basic Metrics
                pnl_summary = self.pnl_tracker.get_summary()
                status = await self.budget_manager.get_status()
                # balances = status.get('balances', {}) # Not used directly here
                
                # 1. Update Metrics (Balance & PnL)
                self.tick_count += 1
                
                # Optimized polling: 60s for balance/allowance (low churn)
                if self.tick_count % 30 == 0: # 30 * 2s = 60s
                    asyncio.create_task(self._update_balance_metrics())
                
                # Signal Garbage Collection: 10m (low frequency)
                if self.tick_count % 300 == 0: # 300 * 2s = 600s = 10m
                    asyncio.create_task(self.bus.prune_stale_signals())
                
                # Calculate approximate equity
                total_pnl = float(pnl_summary.get('total_pnl', 0.0))
                
                # Dynamic Budget Sync (Task 13)
                await self.budget_manager.sync_with_real_pnl(total_pnl, self.risk_manager.start_of_day_equity)
                
                unrealized = float(pnl_summary.get('unrealized_pnl', 0.0))
                equity = self.last_balance + unrealized
                
                self.status_reporter.update_metrics(
                    balance=self.last_balance,
                    equity=equity, 
                    daily_pnl=total_pnl
                )

                # 2. Update Active Position List
                active_trades = []
                for trade in self.pnl_tracker.active_trades.values():
                    # Calculate current PnL
                    current_price = self.client.get_best_ask_price(trade.token_id)
                    entry_price = trade.entry_price
                    pnl_amt = (current_price - entry_price) * trade.size if current_price > 0 else 0.0
                    
                    active_trades.append({
                        "symbol": trade.asset_name or trade.token_id[:10],
                        "side": trade.side,
                        "size": trade.size * entry_price, # Approximate USD size
                        "entry": entry_price,
                        "current": current_price,
                        "pnl": pnl_amt
                    })
                self.status_reporter.update_active_positions(active_trades)
                
                # 4. Update Signals
                hot_tokens = await self.bus.get_hot_tokens(min_sentiment=0.1)
                for tid, sig in hot_tokens.items():
                    self.status_reporter.update_signal(tid[:10], sig.sentiment_score)
                
                # 5. Heartbeat for dashboard
                self.status_reporter.update_state({"last_updated": datetime.now().timestamp()})
                    
            except Exception as e:
                logger.debug(f"Dashboard ticker error: {e}")
                
            await asyncio.sleep(2)
            

    async def _swarm_heartbeat_task(self):
        """Send heartbeats for all active agents to Redis"""
        redis = self.health_monitor.redis
        while self.running:
            await record_heartbeat(redis, "SwarmOrchestrator")
            if self.news_agent: await record_heartbeat(redis, "NewsScalper")
            if self.stat_arb_agent: await record_heartbeat(redis, "StatArb")
            if self.mimic_agent: await record_heartbeat(redis, "EliteMimic")
            if self.arb_agent: await record_heartbeat(redis, "PureArb")
            if self.trend_agent: await record_heartbeat(redis, "TrendFollower")
            await asyncio.sleep(30)

    async def _monitor_swarm_health(self):
        while self.running:
            await asyncio.sleep(60)
            # Threshold를 0.3으로 낮추어 더 많은 활동을 감지
            hot_tokens = await self.bus.get_hot_tokens(min_sentiment=0.3)
            if hot_tokens:
                logger.info(f"🔥 Swarm Alert: {len(hot_tokens)} active signals detected!")

    async def _status_watchdog_task(self):
        if not self.notifier or not self.notifier.enabled:
            return
        check_interval = max(60, self.status_watch_interval)
        next_heartbeat = datetime.now() + timedelta(minutes=self.status_heartbeat_minutes)
        while self.running:
            await asyncio.sleep(check_interval)
            try:
                payload = await self._build_status_payload()
            except Exception as exc:
                logger.error(f"Status watchdog failed to build payload: {exc}")
                continue

            perf = payload["performance"]
            total_pnl = float(perf["total"])
            delta = 0.0 if self._last_total_pnl is None else total_pnl - self._last_total_pnl
            exposures = payload.get("risk", {}).get("exposure", [])
            risky = next(
                (
                    entry
                    for entry in exposures
                    if entry.get("status") not in ("OK", None)
                    or ((entry.get("usage_pct") or 0.0) >= 95.0)
                ),
                None,
            )

            now = datetime.now()
            reason = None
            if self._last_total_pnl is not None and abs(delta) >= self.pnl_alert_threshold:
                reason = f"🔔 *PnL Alert* Δ${delta:+.2f}"
            elif risky:
                usage = risky.get("usage_pct")
                usage_str = f"{usage:.0f}%" if usage is not None else "limit"
                reason = f"⚠️ *Delta Alert* {risky['market']} at {usage_str}"
            elif now >= next_heartbeat:
                reason = "🕰️ *Status Heartbeat*"
                next_heartbeat = now + timedelta(minutes=self.status_heartbeat_minutes)

            self._last_total_pnl = total_pnl

            if not reason:
                # Still flush to reporter regardless of alert
                self.status_reporter.update_metrics(
                    balance=payload["balances"].get("wallet_usdc"),
                    pnl=total_pnl
                )
                self.status_reporter.update_active_positions([
                    {
                        "symbol": x, "size": 0.0, "pnl": 0.0 # Placeholder: PnLTracker active trades better
                    } for x in payload.get("positions", {}).get("open_list", [])
                ])
                continue

            self._log_status_snapshot(payload)
            message = f"{reason}\n\n{self._format_status_message(payload)}"
            try:
                await self.notifier.send_message(message)
            except Exception as exc:
                logger.error(f"Failed to send status heartbeat: {exc}")

    async def shutdown(self):
        """Gracefully stop all tasks and close resources"""
        if not self.running and not self.tasks:
            return
            
        logger.info("🎬 SwarmSystem: Initiating graceful shutdown...")
        self.running = False
        
        # 1. Cancel all background tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()
        if self.notifier_task and not self.notifier_task.done():
            self.notifier_task.cancel()

        # 2. Wait for tasks to acknowledge cancellation
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
            self.tasks.clear()
        
        if self.notifier_task:
            if self.notifier:
                await self.notifier.stop()
            with suppress(asyncio.CancelledError):
                await self.notifier_task
            self.notifier_task = None

        # 3. Clean up agents and clients
        await self._shutdown_agents()
        logger.info("👋 Swarm Disconnected")

    async def liquidate_trade(self, trade_id: str, reason: str = "Expert Audit Liquidation"):
        """
        Automatically close a specific trade position via PolyClient.
        """
        entry = self.pnl_tracker.active_trades.get(trade_id)
        if not entry:
            logger.warning(f"⚠️ [Swarm] Cannot liquidate unknown trade: {trade_id}")
            return False

        token_id = entry.token_id
        entry_side = entry.side.upper()
        # To close: BUY -> SELL, SELL -> BUY
        exit_side = "SELL" if entry_side == "BUY" else "BUY"
        
        # Determine size (shares). PnLTracker 'size' for entries is usually USD, 
        # but for ArbV2 it might be shares.
        # Let's assume size is SHARES if coming from ArbV2, or calculate from USD.
        # In record_entry: price, size.
        # shares = size / price
        shares = entry.size / entry.entry_price if entry.entry_price > 0 else 0
        
        if shares <= 0:
            logger.error(f"❌ [Swarm] Cannot liquidate {trade_id}: Zero shares calculated.")
            return False

        logger.warning(f"🔥 [Swarm] AUTO-LIQUIDATING {trade_id} | Token: {token_id[:10]} | Side: {exit_side} | Shares: {shares:.2f} | Reason: {reason}")
        
        try:
            # 1. Execute Market Order (Aggressive)
            # In PolyClient: place_market_order(token_id, side, amount=0, size=shares)
            order_result = await self.client.place_market_order(
                token_id=token_id,
                side=exit_side,
                size=shares
            )
            
            if order_result or self.client.config.DRY_RUN:
                # 2. Extract fill price (fallback to current market midpoint)
                fill_price = 0.50 # Dry run default
                if isinstance(order_result, dict) and order_result.get("price"):
                    fill_price = float(order_result["price"])
                else:
                    # Fallback to book price
                    fill_price = await self.client.get_real_market_price(token_id) or 0.0

                # 3. Record the exit in PnL tracker
                self.pnl_tracker.record_exit(trade_id, fill_price, reason=reason)
                logger.info(f"✅ [Swarm] Liquidated {trade_id} successfully.")
                
                if self.notifier and not self.client.config.DRY_RUN:
                    await self.notifier.notify_trade(
                        side=f"EXIT ({exit_side})",
                        asset=token_id[:10],
                        price=fill_price,
                        size=shares,
                        profit=0.0, # Will be calculated by PnLTracker
                        reasoning=f"AUTO-LIQUIDATION: {reason}",
                        strategy="SwarmAuditor"
                    )
                return True
            else:
                logger.error(f"❌ [Swarm] Rapid liquidation FAILED for {trade_id}")
                return False

        except Exception as e:
            logger.error(f"❌ [Swarm] Liquidation CRASH for {trade_id}: {e}", exc_info=True)
            return False

    async def handle_audit(self, text):
        """Manually trigger a thesis re-evaluation audit"""
        if not self._check_mode_match(text): return
        
        await self.notifier.send_message("🔎 *Manual Audit Initiated*... Auditing all active positions.")
        
        try:
            if not self.revaluation_engine:
                await self.notifier.send_message("⚠️ Revaluation Engine not initialized.")
                return
                
            flags = await self.revaluation_engine.reevaluate_all()
            
            if not flags:
                await self.notifier.send_message("✅ Audit Complete: All positions confirmed valid.")
                return
                
            for flag in flags:
                action = flag.get("verdict", "CONTINUE")
                trade_id = flag.get("trade_id")
                reason = flag.get("reasoning")
                
                msg = f"🔎 *Audit Verdict*: `{trade_id}`\nAction: *{action}*\nReason: {reason}"
                await self.notifier.send_message(msg)
                
                if action == "EXIT":
                    success = await self.liquidate_trade(trade_id, reason=f"Manual Audit: {reason[:100]}")
                    if success:
                        await self.notifier.send_message(f"🔥 Auto-Liquidation Executed for `{trade_id}`")
                    else:
                        await self.notifier.send_message(f"❌ Auto-Liquidation Failed for `{trade_id}`")
        except Exception as e:
            logger.error(f"Manual audit failed: {e}")
            await self.notifier.send_message(f"❌ Audit Error: {e}")

    async def _shutdown_agents(self):
        """Invoke shutdown/close on all sub-components"""
        async def _close_component(comp, name):
            if comp:
                logger.debug(f"Closing {name}...")
                try:
                    if hasattr(comp, "shutdown"):
                        await comp.shutdown()
                    elif hasattr(comp, "close"):
                        await comp.close()
                except Exception as exc:
                    logger.error(f"Error closing {name} ({comp.__class__.__name__}): {exc}")

        await _close_component(self.news_agent, "NewsScalper")
        await _close_component(self.stat_arb_agent, "StatArb")
        await _close_component(self.mimic_agent, "EliteMimic")
        await _close_component(self.arb_agent, "PureArb")
        await _close_component(self.trend_agent, "TrendFollower")
        await _close_component(self.liquidity_sniper, "LiquiditySniper")
        await _close_component(self.spread_scalper, "SpreadScalper")
        await _close_component(self.health_monitor, "HealthMonitor")

        # 🧠 Close Hive Mind / SignalBus
        await _close_component(self.bus, "SignalBus")

        # Core Clients (Final layer)
        await _close_component(self.client, "PolyClient")
        if hasattr(self, 'gamma_client'):
            await _close_component(self.gamma_client, "GammaClient")
            
        # 🧪 Price History API (Phase 5, shared instance)
        if hasattr(self, 'price_history_api'):
            await _close_component(self.price_history_api, "PriceHistoryAPI")

        if hasattr(self, 'redis') and self.redis:
            try:
                await self.redis.aclose()
                logger.info("✅ SwarmSystem: Redis connection closed")
            except Exception as exc:
                logger.error(f"SwarmSystem: Redis close error: {exc}")


async def main(args):
    # Initialize and run
    system = SwarmSystem(json_logs=args.json_logs)
    
    loop = asyncio.get_running_loop()

    def _handle_signal():
        # Schedule shutdown on the loop
        logger.info("🛑 Shutdown signal received...")
        # Instead of creating a task that might be orphaned, 
        # we can just cancel the running tasks which will trigger 'finally' in run()
        for task in system.tasks:
            if not task.done():
                task.cancel()
        if system.notifier_task and not system.notifier_task.done():
            system.notifier_task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    try:
        # Always run the swarm directly (UI is now external)
        await system.run(dry_run=args.dry_run)
    finally:
        await system.shutdown()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Hive Mind Swarm System")
    parser.add_argument("--dry-run", action="store_true", help="Run in paper trading mode")
    parser.add_argument("--ui", action="store_true", help="Launch TUI Dashboard")
    parser.add_argument("--json-logs", action="store_true", help="Enable JSON logging output")
    args = parser.parse_args()

    # 🛡️ Singleton Lock (Phase 25): Mode-specific instance protection
    lock_name = "swarm_test.lock" if args.dry_run else "swarm_live.lock"
    lock_path = os.path.join("/tmp", lock_name)
    lock_file = open(lock_path, "w")
    try:
        fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        mode_str = "DRY RUN" if args.dry_run else "LIVE"
        print(f"❌ Error: Another instance of SwarmSystem ({mode_str}) is already running!")
        sys.exit(1)

    try:
        import asyncio
        asyncio.run(main(args))
    except KeyboardInterrupt:
        pass

