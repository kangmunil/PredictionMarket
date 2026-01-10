import asyncio
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.news.news_aggregator import NewsAggregator

logging.basicConfig(level=logging.INFO)

async def test_aggregator():
    agg = NewsAggregator()
    
    print("Fetching news for 'bitcoin'...")
    articles = await agg.get_breaking_news(["bitcoin", "crypto"], max_results=10)
    
    print(f"Found {len(articles)} articles.")
    for a in articles:
        print(f"- {a['title']} ({a['source']['name']})")
        
    await agg.close()

if __name__ == "__main__":
    asyncio.run(test_aggregator())
