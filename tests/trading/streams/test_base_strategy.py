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
    redis.has_position = AsyncMock(return_value=False)
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
    mock_redis.has_position = AsyncMock(return_value=True)

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
