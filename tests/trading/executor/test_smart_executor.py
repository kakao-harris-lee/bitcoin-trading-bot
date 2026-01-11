# tests/trading/executor/test_smart_executor.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from trading.executor.smart_executor import SmartExecutor
from trading.strategies.volatility_tracker import VolatilityTracker


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


@pytest.mark.asyncio
async def test_volatility_check_trending_down(mock_redis, mock_binance, config):
    """Detect trending down from price action."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    # 3+ consecutive red candles
    prices = [100000, 99500, 99000, 98500]
    executor.volatility_trackers["BTC"] = VolatilityTracker()
    for p in prices:
        executor.volatility_trackers["BTC"].add_price(p)

    action = executor.analyze_price_action("BTC")
    assert action == "trending_down"


@pytest.mark.asyncio
async def test_volatility_check_trending_up(mock_redis, mock_binance, config):
    """Detect trending up from price action."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    # 3+ consecutive green candles
    prices = [100000, 100500, 101000, 101500]
    executor.volatility_trackers["BTC"] = VolatilityTracker()
    for p in prices:
        executor.volatility_trackers["BTC"].add_price(p)

    action = executor.analyze_price_action("BTC")
    assert action == "trending_up"


@pytest.mark.asyncio
async def test_volatility_check_bouncing(mock_redis, mock_binance, config):
    """Detect bouncing/choppy from price action."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    # Up-down-up pattern
    prices = [100000, 100500, 100200, 100700]
    executor.volatility_trackers["BTC"] = VolatilityTracker()
    for p in prices:
        executor.volatility_trackers["BTC"].add_price(p)

    action = executor.analyze_price_action("BTC")
    assert action == "bouncing"


@pytest.mark.asyncio
async def test_volatility_check_unknown_insufficient_data(mock_redis, mock_binance, config):
    """Return unknown when insufficient price data."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    # Only 2 prices - not enough for analysis
    prices = [100000, 99500]
    executor.volatility_trackers["BTC"] = VolatilityTracker()
    for p in prices:
        executor.volatility_trackers["BTC"].add_price(p)

    action = executor.analyze_price_action("BTC")
    assert action == "unknown"


@pytest.mark.asyncio
async def test_volatility_check_unknown_no_tracker(mock_redis, mock_binance, config):
    """Return unknown when no tracker exists for symbol."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    # No tracker for ETH
    action = executor.analyze_price_action("ETH")
    assert action == "unknown"


@pytest.mark.asyncio
async def test_price_monitor_updates_volatility_tracker(mock_redis, mock_binance, config):
    """Price monitor consumes prices and updates volatility trackers."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    # Simulate price messages from Redis stream
    price_messages = [
        {"symbol": "BTC", "price": "100000", "_id": "1-0"},
        {"symbol": "BTC", "price": "100500", "_id": "1-1"},
        {"symbol": "ETH", "price": "3000", "_id": "1-2"},
    ]

    # Configure mock to return messages once, then empty
    mock_redis.consume = AsyncMock(side_effect=[price_messages, []])

    executor._running = True

    # Run one iteration of price monitor
    import asyncio

    async def run_once():
        executor._running = True
        group = "smart-executor-prices"
        consumer = "test-consumer"
        await executor.redis.create_consumer_group("market:prices", group)
        messages = await executor.redis.consume(
            "market:prices", group, consumer, count=50, block_ms=500
        )
        for msg in messages:
            symbol = msg.get("symbol")
            price = msg.get("price")
            if symbol and price:
                if symbol not in executor.volatility_trackers:
                    executor.volatility_trackers[symbol] = VolatilityTracker(
                        window=executor.volatility_window
                    )
                executor.volatility_trackers[symbol].add_price(float(price))

    await run_once()

    # Verify trackers were created and updated
    assert "BTC" in executor.volatility_trackers
    assert "ETH" in executor.volatility_trackers
    assert len(executor.volatility_trackers["BTC"].prices) == 2
    assert len(executor.volatility_trackers["ETH"].prices) == 1


@pytest.mark.asyncio
async def test_price_monitor_updates_hwm_for_active_positions(mock_redis, mock_binance, config):
    """Price monitor updates high water mark for symbols with active positions."""
    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    # Set initial HWM (indicating active position tracking)
    executor.high_water_marks["BTC"] = 99000.0

    # Simulate price message with higher price
    price_messages = [
        {"symbol": "BTC", "price": "100000", "_id": "1-0"},
    ]
    mock_redis.consume = AsyncMock(return_value=price_messages)

    executor._running = True

    # Manually invoke the logic from _price_monitor_loop
    messages = await executor.redis.consume(
        "market:prices", "group", "consumer", count=50, block_ms=500
    )
    for msg in messages:
        symbol = msg.get("symbol")
        price = msg.get("price")
        if symbol and price:
            if symbol not in executor.volatility_trackers:
                executor.volatility_trackers[symbol] = VolatilityTracker(
                    window=executor.volatility_window
                )
            executor.volatility_trackers[symbol].add_price(float(price))
            if symbol in executor.high_water_marks:
                executor.update_high_water_mark(symbol, float(price))

    # Verify HWM was updated
    assert executor.high_water_marks["BTC"] == 100000.0


