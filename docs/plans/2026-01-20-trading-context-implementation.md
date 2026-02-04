# TradingContext Centralization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Centralize trading decision information into a single `TradingContext` object computed once per symbol per tick, improving performance and giving all strategies (including exit) access to regime and cross-strategy position data.

**Architecture:** Create `TradingContext` dataclass containing `MarketData`, `MarketContext`, and positions map. `TradingContextBuilder` computes this once per tick with timestamp-based cache invalidation. All strategy interfaces updated to receive `TradingContext` instead of separate objects.

**Tech Stack:** Python dataclasses, Protocol typing, Redis for position lookups, existing IndicatorService for market data.

---

## Task 1: Fix Duplicate high_water_mark in MarketData

**Files:**
- Modify: `trading/strategies/components/models.py:69,77`

**Step 1: Read the file to confirm duplicate**

Run: `grep -n "high_water_mark" trading/strategies/components/models.py`
Expected: Two lines with high_water_mark definition

**Step 2: Remove duplicate field**

In `trading/strategies/components/models.py`, remove line 77 (the duplicate):
```python
# REMOVE this line (around line 77):
    high_water_mark: float | None = None
```

Keep only line 69:
```python
    high_water_mark: float | None = None  # Track HWM for trailing stops
```

**Step 3: Run tests to verify no regression**

Run: `pytest tests/trading/strategies/components/ -v --tb=short`
Expected: All tests pass

**Step 4: Commit**

```bash
git add trading/strategies/components/models.py
git commit -m "fix: remove duplicate high_water_mark field in MarketData"
```

---

## Task 2: Add TradingContext Dataclass

**Files:**
- Modify: `trading/strategies/components/models.py`
- Test: `tests/trading/strategies/components/test_trading_context.py`

**Step 1: Write the failing test**

Create `tests/trading/strategies/components/test_trading_context.py`:
```python
"""Tests for TradingContext dataclass."""

import pytest
from trading.strategies.components.models import (
    TradingContext,
    MarketData,
    MarketContext,
    Position,
    build_market_context,
)


def test_trading_context_creation():
    """TradingContext can be created with all required fields."""
    market = MarketData(
        symbol="BTC",
        close=100000.0,
        mfi=55.0,
        adx=25.0,
        rsi=60.0,
        timestamp=1000,
    )
    regime = build_market_context(mfi=55.0, adx=25.0, atr=1000.0, close=100000.0)
    positions = {
        "v35_classic_wide": Position(
            symbol="BTC",
            entry_price=99000.0,
            quantity=0.01,
            strategy="v35_classic_wide",
            market="futures",
            timestamp=900,
        )
    }

    ctx = TradingContext(
        symbol="BTC",
        timestamp=1000,
        market=market,
        regime=regime,
        positions=positions,
    )

    assert ctx.symbol == "BTC"
    assert ctx.market.close == 100000.0
    assert ctx.regime.regime == "BULL_STRONG"
    assert "v35_classic_wide" in ctx.positions


def test_trading_context_has_position():
    """TradingContext.has_position returns correct boolean."""
    market = MarketData(symbol="BTC", close=100000.0, mfi=50.0, adx=20.0, rsi=50.0, timestamp=1000)
    regime = build_market_context(mfi=50.0, adx=20.0, atr=1000.0, close=100000.0)
    positions = {"v35_classic_wide": Position(symbol="BTC", entry_price=99000.0, quantity=0.01, strategy="v35_classic_wide", market="futures", timestamp=900)}

    ctx = TradingContext(symbol="BTC", timestamp=1000, market=market, regime=regime, positions=positions)

    assert ctx.has_position("v35_classic_wide") is True
    assert ctx.has_position("short_v1") is False


def test_trading_context_get_position():
    """TradingContext.get_position returns position or None."""
    market = MarketData(symbol="BTC", close=100000.0, mfi=50.0, adx=20.0, rsi=50.0, timestamp=1000)
    regime = build_market_context(mfi=50.0, adx=20.0, atr=1000.0, close=100000.0)
    pos = Position(symbol="BTC", entry_price=99000.0, quantity=0.01, strategy="v35_classic_wide", market="futures", timestamp=900)
    positions = {"v35_classic_wide": pos}

    ctx = TradingContext(symbol="BTC", timestamp=1000, market=market, regime=regime, positions=positions)

    assert ctx.get_position("v35_classic_wide") == pos
    assert ctx.get_position("nonexistent") is None


def test_trading_context_other_strategies_positioned():
    """TradingContext.other_strategies_positioned excludes specified strategy."""
    market = MarketData(symbol="BTC", close=100000.0, mfi=50.0, adx=20.0, rsi=50.0, timestamp=1000)
    regime = build_market_context(mfi=50.0, adx=20.0, atr=1000.0, close=100000.0)
    positions = {
        "v35_classic_wide": Position(symbol="BTC", entry_price=99000.0, quantity=0.01, strategy="v35_classic_wide", market="futures", timestamp=900),
        "sideways": Position(symbol="BTC", entry_price=98000.0, quantity=0.02, strategy="sideways", market="futures", timestamp=800),
    }

    ctx = TradingContext(symbol="BTC", timestamp=1000, market=market, regime=regime, positions=positions)

    others = ctx.other_strategies_positioned("v35_classic_wide")
    assert "sideways" in others
    assert "v35_classic_wide" not in others


def test_trading_context_immutable():
    """TradingContext is immutable (frozen dataclass)."""
    market = MarketData(symbol="BTC", close=100000.0, mfi=50.0, adx=20.0, rsi=50.0, timestamp=1000)
    regime = build_market_context(mfi=50.0, adx=20.0, atr=1000.0, close=100000.0)

    ctx = TradingContext(symbol="BTC", timestamp=1000, market=market, regime=regime, positions={})

    with pytest.raises(Exception):  # FrozenInstanceError or dataclasses.FrozenInstanceError
        ctx.symbol = "ETH"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/trading/strategies/components/test_trading_context.py -v`
