#!/usr/bin/env python3
"""
MLflow-based Strategy Parameter Optimization.

Grid search optimization with MLflow experiment tracking for comparing
different strategy parameter combinations.

Usage:
    python scripts/optimize_mlflow.py
    python scripts/optimize_mlflow.py --strategy sideways_v2 --experiment my-experiment
    python scripts/optimize_mlflow.py --dry-run  # Show param combinations without running

View results:
    mlflow ui --host 0.0.0.0 --port 5000
    # Open http://localhost:5000
"""

import sys
from pathlib import Path
from itertools import product
from typing import Dict, Any, List, Tuple
from dataclasses import dataclass
from datetime import datetime
import argparse
import json
import re

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
import mlflow


# Candles per year for different timeframes
CANDLES_PER_YEAR = {
    "minute1": 525600,      # 60 * 24 * 365
    "minute5": 105120,      # 12 * 24 * 365
    "minute15": 35040,      # 4 * 24 * 365
    "minute30": 17520,      # 2 * 24 * 365
    "minute60": 8760,       # 24 * 365
    "minute240": 2190,      # 6 * 365 (4-hour candles)
    "day": 365,
    "week": 52,
}


def validate_date(date_str: str, param_name: str) -> datetime:
    """Validate date string format.

    Args:
        date_str: Date string to validate (YYYY-MM-DD format).
        param_name: Parameter name for error messages.

    Returns:
        Parsed datetime object.

    Raises:
        ValueError: If date format is invalid.
    """
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise ValueError(
            f"Invalid {param_name} format: '{date_str}'. "
            f"Expected YYYY-MM-DD format (e.g., '2024-01-01')."
        )


def validate_date_range(start_date: str, end_date: str) -> None:
    """Validate that date range is valid.

    Args:
        start_date: Start date string.
        end_date: End date string.

    Raises:
        ValueError: If dates are invalid or end_date <= start_date.
    """
    start_dt = validate_date(start_date, "train_start")
    end_dt = validate_date(end_date, "train_end")

    if end_dt <= start_dt:
        raise ValueError(
            f"train_end ({end_date}) must be after train_start ({start_date})."
        )

    # Warn if dates are in the future
    if end_dt > datetime.now():
        print(f"  Warning: train_end ({end_date}) is in the future.")


def validate_dataframe(df: pd.DataFrame, timeframe: str) -> None:
    """Validate loaded DataFrame has required structure.

    Args:
        df: DataFrame to validate.
        timeframe: Timeframe for context in error messages.

    Raises:
        ValueError: If DataFrame is invalid.
    """
    if df is None or df.empty:
        raise ValueError(
            f"No data loaded for timeframe '{timeframe}'. "
            f"Check that historical data exists in the database."
        )

    required_columns = {"open", "high", "low", "close"}
    missing = required_columns - set(df.columns.str.lower())
    if missing:
        raise ValueError(
            f"DataFrame missing required columns: {missing}. "
            f"Available columns: {list(df.columns)}"
        )

    # Check for NaN values in price columns
    price_cols = [c for c in df.columns if c.lower() in required_columns]
    nan_counts = df[price_cols].isna().sum()
    if nan_counts.any():
        print(f"  Warning: NaN values found in price data: {nan_counts.to_dict()}")


def sanitize_error_message(error: Exception) -> str:
    """Sanitize error message for logging (remove sensitive info).

    Args:
        error: Exception to sanitize.

    Returns:
        Sanitized error message string.
    """
    msg = str(error)
    # Remove file paths
    msg = re.sub(r'/[\w/.-]+', '<path>', msg)
    # Remove memory addresses
    msg = re.sub(r'0x[0-9a-fA-F]+', '<addr>', msg)
    # Truncate long messages
    if len(msg) > 200:
        msg = msg[:200] + "..."
    return msg


@dataclass
class OptimizationResult:
    """Result of a single backtest run."""
    params: Dict[str, Any]
    total_return: float
    total_trades: int
    win_rate: float
    sharpe_ratio: float
    max_drawdown: float
    profit_factor: float
    avg_trades_per_year: float
    strategy_name: str


# Parameter grids for different strategies
PARAM_GRIDS = {
    "sideways_v2": {
        # Entry params
        "rsi_oversold": [30.0, 35.0, 40.0],
        "adx_weak": [12.0, 15.0, 18.0],
        "position_size": [0.3, 0.5],
        # Exit params
        "stop_loss_pct": [1.0, 1.5, 2.0],
        "take_profit_pct": [1.5, 2.0, 2.5],
    },
}


