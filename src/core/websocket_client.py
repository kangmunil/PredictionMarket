"""
Polymarket CLOB WebSocket Client
=================================

Real-time orderbook streaming for high-frequency arbitrage.
Latency: < 100ms (vs 1-3s for HTTP polling)

Author: ArbHunter V2.1
Updated: 2026-01-03 (WebSocket Implementation)
"""

import asyncio
import logging
import json
import time
from typing import Dict, Callable, Optional, List
from decimal import Decimal
import websockets
from sortedcontainers import SortedDict

logger = logging.getLogger(__name__)


class LocalOrderBook:
    """
    Local in-memory orderbook replica.
    Updates via WebSocket deltas for O(log n) performance.

    Uses SortedDict for automatic price-level sorting:
    - Bids: Descending (highest bid first)
    - Asks: Ascending (lowest ask first)
    """
    def __init__(self, token_id: str):
        self.token_id = token_id
        self.bids = SortedDict()  # {price: size}
        self.asks = SortedDict()  # {price: size}
        self.last_update = time.time()

    def update(self, side: str, price: float, size: float):
        """
        Update orderbook with delta from WebSocket.

        Args:
            side: "BUY" or "SELL"
            price: Price level
            size: New size (0 = remove level)
        """
        price_dec = Decimal(str(price))
        size_dec = Decimal(str(size))

        book = self.bids if side.upper() == "BUY" else self.asks

        if size_dec == 0:
            # Remove price level
            if price_dec in book:
                del book[price_dec]
        else:
            # Update or insert
            book[price_dec] = size_dec

        self.last_update = time.time()

    def get_best_ask(self) -> tuple[Optional[Decimal], Optional[Decimal]]:
        """Returns (price, size) of lowest ask or (None, None)"""
        if not self.asks:
            return None, None
        price, size = self.asks.peekitem(0)  # First item (lowest price)
        return price, size

    def get_best_bid(self) -> tuple[Optional[Decimal], Optional[Decimal]]:
        """Returns (price, size) of highest bid or (None, None)"""
        if not self.bids:
            return None, None
        price, size = self.bids.peekitem(-1)  # Last item (highest price)
        return price, size

    def get_avg_price_for_shares(self, side: str, total_shares: float) -> float:
        """
        Calculate the average price for a specific number of shares.
        """
        book = self.bids if side.upper() == "BUY" else self.asks
        if not book or total_shares <= 0:
            return 0.0

        # For asks (SELL side for client buying), we want ascending prices
        # For bids (BUY side for client selling), we want descending prices
        prices = sorted(book.keys(), reverse=(side.upper() == "BUY"))
        
        remaining_shares = Decimal(str(total_shares))
        weighted_sum = Decimal("0")

        for price in prices:
            size = book[price]
            
            if size >= remaining_shares:
                weighted_sum += (remaining_shares * price)
                remaining_shares = Decimal("0")
                break
            else:
                weighted_sum += (size * price)
                remaining_shares -= size

        if remaining_shares > 0:
            # Not enough liquidity for this many shares
            return 0.0

        return float(weighted_sum / Decimal(str(total_shares)))

    def get_max_shares_within_price(self, side: str, max_avg_price: float) -> float:
        """
        Find the maximum number of shares we can buy/sell without the 
        average price exceeding/dropping below 'max_avg_price'.
        """
        book = self.bids if side.upper() == "BUY" else self.asks
        if not book:
            return 0.0

        prices = sorted(book.keys(), reverse=(side.upper() == "BUY"))
        max_avg_dec = Decimal(str(max_avg_price))
        
        total_shares = Decimal("0")
        weighted_sum = Decimal("0")

        for price in prices:
            # If the best price itself is already worse than max_avg, stop
            if (side.upper() == "SELL" and price > max_avg_dec) or (side.upper() == "BUY" and price < max_avg_dec):
                if total_shares == 0: return 0.0
                break
                
            size = book[price]
            potential_total = total_shares + size
            potential_sum = weighted_sum + (size * price)
            
            current_avg = potential_sum / potential_total
            
            if (side.upper() == "SELL" and current_avg <= max_avg_dec) or (side.upper() == "BUY" and current_avg >= max_avg_dec):
                total_shares = potential_total
                weighted_sum = potential_sum
            else:
                # Calculate partial size from this level to hit exactly max_avg_price
                denom = (price - max_avg_dec)
                if abs(denom) > 1e-12:
                    extra_x = (max_avg_dec * total_shares - weighted_sum) / denom
                    if extra_x > 0:
                        total_shares += extra_x
                break

        return float(total_shares)

    def get_spread(self) -> Optional[Decimal]:
        """Returns bid-ask spread or None"""
        best_bid, _ = self.get_best_bid()
        best_ask, _ = self.get_best_ask()
        if best_bid and best_ask:
            return best_ask - best_bid
        return None


