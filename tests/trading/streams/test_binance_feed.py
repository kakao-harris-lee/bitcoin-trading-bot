# tests/trading/streams/test_binance_feed.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from trading.streams.binance_feed import BinanceFeedTask


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.publish = AsyncMock(return_value="1234-0")
    return redis


def test_binance_feed_builds_ws_url():
    """Test WebSocket URL construction."""
    task = BinanceFeedTask(symbol="BTC", redis=AsyncMock())

    url = task._build_ws_url()
    assert "btcusdt@trade" in url
    assert "wss://fstream.binance.com" in url


def test_binance_feed_parses_trade_message():
    """Test parsing Binance trade message."""
    task = BinanceFeedTask(symbol="BTC", redis=AsyncMock())

    raw_msg = {
        "e": "trade",
        "s": "BTCUSDT",
        "p": "43250.50",
        "T": 1704912345678,
    }

    parsed = task._parse_trade_message(raw_msg)
    assert parsed["price"] == "43250.50"
    assert parsed["market"] == "futures"


def test_binance_futures_feed_parses_message():
    """Test parsing Binance futures trade message."""
    task = BinanceFeedTask(symbol="BTC", redis=AsyncMock(), market="futures")

    raw_msg = {
        "e": "trade",
        "s": "BTCUSDT",
        "p": "43255.00",
        "T": 1704912345678,
    }

    parsed = task._parse_trade_message(raw_msg)
    assert parsed["price"] == "43255.00"
    assert parsed["market"] == "futures"