Expected: FAIL with "cannot import name 'TradingContext'"

**Step 3: Add TradingContext to models.py**

Add after the `Position` class (around line 305) in `trading/strategies/components/models.py`:

```python
@dataclass(frozen=True)
class TradingContext:
    """Centralized trading decision context.

    Computed once per symbol per tick, shared across all strategies.
    Contains market data, regime analysis, and cross-strategy position info.
    """

    symbol: str
    timestamp: int  # Unix ms

    # Market data (indicators computed once)
    market: MarketData

    # Pre-analyzed regime (computed once)
    regime: MarketContext

    # All open positions for this symbol across strategies
    # Key: strategy_name, Value: Position
    positions: dict[str, Position]

    def has_position(self, strategy: str) -> bool:
        """Check if a strategy has an open position."""
        return strategy in self.positions

    def get_position(self, strategy: str) -> Position | None:
        """Get position for a strategy, or None if not positioned."""
        return self.positions.get(strategy)

    def other_strategies_positioned(self, exclude: str) -> list[str]:
        """Get strategy names holding positions, excluding specified strategy."""
        return [s for s in self.positions if s != exclude]
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/trading/strategies/components/test_trading_context.py -v`
Expected: All 5 tests pass

**Step 5: Commit**

```bash
git add trading/strategies/components/models.py tests/trading/strategies/components/test_trading_context.py
git commit -m "feat: add TradingContext dataclass for centralized decision info"
```

---

## Task 3: Update Strategy Interfaces

**Files:**
- Modify: `trading/strategies/components/interfaces.py`
- Test: `tests/trading/strategies/components/test_interfaces.py`

**Step 1: Write the failing test**

Create `tests/trading/strategies/components/test_interfaces.py`:
```python
"""Tests for updated strategy interfaces."""

from typing import Protocol, runtime_checkable
from trading.strategies.components.interfaces import IEntryStrategy, IExitStrategy
from trading.strategies.components.models import TradingContext, MarketData, MarketContext, Position, Signal, build_market_context


def test_entry_strategy_protocol_signature():
    """IEntryStrategy.check_entry accepts TradingContext."""

    class MockEntry:
        def check_entry(self, ctx: TradingContext) -> Signal | None:
            return None

    # Should not raise - MockEntry implements IEntryStrategy
    entry: IEntryStrategy = MockEntry()
    assert entry is not None


def test_exit_strategy_protocol_signature():
    """IExitStrategy.check_exit accepts TradingContext and Position."""

    class MockExit:
        def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
            return None

        def on_position_opened(self, position: Position) -> None:
            pass

        def on_position_closed(self, symbol: str) -> None:
            pass

    # Should not raise - MockExit implements IExitStrategy
    exit_strat: IExitStrategy = MockExit()
    assert exit_strat is not None
```

**Step 2: Run test to verify current state**

Run: `pytest tests/trading/strategies/components/test_interfaces.py -v`
Expected: Tests may fail due to signature mismatch

**Step 3: Update interfaces.py**

Replace the entire content of `trading/strategies/components/interfaces.py`:

```python
"""Strategy component interfaces using Protocol for structural subtyping.

These protocols define the contracts for entry and exit strategy components.
Implementations don't need to inherit - they just need to implement the methods
(duck typing via typing.Protocol).
"""

from typing import Protocol

from .models import MarketContext, MarketData, Position, Signal, TradingContext


class IEntryStrategy(Protocol):
    """Interface for entry logic only.

    Entry strategies analyze market conditions and decide when to open
    a position. They are stateless and don't track open positions.
    """

    def check_entry(
        self,
        ctx: TradingContext,
    ) -> Signal | None:
        """Analyze market conditions and return entry signal.

        Args:
            ctx: Complete trading context containing:
                - market: MarketData with indicators
                - regime: MarketContext with trend/volatility analysis
                - positions: Cross-strategy position info

        Returns:
            Signal with side="buy" for long, side="sell" for short
            None if no entry conditions met
        """
        ...


class IExitStrategy(Protocol):
    """Interface for exit logic only.

    Exit strategies manage open positions and decide when to close them.
    They may be stateful (e.g., tracking high water mark for trailing stops).
    """

    def check_exit(
        self,
        ctx: TradingContext,
        position: Position,
    ) -> Signal | None:
        """Evaluate exit conditions for existing position.

        Args:
            ctx: Complete trading context (now includes regime!)
            position: This strategy's open position

        Returns:
            Signal to close position, or None to hold
        """
        ...

    def on_position_opened(self, position: Position) -> None:
        """Called when a new position is opened.

        Use this to initialize state (e.g., set initial high water mark).

        Args:
            position: The newly opened position
        """
        ...

    def on_position_closed(self, symbol: str) -> None:
        """Called when position is closed.

        Use this to clean up state (e.g., reset high water mark).

        Args:
            symbol: The symbol whose position was closed
        """
        ...
```

**Step 4: Run interface tests**

Run: `pytest tests/trading/strategies/components/test_interfaces.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add trading/strategies/components/interfaces.py tests/trading/strategies/components/test_interfaces.py
git commit -m "feat: update strategy interfaces to use TradingContext"
```

---

