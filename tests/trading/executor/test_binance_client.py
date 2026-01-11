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


@pytest.fixture
def mock_client():
    """Create BinanceClient with mocked internal clients."""
    client = BinanceClient(api_key="test", api_secret="test")
    client._spot_client = AsyncMock()
    client._futures_client = AsyncMock()
    client._is_mock = False
    return client


@pytest.mark.asyncio
async def test_limit_order_spot(mock_client):
    """Test placing spot limit order."""
    mock_client._spot_client.create_order = AsyncMock(return_value={
        "orderId": 12345,
        "executedQty": "0.0",
        "cummulativeQuoteQty": "0.0",
        "status": "NEW",
        "price": "95000.00",
    })

    result = await mock_client.limit_order(
        symbol="BTC",
        side="sell",
        quantity=0.01,
        price=95000.0,
        market="spot",
    )

    assert result["order_id"] == 12345
    assert result["status"] == "NEW"
    assert result["price"] == 95000.0
    mock_client._spot_client.create_order.assert_called_once()


@pytest.mark.asyncio
async def test_limit_order_futures(mock_client):
    """Test placing futures limit order."""
    mock_client._futures_client.futures_create_order = AsyncMock(return_value={
        "orderId": 67890,
        "executedQty": "0.0",
        "cumQuote": "0.0",
        "status": "NEW",
        "price": "94000.00",
    })

    result = await mock_client.limit_order(
        symbol="BTC",
        side="buy",
        quantity=0.01,
        price=94000.0,
        market="futures",
    )

    assert result["order_id"] == 67890
    assert result["status"] == "NEW"
    assert result["price"] == 94000.0
    assert result["market"] == "futures"
    mock_client._futures_client.futures_create_order.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_order_spot(mock_client):
    """Test canceling spot order."""
    mock_client._spot_client.cancel_order = AsyncMock(return_value={
        "orderId": 12345,
        "status": "CANCELED",
    })

    result = await mock_client.cancel_order(
        symbol="BTC",
        order_id=12345,
        market="spot",
    )

    assert result["status"] == "CANCELED"
    mock_client._spot_client.cancel_order.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_order_futures(mock_client):
    """Test canceling futures order."""
    mock_client._futures_client.futures_cancel_order = AsyncMock(return_value={
        "orderId": 67890,
        "status": "CANCELED",
    })

    result = await mock_client.cancel_order(
        symbol="BTC",
        order_id=67890,
        market="futures",
    )

    assert result["status"] == "CANCELED"
    mock_client._futures_client.futures_cancel_order.assert_called_once()


@pytest.mark.asyncio
async def test_get_order_status_spot(mock_client):
    """Test getting spot order status."""
    mock_client._spot_client.get_order = AsyncMock(return_value={
        "orderId": 12345,
        "status": "PARTIALLY_FILLED",
        "executedQty": "0.005",
        "price": "95000.00",
    })

    result = await mock_client.get_order(
        symbol="BTC",
        order_id=12345,
        market="spot",
    )

    assert result["status"] == "PARTIALLY_FILLED"
    assert result["filled_qty"] == 0.005
    assert result["price"] == 95000.0
    mock_client._spot_client.get_order.assert_called_once()


@pytest.mark.asyncio
async def test_get_order_status_futures(mock_client):
    """Test getting futures order status."""
    mock_client._futures_client.futures_get_order = AsyncMock(return_value={
        "orderId": 67890,
        "status": "FILLED",
        "executedQty": "0.01",
        "price": "94000.00",
    })

    result = await mock_client.get_order(
        symbol="BTC",
        order_id=67890,
        market="futures",
    )

    assert result["status"] == "FILLED"
    assert result["filled_qty"] == 0.01
    assert result["price"] == 94000.0
    mock_client._futures_client.futures_get_order.assert_called_once()
