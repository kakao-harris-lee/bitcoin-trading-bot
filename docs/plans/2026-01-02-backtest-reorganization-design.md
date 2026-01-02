# Backtest Reorganization Design

## Overview

Reorganize backtesting scripts into per-strategy isolated files under `scripts/backtest/`.

## Goals

- **Per-strategy isolation**: Each strategy has its own dedicated backtest file
- **Minimal structure**: Import strategy from `trading/strategy/`, config from `config/strategies/`
- **Standard CLI**: Consistent interface across all backtest scripts

## File Structure

```
scripts/backtest/
├── __init__.py
├── _common.py          # Shared utilities (data loading, metrics, output formatting)
├── v35_long.py         # V35 long strategy backtest
├── short_v1.py         # Short V1 strategy backtest
├── sideways_v1.py      # Sideways V1 strategy backtest
├── sideways_v2.py      # Sideways V2 strategy backtest
├── h4_conservative.py  # H4 conservative strategy backtest
└── h4_short.py         # H4 short strategy backtest
```

## CLI Interface

Each script supports:

```bash
python scripts/backtest/v35_long.py \
    --start-date 2020-01-01 \
    --end-date 2024-12-31 \
    --capital 10000000 \
    --timeframe day \
    --by-year \
    --verbose
```

| Argument | Default | Description |
|----------|---------|-------------|
| `--start-date` | 2020-01-01 | Backtest start date |
| `--end-date` | 2024-12-31 | Backtest end date |
| `--capital` | 10,000,000 | Initial capital (KRW for Upbit, USDT for Binance) |
| `--timeframe` | strategy-specific | Candle timeframe |
| `--by-year` | false | Show year-by-year breakdown |
| `--verbose` | true | Verbose output |

## Common Module (`_common.py`)

Shared utilities to avoid duplication:

```python
# Data loading
def load_data(db_path, timeframe, start_date, end_date) -> pd.DataFrame

# Metrics calculation
def compute_metrics(equity_curve) -> Dict[str, float]
    # Returns: total_return, cagr, mdd, sharpe, win_rate, profit_factor

# Output formatting
def print_summary(strategy_name, results, metrics)
def print_yearly_table(equity_curve)

# CLI argument parsing
def create_parser(default_timeframe) -> argparse.ArgumentParser
```

## Strategy Backtest Template

Each strategy file follows this pattern:

```python
#!/usr/bin/env python3
"""Backtest for {strategy_name} strategy."""

from scripts.backtest._common import load_data, compute_metrics, print_summary, create_parser
from trading.strategy.{strategy_module} import {StrategyClass}
from core.backtester import Backtester

def main():
    parser = create_parser(default_timeframe="{default_tf}")
    args = parser.parse_args()

    # Load data
    df = load_data(args.db_path, args.timeframe, args.start_date, args.end_date)

    # Initialize strategy
    strategy = {StrategyClass}()

    # Run backtest
    bt = Backtester(initial_capital=args.capital)
    results = bt.run(df, strategy, {})

    # Output results
    metrics = compute_metrics(results["equity_curve"])
    print_summary("{strategy_name}", results, metrics)

    if args.by_year:
        print_yearly_table(results["equity_curve"])

if __name__ == "__main__":
    main()
```

## Strategy-Specific Details

| Strategy | Default Timeframe | DB Path | Notes |
|----------|-------------------|---------|-------|
| v35_long | day | upbit_bitcoin.db | Uses V35LongStrategy |
| short_v1 | minute240 | upbit_bitcoin.db | Uses ShortV1Strategy, margin-style backtest |
| sideways_v1 | day | upbit_bitcoin.db | Uses SideWaysV1Strategy |
| sideways_v2 | day | upbit_bitcoin.db | Uses SideWaysV2Strategy |
| h4_conservative | minute240 | upbit_bitcoin.db | Uses H4ConservativeStrategy |
| h4_short | minute240 | upbit_bitcoin.db | Uses H4ShortStrategy |

## Short Strategy Handling

`short_v1.py` and `h4_short.py` require margin-style backtesting (short positions). These will use a modified backtest loop that:
- Tracks margin and unrealized P&L
- Handles short entry (sell first) and exit (buy back)
- Uses the existing `ShortMarginBacktester` logic from `backtest.py`

## Migration Notes

- Old scripts in `scripts/` remain unchanged (no breaking changes)
- New scripts are additive
- Future: deprecate old scattered scripts after validation
