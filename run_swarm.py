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

# Strategies & Agents
from src.news.news_scalper_optimized import OptimizedNewsScalper
from src.strategies.stat_arb_enhanced import EnhancedStatArbStrategy
from src.strategies.elite_mimic import EliteMimicAgent
from src.strategies.arbitrage import ArbitrageStrategy
from src.strategies.trend_follower import SmartTrendFollower

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
        self.pnl_tracker = PnLTracker()
        self.delta_tracker = DeltaTracker(self.bus, delta_limits=self.config.DELTA_LIMITS)
        self.budget_manager = None
        self.notifier = None
        self.health_monitor = None
        self.s_logger = None
        
        # Dashboard Reporter
        self.status_reporter = StatusReporter()
        
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

        self.s_logger = StructuredLogger("SwarmOrchestrator")
        self.s_logger.info(f"🐝 Initializing Swarm Intelligence System... (Mode: {'DRY RUN' if dry_run else 'LIVE'})")

        # 0. Init Notifier & Commands
        self.notifier = TelegramNotifier(
            token=os.getenv("TELEGRAM_BOT_TOKEN"),
            chat_id=os.getenv("TELEGRAM_CHAT_ID")
        )
        self._register_commands()

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
            market_specialist=self.market_specialist
        )

        # 2. Stat Arb
        self.stat_arb_agent = EnhancedStatArbStrategy(
            client=self.client,
            budget_manager=self.budget_manager,
            pnl_tracker=self.pnl_tracker,
            delta_tracker=self.delta_tracker
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

        # 4. Pure Arb
        self.arb_agent = ArbitrageStrategy(
            client=self.client, 
            gamma_client=self.gamma_client, # 🎯 Inject Gamma Client
            signal_bus=self.bus, 
            budget_manager=self.budget_manager
        )
        self.arb_agent.notifier = self.notifier

        # 5. Trend Follower
        self.trend_agent = SmartTrendFollower(
            client=self.client,
            budget_manager=self.budget_manager
        )

        # 5. Health Monitor
        import redis.asyncio as aioredis
        redis = aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost"))
        self.health_monitor = await get_health_monitor(
            redis=redis,
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

        lines.extend(
            [
                "",
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
                    self.news_agent.hydrate_position(token_id, size, entry_price)

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
                asyncio.create_task(self.mimic_agent.run(), name="EliteMimic"),
                asyncio.create_task(self.arb_agent.run(), name="PureArb"),
                asyncio.create_task(self.trend_agent.run(), name="TrendFollower"),
                asyncio.create_task(self.health_monitor.run(), name="HealthMonitor"),
                asyncio.create_task(self._daily_report_task(), name="DailyReport"),
                asyncio.create_task(self._status_watchdog_task(), name="StatusWatchdog"),
                asyncio.create_task(self._swarm_heartbeat_task(), name="Heartbeat"),
                asyncio.create_task(self._dashboard_ticker_task(), name="DashboardTicker"),
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
                    balance=float(balances.get('total_equity', 0.0)),
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
                
                # 5. Dump State for TUI
                self._dump_dashboard_state()
                    
            except Exception as e:
                logger.debug(f"Dashboard ticker error: {e}")
                
            await asyncio.sleep(2)
            
    def _dump_dashboard_state(self):
        """Dump current state to JSON for external dashboard"""
        try:
            import json
            pnl = self.pnl_tracker.get_summary()
            
            # Active positions
            positions = []
            for tid, t in self.pnl_tracker.active_trades.items():
                current_price = self.client.get_best_ask_price(t.token_id) or t.entry_price
                pnl_amt = (current_price - t.entry_price) * t.size if t.side == "BUY" else (t.entry_price - current_price) * t.size
                
                positions.append({
                    "symbol": t.asset_name or t.token_id[:10],
                    "side": t.side,
                    "size": t.size,
                    "entry_price": t.entry_price,
                    "current_price": current_price,
                    "pnl": pnl_amt
                })
            
            state = {
                "timestamp": datetime.now().isoformat(),
                "status": "RUNNING" if self.running else "STOPPED",
                "mode": "DRY RUN" if getattr(self.client.config, 'DRY_RUN', True) else "LIVE",
                "pnl": {
                    "total_net": pnl.get('total_pnl', 0.0),
                    "realized": pnl.get('realized_pnl', 0.0),
                    "unrealized": pnl.get('unrealized_pnl', 0.0),
                    "win_rate": pnl.get('win_rate', 0.0)*100
                },
                "positions": positions,
                "active_signals": len(hot_tokens) if 'hot_tokens' in locals() else 0
            }
            
            with open("dashboard_state.json", "w") as f:
                json.dump(state, f, indent=2)
                
        except Exception as e:
            # logger.debug(f"Failed to dump dashboard state: {e}")
            pass

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
        if not self.running:
            return
        self.running = False
        for task in self.tasks:
            task.cancel()
        if self.notifier_task:
            self.notifier_task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        if self.notifier_task:
            with suppress(asyncio.CancelledError):
                await self.notifier_task
            self.notifier_task = None

        await self._shutdown_agents()
        logger.info("👋 Swarm Disconnected")

    async def _shutdown_agents(self):
        async def _close_agent(agent):
            if agent and hasattr(agent, "shutdown"):
                try:
                    await agent.shutdown()
                except Exception as exc:
                    logger.error(f"Agent shutdown error ({agent.__class__.__name__}): {exc}")

        await _close_agent(self.news_agent)
        await _close_agent(self.stat_arb_agent)
        await _close_agent(self.mimic_agent)
        await _close_agent(self.arb_agent)
        await _close_agent(self.trend_agent)
        await _close_agent(self.health_monitor)

        if self.client:
            try:
                await self.client.close()
            except Exception as exc:
                logger.error(f"PolyClient close error: {exc}")

        if self.gamma_client and hasattr(self.gamma_client, "close"):
            try:
                await self.gamma_client.close()
            except Exception as exc:
                logger.error(f"GammaClient close error: {exc}")


async def main(args):
    # Initialize and run
    system = SwarmSystem(json_logs=args.json_logs)
    
    loop = asyncio.get_running_loop()

    def _handle_signal():
        logger.info("🛑 Shutdown signal received...")
        asyncio.create_task(system.shutdown())

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

