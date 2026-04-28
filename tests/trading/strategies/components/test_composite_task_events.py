# tests/trading/strategies/components/test_composite_task_events.py
"""
CompositeStrategyTask event emission integration tests.

Tests cover:
- EventEmitter initialization with emit_events flag
- Entry evaluation event emission
- Exit evaluation event emission
- HWM update event emission via exit strategy callback
- Safety rejection event emission
"""

import asyncio
import pytest
import pytest_asyncio
from datetime import datetime
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

# Mark all tests as asyncio
pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_redis():
    """Create mock RedisStreams."""
    redis = MagicMock()
    redis.publish_event = AsyncMock(return_value="1234567890-0")
    redis.publish = AsyncMock(return_value=1)
    redis.get_position = AsyncMock(return_value={})
    redis._client = MagicMock()
    redis._client.hgetall = AsyncMock(return_value={})
    return redis


@pytest.fixture
def mock_entry_strategy():
    """Create mock entry strategy."""
    entry = MagicMock()
    entry.check_entry = MagicMock(return_value=None)
    entry._classify_regime = MagicMock(return_value="BULL_STRONG")
    entry._should_enter = MagicMock(return_value=False)
    entry.params = MagicMock()
    entry.params.mfi_bull = 52.0
    entry.params.mfi_bear = 48.0
    entry.params.adx_trend = 20.0
    return entry


@pytest.fixture
def mock_exit_strategy():
    """Create mock exit strategy."""
    exit_strat = MagicMock()
    exit_strat.check_exit = MagicMock(return_value=None)
    exit_strat.on_position_opened = MagicMock()
    exit_strat.on_position_closed = MagicMock()
    # Mock params for exit strategy
    exit_strat.params = MagicMock()
    exit_strat.params.stop_loss_pct = 0.02
    exit_strat.params.take_profit_pct = 0.05
    return exit_strat


class TestCompositeTaskEmitEventsFlag:
    """Test emit_events flag initialization."""

    async def test_init_without_emit_events_flag(
        self, mock_redis, mock_entry_strategy, mock_exit_strategy
    ):
        """Test CompositeStrategyTask defaults to emit_events=False."""
        from trading.strategies.components.composite_task import CompositeStrategyTask

        task = CompositeStrategyTask(
            name="llm_direction_btc",
            symbols=["BTC"],
            redis=mock_redis,
            entry_strategy=mock_entry_strategy,
            exit_strategy=mock_exit_strategy,
        )

        assert task.emit_events is False
        assert task.event_emitter is None

    async def test_init_with_emit_events_false(
        self, mock_redis, mock_entry_strategy, mock_exit_strategy
    ):
        """Test CompositeStrategyTask with emit_events=False."""
        from trading.strategies.components.composite_task import CompositeStrategyTask

        task = CompositeStrategyTask(
            name="llm_direction_btc",
            symbols=["BTC"],
            redis=mock_redis,
            entry_strategy=mock_entry_strategy,
            exit_strategy=mock_exit_strategy,
            emit_events=False,
        )

        assert task.emit_events is False
        assert task.event_emitter is None

    async def test_init_with_emit_events_true(
        self, mock_redis, mock_entry_strategy, mock_exit_strategy
    ):
        """Test CompositeStrategyTask with emit_events=True creates EventEmitter."""
        from trading.strategies.components.composite_task import CompositeStrategyTask
        from trading.core.event_emitter import EventEmitter

        task = CompositeStrategyTask(
            name="llm_direction_btc",
            symbols=["BTC"],
            redis=mock_redis,
            entry_strategy=mock_entry_strategy,
            exit_strategy=mock_exit_strategy,
            emit_events=True,
        )

        assert task.emit_events is True
        assert task.event_emitter is not None
        assert isinstance(task.event_emitter, EventEmitter)
        assert task.event_emitter.enabled is True


