#!/usr/bin/env python3
"""
Feature Set A/B Comparison Backtest.

Runs MLP Direction strategy with different feature sets per asset:
  1. paper_36: Original paper feature set (23 candlestick patterns)
  2. v2_36: Improved feature set (23 technical indicators)

Compares: Total Return, Max Drawdown, Sharpe, Calmar Ratio, per-year returns.

Usage:
    python scripts/backtest/feature_set_comparison.py
    python scripts/backtest/feature_set_comparison.py --assets BTC ETH SOL
    python scripts/backtest/feature_set_comparison.py --by-year
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import (
    load_data,
    compute_metrics,
    print_yearly_table,
)
from scripts.backtest.backtest_mlp import (
    MLPDirectionBacktester,
    load_strategy_config,
)
from core.backtester import Backtester
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.indicators import add_all_indicators

# Asset database paths
ASSET_DB = {
    "BTC": ("data/binance_bitcoin.db", "BTC"),
    "ETH": ("data/binance_ethereum.db", "ETH"),
    "SOL": ("data/binance_solana.db", "SOL"),
}

MLP_STRATEGY_IDS = {
    "BTC": "mlp_direction_btc",
    "ETH": "mlp_direction_eth",
    "SOL": "mlp_direction_sol",
}

# V2 model paths per asset
V2_MODEL_PATHS = {
    "BTC": "models/mlp_direction/btc_v2_bwin5_fwin2/model_final.pt",
    "ETH": "models/mlp_direction/eth_v2_bwin4_fwin2/model_final.pt",
    "SOL": "models/mlp_direction/eth_v2_bwin4_fwin2/model_final.pt",  # shared
}


def run_single_asset(
    asset: str,
    config_path: str,
    capital: float,
    start_date: str,
    end_date: str,
    feature_set: str = "paper_36",
    model_path_override: str | None = None,
) -> dict[str, Any]:
    """Run MLP Direction backtest for a single asset with given feature set."""
    db_file, symbol = ASSET_DB[asset]
    db_path = str(PROJECT_ROOT / db_file)

    try:
        _, strategy_id, strategy_config = load_strategy_config(
            config_path=config_path,
            symbol=asset,
            mode="paper",
            strategy_id=MLP_STRATEGY_IDS.get(asset),
        )
    except ValueError as e:
        print(f"  WARNING: {e}, skipping {asset}")
        return {}

    # Override feature set
    strategy_config["mlp_feature_set"] = feature_set
    if strategy_config.get("entry", {}).get("params"):
        strategy_config["entry"]["params"]["mlp_feature_set"] = feature_set
    if strategy_config.get("exit", {}).get("params"):
        strategy_config["exit"]["params"]["mlp_feature_set"] = feature_set

    # Override model path if provided
    if model_path_override:
        strategy_config["model_path"] = model_path_override
        if strategy_config.get("entry", {}).get("params"):
            strategy_config["entry"]["params"]["model_path"] = model_path_override
        if strategy_config.get("exit", {}).get("params"):
            strategy_config["exit"]["params"]["model_path"] = model_path_override

    model_path = Path(strategy_config.get("model_path", ""))
    if not model_path.exists():
        print(f"  WARNING: Model not found at {model_path}, skipping {asset}")
        return {}

    # Load and prepare data
    df = load_data(db_path, "minute240", start_date, end_date, exchange="binance")
    if df.empty:
        print(f"  WARNING: No data for {asset}")
        return {}

    mlp_bt = MLPDirectionBacktester(
        symbol=asset,
        config=strategy_config,
        strategy_label=strategy_id,
    )
    df = mlp_bt.prepare_data(df)

    # Create adapter
    factory = StrategyFactory(redis=None)
    adapter = ComponentStrategyAdapter(
        factory=factory,
        strategy_name="mlp_direction",
        config=strategy_config,
    )
    adapter.symbol = asset
    adapter.precompute_mlp_predictions(df)

    # Run backtest
    bt = Backtester(
        initial_capital=capital,
        fee_rate=0.001,
        slippage=0.0002,
    )
    results = bt.run(df, adapter, {})
    metrics = compute_metrics(results.get("equity_curve"), timeframe="minute240")

    return {
        "results": results,
        "metrics": metrics,
        "equity_curve": results.get("equity_curve"),
        "config": strategy_config,
    }


def run_comparison(
    assets: list[str],
    config_path: str,
    capital_per_asset: float,
    start_date: str,
    end_date: str,
    by_year: bool = False,
) -> None:
    """Run A/B comparison: paper_36 vs v2_36, per asset and portfolio."""
    paper_results = {}
    v2_results = {}

    for asset in assets:
        print(f"\n{'='*60}")
        print(f"  {asset}: Running paper_36 (baseline)...")
        print(f"{'='*60}")
        paper_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            feature_set="paper_36",
        )

        print(f"\n  {asset}: Running v2_36 (improved features)...")
        v2_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            feature_set="v2_36",
            model_path_override=V2_MODEL_PATHS.get(asset),
        )

    # Print comparison table
    print("\n")
    print("=" * 80)
    print("  FEATURE SET COMPARISON: paper_36 vs v2_36")
    print("=" * 80)

    header = f"{'Asset':<8} {'Metric':<14} {'paper_36':>12} {'v2_36':>12} {'Delta':>10}"
    print(header)
    print("-" * 80)

    portfolio_paper_return = 0.0
    portfolio_v2_return = 0.0

    for asset in assets:
        p36 = paper_results.get(asset, {}).get("metrics", {})
        v2 = v2_results.get(asset, {}).get("metrics", {})

        if not p36 or not v2:
            print(f"{asset:<8} {'SKIPPED':<14}")
            continue

        for metric, label, fmt in [
            ("total_return", "Return", "{:+.1f}%"),
            ("mdd", "MDD", "{:.1f}%"),
            ("sharpe", "Sharpe", "{:.2f}"),
        ]:
            p_val = p36.get(metric, 0)
            v_val = v2.get(metric, 0)
            delta = v_val - p_val

            p_str = fmt.format(p_val)
            v_str = fmt.format(v_val)
            delta_str = fmt.format(delta)

            print(f"{asset if metric == 'total_return' else '':<8} {label:<14} {p_str:>12} {v_str:>12} {delta_str:>10}")

        # Calmar ratio
        p_calmar = abs(p36.get("total_return", 0) / p36.get("mdd", -1)) if p36.get("mdd", 0) != 0 else 0
        v_calmar = abs(v2.get("total_return", 0) / v2.get("mdd", -1)) if v2.get("mdd", 0) != 0 else 0
        delta_calmar = v_calmar - p_calmar
        print(f"{'':8} {'Calmar':<14} {p_calmar:>11.2f}x {v_calmar:>11.2f}x {delta_calmar:>+9.2f}x")

        # Trade count
        p_trades = p36.get("num_trades", 0)
        v_trades = v2.get("num_trades", 0)
        print(f"{'':8} {'Trades':<14} {p_trades:>12} {v_trades:>12} {v_trades - p_trades:>+10}")
        print()

        portfolio_paper_return += p36.get("total_return", 0)
        portfolio_v2_return += v2.get("total_return", 0)

    # Portfolio summary
    n = len([a for a in assets if paper_results.get(a, {}).get("metrics")])
    if n > 0:
        print("-" * 80)
        avg_p = portfolio_paper_return / n
        avg_v = portfolio_v2_return / n
        print(f"{'PORTFOLIO':<8} {'Avg Return':<14} {avg_p:>+11.1f}% {avg_v:>+11.1f}% {avg_v-avg_p:>+9.1f}%")

    # Per-year breakdown
    if by_year:
        for asset in assets:
            for label, results in [("paper_36", paper_results), ("v2_36", v2_results)]:
                eq = results.get(asset, {}).get("equity_curve")
                if eq is not None and not eq.empty:
                    print(f"\n--- {asset} {label} Per-Year ---")
                    print_yearly_table(eq)


def main():
    parser = argparse.ArgumentParser(description="Feature Set A/B Comparison")
    parser.add_argument(
        "--assets", nargs="+", default=["BTC", "ETH", "SOL"],
        choices=list(ASSET_DB.keys()),
        help="Assets to backtest",
    )
    parser.add_argument(
        "--config", default="config/strategies/allocation.json",
        help="Path to allocation config",
    )
    parser.add_argument(
        "--capital", type=float, default=10_000,
        help="Capital per asset",
    )
    parser.add_argument(
        "--start-date", default="2020-01-01",
        help="Backtest start date",
    )
    parser.add_argument(
        "--end-date", default="2026-02-01",
        help="Backtest end date",
    )
    parser.add_argument(
        "--by-year", action="store_true",
        help="Show per-year breakdown",
    )

    args = parser.parse_args()

    run_comparison(
        assets=args.assets,
        config_path=args.config,
        capital_per_asset=args.capital,
        start_date=args.start_date,
        end_date=args.end_date,
        by_year=args.by_year,
    )


if __name__ == "__main__":
    main()
