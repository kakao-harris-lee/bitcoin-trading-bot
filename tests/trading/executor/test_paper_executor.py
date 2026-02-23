# tests/trading/executor/test_paper_executor.py
import pytest
from unittest.mock import AsyncMock
from trading.executor.paper_executor import PaperExecutor


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
    redis.set_position = AsyncMock()
    redis.set_risk = AsyncMock()
    redis.publish = AsyncMock()
    redis.consume = AsyncMock(return_value=[])
    redis.create_consumer_group = AsyncMock()
    # Mock getting latest price
    redis.hgetall = AsyncMock(return_value={"BTC": "43000"})
    redis.get_position = AsyncMock(return_value=None)
    redis.clear_position = AsyncMock()
    return redis


@pytest.mark.asyncio
async def test_paper_executor_simulates_fill(mock_redis):
    """Test paper executor simulates order fill."""
    executor = PaperExecutor(
        redis=mock_redis,
        config={"initial_balance": 10000},
    )
    executor.last_prices = {"BTC": 43000.0}

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "futures",
        "quantity": "0.01",
        "strategy": "short_v1",
    }

    result = await executor._process_order(order)

    assert result is not None
    assert result["filled_qty"] == 0.01
    assert result["status"] == "FILLED"


@pytest.mark.asyncio
async def test_paper_executor_applies_slippage(mock_redis):
    """Test slippage is applied to fill price."""
    executor = PaperExecutor(
        redis=mock_redis,
        config={"initial_balance": 10000, "slippage": 0.001},
    )
    executor.last_prices = {"BTC": 43000.0}

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "futures",
        "quantity": "0.01",
        "strategy": "short_v1",
    }

    result = await executor._process_order(order)

    # Buy should have positive slippage (higher price)
    assert result["filled_price"] > 43000.0


@pytest.mark.asyncio
async def test_paper_executor_tracks_balance(mock_redis):
    """Test balance tracking."""
    executor = PaperExecutor(
        redis=mock_redis,
        config={"initial_balance": 10000},
    )
    executor.last_prices = {"BTC": 43000.0}

    initial_balance = executor.balance

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "futures",
        "quantity": "0.01",
        "strategy": "short_v1",
    }

    await executor._process_order(order)

    # Balance should decrease by order value + fees
    assert executor.balance < initial_balance


@pytest.mark.asyncio
async def test_is_exit_order_detects_short_exit():
    """Buy order should close a short (sell) position."""
    from unittest.mock import MagicMock
    from trading.executor.paper_executor import PaperExecutor

    # Mock Redis
    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value={
        "side": "sell",  # Short position
        "quantity": "0.01",
        "entry_price": "100000",
    })

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    # Buy order should close short position
    order = {"symbol": "BTC", "market": "futures", "side": "buy"}
    result = await executor._is_exit_order(order)

    assert result is True, "Buy should close short position"


@pytest.mark.asyncio
async def test_is_exit_order_detects_long_exit():
    """Sell order should close a long (buy) position."""
    from unittest.mock import MagicMock
    from trading.executor.paper_executor import PaperExecutor

    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value={
        "side": "buy",  # Long position
        "quantity": "0.01",
        "entry_price": "100000",
    })

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    order = {"symbol": "BTC", "market": "futures", "side": "sell"}
    result = await executor._is_exit_order(order)

    assert result is True, "Sell should close long position"


@pytest.mark.asyncio
async def test_is_exit_order_returns_false_for_new_position():
    """Order should not be exit if no position exists."""
    from unittest.mock import MagicMock
    from trading.executor.paper_executor import PaperExecutor

    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value=None)

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    order = {"symbol": "BTC", "market": "futures", "side": "sell"}
    result = await executor._is_exit_order(order)

    assert result is False, "No position means not an exit"


@pytest.mark.asyncio
async def test_calculate_pnl_for_profitable_short():
    """Short P&L: profit when price drops."""
    from unittest.mock import MagicMock
    from trading.executor.paper_executor import PaperExecutor

    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value={
        "side": "sell",  # Short position
        "quantity": "0.01",
        "entry_price": "100000",
        "leverage": "1",
    })
    mock_redis.get_risk = AsyncMock(return_value={"daily_pnl": "0"})
    mock_redis.hset = AsyncMock()

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    order = {"symbol": "BTC", "market": "futures", "side": "buy"}
    fill = {"filled_qty": 0.01, "filled_price": 95000}  # Price dropped

    result = await executor._calculate_exit_pnl(order, fill)

    # Short profit: (entry - exit) * qty = (100000 - 95000) * 0.01 = 50
    assert result["profit"] == pytest.approx(50.0, rel=0.01)
    assert result["profit_pct"] == pytest.approx(5.0, rel=0.01)


