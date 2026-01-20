#!/usr/bin/env python3
"""
Backtest for Short V1 Strategy.

Short V1 is an EMA/ADX-based short strategy for Binance Futures that:
- Enters on EMA death cross with strong ADX
- Uses -DI > +DI confirmation
- Exits on golden cross or TP/SL levels

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
# from trading.strategy.short_v1 import ShortV1Strategy
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.indicators import add_all_indicators


class ShortV1Adapter:
    """Adapter to make ShortV1Strategy compatible with margin backtester."""

    def __init__(self, config: dict = None):
        self.config = config or {}
        # Initialize component adapter
        self.adapter = ComponentStrategyAdapter(
            factory=StrategyFactory(),
            strategy_name="short_v1",
            config=self.config
        )
        self._cached_df = None

    @property
    def in_position(self) -> bool:
        return self.adapter.current_position is not None

    def __call__(self, df, i, params):
        if i < 200:  # EMA200 warmup
            return {"action": "hold"}

        # Cache indicators
        if self._cached_df is None or len(df) != len(self._cached_df):
            # Use unified indicator function
            self._cached_df = add_all_indicators(df.copy())

        # Delegate to ComponentStrategyAdapter
        return self.adapter(self._cached_df, i, params)

        signal = self.strategy.generate_signal(self._cached_df, i)
        if signal is None:
            return {"action": "hold"}

        # Map short actions to standardized names
        action = signal.get("action", "hold")
        if action == "open_short":
            return {
                "action": "short",
                "fraction": signal.get("fraction", 1.0),
                "reason": signal.get("reason", ""),
            }
        elif action == "close_short":
            return {
                "action": "close_short",
                "fraction": 1.0,
                "reason": signal.get("reason", ""),
            }

        return {"action": "hold"}


def main():
    parser = create_parser(
        strategy_name="short_v1",
        default_timeframe="minute240",
        default_capital=10_000,  # USDT
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

    # Initialize strategy adapter
    strategy = ShortV1Adapter()

    # Run backtest with shared margin backtester (USDT: min_order=10)
    bt = ShortMarginBacktester(
        initial_capital=args.capital,
        fee_rate=0.0005,
        slippage=0.0002,
        min_order_amount=10,  # USDT
        action_open="short",
        action_close="close_short",
    )
    results = bt.run(df, strategy, {})

    # Compute metrics with correct timeframe
    metrics = compute_metrics(results.get("equity_curve"), args.timeframe)

    # Print results
    print_summary("Short V1", results, metrics, verbose=args.verbose)

    if args.by_year:
        print_yearly_table(results.get("equity_curve"))


if __name__ == "__main__":
    main()
