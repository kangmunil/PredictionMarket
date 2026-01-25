import asyncio
import logging
import json
import time
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
        default_trade_size: float = 50.0,
        risk_manager = None,
        pnl_tracker = None, # Phase 4.3
        market_ranker = None, # Phase 7
        dry_run: bool = True
    ):
        self.client = client
        self.gamma_client = gamma_client
        self.signal_bus = signal_bus
        self.budget_manager = budget_manager
        self.risk_manager = risk_manager
        self.pnl_tracker = pnl_tracker # Phase 4.3
        self.market_ranker = market_ranker # Phase 7
        self.dry_run = dry_run
        
        self.min_profit_threshold = Decimal(str(min_profit))
        self.base_trade_size = default_trade_size
        
        self.local_orderbook = {} # token_id -> best_ask
        self.market_map = {}      # yes_id <-> no_id
        self.subscribed_ids = set()
        self.market_cooldowns = {} # market_id -> last_trade_time
        self.is_running = True
        self.notifier = None

    async def run(self):
        logger.info(f">>> Pure Arbitrage V2 (Maker-Taker) Online | Mode: {'DRY' if self.dry_run else 'LIVE'} <<<")
        
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
        """Global NegRisk Scanner: Monitors ALL mutually exclusive markets"""
        while self.is_running:
            try:
                if self.gamma_client:
                    # 💎 ALPHA HEATMAP INTEGRATION (Phase 7)
                    if self.market_ranker and self.market_ranker.top_markets:
                        # Focus search fire only on Hot Zones
                        top_ids = self.market_ranker.get_top_token_ids()
                        new_assets = [tid for tid in top_ids if tid not in self.subscribed_ids]
                        
                        # Register mappings for the top markets
                        for m in self.market_ranker.top_markets:
                            ids = m.get("clob_ids", [])
                            for tid in ids:
                                self.market_map[tid] = ids

                        logger.info(f"🔥 ArbV2 (Heatmap): Focusing on {len(self.market_ranker.top_markets)} Hot Zones")
                    else:
                        # Fallback: Fetch Global NegRisk Markets (Sub-optimal, Phase 6 style)
                        markets = await self.gamma_client.get_active_markets(
                            limit=100, # Lower limit for fallback to save bandwidth
                            neg_risk=True
                        )
                        
                        new_assets = []
                        for m in markets:
                            clob_ids = self._extract_clob_ids(m)
                            if not clob_ids or len(clob_ids) < 2:
                                continue
                            for tid in clob_ids:
                                self.market_map[tid] = clob_ids
                                if tid not in self.subscribed_ids:
                                    new_assets.append(tid)
                    
                    if new_assets:
                        # Update global tracker for new assets
                        for tid in new_assets:
                            self.subscribed_ids.add(tid)
                            
                        logger.info(f"🎯 ArbV2: Subscribed to {len(new_assets)} NEW risk tokens")
                        await self.client.subscribe_orderbook(new_assets, self.on_book_update)
                        
                    logger.info(f"📊 ArbV2 Status: Monitoring {len(self.subscribed_ids)} tokens across prioritized markets")
            
            except Exception as e:
                logger.error(f"ArbV2 market update error: {e}")
            
            await asyncio.sleep(60) # 1분마다 갱신 (Aggressive scan)

    def _extract_clob_ids(self, market: Dict) -> Optional[List[str]]:
        """Extract all CLOB Token IDs from a market"""
        if 'clobTokenIds' in market:
            try:
                raw_ids = market['clobTokenIds']
                return json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
            except:
                pass
        
        tokens = market.get('tokens', [])
        if tokens:
            return [t['token_id'] for t in tokens if 'token_id' in t]
        
        return None

    async def _monitor_bus_updates(self):
        """시장 과열 시 임계값 동적 조정"""
        while self.is_running:
            await asyncio.sleep(15)
            # 호재 시에는 조금 더 보수적으로 (슬리피지 대비)
            hot_tokens = await self.signal_bus.get_hot_tokens(min_sentiment=0.8)
            if hot_tokens:
                self.min_profit_threshold = Decimal("0.02") # 2% Edge Required if busy
            else:
                self.min_profit_threshold = Decimal("0.01") # 1% Standard

    async def on_book_update(self, token_id, book):
        """실시간 오더북 업데이트 핸들러"""
        if hasattr(book, "get_best_ask"):
            best_price, _ = book.get_best_ask()
            if best_price > 0:
                self.local_orderbook[token_id] = Decimal(str(best_price))
                # Trigger check for the whole basket
                await self.check_arbitrage(token_id)

    async def check_arbitrage(self, token_id):
        # Get all siblings in this market
        market_tokens = self.market_map.get(token_id)
        if not market_tokens:
            return

        total_cost = Decimal("0")
        prices = {}
        
        # 💎 COOLDOWN CHECK: Prevent spamming the same opportunity
        market_id = market_tokens[0] # Use first token as key for the market set
        now = time.time()
        if market_id in self.market_cooldowns:
            if now - self.market_cooldowns[market_id] < 60: # 1-minute logic cooldown
                return
        
        # Determine target shares for depth check
        # We use base_trade_size (usually $50) to see if it even clears a profit.
        # size = float(self.base_trade_size)
        # Note: payout size is roughly size / avg_price. Let's assume 100 shares for a $50 bet @ 0.50.
        test_shares = 100.0 
        
        # Check liquidity for ALL tokens in the basket
        for tid in market_tokens:
            # Check local book depth via PolyClient
            book = self.client.orderbooks.get(tid)
            if not book:
                return # Incomplete data, wait
            
            # 💎 DEPTH CHECK: Calculate weighted average price for the desired size
            # This accounts for '호가의 슬리피지' (Orderbook Slippage)
            avg_p = book.get_avg_price_for_shares('BUY', test_shares)
            
            if avg_p <= 0:
                # logger.debug(f"ArbV2: Insufficient depth for {test_shares} shares of {tid[:8]}")
                return # Illiquid leg, abort arb
                
            p_dec = Decimal(str(round(avg_p, 4)))
            prices[tid] = p_dec
            total_cost += p_dec

        # 💎 REALISTIC ARB CONDITION: Sum(AvgFillPrices) < 1.0 - Threshold
        if total_cost < (Decimal("1.0") - self.min_profit_threshold):
            profit = Decimal("1.0") - total_cost
            roi = (profit / total_cost) * 100
            
            logger.warning(f"💰 [ArbV2] GLOBAL NEGRISK OPPORTUNITY! (DEPTH ADJUSTED) Cost: ${total_cost:.4f} | ROI: {roi:.2f}% | Basket Size: {len(market_tokens)}")
            
            # Simple sizing
            size = self.base_trade_size
            
            await self.execute_trade(market_tokens, prices, size)

    async def execute_trade(self, tokens: List[str], prices: Dict[str, Decimal], size: float):
        """
        Executes a NegRisk Arbitrage trade with Dynamic Sizing & Min Notional Guards.
        Ensures 1:1 consistency between Test and Live environments.
        """
        # 1. CALCULATE MIN SHARES FOR LIVE COMPATIBILITY
        # Polymarket requires ~$5.0 notional per order. 
        # If price = 0.01, we need 500 shares.
        MIN_NOTIONAL = Decimal("5.10") # Small buffer
        max_required_shares = Decimal("0")
        
        for tid in tokens:
            p = prices[tid]
            needed_shares = MIN_NOTIONAL / p
            max_required_shares = max(max_required_shares, needed_shares)
        
        # Scale 'size' (Target Payout) up to meet min notional requirements if necessary
        payout_size = max(Decimal(str(size)), max_required_shares)
        
        # 2. BUDGET ALLOCATION (TIER 1 - High Priority)
        total_cost_price = sum(prices.values())
        allocation_needed = payout_size * total_cost_price
        
        if self.budget_manager:
            alloc_id = await self.budget_manager.request_allocation("arbhunter", allocation_needed, priority="high")
            
            # DYNAMIC DOWNSCALING: If request denied, try scaling to available balance (if > min notional)
            if not alloc_id:
                status = await self.budget_manager.get_status()
                # Use arbhunter's specific sub-balance or available capital
                available = Decimal(str(status['balances'].get('arbhunter', 0)))
                if available > (MIN_NOTIONAL * len(tokens)): 
                    payout_size = available * Decimal("0.95") / total_cost_price # Scale down with safety margin
                    allocation_needed = payout_size * total_cost_price
                    logger.info(f"⚖️ ArbV2: Downscaling trade to ${allocation_needed:.2f} due to wallet limits.")
                    alloc_id = await self.budget_manager.request_allocation("arbhunter", allocation_needed, priority="high")
            
            if not alloc_id:
                logger.warning(f"❌ ArbV2: Insufficient budget for even a minimum-size trade (${allocation_needed:.2f} needed)")
                return

        try:
            shares = float(payout_size)
            profit_pct = (1.0 - float(total_cost_price)) * 100
            
            # Update Cooldown
            market_id = tokens[0]
            self.market_cooldowns[market_id] = time.time()

            if self.dry_run:
                # Simulating latency and slippage as in previous version
                await asyncio.sleep(0.1) 
                logger.info(f"🧪 [DRY RUN] NegRisk Arb Success | ROI: {profit_pct:.2f}% | Payout: ${shares:.2f}")
                
                if self.pnl_tracker:
                    for tid in tokens:
                        self.pnl_tracker.record_entry(
                            "arbhunter", tid, "BUY", float(prices[tid]), shares, 
                            metadata={
                                "group": "NEGRISK",
                                "thesis": {
                                    "entry_reason": f"Global NegRisk Arbitrage Basket ({len(tokens)} legs) | Cost: ${total_cost_price:.4f}",
                                    "entry_conditions": {"total_cost": float(total_cost_price), "basket_size": len(tokens)},
                                    "expected_window": "Resolution"
                                }
                            }
                        )

                if self.notifier and not self.dry_run:
                    await self.notifier.notify_trade(
                        side="BUY (NegRisk)",
                        asset=f"Basket ({len(tokens)} Tokens)", 
                        price=float(total_cost_price), 
                        size=shares,
                        profit=shares * (1.0 - float(total_cost_price)),
                        reasoning=f"NegRisk Arb ROI: {profit_pct:.2f}%",
                        strategy="PureArbitrageV2"
                    )
            else:
                orders_data = []
                for tid in tokens:
                    orders_data.append({
                        "token_id": tid, 
                        "side": "BUY", 
                        "size": shares, 
                        "price": float(prices[tid])
                    })
                
                # Phase 8.3: Attempt Atomic Execution via Smart Contract
                success = await self.client.execute_atomic_trade(orders_data)
                
                if success:
                    logger.info(f"✅ ArbV2 Atomic Execution Success | {shares:.2f} shares x {len(tokens)} legs")
                    
                    # Manual Tracking (since direct contract sub might not update balance immediately)
                    if self.pnl_tracker:
                        for tid in tokens:
                            self.pnl_tracker.record_entry(
                                "arbhunter", tid, "BUY", float(prices[tid]), shares, 
                                metadata={"group": "NEGRISK", "execution": "ATOMIC"}
                            )
                else:
                    logger.error("❌ ArbV2 Atomic Execution Failed or Reverted.")
                
        except Exception as e:
            logger.error(f"ArbV2 execution failed: {e}")
        finally:
            if self.budget_manager:
                await self.budget_manager.release_allocation("arbhunter", alloc_id, Decimal("0"))

import json # For json.loads in _extract_clob_ids