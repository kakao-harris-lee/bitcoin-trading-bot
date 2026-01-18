# tests/trading/executor/test_smart_executor_integration.py
"""Integration tests for SmartExecutor exit flow."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from trading.executor.smart_executor import SmartExecutor
from trading.strategies.volatility_tracker import VolatilityTracker
from trading.utils.precision import SymbolInfo


@pytest.fixture
def mock_symbol_info_btc():
    """Mock SymbolInfo for BTCUSDT."""
    return SymbolInfo(
        symbol="BTCUSDT",
        price_precision=2,
        qty_precision=5,
        min_qty="0.00001",
        step_size="0.00001",
        tick_size="0.01",
        min_notional="10.0",
    )


@pytest.fixture
def mock_symbol_info_eth():
    """Mock SymbolInfo for ETHUSDT."""
    return SymbolInfo(
        symbol="ETHUSDT",
        price_precision=2,
        qty_precision=4,
        min_qty="0.0001",
        step_size="0.0001",
        tick_size="0.01",
        min_notional="10.0",
    )


@pytest.fixture
def mock_symbol_info_sol():
    """Mock SymbolInfo for SOLUSDT."""
    return SymbolInfo(
        symbol="SOLUSDT",
        price_precision=2,
        qty_precision=2,
        min_qty="0.01",
        step_size="0.01",
        tick_size="0.01",
        min_notional="10.0",
    )


@pytest.fixture
def mock_exchange_cache(mock_symbol_info_btc, mock_symbol_info_eth, mock_symbol_info_sol):
    """Mock exchange cache that returns symbol info."""
    symbol_map = {
        "BTC": mock_symbol_info_btc,
        "BTCUSDT": mock_symbol_info_btc,
        "ETH": mock_symbol_info_eth,
        "ETHUSDT": mock_symbol_info_eth,
        "SOL": mock_symbol_info_sol,
        "SOLUSDT": mock_symbol_info_sol,
    }
    cache = MagicMock()
    cache.get = MagicMock(side_effect=lambda s: symbol_map.get(s, mock_symbol_info_btc))
    return cache


@pytest.fixture
def mock_redis():
    """Create mock Redis client."""
    redis = AsyncMock()
    redis.consume = AsyncMock(return_value=[])
    redis.create_consumer_group = AsyncMock()
    redis.ack = AsyncMock()
    redis.publish = AsyncMock(return_value="1234-0")
    redis.get_position = AsyncMock(return_value=None)
    redis.hset = AsyncMock()
    return redis


@pytest.fixture
def mock_binance():
    """Create mock Binance client."""
    client = AsyncMock()
    client.limit_order = AsyncMock(return_value={
        "order_id": 12345,
        "status": "NEW",
        "filled_qty": 0.0,
    })
    client.get_order = AsyncMock(return_value={
        "order_id": 12345,
        "status": "FILLED",
        "filled_qty": 0.01,
    })
    client.cancel_order = AsyncMock(return_value={"status": "CANCELED"})
    client.market_order = AsyncMock(return_value={
        "order_id": 12346,
        "status": "FILLED",
        "filled_qty": 0.01,
    })
    return client


@pytest.fixture
def integration_config():
    """Config with 2 ladder tiers for integration testing."""
    return {
        "smart_executor": {
            "enabled": True,
            "trailing": {"volatility_window": 5},
            "split_execution": {
                "ladder_tiers": [0.05, 0.10],
                "ladder_weights": [0.6, 0.4],
                "max_execution_sec": 5,
            },
        }
    }


@pytest.mark.asyncio
async def test_full_exit_flow(mock_redis, mock_binance, integration_config, mock_exchange_cache):
    """Test complete exit flow from signal to completion."""
    executor = SmartExecutor(mock_redis, mock_binance, integration_config)

    # Simulate exit signal
    signal = {
        "symbol": "BTC",
        "market": "spot",
        "quantity": "0.1",
        "trigger_price": "95000",
        "strategy": "v35_long",
    }

    with patch("trading.executor.smart_executor.get_exchange_cache", return_value=mock_exchange_cache):
        await executor._handle_exit_signal(signal)

    # Verify ladder orders placed
    assert mock_binance.limit_order.call_count == 2
    assert "BTC:spot" in executor.active_exits

    # Verify exit plan created correctly
    plan = executor.active_exits["BTC:spot"]
    assert plan.symbol == "BTC"
    assert plan.market == "spot"
    assert plan.total_quantity == 0.1
    assert plan.trigger_price == 95000.0
    assert plan.strategy == "v35_long"
    assert plan.phase == "ladder"
    assert len(plan.ladder_orders) == 2


@pytest.mark.asyncio
async def test_exit_flow_ladder_prices(mock_redis, mock_binance, integration_config, mock_exchange_cache):
    """Test that ladder prices are calculated correctly."""
    executor = SmartExecutor(mock_redis, mock_binance, integration_config)

    signal = {
        "symbol": "ETH",
        "market": "spot",
        "quantity": "1.0",
        "trigger_price": "3000",
        "strategy": "sideways_v2",
    }

    with patch("trading.executor.smart_executor.get_exchange_cache", return_value=mock_exchange_cache):
        await executor._handle_exit_signal(signal)

    # Verify limit_order calls with correct prices
    calls = mock_binance.limit_order.call_args_list

    # First tier: 3000 * (1 + 0.05/100) = 3001.50
    assert calls[0].kwargs["price"] == pytest.approx(3001.5, rel=0.01)
    # Second tier: 3000 * (1 + 0.10/100) = 3003.00
    assert calls[1].kwargs["price"] == pytest.approx(3003.0, rel=0.01)


@pytest.mark.asyncio
async def test_exit_flow_ladder_quantities(mock_redis, mock_binance, integration_config, mock_exchange_cache):
    """Test that ladder quantities match weight distribution."""
    executor = SmartExecutor(mock_redis, mock_binance, integration_config)

    signal = {
        "symbol": "SOL",
        "market": "spot",
        "quantity": "10.0",
        "trigger_price": "150",
        "strategy": "v35_long",
    }

    with patch("trading.executor.smart_executor.get_exchange_cache", return_value=mock_exchange_cache):
        await executor._handle_exit_signal(signal)

    calls = mock_binance.limit_order.call_args_list

    # First tier: 60% of 10.0 = 6.0
    assert calls[0].kwargs["quantity"] == pytest.approx(6.0, rel=0.01)
    # Second tier: 40% of 10.0 = 4.0
    assert calls[1].kwargs["quantity"] == pytest.approx(4.0, rel=0.01)


@pytest.mark.asyncio
async def test_exit_flow_order_parameters(mock_redis, mock_binance, integration_config, mock_exchange_cache):
    """Test that orders are placed with correct parameters."""
    executor = SmartExecutor(mock_redis, mock_binance, integration_config)

    signal = {
        "symbol": "BTC",
        "market": "futures",
        "quantity": "0.05",
        "trigger_price": "100000",
        "strategy": "short_v1",
    }

    with patch("trading.executor.smart_executor.get_exchange_cache", return_value=mock_exchange_cache):
        await executor._handle_exit_signal(signal)

    # All orders should be sell orders
    for call in mock_binance.limit_order.call_args_list:
        assert call.kwargs["symbol"] == "BTC"
        assert call.kwargs["side"] == "sell"
        assert call.kwargs["market"] == "futures"


@pytest.mark.asyncio
async def test_exit_flow_multiple_symbols(mock_redis, mock_binance, integration_config, mock_exchange_cache):
    """Test handling multiple concurrent exits for different symbols."""
    executor = SmartExecutor(mock_redis, mock_binance, integration_config)

    # Exit BTC position
    btc_signal = {
        "symbol": "BTC",
        "market": "spot",
        "quantity": "0.1",
        "trigger_price": "95000",
        "strategy": "v35_long",
    }

    # Exit ETH position
    eth_signal = {
        "symbol": "ETH",
        "market": "spot",
        "quantity": "2.0",
        "trigger_price": "3500",
        "strategy": "v35_long",
    }

    with patch("trading.executor.smart_executor.get_exchange_cache", return_value=mock_exchange_cache):
        await executor._handle_exit_signal(btc_signal)
        await executor._handle_exit_signal(eth_signal)

    # Both exits tracked
    assert "BTC:spot" in executor.active_exits
    assert "ETH:spot" in executor.active_exits

    # 4 total orders (2 per symbol)
    assert mock_binance.limit_order.call_count == 4


@pytest.mark.asyncio
async def test_exit_flow_stores_order_results(mock_redis, mock_binance, integration_config, mock_exchange_cache):
    """Test that order results are stored in the exit plan."""
    # Set up unique order IDs for each call
    order_ids = iter([11111, 22222])
    mock_binance.limit_order = AsyncMock(
        side_effect=lambda **kwargs: {
            "order_id": next(order_ids),
            "status": "NEW",
            "filled_qty": 0.0,
        }
    )

    executor = SmartExecutor(mock_redis, mock_binance, integration_config)

    signal = {
        "symbol": "BTC",
        "market": "spot",
        "quantity": "0.1",
        "trigger_price": "95000",
        "strategy": "v35_long",
    }

    with patch("trading.executor.smart_executor.get_exchange_cache", return_value=mock_exchange_cache):
        await executor._handle_exit_signal(signal)

    plan = executor.active_exits["BTC:spot"]
    assert len(plan.ladder_orders) == 2
    assert plan.ladder_orders[0]["order_id"] == 11111
    assert plan.ladder_orders[1]["order_id"] == 22222
