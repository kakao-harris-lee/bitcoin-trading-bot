# tests/trading/executor/test_smart_executor.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from trading.executor.smart_executor import SmartExecutor


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get_position = AsyncMock(return_value=None)
    redis.is_kill_switch_on = AsyncMock(return_value=False)
    redis.publish = AsyncMock(return_value="1234-0")
    redis.consume = AsyncMock(return_value=[])
    redis.create_consumer_group = AsyncMock()
    redis.ack = AsyncMock()
    redis.client = AsyncMock()
    redis.client.xrange = AsyncMock(return_value=[])
    return redis


@pytest.fixture
def mock_binance():
    client = AsyncMock()
    client.limit_order = AsyncMock(return_value={
        "order_id": 12345,
        "status": "NEW",
        "price": 95000.0,
        "filled_qty": 0.0,
    })
    client.cancel_order = AsyncMock(return_value={"status": "CANCELED"})
    client.get_order = AsyncMock(return_value={
        "order_id": 12345,
        "status": "FILLED",
        "filled_qty": 0.01,
    })
    client.market_order = AsyncMock(return_value={
        "order_id": 12346,
        "filled_qty": 0.01,
        "filled_price": 94900.0,
        "status": "FILLED",
    })
    return client


@pytest.fixture
def config():
    return {
        "smart_executor": {
            "enabled": True,
            "trailing": {
                "volatility_window": 20,
                "low_vol_trail": 0.8,
                "med_vol_trail": 1.2,
                "high_vol_trail": 1.8,
            },
            "split_execution": {
                "ladder_tiers": [0.05, 0.12, 0.20],
                "ladder_weights": [0.40, 0.35, 0.25],
                "phase1_timeout_sec": 60,
                "max_execution_sec": 90,
            },
        }
    }


def test_smart_executor_init(mock_redis, mock_binance, config):
    """SmartExecutor initializes with config."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    assert executor.enabled is True
    assert executor.volatility_window == 20


@pytest.mark.asyncio
async def test_calculate_ladder_prices(mock_redis, mock_binance, config):
    """Calculate limit ladder prices."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    base_price = 100000.0
    prices = executor._calculate_ladder_prices(base_price)

    # Should have 3 tiers at +0.05%, +0.12%, +0.20%
    assert len(prices) == 3
    assert prices[0] == pytest.approx(100050.0, rel=0.001)  # +0.05%
    assert prices[1] == pytest.approx(100120.0, rel=0.001)  # +0.12%
    assert prices[2] == pytest.approx(100200.0, rel=0.001)  # +0.20%


@pytest.mark.asyncio
async def test_calculate_ladder_quantities(mock_redis, mock_binance, config):
    """Calculate quantity per ladder tier."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    total_qty = 0.10
    quantities = executor._calculate_ladder_quantities(total_qty)

    # Should split by weights: 40%, 35%, 25%
    assert len(quantities) == 3
    assert quantities[0] == pytest.approx(0.04, rel=0.01)
    assert quantities[1] == pytest.approx(0.035, rel=0.01)
    assert quantities[2] == pytest.approx(0.025, rel=0.01)
    assert sum(quantities) == pytest.approx(total_qty, rel=0.001)


@pytest.mark.asyncio
async def test_update_trailing_stop(mock_redis, mock_binance, config):
    """Test trailing stop updates with price."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    # Price goes up - HWM should update
    executor.update_high_water_mark("BTC", 101000.0)
    assert executor.high_water_marks["BTC"] == 101000.0

    # Price goes up more
    executor.update_high_water_mark("BTC", 102000.0)
    assert executor.high_water_marks["BTC"] == 102000.0

    # Price goes down - HWM stays
    executor.update_high_water_mark("BTC", 101500.0)
    assert executor.high_water_marks["BTC"] == 102000.0


@pytest.mark.asyncio
async def test_calculate_trailing_stop_price(mock_redis, mock_binance, config):
    """Calculate stop price from HWM and volatility."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    executor.high_water_marks["BTC"] = 100000.0

    # Low volatility = tight stop (0.8%)
    stop = executor.calculate_stop_price("BTC", "low")
    assert stop == pytest.approx(99200.0, rel=0.001)

    # High volatility = wide stop (1.8%)
    stop = executor.calculate_stop_price("BTC", "high")
    assert stop == pytest.approx(98200.0, rel=0.001)


@pytest.mark.asyncio
async def test_should_trigger_trailing_stop(mock_redis, mock_binance, config):
    """Trailing stop triggers when price drops below stop."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    executor.high_water_marks["BTC"] = 100000.0

    # Price above stop - no trigger
    assert executor.should_trigger_stop("BTC", 99500.0, "low") is False

    # Price at stop - trigger
    assert executor.should_trigger_stop("BTC", 99200.0, "low") is True

    # Price below stop - trigger
    assert executor.should_trigger_stop("BTC", 99000.0, "low") is True
