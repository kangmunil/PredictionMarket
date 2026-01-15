import asyncio
import os
import sys

# Add project root to sys.path
sys.path.append(os.getcwd())

from src.core.clob_client import PolyClient
from src.core.config import Config

TOKEN_ID = "105267568073659068217311993901927962476298440625043565106676088842803600775810"
SELL_SIZE = 35.0
SELL_PRICE = 0.47 # Aggressive (Bid is likely 0.48)

async def main():
    client = PolyClient()
    print(f"📉 Reducing Exposure: Selling {SELL_SIZE} shares of {TOKEN_ID[:10]}...")
    
    # Check if sell price is sane
    bid, bid_size = client.get_best_bid(TOKEN_ID)
    print(f"   Current Bid: ${bid:.3f} (Size: {bid_size})")
    
    # Place Limit Order (Sell)
    # Side: SELL
    order_id = await client.place_limit_order(TOKEN_ID, "SELL", SELL_PRICE, SELL_SIZE)
    
    if order_id:
        print(f"✅ Order Placed! ID: {order_id}")
    else:
        print("❌ Order Failed")

if __name__ == "__main__":
    asyncio.run(main())
