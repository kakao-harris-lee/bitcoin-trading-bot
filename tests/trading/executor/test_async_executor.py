# tests/trading/executor/test_async_executor.py
import pytest
from unittest.mock import AsyncMock, patch
from trading.executor.async_executor import AsyncExecutor


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
    redis.get_position = AsyncMock(return_value=None)  # No existing position by default
    redis.set_position = AsyncMock()
    redis.set_risk = AsyncMock()
    redis.publish = AsyncMock()
    redis.consume = AsyncMock(return_value=[])
    redis.create_consumer_group = AsyncMock()
    redis.hset = AsyncMock()
    return redis


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.market_order = AsyncMock(return_value={
        "order_id": 12345,
        "symbol": "BTC",
        "side": "buy",
        "market": "futures",
        "filled_qty": 0.01,
        "filled_price": 43000.0,
        "status": "FILLED",
    })
    return client


@pytest.mark.asyncio
async def test_executor_passes_risk_gates(mock_redis, mock_client):
    """Test order passes risk gates."""
    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})
    # Set up balance cache (required for balance check)
    executor._balance_cache = {"futures": 10000.0, "last_update": 0}

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "futures",
        "quantity": "0.01",
        "strategy": "short_v1",
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
        "market": "futures",
        "quantity": "0.01",
        "strategy": "short_v1",
    }

    result = await executor._process_order(order)

    assert result is None
    mock_client.market_order.assert_not_called()


@pytest.mark.asyncio
async def test_executor_updates_position_after_fill(mock_redis, mock_client):
    """Test position is updated after successful fill."""
    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})
    # Set up balance cache (required for balance check)
    executor._balance_cache = {"futures": 10000.0, "last_update": 0}

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "futures",
        "quantity": "0.01",
        "strategy": "short_v1",
    }

    await executor._process_order(order)

    mock_redis.set_position.assert_called_once()
    call_args = mock_redis.set_position.call_args
    assert call_args[0][0] == "BTC"
    assert call_args[0][1] == "futures"


@pytest.mark.asyncio
async def test_executor_routes_spot_orders_correctly(mock_redis, mock_client):
    """Test spot orders are routed to _execute_spot_order."""
    # Set up spot order response
    mock_client.market_order = AsyncMock(return_value={
        "order_id": 54321,
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "filled_qty": 0.02,
        "filled_price": 43000.0,
        "status": "FILLED",
    })

    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})
    # Set up balance cache with enough balance for estimated order value
    # 0.02 BTC @ ~90k = ~1800 + buffer = ~2000 USDT needed
    executor._balance_cache = {"spot": 2000.0, "last_update": 0}

    order = {
        "id": "spot-test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.02",
        "strategy": "spot_simple",
    }

    result = await executor._process_order(order)

    # Verify order was executed
    assert result is not None
    assert result["market"] == "spot"
    mock_client.market_order.assert_called_once()

    # Verify market_order was called with spot market and no position_side
    call_args = mock_client.market_order.call_args
    assert call_args[1]["market"] == "spot"
    assert call_args[1]["position_side"] is None

    # Verify position was updated in Redis with spot key
    mock_redis.set_position.assert_called_once()
    pos_call_args = mock_redis.set_position.call_args
    assert pos_call_args[0][0] == "BTC"
    assert pos_call_args[0][1] == "spot"

    # Verify spot position has no leverage/liquidation
    position_data = pos_call_args[0][2]
    assert position_data["leverage"] == "1"
    assert position_data["liquidation_price"] == "0"


@pytest.mark.asyncio
async def test_executor_spot_position_has_no_liquidation(mock_redis, mock_client):
    """Test spot positions don't have liquidation price."""
    mock_client.market_order = AsyncMock(return_value={
        "order_id": 54321,
        "symbol": "ETH",
        "side": "buy",
        "market": "spot",
        "filled_qty": 0.5,
        "filled_price": 3000.0,
        "status": "FILLED",
    })

    executor = AsyncExecutor(redis=mock_redis, client=mock_client, config={})
    executor._balance_cache = {"spot": 2000.0, "last_update": 0}

    order = {
        "id": "spot-eth-123",
        "symbol": "ETH",
        "side": "buy",
        "market": "spot",
        "quantity": "0.5",
        "strategy": "spot_simple",
    }

    await executor._process_order(order)

    # Verify position data
    pos_call_args = mock_redis.set_position.call_args
    position_data = pos_call_args[0][2]

    # Spot: no leverage, no liquidation
    assert position_data["leverage"] == "1"
    assert position_data["liquidation_price"] == "0"
    assert position_data["quantity"] == "0.5"
    assert position_data["entry_price"] == "3000.0"


@pytest.mark.asyncio
async def test_executor_futures_order_still_works(mock_redis, mock_client):
    """Test futures orders still route correctly after spot addition."""
    # Mock leverage manager
    mock_leverage_manager = AsyncMock()
    mock_leverage_manager.get_allowed_leverage = AsyncMock(return_value=5)  # Allow up to 5x

    mock_client.set_leverage = AsyncMock()
    mock_client.market_order = AsyncMock(return_value={
        "order_id": 99999,
        "symbol": "BTC",
        "side": "buy",
        "market": "futures",
        "filled_qty": 0.01,
        "filled_price": 43000.0,
        "status": "FILLED",
    })

    executor = AsyncExecutor(
        redis=mock_redis,
        client=mock_client,
        config={},
        leverage_manager=mock_leverage_manager,
    )
    executor._balance_cache = {"futures": 10000.0, "last_update": 0}

    order = {
        "id": "futures-test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "futures",
        "quantity": "0.01",
        "strategy": "short_v1",
        "leverage": 3,
    }

    result = await executor._process_order(order)

    # Verify order was executed
    assert result is not None

    # Verify leverage was set (futures-specific)
    mock_client.set_leverage.assert_called_once_with("BTC", 3)

    # Verify position has leverage and liquidation price
    pos_call_args = mock_redis.set_position.call_args
    position_data = pos_call_args[0][2]
    assert position_data["leverage"] == "3"
    # Liquidation price should be calculated (non-zero for leveraged position)
    assert float(position_data["liquidation_price"]) > 0
