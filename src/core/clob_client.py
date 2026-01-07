import asyncio
import json
import logging
import threading
import os
from typing import Dict, List, Callable, Optional, Set, Tuple
from decimal import Decimal
import aiohttp
import websockets
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL

from src.core.config import Config
from src.core.market_registry import market_registry
from src.core.polymarket_mcp_client import PolymarketMCPClient

logger = logging.getLogger(__name__)

class LocalOrderBook:
    """
    Maintains a real-time local copy of the order book.
    Updates via WebSocket deltas.
    """
    def __init__(self, token_id: str):
        self.token_id = token_id
        # Bids: price -> size
        self.bids: Dict[float, float] = {} 
        # Asks: price -> size
        self.asks: Dict[float, float] = {}

    def update(self, side: str, price: float, size: float):
        book = self.bids if side == BUY else self.asks
        if size == 0:
            if price in book: del book[price]
        else:
            book[price] = size

    def get_best_ask(self) -> Tuple[float, float]:
        if not self.asks: return 0.0, 0.0
        best_price = min(self.asks.keys())
        return best_price, self.asks[best_price]

    def get_best_bid(self) -> Tuple[float, float]:
        if not self.bids: return 0.0, 0.0
        best_price = max(self.bids.keys())
        return best_price, self.bids[best_price]

    def get_avg_price_for_shares(self, side: str, total_shares: float) -> float:
        """
        Calculate the average price for a specific number of shares.
        Used to ensure perfect hedging with equal shares on both legs.
        """
        book = self.bids if side == BUY else self.asks
        if not book or total_shares <= 0:
            return 0.0

        prices = sorted(book.keys(), reverse=(side == BUY))
        
        remaining_shares = total_shares
        weighted_sum = 0.0

        for price in prices:
            size = book[price]
            
            if size >= remaining_shares:
                weighted_sum += (remaining_shares * price)
                remaining_shares = 0
                break
            else:
                weighted_sum += (size * price)
                remaining_shares -= size

        if remaining_shares > 0:
            # Not enough liquidity for this many shares
            return 0.0

        return weighted_sum / total_shares

    def get_max_shares_within_price(self, side: str, max_avg_price: float) -> float:
        """
        Find the maximum number of shares we can buy without the 
        average price exceeding 'max_avg_price'.
        Used for size optimization.
        """
        book = self.bids if side == BUY else self.asks
        if not book:
            return 0.0

        prices = sorted(book.keys(), reverse=(side == BUY))
        
        total_shares = 0.0
        weighted_sum = 0.0

        for price in prices:
            # If the best price itself is already worse than max_avg, stop
            if (side == SELL and price > max_avg_price) or (side == BUY and price < max_avg_price):
                if total_shares == 0: return 0.0
                break
                
            size = book[price]
            potential_total = total_shares + size
            potential_sum = weighted_sum + (size * price)
            
            if (potential_sum / potential_total) <= max_avg_price if side == SELL else (potential_sum / potential_total) >= max_avg_price:
                total_shares = potential_total
                weighted_sum = potential_sum
            else:
                # Calculate partial size from this level to hit exactly max_avg_price
                # (weighted_sum + p*x) / (total_shares + x) = max_avg
                # weighted_sum + p*x = max_avg*total_shares + max_avg*x
                # x*(p - max_avg) = max_avg*total_shares - weighted_sum
                # x = (max_avg*total_shares - weighted_sum) / (p - max_avg)
                denom = (price - max_avg_price)
                if abs(denom) > 1e-9:
                    extra_x = (max_avg_price * total_shares - weighted_sum) / denom
                    if extra_x > 0:
                        total_shares += extra_x
                break

        return total_shares

