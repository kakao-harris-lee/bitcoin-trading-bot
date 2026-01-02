#!/usr/bin/env python3
"""
Backtest for SideWays V1 Strategy.

SideWays V1 is a sideways market strategy that:
- Uses RSI + Bollinger Bands for oversold entries
- Uses Stochastic golden cross entries
- Uses volume breakout entries
- Filters high volatility and ATR spikes
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
from trading.strategy.sideways_v1 import SideWaysV1Strategy
from core.backtester import Backtester


class SideWaysV1Adapter:
    """Adapter to make SideWaysV1Strategy compatible with Backtester."""

    def __init__(self, config: dict = None):
        self.strategy = SideWaysV1Strategy(strategy_config=config)
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
        strategy_name="sideways_v1",
        default_timeframe="day",
        default_capital=10_000_000,
    )
    args = parser.parse_args()

    db_path = get_db_path(args.db_path)

    print(f"Loading data: {args.timeframe} from {args.start_date} to {args.end_date}")
    df = load_data(db_path, args.timeframe, args.start_date, args.end_date)
    print(f"Loaded {len(df):,} candles")

    # Initialize strategy adapter
    strategy = SideWaysV1Adapter()

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
    print_summary("SideWays V1", results, metrics, verbose=args.verbose)

    if args.by_year:
        print_yearly_table(results.get("equity_curve", None))


if __name__ == "__main__":
    main()
