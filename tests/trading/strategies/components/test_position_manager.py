"""Tests for Redis-backed PositionManager snapshots."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from trading.strategies.components.context_builder import PositionManager
from trading.strategies.components.models import Position


@pytest.mark.asyncio
async def test_refresh_loads_positions_from_redis():
    redis_client = MagicMock()
    redis_client.hgetall = AsyncMock(side_effect=[
        {
            "quantity": "0.25",
            "entry_price": "100000",
            "strategy": "llm_direction_btc",
            "entry_time": "1700000000000",
            "side": "buy",
            "leverage": "1",
        },
        {},
        {},
        {},
    ])

    manager = PositionManager(redis_client=redis_client, cache_ttl_seconds=0.0)
    await manager.refresh(symbols=["BTC", "ETH"], force=True)

    btc_positions = manager.get_positions_for_symbol("BTC")
    assert "llm_direction_btc" in btc_positions
    assert btc_positions["llm_direction_btc"].entry_price == 100000.0
    assert btc_positions["llm_direction_btc"].entry_time == 1700000000000

    portfolio = manager.get_portfolio_positions()
    assert len(portfolio) == 1
    only = next(iter(portfolio.values()))
    assert only.symbol == "BTC"


def test_update_cached_position_adds_and_removes():
    redis_client = MagicMock()
    manager = PositionManager(redis_client=redis_client)
    position = Position(
        symbol="BTC",
        entry_price=100000.0,
        quantity=0.1,
        strategy="llm_direction_btc",
        market="spot",  # type: ignore[arg-type]
        timestamp=1700000000000,
    )

    manager.update_cached_position("BTC", "llm_direction_btc", position)
    assert "llm_direction_btc" in manager.get_positions_for_symbol("BTC")
    assert len(manager.get_portfolio_positions()) == 1

    manager.update_cached_position("BTC", "llm_direction_btc", None)
    assert "llm_direction_btc" not in manager.get_positions_for_symbol("BTC")
    assert len(manager.get_portfolio_positions()) == 0
