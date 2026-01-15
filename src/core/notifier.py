import httpx
import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, List, Callable, Any
from decimal import Decimal

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """
    Enhanced Telegram Command & Control System.
    Includes support for inline keyboards, rich notifications, and prioritized alerts.
    """
    def __init__(self, token: Optional[str], chat_id: Optional[str]):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
        self.base_url = f"https://api.telegram.org/bot{token}" if self.enabled else ""
        self.last_update_id = 0
        self.commands: Dict[str, Callable] = {}
        self._poll_error_streak = 0
        
        # Rate Limiting
        self._msg_queue = asyncio.Queue()
        self._worker_task = None
        
        if self.enabled:
            logger.info("📱 Telegram Notifier V2 Enabled (HTML Mode + Rate Limiting)")
        else:
            logger.warning("📱 Telegram Notifier disabled (Check .env)")

    def register_command(self, command: str, handler: Callable):
        """Register a command handler (e.g. /status)"""
        self.commands[command] = handler
        logger.info(f"⌨️ Registered Telegram command: {command}")

    async def start_polling(self):
        """Message polling loop + Queue Worker"""
        if not self.enabled: return
        
        # Start Queue Worker
        if not self._worker_task:
            self._worker_task = asyncio.create_task(self._process_queue())
        
        logger.info("👂 Telegram Listener Active...")
        # startup message moved to orchestrator to avoid duplication
        
        while True:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{self.base_url}/getUpdates",
                        params={"offset": self.last_update_id + 1, "timeout": 30},
                        timeout=35
                    )
                if resp.status_code != 200:
                    self._poll_error_streak += 1
                    preview = resp.text[:200] if hasattr(resp, "text") else ""
                    logger.error(f"Telegram polling HTTP {resp.status_code}: {preview}")
                    await asyncio.sleep(min(30, 1 + self._poll_error_streak * 2))
                    continue

                self._poll_error_streak = 0
                data = resp.json()
                for update in data.get("result", []):
                    self.last_update_id = update["update_id"]
                    # Handle both text messages and button callbacks
                    if "message" in update:
                        await self._handle_message(update["message"])
                    elif "callback_query" in update:
                        await self._handle_callback(update["callback_query"])
            
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
                self._poll_error_streak += 1
                wait_time = min(60, 2 * self._poll_error_streak)
                logger.warning(f"⚠️ Telegram connection issue (Streak: {self._poll_error_streak}): {e}. Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)
                continue

            except Exception as e:
                self._poll_error_streak += 1
                logger.error(f"Telegram polling error ({type(e).__name__}): {e}", exc_info=True)
                await asyncio.sleep(min(30, 1 + self._poll_error_streak * 2))
                continue
            await asyncio.sleep(1)

    async def _handle_message(self, message: Dict):
        text = message.get("text", "")
        chat_id = str(message["chat"]["id"])
        
        if chat_id != str(self.chat_id).strip():
            logger.warning(f"🚫 Unauthorized access from {chat_id}")
            return

        if not text.startswith("/"):
            # Provide menu if user just says something
            await self.send_menu("How can I help you today?")
            return

        cmd = text.split()[0].lower()
        if cmd in self.commands:
            await self.commands[cmd](text)
        else:
            await self.send_message(f"❓ Unknown command: {cmd}", use_menu=True)

    async def _handle_callback(self, query: Dict):
        """Handle inline button clicks"""
        data = query.get("data", "")
        # Map callback data to commands
        if data.startswith("/"):
            if data in self.commands:
                await self.commands[data]("")
            else:
                await self.send_message(f"Command {data} not registered.")
        
        # Acknowledge callback to stop loading spinner in UI
        try:
            async with httpx.AsyncClient() as client:
                await client.post(f"{self.base_url}/answerCallbackQuery", json={
                    "callback_query_id": query["id"]
                })
        except: pass

    async def _process_queue(self):
        """Background worker to send messages with rate limiting (20/min per chat ~ 3s delay)"""
        while True:
            try:
                task = await self._msg_queue.get()
                text, parse_mode, keyboard = task
                
                await self._send_payload(text, parse_mode, keyboard)
                self._msg_queue.task_done()
                
                # Rate limit: 1 message every 3 seconds to be safe
                await asyncio.sleep(3.0) 
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Telegram queue error: {e}")

    async def send_message(self, text: str, parse_mode: str = "HTML", use_menu: bool = False, inline_keyboard: Any = None):
        """Enqueue message for sending"""
        if not self.enabled: return
        
        keyboard = None
        if inline_keyboard:
            keyboard = {"inline_keyboard": inline_keyboard}
        elif use_menu:
             keyboard = {
                "inline_keyboard": [
                    [{"text": "📊 Status", "callback_data": "/status"}, {"text": "📜 History", "callback_data": "/history"}],
                    [{"text": "🛑 STOP", "callback_data": "/stop"}, {"text": "▶️ RESUME", "callback_data": "/resume"}]
                ]
            }
            
        await self._msg_queue.put((text, parse_mode, keyboard))

    async def _send_payload(self, text, parse_mode, reply_markup):
        """Internal sender"""
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
            
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
            
            if resp.status_code != 200:
                logger.error(f"Telegram send failed {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            logger.error(f"Telegram connection failed: {e}")

    async def send_menu(self, text: str):
        """Helper to send a message with the main control menu"""
        await self.send_message(text, use_menu=True)

    # --- Rich Trading Notifications ---

    async def notify_trade(
        self, 
        side: str, 
        asset: str, 
        price: float, 
        size: float, 
        profit: float = 0.0, 
        condition_id: str = "", 
        brain_score: float = 1.0,
        reasoning: str = "",
        strategy: str = "Unknown"
    ):
        """Enhanced HTML trade notification with Brain Score & Reasoning"""
        emoji = "🟢" if side.upper() in ["YES", "BUY"] else "🔴"
        
        market_link = f"https://polymarket.com/event/{condition_id}" if condition_id else ""
        link_text = f'\n🔗 <a href="{market_link}">View on Polymarket</a>' if market_link else ""

        # Brain Context
        brain_text = ""
        if brain_score > 1.0:
            brain_text = f"🧠 <b>Brain Boost:</b> x{brain_score:.2f} (High Confidence)\n"
        elif brain_score < 1.0:
            brain_text = f"🧠 <b>Brain Penalty:</b> x{brain_score:.2f} (Caution)\n"

        # Reasoning Section
        reasoning_text = ""
        if reasoning:
            reasoning_text = f"💡 <b>AI Prediction:</b>\n<i>{reasoning}</i>\n"

        text = (
            f"{emoji} <b>TRADE EXECUTED</b> | {strategy}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Asset:</b> <code>{asset}</code>\n"
            f"<b>Action:</b> {side.upper()}\n"
            f"<b>Size:</b> ${size:.2f}\n"
            f"<b>Price:</b> ${price:.4f}\n"
            f"{brain_text}"
            f"{reasoning_text}"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Exp. PnL:</b> ${profit:+.4f}\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
            f"{link_text}"
        )
        
        # Inline button
        keyboard = None
        if market_link:
            keyboard = [[{"text": "🌐 Open Market", "url": market_link}]]
            
        await self.send_message(text, inline_keyboard=keyboard)

    async def notify_daily_summary(self, stats: Dict):
        """Send daily performance summary"""
        text = (
            f"📅 <b>DAILY REPORT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Trades:</b> {stats.get('total_trades', 0)}\n"
            f"<b>Volume:</b> ${stats.get('total_volume', 0.0):,.2f}\n"
            f"<b>Wins:</b> {stats.get('wins', 0)}\n"
            f"<b>Gains:</b> ${stats.get('pnl', 0.0):+,.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 <b>Bot Health:</b> 100% Active"
        )
        await self.send_message(text)


    async def send_alert(self, level: str, title: str, message: str):
        """Prioritized alerts: INFO, WARNING, CRITICAL"""
        emojis = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🚨", "SUCCESS": "✅"}
        emoji = emojis.get(level.upper(), "🔔")
        
        text = (
            f"{emoji} *{level.upper()}: {title}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{message}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {datetime.now().strftime('%m/%d %H:%M:%S')}"
        )
        await self.send_message(text)

    async def notify_position_closed(self, asset: str, pnl_usd: float, duration_hrs: float):
        """Notification for closed positions"""
        emoji = "💰" if pnl_usd >= 0 else "💸"
        text = (
            f"{emoji} *POSITION CLOSED* {emoji}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*Asset:* `{asset}`\n"
            f"*Profit:* `${pnl_usd:+.2f}`\n"
            f"*Held for:* `{duration_hrs:.1f} hours`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *New Balance:* Updating..."
        )
        await self.send_message(text, use_menu=True)
