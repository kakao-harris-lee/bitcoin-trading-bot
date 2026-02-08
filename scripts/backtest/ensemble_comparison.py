#!/usr/bin/env python3
"""
Ensemble A/B Comparison Backtest.

Compares single-model MLP Direction strategy vs temporal ensemble
(soft-voting across bwin=3/1, bwin=4/2, bwin=5/2, bwin=7/3 models).

Usage:
    python scripts/backtest/ensemble_comparison.py
    python scripts/backtest/ensemble_comparison.py --assets BTC ETH SOL
    python scripts/backtest/ensemble_comparison.py --by-year
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

# Ensemble model configurations per asset
# All assets use the same set of multi-asset models
ENSEMBLE_CONFIGS = [
    {"model_path": "models/mlp_direction/multi_bwin3_fwin1/model_final.pt", "weight": 0.20},
    {"model_path": "models/mlp_direction/eth_bwin4_fwin2/model_final.pt", "weight": 0.30},
    {"model_path": "models/mlp_direction/btc_bwin5_fwin2/model_final.pt", "weight": 0.30},
    {"model_path": "models/mlp_direction/multi_bwin7_fwin3/model_final.pt", "weight": 0.20},
]


def run_single_asset(
    asset: str,
    config_path: str,
    capital: float,
    start_date: str,
    end_date: str,
    ensemble_models: list[dict] | None = None,
) -> dict[str, Any]:
    """Run MLP Direction backtest for a single asset.

    Args:
        ensemble_models: If provided, use ensemble prediction instead of single model.
    """
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

    # Inject ensemble configuration
    if ensemble_models:
        strategy_config["ensemble_models"] = ensemble_models
        if strategy_config.get("entry", {}).get("params"):
            strategy_config["entry"]["params"]["ensemble_models"] = ensemble_models

    model_path = Path(strategy_config.get("model_path", ""))
    if not ensemble_models and not model_path.exists():
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
    weights: list[float] | None = None,
) -> None:
    """Run A/B comparison: single model vs ensemble."""
    # Prepare ensemble configs with optional weight override
    ensemble_configs = []
    for i, cfg in enumerate(ENSEMBLE_CONFIGS):
        entry = dict(cfg)
        if weights and i < len(weights):
            entry["weight"] = weights[i]
        ensemble_configs.append(entry)

    single_results = {}
    ensemble_results = {}

    for asset in assets:
        print(f"\n{'='*60}")
        print(f"  {asset}: Running single model (baseline)...")
        print(f"{'='*60}")
        single_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            ensemble_models=None,
        )

        print(f"\n  {asset}: Running ensemble (4 models)...")
        ensemble_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            ensemble_models=ensemble_configs,
        )

    # Print comparison table
    print("\n")
    print("=" * 85)
    print("  ENSEMBLE COMPARISON: Single Model vs Temporal Ensemble")
    print("=" * 85)

    # Show ensemble weights
    print(f"\n  Ensemble: ", end="")
    for cfg in ensemble_configs:
        name = Path(cfg["model_path"]).parent.name
        print(f"{name}(w={cfg['weight']:.1f}) ", end="")
    print("\n")

    header = f"{'Asset':<8} {'Metric':<14} {'Single':>12} {'Ensemble':>12} {'Delta':>10}"
    print(header)
    print("-" * 85)

    portfolio_single_return = 0.0
    portfolio_ensemble_return = 0.0

    for asset in assets:
        s = single_results.get(asset, {}).get("metrics", {})
        e = ensemble_results.get(asset, {}).get("metrics", {})

        if not s or not e:
            print(f"{asset:<8} {'SKIPPED':<14}")
            continue

        for metric, label, fmt in [
            ("total_return", "Return", "{:+.1f}%"),
            ("mdd", "MDD", "{:.1f}%"),
            ("sharpe", "Sharpe", "{:.2f}"),
        ]:
            s_val = s.get(metric, 0)
            e_val = e.get(metric, 0)
            delta = e_val - s_val

            s_str = fmt.format(s_val)
            e_str = fmt.format(e_val)
            delta_str = fmt.format(delta)

            print(f"{asset if metric == 'total_return' else '':<8} {label:<14} {s_str:>12} {e_str:>12} {delta_str:>10}")

        # Calmar ratio
        s_calmar = abs(s.get("total_return", 0) / s.get("mdd", -1)) if s.get("mdd", 0) != 0 else 0
        e_calmar = abs(e.get("total_return", 0) / e.get("mdd", -1)) if e.get("mdd", 0) != 0 else 0
        delta_calmar = e_calmar - s_calmar
        print(f"{'':8} {'Calmar':<14} {s_calmar:>11.2f}x {e_calmar:>11.2f}x {delta_calmar:>+9.2f}x")

        # Trade count
        s_trades = s.get("num_trades", 0)
        e_trades = e.get("num_trades", 0)
        print(f"{'':8} {'Trades':<14} {s_trades:>12} {e_trades:>12} {e_trades - s_trades:>+10}")
        print()

        portfolio_single_return += s.get("total_return", 0)
        portfolio_ensemble_return += e.get("total_return", 0)

    # Portfolio summary
    n = len([a for a in assets if single_results.get(a, {}).get("metrics")])
    if n > 0:
        print("-" * 85)
        avg_s = portfolio_single_return / n
        avg_e = portfolio_ensemble_return / n
        print(f"{'PORTFOLIO':<8} {'Avg Return':<14} {avg_s:>+11.1f}% {avg_e:>+11.1f}% {avg_e-avg_s:>+9.1f}%")

    # Per-year breakdown
    if by_year:
        for asset in assets:
            for label, results in [("Single", single_results), ("Ensemble", ensemble_results)]:
                eq = results.get(asset, {}).get("equity_curve")
                if eq is not None and not eq.empty:
                    print(f"\n--- {asset} {label} Per-Year ---")
                    print_yearly_table(eq)


def main():
    parser = argparse.ArgumentParser(description="Ensemble A/B Comparison")
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
    parser.add_argument(
        "--weights", nargs=4, type=float,
        help="Custom weights for 4 ensemble models (bwin3, bwin4, bwin5, bwin7)",
    )

    args = parser.parse_args()

    run_comparison(
        assets=args.assets,
        config_path=args.config,
        capital_per_asset=args.capital,
        start_date=args.start_date,
        end_date=args.end_date,
        by_year=args.by_year,
        weights=args.weights,
    )


if __name__ == "__main__":
    main()
