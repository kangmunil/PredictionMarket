import asyncio
import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.clob_client import PolyClient
from src.core.config import Config

async def liquidation_procedure():
    print("🚨 STARTING EMERGENCY LIQUIDATION 🚨")
    client = PolyClient()
    
    # 1. Cancel All Orders
    print("🗑️ Canceling open orders...")
    try:
        await client.cancel_all_orders()
        print("✅ Orders Cancelled.")
    except Exception as e:
        print(f"❌ Error canceling orders: {e}")

    # 2. Get All Positions
    print("🔍 Fetching open positions...")
    positions = await client.get_all_positions()
    if not positions:
        print("✅ No open positions found. Clean start.")
        await client.close()
        return

    print(f"found {len(positions)} positions.")

    # 3. Close Each Position
    for pos in positions:
        token_id = pos.get("asset") # or 'asset_id'?
        size = float(pos.get("size", 0))
        if size <= 0: continue
        
        print(f"📉 Closing position {token_id[:15]}... Size: {size}")
        
        # We need to know SIDE to close.
        # If we hold YES, we Sell YES. If we hold NO, we Sell NO.
        # Check balance.
        try:
             # Basic dump: Place limit sell at 0.01 (or best bid)
             # ClobClient doesn't have simple 'close_position'. We must place order.
             # We sell 'size' of 'token_id'.
             
             # Fetch orderbook to be nice? No, user said JUST SELL.
             # We will place an IOC or FOK limit sell at a very low price to simulate market sell
             # BUT Polymarket doesn't support 'Market' orders natively on CLOB mostly.
             # We place Limit Sell at 0.05 or lower.
             
             resp = await client.place_limit_order(
                 token_id=token_id,
                 side="SELL",
                 price=0.01, # Dump it
                 size=size
             )
             print(f"   ✅ Sell Order Placed: {resp}")
        except Exception as e:
            print(f"   ❌ Failed to close {token_id}: {e}")

    print("✅ Liquidation Complete.")
    await client.close()

if __name__ == "__main__":
    asyncio.run(liquidation_procedure())
