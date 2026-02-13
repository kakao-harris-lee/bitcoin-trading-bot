# MLP Uptrend Alpha Improvement - Implementation Record

**Date:** 2026-02-13  
**Scope:** MLP strategy behavior update for better uptrend participation with capped risk profile.

## 1. Objective

Improve MLP strategy performance in up-market regimes by:

- reducing premature SELL exits,
- enabling risk-on/risk-off threshold switching,
- adding measurable diagnostics for up-market alpha and early-exit behavior.

## 2. Implemented Changes

### 2.1 Exit Strategy Guardrails

File: `trading/strategies/components/mlp_direction_exit.py`

Implemented:

- Added `min_hold_bars_for_sell_exit` to block immediate SELL exits after entry.
- Added `bull_regime_sell_guard` to require stricter SELL confidence in bull regimes.
- Integrated hold-bar tracking into `check_exit()` via existing base exit state.
- Added `_resolve_sell_threshold()` to unify runtime switch and bull-regime guard logic.

### 2.2 Config Runtime Profiles

File: `config/strategies/allocation.json`

For each `mlp_direction_*` strategy:

- Entry runtime profile enabled:
  - `runtime_switch_enabled: true`
  - `switch_mfi_threshold: 52.0`
  - `switch_adx_threshold: 18.0`
  - `switch_require_above_ema200: true`
  - `risk_on_*` and `risk_off_*` buy thresholds and position sizes set
- Exit runtime profile enabled:
  - `runtime_switch_enabled: true`
  - `risk_on_sell_confidence_threshold` and `risk_off_sell_confidence_threshold` set
  - `min_hold_bars_for_sell_exit: 2`
  - `bull_regime_sell_guard: true`

### 2.3 Backtest/Monitoring Metrics

File: `scripts/backtest/period_vs_bnh.py`

Added symbol-level summary metrics:

- `up_market_alpha_pct`
- `up_market_capture_ratio`
- `avg_hold_bars`
- `early_exit_rate_pct`

Also updated console summary output to display these values directly.

### 2.4 Tests

File: `tests/trading/strategies/components/test_mlp_direction_exit.py`

Added test coverage for:

- min-hold guard blocking SELL exits before required bars,
- bull-regime SELL threshold guard behavior.

## 3. Validation Executed on 2026-02-13

- `python -m pytest tests/trading/strategies/components/test_mlp_direction_exit.py -q` (pass)
- `python -m pytest tests/trading/strategies/components/test_strategy_factory.py -q` (pass)
- `python -m py_compile trading/strategies/components/mlp_direction_exit.py scripts/backtest/period_vs_bnh.py` (pass)
- `python scripts/backtest/period_vs_bnh.py --start-date 2025-01-01 --end-date 2026-01-11 --periods M,Q --output-dir /tmp/period_bnh_full_check` (pass)

## 4. Operations Additions

New scripts:

- `scripts/paper/collect_daily_mlp_soak_metrics.py`
- `scripts/paper/run_daily_soak_and_notify.sh`
- `scripts/paper/summarize_7d_soak_validation.py`
- `scripts/paper/run_final_7d_validation_and_notify.sh`
- `scripts/paper/send_validation_reminder.py`
- `scripts/paper/run_validation_reminder_and_notify.sh`

Purpose:

- collect daily rolling soak KPIs from Redis streams,
- run no-run soak comparison,
- send summary notification to Telegram,
- execute a scheduled final 7-day validation summary on the end date.

## 5. Notes

- This document records implementation only.
- 7-day runtime validation is tracked in:
  - `docs/plans/2026-02-13-mlp-uptrend-7d-validation.md`
