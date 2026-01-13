import asyncio
import logging
import sys
import os

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.backtest.engine import BacktestEngine

# Setup basic logging
logging.basicConfig(level=logging.INFO)

class TestStrategy:
    def __init__(self, client, budget_manager):
        self.client = client
        self.budget_manager = budget_manager
        
    async def on_tick(self, token_id, price, timestamp):
        # simple mean reversion strategy for testing
        # buy if price < 0.45, sell if price > 0.55
        if price < 0.45:
             await self.client.place_limit_order(token_id, "BUY", price, 10.0)
        elif price > 0.55:
             await self.client.place_limit_order(token_id, "SELL", price, 10.0)

async def main():
    engine = BacktestEngine()
    
    # Use a known active market token for testing
    # This is TRUMP/HARRIS token example or similar, ensuring we get data.
    # Using a random valid-looking hash if specific one not known, 
    # but likely need a real one for data downloader to work.
    # Let's use the one from the test_api example in price_history_api.py if possible,
    # or a known one. 
    # Token ID for "Will Trump win 2024?" (example, might be stale)
    # Better to use the one from gamma_client test or a recent one.
    token_id = "21742633143463906290569050155826241533067272736897614950488156847949938836455" # Example
    
    # Actually, let's use the one found in price_history_api.py test
    token_id = "0x19ee98fe1a1379ef360f5e24965e84a991eb80f6" # from price_history_api.py
    
    await engine.run(TestStrategy, token_id, days=3)

if __name__ == "__main__":
    asyncio.run(main())
