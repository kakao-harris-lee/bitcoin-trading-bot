# Strategy Interface Contract

**Feature**: 001-improve-short-v1
**Date**: 2026-01-09

## Overview

This document defines the internal interfaces for the improved Short V1 strategy. Since this is a trading bot (not a web API), contracts describe method signatures and data structures.

## ShortV1Strategy Class Interface

### Inherited from BaseStrategy

```python
class ShortV1Strategy(BaseStrategy):
    """Enhanced Short V1 Strategy for Binance Futures."""

    # Required abstract method implementations
    def _min_buffer_size(self) -> int: ...
    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame: ...
    def generate_signal(self, df: pd.DataFrame, i: int) -> Optional[Dict]: ...
```

### New/Enhanced Methods

#### Entry Logic

```python
def _check_entry(
    self,
    row: pd.Series,
    prev_row: Optional[pd.Series],
    df_history: pd.DataFrame
) -> Optional[Dict]:
    """
    Check entry conditions for short position.

    Enhanced checks (FR-002, FR-003, FR-011, FR-013):
    - ADX >= threshold AND not declining
    - -DI > +DI (bearish momentum)
    - Not in extreme volatility
    - Death cross or existing bear trend

    Returns:
        Entry signal dict with:
        - action: 'open_short'
        - fraction: 1.0
        - confidence: float (>= 0.7)
        - stop_loss: float (ATR-buffered)
        - take_profit: float (1R target)
        - leverage: int (max 2)
        - metadata: dict (indicator values)

        Or None if conditions not met.
    """
```

#### Exit Logic

```python
def _check_exit(self, row: pd.Series) -> Optional[Dict]:
    """
    Check exit conditions for open position.

    Exit triggers (priority order):
    1. Gap past stop loss (FR-012) - immediate market exit
    2. Stop loss hit - exit all
    3. Golden cross (FR-007) - exit all
    4. 1R target hit - exit 50%, activate trailing (FR-006)
    5. Trailing stop hit - exit remaining
    6. 2R target hit - exit remaining

    Returns:
        Exit signal dict with:
        - action: 'close_short' or 'partial_close'
        - fraction: 1.0 (full) or 0.5 (partial)
        - reason: str (exit type)
        - exit_type: enum
        - metadata: dict

        Or None if no exit triggered.
    """
```

#### Stop Loss Calculation

```python
def _calculate_stop_loss(
    self,
    entry_price: float,
    swing_high: float,
    atr_value: float
) -> Dict:
    """
    Calculate ATR-buffered stop loss (FR-004, FR-005).

    Formula:
        raw_stop = swing_high + (atr_value * atr_multiplier)
        capped_stop = min(raw_stop, entry_price * 1.05)

    Args:
        entry_price: Short entry price
        swing_high: Recent swing high (10-bar max)
        atr_value: Current ATR value

    Returns:
        Dict with:
        - stop_loss: float (price level)
        - risk_pct: float (percentage from entry)
        - atr_buffer: float (ATR contribution)
    """
```

#### Trailing Stop Management

```python
def _update_trailing_stop(
    self,
    current_low: float,
    atr_value: float
) -> Optional[float]:
    """
    Update trailing stop for remaining position (FR-006).

    Rules:
    - Only active after 1R hit
    - Initial trail at entry_price (break-even)
    - Trail at: lowest_since_1r + (atr * multiplier)
    - Only tighten, never widen

    Args:
        current_low: Current candle low
        atr_value: Current ATR value

    Returns:
        New trailing stop price, or None if no change.
    """
```

#### Volatility Check

```python
def _check_extreme_volatility(self, daily_df: pd.DataFrame) -> bool:
    """
    Check for extreme daily volatility (FR-013).

    Formula:
        daily_range = (high - low) / open
        extreme = daily_range > 0.10

    Args:
        daily_df: Daily timeframe data

    Returns:
        True if volatility exceeds 10% threshold.
    """
```

## Signal Data Structures

### Entry Signal

