#!/usr/bin/env python3
"""
Backtest for H4 Short Strategy.

H4 Short is a 4-hour timeframe short strategy that:
- Enters on downtrend + RSI overbought + BB upper band
- Requires 6%+ rise from recent low (dead cat bounce)
- Requires 1.5x+ volume spike
- Uses 5% TP, 2% SL, 72h max hold

Note: Uses margin-style backtesting for short positions.
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
    ShortMarginBacktester,
)
from trading.strategy.h4_short import H4ShortAdapter


def main():
    parser = create_parser(
        strategy_name="h4_short",
        default_timeframe="minute240",
        default_capital=10_000_000,  # KRW
    )
    args = parser.parse_args()

    db_path = get_db_path(args.db_path)

    print(f"Loading data: {args.timeframe} from {args.start_date} to {args.end_date}")
    df = load_data(db_path, args.timeframe, args.start_date, args.end_date)
    print(f"Loaded {len(df):,} candles")

    # Validate data
    if df.empty:
        print("ERROR: No data found for the specified date range.")
        sys.exit(1)

    # Initialize strategy adapter (from strategy module)
    strategy = H4ShortAdapter()

    # Run backtest with shared margin backtester (KRW: min_order=10000)
    bt = ShortMarginBacktester(
        initial_capital=args.capital,
        fee_rate=0.0005,
        slippage=0.0002,
        min_order_amount=10000,  # KRW
        action_open="short",
        action_close="close_short",
    )
    results = bt.run(df, strategy, {})

    # Compute metrics with correct timeframe
    metrics = compute_metrics(results.get("equity_curve"), args.timeframe)

    # Print results
    print_summary("H4 Short", results, metrics, verbose=args.verbose)

    if args.by_year:
        print_yearly_table(results.get("equity_curve"))


if __name__ == "__main__":
    main()
