import asyncio
import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())

from src.core.clob_client import PolyClient
from src.core.config import Config

async def main():
    load_dotenv()
    print("🚀 Initializing Liquidation Client...")
    
    config = Config()
    client = PolyClient(config)
    await client.start_ws() # Minimal init for auth
    
    print("🔍 Fetching open positions...")
    positions = client.get_open_positions()
    
    if not positions:
        print("✅ No open positions found.")
        await client.close()
        return

    print(f"⚠️ Found {len(positions)} open positions. LIQUIDATING ALL...")
    
    for pos in positions:
        token_id = pos.get("asset")
        size = float(pos.get("size", 0))
        side = "SELL" # Always sell to close long? Or opposite?
        # Typically positions are "Long" (held tokens). We sell them.
        
        if size > 0:
            print(f"💸 Selling {size} of {token_id}...")
            try:
                # Use market order to close immediately
                resp = await client.place_order(
                    token_id=token_id,
                    side="SELL",
                    size=size,
                    price=0.01 # Market sell roughly
                )
                print(f"   ✅ Executed: {resp}")
            except Exception as e:
                print(f"   ❌ Failed: {e}")
                
    print("🏁 Liquidation Complete.")
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