```python
{
    "action": "open_short",
    "fraction": 1.0,
    "reason": "DEATH_CROSS+ADX_28+DI_BEAR",
    "confidence": 0.85,
    "leverage": 2,
    "stop_loss": 45200.0,
    "stop_loss_pct": 3.5,
    "take_profit": 42800.0,
    "take_profit_pct": 2.0,
    "metadata": {
        "adx": 28.5,
        "adx_prev": 26.2,
        "adx_declining": False,
        "plus_di": 18.3,
        "minus_di": 32.1,
        "atr": 450.0,
        "swing_high": 44800.0,
        "trend": "BEAR"
    }
}
```

### Exit Signal (Partial - 1R Hit)

```python
{
    "action": "partial_close",
    "fraction": 0.5,
    "reason": "TAKE_PROFIT_1R_HIT_2.0%",
    "confidence": 0.95,
    "exit_type": "TAKE_PROFIT_1R",
    "metadata": {
        "exit_price": 42800.0,
        "pnl_pct": 2.0,
        "remaining_fraction": 0.5,
        "trailing_activated": True
    }
}
```

### Exit Signal (Full - Stop Loss)

```python
{
    "action": "close_short",
    "fraction": 1.0,
    "reason": "STOP_LOSS_HIT_-3.5%",
    "confidence": 0.95,
    "exit_type": "STOP_LOSS",
    "metadata": {
        "exit_price": 45200.0,
        "pnl_pct": -3.5,
        "gap_exit": False
    }
}
```

## Configuration Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["strategy_name", "indicators", "entry", "exit", "stop_loss", "risk_management"],
  "properties": {
    "strategy_name": { "const": "SHORT_V1" },
    "indicators": {
      "type": "object",
      "properties": {
        "ema_fast": { "type": "integer", "minimum": 10, "maximum": 100 },
        "ema_slow": { "type": "integer", "minimum": 50, "maximum": 300 },
        "adx_period": { "type": "integer", "minimum": 7, "maximum": 28 },
        "atr_period": { "type": "integer", "minimum": 7, "maximum": 28 }
      }
    },
    "entry": {
      "type": "object",
      "properties": {
        "adx_min": { "type": "integer", "minimum": 20, "maximum": 40 },
        "adx_slope_bars": { "type": "integer", "minimum": 2, "maximum": 10 },
        "require_adx_not_declining": { "type": "boolean" },
        "require_death_cross": { "type": "boolean" },
        "di_negative_dominant": { "type": "boolean" }
      }
    },
    "exit": {
      "type": "object",
      "properties": {
        "two_tier_enabled": { "type": "boolean" },
        "first_tier_pct": { "type": "number", "minimum": 0.25, "maximum": 0.75 },
        "first_tier_r_multiple": { "type": "number", "minimum": 0.5, "maximum": 2.0 },
        "second_tier_r_multiple": { "type": "number", "minimum": 1.5, "maximum": 4.0 },
        "trailing_stop_atr_multiplier": { "type": "number", "minimum": 1.0, "maximum": 3.0 },
        "exit_on_golden_cross": { "type": "boolean" }
      }
    },
    "stop_loss": {
      "type": "object",
      "properties": {
        "atr_buffer_multiplier": { "type": "number", "minimum": 1.0, "maximum": 3.0 },
        "max_stop_loss_pct": { "type": "number", "maximum": 5.0 }
      }
    },
    "risk_management": {
      "type": "object",
      "properties": {
        "max_leverage": { "type": "integer", "maximum": 2 },
        "extreme_volatility_threshold": { "type": "number", "minimum": 0.05, "maximum": 0.20 },
        "halt_entries_on_extreme_vol": { "type": "boolean" }
      }
    }
  }
}
```

## Backward Compatibility

The enhanced strategy maintains backward compatibility:

1. **Config migration**: New fields have sensible defaults
2. **Signal format**: New fields added, existing fields unchanged
3. **Position state**: Internal enhancement, external interface same
4. **BaseStrategy**: No changes to abstract interface
