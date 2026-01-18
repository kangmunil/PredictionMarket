import pytest
import asyncio
import json
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock

import sys
from pathlib import Path
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.strategies.trend_follower import SmartTrendFollower

@pytest.mark.asyncio
async def test_position_logic_enhancements():
    # Setup mocks
    client_mock = MagicMock()
    # Mocking get_real_market_price
    client_mock.get_real_market_price = AsyncMock()
    client_mock.get_all_positions = AsyncMock(return_value=[])
    client_mock.place_limit_order_with_slippage_protection = AsyncMock(return_value={"orderID": "test_order", "price": 0.5, "filled": 10})
    
    # Clean up any existing state file for test
    state_file = "data/trend_follower_state.json"
    if os.path.exists(state_file):
        os.remove(state_file)
        
    strategy = SmartTrendFollower(client=client_mock)
    
    # Manually inject a position
    token_id = "test_token_123"
    strategy.active_positions[token_id] = {
        'entry_price': 0.10,
        'size': 100.0,
        'market_question': 'Test Market',
        'condition_id': '0xABC',
        'timestamp': datetime.now().isoformat(),
        'side': 'BUY',
        'strategy': 'scalp',
        'high_water_mark': 0.10
    }
    
    # 1. Test Partial Take Profit (PNL = 15% > 10%)
    client_mock.get_real_market_price.return_value = 0.115 # 15% gain
    await strategy._manage_positions()
    
    assert strategy.active_positions[token_id]['partial_exit_hit'] is True
    assert strategy.active_positions[token_id]['size'] == 50.0 # 50% sold
    
    # 2. Test Trailing Stop Adjustment (Price goes up to 0.12, PnL = 20% < 25%)
    # HWM should update from 0.115 to 0.12
    client_mock.get_real_market_price.return_value = 0.12
    await strategy._manage_positions()
    assert token_id in strategy.active_positions
    assert strategy.active_positions[token_id]['high_water_mark'] == 0.12
    
    # 3. Test Trailing Stop Trigger (Price drops 6% from 0.12 -> 0.112)
    # 0.112 / 0.12 = 0.933 (6.7% drop)
    client_mock.get_real_market_price.return_value = 0.112
    await strategy._manage_positions()
    
    # Position should be closed
    assert token_id not in strategy.active_positions
    
    # 4. Test Persistence
    # Create new position, save, reload
    token_2 = "token_persisted"
    strategy.active_positions[token_2] = {
        'entry_price': 0.50,
        'size': 10.0,
        'market_question': 'Persisted Market',
        'timestamp': datetime.now().isoformat(),
        'side': 'BUY',
        'high_water_mark': 0.50
    }
    strategy._save_state()
    
    new_strategy = SmartTrendFollower(client=client_mock)
    assert token_2 in new_strategy.active_positions
    assert new_strategy.active_positions[token_2]['size'] == 10.0
    
    # 5. Test Position Sync
    client_mock.get_all_positions.return_value = [
        {'asset_id': 'sync_token', 'size': '25.0', 'avgPrice': '0.30'}
    ]
    # Mock market lookup for sync
    client_mock.get_market_cached = AsyncMock(return_value={'question': 'Sync Question', 'condition_id': '0xSYNC'})
    
    await strategy._sync_with_account()
    assert 'sync_token' in strategy.active_positions
    assert strategy.active_positions['sync_token']['size'] == 25.0
    assert strategy.active_positions['sync_token']['high_water_mark'] == 0.30

    print("\nAdvanced Position Management Verification successful!")

if __name__ == "__main__":
    asyncio.run(test_position_logic_enhancements())
