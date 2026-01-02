#!/usr/bin/env python3
"""
Backtest for H4 Conservative Strategy.

H4 Conservative is a 4-hour timeframe strategy that:
- Enters on uptrend + RSI oversold + BB lower band
- Requires 5%+ drop from recent high
- Requires 1.5x+ volume spike
- Uses 4% TP, 2% SL, 72h max hold
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import (
    create_parser,
    get_db_path,
    load_data,
    compute_metrics,
    print_summary,
    print_yearly_table,
)
from trading.strategy.h4_conservative import H4ConservativeAdapter
from core.backtester import Backtester


def main():
    parser = create_parser(
        strategy_name="h4_conservative",
        default_timeframe="minute240",
        default_capital=10_000_000,
    )
    args = parser.parse_args()

    db_path = get_db_path(args.db_path)

    print(f"Loading data: {args.timeframe} from {args.start_date} to {args.end_date}")
    df = load_data(db_path, args.timeframe, args.start_date, args.end_date)
    print(f"Loaded {len(df):,} candles")

    # Initialize strategy adapter (already provided by the strategy module)
    strategy = H4ConservativeAdapter()

    # Run backtest
    bt = Backtester(
        initial_capital=args.capital,
        fee_rate=0.0005,
        slippage=0.0002,
    )
    results = bt.run(df, strategy, {})

    # Compute metrics
    metrics = compute_metrics(results.get("equity_curve", None))

    # Print results
    print_summary("H4 Conservative", results, metrics, verbose=args.verbose)

    if args.by_year:
        print_yearly_table(results.get("equity_curve", None))


if __name__ == "__main__":
    main()
