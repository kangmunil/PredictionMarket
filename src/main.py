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
from src.core.structured_logger import setup_logging

async def main():
    parser = argparse.ArgumentParser(description="Polymarket Trading Bot")
    parser.add_argument("--strategy", type=str, required=True, 
                        choices=["arbitrage", "stat_arb", "ai", "copy", "elitemimic"],
                        help="Strategy to run: arbitrage, stat_arb, ai, copy, or elitemimic")
    parser.add_argument("--json-logs", action="store_true", help="Enable JSON logging output")
    
    args = parser.parse_args()
    
    # Configure Logging
    setup_logging(
        level=logging.INFO,
        json_output=args.json_logs,
        log_file="logs/polybot.log"
    )
    logger = logging.getLogger("PolyBot")
    
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
