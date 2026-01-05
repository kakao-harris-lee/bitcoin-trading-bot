#!/usr/bin/env python3
"""
Backtest for Short V2 Hedge Strategy.

Short V2 is a BEAR_STRONG regime-gated hedge strategy that:
- Only activates during BEAR_STRONG regime
- Uses EMA 30/100 + ADX >= 20 entry conditions
- Exits on regime change or 5% stop-loss
- No take-profit (pure hedge)

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
from trading.strategy.short_v2 import ShortV2Strategy
from trading.strategy.regime_router import RegimeRouter


class ShortV2Adapter:
    """Adapter to make ShortV2Strategy compatible with margin backtester.

    Simulates regime classification and long exposure for backtesting.
    """

    def __init__(self, config: dict = None, simulated_long_exposure: float = 10_000_000):
        self.strategy = ShortV2Strategy(strategy_config=config)
        self.router = RegimeRouter(
            binance_gate_mode="bear_strong_only",
            binance_policy="short_v2",
        )
        self._cached_df = None
        self._cached_day_df = None
        self._simulated_long_exposure = simulated_long_exposure  # KRW

    @property
    def in_position(self) -> bool:
        return self.strategy.in_position

    def _get_regime(self, df, i: int) -> str:
        """Classify regime from 4h data by aggregating to daily."""
        # Simple approach: use the last 14+ days of 4h candles to compute daily MFI/ADX
        # We need at least 14*6 = 84 4h candles for daily computation
        if i < 100:
            return "SIDEWAYS_NEUTRAL"  # Not enough data

        # Get recent data window for regime classification
        lookback = min(i + 1, 200)
        recent_df = df.iloc[i - lookback + 1:i + 1].copy()

        # Resample to daily for regime classification
        if 'timestamp' in recent_df.columns:
            recent_df = recent_df.set_index('timestamp')

        daily_df = recent_df.resample('D').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()

        if len(daily_df) < 20:
            return "SIDEWAYS_NEUTRAL"

        # Use router to classify
        try:
            market_state = self.router.classify_market_state(daily_df)
            return market_state
        except Exception:
            return "SIDEWAYS_NEUTRAL"

    def __call__(self, df, i, params):
        if i < 100:  # EMA100 warmup
            return {"action": "hold"}

        # Cache indicators
        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self.strategy.add_indicators(df)

        # Get current regime
        regime = self._get_regime(df, i)

        # Generate signal with regime and simulated long exposure
        signal = self.strategy.generate_signal(
            self._cached_df,
            i,
            regime=regime,
            long_exposure_krw=self._simulated_long_exposure if not self.in_position else 0,
        )

        if signal is None:
            return {"action": "hold"}

        # Map short actions to standardized names
        action = signal.get("action", "hold")
        if action == "open_short":
            return {
                "action": "short",
                "fraction": signal.get("fraction", 1.0),
                "reason": f"{signal.get('reason', '')}|REGIME={regime}",
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
        strategy_name="short_v2",
        default_timeframe="minute240",
        default_capital=10_000,  # USDT
    )
    parser.add_argument(
        "--simulated-exposure",
        type=float,
        default=10_000_000,
        help="Simulated long exposure in KRW (default: 10M)"
    )
    args = parser.parse_args()

    db_path = get_db_path(args.db_path)

    print(f"=" * 60)
    print(f"SHORT_V2 Hedge Strategy Backtest")
    print(f"=" * 60)
    print(f"Timeframe: {args.timeframe}")
    print(f"Period: {args.start_date} to {args.end_date}")
    print(f"Simulated long exposure: {args.simulated_exposure:,.0f} KRW")
    print(f"=" * 60)

    print(f"\nLoading data...")
    df = load_data(db_path, args.timeframe, args.start_date, args.end_date)
    print(f"Loaded {len(df):,} candles")

    # Validate data
    if df.empty:
        print("ERROR: No data found for the specified date range.")
        sys.exit(1)

    # Initialize strategy adapter
    strategy = ShortV2Adapter(simulated_long_exposure=args.simulated_exposure)

    # Run backtest with shared margin backtester
    # Note: Leverage and stop-loss are handled by the strategy, not the backtester
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
    print_summary("Short V2 (Hedge)", results, metrics, verbose=args.verbose)

    if args.by_year:
        print_yearly_table(results.get("equity_curve"))


if __name__ == "__main__":
    main()