## Task 4: Create TradingContextBuilder

**Files:**
- Create: `trading/strategies/components/context_builder.py`
- Test: `tests/trading/strategies/components/test_context_builder.py`

**Step 1: Write the failing test**

Create `tests/trading/strategies/components/test_context_builder.py`:
```python
"""Tests for TradingContextBuilder."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from trading.strategies.components.context_builder import TradingContextBuilder
from trading.strategies.components.models import MarketData, Position


@pytest.fixture
def mock_indicator_service():
    """Create mock IndicatorService."""
    service = MagicMock()
    service.get_market_data.return_value = MarketData(
        symbol="BTC",
        close=100000.0,
        mfi=55.0,
        adx=25.0,
        rsi=60.0,
        timestamp=1000,
        atr=1000.0,
        volume=100.0,
        avg_volume_20=80.0,
    )
    return service


@pytest.fixture
def mock_position_manager():
    """Create mock PositionManager."""
    manager = MagicMock()
    manager.get_positions_for_symbol.return_value = {
        "v35_classic_wide": Position(
            symbol="BTC",
            entry_price=99000.0,
            quantity=0.01,
            strategy="v35_classic_wide",
            market="futures",
            timestamp=900,
        )
    }
    return manager


def test_builder_creates_context(mock_indicator_service, mock_position_manager):
    """TradingContextBuilder creates TradingContext with all components."""
    builder = TradingContextBuilder(
        indicator_service=mock_indicator_service,
        position_manager=mock_position_manager,
    )

    ctx = builder.get_context("BTC", timestamp=1000)

    assert ctx.symbol == "BTC"
    assert ctx.timestamp == 1000
    assert ctx.market.close == 100000.0
    assert ctx.regime.regime == "BULL_STRONG"
    assert ctx.has_position("v35_classic_wide")


def test_builder_caches_same_tick(mock_indicator_service, mock_position_manager):
    """TradingContextBuilder caches context for same timestamp."""
    builder = TradingContextBuilder(
        indicator_service=mock_indicator_service,
        position_manager=mock_position_manager,
    )

    ctx1 = builder.get_context("BTC", timestamp=1000)
    ctx2 = builder.get_context("BTC", timestamp=1000)

    assert ctx1 is ctx2  # Same object returned
    assert mock_indicator_service.get_market_data.call_count == 1  # Only called once


def test_builder_invalidates_on_new_tick(mock_indicator_service, mock_position_manager):
    """TradingContextBuilder invalidates cache on new timestamp."""
    builder = TradingContextBuilder(
        indicator_service=mock_indicator_service,
        position_manager=mock_position_manager,
    )

    ctx1 = builder.get_context("BTC", timestamp=1000)
    ctx2 = builder.get_context("BTC", timestamp=2000)

    assert ctx1 is not ctx2  # Different objects
    assert mock_indicator_service.get_market_data.call_count == 2  # Called twice


def test_builder_handles_no_market_data(mock_position_manager):
    """TradingContextBuilder returns None when no market data available."""
    service = MagicMock()
    service.get_market_data.return_value = None

    builder = TradingContextBuilder(
        indicator_service=service,
        position_manager=mock_position_manager,
    )

    ctx = builder.get_context("BTC", timestamp=1000)

    assert ctx is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/trading/strategies/components/test_context_builder.py -v`
Expected: FAIL with "cannot import name 'TradingContextBuilder'"

**Step 3: Create context_builder.py**

