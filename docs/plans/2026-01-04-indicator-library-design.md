# Shared Indicator Library Design

**Date:** 2026-01-04
**Status:** Approved

## Overview

Create a shared indicator library to consolidate duplicate indicator calculations across trading strategies. Currently, RSI is calculated in 5 strategies, BBands in 5, Stochastic in 4, ADX in 4 - approximately 80% code duplication.

## Design Decisions

| Decision | Choice |
|----------|--------|
| Approach | Library + pre-computation at data level |
| talib dependency | Required (not optional) |
| Pre-compute scope | All 8 indicators |
| Location | `trading/indicators/` |
| Migration strategy | Parallel run with verification |

## Architecture

```
WebSocket (OHLCV)
     │
     ▼
FeedHandler
     │
     ▼
Strategy._get_dataframe()
     │
     ▼
┌─────────────────────────────────────────┐
│  trading/indicators/precompute.py       │
│  add_all_indicators(df) ────────────────┼──► Returns df with
│    └── calls technical.py functions     │    all indicators
└─────────────────────────────────────────┘
     │
     ▼
Strategy.generate_signal(df)  ◄── reads pre-computed columns
```

## File Structure

```
trading/indicators/
├── __init__.py          # Exports: add_all_indicators, technical module
├── technical.py         # 8 indicator functions (~80 lines)
└── precompute.py        # add_all_indicators + INDICATOR_COLUMNS (~60 lines)

tests/trading/indicators/
├── __init__.py
├── test_technical.py    # Unit tests for each indicator
└── test_precompute.py   # Integration tests for pre-computation
```

## Indicators

All indicators use talib for performance (~10x faster than numpy):

| Indicator | Function | Default Params | Output Columns |
|-----------|----------|----------------|----------------|
| RSI | `rsi(close, period=14)` | 14 | `rsi` |
| BBands | `bbands(close, period=20, std=2.0)` | 20, 2σ | `bb_upper`, `bb_middle`, `bb_lower` |
| Stochastic | `stochastic(high, low, close, k=14, d=3)` | 14, 3 | `stoch_k`, `stoch_d` |
| MFI | `mfi(high, low, close, volume, period=14)` | 14 | `mfi` |
| ADX | `adx(high, low, close, period=14)` | 14 | `adx`, `plus_di`, `minus_di` |
| MACD | `macd(close, fast=12, slow=26, signal=9)` | 12/26/9 | `macd`, `macd_signal`, `macd_hist` |
| EMA | `ema(close, period)` | 50, 200 | `ema_50`, `ema_200` |
| ATR | `atr(high, low, close, period=14)` | 14 | `atr` |

## technical.py

```python
"""Technical indicators using talib. All functions are pure and stateless."""

import talib
import pandas as pd

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    return pd.Series(talib.RSI(close.values, timeperiod=period), index=close.index)

def bbands(close: pd.Series, period: int = 20, std: float = 2.0
          ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands. Returns (upper, middle, lower)."""
    upper, middle, lower = talib.BBANDS(close.values, timeperiod=period,
                                         nbdevup=std, nbdevdn=std)
    return (pd.Series(upper, index=close.index),
            pd.Series(middle, index=close.index),
            pd.Series(lower, index=close.index))

def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               k_period: int = 14, d_period: int = 3) -> tuple[pd.Series, pd.Series]:
    """Stochastic K and D. Returns (stoch_k, stoch_d)."""
    k, d = talib.STOCH(high.values, low.values, close.values,
                       fastk_period=k_period, slowk_period=d_period, slowd_period=d_period)
    return pd.Series(k, index=close.index), pd.Series(d, index=close.index)

def mfi(high: pd.Series, low: pd.Series, close: pd.Series,
        volume: pd.Series, period: int = 14) -> pd.Series:
    """Money Flow Index."""
    return pd.Series(talib.MFI(high.values, low.values, close.values,
                               volume.values, timeperiod=period), index=close.index)

def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """ADX with directional indicators. Returns (adx, plus_di, minus_di)."""
    adx_val = talib.ADX(high.values, low.values, close.values, timeperiod=period)
    plus_di = talib.PLUS_DI(high.values, low.values, close.values, timeperiod=period)
    minus_di = talib.MINUS_DI(high.values, low.values, close.values, timeperiod=period)
    return (pd.Series(adx_val, index=close.index),
            pd.Series(plus_di, index=close.index),
            pd.Series(minus_di, index=close.index))

def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
        ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD. Returns (macd, signal, histogram)."""
    m, s, h = talib.MACD(close.values, fastperiod=fast, slowperiod=slow, signalperiod=signal)
    return (pd.Series(m, index=close.index),
            pd.Series(s, index=close.index),
            pd.Series(h, index=close.index))

def ema(close: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return pd.Series(talib.EMA(close.values, timeperiod=period), index=close.index)

def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range."""
    return pd.Series(talib.ATR(high.values, low.values, close.values,
                               timeperiod=period), index=close.index)
```

