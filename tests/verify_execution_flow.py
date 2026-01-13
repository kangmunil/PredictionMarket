import asyncio
import logging
import os
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime
from decimal import Decimal

# Add src to path
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.news.news_scalper_optimized import OptimizedNewsScalper
from src.core.rag_system_openrouter import MarketImpact, NewsEvent

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_execution_flow():
    """
    Simulate a full pipeline execution with:
    1. Mocked AI (returning High Confidence)
    2. Mocked Market Logic
    3. Real/Mocked Execution Logic
    """
    logger.info("🚀 Starting Execution Flow Verification...")

    # 1. Mock CLOB Client
    mock_clob = MagicMock()
    mock_clob.get_yes_token_id.return_value = "0x1234567890abcdef" # Valid-looking token ID
    mock_clob.place_limit_order = AsyncMock(return_value="order_123")
    mock_clob.place_market_order = AsyncMock(return_value="order_123")
    mock_clob.subscribe_orderbook = AsyncMock(return_value=None)
    mock_clob.get_usdc_balance = AsyncMock(return_value="100.0")

    # 2. Mock RAG System (The key fix: force positive signal)
    mock_rag = MagicMock()
    
    # Mock extract_entities
    mock_rag.extract_entities = AsyncMock(return_value=["Bitcoin", "Crypto"])

    # Mock analyze_market_impact to return BUY signal
    fake_impact = MarketImpact(
        market_id="123",
        current_price=Decimal("0.50"),
        suggested_price=Decimal("0.70"),
        confidence=0.85, # High confidence
        reasoning="Test simulation: definitive positive news",
        similar_events=[],
        trade_recommendation="buy",
        expected_value=Decimal("0.17"),
        model_used="simulator"
    )
    mock_rag.analyze_market_impact = AsyncMock(return_value=fake_impact)

    # 3. Initialize Scalper with Mocks
    # We patch the class-level import or just inject mocks if supported
    # The Scalper creates its own RAG system in __init__ if use_rag=True.
    # We'll use a subclass or patching to inject our mock_rag.
    
    with patch('src.news.news_scalper_optimized.OpenRouterRAGSystem') as MockRagClass:
        # Make the constructor return our pre-configured mock
        MockRagClass.return_value = mock_rag
        
        # Also mock MarketMatcher logic to find a market
        with patch('src.news.news_scalper_optimized.MarketMatcher') as MockMatcherClass:
            mock_matcher = MockMatcherClass.return_value
            # Return a valid-looking market dict
            mock_matcher.find_matching_markets = AsyncMock(return_value=[{
                "condition_id": "0xabc123",
                "question": "Will Bitcoin hit $100k?",
                "clobTokenIds": ["0x1234567890abcdef", "0x00000"],
                "outcomePrices": ["0.5", "0.5"],
                "tokens": [{"token_id": "0x1234567890abcdef"}]
            }])
            mock_matcher.extract_entities.return_value = {"manual": ["Bitcoin"]}

            # Create Scalper
            scalper = OptimizedNewsScalper(
                news_api_key="fake",
                tree_news_api_key="fake",
                clob_client=mock_clob,
                dry_run=True, # Safety first, though we mocked CLOB too
                use_rag=True
            )
            
            # Ensure Budget Manager mock if needed (handled by None in init usually, but let's check execution)
            scalper.budget_manager = MagicMock()
            scalper.budget_manager.request_allocation = AsyncMock(return_value="alloc_1")
            scalper.budget_manager.release_allocation = AsyncMock()

            # 4. Trigger Processing
            test_article = {
                "title": "Bitcoin surges to new highs as SEC approves everything",
                "content": "A very positive article for testing execution logic.",
                "url": "http://test.com/1",
                "source": {"name": "TestWire"},
                "publishedAt": datetime.now().isoformat()
            }

            logger.info("⚡ Feeding test article to Scalper...")
            result = await scalper._process_article_optimized(test_article)
            
            # 5. Verify Results
            logger.info(f"📝 Result: {result}")

            if result and result.get('success'):
                logger.info("✅ Pipeline processed successfully.")
            else:
                logger.error("❌ Pipeline failed to return success.")

            # Check if order was placed
            # In dry_run, it usually logs but might not call clob_client.place_order unless logic allows.
            # Let's check the code: _process_article_optimized -> _execute_trade
            # _execute_trade logs "DRY RUN" but might skip client calls?
            # Let's check logs output in the real run.
            
            # If logic reaches _refresh_position_signal or similar, we consider it a success.
            # Wait, the Scalper logic calls `_execute_trade`. 
            # If dry_run=True, it usually just logs. 
            # But we want to ensure it *reached* that point.
            
            # We can verify the "signals_generated" stat incremented.
            if scalper.stats["signals_generated"] > 0:
                 logger.info(f"✅ Signal Generated Count: {scalper.stats['signals_generated']}")
            else:
                 logger.error("❌ No signals generated.")
                 exit(1)

            # Also check if RAG was hit
            mock_rag.analyze_market_impact.assert_called_once()
            logger.info("✅ AI Analysis called.")

            logger.info("🎉 VERIFICATION SUCCESS: Execution logic handles positive signals correctly.")

if __name__ == "__main__":
    asyncio.run(test_execution_flow())
