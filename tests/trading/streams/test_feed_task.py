# tests/trading/streams/test_feed_task.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from trading.streams.feed_task import SymbolFeedTask


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value="1234-0")
    return redis


@pytest.mark.asyncio
async def test_feed_task_publishes_price(mock_redis):
    """Test feed task publishes prices to stream."""
    task = SymbolFeedTask(symbol="BTC", redis=mock_redis)

    # Simulate receiving a price update
    await task._publish_price({
        "price": "43250.50",
        "market": "futures",
    })

    mock_redis.publish.assert_called_once()
    call_args = mock_redis.publish.call_args
    assert call_args[0][0] == "market:prices"
    assert call_args[0][1]["symbol"] == "BTC"
    assert call_args[0][1]["price"] == "43250.50"
    assert call_args[0][1]["market"] == "futures"
    assert call_args[0][1]["source"] == "binance"


@pytest.mark.asyncio
async def test_feed_task_backoff_calculation():
    """Test exponential backoff."""
    task = SymbolFeedTask(symbol="BTC", redis=AsyncMock())

    assert task._calculate_backoff(0) == 1
    assert task._calculate_backoff(1) == 2
    assert task._calculate_backoff(2) == 4
    assert task._calculate_backoff(10) == 60  # capped at 60


@pytest.mark.asyncio
async def test_feed_task_stop():
    """Test feed task stop signal."""
    task = SymbolFeedTask(symbol="BTC", redis=AsyncMock())

    assert task._running is False
    task._running = True
    assert task._running is True

    task.stop()
    assert task._running is False


@pytest.mark.asyncio
async def test_feed_task_connect_websocket_not_implemented():
    """Test that _connect_websocket raises NotImplementedError."""
    task = SymbolFeedTask(symbol="BTC", redis=AsyncMock())

    with pytest.raises(NotImplementedError) as exc_info:
        await task._connect_websocket()

    assert "Subclass must implement _connect_websocket" in str(exc_info.value)
