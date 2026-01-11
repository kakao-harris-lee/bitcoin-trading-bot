# tests/trading/executor/test_binance_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from trading.executor.binance_client import BinanceClient


def test_binance_client_init():
    """Test client initialization."""
    client = BinanceClient(api_key="test", api_secret="secret")
    assert client.api_key == "test"


@pytest.mark.asyncio
async def test_spot_market_order():
    """Test spot market order execution."""
    client = BinanceClient(api_key="test", api_secret="secret")

    with patch.object(client, '_spot_client') as mock_spot:
        mock_spot.create_order = AsyncMock(return_value={
            "orderId": 12345,
            "executedQty": "0.01",
            "cummulativeQuoteQty": "430.00",
            "status": "FILLED",
        })

        fill = await client.market_order(
            symbol="BTC",
            side="buy",
            quantity=0.01,
            market="spot",
        )

        assert fill["order_id"] == 12345
        assert fill["filled_qty"] == 0.01
        assert fill["status"] == "FILLED"


@pytest.mark.asyncio
async def test_futures_market_order():
    """Test futures market order execution."""
    client = BinanceClient(api_key="test", api_secret="secret")

    with patch.object(client, '_futures_client') as mock_futures:
        mock_futures.futures_create_order = AsyncMock(return_value={
            "orderId": 67890,
            "executedQty": "0.01",
            "cumQuote": "430.50",
            "avgPrice": "43050.00",
            "status": "FILLED",
        })

        fill = await client.market_order(
            symbol="BTC",
            side="sell",
            quantity=0.01,
            market="futures",
        )

        assert fill["order_id"] == 67890
        assert fill["side"] == "sell"
        assert fill["market"] == "futures"
