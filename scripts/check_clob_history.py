import asyncio
import os
import sys
from dotenv import load_dotenv

sys.path.append(os.getcwd())

from src.core.price_history_api import PolymarketHistoryAPI
from src.core.config import Config

async def main():
    load_dotenv()
    api = PolymarketHistoryAPI() # Use default URL

    
    # BTC 15m condition ID
    condition_id = "0xb318b53528ed532d3e01ab0dbeb58db586474f44f7a5ad030611d0ecb63c6767"
    print(f"🔍 Checking history for Condition ID: {condition_id}")
    
    # 1. First, snapshot to get token ID
    snapshot = await api._fetch_market_snapshot(condition_id)
    print(f"📸 Snapshot Result: {snapshot.keys() if snapshot else 'None'}")
    if snapshot:
        print(f"   Name: {snapshot.get('question')}")
        print(f"   Token IDs: {snapshot.get('clobTokenIds')}")
        
        token_id = None
        if snapshot.get("clobTokenIds"):
            token_id = snapshot["clobTokenIds"][0]
            print(f"   🎯 Target Token ID: {token_id}")
        
        if token_id:
            # 2. Fetch history
            print("⏳ Fetching CLOB history...")
            history = await api._fetch_clob_history(token_id)
            print(f"📊 History Points: {len(history) if history else 0}")
            if history:
                print(f"   First: {history[0]}")
                print(f"   Last: {history[-1]}")
            else:
                print("   ❌ No history returned")

if __name__ == "__main__":
    asyncio.run(main())
