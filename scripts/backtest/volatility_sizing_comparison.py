#!/usr/bin/env python3
"""
Volatility Sizing A/B Comparison Backtest.

Runs MLP Direction strategy twice per asset:
  1. Baseline: volatility_sizing.enabled = false (current behavior)
  2. Vol-sized: volatility_sizing.enabled = true

Compares: Total Return, Max Drawdown, Sharpe, Calmar Ratio, per-year returns.

Usage:
    python scripts/backtest/volatility_sizing_comparison.py
    python scripts/backtest/volatility_sizing_comparison.py --assets BTC ETH SOL
    python scripts/backtest/volatility_sizing_comparison.py --by-year
    python scripts/backtest/volatility_sizing_comparison.py --target-vol 0.03
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
    "XRP": ("data/binance_xrp.db", "XRP"),
}

MLP_STRATEGY_IDS = {
    "BTC": "mlp_direction_btc",
    "ETH": "mlp_direction_eth",
    "SOL": "mlp_direction_sol",
    "XRP": "mlp_direction_xrp",
}


def run_single_asset(
    asset: str,
    config_path: str,
    capital: float,
    start_date: str,
    end_date: str,
    vol_sizing_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run MLP Direction backtest for a single asset with optional vol sizing override.

    Args:
        asset: Trading symbol (BTC, ETH, SOL).
        config_path: Path to allocation.json.
        capital: Initial capital.
        start_date: Backtest start date.
        end_date: Backtest end date.
        vol_sizing_override: Override for volatility_sizing config (None = use allocation.json).

    Returns:
        Results dict with equity_curve, metrics, etc.
    """
    db_file, symbol = ASSET_DB[asset]
    db_path = str(PROJECT_ROOT / db_file)

    # Load strategy config
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

    # Apply vol sizing override
    if vol_sizing_override is not None:
        strategy_config["volatility_sizing"] = vol_sizing_override

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
    target_vol: float = 0.02,
    min_scale: float = 0.25,
    max_scale: float = 1.0,
    by_year: bool = False,
) -> None:
    """Run A/B comparison: baseline vs vol-sized, per asset and portfolio.

    Args:
        assets: List of assets to backtest.
        config_path: Path to allocation.json.
        capital_per_asset: Capital allocated per asset.
        start_date: Backtest start date.
        end_date: Backtest end date.
        target_vol: Target volatility for vol sizing.
        min_scale: Minimum scale factor.
        max_scale: Maximum scale factor.
        by_year: Whether to show per-year breakdown.
    """
    baseline_results = {}
    volsized_results = {}

    vol_config_off = {"enabled": False}
    vol_config_on = {
        "enabled": True,
        "target_vol": target_vol,
        "min_scale": min_scale,
        "max_scale": max_scale,
    }

    for asset in assets:
        print(f"\n{'='*60}")
        print(f"  {asset}: Running baseline (no vol sizing)...")
        print(f"{'='*60}")
        baseline_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            vol_sizing_override=vol_config_off,
        )

        print(f"\n  {asset}: Running vol-sized (target={target_vol*100:.1f}%)...")
        volsized_results[asset] = run_single_asset(
            asset, config_path, capital_per_asset, start_date, end_date,
            vol_sizing_override=vol_config_on,
        )

    # Print comparison table
    print("\n")
    print("=" * 80)
    print("  VOLATILITY SIZING COMPARISON")
    print(f"  target_vol={target_vol*100:.1f}%, min_scale={min_scale}, max_scale={max_scale}")
    print("=" * 80)

    header = f"{'Asset':<8} {'Metric':<14} {'Baseline':>12} {'Vol-Sized':>12} {'Delta':>10}"
    print(header)
    print("-" * 80)

    portfolio_baseline_return = 0.0
    portfolio_volsized_return = 0.0

    for asset in assets:
        bl = baseline_results.get(asset, {}).get("metrics", {})
        vs = volsized_results.get(asset, {}).get("metrics", {})

        if not bl or not vs:
            print(f"{asset:<8} {'SKIPPED':<14}")
            continue

        for metric, label, fmt in [
            ("total_return", "Return", "{:+.1f}%"),
            ("mdd", "MDD", "{:.1f}%"),
            ("sharpe", "Sharpe", "{:.2f}"),
        ]:
            bl_val = bl.get(metric, 0)
            vs_val = vs.get(metric, 0)
            delta = vs_val - bl_val

            bl_str = fmt.format(bl_val)
            vs_str = fmt.format(vs_val)
            delta_str = fmt.format(delta)

            print(f"{asset if metric == 'total_return' else '':<8} {label:<14} {bl_str:>12} {vs_str:>12} {delta_str:>10}")

        # Calmar ratio (return / abs(mdd))
        bl_calmar = abs(bl.get("total_return", 0) / bl.get("mdd", -1)) if bl.get("mdd", 0) != 0 else 0
        vs_calmar = abs(vs.get("total_return", 0) / vs.get("mdd", -1)) if vs.get("mdd", 0) != 0 else 0
        delta_calmar = vs_calmar - bl_calmar
        print(f"{'':8} {'Calmar':<14} {bl_calmar:>11.2f}x {vs_calmar:>11.2f}x {delta_calmar:>+9.2f}x")
        print()

        portfolio_baseline_return += bl.get("total_return", 0)
        portfolio_volsized_return += vs.get("total_return", 0)

    # Portfolio summary (equal-weight)
    n = len([a for a in assets if baseline_results.get(a, {}).get("metrics")])
    if n > 0:
        print("-" * 80)
        avg_bl = portfolio_baseline_return / n
        avg_vs = portfolio_volsized_return / n
        print(f"{'PORTFOLIO':<8} {'Avg Return':<14} {avg_bl:>+11.1f}% {avg_vs:>+11.1f}% {avg_vs-avg_bl:>+9.1f}%")

    # Per-year breakdown
    if by_year:
        for asset in assets:
            for label, results in [("Baseline", baseline_results), ("Vol-Sized", volsized_results)]:
                eq = results.get(asset, {}).get("equity_curve")
                if eq is not None and not eq.empty:
                    print(f"\n--- {asset} {label} Per-Year ---")
                    print_yearly_table(eq)


def main():
    parser = argparse.ArgumentParser(description="Volatility Sizing A/B Comparison")
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
        "--target-vol", type=float, default=0.02,
        help="Target volatility (0.02 = 2%%)",
    )
    parser.add_argument(
        "--min-scale", type=float, default=0.25,
        help="Minimum position scale factor",
    )
    parser.add_argument(
        "--max-scale", type=float, default=1.0,
        help="Maximum position scale factor",
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
        target_vol=args.target_vol,
        min_scale=args.min_scale,
        max_scale=args.max_scale,
        by_year=args.by_year,
    )


if __name__ == "__main__":
    main()
