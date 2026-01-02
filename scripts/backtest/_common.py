#!/usr/bin/env python3
"""
Common utilities for per-strategy backtesting.

Provides shared functionality:
- Data loading
- Metrics calculation
- Output formatting
- CLI argument parsing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

# Project root setup
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.data_loader import DataLoader


def load_data(
    db_path: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Load OHLCV data from database.

    Args:
        db_path: Path to SQLite database
        timeframe: Candle timeframe (day, minute240, etc.)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)

    Returns:
        DataFrame with OHLCV data
    """
    with DataLoader(db_path) as loader:
        df = loader.load_timeframe(timeframe, start_date, end_date)
    return df


def compute_metrics(equity_curve: pd.DataFrame) -> Dict[str, float]:
    """Compute backtest metrics from equity curve.

    Args:
        equity_curve: DataFrame with 'timestamp' and 'total_equity' columns

    Returns:
        Dict with: total_return, cagr, mdd, sharpe
    """
    if equity_curve.empty or len(equity_curve) < 2:
        return {
            "total_return": 0.0,
            "cagr": 0.0,
            "mdd": 0.0,
            "sharpe": 0.0,
        }

    eq = equity_curve.copy()
    eq = eq.sort_values("timestamp")

    initial = float(eq["total_equity"].iloc[0])
    final = float(eq["total_equity"].iloc[-1])

    # Total return
    total_return = ((final - initial) / initial) * 100 if initial > 0 else 0.0

    # CAGR
    start = pd.Timestamp(eq["timestamp"].iloc[0])
    end = pd.Timestamp(eq["timestamp"].iloc[-1])
    years = (end - start).days / 365.25
    cagr = 0.0
    if years > 0 and initial > 0:
        cagr = ((final / initial) ** (1 / years) - 1) * 100

    # Max Drawdown
    peak = eq["total_equity"].cummax()
    drawdown = (eq["total_equity"] - peak) / peak
    mdd = float(drawdown.min() * 100)

    # Sharpe Ratio (annualized)
    returns = eq["total_equity"].pct_change().dropna()
    sharpe = 0.0
    if len(returns) > 5 and returns.std() != 0:
        sharpe = float((returns.mean() / returns.std()) * np.sqrt(252))

    return {
        "total_return": total_return,
        "cagr": cagr,
        "mdd": mdd,
        "sharpe": sharpe,
    }


def compute_trade_stats(results: Dict) -> Dict[str, float]:
    """Extract trade statistics from backtest results.

    Args:
        results: Backtester results dictionary

    Returns:
        Dict with: total_trades, win_rate, profit_factor, avg_profit, avg_loss
    """
    return {
        "total_trades": results.get("total_trades", 0),
        "win_rate": results.get("win_rate", 0.0),
        "profit_factor": results.get("profit_factor", 0.0),
        "avg_profit": results.get("avg_profit", 0.0),
        "avg_loss": results.get("avg_loss", 0.0),
    }


def print_summary(
    strategy_name: str,
    results: Dict,
    metrics: Dict[str, float],
    verbose: bool = True,
) -> None:
    """Print backtest summary.

    Args:
        strategy_name: Name of the strategy
        results: Backtester results
        metrics: Computed metrics
        verbose: Whether to print detailed output
    """
    print("\n" + "=" * 60)
    print(f"Backtest: {strategy_name.upper()}")
    print("=" * 60)
    print(f"Initial Capital: {results.get('initial_capital', 0):,.0f}")
    print(f"Final Capital:   {results.get('final_capital', 0):,.0f}")
    print(f"Total Return:    {results.get('total_return', 0):+.2f}%")
    print(f"CAGR:            {metrics.get('cagr', 0):+.2f}%")
    print(f"MDD:             {metrics.get('mdd', 0):.2f}%")
    print(f"Sharpe:          {metrics.get('sharpe', 0):+.2f}")

    if verbose and results.get("total_trades", 0) > 0:
        print("-" * 40)
        print(f"Total Trades:    {results.get('total_trades', 0)}")
        print(f"Win Rate:        {results.get('win_rate', 0) * 100:.1f}%")
        print(f"Profit Factor:   {results.get('profit_factor', 0):.2f}")
        print(f"Avg Profit:      {results.get('avg_profit', 0):,.0f}")
        print(f"Avg Loss:        {results.get('avg_loss', 0):,.0f}")


def print_yearly_table(equity_curve: pd.DataFrame) -> None:
    """Print year-by-year breakdown table.

    Args:
        equity_curve: DataFrame with 'timestamp' and 'total_equity' columns
    """
    if equity_curve.empty:
        print("(no data)")
        return

    df = equity_curve.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["year"] = df["timestamp"].dt.year

    print("\n" + "=" * 50)
    print("Year-by-Year Breakdown")
    print("=" * 50)
    print(f"{'YEAR':<6} {'RET%':>10} {'MDD%':>10}")
    print("-" * 30)

    for year, grp in df.groupby("year"):
        if len(grp) < 2:
            continue

        start_eq = float(grp["total_equity"].iloc[0])
        end_eq = float(grp["total_equity"].iloc[-1])
        ret = ((end_eq - start_eq) / start_eq) * 100 if start_eq > 0 else 0.0

        peak = grp["total_equity"].cummax()
        dd = (grp["total_equity"] - peak) / peak
        mdd = float(dd.min() * 100)

        print(f"{int(year):<6} {ret:>10.2f} {mdd:>10.2f}")


def create_parser(
    strategy_name: str,
    default_timeframe: str = "day",
    default_capital: float = 10_000_000,
) -> argparse.ArgumentParser:
    """Create CLI argument parser.

    Args:
        strategy_name: Name of the strategy
        default_timeframe: Default candle timeframe
        default_capital: Default initial capital

    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        description=f"Backtest for {strategy_name} strategy"
    )

    parser.add_argument(
        "--start-date",
        default="2020-01-01",
        help="Backtest start date (default: 2020-01-01)",
    )
    parser.add_argument(
        "--end-date",
        default="2024-12-31",
        help="Backtest end date (default: 2024-12-31)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=default_capital,
        help=f"Initial capital (default: {default_capital:,.0f})",
    )
    parser.add_argument(
        "--timeframe",
        default=default_timeframe,
        help=f"Candle timeframe (default: {default_timeframe})",
    )
    parser.add_argument(
        "--by-year",
        action="store_true",
        help="Show year-by-year breakdown",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=True,
        help="Verbose output (default: True)",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Database path (default: data/upbit_bitcoin.db)",
    )

    return parser


def get_db_path(args_db_path: Optional[str] = None) -> str:
    """Get database path.

    Args:
        args_db_path: User-provided path or None

    Returns:
        Resolved database path
    """
    if args_db_path:
        return args_db_path
    return str(PROJECT_ROOT / "data" / "upbit_bitcoin.db")
