import pytest
from unittest.mock import AsyncMock

from trading.executor.binance_client import BinanceClient


def test_binance_client_init():
    client = BinanceClient(api_key="test", api_secret="secret")
    assert client.api_key == "test"
    assert client.api_secret == "secret"


@pytest.fixture
def mock_client():
    client = BinanceClient(api_key="test", api_secret="test")
    client._spot_client = AsyncMock()
    client._is_mock = False
    return client


@pytest.mark.asyncio
async def test_spot_market_order(mock_client):
    mock_client._spot_client.create_order = AsyncMock(
        return_value={
            "orderId": 12345,
            "executedQty": "0.1",
            "cummulativeQuoteQty": "9500.0",
            "status": "FILLED",
        }
    )

    result = await mock_client.market_order(
        symbol="BTC",
        side="buy",
        quantity=0.1,
        market="spot",
    )

    assert result["order_id"] == 12345
    assert result["market"] == "spot"
    assert result["filled_qty"] == 0.1
    assert result["filled_price"] == 95000.0


@pytest.mark.asyncio
async def test_non_spot_market_order_is_rejected(mock_client):
    with pytest.raises(NotImplementedError):
        await mock_client.market_order(
            symbol="BTC",
            side="buy",
            quantity=0.1,
            market="margin",
        )


@pytest.mark.asyncio
async def test_limit_order_spot(mock_client):
    mock_client._spot_client.create_order = AsyncMock(
        return_value={
            "orderId": 54321,
            "executedQty": "0.0",
            "status": "NEW",
            "price": "95000.00",
        }
    )

    result = await mock_client.limit_order(
        symbol="BTC",
        side="sell",
        quantity=0.01,
        price=95000.0,
        market="spot",
    )

    assert result["order_id"] == 54321
    assert result["market"] == "spot"
    assert result["price"] == 95000.0


@pytest.mark.asyncio
async def test_cancel_order_spot(mock_client):
    mock_client._spot_client.cancel_order = AsyncMock(
        return_value={"orderId": 12345, "status": "CANCELED"}
    )

    result = await mock_client.cancel_order(symbol="BTC", order_id=12345, market="spot")

    assert result["status"] == "CANCELED"


@pytest.mark.asyncio
async def test_get_order_status_spot(mock_client):
    mock_client._spot_client.get_order = AsyncMock(
        return_value={
            "orderId": 12345,
            "status": "FILLED",
            "executedQty": "0.01",
            "price": "95000.00",
        }
    )

    result = await mock_client.get_order(symbol="BTC", order_id=12345, market="spot")

    assert result["status"] == "FILLED"
    assert result["filled_qty"] == 0.01
    assert result["price"] == 95000.0


@pytest.mark.asyncio
async def test_stop_loss_limit_order_spot(mock_client):
    mock_client._spot_client.create_order = AsyncMock(
        return_value={"orderId": 77777, "status": "NEW"}
    )

    result = await mock_client.stop_loss_limit_order(
        symbol="BTC",
        side="sell",
        quantity=0.01,
        stop_price=39130.0,
        limit_price=38738.7,
        market="spot",
    )

    assert result["orderId"] == 77777
    assert result["market"] == "spot"


@pytest.mark.asyncio
async def test_cancel_open_orders_spot(mock_client):
    mock_client._spot_client.get_open_orders = AsyncMock(
        return_value=[{"orderId": 101}, {"orderId": 202}]
    )
    mock_client._spot_client.cancel_order = AsyncMock(
        side_effect=[
            {"orderId": 101, "status": "CANCELED"},
            {"orderId": 202, "status": "CANCELED"},
        ]
    )

    result = await mock_client.cancel_open_orders(symbol="BTC", market="spot")

    assert len(result) == 2
    assert result[0]["status"] == "CANCELED"


@pytest.mark.asyncio
async def test_get_balance_returns_spot_only(mock_client):
    mock_client._spot_client.get_account = AsyncMock(
        return_value={
            "balances": [
                {"asset": "USDT", "free": "100.0", "locked": "25.0"},
                {"asset": "BTC", "free": "0.1", "locked": "0.0"},
            ]
        }
    )

    balance = await mock_client.get_balance()

    assert balance.spot_usdt == 125.0
    assert balance.total_usdt == 125.0
