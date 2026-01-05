import asyncio
import logging
import time
from unittest.mock import MagicMock, AsyncMock
from src.core.clob_client import PolyClient
from src.core.wallet_watcher import WalletWatcher
from src.strategies.ai_model import AIModelStrategy
from src.strategies.stat_arb import StatArbStrategy
from src.strategies.elite_mimic import EliteMimicAgent

# Setup Logging for Simulation
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Simulation")

class SimulationRunner:
    def __init__(self):
        logger.info("🎬 Initializing Scenario: 'Operation Red Mirage'...")
        
        # 1. Mock Client (Controls Market Prices)
        self.mock_client = MagicMock(spec=PolyClient)
        self.mock_client.place_market_order = AsyncMock(return_value="tx_hash_123")
        
        # Dynamic Price Storage
        self.market_prices = {
            "token_trump_yes": 0.50,
            "token_gop_yes": 0.50
        }
        
        # Connect get_best_ask_price to our dynamic storage
        self.mock_client.get_best_ask_price.side_effect = lambda token: self.market_prices.get(token, 0.0)
        
        # Mock History for Stat Arb (Initially Correlated)
        self.mock_client.get_price_history.return_value = [0.5] * 24

        # 2. Setup Agent Components with Mock Client
        self.agent = EliteMimicAgent(self.mock_client)
        
        # 3. Patch AI to return deterministic sentiment for simulation
        # We override the fetch method to control the 'News'
        self.agent.ai_brain.fetch_market_sentiment = AsyncMock(return_value=0.0) 

        # 4. Patch StatArb pairs to match our scenario tokens
        self.agent.stat_arb_engine.pairs = [
            ("token_trump_yes", "token_gop_yes", "Trump/GOP Pair")
        ]
        # Override fetch_history to return values that create Z-Score
        self.agent.stat_arb_engine.fetch_history = MagicMock()

    async def run_scenario(self):
        logger.info("\n--- 🎬 SCENE 1: The Calm (Baseline) ---")
        logger.info("Market is stable. Trump: $0.50, GOP: $0.50")
        self.agent.stat_arb_engine.fetch_history.side_effect = lambda t: [0.50] * 24 # Perfect correlation
        await self.agent.stat_arb_engine.analyze_pair("token_trump_yes", "token_gop_yes", "Trump/GOP Pair")
        logger.info(">> StatArb check complete (Expect: No Action)")

        logger.info("\n--- 🎬 SCENE 2: The News Break (AI Activation) ---")
        logger.info("📰 Breaking News: 'Exit polls show Trump leading in PA!'")
        # Inject positive sentiment
        self.agent.ai_brain.fetch_market_sentiment = AsyncMock(return_value=0.8) 
        
        # Trigger AI analysis manually to show effect
        prob = await self.agent.ai_brain.predict_probability("Trump Wins", "YES")
        logger.info(f">> AI Probability updated to: {prob:.2%} (Expect: > 50%)")

        logger.info("\n--- 🎬 SCENE 3: The Elite Move (Copy Trade) ---")
        elite_trader = "0xe00...baguette"
        logger.info(f"👀 Detected transaction from {elite_trader} buying Trump YES")
        
        # Force WalletWatcher to process a trade
        # Token Price is still 0.50, AI prob is high (from Scene 2) -> EV should be positive
        await self.agent.wallet_watcher.process_detected_trade(
            trader_id=elite_trader,
            token_id="token_trump_yes",
            side="BUY",
            detected_price=0.50,
            tx_hash="0xSimulatedTx"
        )

        logger.info("\n--- 🎬 SCENE 4: The Divergence (Stat Arb Hedge) ---")
        logger.info("📈 Market Reaction: Trump spikes to $0.70, GOP lags at $0.52")
        self.market_prices["token_trump_yes"] = 0.70
        self.market_prices["token_gop_yes"] = 0.52
        
        # Create divergent history for Z-Score calculation
        # Trump history spikes up, GOP stays flat
        history_trump = [0.50] * 23 + [0.70]
        history_gop = [0.50] * 23 + [0.52]
        
        def mock_history_divergence(token_id):
            if token_id == "token_trump_yes": return history_trump
            return history_gop
            
        self.agent.stat_arb_engine.fetch_history.side_effect = mock_history_divergence
        
        # Run Stat Arb Logic
        await self.agent.stat_arb_engine.analyze_pair("token_trump_yes", "token_gop_yes", "Trump/GOP Pair")
        logger.info(">> StatArb check complete (Expect: HEDGE SIGNAL - Short Trump / Long GOP)")

        logger.info("\n--- 🎬 SCENE 5: The Trap (Slippage Protection) ---")
        logger.info("Elite trader buys MORE, but price has pumped to $0.70")
        logger.info("He got in at $0.70, but our latency checks price at $0.75")
        self.market_prices["token_trump_yes"] = 0.75 # Price moved against us
        
        # Try to copy again
        await self.agent.wallet_watcher.process_detected_trade(
            trader_id=elite_trader,
            token_id="token_trump_yes",
            side="BUY",
            detected_price=0.70, # He bought at 0.70
            tx_hash="0xSimulatedTx2"
        )
        logger.info(">> Protection check complete (Expect: SLIPPAGE WARNING / SKIP)")
        
        logger.info("\n✅ SCENARIO COMPLETE")
        # Print Summary Logs
        self.agent.report_status()

if __name__ == "__main__":
    runner = SimulationRunner()
    asyncio.run(runner.run_scenario())
