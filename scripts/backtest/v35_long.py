#!/usr/bin/env python3
"""
Backtest for V35 Long Strategy.

V35 is a momentum-based long strategy for Upbit that:
- Enters on RSI/MACD momentum signals in BULL markets
- Uses breakout/range entries in SIDEWAYS markets
- Employs dynamic take-profit levels based on market state
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
from trading.strategy.v35_long import V35LongStrategy
from core.backtester import Backtester


class V35LongAdapter:
    """Adapter to make V35LongStrategy compatible with Backtester."""

    def __init__(self, config: dict = None):
        self.strategy = V35LongStrategy(strategy_config=config)
        self._cached_df = None

    def __call__(self, df, i, params):
        if i < 30:
            return {"action": "hold"}

        # Cache indicators
        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self.strategy.add_indicators(df)

        signal = self.strategy.generate_signal(self._cached_df, i)
        return signal or {"action": "hold"}


def main():
    parser = create_parser(
        strategy_name="v35_long",
        default_timeframe="day",
        default_capital=10_000_000,
    )
    args = parser.parse_args()

    db_path = get_db_path(args.db_path)

    print(f"Loading data: {args.timeframe} from {args.start_date} to {args.end_date}")
    df = load_data(db_path, args.timeframe, args.start_date, args.end_date)
    print(f"Loaded {len(df):,} candles")

    # Initialize strategy adapter
    strategy = V35LongAdapter()

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
    print_summary("V35 Long", results, metrics, verbose=args.verbose)

    if args.by_year:
        print_yearly_table(results.get("equity_curve", None))


if __name__ == "__main__":
    main()
