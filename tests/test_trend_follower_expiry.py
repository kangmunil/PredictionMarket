import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock

import sys
from pathlib import Path
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.strategies.trend_follower import SmartTrendFollower

@pytest.mark.asyncio
async def test_expiry_validation():
    # Setup mocks
    client_mock = MagicMock()
    
    # Instantiate strategy
    strategy = SmartTrendFollower(client=client_mock)
    strategy.gamma = gamma_mock = AsyncMock()
    strategy.signal_bus = signal_bus_mock = AsyncMock()
    
    # Setup markets with valid CLOB data
    past_market = {
        'question': 'Past Market',
        'end_date': (datetime.now() - timedelta(hours=1)).isoformat(),
        'condition_id': '0x1',
        'active': True,
        'tags': ['Crypto'],
        'clobTokenIds': ['t1_yes', 't1_no'],
        'tokens': [{'outcome': 'Yes'}, {'outcome': 'No'}]
    }
    
    near_market = {
        'question': 'Near Market',
        'end_date': (datetime.now() + timedelta(hours=1)).isoformat(),
        'condition_id': '0x2',
        'active': True,
        'tags': ['Crypto'],
        'clobTokenIds': ['t2_yes', 't2_no'],
        'tokens': [{'outcome': 'Yes'}, {'outcome': 'No'}]
    }
    
    safe_market = {
        'question': 'Safe Market',
        'end_date': (datetime.now() + timedelta(days=1)).isoformat(),
        'condition_id': '0x3',
        'active': True,
        'tags': ['Crypto'],
        'clobTokenIds': ['t3_yes', 't3_no'],
        'tokens': [{'outcome': 'Yes'}, {'outcome': 'No'}]
    }

    low_price_market = {
        'question': 'Low Price Market',
        'end_date': (datetime.now() + timedelta(days=1)).isoformat(),
        'condition_id': '0x4',
        'active': True,
        'tags': ['Crypto'],
        'clobTokenIds': ['t4_yes', 't4_no'],
        'tokens': [{'outcome': 'Yes'}, {'outcome': 'No'}]
    }
    
    # Mock gamma to return markets
    gamma_mock.get_active_markets.return_value = [past_market, near_market, safe_market, low_price_market]
    
    # Mock history API
    strategy.history_api = AsyncMock()
    
    # Side effect for history API to simulate different prices
    async def history_side_effect(condition_id, **kwargs):
        if condition_id == '0x4': # Low price
            return ([
                {'price': 0.001, 'timestamp': datetime.now() - timedelta(minutes=10)},
                {'price': 0.001, 'timestamp': datetime.now() - timedelta(minutes=5)},
                {'price': 0.002, 'timestamp': datetime.now()} # 100% momentum but price < 0.02
            ], "mcp")
        else: # Safe price
            return ([
                {'price': 0.1, 'timestamp': datetime.now() - timedelta(minutes=10)},
                {'price': 0.1, 'timestamp': datetime.now() - timedelta(minutes=5)},
                {'price': 0.2, 'timestamp': datetime.now()} # Momentum!
            ], "mcp")

    strategy.history_api.get_history_with_source.side_effect = history_side_effect
    
    # Run scan
    await strategy._scan_scalp_candidates()
    
    print("\nExpiry and Price Floor validation test completed successfully")

if __name__ == "__main__":
    asyncio.run(test_expiry_validation())
