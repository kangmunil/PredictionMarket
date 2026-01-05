import os
import json
import logging
from typing import List, Dict
from datetime import datetime, timedelta
from dotenv import load_dotenv
from .memory_manager import MemoryManager

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DataSeeder")

class DataSeeder:
    """
    Seeds the AI Memory with historical crypto/market events.
    Crucial for the RAG system to have a baseline for comparison.
    """
    
    def __init__(self):
        load_dotenv()
        self.memory = MemoryManager()

    def seed_initial_crypto_events(self):
        """Seed hardcoded key events for Bitcoin/Crypto"""
        events = [
            {
                "entity": "Bitcoin",
                "content": "SEC approves 11 Spot Bitcoin ETFs, marking a historic milestone.",
                "category": "Crypto",
                "impact": {"price_change_24h": -0.05, "outcome": "Sell the news", "note": "Price dropped initially due to GBTC outflows"}
            },
            {
                "entity": "Bitcoin",
                "content": "Tesla purchases $1.5B worth of Bitcoin.",
                "category": "Crypto",
                "impact": {"price_change_24h": 0.15, "outcome": "Pump", "note": "Massive rally followed"}
            },
            {
                "entity": "Bitcoin",
                "content": "China bans cryptocurrency mining and transactions.",
                "category": "Crypto",
                "impact": {"price_change_24h": -0.10, "outcome": "Dump", "note": "Short-term panic, long-term recovery"}
            },
            {
                "entity": "Binance",
                "content": "Binance CEO CZ steps down and pleads guilty to money laundering violations.",
                "category": "Crypto",
                "impact": {"price_change_24h": -0.04, "outcome": "Uncertainty", "note": "BNB dropped but market stabilized quickly"}
            },
            {
                "entity": "FTX",
                "content": "FTX files for Chapter 11 bankruptcy protection.",
                "category": "Crypto",
                "impact": {"price_change_24h": -0.20, "outcome": "Crash", "note": "Market-wide contagion"}
            }
        ]

        logger.info(f"🌱 Seeding {len(events)} initial events...")
        
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