class TestCompositeTaskEntryEventEmission:
    """Test entry evaluation event emission."""

    async def test_entry_evaluation_emits_event_when_enabled(
        self, mock_redis, mock_entry_strategy, mock_exit_strategy
    ):
        """Test that entry evaluation emits event when emit_events=True."""
        from trading.strategies.components.composite_task import CompositeStrategyTask
        from trading.strategies.components.models import MarketData

        task = CompositeStrategyTask(
            name="llm_direction_btc",
            symbols=["BTC"],
            redis=mock_redis,
            entry_strategy=mock_entry_strategy,
            exit_strategy=mock_exit_strategy,
            emit_events=True,
        )

        # Setup price buffer and history
        task.price_buffer["BTC"] = [{"price": "43000", "timestamp": 1234567890}]
        task.history["BTC"] = [
            {"open": 42000, "high": 43500, "low": 41500, "close": 43000, "volume": 1000}
            for _ in range(200)
        ]

        # Mock _build_market_data to return valid data
        mock_market_data = MarketData(
            symbol="BTC",
            close=43000.0,
            mfi=55.0,
            adx=25.0,
            rsi=45.0,
            timestamp=1234567890,
        )
        task._build_market_data = MagicMock(return_value=mock_market_data)

        # Evaluate (entry strategy returns None = no signal)
        await task.evaluate("BTC")
        # Allow background event emission tasks to complete
        await asyncio.sleep(0)

        # Verify entry event was emitted
        mock_redis.publish_event.assert_called()
        calls = mock_redis.publish_event.call_args_list
        entry_calls = [c for c in calls if c[0][0] == "strategy:entry:events"]
        assert len(entry_calls) >= 1

    async def test_entry_evaluation_does_not_emit_when_disabled(
        self, mock_redis, mock_entry_strategy, mock_exit_strategy
    ):
        """Test that entry evaluation does not emit when emit_events=False."""
        from trading.strategies.components.composite_task import CompositeStrategyTask
        from trading.strategies.components.models import MarketData

        task = CompositeStrategyTask(
            name="llm_direction_btc",
            symbols=["BTC"],
            redis=mock_redis,
            entry_strategy=mock_entry_strategy,
            exit_strategy=mock_exit_strategy,
            emit_events=False,
        )

        # Setup price buffer and history
        task.price_buffer["BTC"] = [{"price": "43000", "timestamp": 1234567890}]
        task.history["BTC"] = [
            {"open": 42000, "high": 43500, "low": 41500, "close": 43000, "volume": 1000}
            for _ in range(200)
        ]

        # Mock _build_market_data
        mock_market_data = MarketData(
            symbol="BTC",
            close=43000.0,
            mfi=55.0,
            adx=25.0,
            rsi=45.0,
            timestamp=1234567890,
        )
        task._build_market_data = MagicMock(return_value=mock_market_data)

        await task.evaluate("BTC")
        await asyncio.sleep(0)

        # Verify NO entry event was emitted
        calls = mock_redis.publish_event.call_args_list
        entry_calls = [c for c in calls if c[0][0] == "strategy:entry:events"]
        assert len(entry_calls) == 0

    async def test_entry_decision_snapshot_uses_latest_entry_hint(
        self, mock_redis, mock_entry_strategy, mock_exit_strategy
    ):
        """Decision snapshot should use reason from latest real entry evaluation."""
        from trading.strategies.components.composite_task import CompositeStrategyTask
        from trading.strategies.components.models import MarketData

        task = CompositeStrategyTask(
            name="llm_direction_btc",
            symbols=["BTC"],
            redis=mock_redis,
            entry_strategy=mock_entry_strategy,
            exit_strategy=mock_exit_strategy,
            emit_events=False,
        )

        market_data = MarketData(
            symbol="BTC",
            close=43000.0,
            mfi=62.0,
            adx=30.0,
            rsi=55.0,
            timestamp=1234567890,
        )
        task._update_entry_decision_hint(
            "BTC",
            should_enter=False,
            reason="LLM predicted HOLD (conf=0.00): policy hold",
        )

        decision, reason, _ = task._build_entry_decision_snapshot(
            market_data=market_data,
            regime="BULL_STRONG",
            mfi_bull=52.0,
            mfi_bear=48.0,
            adx_trend=20.0,
        )

        assert decision == "WAIT"
        assert "LLM predicted HOLD" in reason

    async def test_entry_event_uses_no_signal_reason_hint(
        self, mock_redis, mock_entry_strategy, mock_exit_strategy
    ):
        """Entry evaluation event reason should use strategy rejection reason."""
        from trading.strategies.components.composite_task import CompositeStrategyTask
        from trading.strategies.components.models import MarketData, build_market_context

        task = CompositeStrategyTask(
            name="llm_direction_btc",
            symbols=["BTC"],
            redis=mock_redis,
            entry_strategy=mock_entry_strategy,
            exit_strategy=mock_exit_strategy,
            emit_events=True,
        )

        market_data = MarketData(
            symbol="BTC",
            close=43000.0,
            mfi=62.0,
            adx=30.0,
            rsi=55.0,
            timestamp=1234567890,
            atr=1200.0,
            volume=100.0,
            avg_volume_20=80.0,
        )
        context = build_market_context(mfi=62.0, adx=30.0, atr=1200.0, close=43000.0)

        await task._emit_entry_evaluation(
            market_data,
            context,
            signal=None,
            no_signal_reason="LLM predicted HOLD (conf=0.00): policy hold",
        )
        await asyncio.sleep(0)

        calls = mock_redis.publish_event.call_args_list
        entry_calls = [c for c in calls if c[0][0] == "strategy:entry:events"]
        assert len(entry_calls) >= 1
        payload = entry_calls[-1][0][1]
        assert payload["reason"] == "LLM predicted HOLD (conf=0.00): policy hold"


