import pytest
from datetime import datetime, timedelta

from src.core.price_history_api import PolymarketHistoryAPI


class _DummyMCP:
    def __init__(self, trades):
        self.trades = trades

    async def get_trades(self, market_id=None, limit=50, side=None, event_id=None):
        return {"trades": self.trades}


@pytest.mark.anyio
async def test_history_api_prefers_mcp(monkeypatch):
    trades = [
        {"price": 0.45, "timestamp": datetime.now().isoformat()},
        {"price": 0.55, "timestamp": datetime.now().isoformat()},
    ]
    dummy_client = _DummyMCP(trades)

    async def fake_get_default():
        return dummy_client

    monkeypatch.setattr(
        "src.core.price_history_api.get_default_mcp_client",
        fake_get_default,
    )

    async def no_gamma_fetch(self, *args, **kwargs):
        pytest.fail("Gamma fallback should not be used when MCP succeeds")

    monkeypatch.setattr(
        PolymarketHistoryAPI,
        "_fetch_events_from_gamma",
        no_gamma_fetch,
    )

    api = PolymarketHistoryAPI(use_mcp=True)
    points = await api.get_historical_events("CID", days=1)
    assert len(points) == len(trades)
    await api.close()


@pytest.mark.anyio
async def test_history_api_falls_back_when_mcp_fails(monkeypatch):
    class _FailingMCP:
        async def get_trades(self, **kwargs):
            raise RuntimeError("boom")

    async def fake_get_default():
        return _FailingMCP()

    monkeypatch.setattr(
        "src.core.price_history_api.get_default_mcp_client",
        fake_get_default,
    )

    async def fake_fetch(self, condition_id, start_time, end_time):
        now = datetime.now()
        return [
            {"timestamp": now.timestamp(), "price": 0.4},
            {"timestamp": (now + timedelta(minutes=5)).timestamp(), "price": 0.6},
        ]

    monkeypatch.setattr(
        PolymarketHistoryAPI,
        "_fetch_events_from_gamma",
        fake_fetch,
    )

    api = PolymarketHistoryAPI(use_mcp=True)
    points = await api.get_historical_events("CID", days=1)
    assert len(points) > 2
    await api.close()