def load_data(
    start_date: str = "2020-01-01",
    end_date: str = "2024-12-31",
    timeframe: str = "minute240",
) -> pd.DataFrame:
    """Load historical price data.

    Args:
        start_date: Start date for data.
        end_date: End date for data.
        timeframe: Candle timeframe (minute60, minute240, etc).

    Returns:
        DataFrame with OHLCV data.
    """
    from core.data_loader import DataLoader

    with DataLoader() as loader:
        df = loader.load_timeframe(timeframe, start_date, end_date)
    return df


def generate_param_combinations(param_grid: Dict[str, List]) -> List[Dict[str, Any]]:
    """Generate all parameter combinations from grid.

    Args:
        param_grid: Dictionary mapping param names to value lists.

    Returns:
        List of parameter dictionaries.
    """
    keys = list(param_grid.keys())
    values = list(param_grid.values())

    combinations = []
    for combo in product(*values):
        combinations.append(dict(zip(keys, combo)))

    return combinations


def run_backtest(
    strategy_name: str,
    entry_params: Dict[str, Any],
    exit_params: Dict[str, Any],
    df: pd.DataFrame,
    market: str = "spot",
    timeframe: str = "minute240",
) -> OptimizationResult:
    """Run a single backtest with given parameters.

    Args:
        strategy_name: Name of the strategy (e.g., "sideways_v2").
        entry_params: Entry strategy parameter overrides.
        exit_params: Exit strategy parameter overrides.
        df: Price data DataFrame.
        market: Market type ("spot").
        timeframe: Data timeframe for accurate annualization.

    Returns:
        OptimizationResult with metrics.
    """
    from trading.strategies.components.strategy_factory import StrategyFactory
    from core.backtester import Backtester, BacktestAdapter

    # Create strategy components with overrides
    factory = StrategyFactory()
    config = {"market": market}

    entry, exit_strat = factory.create_components(
        strategy_name,
        config=config,
        entry_overrides=entry_params,
        exit_overrides=exit_params,
    )

    # Create adapter for backtester
    adapter = BacktestAdapter(
        entry_strategy=entry,
        exit_strategy=exit_strat,
        symbol="BTC",
        market=market,
        position_size=entry_params.get("position_size", 0.3),
    )

    # Run backtest (new instance each time to avoid trade accumulation)
    backtester = Backtester(
        initial_capital=10_000_000,
        fee_rate=0.0005,
        slippage=0.0002,
    )

    result = backtester.run(df, adapter)

    # Calculate years using correct candles per year for timeframe
    candles_per_year = CANDLES_PER_YEAR.get(timeframe, 2190)  # Default to 4-hour
    years = len(df) / candles_per_year if candles_per_year > 0 else 1.0
    avg_trades = result.get("total_trades", 0) / years if years > 0 else 0

    # Calculate profit factor with proper edge case handling
    profit_factor = _calculate_profit_factor(backtester.trades)

    all_params = {**entry_params, **exit_params}

    return OptimizationResult(
        params=all_params,
        total_return=result.get("total_return", 0),
        total_trades=result.get("total_trades", 0),
        win_rate=result.get("win_rate", 0),
        sharpe_ratio=result.get("sharpe_ratio", 0),
        max_drawdown=result.get("max_drawdown_pct", result.get("max_drawdown", 0)),
        profit_factor=profit_factor,
        avg_trades_per_year=avg_trades,
        strategy_name=strategy_name,
    )


def _calculate_profit_factor(trades: List) -> float:
    """Calculate profit factor with proper edge case handling.

    Args:
        trades: List of trade objects with profit_loss attribute.

    Returns:
        Profit factor (total profits / abs(total losses)).
        Returns float('inf') if all trades are winners.
        Returns 0.0 if all trades are losers or no trades.
    """
    if not trades:
        return 0.0

    total_profits = 0.0
    total_losses = 0.0

    for t in trades:
        if t.profit_loss is None:
            continue
        if t.profit_loss > 0:
            total_profits += t.profit_loss
        else:
            total_losses += t.profit_loss  # Negative value

    # Edge cases
    if total_losses == 0:
        # All winners or no completed trades
        return float('inf') if total_profits > 0 else 0.0

    if total_profits == 0:
        # All losers
        return 0.0

    return total_profits / abs(total_losses)