class TestCompositeTaskPositionParsing:
    """Test position dict parsing for exit contexts."""

    async def test_dict_to_position_maps_entry_time(
        self, mock_redis, mock_entry_strategy, mock_exit_strategy
    ):
        from trading.strategies.components.composite_task import CompositeStrategyTask

        task = CompositeStrategyTask(
            name="llm_direction_btc",
            symbols=["BTC"],
            redis=mock_redis,
            entry_strategy=mock_entry_strategy,
            exit_strategy=mock_exit_strategy,
            emit_events=False,
        )

        position = task._dict_to_position(
            {
                "symbol": "BTC",
                "entry_price": "43000",
                "quantity": "0.05",
                "strategy": "llm_direction_btc",
                "market": "spot",
                "entry_time": "1234567000",
                "side": "buy",
                "leverage": "1",
            }
        )

        assert position.timestamp == 1234567000
        assert position.entry_time == 1234567000


class TestCompositeTaskEntryFunnelEmission:
    """Test selector-to-order funnel event emission."""

    async def test_entry_funnel_emits_no_signal_reason(
        self, mock_redis, mock_entry_strategy, mock_exit_strategy
    ):
        """No-signal evaluations should emit a funnel event with rejection detail."""
        from trading.strategies.components.composite_task import CompositeStrategyTask
        from trading.strategies.components.models import MarketData, build_market_context, TradingContext

        task = CompositeStrategyTask(
            name="llm_direction_btc",
            symbols=["BTC"],
            redis=mock_redis,
            entry_strategy=mock_entry_strategy,
            exit_strategy=mock_exit_strategy,
            emit_events=True,
        )

        market_data = MarketData(
            symbol="BTC",
            close=43000.0,
            mfi=62.0,
            adx=30.0,
            rsi=55.0,
            timestamp=1234567890,
            atr=900.0,
            volume=100.0,
            avg_volume_20=80.0,
        )
        context = build_market_context(mfi=62.0, adx=30.0, atr=900.0, close=43000.0)
        ctx = TradingContext(
            symbol="BTC",
            timestamp=market_data.timestamp,
            market=market_data,
            regime=context,
            positions=MappingProxyType({}),
        )

        task._refresh_indicator_history = AsyncMock()
        task._build_market_data = MagicMock(return_value=market_data)
        task._build_entry_context = MagicMock(return_value=(context, ctx))
        task._update_regime_snapshot = AsyncMock()
        task._check_and_record_decision = AsyncMock()
        task._passes_entry_gates = MagicMock(return_value=True)
        task._dq_entry_assessment["BTC"] = {
            "allowed": True,
            "reason": "ok",
            "tier": "high",
            "price_age_seconds": 1.5,
            "ticks_per_minute": 12.0,
        }
        task._resolve_entry_leverage = AsyncMock(return_value=1.0)
        task.entry_strategy.check_entry.return_value = None
        task.entry_strategy.get_last_rejection_reason = MagicMock(
            return_value="LLM predicted HOLD (conf=0.00): policy hold"
        )

        await task.evaluate("BTC")
        await asyncio.sleep(0)

        calls = mock_redis.publish_event.call_args_list
        funnel_calls = [c for c in calls if c[0][0] == "strategy:entry:funnel"]
        assert len(funnel_calls) >= 1
        payload = funnel_calls[-1][0][1]
        assert payload["entry_signal_generated"] == "false"
        assert payload["entry_rejection_category"] == "model_non_buy"
        assert payload["order_build_result"] == "not_attempted"

    async def test_entry_funnel_emits_built_and_published_order(
        self, mock_redis, mock_entry_strategy, mock_exit_strategy
    ):
        """Built orders should emit a funnel event after publish."""
        from trading.strategies.components.composite_task import CompositeStrategyTask
        from trading.strategies.components.models import MarketData, Signal, TradingContext, build_market_context

        task = CompositeStrategyTask(
            name="llm_direction_btc",
            symbols=["BTC"],
            redis=mock_redis,
            entry_strategy=mock_entry_strategy,
            exit_strategy=mock_exit_strategy,
            emit_events=True,
        )

        market_data = MarketData(
            symbol="BTC",
            close=43000.0,
            mfi=65.0,
            adx=32.0,
            rsi=57.0,
            timestamp=1234567890,
            atr=800.0,
            volume=120.0,
            avg_volume_20=80.0,
        )
        context = build_market_context(mfi=65.0, adx=32.0, atr=800.0, close=43000.0)
        ctx = TradingContext(
            symbol="BTC",
            timestamp=market_data.timestamp,
            market=market_data,
            regime=context,
            positions=MappingProxyType({}),
        )
        signal = Signal(
            symbol="BTC",
            side="buy",
            market="spot",
            quantity=0.1,
            reason="LLMDirection entry: BUY conf=0.65 provider=ollama model=test prompt=v1 reason=trend aligned",
        )
        order = {
            "symbol": "BTC",
            "side": "buy",
            "market": "spot",
            "quantity": "0.1",
            "reason": signal.reason,
        }

        task._refresh_indicator_history = AsyncMock()
        task._build_market_data = MagicMock(return_value=market_data)
        task._build_entry_context = MagicMock(return_value=(context, ctx))
        task._update_regime_snapshot = AsyncMock()
        task._check_and_record_decision = AsyncMock()
        task._passes_entry_gates = MagicMock(return_value=True)
        task._dq_entry_assessment["BTC"] = {
            "allowed": True,
            "reason": "ok",
            "tier": "high",
            "price_age_seconds": 0.8,
            "ticks_per_minute": 18.0,
        }
        task._resolve_entry_leverage = AsyncMock(return_value=1.0)
        task.entry_strategy.check_entry.return_value = signal
        task._build_entry_order = AsyncMock(return_value=order)

        built = await task.evaluate("BTC")
        assert built == order

        await task._publish_order(order)
        await asyncio.sleep(0)

        calls = mock_redis.publish_event.call_args_list
        funnel_calls = [c for c in calls if c[0][0] == "strategy:entry:funnel"]
        assert len(funnel_calls) >= 1
        payload = funnel_calls[-1][0][1]
        assert payload["entry_signal_generated"] == "true"
        assert payload["entry_route"] == "llm"
        assert payload["order_build_result"] == "built"
        assert payload["order_published"] == "true"