## precompute.py

```python
"""Pre-compute all standard indicators for strategy consumption."""

import pandas as pd
from . import technical as ta

INDICATOR_COLUMNS = [
    'rsi', 'bb_upper', 'bb_middle', 'bb_lower',
    'stoch_k', 'stoch_d', 'mfi',
    'adx', 'plus_di', 'minus_di',
    'macd', 'macd_signal', 'macd_hist',
    'ema_50', 'ema_200', 'atr'
]

def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add all pre-computed indicators to DataFrame.

    Expects columns: open, high, low, close, volume
    Returns the same DataFrame with indicator columns added.
    """
    required = ['open', 'high', 'low', 'close', 'volume']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    if len(df) < 200:
        return df

    df['rsi'] = ta.rsi(df['close'])
    df['bb_upper'], df['bb_middle'], df['bb_lower'] = ta.bbands(df['close'])
    df['stoch_k'], df['stoch_d'] = ta.stochastic(df['high'], df['low'], df['close'])
    df['mfi'] = ta.mfi(df['high'], df['low'], df['close'], df['volume'])
    df['adx'], df['plus_di'], df['minus_di'] = ta.adx(df['high'], df['low'], df['close'])
    df['macd'], df['macd_signal'], df['macd_hist'] = ta.macd(df['close'])
    df['ema_50'] = ta.ema(df['close'], 50)
    df['ema_200'] = ta.ema(df['close'], 200)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'])

    return df
```

## Migration Strategy

**Parallel run approach:**

1. Build library with tests
2. Update each strategy's `add_indicators()` to call library
3. Add verification logging to compare old vs new values
4. Run in paper mode, verify no discrepancies
5. Remove old code once verified

**Migration order:**
1. `v35_long.py` - Most used, covers all indicators
2. `sideways_v2.py` - Active in production
3. `regime_router.py` - Critical (note: ADX will change from rolling mean to EMA)
4. `short_v1.py` - ADX/DI heavy
5. `h4_conservative.py`, `h4_short.py` - Lower frequency
6. `sideways_v1.py` - If still in use

**Expected discrepancy:** `regime_router.py` currently uses rolling mean for ADX calculation. After migration, it will use talib's EMA-based ADX which is more accurate.

## Testing

**Unit tests (test_technical.py):**
- Each indicator: range validation, NaN handling, period behavior
- RSI: 0-100 range, first N-1 values are NaN
- BBands: upper >= middle >= lower
- ADX/DI: 0-100 range

**Integration tests (test_precompute.py):**
- All expected columns added
- Insufficient data (<200 rows) skips gracefully
- Required columns validation

## Implementation Order

1. Create `trading/indicators/` package with `__init__.py`, `technical.py`, `precompute.py`
2. Create `tests/trading/indicators/` with unit and integration tests
3. Verify tests pass
4. Migrate strategies one by one with verification
5. Remove duplicate code after verification passes
