import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

from trading.executor.paper_executor import PaperExecutor


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get_risk = AsyncMock(
        return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "0"}
    )
    redis.set_position = AsyncMock()
    redis.set_risk = AsyncMock()
    redis.publish = AsyncMock()
    redis.consume = AsyncMock(return_value=[])
    redis.create_consumer_group = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    redis.get_position = AsyncMock(return_value=None)
    redis.clear_position = AsyncMock()
    redis.ack = AsyncMock()
    return redis


def test_log_trade_to_db_preserves_order_strategy(mock_redis):
    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
    executor.trade_logger = MagicMock()

    executor._log_trade_to_db_sync(
        order={
            "symbol": "BTC",
            "side": "buy",
            "market": "spot",
            "strategy": "llm_direction_btc",
        },
        fill={"filled_price": 43000.0, "filled_qty": 0.01},
        profit_data=None,
    )

    executor.trade_logger.log_trade.assert_called_once()
    assert (
        executor.trade_logger.log_trade.call_args.kwargs["strategy_name"]
        == "llm_direction_btc"
    )


@pytest.mark.asyncio
async def test_paper_executor_simulates_spot_buy(mock_redis):
    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
    executor.last_prices = {"BTC": 43000.0}

    order = {
        "id": "test-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "spot",
        "quantity": "0.01",
        "strategy": "llm_direction_btc",
    }

    result = await executor._process_order(order)

    assert result is not None
    assert result["filled_qty"] == 0.01
    assert result["market"] == "spot"
    assert executor.spot_balance < 10000
    mock_redis.set_position.assert_called_once()
    assert any(call.args[0] == "trades" for call in mock_redis.publish.await_args_list)


@pytest.mark.asyncio
async def test_paper_executor_rejects_non_spot_order(mock_redis):
    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
    executor.last_prices = {"BTC": 43000.0}

    order = {
        "id": "legacy-123",
        "symbol": "BTC",
        "side": "buy",
        "market": "margin",
        "quantity": "0.01",
        "strategy": "legacy_strategy",
    }

    result = await executor._process_order(order)

    assert result is None
    mock_redis.publish.assert_called_once()
    alert = mock_redis.publish.call_args[0][1]
    assert alert["reason"] == "unsupported_market"


@pytest.mark.asyncio
async def test_is_exit_order_detects_spot_sell():
    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(
        return_value={"side": "buy", "quantity": "0.01", "entry_price": "100000"}
    )

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
    result = await executor._is_exit_order({"symbol": "BTC", "market": "spot", "side": "sell"})

    assert result is True


@pytest.mark.asyncio
async def test_calculate_pnl_for_profitable_long():
    mock_redis = MagicMock()
    mock_redis.get_position = AsyncMock(
        return_value={
            "side": "buy",
            "quantity": "0.01",
            "entry_price": "100000",
            "leverage": "1",
        }
    )
    mock_redis.get_risk = AsyncMock(return_value={"daily_pnl": "0", "daily_pnl_date": date.today().isoformat()})
    mock_redis.hset = AsyncMock()
    mock_redis.publish = AsyncMock()

    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
    fill = {"symbol": "BTC", "filled_qty": 0.01, "filled_price": 105000}

    result = await executor._calculate_exit_pnl({"symbol": "BTC", "market": "spot", "side": "sell"}, fill)

    assert result["profit"] == pytest.approx(50.0, rel=0.01)
    assert result["profit_pct"] == pytest.approx(5.0, rel=0.01)


@pytest.mark.asyncio
async def test_spot_sell_clears_position_and_updates_balance(mock_redis):
    mock_redis.get_position = AsyncMock(
        return_value={
            "quantity": "0.1",
            "entry_price": "49000",
            "entry_time": "1000000",
            "side": "buy",
            "strategy": "spot_test",
            "leverage": "1",
        }
    )
    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
    executor.last_prices = {"BTC": 50000.0}
    executor.spot_positions["BTC"] = 0.1
    initial_balance = executor.spot_balance

    order = {
        "id": "spot-sell-1",
        "symbol": "BTC",
        "side": "sell",
        "market": "spot",
        "quantity": "0.1",
        "strategy": "spot_test",
    }

    result = await executor._process_order(order)

    assert result is not None
    assert executor.spot_balance > initial_balance
    assert "BTC" not in executor.spot_positions
    mock_redis.clear_position.assert_called_once_with("BTC", "spot")


@pytest.mark.asyncio
async def test_spot_partial_sell_keeps_redis_position(mock_redis):
    mock_redis.get_position = AsyncMock(
        return_value={
            "quantity": "0.2",
            "entry_price": "49000",
            "entry_time": "1000000",
            "side": "buy",
            "strategy": "spot_test",
            "leverage": "1",
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
async def test_get_current_daily_pnl_resets_legacy_cumulative_state(mock_redis, monkeypatch):
    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
    monkeypatch.setattr(PaperExecutor, "_current_paper_day", staticmethod(lambda: "2026-04-22"))
    mock_redis.get_risk = AsyncMock(
        return_value={"kill_switch": "false", "blocked": "false", "daily_pnl": "-286.82"}
    )

    current = await executor._get_current_daily_pnl()

    assert current == 0.0
    mock_redis.set_risk.assert_called_with({"daily_pnl": "0", "daily_pnl_date": "2026-04-22"})


@pytest.mark.asyncio
async def test_pass_risk_gates_ignores_stale_previous_day_loss(mock_redis, monkeypatch):
    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000, "max_daily_loss": 100})
    monkeypatch.setattr(PaperExecutor, "_current_paper_day", staticmethod(lambda: "2026-04-22"))
    mock_redis.get_risk = AsyncMock(
        return_value={
            "kill_switch": "false",
            "blocked": "false",
            "daily_pnl": "-286.82",
            "daily_pnl_date": "2026-04-21",
        }
    )

    result = await executor._pass_risk_gates()

    assert result is True


@pytest.mark.asyncio
async def test_run_creates_consumer_group_and_processes_orders(mock_redis):
    executor = PaperExecutor(redis=mock_redis, config={"initial_balance": 10000})
    executor.last_prices = {"BTC": 50000.0}

    async def consume_side_effect(*args, **kwargs):
        if args[0] == "orders":
            executor.stop()
            return [
                {
                    "_id": "msg-1",
                    "id": "order-1",
                    "symbol": "BTC",
                    "side": "buy",
                    "quantity": "0.01",
                    "market": "spot",
                    "strategy": "test_strategy",
                }
            ]
        return []

    mock_redis.consume = AsyncMock(side_effect=consume_side_effect)

    await executor.run()

    mock_redis.create_consumer_group.assert_called()
    mock_redis.ack.assert_called()
