import os
import csv
import logging
import asyncio
from datetime import datetime
from src.core.price_history_api import PolymarketHistoryAPI

logger = logging.getLogger(__name__)

class DataLoader:
    def __init__(self, cache_dir="data/backtest_cache"):
        # Use abs path relative to project root
        self.cache_dir = os.path.abspath(cache_dir)
        self.api = PolymarketHistoryAPI()
        os.makedirs(self.cache_dir, exist_ok=True)

    async def download_history(self, token_id: str, days: int = 7) -> str:
        """
        Downloads trade history for a token and saves to CSV.
        Returns the path to the CSV file.
        """
        filepath = os.path.join(self.cache_dir, f"{token_id}.csv")
        
        # Check if recent cache exists (less than 1 hour old)
        if os.path.exists(filepath):
            # For simplicity, we just check existence. Real implementation might check modification time.
            logger.info(f"📂 Using cached data for {token_id}")
            return filepath

        logger.info(f"⬇️ Downloading history for {token_id} ({days} days)...")
        points, source = await self.api.get_history_with_source(token_id, days=days)
        
        if not points:
            logger.warning(f"⚠️ No data found for {token_id}")
            return None

        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'price'])
            for p in points:
                writer.writerow([p['timestamp'].isoformat(), p['price']])
                
        logger.info(f"✅ Saved {len(points)} points to {filepath} (Source: {source})")
        return filepath

    def load_data(self, token_id: str):
        """Loads data from CSV into a list of dicts."""
        filepath = os.path.join(self.cache_dir, f"{token_id}.csv")
        if not os.path.exists(filepath):
            return []
            
        data = []
        with open(filepath, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append({
                    'timestamp': datetime.fromisoformat(row['timestamp']),
                    'price': float(row['price'])
                })
        return data

    async def close(self):
        await self.api.close()
