#!/usr/bin/env python3
"""
Backtest for MLP Direction Strategy.

MLP Direction is a neural network-based direction prediction strategy that:
- Uses paper_36 features (Parente & Rizzuti 2025)
- Predicts 3-class direction (Hold/Buy/Sell)
- Enters on BUY prediction
- Exits based on configured MLP SELL / FWin / stop loss rules

Usage:
    python scripts/backtest/backtest_mlp.py --symbol BTC --start-date 2020-01-01
    python scripts/backtest/backtest_mlp.py --symbol ETH --start-date 2020-01-01 --by-year
    python scripts/backtest/backtest_mlp.py --symbol BTC --mode live --strategy-id mlp_direction_optimized
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

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


def _expand_env_vars(obj: Any) -> Any:
    if isinstance(obj, str):
        return os.path.expandvars(obj)
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    return obj


def load_allocation_config(path: str) -> dict[str, Any]:
    with open(path) as f:
        config = json.load(f)
    return _expand_env_vars(config)


def _extract_param(config: dict[str, Any], key: str) -> Any:
    if key in config:
        return config.get(key)
    entry_params = config.get("entry", {}).get("params", {})
    if key in entry_params:
        return entry_params.get(key)
    exit_params = config.get("exit", {}).get("params", {})
    if key in exit_params:
        return exit_params.get(key)
    return None


def _normalize_mlp_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    if "model_path" not in normalized:
        model_path = _extract_param(config, "model_path")
        if model_path:
            normalized["model_path"] = model_path
    if "mlp_feature_set" not in normalized:
        feature_set = _extract_param(config, "mlp_feature_set")
        if feature_set:
            normalized["mlp_feature_set"] = feature_set
    if "bwin" not in normalized:
        bwin = _extract_param(config, "bwin")
        if bwin is not None:
            normalized["bwin"] = bwin
    return normalized


def _resolve_strategy_id(
    strategies: dict[str, Any],
    symbol: str,
    mode: str,
    strategy_id: str | None,
) -> str:
    if strategy_id:
        return strategy_id

    symbol_key = f"mlp_direction_{symbol.lower()}"
    if mode == "paper":
        if symbol_key in strategies:
            return symbol_key
        if "mlp_direction" in strategies:
            return "mlp_direction"
        return symbol_key

    if mode == "live":
        if "mlp_direction_optimized" in strategies:
            return "mlp_direction_optimized"
        if symbol_key in strategies:
            return symbol_key
        if "mlp_direction" in strategies:
            return "mlp_direction"
        return symbol_key

    # Fallback
    return symbol_key if symbol_key in strategies else "mlp_direction"


def load_strategy_config(
    config_path: str,
    symbol: str,
    mode: str,
    strategy_id: str | None = None,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    allocation = load_allocation_config(config_path)
    strategies = allocation.get("strategies", {})
    if not strategies:
        raise ValueError("No strategies found in allocation config.")

    resolved_id = _resolve_strategy_id(
        strategies=strategies,
        symbol=symbol,
        mode=mode,
        strategy_id=strategy_id,
    )
    if resolved_id not in strategies:
        raise ValueError(f"Strategy '{resolved_id}' not found in allocation config.")

    strategy_config = _normalize_mlp_config(strategies[resolved_id])
    return allocation, resolved_id, strategy_config


class MLPDirectionBacktester:
    """Wrapper for MLP Direction strategy backtesting.

    Handles data loading, indicator calculation, and result formatting.
    """

    def __init__(
        self,
        symbol: str = "BTC",
        config: dict[str, Any] | None = None,
        entry_overrides: dict[str, Any] | None = None,
        exit_overrides: dict[str, Any] | None = None,
        strategy_label: str | None = None,
    ):
        self.symbol = symbol
        self.config = _normalize_mlp_config(config or {})
        self.entry_overrides = entry_overrides or {}
        self.exit_overrides = exit_overrides or {}
        self.strategy_label = strategy_label or "mlp_direction"

        feature_set = _extract_param(self.config, "mlp_feature_set")
        self.feature_set = feature_set or "paper_36"

        bwin = _extract_param(self.config, "bwin")
        self.bwin = int(bwin) if bwin is not None else 5

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
        mlp_features = calculate_mlp_features(
            df,
            bwin=self.bwin,
            include_temporal=True,
            feature_set=self.feature_set,
        )

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
            entry_overrides=self.entry_overrides,
            exit_overrides=self.exit_overrides,
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
    strategy_config: dict[str, Any] | None = None,
    entry_overrides: dict[str, Any] | None = None,
    exit_overrides: dict[str, Any] | None = None,
    strategy_label: str | None = None,
) -> dict:
    """Run MLP Direction strategy backtest.

    Args:
        symbol: Trading symbol (BTC, ETH).
        db_path: Path to database file.
        start_date: Backtest start date.
        end_date: Backtest end date.
        timeframe: Candle timeframe.
        initial_capital: Starting capital.
        strategy_config: Strategy config dict (allocation.json block).
        entry_overrides: Entry parameter overrides.
        exit_overrides: Exit parameter overrides.
        strategy_label: Label for reporting.

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
        config=strategy_config or {},
        entry_overrides=entry_overrides,
        exit_overrides=exit_overrides,
        strategy_label=strategy_label,
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
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Config mode to load from allocation.json (default: paper)",
    )
    parser.add_argument(
        "--config",
        default="config/strategies/allocation.json",
        help="Path to allocation config (default: config/strategies/allocation.json)",
    )
    parser.add_argument(
        "--strategy-id",
        default=None,
        help="Strategy config id in allocation.json (default: auto by mode/symbol)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override model path (defaults to allocation.json)",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=None,
        help="Override buy_confidence_threshold (default: use config)",
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        default=None,
        help="Override stop_loss_pct (default: use config)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare with baseline strategies",
    )
    parser.add_argument(
        "--fwin-exit",
        action="store_true",
        default=None,
        help="Force enable FWin exit (override config)",
    )
    parser.add_argument(
        "--no-fwin-exit",
        action="store_true",
        default=None,
        help="Force disable FWin exit (override config)",
    )
    parser.add_argument(
        "--fwin-periods",
        type=int,
        default=None,
        help="Override fwin_periods (default: use config)",
    )

    args = parser.parse_args()
    try:
        _, strategy_id, strategy_config = load_strategy_config(
            config_path=args.config,
            symbol=args.symbol,
            mode=args.mode,
            strategy_id=args.strategy_id,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    entry_overrides: dict[str, Any] = {}
    exit_overrides: dict[str, Any] = {}

    if args.model:
        strategy_config["model_path"] = args.model
        entry_overrides["model_path"] = args.model
        exit_overrides["model_path"] = args.model

    if args.confidence is not None:
        entry_overrides["buy_confidence_threshold"] = args.confidence

    if args.stop_loss is not None:
        exit_overrides["stop_loss_pct"] = args.stop_loss

    if args.fwin_exit is not None or args.no_fwin_exit is not None:
        if args.fwin_exit and args.no_fwin_exit:
            print("WARNING: Both --fwin-exit and --no-fwin-exit set; using --no-fwin-exit.")
        fwin_enabled = bool(args.fwin_exit) and not bool(args.no_fwin_exit)
        exit_overrides["fwin_exit_enabled"] = fwin_enabled

    if args.fwin_periods is not None:
        exit_overrides["fwin_periods"] = args.fwin_periods

    model_path = strategy_config.get("model_path")
    if model_path:
        model_path = Path(model_path)
        if not model_path.exists():
            print(f"WARNING: Model not found at {model_path}")
            print("Run training first: python mlp_trainer/train.py")
            print("Proceeding with backtest (will fail at prediction step)...")

    print(f"Mode: {args.mode} | Strategy config: {strategy_id}")

    # Run backtest
    results = run_backtest(
        symbol=args.symbol,
        db_path=args.db_path,
        start_date=args.start_date,
        end_date=args.end_date,
        timeframe=args.timeframe,
        initial_capital=args.capital,
        strategy_config=strategy_config,
        entry_overrides=entry_overrides,
        exit_overrides=exit_overrides,
        strategy_label=strategy_id,
    )

    if not results:
        print("Backtest failed - no results returned.")
        sys.exit(1)

    # Compute metrics
    metrics = compute_metrics(results.get("equity_curve"), args.timeframe)

    # Print results
    label = f"MLP Direction ({args.symbol}) [{strategy_id}]"
    print_summary(label, results, metrics, verbose=args.verbose)

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