Create `trading/strategies/components/context_builder.py`:
```python
"""TradingContext builder for centralized context construction.

This module provides the TradingContextBuilder class that builds
TradingContext objects once per symbol per tick, caching results
to avoid redundant computation across multiple strategies.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .models import TradingContext, build_market_context

if TYPE_CHECKING:
    from trading.indicators.indicator_service import IndicatorService

logger = logging.getLogger(__name__)


class PositionManager:
    """Manages position lookups from Redis.

    Provides a clean interface for retrieving positions across strategies.
    """

    def __init__(self, redis_client):
        """Initialize with Redis client.

        Args:
            redis_client: Async Redis client instance.
        """
        self._redis = redis_client

    def get_positions_for_symbol(self, symbol: str) -> dict:
        """Get all positions for a symbol across strategies.

        Note: This is a synchronous method that uses cached position data.
        Position data is updated asynchronously by the executor.

        Args:
            symbol: Trading symbol (BTC, ETH, SOL).

        Returns:
            Dict mapping strategy_name -> Position for this symbol.
        """
        # Import here to avoid circular dependency
        from .models import Position

        positions = {}

        # Position key pattern: positions:{symbol}:futures
        # Value is a hash with strategy as the grouping
        # For now, we return empty - will be populated by CompositeStrategyTask
        # which already has position access via Redis

        return positions


class TradingContextBuilder:
    """Builds TradingContext once per symbol per tick.

    Caches results by timestamp to avoid redundant computation when
    multiple strategies request context for the same symbol.

    Usage:
        builder = TradingContextBuilder(indicator_service, position_manager)

        # In strategy evaluation loop:
        ctx = builder.get_context("BTC", timestamp=current_timestamp)
        # ctx is cached - subsequent calls with same timestamp return same object
    """

    def __init__(
        self,
        indicator_service: IndicatorService,
        position_manager: PositionManager | None = None,
    ):
        """Initialize context builder.

        Args:
            indicator_service: Shared indicator calculation service.
            position_manager: Optional position manager for cross-strategy awareness.
        """
        self._indicators = indicator_service
        self._positions = position_manager

        # Cache: symbol -> TradingContext
        self._cache: dict[str, TradingContext] = {}
        self._cache_timestamp: int = 0

        logger.info("TradingContextBuilder initialized")

    def get_context(self, symbol: str, timestamp: int) -> TradingContext | None:
        """Get or build context for symbol.

        Cache invalidates when timestamp changes (new tick).

        Args:
            symbol: Trading symbol (BTC, ETH, SOL).
            timestamp: Current tick timestamp in milliseconds.

        Returns:
            TradingContext with market data, regime, and positions.
            None if market data unavailable.
        """
        # Invalidate cache on new tick
        if timestamp != self._cache_timestamp:
            self._cache.clear()
            self._cache_timestamp = timestamp

        # Return cached context if available
        if symbol in self._cache:
            return self._cache[symbol]

        # Build new context
        ctx = self._build(symbol, timestamp)

        if ctx is not None:
            self._cache[symbol] = ctx

        return ctx

    def _build(self, symbol: str, timestamp: int) -> TradingContext | None:
        """Build TradingContext from components.

        Args:
            symbol: Trading symbol.
            timestamp: Current timestamp.

        Returns:
            TradingContext or None if market data unavailable.
        """
        # 1. Get market data from IndicatorService (already cached)
        market_data = self._indicators.get_market_data(symbol)
        if market_data is None:
            logger.debug(f"TradingContextBuilder: No market data for {symbol}")
            return None

        # 2. Build regime context (computed once here)
        regime = build_market_context(
            mfi=market_data.mfi,
            adx=market_data.adx,
            atr=market_data.atr,
            close=market_data.close,
            volume=market_data.volume,
            avg_volume=market_data.avg_volume_20,
        )

        # 3. Get positions for cross-strategy awareness
        positions = {}
        if self._positions is not None:
            positions = self._positions.get_positions_for_symbol(symbol)

        return TradingContext(
            symbol=symbol,
            timestamp=timestamp,
            market=market_data,
            regime=regime,
            positions=positions,
        )

    def invalidate(self, symbol: str | None = None) -> None:
        """Invalidate cache for a symbol or all symbols.

        Args:
            symbol: Symbol to invalidate, or None for all.
        """
        if symbol:
            self._cache.pop(symbol, None)
        else:
            self._cache.clear()

    def update_position(self, symbol: str, strategy: str, position) -> None:
        """Update position in cache for cross-strategy awareness.

        Called by CompositeStrategyTask when positions change.

        Args:
            symbol: Trading symbol.
            strategy: Strategy name.
            position: Position object or None to remove.
        """
        if symbol in self._cache:
            ctx = self._cache[symbol]
            # Create new positions dict (immutable update)
            new_positions = dict(ctx.positions)
            if position is None:
                new_positions.pop(strategy, None)
            else:
                new_positions[strategy] = position

            # Create new context with updated positions
            from dataclasses import replace
            self._cache[symbol] = replace(ctx, positions=new_positions)
```

**Step 4: Run tests**

Run: `pytest tests/trading/strategies/components/test_context_builder.py -v`
Expected: All 4 tests pass

**Step 5: Commit**

```bash
git add trading/strategies/components/context_builder.py tests/trading/strategies/components/test_context_builder.py
git commit -m "feat: add TradingContextBuilder for centralized context construction"
```

---

## Task 5: Update V35EntryStrategy

**Files:**
- Modify: `trading/strategies/components/v35_entry.py`
- Test: `tests/trading/strategies/components/test_v35_entry.py`

**Step 1: Write test for new interface**

Create `tests/trading/strategies/components/test_v35_entry.py`:
```python
"""Tests for V35EntryStrategy with TradingContext."""

import pytest
from trading.strategies.components.v35_entry import V35EntryStrategy, V35EntryParams
from trading.strategies.components.models import (
    TradingContext, MarketData, MarketContext, Position, build_market_context
)


def _make_context(
    mfi: float = 55.0,
    adx: float = 25.0,
    rsi: float = 60.0,
    macd: float = 10.0,
    macd_signal: float = 5.0,
    close: float = 100000.0,
) -> TradingContext:
    """Helper to create TradingContext for tests."""
    market = MarketData(
        symbol="BTC",
        close=close,
        mfi=mfi,
        adx=adx,
        rsi=rsi,
        timestamp=1000,
        macd=macd,
        macd_signal=macd_signal,
        atr=1000.0,
        volume=100.0,
        avg_volume_20=80.0,
    )
    regime = build_market_context(mfi=mfi, adx=adx, atr=1000.0, close=close)
    return TradingContext(symbol="BTC", timestamp=1000, market=market, regime=regime, positions={})


def test_v35_entry_bull_strong_signal():
    """V35 entry generates signal in BULL_STRONG with MACD crossover."""
    strategy = V35EntryStrategy()
    ctx = _make_context(mfi=55.0, adx=26.0, rsi=58.0, macd=10.0, macd_signal=5.0)

    signal = strategy.check_entry(ctx)

    assert signal is not None
    assert signal.side == "buy"
    assert "MOMENTUM" in signal.reason


def test_v35_entry_no_signal_bear_regime():
    """V35 entry returns None in BEAR regime."""
    strategy = V35EntryStrategy()
    ctx = _make_context(mfi=30.0, adx=26.0)  # BEAR_STRONG

    signal = strategy.check_entry(ctx)

    assert signal is None


def test_v35_entry_no_signal_weak_adx():
    """V35 entry returns None when ADX is weak."""
    strategy = V35EntryStrategy()
    ctx = _make_context(mfi=55.0, adx=15.0)  # Weak ADX

    signal = strategy.check_entry(ctx)

    assert signal is None
```

