"""Tests for Redis-backed StateManager."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from trading.strategies.components.state_manager import StateManager


@pytest.mark.asyncio
async def test_load_uses_redis_and_caches_value():
    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value='{"count": 2}')

    manager = StateManager(redis=redis_client, strategy_name="short_v1_exit")
    value = await manager.load(symbol="BTC", variable="entry_count", default=0)

    assert value == {"count": 2}
    assert manager.get_cached("BTC", "entry_count") == {"count": 2}

    cached_value = await manager.get("BTC", "entry_count")
    assert cached_value == {"count": 2}
    redis_client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_missing_returns_default_and_caches():
    redis_client = MagicMock()
    redis_client.get = AsyncMock(return_value=None)

    manager = StateManager(redis=redis_client, strategy_name="short_v1_exit")
    value = await manager.load(symbol="ETH", variable="high_water_mark", default=0.0)

    assert value == 0.0
    assert manager.get_cached("ETH", "high_water_mark") == 0.0


@pytest.mark.asyncio
async def test_set_updates_cache_only_on_success():
    redis_client = MagicMock()
    redis_client.set = AsyncMock()

    manager = StateManager(redis=redis_client, strategy_name="short_v1_exit")
    manager.set_cached("BTC", "entry_count", 1)

    await manager.set("BTC", "entry_count", 2)

    assert manager.get_cached("BTC", "entry_count") == 2
    redis_client.set.assert_awaited_once()

    redis_client.set = AsyncMock(side_effect=RuntimeError("redis down"))
    await manager.set("BTC", "entry_count", 3)

    assert manager.get_cached("BTC", "entry_count") == 2


@pytest.mark.asyncio
async def test_bulk_load_delete_and_list_cached_symbols():
    redis_client = MagicMock()
    redis_client.get = AsyncMock(side_effect=['"abc"', None])
    redis_client.delete = AsyncMock()

    manager = StateManager(redis=redis_client, strategy_name="mlp_direction")
    values = await manager.load_all_for_symbol(
        symbol="BTC",
        variables=["position_id", "high_water_mark"],
        defaults={"high_water_mark": 10.0},
    )

    assert values == {"position_id": "abc", "high_water_mark": 10.0}
    assert manager.list_cached_symbols("position_id") == ["BTC"]

    await manager.delete_all_for_symbol("BTC", ["position_id", "high_water_mark"])

    assert manager.get_cached("BTC", "position_id") is None
    assert manager.get_cached("BTC", "high_water_mark") is None
    assert redis_client.delete.await_count == 2