@pytest.mark.asyncio
async def test_calculate_pnl_for_losing_short():
    """Short P&L: loss when price rises."""
    from unittest.mock import MagicMock
    from trading.executor.paper_executor import PaperExecutor

    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value={
        "side": "sell",
        "quantity": "0.01",
        "entry_price": "100000",
        "leverage": "1",
    })
    mock_redis.get_risk = AsyncMock(return_value={"daily_pnl": "0"})
    mock_redis.hset = AsyncMock()

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    order = {"symbol": "BTC", "market": "futures", "side": "buy"}
    fill = {"filled_qty": 0.01, "filled_price": 102000}  # Price rose

    result = await executor._calculate_exit_pnl(order, fill)

    # Short loss: (entry - exit) * qty = (100000 - 102000) * 0.01 = -20
    assert result["profit"] == pytest.approx(-20.0, rel=0.01)
    assert result["profit_pct"] == pytest.approx(-2.0, rel=0.01)


@pytest.mark.asyncio
async def test_calculate_pnl_for_long_still_works():
    """Long P&L should still work correctly."""
    from unittest.mock import MagicMock
    from trading.executor.paper_executor import PaperExecutor

    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(return_value={
        "side": "buy",
        "quantity": "0.01",
        "entry_price": "100000",
        "leverage": "1",
    })
    mock_redis.get_risk = AsyncMock(return_value={"daily_pnl": "0"})
    mock_redis.hset = AsyncMock()

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    order = {"symbol": "BTC", "market": "futures", "side": "sell"}
    fill = {"filled_qty": 0.01, "filled_price": 105000}  # Price rose

    result = await executor._calculate_exit_pnl(order, fill)

    # Long profit: (exit - entry) * qty = (105000 - 100000) * 0.01 = 50
    assert result["profit"] == pytest.approx(50.0, rel=0.01)
    assert result["profit_pct"] == pytest.approx(5.0, rel=0.01)


@pytest.mark.asyncio
async def test_update_position_stores_position_in_redis():
    """_update_position should store position data in Redis."""
    from unittest.mock import MagicMock
    from trading.executor.paper_executor import PaperExecutor

    mock_redis = MagicMock()
    mock_redis.set_position = AsyncMock()

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    order = {
        "symbol": "BTC",
        "market": "futures",
        "side": "sell",
        "strategy": "short_v1",
        "leverage": 5,
    }
    fill = {"filled_qty": 0.01, "filled_price": 100000}

    await executor._update_position(order, fill)

    # Verify set_position was called
    mock_redis.set_position.assert_called_once()
    call_args = mock_redis.set_position.call_args
    assert call_args[0][0] == "BTC"  # symbol
    assert call_args[0][1] == "futures"  # market

    # Verify position data
    position_data = call_args[0][2]
    assert position_data["side"] == "sell"
    assert position_data["leverage"] == "5"
    assert float(position_data["liquidation_price"]) > 0  # Should have liquidation price


@pytest.mark.asyncio
async def test_update_position_calculates_liquidation_price_for_futures():
    """_update_position should calculate liquidation price for futures."""
    from unittest.mock import MagicMock
    from trading.executor.paper_executor import PaperExecutor

    mock_redis = MagicMock()
    mock_redis.set_position = AsyncMock()

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    order = {
        "symbol": "BTC",
        "market": "futures",
        "side": "buy",
        "strategy": "short_v1",
        "leverage": 5,
    }
    fill = {"filled_qty": 0.01, "filled_price": 100000}

    await executor._update_position(order, fill)

    position_data = mock_redis.set_position.call_args[0][2]
    liq_price = float(position_data["liquidation_price"])

    # For 5x long, liquidation should be around 80% of entry
    assert liq_price > 0
    assert liq_price < 100000  # Below entry for long


@pytest.mark.asyncio
async def test_process_order_validates_required_fields(mock_redis):
    """_process_order should validate required fields."""
    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
    executor.last_prices = {"BTC": 43000.0}

    # Missing required fields
    invalid_order = {
        "symbol": "BTC",
        "side": "buy",
        # Missing: id, quantity, market, strategy
    }

    result = await executor._process_order(invalid_order)
    assert result is None