**Step 2: Run test to see current state**

Run: `pytest tests/trading/strategies/components/test_v35_entry.py -v`
Expected: FAIL due to interface mismatch

**Step 3: Update V35EntryStrategy**

In `trading/strategies/components/v35_entry.py`, update the `check_entry` method signature and access patterns:

```python
# Change import at top
from .models import MarketContext, MarketData, Signal, BEAR_REGIMES, TradingContext

# Update check_entry method (around line 87)
def check_entry(
    self,
    ctx: TradingContext,
) -> Signal | None:
    """Check entry conditions and return signal if entry criteria met.

    Routes to different entry strategies based on market regime:
    - BULL: Momentum entry (MACD + RSI)
    - SIDEWAYS_UP: Breakout entry
    - SIDEWAYS_FLAT/DOWN: Range entry

    Safety filters (Binance Futures):
    - Skip if ADX < threshold (avoid whipsaws in weak trends)
    - Skip if regime is BEAR (don't catch falling knives)
    - Skip if extreme volatility (avoid wild swings)

    Args:
        ctx: Trading context with market data, regime, and positions.

    Returns:
        Signal with side="buy" if entry conditions met, None otherwise.
    """
    market_data = ctx.market
    context = ctx.regime

    # === SAFETY FILTER 1: Weak trend (ADX) ===
    if context.adx < self.params.adx_moderate_trend:
        logger.debug(
            f"{market_data.symbol}: Skipping long entry - weak trend "
            f"(ADX={context.adx:.1f} < {self.params.adx_moderate_trend})"
        )
        return None

    # === SAFETY FILTER 2: BEAR regime ===
    if context.regime in BEAR_REGIMES:
        logger.debug(
            f"{market_data.symbol}: Skipping long entry - BEAR regime "
            f"({context.regime})"
        )
        return None

    # === SAFETY FILTER 3: Extreme volatility ===
    if context.is_extreme_volatility:
        logger.debug(
            f"{market_data.symbol}: Skipping entry - extreme volatility "
            f"({context.volatility_score*100:.2f}%)"
        )
        return None

    # Use centralized regime from MarketContext
    regime = context.regime

    # Route to appropriate entry strategy based on regime
    signal_data = None

    if regime == "BULL_STRONG":
        signal_data = self._momentum_entry(market_data, aggressive=True)
    elif regime == "BULL_MODERATE":
        signal_data = self._momentum_entry(market_data, aggressive=False)
    elif regime == "SIDEWAYS_UP":
        signal_data = self._breakout_entry(market_data)
    elif regime in ("SIDEWAYS_FLAT", "SIDEWAYS_DOWN"):
        signal_data = self._range_entry(market_data)
    elif regime in ("BEAR_MODERATE", "BEAR_STRONG"):
        signal_data = self._conservative_entry(market_data)

    if signal_data:
        reason = (
            f"V35 {signal_data['strategy']}: {regime}, "
            f"MFI={market_data.mfi:.1f}, ADX={market_data.adx:.1f}, "
            f"RSI={market_data.rsi:.1f}"
        )
        logger.info(f"{market_data.symbol}: {reason}")

        return Signal(
            symbol=market_data.symbol,
            side="buy",
            market=self.params.market,
            quantity=signal_data['quantity'],
            reason=reason,
        )

    return None
```

**Step 4: Run tests**

Run: `pytest tests/trading/strategies/components/test_v35_entry.py -v`
Expected: All tests pass

**Step 5: Commit**

```bash
git add trading/strategies/components/v35_entry.py tests/trading/strategies/components/test_v35_entry.py
git commit -m "refactor: update V35EntryStrategy to use TradingContext"
```

---

## Task 6: Update V35TrailingExitStrategy

**Files:**
- Modify: `trading/strategies/components/v35_trailing_exit.py`
- Test: `tests/trading/strategies/components/test_v35_exit.py`

**Step 1: Write test for new interface**

Create `tests/trading/strategies/components/test_v35_exit.py`:
```python
"""Tests for V35TrailingExitStrategy with TradingContext."""

import pytest
from trading.strategies.components.v35_trailing_exit import V35TrailingExitStrategy, V35ExitParams
from trading.strategies.components.models import (
    TradingContext, MarketData, Position, build_market_context
)


def _make_context(close: float = 100000.0, mfi: float = 50.0, adx: float = 20.0) -> TradingContext:
    """Helper to create TradingContext for tests."""
    market = MarketData(
        symbol="BTC", close=close, mfi=mfi, adx=adx, rsi=50.0, timestamp=1000,
        high=close, low=close * 0.99, macd=0.0, macd_signal=0.0, atr=1000.0,
    )
    regime = build_market_context(mfi=mfi, adx=adx, atr=1000.0, close=close)
    return TradingContext(symbol="BTC", timestamp=1000, market=market, regime=regime, positions={})


def _make_position(entry_price: float = 100000.0, quantity: float = 0.01) -> Position:
    """Helper to create Position for tests."""
    return Position(
        symbol="BTC", entry_price=entry_price, quantity=quantity,
        strategy="v35_classic_wide", market="futures", timestamp=900,
    )


def test_v35_exit_stop_loss():
    """V35 exit triggers on stop loss."""
    strategy = V35TrailingExitStrategy(params=V35ExitParams(stop_loss_pct=2.0))
    position = _make_position(entry_price=100000.0)
    ctx = _make_context(close=97000.0)  # -3% loss

    strategy.on_position_opened(position)
    signal = strategy.check_exit(ctx, position)

    assert signal is not None
    assert signal.side == "sell"
    assert "Stop loss" in signal.reason


def test_v35_exit_hold():
    """V35 exit holds when no exit conditions met."""
    strategy = V35TrailingExitStrategy()
    position = _make_position(entry_price=100000.0)
    ctx = _make_context(close=100500.0)  # Small profit

    strategy.on_position_opened(position)
    signal = strategy.check_exit(ctx, position)

    assert signal is None


def test_v35_exit_has_regime_access():
    """V35 exit can access regime from context."""
    strategy = V35TrailingExitStrategy()
    position = _make_position()
    ctx = _make_context(mfi=55.0, adx=26.0)  # BULL_STRONG regime

    strategy.on_position_opened(position)

    # Exit strategy can now see regime
    assert ctx.regime.regime == "BULL_STRONG"
```

