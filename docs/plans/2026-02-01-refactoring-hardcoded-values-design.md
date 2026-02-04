# Refactoring: Hardcoded Values and Duplicate Code

**Date:** 2026-02-01
**Status:** Approved
**Approach:** Bottom-Up (Utilities → Constants → Base Classes)

## Problem Statement

The codebase has accumulated technical debt:
- **13 files** with duplicate PnL calculation logic
- **11 files** with duplicate regime classification
- **8 files** with duplicate exit signal creation
- **Hardcoded values** scattered across backtest_runner.py, component_adapter.py, and strategy files

## Solution Overview

Create centralized utilities, constants, and base classes to eliminate duplication and improve maintainability.

---

## Module 1: PnL Utilities

**File:** `trading/utils/pnl.py`

```python
"""PnL calculation utilities."""
from typing import Literal

def calculate_pnl_pct(
    current_price: float,
    entry_price: float,
    side: Literal["long", "short"] = "long"
) -> float:
    """Calculate profit/loss percentage.

    Args:
        current_price: Current market price
        entry_price: Position entry price
        side: Position side ("long" or "short")

    Returns:
        PnL as percentage (e.g., 5.0 for +5%)
    """
    if entry_price <= 0:
        return 0.0

    if side == "long":
        return ((current_price - entry_price) / entry_price) * 100
    else:
        return ((entry_price - current_price) / entry_price) * 100


def calculate_hwm_pnl_pct(
    high_water_mark: float,
    entry_price: float
) -> float:
    """Calculate PnL at high water mark."""
    if entry_price <= 0:
        return 0.0
    return ((high_water_mark - entry_price) / entry_price) * 100


def calculate_drawdown_from_hwm(
    current_price: float,
    high_water_mark: float
) -> float:
    """Calculate drawdown percentage from high water mark."""
    if high_water_mark <= 0:
        return 0.0
    return ((high_water_mark - current_price) / high_water_mark) * 100
```

**Affected files:** v35_trailing_exit.py, v35_persistent_exit.py, v35_classic_exit.py, short_exit.py, sideways_exit.py, combined_exit.py, hybrid_lstm_exit.py, combo1c_exit.py

---

## Module 2: System Constants

**File:** `trading/config/constants.py`

```python
"""Trading system constants."""

class FeeRates:
    """Exchange fee rates."""
    FUTURES = 0.0004          # 0.04%
    SPOT = 0.0005             # 0.05%
    FUTURES_SLIPPAGE = 0.0002 # 0.02%
    SPOT_SLIPPAGE = 0.0


class TimePeriods:
    """Time-based constants (in candles/hours)."""
    RF_HISTORY_WINDOW = 720       # Rolling window for RF/LSTM scaling
    MIN_HISTORY_REQUIRED = 60     # Minimum candles for LSTM prediction
    BACKTEST_WARMUP = 200         # Warmup before first trade
    STOP_LOSS_COOLDOWN = 24       # 1 day cooldown after stop loss
    CONSECUTIVE_LOSS_PAUSE = 48   # 2 day pause after consecutive losses
    EMA_200_PERIOD = 200
    EMA_120_PERIOD = 120
    TRADING_DAYS_PER_YEAR = 252   # For Sharpe ratio calculation


class LeverageDefaults:
    """Default leverage settings."""
    MAX = 3.0
    BULL_STRONG = 3.0
    BULL_MODERATE = 2.0
    SIDEWAYS = 1.0
    BEAR = 0.0


class DrawdownThresholds:
    """Drawdown management thresholds (percentages)."""
    WARNING = 8.0           # Reduce leverage
    REDUCE = 10.0           # Partial exit
    EXIT = 12.0             # Full exit
    LEVERAGE_REDUCTION = 0.5
    PARTIAL_EXIT_FRACTION = 0.5
```

**Affected files:** backtest_runner.py, component_adapter.py, paper_executor.py, async_executor.py

---

## Module 3: BaseExitStrategy

**File:** `trading/strategies/components/base_exit.py`

