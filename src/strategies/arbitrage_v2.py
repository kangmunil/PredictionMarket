import asyncio
import logging
from decimal import Decimal
from typing import Dict, List, Optional
from src.core.clob_client import PolyClient
from src.core.gamma_client import GammaClient
from src.core.signal_bus import SignalBus
from src.core.budget_manager import BudgetManager
from src.strategies.crypto_15min_filter import Crypto15MinFilter
from datetime import datetime

logger = logging.getLogger(__name__)

class PureArbitrageV2:
    """
    Pure Arbitrage Bot V2 (Maker-Taker Optimized & Crypto 15min Targeted)
    Logic: If Yes Ask + No Ask < $1.00, Buy Both for guaranteed profit.
    """
    def __init__(
        self, 
        client: PolyClient, 
        gamma_client: GammaClient = None, 
        signal_bus: SignalBus = None, 
        budget_manager: BudgetManager = None,
        min_profit: float = 0.010,  # 1.0% 기본 수익 임계값
        default_trade_size: float = 100.0,
        risk_manager = None,
        pnl_tracker = None # Phase 4.3
    ):
        self.client = client
        self.gamma_client = gamma_client
        self.signal_bus = signal_bus
        self.budget_manager = budget_manager
        self.risk_manager = risk_manager
        self.pnl_tracker = pnl_tracker # Phase 4.3
        
        self.market_filter = Crypto15MinFilter()
        self.min_profit_threshold = Decimal(str(min_profit))
        self.base_trade_size = default_trade_size
        
        self.local_orderbook = {} # token_id -> best_ask
        self.market_map = {}      # yes_id <-> no_id
        self.subscribed_ids = set()
        self.is_running = True
        self.notifier = None

    async def run(self):
        logger.info(">>> Pure Arbitrage V2 (Maker-Taker) Online <<<")
        
        # 1. 마켓 탐색 및 구독 루프
        self.market_task = asyncio.create_task(self._market_update_loop())
        
        # 2. 버스 업데이트 모니터링
        self.bus_task = None
        if self.signal_bus:
            self.bus_task = asyncio.create_task(self._monitor_bus_updates())

        while self.is_running:
            await asyncio.sleep(1)

    async def shutdown(self):
        """Stop all background tasks and clean up"""
        logger.info("🛑 Shutting down PureArbitrageV2...")
        self.is_running = False
        
        if hasattr(self, 'market_task') and self.market_task:
            self.market_task.cancel()
        
        if hasattr(self, 'bus_task') and self.bus_task:
            self.bus_task.cancel()
            
        if self.notifier and hasattr(self.notifier, 'stop'):
            try:
                await self.notifier.stop()
            except Exception as e:
                logger.error(f"Error stopping notifier: {e}")

        logger.info("✅ PureArbitrageV2 shutdown complete")

    async def _market_update_loop(self):
        """15분 크립토 마켓을 정밀 타겟팅하여 구독 관리"""
        while self.is_running:
            try:
                if self.gamma_client:
                    markets = await self.market_filter.get_active_crypto_15min_markets(
                        self.gamma_client, limit=50
                    )
                    
                    new_assets = []
                    for m in markets:
                        clob_ids = self._extract_clob_ids(m)
                        if not clob_ids or len(clob_ids) != 2:
                            continue
                            
                        y_id, n_id = clob_ids[0], clob_ids[1]
                        self.market_map[y_id] = n_id
                        self.market_map[n_id] = y_id

                        if y_id not in self.subscribed_ids:
                            new_assets.extend([y_id, n_id])
                            self.subscribed_ids.update([y_id, n_id])
                    
                    if new_assets:
                        logger.info(f"🎯 ArbV2: Subscribed to {len(new_assets)//2} NEW crypto 15min markets")
                        await self.client.subscribe_orderbook(new_assets, self.on_book_update)
                        
                    logger.info(f"📊 ArbV2 Status: Monitoring {len(self.subscribed_ids)//2} crypto 15min markets")
            
            except Exception as e:
                logger.error(f"ArbV2 market update error: {e}")
            
            await asyncio.sleep(120) # 2분마다 갱신

    def _extract_clob_ids(self, market: Dict) -> Optional[List[str]]:
        """마켓 데이터에서 CLOB Token ID 추출"""
        if 'clobTokenIds' in market:
            try:
                raw_ids = market['clobTokenIds']
                return json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
            except:
                pass
        
        tokens = market.get('tokens', [])
        if len(tokens) == 2:
            return [t['token_id'] for t in tokens]
        
        return None

    async def _monitor_bus_updates(self):
        """시장 과열 시 임계값 동적 조정"""
        while self.is_running:
            await asyncio.sleep(15)
            # 호재 시에는 조금 더 보수적으로 (슬리피지 대비) 혹은 더 공격적으로 설정 가능
            hot_tokens = await self.signal_bus.get_hot_tokens(min_sentiment=0.8)
            if hot_tokens:
                self.min_profit_threshold = Decimal("0.015") # 과열 시 1.5%로 상향 (안전성)
            else:
                self.min_profit_threshold = Decimal("0.010")

    async def on_book_update(self, token_id, book):
        """실시간 오더북 업데이트 핸들러"""
        if hasattr(book, "get_best_ask"):
            best_price, _ = book.get_best_ask()
            if best_price > 0:
                self.local_orderbook[token_id] = Decimal(str(best_price))
                await self.check_arbitrage(token_id)

    async def check_arbitrage(self, token_id):
        other_id = self.market_map.get(token_id)
        if not other_id or other_id not in self.local_orderbook:
            return

        price_a = self.local_orderbook[token_id]
        price_b = self.local_orderbook[other_id]
        total_cost = price_a + price_b

        # 💎 ARB CONDITION: Yes + No < $1.00 - Threshold
        if total_cost < (Decimal("1.0") - self.min_profit_threshold):
            # 오더북 깊이 체크 (가상 구현)
            # 여기서는 최상의 가격만 사용하므로 바로 실행
            logger.warning(f"💰 [ArbV2] OPPORTUNITY: {total_cost} (Profit: {Decimal('1.0')-total_cost})")
            
            # 동적 사이즈 계산 (Kelly Criterion 단순화 버전)
            edge = Decimal("1.0") - total_cost
            trade_size = self._calculate_optimal_size(edge)
            
            await self.execute_trade(token_id, other_id, price_a, price_b, trade_size)

    def _calculate_optimal_size(self, edge: Decimal) -> float:
        """가장자리 너비에 따른 주문 사이즈 조절 및 리스크 매니저 적용 (Phase 4.1)"""
        size = self.base_trade_size
        if edge > Decimal("0.03"):  # 3% 이상 이익 시 2배
            size = self.base_trade_size * 2.0
        elif edge > Decimal("0.02"): # 2% 이상 이익 시 1.5배
            size = self.base_trade_size * 1.5
            
        # Global Risk Manager 적용
        if self.risk_manager:
            size = self.risk_manager.calculate_trade_size(size)
            
        return size

    async def execute_trade(self, id_y, id_n, price_y, price_n, size):
        if self.budget_manager:
            alloc_id = await self.budget_manager.request_allocation("arbhunter", Decimal(str(size)), priority="high")
            if not alloc_id: return

        try:
            # 1. Calculate Equal Shares for Guaranteed Profit (True Arb)
            # Target Cost = size. 
            # Total Cost per Unit = price_y + price_n
            # Shares = size / (price_y + price_n)
            
            combined_price = price_y + price_n
            if combined_price <= 0: return
            
            shares = float(Decimal(str(size)) / combined_price)
            
            # Expected Profit = Revenue - Cost
            # Revenue = shares * 1.0 (Guaranteed)
            # Cost = shares * combined_price (= size)
            estimated_pnl = shares * (1.0 - float(combined_price))
            profit_pct = (1.0 - float(combined_price)) * 100

            if getattr(self.client, 'dry_run', True):
                # Phase 18: Latency Emulation
                import random
                latency = random.uniform(0.1, 0.4) # 100ms - 400ms
                await asyncio.sleep(latency)
                
                # Apply 1bp "Latency Slip" (Market moves while we wait)
                combined_price_calibrated = combined_price * Decimal("1.0001") 
                
                logger.info(f"🧪 [DRY RUN] ArbV2 Success | Spread: {profit_pct:.2f}% | Latency: {latency:.2f}s")
                
                # PnL Tracker 기록 (Phase 4.3)
                if self.pnl_tracker:
                    tid = self.pnl_tracker.record_entry("arbhunter", id_y, "BUY", float(combined_price_calibrated), size, metadata={"group": "CRYPTO"})
                    self.pnl_tracker.record_exit(tid, 1.0, reason=f"Arb V2 Spread: {profit_pct:.2f}%")

                if self.notifier:
                    await self.notifier.notify_trade(
                        side="BUY (ArbV2)",
                        asset=f"Pair {id_y[:5]}/{id_n[:5]}", 
                        price=float(combined_price), 
                        size=size,
                        profit=estimated_pnl,
                        reasoning=f"Arbitrage Spread: {profit_pct:.2f}%",
                        strategy="PureArbitrageV2"
                    )
            else:
                orders = [
                    {"token_id": id_y, "side": "BUY", "shares": shares, "price": float(price_y)},
                    {"token_id": id_n, "side": "BUY", "shares": shares, "price": float(price_n)}
                ]
                await self.client.place_batch_market_orders(orders, priority="high")
                logger.info(f"✅ ArbV2 Live Orders Sent | {shares:.2f} shares per leg")
                
        except Exception as e:
            logger.error(f"ArbV2 execution failed: {e}")
        finally:
            if self.budget_manager:
                await self.budget_manager.release_allocation("arbhunter", alloc_id, Decimal("0"))

import json # For json.loads in _extract_clob_ids