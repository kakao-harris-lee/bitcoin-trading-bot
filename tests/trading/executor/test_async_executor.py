import pytest
from unittest.mock import AsyncMock, MagicMock

from trading.executor.async_executor import AsyncExecutor


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get_risk = AsyncMock(
        return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"}
    )
    redis.get_position = AsyncMock(return_value=None)
    redis.set_position = AsyncMock()
    redis.set_risk = AsyncMock()
    redis.publish = AsyncMock()
    redis.consume = AsyncMock(return_value=[])
    redis.create_consumer_group = AsyncMock()
    redis.hset = AsyncMock()
    redis.clear_position = AsyncMock()
    redis.redis = MagicMock()
    redis.redis.hset = AsyncMock()
    return redis


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.market_order = AsyncMock(
        return_value={
            "order_id": 12345,
            "symbol": "BTC",
            "side": "buy",
            "market": "spot",
            "filled_qty": 0.01,
            "filled_price": 43000.0,
            "status": "FILLED",
        }
    )
    client.stop_loss_limit_order = AsyncMock(
        return_value={
            "orderId": 77777,
            "symbol": "BTC",
            "side": "sell",
            "market": "spot",
            "stop_price": 39130.0,
            "status": "NEW",
        }
    )
    client.cancel_open_orders = AsyncMock(return_value=[])
    return client


@pytest.mark.asyncio
async def test_executor_processes_spot_buy_order(mock_redis, mock_client):
    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})
    executor._balance_cache = {"spot": 10000.0, "last_update": 0}

    order = {
        "id": "spot-test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "llm_direction_btc",
    }

    result = await executor._process_order(order)

    assert result is not None
    assert result["market"] == "spot"
    mock_client.market_order.assert_called_once()
    mock_redis.set_position.assert_called_once()
    position_data = mock_redis.set_position.call_args[0][2]
    assert position_data["leverage"] == "1"
    assert "liquidation_price" not in position_data


@pytest.mark.asyncio
async def test_executor_rejects_non_spot_orders(mock_redis, mock_client):
    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})
    executor._balance_cache = {"spot": 10000.0, "last_update": 0}

    order = {
        "id": "bad-market-1",
        "symbol": "BTC",
        "side": "buy",
        "market": "margin",
        "quantity": "0.01",
        "strategy": "legacy_strategy",
    }

    result = await executor._process_order(order)

    assert result is None
    mock_client.market_order.assert_not_called()
    mock_redis.publish.assert_called_once()
    alert = mock_redis.publish.call_args[0][1]
    assert alert["reason"] == "unsupported_market"


@pytest.mark.asyncio
async def test_executor_blocks_on_kill_switch(mock_redis, mock_client):
    mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "true", "blocked": "false", "daily_pnl": "0"})
    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})
    executor._balance_cache = {"spot": 10000.0, "last_update": 0}

    order = {
        "id": "blocked-1",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "llm_direction_btc",
    }

    result = await executor._process_order(order)

    assert result is None
    mock_client.market_order.assert_not_called()


@pytest.mark.asyncio
async def test_executor_places_stop_loss_after_entry(mock_redis, mock_client):
    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})
    executor._balance_cache = {"spot": 10000.0, "last_update": 0}

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "llm_direction_btc",
        "stop_loss_pct": 0.09,
    }

    result = await executor._process_order(order)

    assert result is not None
    mock_client.stop_loss_limit_order.assert_called_once()
    stop_call = mock_client.stop_loss_limit_order.call_args
    assert stop_call.kwargs["market"] == "spot"
    assert abs(stop_call.kwargs["stop_price"] - 39130.0) < 10
    mock_redis.redis.hset.assert_called_once()


@pytest.mark.asyncio
async def test_executor_cancels_stop_loss_on_exit(mock_redis, mock_client):
    mock_redis.get_position = AsyncMock(
        return_value={
            "quantity": "0.01",
            "entry_price": "43000.0",
            "entry_time": "1000",
            "side": "buy",
            "strategy": "llm_direction_btc",
            "stop_order_id": "77777",
            "stop_price": "39130.0",
        }
    )
    mock_client.market_order = AsyncMock(
        return_value={
            "order_id": 12346,
            "symbol": "BTC",
            "side": "sell",
            "market": "spot",
            "filled_qty": 0.01,
            "filled_price": 45000.0,
            "status": "FILLED",
        }
    )

    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})
    executor._balance_cache = {"spot": 10000.0, "last_update": 0}

    order = {
        "id": "exit-test-123",
        "symbol": "BTC",
        "side": "sell",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "llm_direction_btc",
    }

    result = await executor._process_order(order)

    assert result is not None
    mock_client.cancel_open_orders.assert_called_once_with(symbol="BTC", market="spot")
    mock_redis.clear_position.assert_called_once_with("BTC", "spot")
