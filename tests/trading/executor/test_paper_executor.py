# tests/trading/executor/test_paper_executor.py
import pytest
from unittest.mock import AsyncMock
from trading.executor.paper_executor import PaperExecutor


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
    redis.set_position = AsyncMock()
    redis.set_risk = AsyncMock()
    redis.publish = AsyncMock()
    redis.consume = AsyncMock(return_value=[])
    redis.create_consumer_group = AsyncMock()
    # Mock getting latest price
    redis.hgetall = AsyncMock(return_value={"BTC": "43000"})
    return redis


@pytest.mark.asyncio
async def test_paper_executor_simulates_fill(mock_redis):
    """Test paper executor simulates order fill."""
    executor = PaperExecutor(
        redis=mock_redis,
        config={"initial_balance": 10000},
    )
    executor.last_prices = {"BTC": 43000.0}

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
    assert result["filled_qty"] == 0.01
    assert result["status"] == "FILLED"


@pytest.mark.asyncio
async def test_paper_executor_applies_slippage(mock_redis):
    """Test slippage is applied to fill price."""
    executor = PaperExecutor(
        redis=mock_redis,
        config={"initial_balance": 10000, "slippage": 0.001},
    )
    executor.last_prices = {"BTC": 43000.0}

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "v35_long",
    }

    result = await executor._process_order(order)

    # Buy should have positive slippage (higher price)
    assert result["filled_price"] > 43000.0


@pytest.mark.asyncio
async def test_paper_executor_tracks_balance(mock_redis):
    """Test balance tracking."""
    executor = PaperExecutor(
        redis=mock_redis,
        config={"initial_balance": 10000},
    )
    executor.last_prices = {"BTC": 43000.0}

    initial_balance = executor.balance

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "v35_long",
    }

    await executor._process_order(order)

    # Balance should decrease by order value + fees
    assert executor.balance < initial_balance


@pytest.mark.asyncio
async def test_is_exit_order_detects_short_exit():
    """Buy order should close a short (sell) position."""
    from unittest.mock import MagicMock
    from trading.executor.paper_executor import PaperExecutor

    # Mock Redis
    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value={
        "side": "sell",  # Short position
        "quantity": "0.01",
        "entry_price": "100000",
    })

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    # Buy order should close short position
    order = {"symbol": "BTC", "market": "futures", "side": "buy"}
    result = await executor._is_exit_order(order)

    assert result is True, "Buy should close short position"


@pytest.mark.asyncio
async def test_is_exit_order_detects_long_exit():
    """Sell order should close a long (buy) position."""
    from unittest.mock import MagicMock
    from trading.executor.paper_executor import PaperExecutor

    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value={
        "side": "buy",  # Long position
        "quantity": "0.01",
        "entry_price": "100000",
    })

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    order = {"symbol": "BTC", "market": "futures", "side": "sell"}
    result = await executor._is_exit_order(order)

    assert result is True, "Sell should close long position"


@pytest.mark.asyncio
async def test_is_exit_order_returns_false_for_new_position():
    """Order should not be exit if no position exists."""
    from unittest.mock import MagicMock
    from trading.executor.paper_executor import PaperExecutor

    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value=None)

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    order = {"symbol": "BTC", "market": "futures", "side": "sell"}
    result = await executor._is_exit_order(order)

    assert result is False, "No position means not an exit"