@pytest.mark.asyncio
async def test_process_order_validates_side(mock_redis):
    """_process_order should validate order side."""
    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
    executor.last_prices = {"BTC": 43000.0}

    invalid_order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "invalid_side",  # Invalid
        "quantity": "0.01",
        "market": "futures",
        "strategy": "short_v1",
    }

    result = await executor._process_order(invalid_order)
    assert result is None


@pytest.mark.asyncio
async def test_process_order_validates_market(mock_redis):
    """_process_order should validate market type."""
    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
    executor.last_prices = {"BTC": 43000.0}

    invalid_order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "quantity": "0.01",
        "market": "invalid_market",  # Invalid
        "strategy": "short_v1",
    }

    result = await executor._process_order(invalid_order)
    assert result is None


@pytest.mark.asyncio
async def test_process_order_validates_quantity(mock_redis):
    """_process_order should validate quantity is positive."""
    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
    executor.last_prices = {"BTC": 43000.0}

    invalid_order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "quantity": "-0.01",  # Negative
        "market": "futures",
        "strategy": "short_v1",
    }

    result = await executor._process_order(invalid_order)
    assert result is None


@pytest.mark.asyncio
async def test_pass_risk_gates_handles_bool_kill_switch(mock_redis):
    """_pass_risk_gates should handle boolean kill_switch from Redis."""
    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

    # Test with boolean True
    mock_redis.get_risk = AsyncMock(return_value={
        "kill_switch": True,
        "blocked": "false",
        "daily_pnl": "0"
    })
    result = await executor._pass_risk_gates()
    assert result is False

    # Test with string "TRUE"
    mock_redis.get_risk = AsyncMock(return_value={
        "kill_switch": "TRUE",
        "blocked": "false",
        "daily_pnl": "0"
    })
    result = await executor._pass_risk_gates()
    assert result is False


