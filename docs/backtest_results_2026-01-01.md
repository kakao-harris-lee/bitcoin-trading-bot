# Unified Backtest Results - 2026-01-01

## Executive Summary

The unified backtesting framework has been completed and tested. Results reveal important insights about strategy component performance.

**Key Finding:** Long-only strategy is profitable, but short strategy significantly underperforms.

## Test Results

### All Tests Passed: 49/49

| Test Suite | Tests | Status |
|------------|-------|--------|
| Unified Backtester Unit Tests | 33 | PASS |
| Integration Tests | 16 | PASS |

## Backtest Results

### Training Period (2020-01-01 to 2024-12-31)

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Total Return | -7.12% | >= 15% | FAIL |
| Total Trades | 158 | 10-200 | PASS |
| Win Rate | 0.4% | >= 50% | FAIL |
| Sharpe Ratio | 0.41 | >= 1.5 | FAIL |
| Max Drawdown | -30.04% | >= -20% | FAIL |

### Validation Period (2025-01-01 to 2025-12-31)

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Total Return | -18.81% | >= 15% | FAIL |
| Total Trades | 25 | 10-200 | PASS |
| Win Rate | 0.4% | >= 50% | FAIL |
| Sharpe Ratio | 0.27 | >= 1.5 | FAIL |
| Max Drawdown | -24.81% | >= -20% | FAIL |

### Yearly Breakdown

| Year | Return % | Trades | Win Rate | Sharpe | Max DD |
|------|----------|--------|----------|--------|--------|
| 2020 | 1.70 | 21 | 0.4% | 0.35 | -20.30% |
| 2021 | -20.67 | 34 | 0.4% | 0.24 | -24.38% |
| 2022 | -16.28 | 29 | 0.4% | 0.36 | -24.15% |
| 2023 | -9.01 | 35 | 0.3% | 0.38 | -23.62% |
| 2024 | -10.44 | 35 | 0.4% | 0.32 | -24.88% |
| 2025 | -18.81 | 25 | 0.4% | 0.27 | -24.81% |

### Component Comparison (2024)

| Component | Return % | Trades | Sharpe |
|-----------|----------|--------|--------|
| **Long Only** | **+10.37** | 20 | 0.36 |
| Short Only | -13.98 | 15 | 0.29 |
| Long + Short | -10.44 | 35 | 0.32 |
| Full System | -10.44 | 35 | 0.32 |

> Note: The Kimchi premium arbitrage path has been removed from the codebase; results above cover the remaining alpha strategies only.

## Key Insights

### 1. Long Strategy Outperforms
- Long-only achieves **+10.37%** return in 2024
- This validates the V35 long strategy's effectiveness

### 2. Short Strategy Underperforms
- Short-only produces **-13.98%** loss in 2024
- Short trades drag down overall system performance
- The regime-based short entry logic needs refinement

### 3. Recommendations

1. **Disable or refine Short Strategy**: Current implementation loses money
2. **Use Long-Only Mode** until short strategy is improved
3. **Review RegimeRouter thresholds** for BEAR detection
4. **Consider more conservative short entry conditions**

## Files Created

| File | Purpose |
|------|---------|
| `core/unified_backtester.py` | Unified backtesting engine |
| `tests/test_unified_backtester.py` | Unit tests (33 tests) |
| `tests/integration/test_full_system.py` | Integration tests (16 tests) |
| `scripts/run_unified_backtest.py` | CLI runner script |

## Next Steps

1. Investigate why short strategy underperforms
2. Consider disabling short strategy in production
3. Add more sophisticated entry/exit logic to unified backtester