class TestCompositeTaskExitEventEmission:
    """Test exit evaluation event emission."""

    async def test_exit_evaluation_emits_event_when_enabled(
        self, mock_redis, mock_entry_strategy, mock_exit_strategy
    ):
        """Test that exit evaluation emits event when emit_events=True."""
        from trading.strategies.components.composite_task import CompositeStrategyTask
        from trading.strategies.components.models import MarketData

        task = CompositeStrategyTask(
            name="llm_direction_btc",
            symbols=["BTC"],
            redis=mock_redis,
            entry_strategy=mock_entry_strategy,
            exit_strategy=mock_exit_strategy,
            emit_events=True,
        )

        # Setup price buffer and history
        task.price_buffer["BTC"] = [{"price": "44000", "timestamp": 1234567890}]
        task.history["BTC"] = [
            {"open": 42000, "high": 43500, "low": 41500, "close": 44000, "volume": 1000}
            for _ in range(200)
        ]

        # Mock _build_market_data
        mock_market_data = MarketData(
            symbol="BTC",
            close=44000.0,
            mfi=55.0,
            adx=25.0,
            rsi=45.0,
            timestamp=1234567890,
        )
        task._build_market_data = MagicMock(return_value=mock_market_data)

        position_dict = {
            "symbol": "BTC",
            "entry_price": "43000",
            "quantity": "0.05",
            "strategy": "llm_direction_btc",
            "market": "spot",
            "timestamp": 1234567000,
        }

        # Evaluate exit (exit strategy returns None = no signal)
        await task.evaluate_exit("BTC", position_dict)
        await asyncio.sleep(0)

        # Verify exit event was emitted
        mock_redis.publish_event.assert_called()
        calls = mock_redis.publish_event.call_args_list
        exit_calls = [c for c in calls if c[0][0] == "strategy:exit:events"]
        assert len(exit_calls) >= 1