class TestPaperExecutorRun:
    """Test the run() method."""

    @pytest.mark.asyncio
    async def test_run_creates_consumer_group(self):
        """run() should create consumer group on startup."""
        from unittest.mock import MagicMock
        import asyncio

        mock_redis = MagicMock()
        mock_redis.create_consumer_group = AsyncMock()
        mock_redis.consume = AsyncMock(return_value=[])
        mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})

        executor = PaperExecutor(
            redis=mock_redis,
            config={"initial_balance": 10000, "symbols": ["BCH"]},
        )

        # Side effect to stop executor immediately after first consume call
        async def stop_side_effect(*args, **kwargs):
            executor.stop()
            return []

        mock_redis.consume.side_effect = stop_side_effect

        await executor.run()

        # Verify consumer group was created
        mock_redis.create_consumer_group.assert_called()

    @pytest.mark.asyncio
    async def test_run_starts_price_tracker_task(self):
        """run() should start the price tracker background task."""
        from unittest.mock import MagicMock
        import asyncio

        mock_redis = MagicMock()
        mock_redis.create_consumer_group = AsyncMock()
        mock_redis.consume = AsyncMock(return_value=[])
        mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
        mock_redis.ack = AsyncMock()

        executor = PaperExecutor(
            redis=mock_redis,
            config={"initial_balance": 10000, "symbols": ["BCH"]},
        )

        async def stop_side_effect(*args, **kwargs):
            # Only stop if we are consuming orders (main loop), leave price tracker running ideally or stop global
            if args[0] == "orders":
                executor.stop()
            return []

        mock_redis.consume.side_effect = stop_side_effect

        await executor.run()

        # Verify price tracker task was created
        assert executor._price_tracker_task is not None

    @pytest.mark.asyncio
    async def test_stop_sets_running_to_false(self):
        """stop() should set _running to False."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        executor = PaperExecutor(
            redis=mock_redis,
            config={"initial_balance": 10000, "symbols": ["BCH"]},
        )

        executor._running = True
        executor.stop()

        assert executor._running is False

    @pytest.mark.asyncio
    async def test_run_processes_orders_from_stream(self):
        """run() should process orders from Redis stream."""
        from unittest.mock import MagicMock
        import asyncio

        mock_redis = MagicMock()
        mock_redis.create_consumer_group = AsyncMock()
        mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
        mock_redis.ack = AsyncMock()
        mock_redis.set_position = AsyncMock()
        mock_redis.get_position = AsyncMock(return_value=None)
        mock_redis.publish = AsyncMock()

        executor = PaperExecutor(
            redis=mock_redis,
            config={"initial_balance": 10000, "symbols": ["BCH"]},
        )
        executor.last_prices = {"BTC": 50000.0}

        async def mock_consume(*args, **kwargs):
            # Only verify orders stream
            if args[0] == "orders":
                executor.stop() # Stop after serving this batch
                return [{
                    "_id": "msg-1",
                    "id": "order-1",
                    "symbol": "BTC",
                    "side": "buy",
                    "quantity": "0.01",
                    "market": "futures",
                    "strategy": "test",
                }]
            return []

        mock_redis.consume = AsyncMock(side_effect=mock_consume)

        await executor.run()

        # Should have acknowledged the order
        mock_redis.ack.assert_called()


class TestShortPositions:
    """Test short position handling."""

    @pytest.mark.asyncio
    async def test_process_order_opens_short_position(self):
        """_process_order should handle short (sell) order entry."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
        mock_redis.set_position = AsyncMock()
        mock_redis.get_position = AsyncMock(return_value=None)  # No existing position
        mock_redis.publish = AsyncMock()

        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
        executor.last_prices = {"BTC": 100000.0}

        order = {
            "id": "short-1",
            "symbol": "BTC",
            "side": "sell",
            "market": "futures",
            "quantity": "0.01",
            "strategy": "short_v1",
            "leverage": 5,
        }

        result = await executor._process_order(order)

        assert result is not None
        assert result["side"] == "sell"
        assert result["status"] == "FILLED"

        # Verify position was stored
        mock_redis.set_position.assert_called_once()
        position_data = mock_redis.set_position.call_args[0][2]
        assert position_data["side"] == "sell"

    @pytest.mark.asyncio
    async def test_short_position_applies_slippage_correctly(self):
        """Short orders should apply slippage in favor of the exchange."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
        mock_redis.set_position = AsyncMock()
        mock_redis.get_position = AsyncMock(return_value=None)
        mock_redis.publish = AsyncMock()

        executor = PaperExecutor(
            redis=mock_redis,
            config={"initial_balance": 10000, "slippage": 0.001}
        )
        executor.last_prices = {"BTC": 100000.0}

        order = {
            "id": "short-1",
            "symbol": "BTC",
            "side": "sell",
            "market": "futures",
            "quantity": "0.01",
            "strategy": "short_v1",
        }

        result = await executor._process_order(order)

        # Sell should have negative slippage (lower price for seller)
        assert result["filled_price"] < 100000.0

    @pytest.mark.asyncio
    async def test_short_exit_with_profit(self):
        """Closing short at lower price should yield profit."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
        mock_redis.hset = AsyncMock()
        mock_redis.get_position = AsyncMock(return_value={
            "side": "sell",
            "quantity": "0.01",
            "entry_price": "100000",
            "leverage": "5",
        })
        mock_redis.clear_position = AsyncMock()
        mock_redis.publish = AsyncMock()

        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
        executor.last_prices = {"BTC": 95000.0}  # Price dropped

        order = {
            "id": "exit-1",
            "symbol": "BTC",
            "side": "buy",  # Buy to close short
            "market": "futures",
            "quantity": "0.01",
            "strategy": "short_v1",
        }

        result = await executor._process_order(order)

        assert result is not None
        # Position should be cleared
        mock_redis.clear_position.assert_called_once_with("BTC", "futures")


class TestApplySlippage:
    """Test _apply_slippage method."""

    def test_apply_slippage_buy(self):
        """Buy orders get higher price (unfavorable slippage)."""
        from unittest.mock import MagicMock
        import pytest

        mock_redis = MagicMock()
        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000, "slippage": 0.001})

        result = executor._apply_slippage(100000.0, "buy")
        assert result == pytest.approx(100100.0)  # 0.1% higher

    def test_apply_slippage_sell(self):
        """Sell orders get lower price (unfavorable slippage)."""
        from unittest.mock import MagicMock
        import pytest

        mock_redis = MagicMock()
        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000, "slippage": 0.001})

        result = executor._apply_slippage(100000.0, "sell")
        assert result == pytest.approx(99900.0)  # 0.1% lower


