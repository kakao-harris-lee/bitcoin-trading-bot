# tests/trading/streams/test_base_strategy.py
import pytest
from unittest.mock import AsyncMock
from collections import deque
from trading.streams.base_strategy import BaseStrategyTask


class TestStrategy(BaseStrategyTask):
    """Concrete implementation for testing."""

    async def evaluate(self, symbol: str) -> dict | None:
        # Simple: buy if price > 40000
        if len(self.price_buffer.get(symbol, [])) == 0:
            return None
        last_price = float(self.price_buffer[symbol][-1]["price"])
        if last_price > 40000:
            return {
                "symbol": symbol,
                "side": "buy",
                "market": "spot",
                "quantity": "0.01",
                "reason": "price above 40000",
            }
        return None


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value="1234-0")
    redis.get_position = AsyncMock(return_value=None)  # No position
    redis.is_blocked = AsyncMock(return_value=False)
    return redis


@pytest.mark.asyncio
async def test_strategy_buffers_prices(mock_redis):
    """Test price buffering."""
    strategy = TestStrategy(
        name="test",
        symbols=["BTC"],
        redis=mock_redis,
        market="spot",
    )

    # Process price message
    msg = {"symbol": "BTC", "price": "43000", "market": "spot", "_id": "1-0"}
    await strategy._handle_message(msg)

    assert "BTC" in strategy.price_buffer
    assert len(strategy.price_buffer["BTC"]) == 1
    assert strategy.price_buffer["BTC"][-1]["price"] == "43000"


@pytest.mark.asyncio
async def test_strategy_publishes_order(mock_redis):
    """Test order publishing."""
    strategy = TestStrategy(
        name="test",
        symbols=["BTC"],
        redis=mock_redis,
        market="spot",
    )

    # Process price that triggers signal
    msg = {"symbol": "BTC", "price": "43000", "market": "spot", "_id": "1-0"}
    await strategy._handle_message(msg)

    # Verify order published
    mock_redis.publish.assert_called_once()
    call_args = mock_redis.publish.call_args
    assert call_args[0][0] == "orders"
    assert call_args[0][1]["symbol"] == "BTC"
    assert call_args[0][1]["side"] == "buy"


@pytest.mark.asyncio
async def test_strategy_skips_when_position_exists(mock_redis):
    """Test skipping when position already exists."""
    # Return a position dict owned by a different strategy
    mock_redis.get_position = AsyncMock(return_value={
        "quantity": "0.01",
        "entry_price": "40000",
        "strategy": "other_strategy",  # Different strategy owns it
        "side": "buy",
    })

    strategy = TestStrategy(
        name="test",
        symbols=["BTC"],
        redis=mock_redis,
        market="spot",
    )

    msg = {"symbol": "BTC", "price": "43000", "market": "spot", "_id": "1-0"}
    await strategy._handle_message(msg)

    # Should not publish order (position exists)
    mock_redis.publish.assert_not_called()


@pytest.mark.asyncio
async def test_strategy_skips_when_blocked(mock_redis):
    """Test skipping when trading is blocked."""
    mock_redis.is_blocked = AsyncMock(return_value=True)

    strategy = TestStrategy(
        name="test",
        symbols=["BTC"],
        redis=mock_redis,
        market="spot",
    )

    msg = {"symbol": "BTC", "price": "43000", "market": "spot", "_id": "1-0"}
    await strategy._handle_message(msg)

    # Should not publish order
    mock_redis.publish.assert_not_called()


