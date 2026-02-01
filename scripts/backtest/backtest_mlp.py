#!/usr/bin/env python3
"""
Backtest for MLP Direction Strategy.

MLP Direction is a neural network-based direction prediction strategy that:
- Uses 13 SHAP-validated features (Parente & Rizzuti 2025)
- Predicts 3-class direction (Hold/Buy/Sell)
- Enters on BUY prediction with high confidence
- Uses 10% fixed stop loss (as per paper)

Usage:
    python scripts/backtest/backtest_mlp.py --symbol BTC --start-date 2020-01-01
    python scripts/backtest/backtest_mlp.py --symbol ETH --start-date 2020-01-01 --by-year
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np

from scripts.backtest._common import (
    create_parser,
    get_db_path,
    load_data,
    compute_metrics,
    print_summary,
    print_yearly_table,
)
from core.backtester import Backtester
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.indicators import add_all_indicators
from trading.indicators.mlp_features import calculate_mlp_features


class MLPDirectionBacktester:
    """Wrapper for MLP Direction strategy backtesting.

    Handles data loading, indicator calculation, and result formatting.
    """

    def __init__(
        self,
        symbol: str = "BTC",
        model_path: str = "models/mlp_direction/model_final.pt",
        confidence_threshold: float = 0.60,
        stop_loss_pct: float = 10.0,
        fwin_exit_enabled: bool = True,
        fwin_periods: int = 2,
    ):
        self.symbol = symbol
        self.model_path = model_path
        self.confidence_threshold = confidence_threshold
        self.stop_loss_pct = stop_loss_pct
        self.fwin_exit_enabled = fwin_exit_enabled
        self.fwin_periods = fwin_periods

        # Build config
        self.config = {
            "position_pct": 0.10,  # 10% position size
            "market": "spot",
            "buy_confidence_threshold": confidence_threshold,
            "stop_loss_pct": stop_loss_pct,
            "model_path": model_path,
            # FWin exit (paper methodology)
            "fwin_exit_enabled": fwin_exit_enabled,
            "fwin_periods": fwin_periods,
        }

    def prepare_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add required indicators to DataFrame.

        Args:
            df: Raw OHLCV DataFrame.

        Returns:
            DataFrame with all required indicators.
        """
        # Add standard indicators (MFI, ADX, RSI, etc.)
        df = add_all_indicators(df)

        # Add MLP-specific features
        mlp_features = calculate_mlp_features(df, bwin=5, include_temporal=True)

        # Merge features
        for col in mlp_features.columns:
            df[col] = mlp_features[col]

        return df

    def run(
        self,
        df: pd.DataFrame,
        initial_capital: float = 10_000,
    ) -> dict:
        """Run backtest on prepared data.

        Args:
            df: DataFrame with OHLCV and indicators.
            initial_capital: Starting capital.

        Returns:
            Backtest results dictionary.
        """
        # Create strategy factory and adapter
        factory = StrategyFactory(redis=None)

        adapter = ComponentStrategyAdapter(
            factory=factory,
            strategy_name="mlp_direction",
            config=self.config,
        )
        adapter.symbol = self.symbol

        # Pre-compute MLP predictions for efficient backtesting
        adapter.precompute_mlp_predictions(df)

        # Run backtest
        bt = Backtester(
            initial_capital=initial_capital,
            fee_rate=0.001,  # Spot fee rate (0.1%)
            slippage=0.0002,
        )

        results = bt.run(df, adapter, {})

        return results


def run_backtest(
    symbol: str,
    db_path: str,
    start_date: str,
    end_date: str,
    timeframe: str = "minute240",  # 4-hour candles
    initial_capital: float = 10_000,
    model_path: str = "models/mlp_direction/model_final.pt",
    confidence_threshold: float = 0.60,
    stop_loss_pct: float = 10.0,
    fwin_exit_enabled: bool = True,
    fwin_periods: int = 2,
) -> dict:
    """Run MLP Direction strategy backtest.

    Args:
        symbol: Trading symbol (BTC, ETH).
        db_path: Path to database file.
        start_date: Backtest start date.
        end_date: Backtest end date.
        timeframe: Candle timeframe.
        initial_capital: Starting capital.
        model_path: Path to trained MLP model.
        confidence_threshold: Minimum confidence for BUY.
        stop_loss_pct: Stop loss percentage.

    Returns:
        Backtest results dictionary.
    """
    # Determine database path based on symbol
    if "BTC" in symbol.upper():
        db_path = str(PROJECT_ROOT / "data" / "binance_bitcoin.db")
    elif "ETH" in symbol.upper():
        db_path = str(PROJECT_ROOT / "data" / "binance_ethereum.db")
    elif "SOL" in symbol.upper():
        db_path = str(PROJECT_ROOT / "data" / "binance_solana.db")
    else:
        db_path = db_path or str(PROJECT_ROOT / "data" / "binance_bitcoin.db")

    print(f"Loading data from {db_path}")
    print(f"Timeframe: {timeframe}, Date range: {start_date} to {end_date}")

    # Load data
    df = load_data(db_path, timeframe, start_date, end_date, exchange="binance")
    print(f"Loaded {len(df):,} candles")

    if df.empty:
        print("ERROR: No data found for the specified date range.")
        return {}

    # Initialize backtester
    backtester = MLPDirectionBacktester(
        symbol=symbol,
        model_path=model_path,
        confidence_threshold=confidence_threshold,
        stop_loss_pct=stop_loss_pct,
        fwin_exit_enabled=fwin_exit_enabled,
        fwin_periods=fwin_periods,
    )

    # Prepare data
    print("Computing indicators...")
    df = backtester.prepare_data(df)
    print(f"Data prepared: {len(df):,} rows with {len(df.columns)} columns")

    # Run backtest
    print("Running backtest...")
    results = backtester.run(df, initial_capital=initial_capital)

    return results


