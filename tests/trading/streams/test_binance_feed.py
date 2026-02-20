# tests/trading/streams/test_binance_feed.py
import pytest
from unittest.mock import AsyncMock, MagicMock
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


def test_binance_feed_builds_book_ticker_ws_url():
    """bookTicker stream should be selectable for fresher quote updates."""
    task = BinanceFeedTask(symbol="BTC", redis=AsyncMock(), stream_type="bookTicker")

    url = task._build_ws_url()
    assert "btcusdt@bookTicker" in url
    assert "wss://fstream.binance.com" in url


def test_binance_feed_parses_ticker_message():
    """Test parsing Binance miniTicker message."""
    task = BinanceFeedTask(symbol="BTC", redis=AsyncMock())

    raw_msg = {
        "e": "24hrMiniTicker",
        "s": "BTCUSDT",
        "c": "43250.50",  # close price
        "E": 1700000000000,  # event time (ms)
        "o": "43000.00",  # open price
        "h": "43500.00",  # high price
        "l": "42800.00",  # low price
        "v": "1000.0",    # volume
    }

    parsed = task._parse_ticker_message(raw_msg)
    assert parsed["price"] == "43250.50"
    assert parsed["market"] == "futures"
    assert parsed["exchange_ts"] == 1700000000000
    assert parsed["source"] == "binance"


def test_binance_futures_feed_parses_message():
    """Test parsing Binance futures miniTicker message."""
    task = BinanceFeedTask(symbol="BTC", redis=AsyncMock(), market="futures")

    raw_msg = {
        "e": "24hrMiniTicker",
        "s": "BTCUSDT",
        "c": "43255.00",  # close price
        "E": 1700000000100,  # event time (ms)
    }

    parsed = task._parse_ticker_message(raw_msg)
    assert parsed["price"] == "43255.00"
    assert parsed["market"] == "futures"
    assert parsed["exchange_ts"] == 1700000000100
    assert parsed["source"] == "binance"


def test_binance_feed_parses_book_ticker_message():
    """bookTicker parsing should emit mid-price and exchange timestamp."""
    task = BinanceFeedTask(symbol="BTC", redis=AsyncMock(), stream_type="bookTicker")

    raw_msg = {
        "e": "bookTicker",
        "E": 1700000000200,
        "b": "43240.0",
        "a": "43260.0",
    }

    parsed = task._parse_ticker_message(raw_msg)
    assert parsed["price"] == "43250.0"
    assert parsed["market"] == "futures"
    assert parsed["exchange_ts"] == 1700000000200
    assert parsed["source"] == "binance"


@pytest.mark.asyncio
async def test_binance_feed_rest_heartbeat_payload():
    """REST heartbeat should produce a publishable ticker payload."""
    task = BinanceFeedTask(symbol="BTC", redis=AsyncMock(), market="futures")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"symbol": "BTCUSDT", "price": "43210.1"})

    class _Ctx:
        async def __aenter__(self):
            return mock_resp

        async def __aexit__(self, exc_type, exc, tb):
            return None

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=_Ctx())

    payload = await task._fetch_rest_heartbeat(mock_session)
    assert payload is not None
    assert payload["price"] == "43210.1"
    assert payload["market"] == "futures"
    assert payload["source"] == "binance_rest"
    assert payload["heartbeat"] == "true"
