import os
import json
import logging
from typing import List, Dict
from datetime import datetime, timedelta
from dotenv import load_dotenv
from .memory_manager import MarketMemory

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DataSeeder")

class DataSeeder:
    def __init__(self):
        load_dotenv()
        self.memory = MarketMemory()

    def seed_initial_events(self):
        """Seed hardcoded key events for multiple categories"""
        events = [
            # Crypto
            {
                "entity": "Bitcoin",
                "content": "SEC approves 11 Spot Bitcoin ETFs.",
                "category": "Crypto",
                "impact": {"price_change": -0.05, "outcome": "Sell the news"}
            },
            {
                "entity": "FTX",
                "content": "FTX files for Chapter 11 bankruptcy.",
                "category": "Crypto",
                "impact": {"price_change": -0.25, "outcome": "Market Crash"}
            },
            # Politics
            {
                "entity": "Trump",
                "content": "Trump wins the Iowa caucus with a landslide.",
                "category": "Politics",
                "impact": {"market_move": "Trump tokens up", "outcome": "Bullish for Republican markets"}
            },
            # Economics
            {
                "entity": "Fed",
                "content": "Federal Reserve pauses interest rate hikes after 10 consecutive increases.",
                "category": "Economics",
                "impact": {"market_move": "Equity markets rally", "outcome": "Dovish Pivot"}
            }
        ]

        logger.info(f"🌱 Seeding {len(events)} events...")
        if not self.memory.enabled:
            logger.error("❌ Memory system disabled. Check keys.")
            return

        for event in events:
            self.memory.add_memory(
                category=event["category"],
                entity=event["entity"],
                content=event["content"],
                impact=event["impact"]
            )
        logger.info("✅ Seeding complete!")

if __name__ == "__main__":
    seeder = DataSeeder()
    seeder.seed_initial_crypto_events()