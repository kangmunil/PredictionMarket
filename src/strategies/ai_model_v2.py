"""
AI Model Strategy V2: Upgraded with Agentic RAG.
Replaces simple sentiment analysis with contextual reasoning.

This version integrates:
- Vector memory search (RAG)
- Multi-step LangGraph reasoning
- Historical pattern matching
"""

import logging
import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from typing import Dict, Optional
from src.ai.agent_brain import build_agent
from src.core.config import Config

logger = logging.getLogger(__name__)


class AIModelStrategyV2:
    """
    Enhanced AI strategy using Agentic RAG.

    Key Differences from V1:
    - V1: Simple sentiment (NewsAPI + TextBlob) → probability adjustment
    - V2: RAG search → LangGraph reasoning → contextual decision

    Use Cases:
    1. Validate copy-trading signals (should we copy distinct-baguette?)
    2. Independent trade signals based on breaking news
    3. Risk assessment for existing positions
    """

    def __init__(self, client=None):
        self.client = client
        self.config = Config()

        # Initialize Agentic RAG workflow
        try:
            self.agent_graph = build_agent()
            logger.info("✅ Agentic RAG Agent initialized")
        except Exception as e:
            logger.error(f"Failed to initialize RAG agent: {e}")
            logger.warning("Falling back to disabled mode")
            self.agent_graph = None

        # Thresholds
        self.min_confidence = 70  # Require 70%+ confidence to act
        self.min_ev = 0.03        # Minimum 3% expected value

    async def analyze_news_event(
        self,
        entity: str,
        category: str,
        news: str,
        current_price: float
    ) -> Dict:
        """
        Analyze a breaking news event using the full RAG workflow.

        Args:
            entity: Subject (e.g., 'Real Madrid', 'Bitcoin')
            category: 'Sports', 'Crypto', 'Politics'
            news: News headline or summary
            current_price: Current market price (0.0-1.0)

        Returns:
            {
                'action': 'BUY_YES'|'BUY_NO'|'HOLD',
                'confidence': 0-100,
                'target_price': float,
                'reasoning': str,
                'ev': float (expected value)
            }
        """
        if not self.agent_graph:
            logger.warning("Agent not available - returning neutral")
            return {
                'action': 'HOLD',
                'confidence': 0,
                'target_price': current_price,
                'reasoning': 'Agent not initialized',
                'ev': 0.0
            }

        try:
            # Prepare input state
            input_state = {
                "entity": entity,
                "category": category,
                "news_content": news,
                "current_price": current_price,
                "similar_memories": [],
                "analysis_reasoning": "",
                "messages": [],
                "action": "",
                "target_price": 0.0,
                "confidence": 0,
                "risk_assessment": ""
            }

            # Run agent workflow (Historian → Analyst → Risk Manager)
            logger.info(f"🤖 Invoking RAG Agent for: {entity}")
            result = self.agent_graph.invoke(input_state)

            # Calculate EV
            predicted_prob = result['target_price']
            ev = predicted_prob - current_price

            analysis = {
                'action': result['action'],
                'confidence': result['confidence'],
                'target_price': result['target_price'],
                'reasoning': result['analysis_reasoning'],
                'risk_notes': result['risk_assessment'],
                'ev': ev,
                'memories_found': len(result['similar_memories'])
            }

            logger.info(f"✅ Agent Decision: {analysis['action']} (Conf: {analysis['confidence']}%, EV: {ev:.3f})")
            return analysis

        except Exception as e:
            logger.error(f"Agent analysis failed: {e}", exc_info=True)
            return {
                'action': 'HOLD',
                'confidence': 0,
                'target_price': current_price,
                'reasoning': f'Error: {str(e)}',
                'ev': 0.0
            }

    async def validate_trade_signal(
        self,
        entity: str,
        category: str,
        current_price: float,
        external_signal: str = "BUY"
    ) -> bool:
        """
        Validate an external trade signal (e.g., from copy-trading).

        Args:
            entity: What we're trading
            category: Category type
            current_price: Current market price
            external_signal: Signal from external source

        Returns:
            bool: True if signal is validated, False if rejected
        """
        # For now, just check if agent agrees with the direction
        # In production, you'd fetch recent news for this entity

        dummy_news = f"External signal detected: {external_signal} on {entity}"

        analysis = await self.analyze_news_event(
            entity=entity,
            category=category,
            news=dummy_news,
            current_price=current_price
        )

        # Validate
        is_valid = (
            analysis['confidence'] >= self.min_confidence and
            analysis['ev'] >= self.min_ev and
            analysis['action'] != 'HOLD'
        )

        if is_valid:
            logger.info(f"✅ External signal APPROVED by AI")
        else:
            logger.info(f"❌ External signal REJECTED by AI")
            logger.info(f"   Reason: Confidence={analysis['confidence']}%, EV={analysis['ev']:.3f}")

        return is_valid

    async def run(self):
        """Main loop (placeholder for active scanning)"""
        logger.info("🧠 AI Model V2 with Agentic RAG - Standing by")

        # In a full implementation, this would:
        # 1. Monitor news feeds in real-time
        # 2. Detect breaking news about tracked entities
        # 3. Automatically trigger agent analysis
        # 4. Generate trade signals

        while True:
            await asyncio.sleep(60)
            # TODO: Implement active news monitoring


# ============================================
# Standalone Test
# ============================================

async def test_strategy():
    """Test the upgraded AI strategy"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    strategy = AIModelStrategyV2()

    # Test 1: Analyze a news event
    print("\n" + "="*70)
    print("TEST 1: News Event Analysis")
    print("="*70)

    result = await strategy.analyze_news_event(
        entity="Real Madrid",
        category="Sports",
        news="Star player Vinicius Jr. leaves training early with minor ankle discomfort. Team medical staff monitoring situation.",
        current_price=0.62  # Dropped from 0.72
    )

    print(f"\nDecision: {result['action']}")
    print(f"Confidence: {result['confidence']}%")
    print(f"EV: {result['ev']:.3f}")
    print(f"Reasoning: {result['reasoning']}")

    # Test 2: Validate external signal
    print("\n" + "="*70)
    print("TEST 2: Validate Copy-Trading Signal")
    print("="*70)

    is_valid = await strategy.validate_trade_signal(
        entity="Bitcoin",
        category="Crypto",
        current_price=0.45,
        external_signal="BUY"
    )

    print(f"\nSignal Validation: {'APPROVED ✅' if is_valid else 'REJECTED ❌'}")


if __name__ == "__main__":
    asyncio.run(test_strategy())
