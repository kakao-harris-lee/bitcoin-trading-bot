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
    client._spot_client = AsyncMock()
    client._spot_client.create_order = AsyncMock(return_value={
        "orderId": 12345,
        "executedQty": "0.1",
        "cummulativeQuoteQty": "9500.0",
        "status": "FILLED",
    })

    result = await client.market_order(
        symbol="BTC",
        side="buy",
        quantity=0.1,
        market="spot",
    )

    assert result["order_id"] == 12345
    assert result["market"] == "spot"
    assert result["filled_qty"] == 0.1
    assert result["filled_price"] == 95000.0
    assert result["status"] == "FILLED"
    client._spot_client.create_order.assert_called_once_with(
        symbol="BTCUSDT",
        side="BUY",
        type="MARKET",
        quantity=0.1,
    )


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
        "orderId": 54321,
        "executedQty": "0.0",
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

    assert result["order_id"] == 54321
    assert result["status"] == "NEW"
    assert result["price"] == 95000.0
    assert result["market"] == "spot"
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
        "status": "FILLED",
        "executedQty": "0.01",
        "price": "95000.00",
    })

    result = await mock_client.get_order(
        symbol="BTC",
        order_id=12345,
        market="spot",
    )

    assert result["status"] == "FILLED"
    assert result["filled_qty"] == 0.01
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


@pytest.mark.asyncio
async def test_set_leverage(mock_client):
    """Test setting leverage for a futures symbol."""
    mock_client._futures_client.futures_change_leverage = AsyncMock(return_value={
        "leverage": 5,
        "symbol": "BTCUSDT",
    })

    result = await mock_client.set_leverage("BTC", 5)

    assert result is True
    assert mock_client._leverage_cache["BTCUSDT"] == 5
    mock_client._futures_client.futures_change_leverage.assert_called_once_with(
        symbol="BTCUSDT",
        leverage=5,
    )


@pytest.mark.asyncio
async def test_set_leverage_cached():
    """Test leverage is not re-set when already cached."""
    client = BinanceClient(api_key="test", api_secret="test")
    client._futures_client = AsyncMock()
    client._is_mock = False

    # Pre-cache leverage
    client._leverage_cache["BTCUSDT"] = 10

    result = await client.set_leverage("BTC", 10)

    assert result is True
    # Should not call API since already cached
    client._futures_client.futures_change_leverage.assert_not_called()


@pytest.mark.asyncio
async def test_get_leverage_cached():
    """Test getting leverage from cache."""
    client = BinanceClient(api_key="test", api_secret="test")
    client._leverage_cache["ETHUSDT"] = 20

    leverage = await client.get_leverage("ETH")

    assert leverage == 20


@pytest.mark.asyncio
async def test_get_leverage_from_api(mock_client):
    """Test getting leverage from API when not cached."""
    mock_client._futures_client.futures_account = AsyncMock(return_value={
        "positions": [
            {"symbol": "BTCUSDT", "leverage": "10"},
            {"symbol": "ETHUSDT", "leverage": "5"},
        ]
    })

    leverage = await mock_client.get_leverage("BTC")

    assert leverage == 10
    assert mock_client._leverage_cache["BTCUSDT"] == 10


@pytest.mark.asyncio
async def test_ensure_leverage_sets_when_different(mock_client):
    """Test ensure_leverage sets leverage when current differs."""
    mock_client._futures_client.futures_account = AsyncMock(return_value={
        "positions": [{"symbol": "BTCUSDT", "leverage": "5"}]
    })
    mock_client._futures_client.futures_change_leverage = AsyncMock(return_value={
        "leverage": 10,
        "symbol": "BTCUSDT",
    })

    result = await mock_client.ensure_leverage("BTC", 10)

    assert result is True
    mock_client._futures_client.futures_change_leverage.assert_called_once()


@pytest.mark.asyncio
async def test_initialize_leverage_multiple_symbols(mock_client):
    """Test initializing leverage for multiple symbols."""
    mock_client._futures_client.futures_change_leverage = AsyncMock(return_value={
        "leverage": 3,
    })

    results = await mock_client.initialize_leverage(["BTC", "ETH", "SOL"], leverage=3)

    assert results["BTC"] is True
    assert results["ETH"] is True
    assert results["SOL"] is True
    assert mock_client._futures_client.futures_change_leverage.call_count == 3


@pytest.mark.asyncio
async def test_set_leverage_mock_client():
    """Test leverage works with mock client."""
    client = BinanceClient(api_key="test", api_secret="test")
    client._is_mock = True

    result = await client.set_leverage("BTC", 5)

    assert result is True
    assert client._leverage_cache["BTCUSDT"] == 5


# --- Hedge Mode Tests ---

