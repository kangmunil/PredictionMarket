import asyncio
import json
import logging
import threading
import os
import time
from typing import Dict, List, Callable, Optional, Set, Tuple
from decimal import Decimal
import aiohttp
import websockets
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderArgs, BalanceAllowanceParams, AssetType
from py_clob_client.order_builder.constants import BUY, SELL

from src.core.config import Config
from src.core.market_registry import market_registry
from src.core.polymarket_mcp_client import PolymarketMCPClient
from src.core.price_history_api import PolymarketHistoryAPI
from src.core.health_monitor import PROM_API_REQUESTS, PROM_API_ERRORS, PROM_LATENCY

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
        self.price_history_api: Optional[PolymarketHistoryAPI] = None
        
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
        self.signal_bus = None  # optional: set by SwarmSystem
        self._last_known_balance: Optional[float] = None
        self.redis = None # Redis caching layer

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
                signature_type=self.config.SIGNATURE_TYPE,
                funder=self.config.FUNDER_ADDRESS,
            )
            creds = self.rest_client.create_or_derive_api_creds()
            self.rest_client.set_api_creds(creds)
            logger.info("✅ PolyClient Authenticated")
        except Exception as exc:
            self.rest_client = None
            logger.error(f"❌ Failed to init REST client: {exc}")

    def set_redis(self, redis_client):
        """Inject Redis client for caching"""
        self.redis = redis_client

    # --- WebSocket & Trading Methods (Already defined in previous step, ensuring consistency) ---
    async def start_ws(self):
        backoff = 1
        self.ws_connected = False
        self.ws_running = True
        logger.info("🔌 Connecting to Polymarket WebSocket...")
        while self.ws_running:
            try:
                # Add keep-alive settings to prevent idle disconnections
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=None,  # Disable client-side ping to avoid 1011 errors on heavy load
                    ping_timeout=None,   # Trust TCP keepalive
                    close_timeout=10,
                    max_size=2**23,    # 8MB message size limit
                ) as ws:
                    self.ws_connection = ws
                    self.ws_connected = True
                    logger.info("✅ WebSocket connected successfully (ws_connected=True)")
                    backoff = 1

                    # Wait for server to be ready before subscribing
                    await asyncio.sleep(1.0)

                    # Re-subscribe to tokens in small batches (max 5 per batch)
                    if self.subscribed_tokens:
                        token_list = list(self.subscribed_tokens)

                        # Limit subscription to avoid server rejection
                        max_subscriptions = int(os.getenv("MAX_WS_SUBSCRIPTIONS", "5"))
                        if len(token_list) > max_subscriptions:
                            logger.warning(f"⚠️ Limiting WebSocket subscriptions: {len(token_list)} → {max_subscriptions} tokens")
                            token_list = token_list[:max_subscriptions]

                        batch_size = 5
                        for i in range(0, len(token_list), batch_size):
                            batch = token_list[i:i+batch_size]
                            await self._send_subscribe(batch)
                            logger.info(f"📡 Subscribed to batch {i//batch_size + 1}: {len(batch)} tokens")
                            await asyncio.sleep(2.0)  # Throttled delay between batches to prevent ping timeout
                        logger.info(f"✅ Total subscribed: {len(token_list)} tokens")

                    async for msg in ws:
                        await self._handle_ws_message(msg)
            except websockets.exceptions.ConnectionClosedError as e:
                self.ws_connected = False
                logger.warning(f"❌ WebSocket closed unexpectedly: {e.code} {e.reason}")
                logger.info(f"🔄 Retrying in {min(backoff, 60)}s...")
                await asyncio.sleep(min(backoff, 60))
                backoff = min(backoff * 2, 60)  # Cap at 60s
            except Exception as e:
                self.ws_connected = False
                logger.warning(f"❌ WebSocket disconnected (ws_connected=False): {e}")
                logger.info(f"🔄 Retrying in {min(backoff, 60)}s...")
                await asyncio.sleep(min(backoff, 60))
                backoff = min(backoff * 2, 60)

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
        try:
            # Official Polymarket CLOB format (from docs.polymarket.com)
            # https://docs.polymarket.com/developers/CLOB/websocket/wss-overview
            payload = {"assets_ids": token_ids, "type": "market"}

            payload_str = json.dumps(payload)

            # Log first subscription for debugging
            if not hasattr(self, '_first_sub_logged'):
                self._first_sub_logged = True
                logger.info(f"📤 First subscription payload: {payload_str}")

            await self.ws_connection.send(payload_str)
            logger.info(f"📤 Sent subscription for {len(token_ids)} tokens")
        except Exception as e:
            logger.error(f"❌ Failed to send subscription: {e}")

    async def _handle_ws_message(self, message: str):
        try:
            # logger.debug(f"🔍 DEBUG: Handling message type {type(message)}")
            data = json.loads(message)
            events = data if isinstance(data, list) else [data]

            # Log first few messages for debugging
            if not hasattr(self, '_ws_msg_count'):
                self._ws_msg_count = 0
            self._ws_msg_count += 1
            if self._ws_msg_count <= 5:
                logger.info(f"📨 WebSocket message #{self._ws_msg_count}: {json.dumps(data)[:200]}...")

            for event in events:
                if not isinstance(event, dict):
                     # logger.debug(f"⚠️ Ignored non-dict WS event: {event}")
                     continue

                # Check for error messages from server
                if 'error' in event or event.get('type') == 'error':
                    logger.error(f"❌ Server error: {event}")
                    continue

                # Handle 'book' event (order book snapshots)
                if event.get('event_type') == 'book':
                    asset_id = event.get('asset_id')
                    if asset_id in self.orderbooks:
                        book = self.orderbooks[asset_id]
                        # Handle both dict and list formats for bids/asks
                        for item in event.get('bids', []):
                            if isinstance(item, dict):
                                p, s = item.get('price'), item.get('size')
                            else:
                                p, s = item[0], item[1]
                            book.update(BUY, float(p), float(s))
                        for item in event.get('asks', []):
                            if isinstance(item, dict):
                                p, s = item.get('price'), item.get('size')
                            else:
                                p, s = item[0], item[1]
                            book.update(SELL, float(p), float(s))
                        if asset_id in self.callbacks:
                            for cb in self.callbacks[asset_id]:
                                if asyncio.iscoroutinefunction(cb): await cb(asset_id, book)
                                else: cb(asset_id, book)
                        await self._broadcast_orderbook_snapshot(asset_id, book)

                # Handle 'price_changes' event (price updates)
                elif 'price_changes' in event:
                    # Price change events don't update orderbook, just log
                    logger.debug(f"📊 Price change event: {len(event['price_changes'])} updates")

                # Handle initial snapshot (array format)
                elif isinstance(event, dict) and 'market' in event and 'timestamp' in event:
                    # Initial market snapshot - can be used for initialization
                    logger.debug(f"📸 Market snapshot received for {event.get('market', 'unknown')[:10]}...")
        except json.JSONDecodeError as e:
            msg_clean = message.strip()
            if msg_clean == "INVALID OPERATION":
                logger.debug(f"⚠️ WS received 'INVALID OPERATION' (likely due to keep-alive or auth glitch) - ignoring.")
            elif msg_clean.upper() == "PONG":
                 logger.debug("   🏓 WS PONG")
            else:
                logger.warning(f"⚠️ WebSocket JSON Decode Error: {e} | Msg: {message[:100]}...")
        except Exception as e:
            logger.exception(f"❌ WebSocket Handler Error: {e} | MsgType: {type(message)} | Msg: {message[:1000]}")

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
        PROM_API_REQUESTS.labels(service="clob_batch_order").inc()
        start_time = time.time()
        
        logger.info(f"🚀 [EXECUTION] Entering place_batch_market_orders for {len(orders_data)} orders")
        
        if self.config.DRY_RUN:
            total_usd = sum(Decimal(str(o['shares'])) * Decimal(str(o['price'])) for o in orders_data)
            logger.info(f"🧪 [DRY RUN] Simulating BATCH of {len(orders_data)} orders (Total: ${total_usd:.2f})")
            return {"status": "OK", "orders": [{"orderID": f"mock_batch_{i}", "price": o['price']} for i, o in enumerate(orders_data)]}

        if not self.rest_client:
            PROM_API_ERRORS.labels(service="clob_batch_order", error_type="no_client").inc()
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
                    PROM_API_ERRORS.labels(service="clob_batch_order", error_type="budget_denied").inc()
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
            
            PROM_LATENCY.labels(service="clob_batch_order").observe(time.time() - start_time)

            # 4. Release Budget
            if self.budget_manager and allocation_id:
                await self.budget_manager.release_allocation(
                    self.strategy_name, allocation_id, total_usd
                )

            logger.info("✅ Batch order request sent successfully")
            return resp

        except Exception as e:
            PROM_API_ERRORS.labels(service="clob_batch_order", error_type="exception").inc()
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

    async def get_market_cached(self, condition_id: str):
        """Fetch market details with Redis Caching (24h TTL)"""
        # 1. Try Redis
        if self.redis:
            try:
                data = await self.redis.get(f"market:{condition_id}")
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.warning(f"Redis get failed: {e}")

        # 2. Fallback to API (Sync call wrapped)
        market = self.get_market(condition_id)
        
        # 3. Cache result
        if market and self.redis:
            try:
                await self.redis.setex(f"market:{condition_id}", 86400, json.dumps(market))
            except Exception as e:
                logger.warning(f"Redis set failed: {e}")
                
        return market

    async def get_yes_token_id_cached(self, condition_id: str) -> Optional[str]:
        """Async Cached Mapper"""
        market = await self.get_market_cached(condition_id)
        if not market: return None
        
        try:
             tokens = market.get("tokens", [])
             if isinstance(tokens, list) and len(tokens) >= 2:
                 return tokens[0].get("token_id")
        except:
             pass
        # Fallback to sync call if structure is weird (safer)
        return self.get_yes_token_id(condition_id)

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

    def get_no_token_id(self, condition_id: str) -> Optional[str]:
        """
        Helper: Resolve condition_id to the NO token_id for CLOB trading.
        """
        logger.debug(f"🔍 [CLOB] Resolving NO token for CID: {condition_id[:10]}...")
        market = self.get_market(condition_id)
        if not market: return None
        
        try:
            # 1. Check clobTokenIds
            ids = market.get('clobTokenIds')
            if isinstance(ids, str): ids = json.loads(ids)
            if ids and len(ids) > 1: return ids[1] # Index 1 is usually NO
            
            # 2. Check tokens list
            tokens = market.get('tokens')
            if tokens and len(tokens) > 1:
                return tokens[1].get('token_id')
        except Exception as exc:
            logger.warning(f"⚠️ Failed to parse NO token ID: {exc}")
        return None

    def get_best_ask_price(self, token_id: str) -> float:
        if token_id in self.orderbooks:
            price, _ = self.orderbooks[token_id].get_best_ask()
            if price > 0: return price
        return 0.0 # Or fallback to REST if needed

    def get_best_ask(self, token_id: str) -> Tuple[float, float]:
        """Get best ask (price, size)"""
        if token_id in self.orderbooks:
             return self.orderbooks[token_id].get_best_ask()
        return (0.0, 0.0)

    def get_best_bid(self, token_id: str) -> Tuple[float, float]:
        """Get best bid (price, size)"""
        if token_id in self.orderbooks:
             return self.orderbooks[token_id].get_best_bid()
        return (0.0, 0.0) # Or fallback to REST if needed

    async def place_market_order(self, token_id: str, side: str, amount: float = 0.0, size: float = 0.0):
        """
        Execute a market order by placing an aggressive limit order 
        with slippage protection to ensure immediate fill.
        """
        logger.info(f"🚀 [EXECUTION] Entering place_market_order for {token_id}")
        return await self.place_limit_order_with_slippage_protection(
            token_id=token_id,
            side=side,
            amount=amount,
            size=size,
            max_slippage_pct=2.0,
            priority="normal"
        )

    # --- NEW: Maker-Taker & Limit Order Support ---

    async def place_limit_order(self, token_id: str, side: str, price: float, size: float) -> Optional[str]:
        """
        Place a Limit Order (Maker).
        Returns order_id if successful, None otherwise.
        """
        PROM_API_REQUESTS.labels(service="clob_limit_order").inc()
        start_time = time.time()

        if self.config.DRY_RUN:
            logger.info(f"🧪 [DRY RUN] Simulating {side} {size} @ ${price} on {token_id[:10]}...")
            return f"mock_order_{os.urandom(4).hex()}"

        if not self.rest_client:
            PROM_API_ERRORS.labels(service="clob_limit_order", error_type="no_client").inc()
            logger.error("❌ REST client not initialized")
            return None

        try:
            # 1. Minimum Order Value Check
            total_usd = Decimal(str(price)) * Decimal(str(size))
            min_order_value = float(os.getenv("MIN_ORDER_VALUE_USD", "5.0"))

            if float(total_usd) < min_order_value:
                PROM_API_ERRORS.labels(service="clob_limit_order", error_type="order_too_small").inc()
                logger.warning(
                    f"⚠️ Order rejected: ${total_usd:.2f} < minimum ${min_order_value:.2f} "
                    f"(Polymarket typically rejects orders below $5)"
                )
                return None

            # 2. Budget Check
            allocation_id = None
            if self.budget_manager:
                allocation_id = await self.budget_manager.request_allocation(
                    strategy=self.strategy_name,
                    amount=float(total_usd),
                    priority="normal"
                )
                if not allocation_id:
                    PROM_API_ERRORS.labels(service="clob_limit_order", error_type="budget_denied").inc()
                    logger.warning(f"⚠️ Limit order denied: Need ${total_usd:.2f}")
                    return None

            # 3. Create Order Args
            order_args = OrderArgs(
                price=float(price),
                size=float(size),
                side=side.upper(),
                token_id=token_id
            )

            # 4. Sign and Post Order
            logger.info(f"🧱 Placing LIMIT {side} {size} @ ${price} (Total: ${total_usd:.2f})")

            # Step 1: Sign the order locally
            signed_order = self.rest_client.create_order(order_args)
            logger.info(f"✍️ Order Signed: {type(signed_order).__name__}")

            # Step 2: Post the signed order to the exchange
            resp = self.rest_client.post_order(signed_order)
            logger.info(f"📤 Order Posted: {type(resp).__name__}")

            PROM_LATENCY.labels(service="clob_limit_order").observe(time.time() - start_time)

            # Handle both dict and SignedOrder object responses
            if isinstance(resp, dict):
                order_id = resp.get("orderID") or resp.get("id")
            else:
                # Debug SignedOrder object structure
                logger.info(f"📋 Response object type: {type(resp)}")
                logger.info(f"📋 Response attributes: {dir(resp)}")

                # Try common attribute names
                order_id = (
                    getattr(resp, "orderID", None) or
                    getattr(resp, "id", None) or
                    getattr(resp, "order_id", None)
                )

                # Try nested order object
                if not order_id and hasattr(resp, "order"):
                    order_obj = resp.order
                    order_id = (
                        getattr(order_obj, "id", None) or
                        getattr(order_obj, "orderID", None) or
                        getattr(order_obj, "order_id", None)
                    )

            if order_id:
                logger.info(f"   ✅ Order Placed: {order_id}")
                return order_id
            else:
                PROM_API_ERRORS.labels(service="clob_limit_order", error_type="api_failure").inc()
                logger.error(f"   ❌ Order failed - could not extract order_id from: {resp}")
                logger.error(f"   Response type: {type(resp)}, Has order attr: {hasattr(resp, 'order')}")
                # Release budget if failed
                if self.budget_manager and allocation_id:
                    await self.budget_manager.release_allocation(self.strategy_name, allocation_id, float(total_usd))
                return None

        except Exception as e:
            PROM_API_ERRORS.labels(service="clob_limit_order", error_type="exception").inc()
            logger.error(f"❌ Limit order exception: {e}")
            return None

    async def place_limit_order_with_slippage_protection(self, token_id: str, side: str, amount: float = 0.0, size: float = 0.0, max_slippage_pct: float = 1.0, priority: str = "normal", target_price: Optional[float] = None) -> Optional[Dict]:
        """
        Place a limit order with aggressive pricing to ensure fill within slippage limits.
        
        Args:
            token_id: The market token ID
            side: 'BUY' or 'SELL'
            amount: USD amount (NOT shares)
            max_slippage_pct: Max allowed price deviation (e.g., 2.0 for 2%)
            priority: Budget priority
            target_price: Optional desired limit price for fallback (AI suggested price)
            
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
            logger.warning(f"⚠️ No visible liquidity for {token_id[:16]}... Placing limit order at target price.")
            # Fallback: Place limit order at target_price (patient order)
            return await self.place_unprotected_aggressive_order(
                token_id=token_id,
                side=side,
                amount=amount,
                priority="high",
                target_price=target_price  # Use AI suggested price
            )
            
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
            
        # Round to valid tick size
        # Round to valid tick size (Strict)
        limit_price = float(f"{limit_price:.3f}")
        
        # 3. Calculate Shares
        if size > 0:
            shares = size
            logger.info(f"🛡️ Slippage Protection: Market ${best_price:.3f} → Limit ${limit_price:.3f} ({max_slippage_pct}%)")
            logger.info(f"   📊 Using explicit size: {shares:.2f} shares")
        else:
            # Initial calculation based on market price
            shares = float(amount) / best_price if best_price > 0 else 0
            
            # Recalculate if SELLING (limit < market) brings value below minimum
            limit_val = shares * limit_price
            if limit_val < 5.0 and amount >= 5.0:
                logger.info(f"   ⚖️ Limit val ${limit_val:.2f} < $5.00. Adjusting shares using Limit Price ${limit_price:.3f}")
                shares = 5.0 / limit_price if limit_price > 0 else shares
                shares *= 1.01 # 1% safety buffer

            shares = float(f"{shares:.2f}")
            
            logger.info(f"🛡️ Slippage Protection: Market ${best_price:.3f} → Limit ${limit_price:.3f} ({max_slippage_pct}%)")
            logger.info(f"   📊 Converting ${amount:.2f} USD → {shares:.2f} shares")
        
        # 4. Place Order
        order_id = await self.place_limit_order(token_id, side, limit_price, shares)
        
        if order_id:
            return {
                "orderID": order_id,
                "price": limit_price,
                "filled": shares
            }
        return None

    async def place_unprotected_aggressive_order(
        self,
        token_id: str,
        side: str,
        amount: float,  # USD amount, not shares
        priority: str = "normal",
        target_price: Optional[float] = None,  # User's desired limit price
    ) -> Optional[Dict]:
        """
        Submit a limit order. If target_price is provided, places order at that price
        (patient order waiting for counterparty). Otherwise uses aggressive pricing.
        
        NOTE: `amount` is in USD. We convert to shares using the limit price.
        """
        side = side.upper()
        
        # Get reference price for share calculation
        book = self.orderbooks.get(token_id)
        if side == "BUY":
            ref_price, _ = book.get_best_ask() if book else (0.50, 0)
        else:
            ref_price, _ = book.get_best_bid() if book else (0.50, 0)
        
        # Determine limit price
        if target_price is not None and 0.01 <= target_price <= 0.99:
            limit_price = round(target_price, 4) # Ensure precision for signing
            logger.info(f"📋 Placing limit order at target price ${limit_price:.3f}")
        else:
            # Aggressive fallback
            limit_price = 0.99 if side == "BUY" else 0.01
            logger.warning(f"🚨 [AGGRESSIVE] Using extreme limit ${limit_price:.3f}")
        
        # Safety: ensure ref_price is valid for share calculation
        calc_price = ref_price if ref_price > 0.01 else limit_price
        if calc_price <= 0.01:
            calc_price = 0.50
            logger.warning(f"⚠️ Invalid reference price, using 0.50 for share calculation")
        
        # Convert USD to shares
        # Note: If placing a patient limit order (target_price), we should calculate shares based on that price
        # to ensure the total value is correct.
        calc_price = limit_price if target_price else calc_price
        
        shares = float(amount) / calc_price
        
        # Adjust for minimum order value ($5)
        # If shares * limit_price < 5 (e.g. due to rounding or different ref price), bump it
        # But here calc_price IS limit_price for patient orders, so it should be exact.
        # Just need to handle rounding.
        
        shares = round(shares, 2)
        
        if shares * limit_price < 4.99:
             # Bump shares to hit $5
             shares = 5.0 / limit_price
             # Safety buffer and round again
             shares *= 1.01 

        # Strict Rounding via String Formatting to avoid float ghosts
        shares = float(f"{shares:.2f}")
        limit_price = float(f"{limit_price:.3f}")
        
        logger.info(
            "📝 Submitting %s limit order: %.2f shares ($%.2f) @ $%.3f for %s...",
            side,
            shares,
            amount,
            limit_price,
            token_id[:12],
        )
        
        # Validate minimum order value (allow ~$5.00 with small tolerance)
        order_value = shares * limit_price
        if order_value < 4.99:
            logger.warning(f"⚠️ Order rejected: ${order_value:.2f} < minimum $5.00")
            return None
        
        order_id = await self.place_limit_order(token_id, side, limit_price, shares)
        if order_id:
            return {"orderID": order_id, "price": limit_price, "filled": shares}
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

    async def get_all_positions(self) -> List[Dict]:
        """Fetch all open positions (held tokens) via manual API call"""
        address = self.config.FUNDER_ADDRESS
        if not address: return []

        # Try manual endpoint
        url = f"https://data-api.polymarket.com/positions?user={address}"
        try:
             async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.warning(f"Positions query failed HTTP {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"❌ Failed to fetch positions (manual): {e}")
            return []

    async def get_real_market_price(
        self,
        token_id: str,
        condition_id: Optional[str] = None
    ) -> Optional[float]:
        """
        Fetch the most recent executable price by preferring MCP trade data,
        with orderbook fallbacks.
        """
        if condition_id:
            try:
                if not self.price_history_api:
                    self.price_history_api = PolymarketHistoryAPI(use_mcp=True)
                price = await self.price_history_api.get_recent_trade_price(
                    condition_id=condition_id,
                    minutes=30
                )
                if price is not None:
                    logger.debug(
                        f"📡 PriceFeed: MCP trade price for {condition_id[:10]} -> {price:.4f}"
                    )
                    return float(price)
            except Exception as exc:
                logger.debug(f"⚠️ MCP price fetch failed for {condition_id}: {exc}")

        best_bid = best_ask = 0.0

        if token_id in self.orderbooks:
            book = self.orderbooks[token_id]
            best_ask, _ = book.get_best_ask()
            best_bid, _ = book.get_best_bid()
        else:
            try:
                if self.rest_client:
                    ob = self.rest_client.get_order_book(token_id)
                    if ob.asks:
                        best_ask = float(ob.asks[0].price)
                    if ob.bids:
                        best_bid = float(ob.bids[0].price)
            except Exception as exc:
                logger.debug(f"Order book lookup failed for {token_id}: {exc}")

        if best_bid > 0 and best_ask > 0:
            mid = (best_bid + best_ask) / 2.0
            logger.debug(f"📡 PriceFeed: Midpoint price for {token_id[:10]} -> {mid:.4f}")
            return mid
        if best_bid > 0:
            logger.debug(f"📡 PriceFeed: Bid-only price for {token_id[:10]} -> {best_bid:.4f}")
            return best_bid
        if best_ask > 0:
            logger.debug(f"📡 PriceFeed: Ask-only price for {token_id[:10]} -> {best_ask:.4f}")
            return best_ask
        return None

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
            # Handle both dict and object responses
            if isinstance(order, dict):
                status = order.get("status", "")
            else:
                status = getattr(order, "status", "")
            return status.upper() if status else None
        except Exception as e:
            logger.error(f"❌ Get status failed: {e}")
            return None

    async def close(self):
        """Gracefully release network resources."""
        self.ws_running = False
        if self.ws_connection:
            try:
                await self.ws_connection.close()
            except Exception as exc:
                logger.debug(f"WebSocket close error: {exc}")
            finally:
                self.ws_connection = None

        if self.price_history_api:
            try:
                await self.price_history_api.close()
            except Exception as exc:
                logger.debug(f"Price history API close error: {exc}")
            finally:
                self.price_history_api = None

    async def _broadcast_orderbook_snapshot(self, token_id: str, book: "LocalOrderBook"):
        if not self.signal_bus:
            return
        best_bid, _ = book.get_best_bid()
        best_ask, _ = book.get_best_ask()
        if not best_bid and not best_ask:
            return
        try:
            await self.signal_bus.update_market_metrics(
                token_id=token_id,
                best_bid=float(best_bid) if best_bid else None,
                best_ask=float(best_ask) if best_ask else None,
            )
        except Exception as exc:
            logger.debug(f"SignalBus spread update failed for {token_id[:8]}: {exc}")

    async def get_usdc_balance(self) -> float:
        """
        Return the live collateral (USDC) balance.
        Prefers authenticated REST client, falls back to public endpoint.
        """
        # Method 1: Use authenticated client (Reliable)
        if self.rest_client:
            try:
                params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
                # py_clob_client calls are synchronous
                resp = self.rest_client.get_balance_allowance(params)
                
                balance_raw = 0.0
                if isinstance(resp, dict):
                    balance_raw = float(resp.get("balance", 0))
                else:
                    balance_raw = float(getattr(resp, "balance", 0))
                
                balance = balance_raw / 1e6  # USDC uses 6 decimals
                self._last_known_balance = balance
                return balance
            except Exception as e:
                logger.error(f"❌ REST client balance fetch failed: {e}", exc_info=True)

        # Method 2: Fallback to manual endpoint
        address = self.config.FUNDER_ADDRESS
        if not address:
            return 0.0

        url = f"https://clob.polymarket.com/data/balances?address={address}"
        max_retries = 3

        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=5) as resp:
                        if resp.status != 200:
                            logger.warning("Balance query failed HTTP %s for %s", resp.status, url)
                            continue
                        payload = await resp.json()
                        for entry in payload:
                            if entry.get("asset_type") == "COLLATERAL":
                                raw = float(entry.get("balance", 0.0))
                                balance = raw / 1e6  # USDC uses 6 decimals
                                self._last_known_balance = balance
                                return balance

                        # No collateral entry found; treat as zero.
                        self._last_known_balance = 0.0
                        return 0.0
            except Exception as exc:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                else:
                    logger.warning(f"Failed to fetch balance after {max_retries} attempts: {exc}")

        if self._last_known_balance is not None:
            logger.info(
                "Using cached balance ($%.2f) due to connection failure.",
                self._last_known_balance,
            )
            return self._last_known_balance
        return None
