import asyncio
import logging
import time
from typing import Dict, List, Optional
from collections import deque
from src.core.clob_client import PolyClient
from src.core.signal_bus import SignalBus

logger = logging.getLogger(__name__)

class LiquiditySniper:
    """
    Liquidity Sniper Strategy
    =========================
    Monitors the Limit Order Book (CLOB) for sudden "Whale Walls" or "Flash Dumps".
    Acts as a leading indicator provider for the SignalBus.
    
    Logic:
    - Polls order books for 'Hot Tokens' (high sentiment).
    - Tracks Depth @ X% (e.g. 5% from mid).
    - Triggers 'WHALE' signal if depth increases > 500% in short window.
    """

    def __init__(self, client: PolyClient, signal_bus: SignalBus):
        self.client = client
        self.bus = signal_bus
        self.running = False
        
        # Calibration
        self.POLL_INTERVAL = 2.0  # Seconds between checks per token
        self.DEPTH_RANGE_CENTS = 0.05 # Check depth within 5 cents of mid
        self.SURGE_THRESHOLD = 5.0    # 500% increase
        self.WINDOW_SIZE = 10         # Keep last 10 snapshots (~20s)
        
        # State: token_id -> deque of (timestamp, buy_vol, sell_vol)
        self.history: Dict[str, deque] = {}

    async def run(self):
        """Main monitoring loop"""
        self.running = True
        logger.info("🐳 Liquidity Sniper: Scanning for Whale Walls...")
        
        while self.running:
            try:
                # 1. Get targets from Hive Mind (Signal Bus)
                # We only want to spend API credits scanning things that matter (High Sentiment)
                hot_tokens = await self.bus.get_hot_tokens(min_sentiment=0.3)
                
                if not hot_tokens:
                    await asyncio.sleep(5)
                    continue

                # 2. Sequential Scan (Avoid Rate Limits)
                for token_id in list(hot_tokens.keys()):
                    await self._scan_token(token_id)
                    await asyncio.sleep(0.5) # Pace requests
                
                await asyncio.sleep(1.0)
                
            except Exception as e:
                logger.error(f"Liquidity Sniper Loop Error: {e}")
                await asyncio.sleep(5)

    async def _scan_token(self, token_id: str):
        """Fetch OB and analyze liquidity changes"""
        try:
            book = await self.client.get_order_book(token_id)
            if not book: return
            
            bids = book.bids
            asks = book.asks
            
            if not bids or not asks: return
            
            best_bid = float(bids[0].price)
            best_ask = float(asks[0].price)
            mid = (best_bid + best_ask) / 2
            
            # Calculate Depth
            buy_wall_vol = sum(float(b.size) for b in bids if float(b.price) >= mid - self.DEPTH_RANGE_CENTS)
            sell_wall_vol = sum(float(a.size) for a in asks if float(a.price) <= mid + self.DEPTH_RANGE_CENTS)
            
            # Update History
            if token_id not in self.history:
                self.history[token_id] = deque(maxlen=self.WINDOW_SIZE)
                
            self.history[token_id].append((time.time(), buy_wall_vol, sell_wall_vol))
            
            # Analysis
            await self._analyze_surge(token_id, buy_wall_vol, sell_wall_vol)

        except Exception as e:
            logger.debug(f"Scan failed for {token_id}: {e}")

    async def _analyze_surge(self, token_id: str, current_buy: float, current_sell: float):
        """Detect rapid changes in liquidity"""
        history = self.history[token_id]
        if len(history) < 3: return
        
        # Compare vs average of past window (excluding current)
        past_buys = [h[1] for h in list(history)[:-1]]
        avg_buy = sum(past_buys) / len(past_buys) if past_buys else 0.1
        
        # Check Buy Wall Surge
        if avg_buy > 100: # Ignore noise in illiquid markets
            ratio = current_buy / avg_buy
            if ratio > self.SURGE_THRESHOLD:
                logger.info(f"🐳 WHALE DETECTED: Buy Wall Surge {ratio:.1f}x on {token_id[:10]} (Vol: {avg_buy:.0f}->{current_buy:.0f})")
                await self.bus.update_signal(
                    token_id, 
                    source='WHALE', 
                    score=min(1.0, 0.5 + (ratio * 0.1)), # Base 0.5, adds more for bigger surge
                    side='BUY'
                )

        # Check Flash Dump (Liquidity Vanish)
        # If huge wall suddenly disappears (ratio < 0.1)
        if avg_buy > 5000: 
            ratio = current_buy / avg_buy
            if ratio < 0.1:
                logger.warning(f"📉 LIQUIDITY VANISH: Buy Wall Pulled on {token_id[:10]} ({avg_buy:.0f}->{current_buy:.0f})")
                await self.bus.update_signal(
                    token_id,
                    source='WHALE',
                    score=0.8, 
                    side='SELL' # Interpret as Bearish
                )