**Step 2: Run test**

Run: `pytest tests/trading/strategies/components/test_v35_exit.py -v`
Expected: FAIL due to interface mismatch

**Step 3: Update V35TrailingExitStrategy**

In `trading/strategies/components/v35_trailing_exit.py`:

```python
# Update import at top
from .models import MarketData, Position, Signal, TradingContext

# Update check_exit signature (around line 111)
def check_exit(
    self,
    ctx: TradingContext,
    position: Position,
) -> Signal | None:
    """Evaluate exit conditions for position.

    Args:
        ctx: Trading context with market data and regime.
        position: Current open position.

    Returns:
        Signal to close position (full or partial), or None to hold.
    """
    market_data = ctx.market

    symbol = position.symbol
    entry_price = position.entry_price
    quantity = position.quantity
    current_price = market_data.close

    # ... rest of method unchanged, uses market_data instead of the old parameter
```

**Step 4: Run tests**

Run: `pytest tests/trading/strategies/components/test_v35_exit.py -v`
Expected: All tests pass

**Step 5: Commit**

```bash
git add trading/strategies/components/v35_trailing_exit.py tests/trading/strategies/components/test_v35_exit.py
git commit -m "refactor: update V35TrailingExitStrategy to use TradingContext"
```

---

## Task 7: Update Remaining Entry Strategies

**Files:**
- Modify: `trading/strategies/components/short_entry.py`
- Modify: `trading/strategies/components/sideways_entry.py`

**Step 1: Update ShortEntryStrategy**

In `trading/strategies/components/short_entry.py`, update imports and `check_entry`:

```python
# Add TradingContext to imports
from .models import (
    MarketContext,
    MarketData,
    Signal,
    TradingContext,
    BULLISH_NO_SHORT_REGIMES,
    SIDEWAYS_VOLATILE_REGIMES,
    BEAR_REGIMES,
)

# Update check_entry signature
def check_entry(
    self,
    ctx: TradingContext,
) -> Signal | None:
    """Check entry conditions for short position."""
    market_data = ctx.market
    context = ctx.regime
    # ... rest uses market_data and context as before
```

**Step 2: Update SidewaysEntryStrategy**

In `trading/strategies/components/sideways_entry.py`, same pattern:

```python
# Add TradingContext to imports
from .models import MarketContext, MarketData, Signal, TradingContext, SIDEWAYS_REGIMES

# Update check_entry signature
def check_entry(
    self,
    ctx: TradingContext,
) -> Signal | None:
    """Check entry conditions for sideways/range entry."""
    market_data = ctx.market
    context = ctx.regime
    # ... rest unchanged
```

**Step 3: Run existing tests**

Run: `pytest tests/trading/strategies/components/ -v --tb=short`
Expected: Pass (after updating any existing tests)

**Step 4: Commit**

```bash
git add trading/strategies/components/short_entry.py trading/strategies/components/sideways_entry.py
git commit -m "refactor: update ShortEntry and SidewaysEntry to use TradingContext"
```

---

## Task 8: Update Remaining Exit Strategies

**Files:**
- Modify: `trading/strategies/components/short_exit.py`
- Modify: `trading/strategies/components/sideways_exit.py`
- Modify: `trading/strategies/components/experimental_exit.py`
- Modify: `trading/strategies/components/v35_persistent_exit.py`

**Step 1: Update ShortExitStrategy**

In `trading/strategies/components/short_exit.py`:

```python
# Add TradingContext to imports
from .models import MarketData, Position, Signal, TradingContext

# Update check_exit signature
def check_exit(
    self,
    ctx: TradingContext,
    position: Position,
) -> Signal | None:
    """Check exit conditions for short position."""
    market_data = ctx.market
    # ... rest uses market_data
```

**Step 2: Update SidewaysExitStrategy**

In `trading/strategies/components/sideways_exit.py`:

```python
# Add TradingContext to imports
from .models import MarketData, Position, Signal, TradingContext

# Update check_exit signature
def check_exit(
    self,
    ctx: TradingContext,
    position: Position,
) -> Signal | None:
    """Check exit conditions for sideways position."""
    market_data = ctx.market
    # ... rest uses market_data
```

**Step 3: Update ExperimentalExitStrategy**

`experimental_exit.py` inherits from `V35TrailingExitStrategy`, so it inherits the updated interface automatically. No changes needed if parent is updated.

**Step 4: Update V35PersistentExitStrategy**

In `trading/strategies/components/v35_persistent_exit.py`:

```python
# Add TradingContext to imports
from .models import MarketData, Position, Signal, TradingContext

# Update check_exit signature (async method)
async def check_exit(
    self,
    ctx: TradingContext,
    position: Position,
) -> Signal | None:
    """Check exit conditions with persistent state."""
    market_data = ctx.market
    # ... rest uses market_data
```

