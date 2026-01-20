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
from src.core.global_risk_manager import GlobalRiskManager
from src.core.trade_repository import TradeRepository
from src.core.dashboard_api import start_dashboard_api, set_swarm_system

# Strategies & Agents
from src.news.news_scalper_optimized import OptimizedNewsScalper
from src.strategies.stat_arb_enhanced import EnhancedStatArbStrategy
from src.strategies.elite_mimic import EliteMimicAgent
from src.strategies.arbitrage_v2 import PureArbitrageV2
from src.strategies.trend_follower import SmartTrendFollower
from src.strategies.liquidity_sniper import LiquiditySniper

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
        self.status_reporter = StatusReporter()
        
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

        self.running = True
        self.tasks = []
        self.notifier_task = None
        self.status_heartbeat_minutes = int(os.getenv("STATUS_HEARTBEAT_MINUTES", "30"))
        self.status_watch_interval = int(os.getenv("STATUS_WATCH_INTERVAL_SECONDS", "300"))
        self.pnl_alert_threshold = float(os.getenv("STATUS_PNL_ALERT_THRESHOLD", "5.0"))
        self._last_total_pnl = None

    async def setup(self, dry_run: bool = False):
        # Configure advanced logging
        setup_logging(
            level=logging.INFO,
            json_output=self.json_logs,
            log_file=f"logs/swarm_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
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
            self.notifier_task = asyncio.create_task(self.notifier.start_polling())
            await self.notifier.send_message("🚀 *Hive Mind Swarm Intelligence* Online!\nUse /status to check system.")
            logger.info("✅ Telegram Notifier initialized and polling started")
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
                # Attempt to fetch real balance
                balance_str = await self.client.get_usdc_balance()
                initial_capital = float(balance_str)
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

        # 4. Pure Arb V2 (Crypto 15min Optimized)
        self.arb_agent = PureArbitrageV2(
            client=self.client, 
            gamma_client=self.gamma_client, 
            signal_bus=self.bus, 
            budget_manager=self.budget_manager,
            min_profit=0.010, # 1.0% Threshold
            default_trade_size=50.0,
            risk_manager=self.risk_manager,
            pnl_tracker=self.pnl_tracker # Phase 4.3
        )
        self.arb_agent.notifier = self.notifier

        # 5. Trend Follower
        self.trend_agent = SmartTrendFollower(
            client=self.client,
            budget_manager=self.budget_manager
        )

        # 5. Health Monitor
        # Use shared redis connection
        self.health_monitor = await get_health_monitor(
            redis=self.redis,
            budget_manager=self.budget_manager,
            metrics_port=int(os.getenv("METRICS_PORT", "8000"))
        )

        logger.info("✅ All Agents Initialized & Connected to Hive Mind")

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
        self.notifier.register_command("/panic", self.handle_panic)
        self.notifier.register_command("/unpanic", self.handle_unpanic)
        
        # Register Command Menu with Telegram
        menu_commands = [
            {"command": "status", "description": "전체 시스템 상태 및 에이전트 활성 수 확인"},
            {"command": "pnl", "description": "금일 수익 현황 요약"},
            {"command": "risk", "description": "글로벌 리스크 배수(Multiplier) 조정"},
            {"command": "panic", "description": "비상 정지 (회로 차단기 활성화)"},
            {"command": "unpanic", "description": "비상 정지 해제"},
            {"command": "stop", "description": "자동 거래 일시 정지 (Dry Run)"},
            {"command": "resume", "description": "자동 거래 재개"},
            {"command": "history", "description": "최근 거래 내역 확인"},
            {"command": "liquidate", "description": "포지션 청산"},
            {"command": "help", "description": "도움말 보기"}
        ]
        asyncio.create_task(self.notifier.set_my_commands(menu_commands))

        logger.info("✅ Telegram Commands Registered: /help, /status, /stop, /resume, /history, /top, /pnl, /risk, /liquidate, /panic, /unpanic")

    async def handle_help(self, text):
        msg = (
            "🤖 *Hive Mind Swarm System Help*\n\n"
            "*Monitoring:*\n"
            "• /status - Get current balances and signals\n"
            "• /history - View last 5 executed trades\n"
            "• /top - See current best market opportunities\n\n"
            "*Control:*\n"
            "• /stop - Pause all automated trading\n"
            "• /resume - Re-enable automated trading\n"
            "• /pnl - Check daily profit/loss\n\n"
            "*Risk Management:*\n"
            "• /risk <low|mid|high|yolo> - Adjust global risk multiplier\n"
            "• /panic - Activate global circuit breaker (stop all trading)\n"
            "• /unpanic - Deactivate global circuit breaker\n"
            "• /liquidate <token_id|all> - Close positions\n\n"
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

            payload = await self._build_status_payload()
            self._log_status_snapshot(payload)
            message = self._format_status_message(payload)
            await self.notifier.send_message(message)
        except Exception as e:
            logger.exception("❌ Failed to generate status report")
            await self.notifier.send_message(f"⚠️ Failed to fetch status: {e}")

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

        real_wallet_balance = None
        if not self.client.config.DRY_RUN:
            try:
                real_wallet_balance = await self.client.get_usdc_balance()
            except Exception as exc:
                logger.error(f"Live balance fetch failed: {exc}")

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
        pnl_data = self.pnl_tracker.get_summary()
        msg = (
            f"💰 *PnL Report*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Daily PnL: ${pnl_data['total_pnl']:+.2f}\n"
            f"Open Positions: {pnl_data['open_positions']}\n"
            f"Closed Trades: {pnl_data['closed_trades']}"
        )
        await self.notifier.send_message(msg)

    def add_trade_record(self, side, token, price, size, pnl=0.0, condition_id: str = "", brain_score: float = 1.0):
        self.completed_trades.append({
            "time": datetime.now().strftime("%H:%M"),
            "side": side, "asset": token, "price": price, "size": size, "pnl": pnl
        })
        if len(self.completed_trades) > 50: self.completed_trades.pop(0)

        # Notify via Telegram
        if self.notifier and self.notifier.enabled:
             asyncio.create_task(
                self.notifier.notify_trade(
                    side, token, price, size, 
                    profit=pnl,
                    condition_id=condition_id, 
                    brain_score=brain_score
                )
            )


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
                asyncio.create_task(self.health_monitor.run(), name="HealthMonitor"),
                asyncio.create_task(self._daily_report_task(), name="DailyReport"),
                asyncio.create_task(self._status_watchdog_task(), name="StatusWatchdog"),
                asyncio.create_task(self._swarm_heartbeat_task(), name="Heartbeat"),
                asyncio.create_task(self._dashboard_ticker_task(), name="DashboardTicker"),
                asyncio.create_task(self.liquidity_sniper.run(), name="LiquiditySniper"),
                asyncio.create_task(self._global_risk_monitor(), name="GlobalRiskMonitor"),
                asyncio.create_task(self._dashboard_api_task(), name="DashboardAPI"),
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
            raise
        finally:
            await self.shutdown()

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

    async def _daily_report_task(self):
        while self.running:
            await asyncio.sleep(12 * 3600)
            if not self.trade_history: continue
            wins = len([t for t in self.trade_history if t.get('pnl', 0) and t['pnl'] > 0])
            msg = f"📅 *Daily Report*\nTrades: {len(self.trade_history)}\nWin Rate: {(wins/len(self.trade_history)*100):.1f}%"
            if self.notifier and self.notifier.enabled:
                await self.notifier.send_message(msg)

    async def _dashboard_ticker_task(self):
        """High-frequency update for the TUI Dashboard (2s interval)."""
        while self.running:
            try:
                # 1. Fetch Basic Metrics
                pnl_summary = self.pnl_tracker.get_summary()
                status = await self.budget_manager.get_status()
                balances = status.get('balances', {})
                
                # 2. Update Metrics in Reporter
                self.status_reporter.update_metrics(
                    balance=float(status.get('total_capital', 0.0)),
                    pnl=float(pnl_summary['total_pnl'])
                )
                
                # 3. Update Active Positions
                # Transform PnLTracker active_trades to Reporter format
                active_trades = []
                for trade_id, trade in self.pnl_tracker.active_trades.items():
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
                self.status_reporter.update_state({"last_updated": time.time()})
                    
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
        await _close_component(self.health_monitor, "HealthMonitor")

        # 🧠 Close Hive Mind / SignalBus
        await _close_component(self.bus, "SignalBus")

        # Core Clients
        await _close_component(self.client, "PolyClient")
        await _close_component(self.gamma_client, "GammaClient")

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

    # Always run the swarm directly (UI is now external)
    await system.run(dry_run=args.dry_run)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Hive Mind Swarm System")
    parser.add_argument("--dry-run", action="store_true", help="Run in paper trading mode")
    parser.add_argument("--ui", action="store_true", help="Launch TUI Dashboard")
    parser.add_argument("--json-logs", action="store_true", help="Enable JSON logging output")
    args = parser.parse_args()

    try:
        import asyncio
        asyncio.run(main(args))
    except KeyboardInterrupt:
        pass

