# tests/trading/core/test_event_emitter.py
"""
EventEmitter unit tests.

Tests cover:
- EventEmitter initialization with enabled/disabled state
- Entry evaluation event emission
- Exit evaluation event emission
- HWM update event emission
- Safety rejection event emission
- Fire-and-forget behavior (non-blocking)
- Stream trimming with maxlen

Note: Tests use mocks, no Redis required.
"""

import pytest
import pytest_asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# Mark all tests as asyncio
pytestmark = pytest.mark.asyncio


class TestEventEmitterDataclasses:
    """Test event dataclasses."""

    async def test_entry_evaluation_event_creation(self):
        """Test EntryEvaluationEvent can be created with all fields."""
        from trading.core.event_emitter import EntryEvaluationEvent

        event = EntryEvaluationEvent(
            timestamp=datetime.now().isoformat(),
            strategy="v35_long",
            symbol="BTC",
            market="futures",
            # Filter conditions
            adx=25.5,
            adx_threshold=20.0,
            adx_passed=True,
            regime="BULL_STRONG",
            regime_allowed=True,
            volatility_score=0.02,
            volatility_threshold=0.03,
            volatility_passed=True,
            # Entry conditions
            mfi=55.0,
            mfi_threshold=52.0,
            mfi_passed=True,
            macd=100.0,
            macd_signal=80.0,
            macd_crossed=True,
            rsi=45.0,
            # Result
            signal_generated=True,
            reason="V35 entry: BULL_STRONG, MFI=55.0, ADX=25.5",
        )

        assert event.strategy == "v35_long"
        assert event.adx_passed is True
        assert event.signal_generated is True

    async def test_exit_evaluation_event_creation(self):
        """Test ExitEvaluationEvent can be created with all fields."""
        from trading.core.event_emitter import ExitEvaluationEvent

        event = ExitEvaluationEvent(
            timestamp=datetime.now().isoformat(),
            strategy="v35_long",
            symbol="BTC",
            market="futures",
            # Position data
            entry_price=43000.0,
            current_price=44000.0,
            quantity=0.05,
            unrealized_pnl=50.0,
            unrealized_pnl_pct=2.33,
            # Exit conditions
            stop_loss_price=42000.0,
            stop_loss_triggered=False,
            take_profit_price=46000.0,
            take_profit_triggered=False,
            trailing_stop_price=43500.0,
            trailing_stop_triggered=False,
            macd_exit_signal=False,
            # HWM tracking
            high_water_mark=44500.0,
            drawdown_from_hwm_pct=1.12,
            # Result
            signal_generated=False,
            reason="Holding: P&L +2.33%",
        )

        assert event.entry_price == 43000.0
        assert event.signal_generated is False

    async def test_hwm_update_event_creation(self):
        """Test HWMUpdateEvent can be created with all fields."""
        from trading.core.event_emitter import HWMUpdateEvent

        event = HWMUpdateEvent(
            timestamp=datetime.now().isoformat(),
            strategy="v35_long",
            symbol="BTC",
            market="futures",
            old_hwm=44000.0,
            new_hwm=44500.0,
            current_price=44500.0,
            trailing_stop_calculated=43700.0,
            trailing_stop_pct=1.8,
        )

        assert event.old_hwm == 44000.0
        assert event.new_hwm == 44500.0

    async def test_safety_rejection_event_creation(self):
        """Test SafetyRejectionEvent can be created with all fields."""
        from trading.core.event_emitter import SafetyRejectionEvent

        event = SafetyRejectionEvent(
            timestamp=datetime.now().isoformat(),
            strategy="v35_long",
            symbol="BTC",
            market="futures",
            rejection_type="weak_trend",
            reason="ADX=15.0 < 20.0 threshold",
            adx=15.0,
            mfi=48.0,
            regime="SIDEWAYS_FLAT",
            volatility_score=0.02,
        )

        assert event.rejection_type == "weak_trend"
        assert event.adx == 15.0