**Step 5: Run all strategy tests**

Run: `pytest tests/trading/strategies/components/ -v --tb=short`
Expected: All pass

**Step 6: Commit**

```bash
git add trading/strategies/components/short_exit.py trading/strategies/components/sideways_exit.py trading/strategies/components/experimental_exit.py trading/strategies/components/v35_persistent_exit.py
git commit -m "refactor: update remaining exit strategies to use TradingContext"
```

---

## Task 9: Update CompositeStrategyTask

**Files:**
- Modify: `trading/strategies/components/composite_task.py`

**Step 1: Update imports and add context_builder**

Add to imports:
```python
from .context_builder import TradingContextBuilder
```

**Step 2: Update __init__ to accept context_builder**

Add parameter and store:
```python
def __init__(
    self,
    name: str,
    symbols: list[str],
    redis: RedisStreams,
    entry_strategy: IEntryStrategy,
    exit_strategy: IExitStrategy,
    market: str = "futures",
    buffer_size: int = 500,
    use_smart_exit: bool = False,
    config: dict | None = None,
    emit_events: bool = False,
    indicator_service: IndicatorService | None = None,
    context_builder: TradingContextBuilder | None = None,  # NEW
):
    # ... existing init code ...
    self.context_builder = context_builder
```

**Step 3: Update evaluate method**

```python
async def evaluate(self, symbol: str) -> dict[str, Any] | None:
    """Evaluate entry conditions using TradingContext."""
    buffer = self.price_buffer.get(symbol, [])
    if len(buffer) < self.min_data_points:
        return None

    # Get timestamp from buffer
    timestamp = int(buffer[-1].get("timestamp", 0)) if buffer else 0

    # Use context builder if available
    if self.context_builder:
        ctx = self.context_builder.get_context(symbol, timestamp)
        if ctx is None:
            return None

        # Record decision
        await self._check_and_record_decision(symbol, ctx.market, ctx.regime)

        # Delegate to entry component with TradingContext
        signal = self.entry_strategy.check_entry(ctx)

        # Emit entry evaluation event
        await self._emit_entry_evaluation(ctx.market, ctx.regime, signal)
    else:
        # Fallback to old behavior (for backwards compatibility during migration)
        market_data = self._build_market_data(symbol)
        if market_data is None:
            return None
        context = self._build_market_context(market_data)
        await self._check_and_record_decision(symbol, market_data, context)

        # Create temporary TradingContext for new interface
        from .models import TradingContext
        ctx = TradingContext(
            symbol=symbol,
            timestamp=timestamp,
            market=market_data,
            regime=context,
            positions={},
        )
        signal = self.entry_strategy.check_entry(ctx)
        await self._emit_entry_evaluation(market_data, context, signal)

    if signal:
        quantity = await self._get_quantity(symbol, ctx.market.close, signal.quantity)
        return self._signal_to_dict(signal, quantity)

    return None
```

**Step 4: Update evaluate_exit method**

```python
async def evaluate_exit(self, symbol: str, position_dict: dict) -> dict[str, Any] | None:
    """Evaluate exit conditions using TradingContext."""
    buffer = self.price_buffer.get(symbol, [])
    timestamp = int(buffer[-1].get("timestamp", 0)) if buffer else 0

    position = self._dict_to_position(position_dict)

    if self.context_builder:
        ctx = self.context_builder.get_context(symbol, timestamp)
        if ctx is None:
            return None

        await self._check_and_record_decision(symbol, ctx.market)

        # Handle both sync and async exit strategies
        check_exit_method = self.exit_strategy.check_exit
        if asyncio.iscoroutinefunction(check_exit_method):
            signal = await check_exit_method(ctx, position)
        else:
            signal = check_exit_method(ctx, position)

        await self._emit_exit_evaluation(position, ctx.market, signal)
    else:
        # Fallback
        market_data = self._build_market_data(symbol)
        if market_data is None:
            return None
        await self._check_and_record_decision(symbol, market_data)

        context = self._build_market_context(market_data)
        from .models import TradingContext
        ctx = TradingContext(symbol=symbol, timestamp=timestamp, market=market_data, regime=context, positions={})

        check_exit_method = self.exit_strategy.check_exit
        if asyncio.iscoroutinefunction(check_exit_method):
            signal = await check_exit_method(ctx, position)
        else:
            signal = check_exit_method(ctx, position)

        await self._emit_exit_evaluation(position, market_data, signal)

    if signal:
        return self._signal_to_dict(signal, signal.quantity)

    return None
```

**Step 5: Run composite task tests**

Run: `pytest tests/trading/strategies/components/test_composite_task_events.py -v`
Expected: Pass (may need test updates)

**Step 6: Commit**

```bash
git add trading/strategies/components/composite_task.py
git commit -m "refactor: update CompositeStrategyTask to use TradingContextBuilder"
```

---

## Task 10: Update Engine Integration

**Files:**
- Modify: `trading/engine.py`

**Step 1: Update _start_component_strategies**

In `trading/engine.py`, update the strategy creation to use TradingContextBuilder:

