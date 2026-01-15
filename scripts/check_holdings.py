import asyncio
import os
import sys

# Add project root to sys.path
sys.path.append(os.getcwd())

from src.core.clob_client import PolyClient
from src.core.config import Config

async def main():
    client = PolyClient()
    positions = await client.get_all_positions()
    print(f"🔍 Found {len(positions)} positions:")
    for p in positions:
        print(f" - Token: {p.get('asset')}")
        print(f" - Size: {p.get('size')}")
        print(f" - Value (Approx): {float(p.get('size')) * 0.5}") # Rough calc
    
    # Get Balance
    bal = await client.get_usdc_balance()
    print(f"💰 Balance: ${bal:.2f}")

if __name__ == "__main__":
    asyncio.run(main())
