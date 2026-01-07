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
        
        if self.enabled:
            logger.info("📱 Telegram Notifier V2 Enabled")
        else:
            logger.warning("📱 Telegram Notifier disabled (Check .env)")

    def register_command(self, command: str, handler: Callable):
        """Register a command handler (e.g. /status)"""
        self.commands[command] = handler
        logger.info(f"⌨️ Registered Telegram command: {command}")

    async def start_polling(self):
        """Message polling loop with command handling"""
        if not self.enabled: return
        
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
                    if resp.status_code == 200:
                        data = resp.json()
                        for update in data.get("result", []):
                            self.last_update_id = update["update_id"]
                            # Handle both text messages and button callbacks
                            if "message" in update:
                                await self._handle_message(update["message"])
                            elif "callback_query" in update:
                                await self._handle_callback(update["callback_query"])
            except Exception as e:
                logger.error(f"Telegram polling error: {e}")
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

    async def send_message(self, text: str, parse_mode: str = "Markdown", use_menu: bool = False, inline_keyboard: Any = None):
        """Send message with optional menu or inline keyboard"""
        if not self.enabled: return
        
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        
        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}
        elif use_menu:
            # Default control menu
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": "📊 Status", "callback_data": "/status"}, {"text": "📜 History", "callback_data": "/history"}],
                    [{"text": "🛑 STOP", "callback_data": "/stop"}, {"text": "▶️ RESUME", "callback_data": "/resume"}]
                ]
            }

        try:
            async with httpx.AsyncClient() as client:
                await client.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    async def send_menu(self, text: str):
        """Helper to send a message with the main control menu"""
        await self.send_message(text, use_menu=True)

    # --- Rich Trading Notifications ---

    async def notify_trade(self, side: str, asset: str, price: float, size: float, profit: float = 0.0, condition_id: str = ""):
        """Enhanced trade notification with Polymarket links"""
        emoji = "📈" if side.upper() == "YES" or side.upper() == "BUY" else "📉"
        
        market_link = f"https://polymarket.com/event/{condition_id}" if condition_id else ""
        link_text = f"\n🔗 [View on Polymarket]({market_link})" if market_link else ""

        text = (
            f"{emoji} *TRADE EXECUTED* {emoji}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*Asset:* `{asset}`\n"
            f"*Action:* {side.upper()}\n"
            f"*Size:* `${size:.2f}`\n"
            f"*Price:* `${price:.4f}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *Expected PnL:* `${profit:+.4f}`\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
            f"{link_text}"
        )
        
        # Inline button for specific market
        keyboard = None
        if market_link:
            keyboard = [[{"text": "🌐 Open Market", "url": market_link}]]
            
        await self.send_message(text, inline_keyboard=keyboard)

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
