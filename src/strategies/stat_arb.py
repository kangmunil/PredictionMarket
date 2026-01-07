import asyncio
import logging
import numpy as np
import pandas as pd
from typing import List, Tuple
from decimal import Decimal
from src.core.clob_client import PolyClient

logger = logging.getLogger(__name__)

class StatArbStrategy:
    """
    EliteMimic Strategy 2: Sharky6999 Style (Statistical Arbitrage)
    Target: Correlated markets (Pairs Trading).
    Logic: Trade Mean Reversion when spread Z-Score exceeds threshold (e.g., > 2.0).
    """
    def __init__(self, client: PolyClient, gamma_client=None):
        self.client = client
        self.gamma_client = gamma_client
        self.lookback_window = 24  # Look back 24 periods (e.g., hours)
        self.z_threshold = 2.0     # Trigger trade if divergence is > 2 sigma
        self.stop_loss_z = 4.0     # Close trade if divergence blows up
        
        # Initial pairs (Real IDs found earlier as baseline)
        self.pairs = [
            (
                "0x19ee98e348c0ccb341d1b9566fa14521566e9b2ea7aed34dc407a0ec56be36a2", 
                "0xe6508d867d153a268bdab732aa8abc8cc57e652d28a23aa042da40895bf031b2", 
                "BTC/ETH Correlation (Static)"
            )
        ]
        
        self.active_positions = {}

    async def resolve_pairs(self):
        """Dynamically find correlated market IDs using Gamma API"""
        if not self.gamma_client:
            return

        logger.info("🔍 StatArb: Resolving dynamic market pairs...")
        new_pairs = []
        
        try:
            # 1. Search for Bitcoin market
            btc_markets = await self.gamma_client.search_markets("Bitcoin price")
            # 2. Search for Ethereum or SOL market
            eth_markets = await self.gamma_client.search_markets("Ethereum price")
            
            if btc_markets and eth_markets:
                # Extract first valid token ID (YES token is usually index 0)
                btc_id = json.loads(btc_markets[0]['clobTokenIds'])[0] if isinstance(btc_markets[0]['clobTokenIds'], str) else btc_markets[0]['clobTokenIds'][0]
                eth_id = json.loads(eth_markets[0]['clobTokenIds'])[0] if isinstance(eth_markets[0]['clobTokenIds'], str) else eth_markets[0]['clobTokenIds'][0]
                
                new_pairs.append((btc_id, eth_id, f"BTC/ETH ({btc_markets[0]['slug'][:10]})"))
                logger.info(f"   ✅ Linked: {btc_markets[0]['question'][:30]}... <-> {eth_markets[0]['question'][:30]}...")

            # 3. Search for Trump/Politics correlation
            trump_markets = await self.gamma_client.search_markets("Trump Fed Chair")
            if btc_markets and trump_markets:
                trump_id = json.loads(trump_markets[0]['clobTokenIds'])[0] if isinstance(trump_markets[0]['clobTokenIds'], str) else trump_markets[0]['clobTokenIds'][0]
                # Reuse btc_id from above
                new_pairs.append((btc_id, trump_id, "BTC/Trump Correlation"))
                logger.info(f"   ✅ Linked: Bitcoin <-> {trump_markets[0]['question'][:30]}...")

            if new_pairs:
                self.pairs = new_pairs
                logger.info(f"🚀 StatArb: Successfully resolved {len(self.pairs)} dynamic pairs")
        except Exception as e:
            logger.error(f"❌ StatArb Pair Resolution Failed: {e}")

    async def run(self):
        logger.info("🛡️ Stat Arb Shield Activated. Monitoring market correlations...")
        
        # Resolve IDs at startup
        await self.resolve_pairs()
        
        while True:
            try:
                for token_a, token_b, pair_name in self.pairs:
                    await self.analyze_pair(token_a, token_b, pair_name)
                
                # Check active positions for exit signals
                # await self.manage_positions()
                
                await asyncio.sleep(20) # Scan every 20 seconds
            except Exception as e:
                logger.error(f"StatArb Error: {e}")
                await asyncio.sleep(20)

    async def analyze_pair(self, token_a: str, token_b: str, pair_name: str):
        """
        Calculates correlation and Z-Score of the price spread.
        """
        # 1. Fetch Historical Data (Simulated for Prototype)
        # In prod: self.client.get_price_history(token_a)
        prices_a = self.fetch_history(token_a)
        prices_b = self.fetch_history(token_b)
        
        if len(prices_a) != len(prices_b):
            logger.warning(f"Data mismatch for {pair_name}")
            return

        # 2. Create DataFrame
        df = pd.DataFrame({
            'A': prices_a,
            'B': prices_b
        })
        
        # 3. Calculate Spread and Z-Score
        # Spread = Price A - Price B
        # Ideally, we use log prices or ratio, but simple difference works for 0-1 range.
        df['spread'] = df['A'] - df['B']
        
        mean_spread = df['spread'].mean()
        std_spread = df['spread'].std()
        
        current_spread = df['spread'].iloc[-1]
        
        if std_spread == 0:
            return

        z_score = (current_spread - mean_spread) / std_spread
        
        # Correlation check
        correlation = df['A'].corr(df['B'])
        
        # Log status
        # logger.debug(f"[{pair_name}] Corr: {correlation:.2f} | Z-Score: {z_score:.2f} | Spread: {current_spread:.3f}")

        # 4. Generate Signals
        if abs(z_score) > self.z_threshold:
            await self.execute_mean_reversion(token_a, token_b, z_score, pair_name, current_spread)

    async def execute_mean_reversion(self, token_a, token_b, z_score, pair_name, spread):
        """
        Execute Hedging / Arb Trade.
        If Z > 0 (Spread too high): Sell A, Buy B (expect A to drop, B to rise)
        If Z < 0 (Spread too low): Buy A, Sell B
        """
        amount = 10.0
        
        logger.info(f"🚨 STAT ARB SIGNAL [{pair_name}]")
        logger.info(f"   Z-Score: {z_score:.2f} (Threshold: {self.z_threshold})")
        logger.info(f"   Reason: Divergence detected. Expecting reversion to mean spread {spread:.3f}")
        
        logger.info("   ✅ Executing Stat Arb Pair Trade...")
        
        if z_score > 0:
            # Spread A-B is too high. A is expensive, B is cheap.
            logger.info(f"   Action: SHORT A ({token_a}) / LONG B ({token_b})")
            await self.client.place_market_order(token_a, "SELL", amount)
            await self.client.place_market_order(token_b, "BUY", amount)
        else:
            # Spread A-B is too low. A is cheap, B is expensive.
            logger.info(f"   Action: LONG A ({token_a}) / SHORT B ({token_b})")
            await self.client.place_market_order(token_a, "BUY", amount)
            await self.client.place_market_order(token_b, "SELL", amount)

    def fetch_history(self, token_id):
        """
        Mock history generator using Random Walk with drift.
        To simulate divergence, we add random noise.
        """
        # Create a base trend
        base_price = 0.5
        trend = np.linspace(0, 0.1, 24) # Slight upward trend
        noise = np.random.normal(0, 0.02, 24)
        
        # Make tokens correlated but sometimes diverging
        if "btc" in token_id:
            return list(np.clip(base_price + trend + noise, 0.01, 0.99))
        elif "eth" in token_id:
            # High correlation to BTC normally
            return list(np.clip(base_price + trend + noise + np.random.normal(0, 0.05, 24), 0.01, 0.99))
        else:
            return list(np.clip(base_price + noise, 0.01, 0.99))