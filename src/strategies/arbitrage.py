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
        
        self.min_profit_threshold = Decimal("0.020") # 2.0% min profit (covers gas + fees + slippage)
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
        """Check if market is a crypto 15-minute market"""
        question = market.get('question', '').lower()
        description = market.get('description', '').lower()
        combined = f"{question} {description}"

        # Crypto asset filter
        crypto_keywords = ['btc', 'bitcoin', 'eth', 'ethereum', 'sol', 'solana', 'xrp', 'ripple']
        has_crypto = any(k in combined for k in crypto_keywords)

        # 15-minute timeframe filter (positive context only)
        timeframe_keywords = ['15 min', '15min', 'fifteen minute', '15-minute', 'next 15', 'in 15']

        # Exclude if it mentions longer timeframes
        exclude_keywords = ['daily', 'hourly', '1 hour', '24 hour', 'weekly', 'monthly', 'not 15']
        has_exclude = any(k in combined for k in exclude_keywords)

        is_15min = any(k in combined for k in timeframe_keywords) and not has_exclude

        return has_crypto and is_15min

    async def _market_update_loop(self):
        """15분마다 생성되는 새로운 크립토 마켓을 자동으로 탐색하여 구독"""
        while self.is_running:
            try:
                if self.gamma_client:
                    # Lower volume threshold to $100 for 15min markets (high frequency)
                    markets = await self.gamma_client.get_active_markets(limit=50, volume_min=100)
                    new_assets = []
                    filtered_count = 0

                    for m in markets:
                        # Apply crypto 15min filter
                        if not self._is_crypto_15min_market(m):
                            filtered_count += 1
                            continue

                        tokens = m.get('tokens', [])
                        if len(tokens) == 2:
                            y_id = next(t['token_id'] for t in tokens if t['outcome'].lower() == 'yes')
                            n_id = next(t['token_id'] for t in tokens if t['outcome'].lower() == 'no')

                            self.market_map[y_id] = n_id
                            self.market_map[n_id] = y_id

                            if y_id not in self.subscribed_ids:
                                new_assets.extend([y_id, n_id])
                                self.subscribed_ids.update([y_id, n_id])
                    
                    if filtered_count > 0:
                        logger.info(f"🔍 ArbHunter: Filtered out {filtered_count} non-crypto-15min markets")

                    if new_assets:
                        logger.info(f"🎯 ArbHunter: Found {len(new_assets)//2} new crypto 15min markets")
                        logger.info(f"🆕 ArbHunter: Subscribing to {len(new_assets)//2} new market pairs")
                        self.client.subscribe('book', self.on_book_update)
                        await self.client.start_ws(list(self.subscribed_ids))
                
            except Exception as e:
                logger.error(f"Market update error: {e}")
            
            await asyncio.sleep(300) # 5분마다 갱신

    async def _monitor_bus_updates(self):
        while self.is_running:
            await asyncio.sleep(10)
            hot_tokens = await self.signal_bus.get_hot_tokens(min_sentiment=0.7)
            if hot_tokens:
                self.min_profit_threshold = Decimal("0.002") # 호재 시 0.2%로 공격적 전환
            else:
                self.min_profit_threshold = Decimal("0.005")

    async def on_book_update(self, event):
        """WebSocket 이벤트 발생 시 1ms 이내 실행"""
        for update in event.get("events", []):
            token_id = update.get("asset_id")
            asks = update.get("asks", [])
            
            if asks:
                self.local_orderbook[token_id] = Decimal(str(asks[0][0]))
                await self.check_arbitrage(token_id)

    async def check_arbitrage(self, token_id):
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
                pass 

        except Exception as e:
            logger.error(f"Arb execution failed: {e}")
        finally:
            if self.budget_manager:
                await self.budget_manager.release_allocation("arbhunter", alloc_id, Decimal("0"))