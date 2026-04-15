# trading/core/event_emitter.py
"""
EventEmitter for component-specific observability events.

Provides fire-and-forget async event emission to Redis streams for:
- Entry condition evaluations
- Entry funnel attribution
- Exit condition evaluations
- High Water Mark (HWM) updates
- Safety filter rejections

Events are opt-in via the `enabled` flag and do not block the trading loop.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)


@dataclass
class EntryEvaluationEvent:
    """Event capturing entry condition evaluation details."""

    timestamp: str
    strategy: str
    symbol: str
    market: str
    # Filter conditions
    adx: float
    adx_threshold: float
    adx_passed: bool
    regime: str
    regime_allowed: bool
    volatility_score: float
    volatility_threshold: float
    volatility_passed: bool
    # Entry conditions
    mfi: float
    mfi_threshold: float
    mfi_passed: bool
    macd: float
    macd_signal: float
    macd_crossed: bool
    rsi: float
    # Result
    signal_generated: bool
    reason: str

    def to_dict(self) -> dict[str, str]:
        """Convert to Redis-compatible dict (all values as strings)."""
        return {
            "timestamp": self.timestamp,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "market": self.market,
            "adx": str(self.adx),
            "adx_threshold": str(self.adx_threshold),
            "adx_passed": "true" if self.adx_passed else "false",
            "regime": self.regime,
            "regime_allowed": "true" if self.regime_allowed else "false",
            "volatility_score": str(self.volatility_score),
            "volatility_threshold": str(self.volatility_threshold),
            "volatility_passed": "true" if self.volatility_passed else "false",
            "mfi": str(self.mfi),
            "mfi_threshold": str(self.mfi_threshold),
            "mfi_passed": "true" if self.mfi_passed else "false",
            "macd": str(self.macd),
            "macd_signal": str(self.macd_signal),
            "macd_crossed": "true" if self.macd_crossed else "false",
            "rsi": str(self.rsi),
            "signal_generated": "true" if self.signal_generated else "false",
            "reason": self.reason,
        }


@dataclass
class EntryFunnelEvent:
    """Event capturing selector-to-order attribution for entry flow."""

    timestamp: str
    strategy: str
    symbol: str
    market: str
    regime: str
    selector_selected: bool
    selector_rank: int
    selector_score: float
    selector_reason: str
    selector_event_types: str
    dq_allowed: bool
    dq_reason: str
    dq_tier: str
    dq_price_age_seconds: float
    dq_ticks_per_minute: float
    gate_passed: bool
    gate_reason: str
    leverage_allowed: bool
    leverage_reason: str
    entry_signal_generated: bool
    entry_route: str
    entry_rejection_category: str
    entry_rejection_reason: str
    order_build_result: str
    order_drop_reason: str
    order_published: bool

    def to_dict(self) -> dict[str, str]:
        """Convert to Redis-compatible dict (all values as strings)."""
        return {
            "timestamp": self.timestamp,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "market": self.market,
            "regime": self.regime,
            "selector_selected": "true" if self.selector_selected else "false",
            "selector_rank": str(self.selector_rank),
            "selector_score": str(self.selector_score),
            "selector_reason": self.selector_reason,
            "selector_event_types": self.selector_event_types,
            "dq_allowed": "true" if self.dq_allowed else "false",
            "dq_reason": self.dq_reason,
            "dq_tier": self.dq_tier,
            "dq_price_age_seconds": str(self.dq_price_age_seconds),
            "dq_ticks_per_minute": str(self.dq_ticks_per_minute),
            "gate_passed": "true" if self.gate_passed else "false",
            "gate_reason": self.gate_reason,
            "leverage_allowed": "true" if self.leverage_allowed else "false",
            "leverage_reason": self.leverage_reason,
            "entry_signal_generated": "true" if self.entry_signal_generated else "false",
            "entry_route": self.entry_route,
            "entry_rejection_category": self.entry_rejection_category,
            "entry_rejection_reason": self.entry_rejection_reason,
            "order_build_result": self.order_build_result,
            "order_drop_reason": self.order_drop_reason,
            "order_published": "true" if self.order_published else "false",
        }


@dataclass
class ExitEvaluationEvent:
    """Event capturing exit condition evaluation details."""

    timestamp: str
    strategy: str
    symbol: str
    market: str
    # Position data
    entry_price: float
    current_price: float
    quantity: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    # Exit conditions
    stop_loss_price: float
    stop_loss_triggered: bool
    take_profit_price: float
    take_profit_triggered: bool
    trailing_stop_price: float
    trailing_stop_triggered: bool
    macd_exit_signal: bool
    # HWM tracking
    high_water_mark: float
    drawdown_from_hwm_pct: float
    # Result
    signal_generated: bool
    reason: str

    def to_dict(self) -> dict[str, str]:
        """Convert to Redis-compatible dict (all values as strings)."""
        return {
            "timestamp": self.timestamp,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "market": self.market,
            "entry_price": str(self.entry_price),
            "current_price": str(self.current_price),
            "quantity": str(self.quantity),
            "unrealized_pnl": str(self.unrealized_pnl),
            "unrealized_pnl_pct": str(self.unrealized_pnl_pct),
            "stop_loss_price": str(self.stop_loss_price),
            "stop_loss_triggered": "true" if self.stop_loss_triggered else "false",
            "take_profit_price": str(self.take_profit_price),
            "take_profit_triggered": "true" if self.take_profit_triggered else "false",
            "trailing_stop_price": str(self.trailing_stop_price),
            "trailing_stop_triggered": "true" if self.trailing_stop_triggered else "false",
            "macd_exit_signal": "true" if self.macd_exit_signal else "false",
            "high_water_mark": str(self.high_water_mark),
            "drawdown_from_hwm_pct": str(self.drawdown_from_hwm_pct),
            "signal_generated": "true" if self.signal_generated else "false",
            "reason": self.reason,
        }


@dataclass
class HWMUpdateEvent:
    """Event capturing High Water Mark update."""

    timestamp: str
    strategy: str
    symbol: str
    market: str
    old_hwm: float
    new_hwm: float
    current_price: float
    trailing_stop_calculated: float
    trailing_stop_pct: float

    def to_dict(self) -> dict[str, str]:
        """Convert to Redis-compatible dict (all values as strings)."""
        return {
            "timestamp": self.timestamp,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "market": self.market,
            "old_hwm": str(self.old_hwm),
            "new_hwm": str(self.new_hwm),
            "current_price": str(self.current_price),
            "trailing_stop_calculated": str(self.trailing_stop_calculated),
            "trailing_stop_pct": str(self.trailing_stop_pct),
        }


@dataclass
class SafetyRejectionEvent:
    """Event capturing safety filter rejection."""

    timestamp: str
    strategy: str
    symbol: str
    market: str
    rejection_type: str  # "weak_trend", "bear_regime", "extreme_volatility", etc.
    reason: str
    adx: float
    mfi: float
    regime: str
    volatility_score: float

    def to_dict(self) -> dict[str, str]:
        """Convert to Redis-compatible dict (all values as strings)."""
        return {
            "timestamp": self.timestamp,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "market": self.market,
            "rejection_type": self.rejection_type,
            "reason": self.reason,
            "adx": str(self.adx),
            "mfi": str(self.mfi),
            "regime": self.regime,
            "volatility_score": str(self.volatility_score),
        }


class EventEmitter:
    """Fire-and-forget event emitter for strategy observability.

    Emits events to Redis streams for dashboard visibility.
    Designed to never block the trading loop.

    Usage:
        emitter = EventEmitter(redis=redis_streams, enabled=True)

        # Emit entry evaluation
        event = EntryEvaluationEvent(...)
        await emitter.emit_entry_evaluation(event)

        # Emit exit evaluation
        event = ExitEvaluationEvent(...)
        await emitter.emit_exit_evaluation(event)
    """

    # Stream names
    ENTRY_EVENTS_STREAM = "strategy:entry:events"
    ENTRY_FUNNEL_STREAM = "strategy:entry:funnel"
    EXIT_EVENTS_STREAM = "strategy:exit:events"
    HWM_UPDATES_STREAM = "strategy:hwm:updates"
    SAFETY_EVENTS_STREAM = "strategy:safety:events"

    def __init__(
        self,
        redis: RedisStreams | None,
        enabled: bool = False,
        maxlen: int = 2000,
    ):
        """Initialize EventEmitter.

        Args:
            redis: RedisStreams client for async operations.
            enabled: Whether event emission is enabled.
            maxlen: Maximum stream length for auto-trimming (~24h retention).
        """
        self.redis = redis
        self.enabled = enabled
        self.maxlen = maxlen

    async def emit_entry_evaluation(self, event: EntryEvaluationEvent) -> None:
        """Emit entry evaluation event (fire-and-forget).

        Args:
            event: Entry evaluation event to emit.
        """
        if not self.enabled:
            return

        await self._emit(self.ENTRY_EVENTS_STREAM, event.to_dict())

    async def emit_exit_evaluation(self, event: ExitEvaluationEvent) -> None:
        """Emit exit evaluation event (fire-and-forget).

        Args:
            event: Exit evaluation event to emit.
        """
        if not self.enabled:
            return

        await self._emit(self.EXIT_EVENTS_STREAM, event.to_dict())

    async def emit_entry_funnel(self, event: EntryFunnelEvent) -> None:
        """Emit entry funnel attribution event (fire-and-forget)."""
        if not self.enabled:
            return

        await self._emit(self.ENTRY_FUNNEL_STREAM, event.to_dict())

    async def emit_hwm_update(self, event: HWMUpdateEvent) -> None:
        """Emit HWM update event (fire-and-forget).

        Args:
            event: HWM update event to emit.
        """
        if not self.enabled:
            return

        await self._emit(self.HWM_UPDATES_STREAM, event.to_dict())

    async def emit_safety_rejection(self, event: SafetyRejectionEvent) -> None:
        """Emit safety rejection event (fire-and-forget).

        Args:
            event: Safety rejection event to emit.
        """
        if not self.enabled:
            return

        await self._emit(self.SAFETY_EVENTS_STREAM, event.to_dict())

    async def _emit(self, stream: str, data: dict[str, str]) -> None:
        """Internal emit method with error handling.

        Fire-and-forget: uses asyncio.create_task to avoid blocking trading loop.
        Logs errors but doesn't raise.

        Args:
            stream: Redis stream name.
            data: Event data dict (string values for Redis).
        """
        async def _do_emit() -> None:
            try:
                await self.redis.publish_event(stream, data, maxlen=self.maxlen)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # Fire-and-forget: log error but don't block trading
                logger.warning("Failed to emit event to %s: %s", stream, exc)

        # Schedule emission as background task - doesn't block caller
        asyncio.create_task(_do_emit())