def compare_with_baseline(
    mlp_results: dict,
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
) -> pd.DataFrame:
    """Compare MLP results with baseline strategies.

    Args:
        mlp_results: MLP backtest results.
        symbol: Trading symbol.
        start_date: Backtest start date.
        end_date: Backtest end date.
        initial_capital: Initial capital.

    Returns:
        Comparison DataFrame.
    """
    # Compute MLP metrics
    mlp_metrics = compute_metrics(mlp_results.get("equity_curve"), "minute240")

    comparison = {
        "Strategy": ["MLP Direction"],
        "Total Return %": [mlp_results.get("total_return", 0.0)],
        "CAGR %": [mlp_metrics.get("cagr", 0.0)],
        "MDD %": [mlp_metrics.get("mdd", 0.0)],
        "Sharpe": [mlp_metrics.get("sharpe", 0.0)],
        "Total Trades": [mlp_results.get("total_trades", 0)],
        "Win Rate %": [mlp_results.get("win_rate", 0.0) * 100],
    }

    return pd.DataFrame(comparison)


def main():
    """Main entry point."""
    parser = create_parser(
        strategy_name="mlp_direction",
        default_timeframe="minute240",  # 4-hour candles
        default_capital=10_000,
    )

    # Add MLP-specific arguments
    parser.add_argument(
        "--symbol",
        default="BTC",
        choices=["BTC", "ETH", "SOL"],
        help="Trading symbol (default: BTC)",
    )
    parser.add_argument(
        "--model",
        default="models/mlp_direction/model_final.pt",
        help="Path to trained MLP model",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.60,
        help="Minimum confidence threshold (default: 0.60)",
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        default=10.0,
        help="Stop loss percentage (default: 10.0)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare with baseline strategies",
    )
    parser.add_argument(
        "--fwin-exit",
        action="store_true",
        default=True,
        help="Enable FWin exit (paper methodology, default: True)",
    )
    parser.add_argument(
        "--no-fwin-exit",
        action="store_true",
        help="Disable FWin exit (use trailing/TP instead)",
    )
    parser.add_argument(
        "--fwin-periods",
        type=int,
        default=2,
        help="Forward window periods (default: 2 candles)",
    )

    args = parser.parse_args()
    # Handle --no-fwin-exit flag
    fwin_enabled = not args.no_fwin_exit

    # Check if model exists
    model_path = Path(args.model)
    if not model_path.exists():
        print(f"WARNING: Model not found at {model_path}")
        print("Run training first: python mlp_trainer/train.py")
        print("Proceeding with backtest (will fail at prediction step)...")

    # Run backtest
    results = run_backtest(
        symbol=args.symbol,
        db_path=args.db_path,
        start_date=args.start_date,
        end_date=args.end_date,
        timeframe=args.timeframe,
        initial_capital=args.capital,
        model_path=args.model,
        confidence_threshold=args.confidence,
        stop_loss_pct=args.stop_loss,
        fwin_exit_enabled=fwin_enabled,
        fwin_periods=args.fwin_periods,
    )

    if not results:
        print("Backtest failed - no results returned.")
        sys.exit(1)

    # Compute metrics
    metrics = compute_metrics(results.get("equity_curve"), args.timeframe)

    # Print results
    print_summary(f"MLP Direction ({args.symbol})", results, metrics, verbose=args.verbose)

    if args.by_year:
        print_yearly_table(results.get("equity_curve"))

    if args.compare:
        print("\n" + "=" * 60)
        print("Comparison with Baselines")
        print("=" * 60)
        comparison_df = compare_with_baseline(
            results,
            args.symbol,
            args.start_date,
            args.end_date,
            args.capital,
        )
        print(comparison_df.to_string(index=False))


if __name__ == "__main__":
    main()
