import asyncio
import logging
import sys
import argparse
from src.core.clob_client import PolyClient
from src.strategies.arbitrage import ArbitrageStrategy
from src.strategies.stat_arb import StatArbStrategy
from src.strategies.ai_model import AIModelStrategy
from src.core.wallet_watcher import WalletWatcher
from src.strategies.elite_mimic import EliteMimicAgent

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("PolyBot")

async def main():
    parser = argparse.ArgumentParser(description="Polymarket Trading Bot")
    parser.add_argument("--strategy", type=str, required=True, 
                        choices=["arbitrage", "stat_arb", "ai", "copy", "elitemimic"],
                        help="Strategy to run: arbitrage, stat_arb, ai, copy, or elitemimic")
    
    args = parser.parse_args()
    
    logger.info("Initializing PolyClient...")
    client = PolyClient()
    
    if args.strategy == "arbitrage":
        strategy = ArbitrageStrategy(client)
    elif args.strategy == "stat_arb":
        strategy = StatArbStrategy(client)
    elif args.strategy == "ai":
        strategy = AIModelStrategy(client)
    elif args.strategy == "copy":
        strategy = WalletWatcher(client)
    elif args.strategy == "elitemimic":
        strategy = EliteMimicAgent(client)
    else:
        logger.error("Unknown strategy")
        return

    await strategy.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
