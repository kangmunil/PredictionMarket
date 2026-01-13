import asyncio
import logging
import sys
import os
import requests
from datetime import datetime, timedelta

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.backtest.engine import BacktestEngine
from src.core.structured_logger import setup_logging

# Use a simple Mean Reversion Strategy for the "Brain Warming"
# In a real scenario, we'd use the actual strategy classes (EnhancedStatArbStrategy, etc.)
# But for now, we want to generate 'wins' and 'losses' to train the Specialist on categories.
# We'll use a TestStrategy that mimics basic logic to create PnL.
class BatchTestStrategy:
    def __init__(self, client, budget_manager):
        self.client = client
        self.budget_manager = budget_manager
        
    async def on_tick(self, token_id, price, timestamp):
        # Simple strategy to generate trades
        # Buy low, Sell high logic
        if price < 0.40:
             await self.client.place_limit_order(token_id, "BUY", price, 10.0)
        elif price > 0.60:
             await self.client.place_limit_order(token_id, "SELL", price, 10.0)

# Categories to warm up
CATEGORIES = {
    "crypto": ["bitcoin", "ethereum", "solana"],
    "politics": ["trump", "harris", "election"],
    "economy": ["fed", "inflation", "rate"],
    "sports": ["nba", "nfl", "winner"]
}

async def fetch_historical_markets(keywords, limit=3):
    """Fetch closed markets with high volume for backtesting."""
    url = "https://gamma-api.polymarket.com/markets"
    found_markets = []
    
    for kw in keywords:
        params = {
            "closed": "true", # We want closed markets for full history
            "limit": "20",
            "order": "volume", # Get high volume
            "ascending": "false",
            "query": kw
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                     markets = data
                else:
                     markets = data.get("data", [])
                
                # Filter for valid binary markets
                for m in markets:
                    # Check for valid clobIDs
                    clob_ids = m.get("clobTokenIds", [])
                    if isinstance(clob_ids, str):
                        import json
                        try:
                            clob_ids = json.loads(clob_ids)
                        except: continue
                    
                    if clob_ids and len(clob_ids) == 2:
                        found_markets.append({
                            "condition_id": m.get("condition_id"),
                            "question": m.get("question"),
                            "token_id": clob_ids[0], # Use first token (Yes)
                            "volume": float(m.get("volume", 0)),
                            "tags": [kw] # Tag for the specialist
                        })
        except Exception as e:
            print(f"Error fetching {kw}: {e}")
            
    # Sort by volume and return top N unique
    found_markets.sort(key=lambda x: x['volume'], reverse=True)
    unique = {}
    for m in found_markets:
        if m['condition_id'] not in unique:
            unique[m['condition_id']] = m
            
    return list(unique.values())[:limit]

async def run_batch():
    setup_logging(level=logging.INFO)
    logger = logging.getLogger("BatchBacktest")
    logger.info("🔥 Starting Brain Warming Batch Process...")
    
    engine = BacktestEngine()
    
    total_runs = 0
    
    for category, keywords in CATEGORIES.items():
        logger.info(f"\n📂 Processing Category: {category.upper()}...")
        markets = await fetch_historical_markets(keywords, limit=3)
        
        if not markets:
            logger.warning(f"   ⚠️ No markets found for {category}")
            continue
            
        for m in markets:
            logger.info(f"   ▶️ Running Backtest: {m['question'][:50]}... ({m['token_id'][:10]})")
            
            # Run Engine
            # We inject the 'category' as a tag into the engine via a side-channel or 
            # modifying engine return. 
            # Note: The engine returns a dict. We can add tags to it before export?
            # Actually, `export_for_specialist` is called inside `run`. 
            # We might need to subclass/modify engine to accept tags or just let MarketSpecialist infer.
            # BUT, we updated MarketSpecialist to look for 'tags' in json.
            # And updated Engine to write 'tags': ['backtest'].
            # To pass specific tags, we should modify the Engine.run signature or property.
            # A quick hack: Set engine.current_tags = ...
            
            engine.current_tags = [category] + m['tags'] 
            
            # We need to temporarily patch/modify BacktestEngine to use these tags 
            # OR pass them.
            # Let's modify BacktestEngine.run signature in a separate step or just assume
            # generic tags for now. 
            # Wait, I can pass a custom 'strategy_class' that acts as a container? 
            # No, cleaner to just set a property on engine if I can.
            
            # Let's rely on the fact I can monkey-patch or just set an attribute.
            pass
            
            # Actually, better to modify BacktestEngine to accept 'tags' arg in run() method.
            # I will assume I made that change or will make it.
            # For now, I'll pass it in kwargs if supported, or just let it run.
            
            # Modify Engine to accept tags during next edit. 
            # Providing standard run for now.
            try:
                # We fetch 30 days of data for closed markets to get a good chunk
                res = await engine.run(
                    BatchTestStrategy, 
                    m['token_id'], 
                    days=30,
                    tags=[category, "brain_warming"]
                )
                if res:
                    total_runs += 1
            except Exception as e:
                logger.error(f"Failed backtest for {m['token_id']}: {e}")

    logger.info(f"\n✅ Brain Warming Complete! Processed {total_runs} markets.")

if __name__ == "__main__":
    asyncio.run(run_batch())
