import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.pnl_tracker import PnLTracker

async def test_thesis_storage():
    print("Testing Thesis Storage...")
    
    # Mock Repository
    mock_repo = MagicMock()
    mock_repo.save_trade = AsyncMock()
    
    tracker = PnLTracker(trade_repository=mock_repo)
    
    # Define a sample thesis
    thesis = {
        "entry_reason": "Statistical Anomaly (Z=2.5)",
        "entry_conditions": {"z_score": 2.5, "corr": 0.95},
        "exit_hypotheses": [{"type": "REVERSION"}],
        "expected_window": "2 days"
    }
    
    # Record Entry
    trade_id = tracker.record_entry(
        strategy="test_strategy",
        token_id="token_abc",
        side="BUY",
        price=0.5,
        size=100.0,
        metadata={"thesis": thesis}
    )
    
    # Verify in-memory storage
    active_trade = tracker.active_trades[trade_id]
    assert active_trade.metadata["thesis"] == thesis
    print(f"✅ In-memory thesis storage verified for {trade_id}")
    
    # Record Exit
    tracker.record_exit(trade_id, 0.6, reason="Target Reached")
    
    # Verify Repository Call
    # Note: record_exit creates a background task for save_trade
    # We might need a small sleep or manual check of the history list
    
    history_record = tracker.history[0]
    assert history_record["metadata"]["thesis"] == thesis
    print("✅ History record thesis persistence verified")
    
    print("\nAll Thesis Storage Tests PASSED! 🚀")

if __name__ == "__main__":
    asyncio.run(test_thesis_storage())
