# tests/trading/executor/test_async_executor.py
import pytest
from unittest.mock import AsyncMock, patch
from trading.executor.async_executor import AsyncExecutor


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
    redis.set_position = AsyncMock()
    redis.set_risk = AsyncMock()
    redis.publish = AsyncMock()
    redis.consume = AsyncMock(return_value=[])
    redis.create_consumer_group = AsyncMock()
    return redis


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.market_order = AsyncMock(return_value={
        "order_id": 12345,
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "filled_qty": 0.01,
        "filled_price": 43000.0,
        "status": "FILLED",
    })
    return client


@pytest.mark.asyncio
async def test_executor_passes_risk_gates(mock_redis, mock_client):
    """Test order passes risk gates."""
    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "v35_long",
    }

    result = await executor._process_order(order)

    assert result is not None
    mock_client.market_order.assert_called_once()


@pytest.mark.asyncio
async def test_executor_blocks_on_kill_switch(mock_redis, mock_client):
    """Test order blocked when kill switch is on."""
    mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "true", "blocked": "false"})

    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "v35_long",
    }

    result = await executor._process_order(order)

    assert result is None
    mock_client.market_order.assert_not_called()


@pytest.mark.asyncio
async def test_executor_updates_position_after_fill(mock_redis, mock_client):
    """Test position is updated after successful fill."""
    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "v35_long",
    }

    await executor._process_order(order)

    mock_redis.set_position.assert_called_once()
    call_args = mock_redis.set_position.call_args
    assert call_args[0][0] == "BTC"
    assert call_args[0][1] == "spot"