class TestPriceTracker:
    """Test _price_tracker async method."""

    @pytest.mark.asyncio
    async def test_price_tracker_updates_last_prices(self):
        """_price_tracker should update last_prices from stream."""
        from unittest.mock import MagicMock
        import asyncio

        mock_redis = MagicMock()
        mock_redis.create_consumer_group = AsyncMock()
        mock_redis.ack = AsyncMock()

        prices_received = []

        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

        async def mock_consume(*args, **kwargs):
            if len(prices_received) == 0:
                prices_received.append(True)
                return [
                    {"_id": "p1", "symbol": "BTC", "price": "50000"},
                    {"_id": "p2", "symbol": "ETH", "price": "3000"},
                ]
            else:
                executor.stop()
                return []

        mock_redis.consume = AsyncMock(side_effect=mock_consume)

        executor._running = True

        # Should finish quickly
        await executor._price_tracker()

        assert executor.last_prices.get("BTC") == 50000.0
        assert executor.last_prices.get("ETH") == 3000.0


class TestPublishTrade:
    """Test _publish_trade method."""

    @pytest.mark.asyncio
    async def test_publish_trade_sends_to_redis(self):
        """_publish_trade should publish trade data to Redis stream."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.publish = AsyncMock()

        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

        order = {
            "symbol": "BTC",
            "side": "buy",
            "market": "futures",
            "strategy": "short_v1",
        }
        fill = {
            "order_id": "12345678",
            "filled_qty": 0.01,
            "filled_price": 50000.0,
        }

        await executor._publish_trade(order, fill)

        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == "trades"
        trade_data = call_args[0][1]
        assert trade_data["symbol"] == "BTC"
        assert trade_data["paper"] == "true"

    @pytest.mark.asyncio
    async def test_publish_trade_includes_profit_data(self):
        """_publish_trade should include profit data for exits."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.publish = AsyncMock()

        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})

        order = {"symbol": "BTC", "side": "sell", "market": "futures", "strategy": "short_v1"}
        fill = {"order_id": "12345678", "filled_qty": 0.01, "filled_price": 52000.0}
        profit_data = {"profit": 20.0, "profit_pct": 4.0}

        await executor._publish_trade(order, fill, profit_data)

        trade_data = mock_redis.publish.call_args[0][1]
        assert trade_data["profit"] == "20.0"
        assert trade_data["profit_pct"] == "4.0"


