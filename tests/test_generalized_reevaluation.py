import asyncio
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.pnl_tracker import PnLTracker
from src.core.revaluation_engine import RevaluationEngine

async def test_kudlow_reevaluation():
    print("Testing Generalized Re-evaluation (Kudlow Case)...")
    
    # 1. Setup PnL Tracker
    tracker = PnLTracker()
    
    # 2. Mock RAG System for Audit
    mock_rag = MagicMock()
    # Simulate AI Auditor rejecting Kudlow due to structural reasons
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({
        "valid": False,
        "confidence_remaining": 0.2,
        "verdict": "EXIT",
        "reasoning": "Missing Board of Governors experience and traditional monetary policy expertise. Candidate is structuredly ineligible.",
        "structural_violation": True
    })
    mock_rag._call_openrouter_with_fallback = AsyncMock(return_value=mock_response)
    mock_rag.analysis_model = "test-model"
    
    # 3. Create Engine
    engine = RevaluationEngine(pnl_tracker=tracker, rag_system=mock_rag)
    
    # 4. Mock a 'Bullish' Kudlow Trade
    trade_id = tracker.record_entry(
        strategy="news_scalper",
        token_id="FED_CHAIR_KUDLOW",
        side="BUY",
        price=0.5,
        size=100.0,
        metadata={
            "group": "FED_CHAIR",
            "thesis": {
                "entry_reason": "Trump likely to nominate loyalist",
                "entry_conditions": {"sentiment": 0.8},
                "expected_window": "1 month"
            }
        }
    )
    
    # 5. Inject User Anti-Thesis (Challenge)
    user_analysis = (
        "1. Institutionally outside norm (No Board of Governors experience). "
        "2. Lacks formal monetary policy expertise (TV Economist vs PhD/Technocrat). "
        "3. High political friction likely during confirmation."
    )
    tracker.add_thesis_challenge(trade_id, {
        "source": "USER_EXPERT",
        "reasoning": user_analysis,
        "severity": 1.0,
        "timestamp": "2026-01-24T08:00:00"
    })
    
    # 6. Run Re-evaluation
    audit_results = await engine.reevaluate_all()
    
    # 7. Verification
    assert len(audit_results) == 1
    result = audit_results[0]
    assert result["trade_id"] == trade_id
    assert result["verdict"] == "EXIT"
    assert result["structural_violation"] is True
    
    print(f"✅ Audit Verdict: {result['verdict']}")
    print(f"✅ Audit Reasoning: {result['reasoning']}")
    print("\nGeneralized Re-evaluation Test PASSED! 🚀")

if __name__ == "__main__":
    asyncio.run(test_kudlow_reevaluation())
