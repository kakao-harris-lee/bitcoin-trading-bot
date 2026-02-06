#!/usr/bin/env python3
"""
Backtest for Bear Short Strategy.

Conservative futures short that activates during confirmed BEAR_STRONG regimes
with MACD momentum + volume confirmation.

Usage:
    python scripts/backtest/bear_short.py
    python scripts/backtest/bear_short.py --assets BTC ETH SOL --by-year
    python scripts/backtest/bear_short.py --start-date 2020-01-01 --end-date 2025-12-31
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import (
    create_parser,
    load_data,
    compute_metrics,
    print_summary,
    print_yearly_table,
    ShortMarginBacktester,
)
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.indicators import add_all_indicators

# Map asset names to DB paths and symbols
ASSET_DB = {
    "BTC": ("data/binance_bitcoin.db", "BTC"),
    "ETH": ("data/binance_ethereum.db", "ETH"),
    "SOL": ("data/binance_solana.db", "SOL"),
}

# Bear short config matching allocation.json
BEAR_SHORT_CONFIG = {
    "market": "futures",
    "leverage": 3,
    "position_pct": 0.90,
    "dynamic_sizing": True,
    "drawdown_enabled": False,
    "stop_loss_cooldown": 0,
    "entry": {
        "class": "BearShortEntryStrategy",
        "params": {
            "volume_ratio_threshold": 1.5,
            "position_size": 0.90,
        },
    },
    "exit": {
        "class": "BearShortExitStrategy",
        "params": {
            "stop_loss_pct": 3.0,
            "take_profit_pct": 5.0,
        },
    },
}


class BearShortAdapter:
    """Adapter to make BearShort compatible with ShortMarginBacktester."""

    def __init__(self, config: dict = None, symbol: str = "BTC"):
        self.config = config or BEAR_SHORT_CONFIG
        self.adapter = ComponentStrategyAdapter(
            factory=StrategyFactory(),
            strategy_name="bear_short",
            config=self.config,
        )
        self.adapter.symbol = symbol
        self._cached_df = None

    def __call__(self, df, i, params):
        if i < 200:
            return {"action": "hold"}

        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = add_all_indicators(df.copy())

        return self.adapter(self._cached_df, i, params)


def run_single_asset(
    asset: str,
    start_date: str,
    end_date: str,
    capital: float,
    timeframe: str,
    by_year: bool,
    verbose: bool,
):
    """Run backtest for a single asset."""
    if asset not in ASSET_DB:
        print(f"Unknown asset: {asset}. Available: {list(ASSET_DB.keys())}")
        return None

    db_rel, symbol = ASSET_DB[asset]
    db_path = str(PROJECT_ROOT / db_rel)

    print(f"\n{'='*60}")
    print(f"BEAR SHORT - {asset}")
    print(f"{'='*60}")
    print(f"Loading {timeframe} data: {start_date} to {end_date}")

    df = load_data(db_path, timeframe, start_date, end_date, exchange="binance")
    print(f"Loaded {len(df):,} candles")

    if df.empty:
        print(f"ERROR: No data found for {asset}")
        return None

    strategy = BearShortAdapter(symbol=symbol)

    bt = ShortMarginBacktester(
        initial_capital=capital,
        fee_rate=0.0005,
        slippage=0.0002,
        min_order_amount=10,
        action_open="open_short",
        action_close="close_short",
    )
    results = bt.run(df, strategy, {})
    metrics = compute_metrics(results.get("equity_curve"), timeframe)

    print_summary(f"Bear Short ({asset})", results, metrics, verbose=verbose)

    if by_year:
        print_yearly_table(results.get("equity_curve"))

    return results, metrics


def main():
    parser = create_parser(
        strategy_name="bear_short",
        default_timeframe="minute240",
        default_capital=10_000,
    )
    parser.add_argument(
        "--assets",
        nargs="+",
        default=["BTC", "ETH", "SOL"],
        help="Assets to backtest (default: BTC ETH SOL)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("BEAR SHORT STRATEGY BACKTEST")
    print(f"Assets: {', '.join(args.assets)} | Timeframe: {args.timeframe}")
    print(f"Period: {args.start_date} to {args.end_date}")
    print(f"Capital: ${args.capital:,.0f} USDT")
    print("=" * 60)

    all_results = {}
    for asset in args.assets:
        result = run_single_asset(
            asset=asset,
            start_date=args.start_date,
            end_date=args.end_date,
            capital=args.capital,
            timeframe=args.timeframe,
            by_year=args.by_year,
            verbose=args.verbose,
        )
        if result:
            all_results[asset] = result

    # Summary table
    if len(all_results) > 1:
        print(f"\n{'='*60}")
        print("COMBINED SUMMARY")
        print(f"{'='*60}")
        print(f"{'Asset':<6} {'Return%':>10} {'Trades':>8} {'WinRate':>10} {'Sharpe':>8} {'MDD%':>8}")
        print("-" * 52)
        for asset, (results, metrics) in all_results.items():
            wr = results.get("win_rate", 0) * 100
            print(
                f"{asset:<6} {results.get('total_return', 0):>10.2f} "
                f"{results.get('total_trades', 0):>8} "
                f"{wr:>9.1f}% "
                f"{metrics.get('sharpe', 0):>8.2f} "
                f"{metrics.get('mdd', 0):>8.2f}"
            )


if __name__ == "__main__":
    main()
