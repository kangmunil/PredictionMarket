import asyncio
import logging
from decimal import Decimal
from src.core.clob_client import PolyClient
from src.core.gamma_client import GammaClient
from datetime import datetime

logger = logging.getLogger(__name__)

class ArbitrageStrategy:
    """
    Pure Arbitrage Bot (Mathematical Error Hunter)
    Logic: If Yes Ask + No Ask < $1.00, Buy Both for guaranteed profit.
    """
    def __init__(self, client: PolyClient, gamma_client: GammaClient = None, signal_bus = None, budget_manager = None):
        self.client = client
        self.gamma_client = gamma_client
        self.signal_bus = signal_bus
        self.budget_manager = budget_manager
        self.notifier = None
        
        self.min_profit_threshold = Decimal("0.001") # 0.1% min profit (Aggressive for neglected markets)
        self.default_trade_size = 50.0             # USD per leg
        
        self.local_orderbook = {} # token_id -> best_ask
        self.market_map = {}      # yes_id <-> no_id
        self.subscribed_ids = set()
        
        self.is_running = True

    async def run(self):
        logger.info(">>> ArbHunter Online: High-Frequency WebSocket Mode <<<")
        
        # 🎯 주기적으로 마켓을 갱신하는 태스크 시작
        asyncio.create_task(self._market_update_loop())
        
        # 👂 SignalBus 모니터링 시작 (Frenzy Mode 등)
        if self.signal_bus:
            asyncio.create_task(self._monitor_bus_updates())

        while self.is_running:
            await asyncio.sleep(1) # 루프 유지

    def _is_crypto_15min_market(self, market: dict) -> bool:
        """Check if market is a crypto price market (any timeframe)"""
        question = market.get('question', '').lower()
        
        # Crypto asset filter (broad)
        crypto_keywords = ['btc', 'bitcoin', 'eth', 'ethereum', 'sol', 'solana', 
                          'xrp', 'ripple', 'doge', 'dogecoin', 'crypto', 'coin']
        has_crypto = any(k in question for k in crypto_keywords)

        return has_crypto

    def _is_valid_yesno_market(self, market: dict) -> bool:
        """Check if market has valid Yes/No tokens for arbitrage"""
        # 1. Check legacy tokens
        tokens = market.get('tokens', [])
        if len(tokens) == 2:
            outcomes = {t.get('outcome', '').lower() for t in tokens}
            return 'yes' in outcomes and 'no' in outcomes
            
        # 2. Check clobTokenIds
        if 'clobTokenIds' in market:
            try:
                raw_ids = market['clobTokenIds']
                if isinstance(raw_ids, str):
                    import json
                    c_ids = json.loads(raw_ids)
                else:
                    c_ids = raw_ids
                
                if isinstance(c_ids, list) and len(c_ids) == 2:
                    return True
            except Exception:
                pass
                
        return False

    async def _market_update_loop(self):
        """모든 활성 마켓을 1분마다 탐색하여 아비트라지 기회 발굴"""
        while self.is_running:
            try:
                if self.gamma_client:
                    # 1. Crypto 마켓 스캔 (모든 크립토)
                    markets = await self.gamma_client.get_active_markets(limit=200, volume_min=10)
                    new_assets = []
                    crypto_count = 0
                    general_count = 0
                    
                    for m in markets:
                        # Valid Yes/No market check
                        if not self._is_valid_yesno_market(m):
                            continue

                        tokens = m.get('tokens', [])
                        y_id = None
                        n_id = None

                        # 1. Try legacy 'tokens' list
                        if tokens:
                            y_id = next((t['token_id'] for t in tokens if t.get('outcome', '').lower() == 'yes'), None)
                            n_id = next((t['token_id'] for t in tokens if t.get('outcome', '').lower() == 'no'), None)

                        # 2. Try modern 'clobTokenIds' (List of strings)
                        if (not y_id or not n_id) and 'clobTokenIds' in m:
                            try:
                                raw_ids = m['clobTokenIds']
                                if isinstance(raw_ids, str):
                                    import json
                                    c_ids = json.loads(raw_ids)
                                else:
                                    c_ids = raw_ids
                                
                                if isinstance(c_ids, list) and len(c_ids) == 2:
                                    # Assume 2-outcome market (Binary)
                                    y_id = c_ids[0]
                                    n_id = c_ids[1]
                            except Exception:
                                pass
                        
                        if not y_id or not n_id:
                            continue

                        self.market_map[y_id] = n_id
                        self.market_map[n_id] = y_id

                        if y_id not in self.subscribed_ids:
                            new_assets.extend([y_id, n_id])
                            self.subscribed_ids.update([y_id, n_id])
                            
                            if self._is_crypto_15min_market(m):
                                crypto_count += 1
                            else:
                                general_count += 1
                    
                    if new_assets:
                        logger.info(f"🎯 ArbHunter: Subscribed to {len(new_assets)//2} markets (Crypto: {crypto_count}, General: {general_count})")
                        # WebSocket 구독 업데이트
                        await self.client.subscribe_orderbook(new_assets, self.on_book_update)
                    
                    # 로그 상태 출력
                    if len(self.subscribed_ids) > 0:
                        logger.info(f"📊 ArbHunter Status: Monitoring {len(self.subscribed_ids)//2} markets for arbitrage")
                
            except Exception as e:
                logger.error(f"Market update error: {e}")
            
            await asyncio.sleep(60) # 1분마다 갱신

    async def _monitor_bus_updates(self):
        while self.is_running:
            await asyncio.sleep(10)
            hot_tokens = await self.signal_bus.get_hot_tokens(min_sentiment=0.7)
            if hot_tokens:
                self.min_profit_threshold = Decimal("0.002") # 호재 시 0.2%로 공격적 전환
            else:
                self.min_profit_threshold = Decimal("0.001")

    async def on_book_update(self, token_id, book):
        """WebSocket 이벤트 발생 시 1ms 이내 실행"""
        # book is the full orderbook dict: {'bids': [], 'asks': []}
        # book might be a dict or LocalOrderBook object
        # 1. Handle LocalOrderBook Object (Preferred)
        if hasattr(book, "get_best_ask"):
            best_price, _ = book.get_best_ask()
            if best_price > 0:
                self.local_orderbook[token_id] = Decimal(str(best_price))
                await self.check_arbitrage(token_id)
            return

        # 2. Handle Raw Dictionary (Legacy/Fallback)
        asks = book.get("asks", []) if isinstance(book, dict) else getattr(book, "asks", [])
        
        if asks:
            try:
                # Handle list of dicts: [{'price': '0.99', ...}]
                if isinstance(asks[0], dict):
                     best_ask = Decimal(str(asks[0].get('price')))
                # Handle list of lists: [['0.99', '100']]
                elif isinstance(asks[0], list):
                     best_ask = Decimal(str(asks[0][0]))
                else:
                     return # Unknown format

                self.local_orderbook[token_id] = best_ask
                await self.check_arbitrage(token_id)
            except (IndexError, AttributeError, ValueError) as e:
                pass

    async def check_arbitrage(self, token_id):
        if getattr(self.client, "ws_connected", True) is False:
            logger.debug("Skipping arbitrage check; orderbook disconnected")
            return
        other_id = self.market_map.get(token_id)
        if not other_id or other_id not in self.local_orderbook:
            return

        price_a = self.local_orderbook[token_id]
        price_b = self.local_orderbook[other_id]
        total_cost = price_a + price_b

        # 💎 ARB CONDITION: Yes + No < $1.00
        if total_cost < (Decimal("1.0") - self.min_profit_threshold):
            logger.warning(f"💰 ARB OPPORTUNITY FOUND! Sum: {total_cost} | Profit: {Decimal('1.0') - total_cost}")
            await self.execute_batch_trade(token_id, other_id, price_a, price_b)

    async def execute_batch_trade(self, id_y, id_n, price_y, price_n):
        """원자적 주문 실행 (Atomic Batch Execution)"""
        # 1. 예산 요청
        if self.budget_manager:
            alloc_id = await self.budget_manager.request_allocation("arbhunter", Decimal(str(self.default_trade_size * 2)), priority="high")
            if not alloc_id: return

        try:
            logger.info(f"🚀 EXECUTING ATOMIC ARB: Buying {id_y} and {id_n}")
            
            # 2. 주문 생성 (Dry Run 시뮬레이션 포함)
            # 실제 운영 시 client.post_batch_orders 사용
            if getattr(self.client, 'dry_run', True):
                logger.info(f"🧪 [DRY RUN] Atomic Arb Success at total cost {price_y + price_n}")
                if self.notifier:
                    await self.notifier.notify_trade("BUY (ARB)", f"Pair {id_y[:8]}", float(price_y+price_n), self.default_trade_size, "Mathematical Arbitrage")
            else:
                # Live Batch Order Logic
                orders = [
                    {
                        "token_id": id_y,
                        "side": "BUY",
                        "shares": float(self.default_trade_size / Decimal(str(price_y))),
                        "price": float(price_y)
                    },
                    {
                        "token_id": id_n,
                        "side": "BUY",
                        "shares": float(self.default_trade_size / Decimal(str(price_n))),
                        "price": float(price_n)
                    }
                ]
                await self.client.place_batch_market_orders(orders, priority="high")
                logger.info(f"✅ Live Batch Order Sent for {id_y} / {id_n}") 

        except Exception as e:
            logger.error(f"Arb execution failed: {e}")
        finally:
            if self.budget_manager:
                await self.budget_manager.release_allocation("arbhunter", alloc_id, Decimal("0"))

    async def shutdown(self):
        """Gracefully close internal clients"""
        logger.info("🎬 Shutting down ArbitrageStrategy...")
        try:
            if hasattr(self, 'gamma_client') and self.gamma_client:
                await self.gamma_client.close()
            logger.info("✅ ArbitrageStrategy resources closed")
        except Exception as e:
            logger.error(f"Error during ArbitrageStrategy shutdown: {e}")