class PolyClient:
    """
    Polymarket Client V3.0 (Hybrid REST + WebSocket + Atomic Contract)
    """
    def __init__(self, strategy_name: str = "unknown", budget_manager=None):
        self.config = Config()
        self.rest_client: Optional[ClobClient] = None
        self._mcp_client: Optional[PolymarketMCPClient] = None
        self.strategy_name = strategy_name
        self.budget_manager = budget_manager
        
        # Web3 & Contract
        self.w3 = None
        self.executor_contract = None
        self._init_web3()
        
        # WebSocket State
        self.ws_url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        self.ws_connection = None
        self.ws_running = False
        self.subscribed_tokens: Set[str] = set()
        self.orderbooks: Dict[str, LocalOrderBook] = {}
        self.callbacks: Dict[str, List[Callable]] = {}
        
        self._init_rest_client()
        if os.getenv("POLYMARKET_MCP_URL"):
            try:
                self._mcp_client = PolymarketMCPClient()
            except Exception as exc:
                logger.warning(f"⚠️ MCP client init failed: {exc}")

    def _init_web3(self):
        """Initialize optional Web3 + contract state."""
        if not self.config.RPC_URL:
            logger.warning("⚠️ POLYGON_RPC_URL not configured; on-chain features disabled")
            return

        try:
            self.w3 = Web3(Web3.HTTPProvider(self.config.RPC_URL))
            self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            addr_path = "src/contracts/address.txt"
            abi_path = "src/contracts/ArbExecutor_ABI.json"
            if os.path.exists(addr_path) and os.path.exists(abi_path):
                with open(addr_path, "r") as f:
                    addr = f.read().strip()
                with open(abi_path, "r") as f:
                    abi = json.load(f)
                self.executor_contract = self.w3.eth.contract(address=addr, abi=abi)
                logger.info(f"🛡️ ArbExecutor linked at {addr}")
        except Exception as exc:
            self.w3 = None
            self.executor_contract = None
            logger.warning(f"⚠️ Web3 unavailable ({exc}); continuing without on-chain access")

    def _init_rest_client(self):
        if not self.config.PRIVATE_KEY:
            logger.warning("⚠️ PRIVATE_KEY missing; REST client disabled (dry-run only)")
            return
        try:
            self.rest_client = ClobClient(
                host=self.config.HOST,
                key=self.config.PRIVATE_KEY,
                chain_id=self.config.CHAIN_ID,
                signature_type=1,
                funder=self.config.FUNDER_ADDRESS,
            )
            creds = self.rest_client.create_or_derive_api_creds()
            self.rest_client.set_api_creds(creds)
            logger.info("✅ PolyClient Authenticated")
        except Exception as exc:
            self.rest_client = None
            logger.error(f"❌ Failed to init REST client: {exc}")

    # --- WebSocket & Trading Methods (Already defined in previous step, ensuring consistency) ---
    async def start_ws(self):
        backoff = 1
        self.ws_connected = False
        while self.ws_running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    self.ws_connection = ws
                    self.ws_connected = True
                    backoff = 1
                    if self.subscribed_tokens:
                        await self._send_subscribe(list(self.subscribed_tokens))
                    async for msg in ws:
                        await self._handle_ws_message(msg)
            except Exception as e:
                self.ws_connected = False
                await asyncio.sleep(min(backoff, 60))
                backoff *= 2

    async def subscribe_orderbook(self, token_ids: List[str], callback: Optional[Callable] = None):
        new_tokens = [tid for tid in token_ids if tid not in self.subscribed_tokens]
        for tid in token_ids:
            self.subscribed_tokens.add(tid)
            if tid not in self.orderbooks: self.orderbooks[tid] = LocalOrderBook(tid)
            if callback:
                if tid not in self.callbacks: self.callbacks[tid] = []
                self.callbacks[tid].append(callback)
        if new_tokens and self.ws_connection: await self._send_subscribe(new_tokens)

    async def _send_subscribe(self, token_ids: List[str]):
        payload = [{"assets_ids": token_ids, "type": "market"}]
        await self.ws_connection.send(json.dumps(payload))

    async def _handle_ws_message(self, message: str):
        try:
            data = json.loads(message)
            events = data if isinstance(data, list) else [data]
            for event in events:
                if event.get('event_type') == 'book':
                    asset_id = event.get('asset_id')
                    if asset_id in self.orderbooks:
                        book = self.orderbooks[asset_id]
                        for p, s in event.get('bids', []): book.update(BUY, float(p), float(s))
                        for p, s in event.get('asks', []): book.update(SELL, float(p), float(s))
                        if asset_id in self.callbacks:
                            for cb in self.callbacks[asset_id]:
                                if asyncio.iscoroutinefunction(cb): await cb(asset_id, book)
                                else: cb(asset_id, book)
        except json.JSONDecodeError as e:
            logger.warning(f"⚠️ WebSocket JSON Decode Error: {e} | Msg: {message[:100]}...")
        except Exception as e:
            logger.error(f"❌ WebSocket Handler Error: {e}")

    # --- NEW: Atomic Batch Execution ---

    async def execute_atomic_trade(self, orders: List[Dict]):
        """
        Execute multiple orders via ArbExecutor contract.
        Each order dict: {'token_id': str, 'amount': float, 'side': str}
        """
        if not self.executor_contract:
            logger.error("❌ ArbExecutor contract not loaded")
            return None

        try:
            targets = []
            calldatas = []
            
            # 1. Encode each order using py-clob-client
            # Note: Polymarket fillOrder requires complex signature.
            # For simplicity in this prototype, we'll log the intention.
            # In a real setup, we'd use rest_client.create_order and encode fillOrder.
            
            logger.info(f"⚡ Batching {len(orders)} orders into atomic transaction...")
            
            # Placeholder for transaction execution
            # nonce = self.w3.eth.get_transaction_count(self.config.FUNDER_ADDRESS)
            # tx = self.executor_contract.functions.executeBatch(targets, calldatas).build_transaction({...})
            # ... sign and send ...
            
            return "BATCH_SENT_PLACEHOLDER"

        except Exception as e:
            logger.error(f"❌ Atomic Trade Failed: {e}")
            return None

    async def place_batch_market_orders(self, orders_data: List[Dict], priority: str = "normal"):
        """
        Execute multiple market orders in a single API batch request.
        orders_data: List of {'token_id': str, 'side': str, 'shares': float, 'price': float}
        """
        logger.info(f"🚀 [EXECUTION] Entering place_batch_market_orders for {len(orders_data)} orders")
        
        if self.config.DRY_RUN:
            total_usd = sum(Decimal(str(o['shares'])) * Decimal(str(o['price'])) for o in orders_data)
            logger.info(f"🧪 [DRY RUN] Simulating BATCH of {len(orders_data)} orders (Total: ${total_usd:.2f})")
            return {"status": "OK", "orders": [{"orderID": f"mock_batch_{i}", "price": o['price']} for i, o in enumerate(orders_data)]}

        if not self.rest_client:
            logger.error("❌ REST client not initialized")
            return None

        try:
            total_usd = sum(Decimal(str(o['shares'])) * Decimal(str(o['price'])) for o in orders_data)
            
            # 1. Budget Request
            allocation_id = None
            if self.budget_manager:
                allocation_id = await self.budget_manager.request_allocation(
                    strategy=self.strategy_name,
                    amount=total_usd,
                    priority=priority
                )
                if not allocation_id:
                    logger.warning(f"⚠️ Batch order denied: Need ${total_usd:.2f}")
                    return None

            # 2. Build Batch Orders
            batch_orders = []
            for o in orders_data:
                order_args = OrderArgs(
                    price=float(o['price']),
                    size=float(o['shares']),
                    side=o['side'],
                    token_id=o['token_id']
                )
                batch_orders.append(order_args)

            # 3. Execute Batch
            logger.info(f"⚡ Executing batch of {len(batch_orders)} orders (Total: ${total_usd:.2f})")
            resp = self.rest_client.create_batch_orders(batch_orders)
            
            # 4. Release Budget
            if self.budget_manager and allocation_id:
                await self.budget_manager.release_allocation(
                    self.strategy_name, allocation_id, total_usd
                )

            logger.info("✅ Batch order request sent successfully")
            return resp

        except Exception as e:
            logger.error(f"❌ Batch order failed: {e}")
            return None

    def get_market(self, condition_id: str):
        """Fetch market details to get token_ids"""
        condition_id = str(condition_id)
        slug = market_registry.get_slug(condition_id)

        if self._mcp_client and slug:
            try:
                market = self._mcp_client.get_market_sync(slug)
                if isinstance(market, dict):
                    market_registry.register_market(market)
                return market
            except Exception as exc:
                logger.warning(f"⚠️ MCP market lookup failed for {slug}: {exc}")

        if not self.rest_client:
            return None
        try:
            market = self.rest_client.get_market(condition_id)
            if isinstance(market, dict):
                market_registry.register_market(market)
            return market
        except Exception as e:
            logger.error(f"Failed to get market {condition_id}: {e}")
            return None

    def get_yes_token_id(self, condition_id: str) -> Optional[str]:
        """
        Helper: Resolve condition_id to the YES token_id for CLOB trading.
        """
        logger.debug(f"🔍 [CLOB] Resolving YES token for CID: {condition_id[:10]}...")
        market = self.get_market(condition_id)
        if not market: return None
        
        try:
            # 1. Check clobTokenIds (Prefer list)
            ids = market.get('clobTokenIds')
            if isinstance(ids, str): ids = json.loads(ids)
            if ids and len(ids) > 0: return ids[0]
            
            # 2. Check tokens list
            tokens = market.get('tokens')
            if tokens and len(tokens) > 0:
                return tokens[0].get('token_id')
        except Exception as exc:
            logger.warning(f"⚠️ Failed to parse token IDs: {exc}")
        return None

    def get_best_ask_price(self, token_id: str) -> float:
        if token_id in self.orderbooks:
            price, _ = self.orderbooks[token_id].get_best_ask()
            if price > 0: return price
        return 0.0 # Or fallback to REST if needed

    async def place_market_order(self, token_id: str, side: str, amount: float):
        """
        Execute a market order by placing an aggressive limit order 
        with slippage protection to ensure immediate fill.
        """
        logger.info(f"🚀 [EXECUTION] Entering place_market_order for {token_id}")
        return await self.place_limit_order_with_slippage_protection(
            token_id=token_id,
            side=side,
            amount=amount,
            max_slippage_pct=2.0,
            priority="normal"
        )

    # --- NEW: Maker-Taker & Limit Order Support ---

    async def place_limit_order(self, token_id: str, side: str, price: float, size: float) -> Optional[str]:
        """
        Place a Limit Order (Maker).
        Returns order_id if successful, None otherwise.
        """
        if self.config.DRY_RUN:
            logger.info(f"🧪 [DRY RUN] Simulating {side} {size} @ ${price} on {token_id[:10]}...")
            return f"mock_order_{os.urandom(4).hex()}"

        if not self.rest_client:
            logger.error("❌ REST client not initialized")
            return None

        try:
            # 1. Budget Check
            total_usd = Decimal(str(price)) * Decimal(str(size))
            allocation_id = None
            if self.budget_manager:
                allocation_id = await self.budget_manager.request_allocation(
                    strategy=self.strategy_name,
                    amount=float(total_usd),
                    priority="normal"
                )
                if not allocation_id:
                    logger.warning(f"⚠️ Limit order denied: Need ${total_usd:.2f}")
                    return None

            # 2. Create Order Args
            order_args = OrderArgs(
                price=float(price),
                size=float(size),
                side=side.upper(),
                token_id=token_id
            )

            # 3. Send Order
            logger.info(f"🧱 Placing LIMIT {side} {size} @ ${price} (Total: ${total_usd:.2f})")
            resp = self.rest_client.create_order(order_args)
            
            order_id = resp.get("orderID") or resp.get("id")
            
            if order_id:
                logger.info(f"   ✅ Order Placed: {order_id}")
                return order_id
            else:
                logger.error(f"   ❌ Order failed: {resp}")
                # Release budget if failed
                if self.budget_manager and allocation_id:
                    await self.budget_manager.release_allocation(self.strategy_name, allocation_id, float(total_usd))
                return None

        except Exception as e:
            logger.error(f"❌ Limit order exception: {e}")
            return None

    async def place_limit_order_with_slippage_protection(self, token_id: str, side: str, amount: float, max_slippage_pct: float = 1.0, priority: str = "normal") -> Optional[Dict]:
        """
        Place a limit order with aggressive pricing to ensure fill within slippage limits.
        
        Args:
            token_id: The market token ID
            side: 'BUY' or 'SELL'
            amount: Number of shares
            max_slippage_pct: Max allowed price deviation (e.g., 2.0 for 2%)
            priority: Budget priority
            
        Returns:
            Dict with orderID and price, or None if failed.
        """
        side = side.upper()
        
        # 1. Get current market price (Orderbook top)
        if token_id in self.orderbooks:
            book = self.orderbooks[token_id]
            best_price, _ = book.get_best_ask() if side == 'BUY' else book.get_best_bid()
        else:
            # Fallback to REST if not subscribed to WS
            try:
                book = self.rest_client.get_order_book(token_id)
                if side == 'BUY' and book.asks:
                    best_price = float(book.asks[0].price)
                elif side == 'SELL' and book.bids:
                    best_price = float(book.bids[0].price)
                else:
                    best_price = 0.0
            except Exception:
                best_price = 0.0
                
        if best_price <= 0:
            logger.warning(f"⚠️ Cannot place protected order: No liquidity for {token_id}")
            return None
            
        # 2. Calculate Limit Price with Slippage
        # BUY: We are willing to pay MORE (up to slippage)
        # SELL: We are willing to receive LESS (down to slippage)
        slippage_factor = max_slippage_pct / 100.0
        
        if side == 'BUY':
            limit_price = best_price * (1 + slippage_factor)
            # Cap at 1.00 (Polymarket max)
            limit_price = min(limit_price, 0.999) 
        else:
            limit_price = best_price * (1 - slippage_factor)
            # Floor at 0.00
            limit_price = max(limit_price, 0.001)
            
        # Round to valid tick size (usually 2-4 decimals, mostly raw float works but being safe)
        limit_price = round(limit_price, 4)
        
        logger.info(f"🛡️ Slippage Protection: Market ${best_price:.3f} -> Limit ${limit_price:.3f} ({max_slippage_pct}%)")
        
        # 3. Place Order
        # We reuse place_limit_order but catch the string return and wrap it
        order_id = await self.place_limit_order(token_id, side, limit_price, amount)
        
        if order_id:
            return {
                "orderID": order_id,
                "price": limit_price,
                "filled": amount # Assumption for now, real fill needs ws confirmation
            }
        return None

    async def cancel_order(self, order_id: str):
        """Cancel a specific order"""
        if not self.rest_client: return
        try:
            logger.info(f"🗑️ Canceling order: {order_id}")
            self.rest_client.cancel(order_id)
            logger.info("   ✅ Cancelled")
        except Exception as e:
            logger.error(f"❌ Cancel failed: {e}")

    async def cancel_all_orders(self):
        """Cancel ALL open orders for this account"""
        if not self.rest_client: return
        try:
            logger.info("🗑️ Canceling ALL open orders...")
            self.rest_client.cancel_all()
            logger.info("   ✅ All orders cancelled")
        except Exception as e:
            logger.error(f"❌ Cancel all failed: {e}")

    async def get_order_status(self, order_id: str) -> Optional[str]:
        """
        Check status of an order. 
        Returns: 'OPEN', 'FILLED', 'CANCELED', or None
        """
        if not self.rest_client: return None
        try:
            order = self.rest_client.get_order(order_id)
            # Map status from API response
            # Typically returns: "status": "open" | "matched" | "cancelled"
            return order.get("status", "").upper()
        except Exception as e:
            logger.error(f"❌ Get status failed: {e}")
            return None