class TestEventEmitterUnit:
    """Unit tests for EventEmitter using mocks."""

    async def test_init_enabled(self):
        """Test EventEmitter initialization when enabled."""
        from trading.core.event_emitter import EventEmitter

        mock_redis = MagicMock()
        emitter = EventEmitter(redis=mock_redis, enabled=True)

        assert emitter.enabled is True
        assert emitter.redis is mock_redis
        assert emitter.maxlen == 2000  # Default

    async def test_init_disabled(self):
        """Test EventEmitter initialization when disabled."""
        from trading.core.event_emitter import EventEmitter

        emitter = EventEmitter(redis=None, enabled=False)

        assert emitter.enabled is False

    async def test_init_custom_maxlen(self):
        """Test EventEmitter with custom maxlen."""
        from trading.core.event_emitter import EventEmitter

        mock_redis = MagicMock()
        emitter = EventEmitter(redis=mock_redis, enabled=True, maxlen=5000)

        assert emitter.maxlen == 5000

    async def test_emit_entry_evaluation_when_enabled(self):
        """Test emitting entry evaluation event when enabled."""
        import asyncio
        from trading.core.event_emitter import EventEmitter, EntryEvaluationEvent

        mock_redis = MagicMock()
        mock_redis.publish_event = AsyncMock(return_value="1234567890-0")

        emitter = EventEmitter(redis=mock_redis, enabled=True)

        event = EntryEvaluationEvent(
            timestamp="2026-01-20T12:00:00",
            strategy="v35_long",
            symbol="BTC",
            market="futures",
            adx=25.5,
            adx_threshold=20.0,
            adx_passed=True,
            regime="BULL_STRONG",
            regime_allowed=True,
            volatility_score=0.02,
            volatility_threshold=0.03,
            volatility_passed=True,
            mfi=55.0,
            mfi_threshold=52.0,
            mfi_passed=True,
            macd=100.0,
            macd_signal=80.0,
            macd_crossed=True,
            rsi=45.0,
            signal_generated=True,
            reason="V35 entry: BULL_STRONG",
        )

        await emitter.emit_entry_evaluation(event)
        # Allow background task to complete
        await asyncio.sleep(0)

        mock_redis.publish_event.assert_called_once()
        call_args = mock_redis.publish_event.call_args
        assert call_args[0][0] == "strategy:entry:events"
        assert call_args[1]["maxlen"] == 2000

    async def test_emit_entry_evaluation_when_disabled(self):
        """Test no emission when disabled."""
        import asyncio
        from trading.core.event_emitter import EventEmitter, EntryEvaluationEvent

        mock_redis = MagicMock()
        mock_redis.publish_event = AsyncMock()

        emitter = EventEmitter(redis=mock_redis, enabled=False)

        event = EntryEvaluationEvent(
            timestamp="2026-01-20T12:00:00",
            strategy="v35_long",
            symbol="BTC",
            market="futures",
            adx=25.5,
            adx_threshold=20.0,
            adx_passed=True,
            regime="BULL_STRONG",
            regime_allowed=True,
            volatility_score=0.02,
            volatility_threshold=0.03,
            volatility_passed=True,
            mfi=55.0,
            mfi_threshold=52.0,
            mfi_passed=True,
            macd=100.0,
            macd_signal=80.0,
            macd_crossed=True,
            rsi=45.0,
            signal_generated=True,
            reason="V35 entry",
        )

        await emitter.emit_entry_evaluation(event)
        await asyncio.sleep(0)

        mock_redis.publish_event.assert_not_called()

    async def test_emit_exit_evaluation_when_enabled(self):
        """Test emitting exit evaluation event when enabled."""
        import asyncio
        from trading.core.event_emitter import EventEmitter, ExitEvaluationEvent

        mock_redis = MagicMock()
        mock_redis.publish_event = AsyncMock(return_value="1234567890-0")

        emitter = EventEmitter(redis=mock_redis, enabled=True)

        event = ExitEvaluationEvent(
            timestamp="2026-01-20T12:00:00",
            strategy="v35_long",
            symbol="BTC",
            market="futures",
            entry_price=43000.0,
            current_price=44000.0,
            quantity=0.05,
            unrealized_pnl=50.0,
            unrealized_pnl_pct=2.33,
            stop_loss_price=42000.0,
            stop_loss_triggered=False,
            take_profit_price=46000.0,
            take_profit_triggered=False,
            trailing_stop_price=43500.0,
            trailing_stop_triggered=False,
            macd_exit_signal=False,
            high_water_mark=44500.0,
            drawdown_from_hwm_pct=1.12,
            signal_generated=False,
            reason="Holding",
        )

        await emitter.emit_exit_evaluation(event)
        await asyncio.sleep(0)

        mock_redis.publish_event.assert_called_once()
        call_args = mock_redis.publish_event.call_args
        assert call_args[0][0] == "strategy:exit:events"

    async def test_emit_hwm_update_when_enabled(self):
        """Test emitting HWM update event when enabled."""
        import asyncio
        from trading.core.event_emitter import EventEmitter, HWMUpdateEvent

        mock_redis = MagicMock()
        mock_redis.publish_event = AsyncMock(return_value="1234567890-0")

        emitter = EventEmitter(redis=mock_redis, enabled=True)

        event = HWMUpdateEvent(
            timestamp="2026-01-20T12:00:00",
            strategy="v35_long",
            symbol="BTC",
            market="futures",
            old_hwm=44000.0,
            new_hwm=44500.0,
            current_price=44500.0,
            trailing_stop_calculated=43700.0,
            trailing_stop_pct=1.8,
        )

        await emitter.emit_hwm_update(event)
        await asyncio.sleep(0)

        mock_redis.publish_event.assert_called_once()
        call_args = mock_redis.publish_event.call_args
        assert call_args[0][0] == "strategy:hwm:updates"

    async def test_emit_safety_rejection_when_enabled(self):
        """Test emitting safety rejection event when enabled."""
        import asyncio
        from trading.core.event_emitter import EventEmitter, SafetyRejectionEvent

        mock_redis = MagicMock()
        mock_redis.publish_event = AsyncMock(return_value="1234567890-0")

        emitter = EventEmitter(redis=mock_redis, enabled=True)

        event = SafetyRejectionEvent(
            timestamp="2026-01-20T12:00:00",
            strategy="v35_long",
            symbol="BTC",
            market="futures",
            rejection_type="weak_trend",
            reason="ADX=15.0 < 20.0 threshold",
            adx=15.0,
            mfi=48.0,
            regime="SIDEWAYS_FLAT",
            volatility_score=0.02,
        )

        await emitter.emit_safety_rejection(event)
        await asyncio.sleep(0)

        mock_redis.publish_event.assert_called_once()
        call_args = mock_redis.publish_event.call_args
        assert call_args[0][0] == "strategy:safety:events"

    async def test_fire_and_forget_does_not_block_on_error(self):
        """Test that emit methods don't block or raise on Redis errors."""
        import asyncio
        from trading.core.event_emitter import EventEmitter, EntryEvaluationEvent

        mock_redis = MagicMock()
        # Simulate Redis error
        mock_redis.publish_event = AsyncMock(side_effect=Exception("Redis connection error"))

        emitter = EventEmitter(redis=mock_redis, enabled=True)

        event = EntryEvaluationEvent(
            timestamp="2026-01-20T12:00:00",
            strategy="v35_long",
            symbol="BTC",
            market="futures",
            adx=25.5,
            adx_threshold=20.0,
            adx_passed=True,
            regime="BULL_STRONG",
            regime_allowed=True,
            volatility_score=0.02,
            volatility_threshold=0.03,
            volatility_passed=True,
            mfi=55.0,
            mfi_threshold=52.0,
            mfi_passed=True,
            macd=100.0,
            macd_signal=80.0,
            macd_crossed=True,
            rsi=45.0,
            signal_generated=True,
            reason="V35 entry",
        )

        # Should not raise, even though Redis fails
        await emitter.emit_entry_evaluation(event)
        # Allow background task to complete (and handle error silently)
        await asyncio.sleep(0)

    async def test_event_serialization_to_dict(self):
        """Test that events serialize to Redis-compatible dict."""
        from trading.core.event_emitter import EntryEvaluationEvent

        event = EntryEvaluationEvent(
            timestamp="2026-01-20T12:00:00",
            strategy="v35_long",
            symbol="BTC",
            market="futures",
            adx=25.5,
            adx_threshold=20.0,
            adx_passed=True,
            regime="BULL_STRONG",
            regime_allowed=True,
            volatility_score=0.02,
            volatility_threshold=0.03,
            volatility_passed=True,
            mfi=55.0,
            mfi_threshold=52.0,
            mfi_passed=True,
            macd=100.0,
            macd_signal=80.0,
            macd_crossed=True,
            rsi=45.0,
            signal_generated=True,
            reason="V35 entry",
        )

        # Event should have to_dict method for Redis serialization
        data = event.to_dict()

        assert isinstance(data, dict)
        assert data["strategy"] == "v35_long"
        assert data["adx"] == "25.5"  # Serialized as string for Redis
        assert data["adx_passed"] == "true"  # Boolean as string


class TestEventEmitterStreams:
    """Test stream naming and structure."""

    async def test_entry_events_stream_name(self):
        """Test entry events go to correct stream."""
        from trading.core.event_emitter import EventEmitter

        assert EventEmitter.ENTRY_EVENTS_STREAM == "strategy:entry:events"

    async def test_exit_events_stream_name(self):
        """Test exit events go to correct stream."""
        from trading.core.event_emitter import EventEmitter

        assert EventEmitter.EXIT_EVENTS_STREAM == "strategy:exit:events"

    async def test_hwm_updates_stream_name(self):
        """Test HWM updates go to correct stream."""
        from trading.core.event_emitter import EventEmitter

        assert EventEmitter.HWM_UPDATES_STREAM == "strategy:hwm:updates"

    async def test_safety_events_stream_name(self):
        """Test safety events go to correct stream."""
        from trading.core.event_emitter import EventEmitter

        assert EventEmitter.SAFETY_EVENTS_STREAM == "strategy:safety:events"
