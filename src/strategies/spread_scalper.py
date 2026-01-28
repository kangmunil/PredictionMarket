import asyncio
import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
from src.core.clob_client import PolyClient
from src.core.gamma_client import GammaClient
from src.core.config import Config

logger = logging.getLogger(__name__)

class SpreadScalper:
    """
    HFT-style Spread Scalper
    
    Strategy:
    1. Identify markets with healthy spread (1% < spread < 5%)
    2. Provide liquidity at Bid/Ask or snipe lazy orders
    3. Strict inventory management (Max $50 per token)
    4. Auto-unwind if position held > 1 hour
    """
    def __init__(self, client: PolyClient, gamma_client: GammaClient = None, budget_manager = None):
        self.client = client
        self.gamma_client = gamma_client
        self.budget_manager = budget_manager
        self.config = Config()
        
        # HFT Parameters
        self.min_spread = 0.015 # 1.5% Minimum spread to carry
        self.max_spread = 0.05  # 5.0% Max spread (avoid illiquid traps)
        self.min_depth = 50.0   # $50 depth required at top level
        self.size_per_clip = 10.0 # $10 per order
        self.max_inventory = 50.0 # Max $50 exposure per token
        
        # Safety Nets
        self.circuit_breaker_triggered = False
        self.circuit_breaker_until = None
        self.recent_pnl = [] # List of (timestamp, pnl_amount)
        self.max_loss_limit = -10.0 # -$10 in 15 mins triggers breaker
        
        # State
        self.active_orders = {} # token_id -> [order_ids]
        self.inventory: Dict[str, dict] = {} # token_id -> {size, entry_price, entry_time}
        self.is_running = True

    async def run(self):
        logger.info("⚡ SpreadScalper (HFT) Online")
        
        while self.is_running:
            try:
                # 0. Check Circuit Breaker
                if self._check_circuit_breaker():
                    await asyncio.sleep(60)
                    continue

                # 1. Manage Inventory (Auto-Unwind)
                await self._manage_inventory()

                # 2. Scan & Quote
                if not self.budget_manager or not self.budget_manager.is_low_capital:
                    await self._scan_and_quote()
                
                await asyncio.sleep(5) # Fast cycle (5s)

            except Exception as e:
                logger.error(f"SpreadScalper loop error: {e}")
                await asyncio.sleep(5)

    def _check_circuit_breaker(self) -> bool:
        """Return True if breaker is active"""
        now = datetime.now()
        
        # Check if currently tripped
        if self.circuit_breaker_until:
            if now < self.circuit_breaker_until:
                remaining = (self.circuit_breaker_until - now).seconds // 60
                logger.warning(f"🚨 HFT Circuit Breaker Active! Resuming in {remaining} mins")
                return True
            else:
                logger.info("✅ HFT Circuit Breaker Reset. Resuming operations.")
                self.circuit_breaker_triggered = False
                self.circuit_breaker_until = None
                self.recent_pnl = [] # Reset PnL tracking
                return False

        # Calculate recent PnL (last 15 mins)
        cutoff = now - timedelta(minutes=15)
        self.recent_pnl = [p for p in self.recent_pnl if p[0] > cutoff]
        
        total_recent_loss = sum(p[1] for p in self.recent_pnl if p[1] < 0)
        
        if total_recent_loss <= self.max_loss_limit:
            logger.critical(f"💥 HFT Circuit Breaker TRIPPED! Loss {total_recent_loss:.2f} <= {self.max_loss_limit}")
            self.circuit_breaker_triggered = True
            self.circuit_breaker_until = now + timedelta(hours=1)
            # Cancel all Orders
            asyncio.create_task(self.client.cancel_all_orders())
            return True
            
        return False

    async def _manage_inventory(self):
        """Monitor held positions for auto-unwind or stop-loss"""
        # Sync with actual account? For now, trusting internal state + periodic sync
        # In a real HFT, we'd listen to fill streams.
        
        for token_id, pos in list(self.inventory.items()):
            # Check holding time
            held_duration = datetime.now() - pos['entry_time']
            if held_duration > timedelta(hours=1):
                logger.info(f"⌛ [Auto-Unwind] Held {token_id[:10]} for {held_duration}. Force closing.")
                await self._force_close(token_id, pos['size'])
                continue
                
            # TODO: Check Stop Loss logic if price dumps fast
            # (Simplified for now)

    async def _force_close(self, token_id: str, size: float):
        """Market sell to free up inventory"""
        try:
            if self.config.DRY_RUN:
                logger.info(f"🧪 [DRY RUN] Force Sold {size} of {token_id}")
                self.inventory.pop(token_id, None)
                # Record simulated slight loss due to spread crossing
                self.recent_pnl.append((datetime.now(), -0.05)) 
                return

            await self.client.place_market_order(token_id, "SELL", size)
            self.inventory.pop(token_id, None)
        except Exception as e:
            logger.error(f"Failed to force close {token_id}: {e}")

    async def _scan_and_quote(self):
        """Find markets with goldilocks spread and place orders"""
        if not self.gamma_client: return

        # Get high liquidity markets
        markets = await self.gamma_client.get_active_markets(limit=20, volume_min=5000)
        
        for market in markets:
            # Get simplified token A (Binary)
            token_id = self._get_primary_token(market)
            if not token_id: continue
            
            # Check inventory limit
            current_inv = self.inventory.get(token_id, {}).get('size', 0) * 0.5 # Approx USD
            if current_inv >= self.max_inventory:
                continue

            # Check Orderbook
            ob = await self.client.get_order_book(token_id)
            if not ob: continue
            
            best_bid_price, best_bid_size = ob.get_best_bid()
            best_ask_price, best_ask_size = ob.get_best_ask()
            
            if best_bid_price == 0 or best_ask_price == 0: continue
            
            spread = (best_ask_price - best_bid_price) / best_bid_price
            
            # 🛡️ Spread Guard
            if spread < self.min_spread or spread > self.max_spread:
                continue
                
            # 🛡️ Depth Guard (Check top level)
            bid_depth = best_bid_size * best_bid_price
            if bid_depth < self.min_depth:
                continue
                
            # Opportunity Found: Place Maker Order at Best Bid
            logger.info(f"🎯 Spread Opp: {market.get('question')[:20]} | Spread: {spread*100:.2f}% | Depth: ${bid_depth:.0f}")
            
            await self._place_maker_buy(token_id, best_bid_price)

    async def _place_maker_buy(self, token_id: str, price: float):
        """Place a limit buy order"""
        amount = self.size_per_clip
        
        # Budget Check
        if self.budget_manager:
            alloc = await self.budget_manager.request_allocation("spread_scalper", Decimal(str(amount)))
            if not alloc: return

        try:
            shares = amount / price
            
            if self.config.DRY_RUN:
                logger.info(f"🧪 [DRY RUN] Quoting BUY {shares:.1f} @ {price}")
                # Simulate fill after random delay? 
                # For now, let's assume 10% fill rate for simulation fun
                import random
                if random.random() < 0.1:
                    logger.info("   ✨ [DRY RUN] Filled!")
                    self.inventory[token_id] = {
                        'size': shares, 
                        'entry_price': price, 
                        'entry_time': datetime.now()
                    }
            else:
                # Post Limit Order
                # Note: place_limit_order usually returns immediately. Fill updates happen via WS.
                # For this simplest MVP, we just place GTC.
                resp = await self.client.create_order(
                    token_id=token_id,
                    side="BUY",
                    price=price,
                    size=shares,
                    type="LIMIT"
                )
                logger.info(f"   📝 Order Placed: {resp.get('id')}")

        except Exception as e:
            logger.error(f"Quote failed: {e}")
            if self.budget_manager:
                await self.budget_manager.release_allocation("spread_scalper", alloc, Decimal(str(amount)))

    def _get_primary_token(self, market: dict) -> Optional[str]:
        # Helper to get YES token
        try:
            clob_ids = market.get('clobTokenIds')
            if clob_ids:
                if isinstance(clob_ids, str):
                    import json
                    return json.loads(clob_ids)[0]
                return clob_ids[0]
        except: pass
        return None