@pytest.mark.asyncio
async def test_check_active_exits_clears_position_on_complete(mock_redis, mock_binance, config):
    """Exit completion clears the Redis position."""
    from trading.executor.smart_executor import ExitPlan
    import time

    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    # Add clear_position mock
    mock_redis.clear_position = AsyncMock()

    # Create an exit plan with all orders filled
    plan = ExitPlan(
        symbol="BTC",
        market="spot",
        total_quantity=0.10,
        trigger_price=100000.0,
        strategy="v35_long",
        start_time=time.time() - 10,  # Started 10 seconds ago
    )
    plan.ladder_orders = [{"order_id": 12345}]

    executor.active_exits["BTC:spot"] = plan

    # Mock get_order to return fully filled
    mock_binance.get_order = AsyncMock(return_value={
        "order_id": 12345,
        "status": "FILLED",
        "filled_qty": 0.10,
    })

    await executor._check_active_exits()

    # Verify position was cleared
    mock_redis.clear_position.assert_called_once_with("BTC", "spot")

    # Verify exit was removed from active exits
    assert "BTC:spot" not in executor.active_exits


@pytest.mark.asyncio
async def test_check_active_exits_phase1_timeout_triggers_sweep(mock_redis, mock_binance, config):
    """Phase 1 timeout triggers sweep for unfilled orders."""
    from trading.executor.smart_executor import ExitPlan
    import time

    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    # Add clear_position mock
    mock_redis.clear_position = AsyncMock()

    # Create an exit plan that has exceeded phase1_timeout (60s) but not max_execution_time (90s)
    plan = ExitPlan(
        symbol="BTC",
        market="spot",
        total_quantity=0.10,
        trigger_price=100000.0,
        strategy="v35_long",
        start_time=time.time() - 65,  # Started 65 seconds ago (past phase1 timeout)
        phase="ladder",  # Still in ladder phase
    )
    plan.ladder_orders = [{"order_id": 12345}, {"order_id": 12346}]

    executor.active_exits["BTC:spot"] = plan

    # Mock get_order to return partially filled
    mock_binance.get_order = AsyncMock(return_value={
        "order_id": 12345,
        "status": "PARTIALLY_FILLED",
        "filled_qty": 0.04,  # Only first tier filled
    })

    await executor._check_active_exits()

    # Verify cancel_order was called for unfilled orders
    assert mock_binance.cancel_order.call_count >= 1

    # Verify market_order was called for remaining quantity
    mock_binance.market_order.assert_called_once()
    call_args = mock_binance.market_order.call_args
    assert call_args.kwargs["symbol"] == "BTC"
    assert call_args.kwargs["side"] == "sell"

    # Verify position was cleared
    mock_redis.clear_position.assert_called_once_with("BTC", "spot")

    # Verify exit was removed from active exits
    assert "BTC:spot" not in executor.active_exits


@pytest.mark.asyncio
async def test_check_active_exits_max_timeout_triggers_sweep(mock_redis, mock_binance, config):
    """Max execution timeout triggers sweep."""
    from trading.executor.smart_executor import ExitPlan
    import time

    executor = SmartExecutor(
        redis=mock_redis,
        binance_client=mock_binance,
        config=config,
    )

    # Add clear_position mock
    mock_redis.clear_position = AsyncMock()

    # Create an exit plan that has exceeded max_execution_time (90s)
    # Set phase to "sweep" so phase1 check is skipped
    plan = ExitPlan(
        symbol="BTC",
        market="spot",
        total_quantity=0.10,
        trigger_price=100000.0,
        strategy="v35_long",
        start_time=time.time() - 95,  # Started 95 seconds ago (past max timeout)
        phase="sweep",  # Already past phase1
    )
    plan.ladder_orders = [{"order_id": 12345}]

    executor.active_exits["BTC:spot"] = plan

    # Mock get_order to return unfilled
    mock_binance.get_order = AsyncMock(return_value={
        "order_id": 12345,
        "status": "NEW",
        "filled_qty": 0.0,
    })

    await executor._check_active_exits()

    # Verify market_order was called for sweep
    mock_binance.market_order.assert_called_once()

    # Verify position was cleared
    mock_redis.clear_position.assert_called_once_with("BTC", "spot")

    # Verify exit was removed from active exits
    assert "BTC:spot" not in executor.active_exits