@pytest.mark.asyncio
async def test_enable_hedge_mode(mock_client):
    """Test enabling hedge mode."""
    mock_client._futures_client.futures_change_position_mode = AsyncMock(return_value={
        "dualSidePosition": True,
    })
    mock_client._hedge_mode_enabled = False

    result = await mock_client.enable_hedge_mode()

    assert result is True
    assert mock_client._hedge_mode_enabled is True
    mock_client._futures_client.futures_change_position_mode.assert_called_once_with(
        dualSidePosition=True
    )


@pytest.mark.asyncio
async def test_enable_hedge_mode_already_enabled():
    """Test hedge mode skips API call if already enabled."""
    client = BinanceClient(api_key="test", api_secret="test")
    client._futures_client = AsyncMock()
    client._hedge_mode_enabled = True

    result = await client.enable_hedge_mode()

    assert result is True
    client._futures_client.futures_change_position_mode.assert_not_called()


@pytest.mark.asyncio
async def test_enable_hedge_mode_mock_client():
    """Test hedge mode works with mock client."""
    client = BinanceClient(api_key="test", api_secret="test")
    client._is_mock = True
    client._hedge_mode_enabled = False

    result = await client.enable_hedge_mode()

    assert result is True
    assert client._hedge_mode_enabled is True


@pytest.mark.asyncio
async def test_hedge_mode_property():
    """Test hedge_mode_enabled property."""
    client = BinanceClient(api_key="test", api_secret="test")

    assert client.hedge_mode_enabled is False

    client._hedge_mode_enabled = True
    assert client.hedge_mode_enabled is True


@pytest.mark.asyncio
async def test_futures_market_order_with_position_side(mock_client):
    """Test futures market order with position_side for hedge mode."""
    mock_client._hedge_mode_enabled = True
    mock_client._futures_client.futures_create_order = AsyncMock(return_value={
        "orderId": 67890,
        "executedQty": "0.01",
        "cumQuote": "430.50",
        "avgPrice": "43050.00",
        "status": "FILLED",
        "positionSide": "LONG",
    })

    fill = await mock_client.market_order(
        symbol="BTC",
        side="buy",
        quantity=0.01,
        market="futures",
        position_side="LONG",
    )

    assert fill["order_id"] == 67890
    assert fill["position_side"] == "LONG"
    mock_client._futures_client.futures_create_order.assert_called_once()
    call_args = mock_client._futures_client.futures_create_order.call_args
    assert call_args.kwargs["positionSide"] == "LONG"


@pytest.mark.asyncio
async def test_futures_market_order_short_position(mock_client):
    """Test futures market order with SHORT position_side."""
    mock_client._hedge_mode_enabled = True
    mock_client._futures_client.futures_create_order = AsyncMock(return_value={
        "orderId": 67891,
        "executedQty": "0.01",
        "cumQuote": "430.50",
        "avgPrice": "43050.00",
        "status": "FILLED",
        "positionSide": "SHORT",
    })

    fill = await mock_client.market_order(
        symbol="BTC",
        side="sell",
        quantity=0.01,
        market="futures",
        position_side="SHORT",
    )

    assert fill["order_id"] == 67891
    assert fill["position_side"] == "SHORT"
    call_args = mock_client._futures_client.futures_create_order.call_args
    assert call_args.kwargs["positionSide"] == "SHORT"


@pytest.mark.asyncio
async def test_futures_limit_order_with_position_side(mock_client):
    """Test futures limit order with position_side for hedge mode."""
    mock_client._hedge_mode_enabled = True
    mock_client._futures_client.futures_create_order = AsyncMock(return_value={
        "orderId": 67892,
        "executedQty": "0.0",
        "cumQuote": "0.0",
        "status": "NEW",
        "price": "43000.00",
        "positionSide": "LONG",
    })

    result = await mock_client.limit_order(
        symbol="BTC",
        side="buy",
        quantity=0.01,
        price=43000.0,
        market="futures",
        position_side="LONG",
    )

    assert result["order_id"] == 67892
    assert result["position_side"] == "LONG"
    call_args = mock_client._futures_client.futures_create_order.call_args
    assert call_args.kwargs["positionSide"] == "LONG"


@pytest.mark.asyncio
async def test_spot_order_ignores_position_side(mock_client):
    """Test spot orders ignore position_side parameter (not applicable to spot)."""
    mock_client._spot_client.create_order = AsyncMock(return_value={
        "orderId": 99999,
        "executedQty": "0.01",
        "cummulativeQuoteQty": "950.0",
        "status": "FILLED",
    })

    result = await mock_client.market_order(
        symbol="BTC",
        side="buy",
        quantity=0.01,
        market="spot",
        position_side="LONG",  # Should be ignored for spot
    )

    assert result["market"] == "spot"
    assert result["status"] == "FILLED"
    # Verify position_side was not passed to spot API
    call_kwargs = mock_client._spot_client.create_order.call_args.kwargs
    assert "positionSide" not in call_kwargs