class TestCompositeTaskSafetyEventEmission:
    """Test safety rejection event emission."""

    async def test_safety_rejection_emits_event_when_entry_blocked(
        self, mock_redis, mock_entry_strategy, mock_exit_strategy
    ):
        """Test that safety rejection event is emitted when entry is blocked."""
        from trading.strategies.components.composite_task import CompositeStrategyTask
        from trading.strategies.components.models import MarketData, MarketContext

        task = CompositeStrategyTask(
            name="llm_direction_btc",
            symbols=["BTC"],
            redis=mock_redis,
            entry_strategy=mock_entry_strategy,
            exit_strategy=mock_exit_strategy,
            emit_events=True,
        )

        # Setup price buffer and history
        task.price_buffer["BTC"] = [{"price": "43000", "timestamp": 1234567890}]
        task.history["BTC"] = [
            {"open": 42000, "high": 43500, "low": 41500, "close": 43000, "volume": 1000}
            for _ in range(200)
        ]

        # Mock weak trend conditions (ADX < threshold)
        mock_market_data = MarketData(
            symbol="BTC",
            close=43000.0,
            mfi=48.0,  # Neutral MFI
            adx=15.0,  # Weak ADX < 20
            rsi=50.0,
            timestamp=1234567890,
            atr=500.0,
        )
        task._build_market_data = MagicMock(return_value=mock_market_data)

        # Mock context with weak trend
        mock_context = MarketContext(
            trend="NEUTRAL",
            regime="SIDEWAYS_FLAT",
            volatility_score=0.012,
            is_extreme_volatility=False,
            adx=15.0,
        )
        task._build_market_context = MagicMock(return_value=mock_context)

        # Entry strategy should reject (return None) due to weak trend
        mock_entry_strategy.check_entry.return_value = None

        await task.evaluate("BTC")
        await asyncio.sleep(0)

        # Verify safety rejection event was emitted
        calls = mock_redis.publish_event.call_args_list
        safety_calls = [c for c in calls if c[0][0] == "strategy:safety:events"]
        assert len(safety_calls) >= 1


class TestCompositeTaskHWMEventEmission:
    """Test HWM update event emission."""

    async def test_hwm_update_emits_event(
        self, mock_redis, mock_entry_strategy, mock_exit_strategy
    ):
        """Test that HWM update emits event via exit strategy callback."""
        from trading.strategies.components.composite_task import CompositeStrategyTask
        from trading.core.event_emitter import HWMUpdateEvent

        task = CompositeStrategyTask(
            name="llm_direction_btc",
            symbols=["BTC"],
            redis=mock_redis,
            entry_strategy=mock_entry_strategy,
            exit_strategy=mock_exit_strategy,
            emit_events=True,
        )

        # Directly call the HWM emit method
        event = HWMUpdateEvent(
            timestamp=datetime.now().isoformat(),
            strategy="llm_direction_btc",
            symbol="BTC",
            market="spot",
            old_hwm=44000.0,
            new_hwm=44500.0,
            current_price=44500.0,
            trailing_stop_calculated=43700.0,
            trailing_stop_pct=1.8,
        )

        await task.event_emitter.emit_hwm_update(event)
        await asyncio.sleep(0)

        # Verify HWM event was emitted
        calls = mock_redis.publish_event.call_args_list
        hwm_calls = [c for c in calls if c[0][0] == "strategy:hwm:updates"]
        assert len(hwm_calls) == 1
