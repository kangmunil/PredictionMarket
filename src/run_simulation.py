import asyncio
import logging
import sys
from unittest.mock import MagicMock

# --- SYSTEM HOT PATCH: Mocking Core for Simulation ---
# This ensures we can run the sim even if 'py-clob-client' isn't installed.
mock_clob = MagicMock()
sys.modules["py_clob_client"] = mock_clob
sys.modules["py_clob_client.client"] = mock_clob
sys.modules["py_clob_client.clob_types"] = mock_clob
sys.modules["py_clob_client.constants"] = mock_clob

# Now we can safely import our internal modules
try:
    from src.core.clob_client import PolyClient
except ImportError:
    # If it still fails, force a mock for our internal client too
    class PolyClient:
        def __init__(self): self.rest_client = MagicMock()
        def place_market_order(self, *args): return asyncio.sleep(0)
    sys.modules["src.core.clob_client"] = MagicMock()
    sys.modules["src.core.clob_client"].PolyClient = PolyClient

from src.strategies.arbitrage import ArbitrageStrategy
from src.strategies.stat_arb import StatArbStrategy

# Setup quiet logging for the simulation
logging.basicConfig(level=logging.WARN) 
logger = logging.getLogger("ArbHunter-Sim")
logger.setLevel(logging.INFO)

async def run_simulation():
    print("\n" + "="*50)
    print("      ARBHUNTER BOT - DIAGNOSTIC SIMULATION      ")
    print("="*50 + "\n")

    client = PolyClient()
    
    # 1. Run Arbitrage Simulation
    arb_strat = ArbitrageStrategy(client)
    arb_results = await arb_strat.simulate()
    
    print("-" * 50)
    
    # 2. Run Stat Arb Simulation
    stat_strat = StatArbStrategy(client)
    stat_results = await stat_strat.simulate()

    print("\n" + "="*50)
    print("              FINAL SIGNAL REPORT                ")
    print("="*50)
    
    if arb_results:
        print("\n[TYPE: BINARY ARBITRAGE (Risk-Free)]")
        print(f"{'MARKET':<30} | {'PRICES':<20} | {'ROI':<10}")
        print("-" * 65)
        for r in arb_results:
            print(f"{r['market']:<30} | {r['prices']:<20} | {r['est_roi']:<10}")

    if stat_results:
        print("\n[TYPE: STATISTICAL ARBITRAGE (Low-Risk)]")
        print(f"{'PAIR':<30} | {'DIVERGENCE':<20} | {'ACTION'}")
        print("-" * 80)
        for r in stat_results:
            print(f"{r['pair']:<30} | {r['divergence']:<20} | {r['action']}")

    print("\n" + "="*50)
    print("LEGAL/ETHICAL DISCLAIMER:")
    print("1. Arbitrage is competitive; past performance (simulated) != future results.")
    print("2. 'Risk-free' applies only to atomic execution; slippage/latency are real risks.")
    print("3. Ensure compliance with Polymarket ToS regarding bot activity.")
    print("="*50 + "\n")

if __name__ == "__main__":
    asyncio.run(run_simulation())
