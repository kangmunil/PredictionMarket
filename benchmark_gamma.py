
import asyncio
import os
import sys
from decimal import Decimal

# Add current directory to path
sys.path.append(os.getcwd())

from src.core.gamma_client import GammaClient
from src.strategies.crypto_15min_filter import Crypto15MinFilter

async def main():
    print("🚀 Benchmarking Gamma API and Crypto15MinFilter...")
    
    gamma = GammaClient()
    filter = Crypto15MinFilter()
    
    print("\n1. Deep Scanning for Bitcoin markets (Top 300 Volume)...")
    all_markets = await gamma.get_active_markets(limit=300)
    print(f"✅ Scanned {len(all_markets)} active markets")

    print("\n2. Testing Filter on Bitcoin Markets:")
    found_any = False
    for m in all_markets:
        q = m.get('question', '')
        if 'bitcoin' in q.lower() or 'btc' in q.lower():
            found_any = True
            is_match = filter.is_crypto_15min_market(m)
            status = "✅ PASS" if is_match else "❌ FAIL"
            print(f" {status} | {q} (Vol: ${m.get('volume', 0)})")

    if not found_any:
        print("⚠️ No Bitcoin markets found in top 300 volume rankings.")

    await gamma.close()

if __name__ == "__main__":
    asyncio.run(main())