```python
"""Base class for exit strategies."""
from abc import ABC, abstractmethod
from typing import Literal

from .models import Position, Signal, TradingContext
from trading.utils.pnl import calculate_pnl_pct, calculate_hwm_pnl_pct


class BaseExitStrategy(ABC):
    """Base class providing common exit strategy functionality."""

    def __init__(self):
        self._high_water_marks: dict[str, float] = {}
        self._exit_stages: dict[str, int] = {}

    @abstractmethod
    def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
        """Check exit conditions. Subclasses must implement."""
        pass

    # === Common Helpers ===

    def _get_position_key(self, position: Position) -> str:
        """Generate unique key for position state tracking."""
        return f"{position.symbol}:{position.strategy}"

    def _update_hwm(self, key: str, current_price: float, entry_price: float) -> float:
        """Update and return high water mark."""
        hwm = self._high_water_marks.get(key, entry_price)
        if current_price > hwm:
            hwm = current_price
            self._high_water_marks[key] = hwm
        return hwm

    def _create_exit_signal(
        self,
        position: Position,
        reason: str,
        quantity: float = 1.0,
        side: Literal["sell", "buy"] = "sell"
    ) -> Signal:
        """Create standardized exit signal."""
        return Signal(
            symbol=position.symbol,
            side=side,
            market=position.market,
            quantity=quantity,
            reason=reason,
        )

    def _clear_state(self, key: str) -> None:
        """Clear all state for a position."""
        self._high_water_marks.pop(key, None)
        self._exit_stages.pop(key, None)

    # === Lifecycle Hooks ===

    def on_position_opened(self, position: Position) -> None:
        """Called when position is opened."""
        key = self._get_position_key(position)
        self._high_water_marks[key] = position.entry_price
        self._exit_stages[key] = 0

    def on_position_closed(self, symbol: str) -> None:
        """Called when position is closed."""
        keys = [k for k in self._high_water_marks if k.startswith(f"{symbol}:")]
        for k in keys:
            self._clear_state(k)
```

**Affected files:** v35_trailing_exit.py, v35_persistent_exit.py, v35_classic_exit.py, short_exit.py, sideways_exit.py, hybrid_lstm_exit.py

---

## Module 4: EntryFilters

**File:** `trading/strategies/components/entry_filters.py`

```python
"""Reusable entry filter checks."""
from dataclasses import dataclass
from typing import Optional

from .models import MarketData, TradingContext


@dataclass
class FilterResult:
    """Result of a filter check."""
    passed: bool
    reason: Optional[str] = None  # Rejection reason if not passed


class EntryFilters:
    """Collection of reusable entry filters."""

    @staticmethod
    def check_ema200(
        market_data: MarketData,
        use_filter: bool = True
    ) -> FilterResult:
        """Check if price is above EMA200."""
        if not use_filter:
            return FilterResult(passed=True)

        if market_data.ema_200 > 0 and market_data.close < market_data.ema_200:
            return FilterResult(
                passed=False,
                reason=f"below EMA200 ({market_data.close:.0f} < {market_data.ema_200:.0f})"
            )
        return FilterResult(passed=True)

    @staticmethod
    def check_adx_strength(
        context: TradingContext,
        min_adx: float
    ) -> FilterResult:
        """Check if ADX indicates sufficient trend strength."""
        if context.market.adx < min_adx:
            return FilterResult(
                passed=False,
                reason=f"weak trend (ADX={context.market.adx:.1f} < {min_adx})"
            )
        return FilterResult(passed=True)

    @staticmethod
    def check_not_bear_regime(
        context: TradingContext,
        bear_regimes: set[str] = {"BEAR_STRONG", "BEAR_MODERATE"}
    ) -> FilterResult:
        """Check if not in bear regime."""
        if context.regime in bear_regimes:
            return FilterResult(
                passed=False,
                reason=f"BEAR regime ({context.regime})"
            )
        return FilterResult(passed=True)

    @staticmethod
    def check_mfi_threshold(
        market_data: MarketData,
        min_mfi: float
    ) -> FilterResult:
        """Check if MFI is above threshold."""
        if market_data.mfi < min_mfi:
            return FilterResult(
                passed=False,
                reason=f"low MFI ({market_data.mfi:.1f} < {min_mfi})"
            )
        return FilterResult(passed=True)
```

**Affected files:** v35_entry.py, v35_classic_entry.py, short_entry.py, sideways_entry.py, hybrid_lstm_entry.py, combined_entry.py

---

## Implementation Plan

### Phase 1: Create Utilities (No existing code changes)
1. Create `trading/utils/__init__.py`
2. Create `trading/utils/pnl.py`
3. Create `trading/config/__init__.py`
4. Create `trading/config/constants.py`
5. Add unit tests for utilities

### Phase 2: Create Base Classes (No existing code changes)
1. Create `trading/strategies/components/base_exit.py`
2. Create `trading/strategies/components/entry_filters.py`
3. Add unit tests for base classes

### Phase 3: Gradual Migration
**Priority:** Start with simplest strategies

```
Round 1 (Low Risk):
  - v35_classic_exit.py → Inherit BaseExitStrategy

Round 2 (Medium Risk):
  - v35_trailing_exit.py → Inherit BaseExitStrategy

Round 3 (Entry Filters):
  - v35_classic_entry.py → Use EntryFilters

Round 4 (Constants):
  - backtest_runner.py → Use FeeRates, TimePeriods
  - component_adapter.py → Use constants
```

### Phase 4: Cleanup
1. Remove unused duplicate code
2. Run full test suite
3. Update documentation

---

## Expected Impact

- **~500 lines** eliminated from duplicate code
- **~15% reduction** in strategy file sizes
- **Single source of truth** for fee rates, timeframes
- **Easier A/B testing** (change constant vs find-replace)
- **Faster onboarding** (fewer magic numbers)

## Rollback Strategy

Each phase is independent. If issues arise, revert only the affected phase.