def split_params(
    params: Dict[str, Any],
    strategy_name: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Split combined params into entry and exit params.

    Args:
        params: Combined parameter dictionary.
        strategy_name: Strategy name for determining param ownership.

    Returns:
        Tuple of (entry_params, exit_params).
    """
    # Entry-specific params (common across strategies)
    entry_keys = {
        "mfi_bull_strong", "mfi_bull_moderate", "mfi_sideways_up",
        "mfi_bear_moderate", "mfi_bear_strong", "mfi_bear", "mfi_bull",
        "adx_strong_trend", "adx_moderate_trend", "adx_trend", "adx_weak",
        "momentum_rsi_bull_strong", "momentum_rsi_bull_moderate",
        "rsi_oversold", "rsi_overbought",
        "breakout_threshold", "breakout_volume_mult",
        "range_support_zone", "range_rsi_oversold",
        "conservative_rsi_threshold", "conservative_stoch_threshold",
        "position_size", "market",
    }

    # Exit-specific params
    exit_keys = {
        "stop_loss_pct", "take_profit_pct",
        "tp_bull_strong_1", "tp_bull_strong_2", "tp_bull_strong_3",
        "tp_bull_moderate_1", "tp_bull_moderate_2", "tp_bull_moderate_3",
        "tp_sideways_1", "tp_sideways_2", "tp_sideways_3",
        "exit_fraction_1", "exit_fraction_2", "exit_fraction_3",
        "trailing_enabled", "trailing_activation", "trailing_distance",
        "macd_exit_enabled", "min_profit_for_macd_exit",
    }

    entry_params = {k: v for k, v in params.items() if k in entry_keys}
    exit_params = {k: v for k, v in params.items() if k in exit_keys}

    return entry_params, exit_params


# Quick parameter grids for faster testing
PARAM_GRIDS_QUICK = {
    "sideways_v2": {
        "rsi_oversold": [30.0, 35.0],
        "stop_loss_pct": [1.5, 2.0],
        "position_size": [0.5],
    },
}


def run_optimization(
    strategy_name: str,
    experiment_name: str,
    train_start: str = "2020-01-01",
    train_end: str = "2024-12-31",
    timeframe: str = "minute240",
    market: str = "spot",
    dry_run: bool = False,
    max_combinations: int = 0,
    quick: bool = False,
) -> List[OptimizationResult]:
    """Run grid search optimization with MLflow tracking.

    Args:
        strategy_name: Strategy to optimize.
        experiment_name: MLflow experiment name.
        train_start: Training data start date.
        train_end: Training data end date.
        timeframe: Data timeframe (minute60, minute240, etc).
        market: Market type.
        dry_run: If True, only show param combinations without running.
        max_combinations: Limit number of combinations (0 = no limit).
        quick: Use reduced parameter grid for quick testing.

    Returns:
        List of optimization results sorted by total return.
    """
    print("=" * 80)
    print(f"MLflow Strategy Optimization: {strategy_name}")
    print("=" * 80)

    # Validate inputs early
    print("\nValidating inputs...")
    validate_date_range(train_start, train_end)

    if timeframe not in CANDLES_PER_YEAR:
        print(f"  Warning: Unknown timeframe '{timeframe}'. Using default annualization.")

    # Get parameter grid
    grids = PARAM_GRIDS_QUICK if quick else PARAM_GRIDS
    if strategy_name not in grids:
        raise ValueError(f"Unknown strategy: {strategy_name}. Available: {list(PARAM_GRIDS.keys())}")

    param_grid = grids[strategy_name]
    combinations = generate_param_combinations(param_grid)

    if max_combinations > 0:
        combinations = combinations[:max_combinations]

    print(f"\nParameter grid: {len(param_grid)} params")
    for k, v in param_grid.items():
        print(f"  {k}: {v}")

    print(f"\nTotal combinations: {len(combinations)}")

    if dry_run:
        print("\n[DRY RUN] First 5 combinations:")
        for i, combo in enumerate(combinations[:5]):
            print(f"  {i+1}. {combo}")
        return []

    # Load and validate data
    print(f"\nLoading data: {train_start} to {train_end} ({timeframe})...")
    df = load_data(train_start, train_end, timeframe)
    validate_dataframe(df, timeframe)
    print(f"  Loaded {len(df):,} candles")

    # Setup MLflow
    mlflow.set_tracking_uri("./mlruns")
    mlflow.set_experiment(experiment_name)

    print(f"\nMLflow experiment: {experiment_name}")
    print(f"Tracking URI: ./mlruns")

    results: List[OptimizationResult] = []

    # Run optimization
    print(f"\nRunning {len(combinations)} backtests...")
    for i, params in enumerate(combinations):
        if (i + 1) % 10 == 0 or i == 0:
            print(f"  Progress: {i+1}/{len(combinations)} ({(i+1)/len(combinations)*100:.1f}%)")

        entry_params, exit_params = split_params(params, strategy_name)

        with mlflow.start_run(run_name=f"{strategy_name}_run_{i+1}"):
            # Log parameters
            mlflow.log_params(params)
            mlflow.log_param("strategy_name", strategy_name)
            mlflow.log_param("market", market)
            mlflow.log_param("train_start", train_start)
            mlflow.log_param("train_end", train_end)

            try:
                result = run_backtest(
                    strategy_name=strategy_name,
                    entry_params=entry_params,
                    exit_params=exit_params,
                    df=df,
                    market=market,
                    timeframe=timeframe,
                )

                # Log metrics
                mlflow.log_metric("total_return", result.total_return)
                mlflow.log_metric("total_trades", result.total_trades)
                mlflow.log_metric("win_rate", result.win_rate)
                mlflow.log_metric("sharpe_ratio", result.sharpe_ratio)
                mlflow.log_metric("max_drawdown", result.max_drawdown)
                # Handle infinity for profit_factor (MLflow doesn't accept inf)
                pf = result.profit_factor if np.isfinite(result.profit_factor) else 999.99
                mlflow.log_metric("profit_factor", pf)
                mlflow.log_metric("avg_trades_per_year", result.avg_trades_per_year)

                results.append(result)

            except KeyboardInterrupt:
                # Don't catch keyboard interrupts - let user stop gracefully
                print(f"\n  Interrupted by user at run {i+1}/{len(combinations)}")
                raise
            except (MemoryError, SystemExit):
                # Don't catch system errors
                raise
            except Exception as e:
                # Sanitize error message before logging
                safe_error = sanitize_error_message(e)
                mlflow.set_tag("error", safe_error)  # Use tag instead of param for errors
                print(f"  Warning: Run {i+1} failed: {type(e).__name__}: {safe_error}")

    # Sort by total return
    results.sort(key=lambda r: r.total_return, reverse=True)

    # Print summary
    print("\n" + "=" * 80)
    print("Top 10 Results")
    print("=" * 80)
    print(f"{'Rank':<5} {'Return':>10} {'Trades':>8} {'WinRate':>8} {'Sharpe':>8} {'MDD':>10} {'PF':>8}")
    print("-" * 60)

    for i, r in enumerate(results[:10]):
        print(
            f"{i+1:<5} {r.total_return:>+9.2f}% {r.total_trades:>8} "
            f"{r.win_rate:>7.1f}% {r.sharpe_ratio:>8.2f} "
            f"{r.max_drawdown:>9.2f}% {r.profit_factor:>8.2f}"
        )

    if results:
        best = results[0]
        print("\n" + "=" * 80)
        print("Best Parameters")
        print("=" * 80)
        for k, v in best.params.items():
            print(f"  {k}: {v}")

        # Save best params to file
        output_dir = PROJECT_ROOT / "config" / "tuned"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"best_{strategy_name}_{market}.json"

        output_data = {
            "optimized_at": pd.Timestamp.now().isoformat(),
            "strategy": strategy_name,
            "market": market,
            "train_period": f"{train_start} to {train_end}",
            "params": best.params,
            "metrics": {
                "total_return": best.total_return,
                "total_trades": best.total_trades,
                "win_rate": best.win_rate,
                "sharpe_ratio": best.sharpe_ratio,
                "max_drawdown": best.max_drawdown,
                "profit_factor": best.profit_factor,
            }
        }
        with open(output_file, "w") as f:
            json.dump(output_data, f, indent=2)
        print(f"\nSaved best params to: {output_file}")

    print(f"\nMLflow UI: mlflow ui --host 0.0.0.0 --port 5000")
    print(f"View at: http://localhost:5000")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="MLflow-based Strategy Parameter Optimization"
    )
    parser.add_argument(
        "--strategy",
        default="sideways_v2",
        choices=list(PARAM_GRIDS.keys()),
        help="Strategy to optimize",
    )
    parser.add_argument(
        "--experiment",
        default="strategy-optimization",
        help="MLflow experiment name",
    )
    parser.add_argument(
        "--train-start",
        default="2020-01-01",
        help="Training data start date",
    )
    parser.add_argument(
        "--train-end",
        default="2024-12-31",
        help="Training data end date",
    )
    parser.add_argument(
        "--timeframe",
        default="minute240",
        help="Data timeframe (minute60, minute240, day)",
    )
    parser.add_argument(
        "--market",
        default="spot",
        choices=["spot"],
        help="Market type",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show param combinations without running",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use reduced parameter grid for quick testing",
    )
    parser.add_argument(
        "--max-combinations",
        type=int,
        default=0,
        help="Limit number of combinations (0 = no limit)",
    )

    args = parser.parse_args()

    run_optimization(
        strategy_name=args.strategy,
        experiment_name=args.experiment,
        train_start=args.train_start,
        train_end=args.train_end,
        timeframe=args.timeframe,
        market=args.market,
        dry_run=args.dry_run,
        quick=args.quick,
        max_combinations=args.max_combinations,
    )


if __name__ == "__main__":
    main()
