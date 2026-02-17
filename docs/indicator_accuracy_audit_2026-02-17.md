# Indicator Accuracy Audit (2026-02-17)

## Scope
- Core indicator wrappers: `trading/indicators/technical.py`
- Batch precompute pipeline: `trading/indicators/precompute.py`
- Live indicator service: `trading/indicators/indicator_service.py`
- Legacy strategy indicator helpers: `trading/strategies/indicators.py`
- MLP helper indicators in `trading/indicators/mlp_features.py`
  - `calculate_bollinger_pct_b`
  - `calculate_ema_crossover`
  - `calculate_zscore`

## Data / Universe
- Source: local Binance DBs (`data/binance_*.db`)
- Symbols checked: BTC, ETH, SOL, BNB, XRP
- Timeframe: `minute240` (4H)
- Window: `2024-01-01` ~ `2025-12-31`

## Method
1. Compute indicators with project code.
2. Compute reference values with TA-Lib (or independent equivalent formula for derived fields).
3. Compare overlapping non-NaN points (`max_abs_diff`).

## Results
- `technical.py` + `precompute.py` indicators: exact match (`max_abs_diff=0`) for:
  - RSI, BB(upper/middle/lower), Stochastic K/D, MFI, ADX/+DI/-DI, MACD/signal/hist,
    EMA(20/50/100/120/200), ATR
  - derived: `market_stress`, `breakout_signal`, `target_price`
  - MLP helper functions: `bollinger_pct_b`, `ema_crossover`, `zscore`
- `indicator_service.py` live snapshot values matched `add_all_indicators()` last-row values exactly (`max_diff=0`) on sampled symbols.

## Findings / Fix
- Found one accuracy gap in legacy helper:
  - File: `trading/strategies/indicators.py`
  - Previous `calculate_rsi()` used simple average gains/losses (not Wilder RSI), causing large drift from TA-Lib.
- Fix applied:
  - `calculate_rsi`, `calculate_mfi`, `calculate_adx` now directly use TA-Lib and return last valid value.
  - Added parity tests:
    - `tests/trading/strategies/test_indicators_talib_parity.py`

## Verification Commands
```bash
pytest -q \
  tests/trading/strategies/test_indicators_talib_parity.py \
  tests/trading/indicators/test_technical.py \
  tests/trading/indicators/test_precompute.py
```

## Outcome
- Current indicator calculation paths are aligned with TA-Lib reference.
- Legacy strategy helper path is now corrected and guarded by unit tests.
