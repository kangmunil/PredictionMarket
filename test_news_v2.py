import asyncio
import sys
import os
import time
from decimal import Decimal

sys.path.insert(0, 'src')

from news.news_scalper import NewsScalperV2
from core.clob_client import PolyClient

async def test_v2_pipeline():
    print("\n" + "=" * 80)
    print("🚀 News Scalper V2 Pipeline Test")
    print("=" * 80)

    # Mock PolyClient
    client = PolyClient(strategy_name="TestV2")
    scalper = NewsScalperV2(clob_client=client, dry_run=True)

    # 1. Mock News Data
    mock_news = [
        {"title": "Bitcoin Surges Past $100,000 in Historic Rally", "url": "url1"},
        {"title": "Fed Announces Aggressive Interest Rate Cut", "url": "url2"},
        {"title": "SEC Files Lawsuit Against Major Crypto Exchange", "url": "url3"}
    ]

    # 2. Process News Individually
    keywords = ["bitcoin", "crypto", "fed", "sec", "rate"]
    
    for item in mock_news:
        print(f"\nIncoming: {item['title']}")
        await scalper._process_news_fast(item, keywords)
        # Small sleep to allow async tasks to log
        await asyncio.sleep(1)

    # 3. Check Results
    print("\n" + "=" * 80)
    scalper._print_stats()
    print(f"Active Positions: {len(scalper.active_positions)}")
    print("=" * 80)
    print("✅ V2 Pipeline Test Complete")

if __name__ == "__main__":
    asyncio.run(test_v2_pipeline())
