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
    """Test WebSocket URL construction.

    Uses miniTicker stream for efficiency (1 update/sec vs thousands for @trade).
    """
    task = BinanceFeedTask(symbol="BTC", redis=AsyncMock())

    url = task._build_ws_url()
    assert "btcusdt@miniTicker" in url
    assert "wss://fstream.binance.com" in url


def test_binance_feed_parses_ticker_message():
    """Test parsing Binance miniTicker message."""
    task = BinanceFeedTask(symbol="BTC", redis=AsyncMock())

    raw_msg = {
        "e": "24hrMiniTicker",
        "s": "BTCUSDT",
        "c": "43250.50",  # close price
        "o": "43000.00",  # open price
        "h": "43500.00",  # high price
        "l": "42800.00",  # low price
        "v": "1000.0",    # volume
    }

    parsed = task._parse_ticker_message(raw_msg)
    assert parsed["price"] == "43250.50"
    assert parsed["market"] == "futures"


def test_binance_futures_feed_parses_message():
    """Test parsing Binance futures miniTicker message."""
    task = BinanceFeedTask(symbol="BTC", redis=AsyncMock(), market="futures")

    raw_msg = {
        "e": "24hrMiniTicker",
        "s": "BTCUSDT",
        "c": "43255.00",  # close price
    }

    parsed = task._parse_ticker_message(raw_msg)
    assert parsed["price"] == "43255.00"
    assert parsed["market"] == "futures"