class TestSpotSimulation:
    """Test spot trading simulation."""

    @pytest.mark.asyncio
    async def test_simulate_spot_buy(self):
        """_simulate_spot_fill should handle spot buy orders."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
        mock_redis.publish = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.get_position = AsyncMock(return_value=None)  # No existing position for buy
        mock_redis.set_position = AsyncMock()

        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
        executor.last_prices = {"BTC": 50000.0}

        initial_spot_balance = executor.spot_balance

        order = {
            "id": "spot-buy-1",
            "symbol": "BTC",
            "side": "buy",
            "market": "spot",
            "quantity": "0.1",
            "strategy": "spot_test",
        }

        result = await executor._process_order(order)

        # Verify fill result
        assert result is not None
        assert result["market"] == "spot"
        assert result["status"] == "FILLED"
        assert result["filled_qty"] == 0.1

        # Verify balance decreased
        assert executor.spot_balance < initial_spot_balance

        # Verify position added
        assert "BTC" in executor.spot_positions
        assert executor.spot_positions["BTC"] == 0.1

    @pytest.mark.asyncio
    async def test_simulate_spot_sell(self):
        """_simulate_spot_fill should handle spot sell orders."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
        mock_redis.publish = AsyncMock()
        mock_redis.hset = AsyncMock()
        # Mock existing spot position with entry price for P&L calculation
        mock_redis.get_position = AsyncMock(return_value={"entry_price": "49000", "entry_time": "1000000", "side": "buy"})
        mock_redis.clear_position = AsyncMock()

        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
        executor.last_prices = {"BTC": 50000.0}

        # Setup existing spot position
        executor.spot_positions["BTC"] = 0.1

        initial_spot_balance = executor.spot_balance

        order = {
            "id": "spot-sell-1",
            "symbol": "BTC",
            "side": "sell",
            "market": "spot",
            "quantity": "0.1",
            "strategy": "spot_test",
        }

        result = await executor._process_order(order)

        # Verify fill result
        assert result is not None
        assert result["market"] == "spot"
        assert result["status"] == "FILLED"

        # Verify balance increased
        assert executor.spot_balance > initial_spot_balance

        # Verify position removed
        assert "BTC" not in executor.spot_positions

    @pytest.mark.asyncio
    async def test_spot_partial_sell_keeps_redis_position(self):
        """Partial spot sell should keep remaining position in Redis."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.get_risk = AsyncMock(
            return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"}
        )
        mock_redis.publish = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.set_position = AsyncMock()
        mock_redis.clear_position = AsyncMock()
        mock_redis.get_position = AsyncMock(
            return_value={
                "quantity": "0.2",
                "entry_price": "49000",
                "entry_time": "1000000",
                "side": "buy",
                "strategy": "spot_test",
                "leverage": "1",
                "liquidation_price": "0",
            }
        )

        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
        executor.last_prices = {"BTC": 50000.0}
        executor.spot_positions["BTC"] = 0.2

        order = {
            "id": "spot-sell-partial-1",
            "symbol": "BTC",
            "side": "sell",
            "market": "spot",
            "quantity": "0.1",
            "strategy": "spot_test",
        }

        result = await executor._process_order(order)

        assert result is not None
        assert executor.spot_positions["BTC"] == pytest.approx(0.1)
        mock_redis.clear_position.assert_not_called()
        mock_redis.set_position.assert_called_once()
        payload = mock_redis.set_position.call_args[0][2]
        assert float(payload["quantity"]) == pytest.approx(0.1)

    @pytest.mark.asyncio
    async def test_spot_partial_sell_clears_dust_below_min_qty(self):
        """Partial spot sell should clear non-tradable dust below minQty."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.get_risk = AsyncMock(
            return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"}
        )
        mock_redis.publish = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.set_position = AsyncMock()
        mock_redis.clear_position = AsyncMock()
        mock_redis.get_position = AsyncMock(
            return_value={
                "quantity": "0.001343836389923081",
                "entry_price": "577.68098",
                "entry_time": "1000000",
                "side": "buy",
                "strategy": "spot_test",
                "leverage": "1",
                "liquidation_price": "0",
            }
        )

        executor = PaperExecutor(
            redis=mock_redis,
            config={"initial_balance": 10000, "symbols": ["BCH"]},
        )
        executor.last_prices = {"BCH": 540.0}
        executor.spot_positions["BCH"] = 0.001343836389923081

        order = {
            "id": "spot-sell-dust-qty-1",
            "symbol": "BCH",
            "side": "sell",
            "market": "spot",
            "quantity": "0.001",
            "strategy": "spot_test",
        }

        result = await executor._process_order(order)

        assert result is not None
        assert "BCH" not in executor.spot_positions
        mock_redis.clear_position.assert_called_once_with("BCH", "spot")
        mock_redis.set_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_spot_partial_sell_clears_dust_below_min_notional(self):
        """Partial spot sell should clear remaining qty that fails MIN_NOTIONAL."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.get_risk = AsyncMock(
            return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"}
        )
        mock_redis.publish = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.set_position = AsyncMock()
        mock_redis.clear_position = AsyncMock()
        mock_redis.get_position = AsyncMock(
            return_value={
                "quantity": "0.002",
                "entry_price": "577.68098",
                "entry_time": "1000000",
                "side": "buy",
                "strategy": "spot_test",
                "leverage": "1",
                "liquidation_price": "0",
            }
        )

        executor = PaperExecutor(
            redis=mock_redis,
            config={"initial_balance": 10000, "symbols": ["BCH"]},
        )
        executor.last_prices = {"BCH": 540.0}
        executor.spot_positions["BCH"] = 0.002

        order = {
            "id": "spot-sell-dust-notional-1",
            "symbol": "BCH",
            "side": "sell",
            "market": "spot",
            "quantity": "0.001",
            "strategy": "spot_test",
        }

        result = await executor._process_order(order)

        assert result is not None
        assert "BCH" not in executor.spot_positions
        mock_redis.clear_position.assert_called_once_with("BCH", "spot")
        mock_redis.set_position.assert_not_called()

    @pytest.mark.asyncio
    async def test_spot_buy_insufficient_balance(self):
        """Spot buy should fail with insufficient balance."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
        mock_redis.publish = AsyncMock()
        mock_redis.get_position = AsyncMock(return_value=None)  # No existing position

        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 100})
        executor.spot_balance = 100  # Only $100
        executor.last_prices = {"BTC": 50000.0}

        order = {
            "id": "spot-buy-1",
            "symbol": "BTC",
            "side": "buy",
            "market": "spot",
            "quantity": "1.0",  # Way too much
            "strategy": "spot_test",
        }

        result = await executor._process_order(order)

        # Should reject
        assert result is None
        mock_redis.publish.assert_called()

    @pytest.mark.asyncio
    async def test_spot_sell_insufficient_position(self):
        """Spot sell should fail with insufficient position."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
        mock_redis.publish = AsyncMock()
        mock_redis.get_position = AsyncMock(return_value=None)  # No existing position

        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
        executor.last_prices = {"BTC": 50000.0}

        # No position
        order = {
            "id": "spot-sell-1",
            "symbol": "BTC",
            "side": "sell",
            "market": "spot",
            "quantity": "0.1",
            "strategy": "spot_test",
        }

        result = await executor._process_order(order)

        # Should reject
        assert result is None
        mock_redis.publish.assert_called()

    @pytest.mark.asyncio
    async def test_spot_fee_rate_is_higher(self):
        """Spot orders should use higher fee rate (0.1% vs 0.05%)."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
        mock_redis.publish = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.get_position = AsyncMock(return_value=None)  # No existing position
        mock_redis.set_position = AsyncMock()

        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
        executor.last_prices = {"BTC": 50000.0}

        order = {
            "id": "spot-buy-1",
            "symbol": "BTC",
            "side": "buy",
            "market": "spot",
            "quantity": "0.1",
            "strategy": "spot_test",
        }

        await executor._process_order(order)

        # Spot fee: 0.1% = 0.001
        # Futures fee: 0.05% = 0.0005
        assert executor.spot_fee_rate == 0.001
        assert executor.fee_rate == 0.0005

    @pytest.mark.asyncio
    async def test_spot_pnl_calculation(self):
        """Spot sell should correctly calculate P&L based on entry price."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.get_risk = AsyncMock(return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"})
        mock_redis.publish = AsyncMock()
        mock_redis.hset = AsyncMock()
        # Entry price was $49000, exit at $50000 (with slippage)
        mock_redis.get_position = AsyncMock(return_value={
            "entry_price": "49000",
            "entry_time": "1000000",
            "side": "buy",
            "leverage": "1",
        })
        mock_redis.clear_position = AsyncMock()

        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
        executor.last_prices = {"BTC": 50000.0}

        # Setup existing spot position
        executor.spot_positions["BTC"] = 0.1
        initial_spot_balance = executor.spot_balance

        order = {
            "id": "spot-sell-1",
            "symbol": "BTC",
            "side": "sell",
            "market": "spot",
            "quantity": "0.1",
            "strategy": "spot_test",
        }

        result = await executor._process_order(order)

        # Verify fill result has P&L data
        assert result is not None
        assert result["market"] == "spot"

        # Verify hset was called to update daily P&L
        hset_calls = [call for call in mock_redis.hset.call_args_list if call[0][0] == "risk"]
        assert len(hset_calls) > 0, "Should have updated daily P&L in Redis"

        # Verify clear_position was called
        mock_redis.clear_position.assert_called_once()

    @pytest.mark.asyncio
    async def test_spot_exit_logs_exit_even_without_profit_data(self, monkeypatch):
        """Spot sell should emit EXIT event even when entry metadata is missing."""
        from unittest.mock import MagicMock
        from trading.executor import paper_executor as paper_executor_module

        mock_structured_logger = MagicMock()
        monkeypatch.setattr(paper_executor_module, "trade_logger", mock_structured_logger)

        mock_redis = MagicMock()
        mock_redis.get_risk = AsyncMock(
            return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"}
        )
        mock_redis.publish = AsyncMock()
        mock_redis.hset = AsyncMock()
        mock_redis.set_position = AsyncMock()
        mock_redis.clear_position = AsyncMock()
        mock_redis.get_position = AsyncMock(return_value={})

        executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
        executor.last_prices = {"BTC": 50000.0}
        executor.spot_positions["BTC"] = 0.1

        order = {
            "id": "spot-sell-no-profit-1",
            "symbol": "BTC",
            "side": "sell",
            "market": "spot",
            "quantity": "0.1",
            "strategy": "spot_test",
        }

        result = await executor._process_order(order)

        assert result is not None
        mock_structured_logger.exit.assert_called_once()
        mock_structured_logger.entry.assert_not_called()