@pytest.mark.asyncio
async def test_strategy_publishes_exit_signal_with_smart_exit(mock_redis):
    """Test exit signal publishing for smart execution."""
    mock_redis.get_position = AsyncMock(return_value={
        "quantity": "0.01",
        "entry_price": "40000",
        "strategy": "test",
        "side": "buy",
    })
    mock_redis.clear_position = AsyncMock()

    class TestExitStrategy(BaseStrategyTask):
        async def evaluate(self, symbol: str) -> dict | None:
            return None

        async def evaluate_exit(self, symbol: str, position: dict) -> dict | None:
            return {
                "symbol": symbol,
                "side": "sell",
                "market": "spot",
                "quantity": position["quantity"],
                "trigger_price": "42000",
                "reason": "test exit",
            }

    strategy = TestExitStrategy(
        name="test",
        symbols=["BTC"],
        redis=mock_redis,
        market="spot",
        use_smart_exit=True,
    )

    msg = {"symbol": "BTC", "price": "42000", "market": "spot", "_id": "1-0"}
    await strategy._handle_message(msg)

    # Should publish to exit_signals, not orders
    calls = mock_redis.publish.call_args_list
    assert len(calls) == 1
    assert calls[0][0][0] == "exit_signals"
    exit_signal = calls[0][0][1]
    assert exit_signal["symbol"] == "BTC"
    assert exit_signal["side"] == "sell"
    assert exit_signal["strategy"] == "test"
    assert exit_signal["trigger_price"] == "42000"

    # Position should NOT be cleared when using smart exit
    mock_redis.clear_position.assert_not_called()


@pytest.mark.asyncio
async def test_strategy_publishes_to_orders_without_smart_exit(mock_redis):
    """Test that without smart exit, exit signals go to orders stream."""
    mock_redis.get_position = AsyncMock(return_value={
        "quantity": "0.01",
        "entry_price": "40000",
        "strategy": "test",
        "side": "buy",
    })
    mock_redis.clear_position = AsyncMock()

    class TestExitStrategy(BaseStrategyTask):
        async def evaluate(self, symbol: str) -> dict | None:
            return None

        async def evaluate_exit(self, symbol: str, position: dict) -> dict | None:
            return {
                "symbol": symbol,
                "side": "sell",
                "market": "spot",
                "quantity": position["quantity"],
                "reason": "test exit",
            }

    strategy = TestExitStrategy(
        name="test",
        symbols=["BTC"],
        redis=mock_redis,
        market="spot",
        use_smart_exit=False,  # Default behavior
    )

    msg = {"symbol": "BTC", "price": "42000", "market": "spot", "_id": "1-0"}
    await strategy._handle_message(msg)

    # Should publish to orders stream (legacy behavior)
    calls = mock_redis.publish.call_args_list
    assert len(calls) == 1
    assert calls[0][0][0] == "orders"

    # Position should be cleared
    mock_redis.clear_position.assert_called_once_with("BTC", "spot")


@pytest.mark.asyncio
async def test_exit_signal_adds_trigger_price_from_buffer(mock_redis):
    """Test that trigger_price is added from buffer if not in signal."""
    mock_redis.get_position = AsyncMock(return_value={
        "quantity": "0.01",
        "entry_price": "40000",
        "strategy": "test",
        "side": "buy",
    })
    mock_redis.clear_position = AsyncMock()

    class TestExitStrategy(BaseStrategyTask):
        async def evaluate(self, symbol: str) -> dict | None:
            return None

        async def evaluate_exit(self, symbol: str, position: dict) -> dict | None:
            # Exit signal WITHOUT trigger_price
            return {
                "symbol": symbol,
                "side": "sell",
                "market": "spot",
                "quantity": position["quantity"],
                "reason": "test exit",
            }

    strategy = TestExitStrategy(
        name="test",
        symbols=["BTC"],
        redis=mock_redis,
        market="spot",
        use_smart_exit=True,
    )

    msg = {"symbol": "BTC", "price": "42500", "market": "spot", "_id": "1-0"}
    await strategy._handle_message(msg)

    # Should have trigger_price from buffer
    calls = mock_redis.publish.call_args_list
    assert len(calls) == 1
    exit_signal = calls[0][0][1]
    assert exit_signal["trigger_price"] == "42500"
