#!/usr/bin/env python3
"""
Compare component entry/exit pairings on the same dataset.

Defaults:
  - BTC, minute60
  - 2020-01-01 to 2025-12-31
  - Binance data (data/binance_bitcoin.db)
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.backtester import Backtester
from core.component_adapter import ComponentStrategyAdapter
from core.data_loader import DataLoader
from trading.indicators import add_all_indicators
from trading.strategies.components.strategy_factory import StrategyFactory
from scripts.backtest._common import compute_metrics, ShortMarginBacktester


def load_data(db_path: Path, timeframe: str, start: str, end: str) -> pd.DataFrame:
    with DataLoader(str(db_path), exchange="binance") as loader:
        return loader.load_timeframe(timeframe, start, end)


def run_long_backtest(
    df: pd.DataFrame,
    name: str,
    config: dict,
    initial_capital: float,
    fee_rate: float,
    slippage: float,
    min_order_amount: float,
) -> dict:
    factory = StrategyFactory()
    adapter = ComponentStrategyAdapter(factory, strategy_name=name, config=config)
    backtester = Backtester(
        initial_capital=initial_capital,
        fee_rate=fee_rate,
        slippage=slippage,
        min_order_amount=min_order_amount,
    )
    results = backtester.run(df, adapter, {})
    return results


def run_short_backtest(
    df: pd.DataFrame,
    name: str,
    config: dict,
    initial_capital: float,
    fee_rate: float,
    slippage: float,
    min_order_amount: float,
) -> dict:
    factory = StrategyFactory()
    adapter = ComponentStrategyAdapter(factory, strategy_name=name, config=config)
    backtester = ShortMarginBacktester(
        initial_capital=initial_capital,
        fee_rate=fee_rate,
        slippage=slippage,
        min_order_amount=min_order_amount,
        action_open="open_short",
        action_close="close_short",
    )
    results = backtester.run(df, adapter, {})
    return results


def print_table(rows: list[dict]) -> None:
    headers = (
        "Strategy",
        "Type",
        "Return%",
        "Sharpe",
        "MDD%",
        "Trades",
        "WinRate%",
    )
    print("\n" + "=" * 110)
    print("{:<34} {:<6} {:>9} {:>8} {:>8} {:>8} {:>9}".format(*headers))
    print("-" * 110)
    for row in rows:
        print(
            "{:<34} {:<6} {:>9.2f} {:>8.2f} {:>8.2f} {:>8} {:>9.1f}".format(
                row["name"],
                row["kind"],
                row["return_pct"],
                row["sharpe"],
                row["mdd"],
                row["trades"],
                row["win_rate"] * 100,
            )
        )
    print("=" * 110)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare component entry/exit pairings on BTC minute60 data."
    )
    parser.add_argument("--db", default="data/binance_bitcoin.db", help="Path to DB")
    parser.add_argument("--timeframe", default="minute60", help="Candle timeframe")
    parser.add_argument("--start", default="2020-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2025-12-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=10_000, help="Initial capital")
    args = parser.parse_args()

    db_path = Path(args.db)
    print(f"Loading data: {db_path} [{args.timeframe}] {args.start} -> {args.end}")
    df = load_data(db_path, args.timeframe, args.start, args.end)
    if df.empty:
        raise SystemExit("No data found for the requested range.")

    print(f"Loaded {len(df):,} candles. Computing indicators...")
    df = add_all_indicators(df.copy())

    fee_rate = 0.0005
    slippage = 0.0002
    min_order_amount = 10

    combos = [
        ("V35 Entry + V35 Exit", "long", "long_combo", {
            "entry": {"class": "V35EntryStrategy"},
            "exit": {"class": "V35TrailingExitStrategy"},
        }),
        ("V35 Entry + Experimental Exit", "long", "exp_exit_combo", {
            "entry": {"class": "V35EntryStrategy"},
            "exit": {"class": "ExperimentalExitStrategy"},
        }),
        ("Sideways Entry + V35 Exit", "long", "sideways_combo", {
            "entry": {"class": "SidewaysEntryStrategy"},
            "exit": {"class": "V35TrailingExitStrategy"},
        }),
        ("Short Entry + Short Exit (death cross)", "short", "short_v1", {
            "mfi_bear": 50.0,
            "mfi_bull": 52.0,
            "adx_trend": 12.0,
            "rsi_overbought": 68.0,
            "use_param_regime": True,
        }),
    ]

    rows = []
    for name, kind, strategy_name, config in combos:
        if kind == "short":
            results = run_short_backtest(
                df,
                strategy_name,
                config,
                args.capital,
                fee_rate,
                slippage,
                min_order_amount,
            )
        else:
            results = run_long_backtest(
                df,
                strategy_name,
                config,
                args.capital,
                fee_rate,
                slippage,
                min_order_amount,
            )

        metrics = compute_metrics(results.get("equity_curve"), args.timeframe)
        rows.append({
            "name": name,
            "kind": kind,
            "return_pct": metrics["total_return"],
            "sharpe": metrics["sharpe"],
            "mdd": metrics["mdd"],
            "trades": results.get("total_trades", 0),
            "win_rate": results.get("win_rate", 0.0),
        })

    print_table(rows)
    print("\nNote: Short result uses ShortMarginBacktester; long results use Backtester.")


if __name__ == "__main__":
    main()
