import pytest
from decimal import Decimal

from src.core.allocation_manager import AllocationManager


@pytest.mark.anyio
async def test_allocator_limits_by_total_balance(monkeypatch):
    monkeypatch.setenv("FUNDER_ADDRESS", "0x123")

    alloc = AllocationManager(refresh_ttl_seconds=0, enable_onchain=False)

    monkeypatch.setattr(
        AllocationManager,
        "_fetch_usdc_balance",
        lambda self: Decimal("1000"),
    )
    monkeypatch.setattr(
        AllocationManager,
        "_fetch_positions",
        lambda self: [{"token_id": "token-x", "exposure_usd": 100}],
    )

    amount = await alloc.allocate_for_market(
        "token-y",
        desired_usd=500,
        allocation_pct=0.2,  # total budget = 200
        per_market_pct=0.15,  # per-market cap = 150
    )
    # used = 100, so remaining budget is 100; per-market cap 150 -> expect 100
    assert amount == pytest.approx(100.0, rel=1e-3)


@pytest.mark.anyio
async def test_allocator_limits_by_market_exposure(monkeypatch):
    monkeypatch.setenv("FUNDER_ADDRESS", "0x123")

    alloc = AllocationManager(refresh_ttl_seconds=0, enable_onchain=False)

    monkeypatch.setattr(
        AllocationManager,
        "_fetch_usdc_balance",
        lambda self: Decimal("500"),
    )
    monkeypatch.setattr(
        AllocationManager,
        "_fetch_positions",
        lambda self: [{"token_id": "token-a", "exposure_usd": 60}],
    )

    amount = await alloc.allocate_for_market(
        "token-a",
        desired_usd=200,
        allocation_pct=0.5,  # total budget = 250
        per_market_pct=0.2,  # per-market cap = 100
    )
    # token already has 60 exposure, so remaining cap 40
    assert amount == pytest.approx(40.0, rel=1e-3)