```python
from trading.strategies.components.context_builder import TradingContextBuilder, PositionManager

async def _start_component_strategies(
    self,
    symbols: list[str],
    strategy_config: dict,
    mode: str,
) -> None:
    """Start strategies using the component-based architecture."""
    factory = StrategyFactory(redis=self.redis._client)
    use_persistence = mode == "live"

    # Create shared IndicatorService
    indicator_cache_ttl = self.config.get("indicator_cache_ttl", 60)
    indicator_service = IndicatorService(cache_ttl=indicator_cache_ttl)
    logger.info(f"Created shared IndicatorService (cache_ttl={indicator_cache_ttl}s)")

    # Create shared TradingContextBuilder
    position_manager = PositionManager(self.redis._client)
    context_builder = TradingContextBuilder(
        indicator_service=indicator_service,
        position_manager=position_manager,
    )
    logger.info("Created shared TradingContextBuilder")

    # ... rest of method, pass context_builder to create_composite_task
    task = await create_composite_task(
        name=name,
        symbols=symbols,
        redis=self.redis,
        entry_strategy=entry,
        exit_strategy=exit_strat,
        market=market,
        config=config,
        use_smart_exit=use_smart_exit,
        indicator_service=indicator_service,
        context_builder=context_builder,  # NEW
    )
```

**Step 2: Update create_composite_task function**

In `trading/strategies/components/composite_task.py`, add context_builder parameter:

```python
async def create_composite_task(
    name: str,
    symbols: list[str],
    redis: RedisStreams,
    entry_strategy: IEntryStrategy,
    exit_strategy: IExitStrategy,
    config: dict | None = None,
    market: str = "futures",
    use_smart_exit: bool = False,
    indicator_service: IndicatorService | None = None,
    context_builder: TradingContextBuilder | None = None,
) -> CompositeStrategyTask:
    """Create a CompositeStrategyTask."""
    task = CompositeStrategyTask(
        name=name,
        symbols=symbols,
        redis=redis,
        entry_strategy=entry_strategy,
        exit_strategy=exit_strategy,
        market=market,
        config=config,
        use_smart_exit=use_smart_exit,
        indicator_service=indicator_service,
        context_builder=context_builder,
    )
    # ... rest unchanged
```

**Step 3: Run integration tests**

Run: `pytest tests/ -k "engine" -v --tb=short`
Expected: Pass

**Step 4: Commit**

```bash
git add trading/engine.py trading/strategies/components/composite_task.py
git commit -m "feat: wire TradingContextBuilder into Engine"
```

---

## Task 11: Update ComponentStrategyAdapter (Backtester)

**Files:**
- Modify: `core/component_adapter.py`

**Step 1: Update adapter to use TradingContext**

```python
# Update imports
from trading.strategies.components.models import MarketData, Position, Signal, MarketContext, TradingContext, build_market_context

# Update __call__ method
def __call__(self, df: pd.DataFrame, i: int, params: Dict = None) -> Dict[str, Any]:
    """Callable interface for Backtester.run(strategy_func)."""
    row = df.iloc[i]

    # ... existing indicator extraction ...

    # Build MarketData (same as before)
    market_data = MarketData(...)

    # Build MarketContext
    context = build_market_context(...)

    # Create TradingContext
    positions = {}
    if self.current_position:
        positions[self.strategy_name] = self.current_position

    ctx = TradingContext(
        symbol=self.symbol,
        timestamp=ts,
        market=market_data,
        regime=context,
        positions=positions,
    )

    # Check exits
    if self.current_position:
        # Update HWM...
        market_data = replace(market_data, high_water_mark=self.high_water_mark)
        ctx = TradingContext(symbol=self.symbol, timestamp=ts, market=market_data, regime=context, positions=positions)

        signal = self.exit_strategy.check_exit(ctx, self.current_position)
        # ... rest of exit handling

    # Check entries
    else:
        signal = self.entry_strategy.check_entry(ctx)
        # ... rest of entry handling
```

**Step 2: Run backtester tests**

Run: `pytest tests/ -k "adapter or backtest" -v --tb=short`
Expected: Pass

**Step 3: Commit**

```bash
git add core/component_adapter.py
git commit -m "refactor: update ComponentStrategyAdapter to use TradingContext"
```

---

## Task 12: Remove Dead Code

**Files:**
- Modify: `trading/strategies/components/composite_task.py`

**Step 1: Remove unused caches and fallback paths**

After verifying all tests pass with TradingContextBuilder, remove:
- `_context_cache` field (unused)
- `_market_data_cache` field (replaced by builder cache)
- Fallback code paths in evaluate/evaluate_exit

**Step 2: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All pass

**Step 3: Commit**

```bash
git add trading/strategies/components/composite_task.py
git commit -m "chore: remove dead code after TradingContext migration"
```

---

## Task 13: Final Integration Test

**Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass

**Step 2: Manual smoke test**

Run: `python run.py --trend paper` (brief test)
Expected: Bot starts, connects to Redis, strategies evaluate without errors

**Step 3: Commit any final fixes**

```bash
git add -A
git commit -m "test: verify TradingContext integration"
```

---

## Summary

| Task | Description | Key Files |
|------|-------------|-----------|
| 1 | Fix duplicate high_water_mark | models.py |
| 2 | Add TradingContext dataclass | models.py |
| 3 | Update strategy interfaces | interfaces.py |
| 4 | Create TradingContextBuilder | context_builder.py (new) |
| 5 | Update V35EntryStrategy | v35_entry.py |
| 6 | Update V35TrailingExitStrategy | v35_trailing_exit.py |
| 7 | Update remaining entry strategies | short_entry.py, sideways_entry.py |
| 8 | Update remaining exit strategies | short_exit.py, sideways_exit.py, experimental_exit.py, v35_persistent_exit.py |
| 9 | Update CompositeStrategyTask | composite_task.py |
| 10 | Update Engine integration | engine.py |
| 11 | Update backtester adapter | component_adapter.py |
| 12 | Remove dead code | composite_task.py |
| 13 | Final integration test | - |
