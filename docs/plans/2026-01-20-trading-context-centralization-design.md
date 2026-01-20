# Trading Context Centralization Design

**Date:** 2026-01-20
**Status:** Approved
**Goal:** Centralize trading decision information for performance and completeness

## Problem Statement

### Performance Issues
- Multiple strategies (4-10) potentially recalculating the same indicators
- Regime classification (`build_market_context()`) called multiple times per tick
- Two indicator calculation paths exist (centralized IndicatorService vs local fallback)

### Completeness Issues
- Exit strategies don't receive `MarketContext` (can't see regime)
- No cross-strategy awareness (strategies can't see other positions)
- Duplicate `high_water_mark` field in MarketData (lines 69 and 77)

## Solution: TradingContext

Create a single `TradingContext` dataclass computed once per symbol per tick, shared across all strategies.

## Core Data Structure

```python
@dataclass(frozen=True)
class TradingContext:
    """Centralized trading decision context.

    Computed once per symbol per tick, shared across all strategies.
    """
    symbol: str
    timestamp: int  # Unix ms

    # Market data (indicators computed once)
    market: MarketData

    # Pre-analyzed regime (computed once)
    regime: MarketContext

    # All open positions across strategies
    # Key: strategy_name, Value: Position
    positions: frozendict[str, Position]

    # Convenience methods
    def has_position(self, strategy: str) -> bool:
        return strategy in self.positions

    def get_position(self, strategy: str) -> Position | None:
        return self.positions.get(strategy)

    def other_strategies_positioned(self, exclude: str) -> list[str]:
        """Returns strategy names holding positions (excluding self)."""
        return [s for s in self.positions if s != exclude]
```

## Interface Changes

### Entry Strategy

```python
class IEntryStrategy(Protocol):
    def check_entry(
        self,
        ctx: TradingContext,
    ) -> Signal | None:
        """Analyze conditions and return entry signal."""
        ...
```

### Exit Strategy

```python
class IExitStrategy(Protocol):
    def check_exit(
        self,
        ctx: TradingContext,
        position: Position,
    ) -> Signal | None:
        """Evaluate exit conditions."""
        ...

    def on_position_opened(self, position: Position) -> None:
        ...

    def on_position_closed(self, symbol: str) -> None:
        ...
```

### Change Summary

| Current | New |
|---------|-----|
| Entry: `market_data, context` (2 args) | Entry: `ctx` (1 arg) |
| Exit: `position, market_data` (2 args) | Exit: `ctx, position` (2 args) |
| Exit has no regime access | Exit gets full regime via `ctx.regime` |
| No cross-strategy visibility | `ctx.positions` shows all positions |

## Context Builder

```python
class TradingContextBuilder:
    """Builds TradingContext once per symbol, shares across strategies."""

    def __init__(
        self,
        indicator_service: IndicatorService,
        position_manager: PositionManager,
    ):
        self._indicators = indicator_service
        self._positions = position_manager
        self._cache: dict[str, TradingContext] = {}
        self._cache_timestamp: int = 0

    def get_context(self, symbol: str, timestamp: int) -> TradingContext:
        """Get or build context for symbol.

        Cache invalidates when timestamp changes (new tick).
        """
        if timestamp != self._cache_timestamp:
            self._cache.clear()
            self._cache_timestamp = timestamp

        if symbol not in self._cache:
            self._cache[symbol] = self._build(symbol, timestamp)

        return self._cache[symbol]

    def _build(self, symbol: str, timestamp: int) -> TradingContext:
        # 1. Get indicators (already cached in IndicatorService)
        market_data = self._indicators.get_market_data(symbol)

        # 2. Build regime (computed once here, not per-strategy)
        regime = build_market_context(
            mfi=market_data.mfi,
            adx=market_data.adx,
            atr=market_data.atr,
            close=market_data.close,
            volume=market_data.volume,
            avg_volume=market_data.avg_volume_20,
        )

        # 3. Get all positions for this symbol
        positions = self._positions.get_positions_for_symbol(symbol)

        return TradingContext(
            symbol=symbol,
            timestamp=timestamp,
            market=market_data,
            regime=regime,
            positions=frozenset(positions.items()),
        )
```

### Performance Gains

- **Indicators**: computed once (via existing `IndicatorService`)
- **Regime classification**: computed once per tick (was N times for N strategies)
- **Position lookup**: single Redis call, shared result

## Engine Integration

```python
class Engine:
    async def _setup_strategies(self):
        # Create shared services (once)
        self._indicator_service = IndicatorService(self._redis)
        self._position_manager = PositionManager(self._redis)

        # Create context builder (once)
        self._context_builder = TradingContextBuilder(
            indicator_service=self._indicator_service,
            position_manager=self._position_manager,
        )

        # Pass to all strategy tasks
        for strategy_config in self._config.strategies:
            task = CompositeStrategyTask(
                context_builder=self._context_builder,  # Shared!
                entry=strategy_config.entry,
                exit=strategy_config.exit,
                ...
            )
            self._tasks.append(task)
```

### CompositeStrategyTask Simplification

```python
class CompositeStrategyTask:
    async def _on_price_update(self, symbol: str, price: float, timestamp: int):
        # Get context (cached if already built for this tick)
        ctx = self._context_builder.get_context(symbol, timestamp)

        # Check entry (if no position)
        if not ctx.has_position(self._strategy_name):
            signal = self._entry.check_entry(ctx)
            if signal:
                await self._emit_order(signal)

        # Check exit (if has position)
        else:
            position = ctx.get_position(self._strategy_name)
            signal = self._exit.check_exit(ctx, position)
            if signal:
                await self._emit_order(signal)
```

## Migration Plan

### Step 1: Add New Types
Create `TradingContext` and `TradingContextBuilder` without breaking existing code.

### Step 2: Update Interfaces
Change `IEntryStrategy` and `IExitStrategy` signatures.

### Step 3: Migrate Strategies
Update each entry/exit component:
- `v35_entry.py`: `market_data.mfi` → `ctx.market.mfi`
- `v35_trailing_exit.py`: gains access to `ctx.regime`
- etc.

### Step 4: Update CompositeStrategyTask
Switch to using `TradingContextBuilder`.

### Step 5: Remove Dead Code
- Delete fallback indicator paths
- Remove unused caches
- Fix duplicate `high_water_mark` in MarketData

### Step 6: Update ComponentAdapter
Ensure backtester works with new interface.

## Testing Strategy

```python
# Unit test: TradingContext is immutable
def test_trading_context_immutable():
    ctx = TradingContext(...)
    with pytest.raises(FrozenInstanceError):
        ctx.symbol = "changed"

# Unit test: Builder caches per tick
def test_builder_caches_same_tick():
    builder = TradingContextBuilder(...)
    ctx1 = builder.get_context("BTC", timestamp=1000)
    ctx2 = builder.get_context("BTC", timestamp=1000)
    assert ctx1 is ctx2  # Same object, not rebuilt

# Unit test: Cache invalidates on new tick
def test_builder_invalidates_on_new_tick():
    builder = TradingContextBuilder(...)
    ctx1 = builder.get_context("BTC", timestamp=1000)
    ctx2 = builder.get_context("BTC", timestamp=2000)
    assert ctx1 is not ctx2  # Rebuilt

# Integration test: Exit strategy sees regime
def test_exit_has_regime_access():
    ctx = build_test_context(regime=MarketContext(regime="BEAR_STRONG", ...))
    exit_strategy = V35TrailingExit()
    signal = exit_strategy.check_exit(ctx, position)
```

## Files to Modify

| File | Change |
|------|--------|
| `trading/strategies/components/models.py` | Add `TradingContext`, fix duplicate `high_water_mark` |
| `trading/strategies/components/interfaces.py` | Update signatures |
| `trading/strategies/components/context_builder.py` | New file |
| `trading/strategies/components/composite_task.py` | Use `TradingContextBuilder` |
| `trading/engine.py` | Create and wire `TradingContextBuilder` |
| `trading/strategies/components/v35_entry.py` | Update to use `ctx` |
| `trading/strategies/components/v35_trailing_exit.py` | Update to use `ctx` |
| `trading/strategies/components/*_entry.py` | Update all entry components |
| `trading/strategies/components/*_exit.py` | Update all exit components |
| `core/component_adapter.py` | Update for backtester compatibility |
| `tests/` | Add new tests, update existing |