class PolymarketWebSocket:
    """
    High-performance WebSocket client for Polymarket CLOB.
    """

    def __init__(self, url: str = "wss://ws.clob.polymarket.com"):
        self.url = url
        self.ws = None
        self.callbacks: Dict[str, List[Callable]] = {
            'book': [],
            'price_change': [],
            'last_trade_price': []
        }
        self.orderbooks: Dict[str, LocalOrderBook] = {}
        self.subscribed_assets: List[str] = []
        self.running = False
        self.reconnect_delay = 5  # seconds

    def subscribe_callback(self, event_type: str, callback: Callable):
        """
        Register callback for specific event type.

        Args:
            event_type: 'book', 'price_change', or 'last_trade_price'
            callback: async function to call with event data
        """
        if event_type in self.callbacks:
            self.callbacks[event_type].append(callback)
            logger.info(f"✅ Registered callback for {event_type}")
        else:
            logger.warning(f"⚠️ Unknown event type: {event_type}")

    def get_orderbook(self, token_id: str) -> Optional[LocalOrderBook]:
        """Get local orderbook for token"""
        return self.orderbooks.get(token_id)

    async def _send_subscription(self, asset_ids: List[str]):
        """Internal: Send subscription message to WebSocket in chunks"""
        if not asset_ids or not self.ws:
            return

        is_open = False
        if hasattr(self.ws, 'open'):
            is_open = self.ws.open
        elif hasattr(self.ws, 'state'):
            is_open = str(self.ws.state).lower() == "state.open" or self.ws.state == 1
        
        if is_open:
            # Polymarket CLOB V2: Send in chunks of 50 to avoid message size limits
            chunk_size = 50
            for i in range(0, len(asset_ids), chunk_size):
                chunk = asset_ids[i:i + chunk_size]
                # Wrap in a LIST: [{"type": "market", "assets_ids": [...]}]
                sub_payload = [{
                    "type": "market",
                    "assets_ids": chunk
                }]
                await self.ws.send(json.dumps(sub_payload))
                logger.info(f"📡 Sent subscription chunk for {len(chunk)} assets (Wrapped in list)")
                await asyncio.sleep(0.1) # Small delay between chunks
        else:
            logger.warning(f"⚠️ Cannot send subscription, WebSocket not open")

    async def update_subscriptions(self, asset_ids: List[str]):
        """
        Dynamically update subscription list and initialize orderbooks.
        """
        new_assets = []
        for asset_id in asset_ids:
            if asset_id not in self.orderbooks:
                self.orderbooks[asset_id] = LocalOrderBook(asset_id)
                new_assets.append(asset_id)
        
        self.subscribed_assets = list(set(self.subscribed_assets + asset_ids))
        logger.info(f"🔄 Updating subscriptions: {len(new_assets)} new assets, {len(self.subscribed_assets)} total")
        
        if new_assets:
            await self._send_subscription(new_assets)

    async def connect(self, asset_ids: List[str]):
        """
        Connect to WebSocket and subscribe to assets.

        Args:
            asset_ids: List of token_ids to monitor (max 500 recommended)
        """
        self.subscribed_assets = asset_ids
        self.running = True

        # Initialize orderbooks
        for asset_id in asset_ids:
            self.orderbooks[asset_id] = LocalOrderBook(asset_id)

        while self.running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                logger.error(f"❌ WebSocket error: {e}")
                if self.running:
                    logger.info(f"🔄 Reconnecting in {self.reconnect_delay}s...")
                    await asyncio.sleep(self.reconnect_delay)
                else:
                    break

    async def _connect_and_listen(self):
        """Internal: Connect and start listening loop"""
        logger.info(f"🔌 Connecting to {self.url}...")

        # Use built-in ping mechanism of websockets library
        async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as ws:
            self.ws = ws
            logger.info(f"✅ WebSocket connected! (State: {getattr(ws, 'state', 'unknown')})")

            # Send initial subscription message
            if self.subscribed_assets:
                await self._send_subscription(self.subscribed_assets)
            else:
                logger.info("ℹ️ No assets to subscribe to yet. Waiting for discovery.")

            # Main listening loop
            async for message in ws:
                await self._handle_message(message)

    async def _heartbeat(self):
        """Deprecated: using built-in websockets ping instead"""
        pass

    async def _handle_message(self, message: str):
        """Process incoming WebSocket message with extreme logging"""
        if not message: return
        
        # 🚨 CRITICAL DEBUG: Print EVERYTHING for 30 seconds
        logger.info(f"📥 RAW_WS_MSG: {message[:200]}")

        msg_strip = message.strip()
        if not (msg_strip.startswith('{') or msg_strip.startswith('[')): return

        try:
            data = json.loads(msg_strip)
            events = data if isinstance(data, list) else [data]
            
            for event in events:
                # 🔍 Determine event type via multiple possible keys
                e_type = event.get("type") or event.get("event_type")
                
                # Fallback: identify by content
                if not e_type:
                    if "bids" in event or "asks" in event:
                        e_type = "book"
                    elif "price_changes" in event:
                        e_type = "price_change"
                    elif "price" in event and "asset_id" in event:
                        e_type = "last_trade_price"

                if e_type == "book":
                    await self._handle_book_event(event)
                elif e_type == "price_change":
                    await self._handle_price_change(event)
                elif e_type == "last_trade_price":
                    await self._handle_last_trade(event)
                elif e_type == "pong":
                    pass 
                elif e_type == "error":
                    logger.error(f"❌ WebSocket Error: {event.get('message')}")

        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"❌ Message handling error: {e}")

    async def _handle_book_event(self, event: dict):
        """
        Handle orderbook update. Supports both wrapped and direct formats.
        """
        # Format 1: { "type": "book", "events": [ { "asset_id": "...", "bids": [...] } ] }
        book_events = event.get("events", [])
        
        # Format 2: { "asset_id": "...", "bids": [...], "asks": [...] } (Direct)
        if not book_events and ("bids" in event or "asks" in event):
            book_events = [event]

        for book_event in book_events:
            asset_id = book_event.get("asset_id")
            if not asset_id or asset_id not in self.orderbooks:
                continue

            orderbook = self.orderbooks[asset_id]
            bids_before = len(orderbook.bids)
            asks_before = len(orderbook.asks)

            # Update bids
            for entry in book_event.get("bids", []):
                try:
                    if isinstance(entry, dict):
                        price = entry.get("price")
                        size = entry.get("size")
                    else:
                        price, size = entry
                    orderbook.update("BUY", float(price), float(size))
                except (ValueError, TypeError, AttributeError):
                    continue 

            # Update asks
            for entry in book_event.get("asks", []):
                try:
                    if isinstance(entry, dict):
                        price = entry.get("price")
                        size = entry.get("size")
                    else:
                        price, size = entry
                    orderbook.update("SELL", float(price), float(size))
                except (ValueError, TypeError, AttributeError):
                    continue 

            
            logger.debug(f"📊 Updated OB {asset_id[:8]}: Bids {bids_before}->{len(orderbook.bids)}, Asks {asks_before}->{len(orderbook.asks)}")

            # Trigger callbacks
            for callback in self.callbacks['book']:
                try:
                    await callback(asset_id, orderbook)
                except Exception as e:
                    logger.error(f"❌ Callback error: {e}")

    async def _handle_price_change(self, event: dict):
        """Handle price change event"""
        for callback in self.callbacks['price_change']:
            try:
                await callback(event)
            except Exception as e:
                logger.error(f"❌ Callback error: {e}")

    async def _handle_last_trade(self, event: dict):
        """Handle last trade price event"""
        for callback in self.callbacks['last_trade_price']:
            try:
                await callback(event)
            except Exception as e:
                logger.error(f"❌ Callback error: {e}")

    async def disconnect(self):
        """Gracefully disconnect"""
        logger.info("🔌 Disconnecting WebSocket...")
        self.running = False
        if self.ws and not self.ws.closed:
            await self.ws.close()
        logger.info("✅ Disconnected")


# Example usage
async def example_callback(asset_id: str, orderbook: LocalOrderBook):
    """Example callback function"""
    best_ask_price, best_ask_size = orderbook.get_best_ask()
    best_bid_price, best_bid_size = orderbook.get_best_bid()
    spread = orderbook.get_spread()

    logger.info(f"""
    📊 [{asset_id[:8]}...] Orderbook Update:
       Best Bid: {best_bid_price} ({best_bid_size} shares)
       Best Ask: {best_ask_price} ({best_ask_size} shares)
       Spread:   {spread}
    """)


async def main():
    """Test WebSocket connection"""
    ws = PolymarketWebSocket()

    # Register callback
    ws.subscribe_callback('book', example_callback)

    # Example asset IDs (replace with real ones)
    test_assets = [
        "21742633143463906290569050155826241533067272736897614950488156847949938836455"
    ]

    try:
        await ws.connect(test_assets)
    except KeyboardInterrupt:
        await ws.disconnect()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(main())
