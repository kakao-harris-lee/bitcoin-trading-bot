#!/usr/bin/env python3
"""
Bear Short Strategy - Optuna Optimization

Optimizes bear_short parameters using Optuna with train/OOS validation.

Parameters optimized:
  - volume_ratio_threshold (entry): volume confirmation threshold
  - stop_loss_pct (exit): stop loss percentage
  - take_profit_pct (exit): take profit percentage

Usage:
    python scripts/optimize_bear_short.py
    python scripts/optimize_bear_short.py --n-trials 200 --assets BTC ETH SOL
    python scripts/optimize_bear_short.py --train-end 2023-12-31 --oos-start 2024-01-01
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.component_adapter import ComponentStrategyAdapter
from core.data_loader import DataLoader
from scripts.backtest._common import ShortMarginBacktester, compute_metrics
from trading.indicators import add_all_indicators
from trading.strategies.components.strategy_factory import StrategyFactory

# Suppress Optuna info logs
optuna.logging.set_verbosity(optuna.logging.WARNING)

ASSET_DB = {
    "BTC": ("data/binance_bitcoin.db", "BTC"),
    "ETH": ("data/binance_ethereum.db", "ETH"),
    "SOL": ("data/binance_solana.db", "SOL"),
}


def load_data(asset: str, timeframe: str, start: str, end: str) -> pd.DataFrame:
    """Load and prepare data for an asset."""
    db_rel, _ = ASSET_DB[asset]
    db_path = str(PROJECT_ROOT / db_rel)
    with DataLoader(db_path, exchange="binance") as loader:
        df = loader.load_timeframe(timeframe, start, end)
    if not df.empty:
        df = add_all_indicators(df)
    return df


def run_backtest(
    df: pd.DataFrame,
    symbol: str,
    config: dict[str, Any],
    capital: float = 10_000,
) -> dict[str, float]:
    """Run a single backtest and return metrics."""
    factory = StrategyFactory()
    adapter = ComponentStrategyAdapter(
        factory=factory,
        strategy_name="bear_short",
        config=config,
    )
    adapter.symbol = symbol

    cached_df = add_all_indicators(df.copy()) if "mfi" not in df.columns else df

    def strategy_func(df_data, i, params):
        if i < 200:
            return {"action": "hold"}
        return adapter(cached_df, i, params)

    bt = ShortMarginBacktester(
        initial_capital=capital,
        fee_rate=0.0005,
        slippage=0.0002,
        min_order_amount=10,
        action_open="open_short",
        action_close="close_short",
    )
    results = bt.run(df, strategy_func, {})
    metrics = compute_metrics(results.get("equity_curve"), "minute240")

    return {
        "total_return": results.get("total_return", 0.0),
        "total_trades": results.get("total_trades", 0),
        "win_rate": results.get("win_rate", 0.0),
        "profit_factor": results.get("profit_factor", 0.0),
        "sharpe": metrics.get("sharpe", 0.0),
        "mdd": metrics.get("mdd", 0.0),
    }


def build_config(
    volume_ratio_threshold: float,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> dict[str, Any]:
    """Build strategy config from trial parameters."""
    return {
        "market": "futures",
        "leverage": 3,
        "position_pct": 0.90,
        "dynamic_sizing": True,
        "drawdown_enabled": False,
        "stop_loss_cooldown": 0,
        "entry": {
            "class": "BearShortEntryStrategy",
            "params": {
                "volume_ratio_threshold": volume_ratio_threshold,
                "position_size": 0.90,
            },
        },
        "exit": {
            "class": "BearShortExitStrategy",
            "params": {
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct,
            },
        },
    }


def create_objective(
    datasets: dict[str, pd.DataFrame],
    capital: float,
):
    """Create Optuna objective function."""

    def objective(trial: optuna.Trial) -> float:
        # Sample parameters
        volume_ratio = trial.suggest_float("volume_ratio_threshold", 0.8, 3.0, step=0.1)
        stop_loss = trial.suggest_float("stop_loss_pct", 1.0, 8.0, step=0.5)
        take_profit = trial.suggest_float("take_profit_pct", 2.0, 12.0, step=0.5)

        # Constraint: TP must be > SL for positive expectancy
        if take_profit <= stop_loss:
            return -100.0

        config = build_config(volume_ratio, stop_loss, take_profit)

        # Run across all assets, average the results
        returns = []
        total_trades = 0
        sharpes = []

        for asset, df in datasets.items():
            _, symbol = ASSET_DB[asset]
            m = run_backtest(df, symbol, config, capital)
            returns.append(m["total_return"])
            total_trades += m["total_trades"]
            sharpes.append(m["sharpe"])

        avg_return = np.mean(returns)
        avg_sharpe = np.mean(sharpes)

        # Penalize too few trades (< 5/year across all assets)
        if total_trades < 15:
            return -50.0

        # Objective: maximize average Sharpe ratio
        # With a small bonus for positive returns
        score = avg_sharpe + 0.01 * avg_return

        trial.set_user_attr("avg_return", float(avg_return))
        trial.set_user_attr("total_trades", int(total_trades))
        trial.set_user_attr("avg_sharpe", float(avg_sharpe))
        trial.set_user_attr("per_asset_returns", {a: r for a, r in zip(datasets.keys(), returns)})

        return score

    return objective


def main():
    parser = argparse.ArgumentParser(description="Optuna optimization for Bear Short strategy")
    parser.add_argument("--n-trials", type=int, default=100, help="Number of Optuna trials")
    parser.add_argument("--assets", nargs="+", default=["BTC", "ETH", "SOL"])
    parser.add_argument("--timeframe", default="minute240")
    parser.add_argument("--train-start", default="2020-01-01")
    parser.add_argument("--train-end", default="2024-06-30")
    parser.add_argument("--oos-start", default="2024-07-01")
    parser.add_argument("--oos-end", default="2025-12-31")
    parser.add_argument("--capital", type=float, default=10_000)
    args = parser.parse_args()

    print("=" * 70)
    print("BEAR SHORT - OPTUNA OPTIMIZATION")
    print(f"Assets: {', '.join(args.assets)} | Trials: {args.n_trials}")
    print(f"Train: {args.train_start} to {args.train_end}")
    print(f"OOS:   {args.oos_start} to {args.oos_end}")
    print("=" * 70)

    # Load training data
    print("\nLoading training data...")
    train_data = {}
    for asset in args.assets:
        df = load_data(asset, args.timeframe, args.train_start, args.train_end)
        if df.empty:
            print(f"  WARNING: No data for {asset}, skipping")
            continue
        train_data[asset] = df
        print(f"  {asset}: {len(df):,} candles")

    if not train_data:
        print("ERROR: No training data loaded")
        sys.exit(1)

    # Run optimization
    print(f"\nRunning {args.n_trials} trials...")
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
        study_name="bear_short_optimization",
    )
    study.optimize(create_objective(train_data, args.capital), n_trials=args.n_trials, show_progress_bar=True)

    # Show top trials
    print(f"\nCompleted {len(study.trials)} trials")
    trials = sorted(study.trials, key=lambda t: t.value if t.value is not None else -999, reverse=True)

    print(f"\nTop 10 Training Results:")
    print("-" * 90)
    print(f"{'#':<4} {'Score':>8} {'VolRatio':>10} {'SL%':>6} {'TP%':>6} {'Return%':>10} {'Trades':>8} {'Sharpe':>8}")
    print("-" * 90)

    for i, t in enumerate(trials[:10]):
        if t.value is None:
            continue
        p = t.params
        print(
            f"{i+1:<4} {t.value:>8.3f} "
            f"{p['volume_ratio_threshold']:>10.1f} "
            f"{p['stop_loss_pct']:>6.1f} "
            f"{p['take_profit_pct']:>6.1f} "
            f"{t.user_attrs.get('avg_return', 0):>10.2f} "
            f"{t.user_attrs.get('total_trades', 0):>8} "
            f"{t.user_attrs.get('avg_sharpe', 0):>8.3f}"
        )

    # OOS validation on best trial
    best = study.best_trial
    best_params = best.params
    print(f"\n{'='*70}")
    print("BEST TRAINING RESULT")
    print(f"{'='*70}")
    print(f"  volume_ratio_threshold: {best_params['volume_ratio_threshold']:.1f}")
    print(f"  stop_loss_pct:          {best_params['stop_loss_pct']:.1f}")
    print(f"  take_profit_pct:        {best_params['take_profit_pct']:.1f}")
    print(f"  Training score:         {best.value:.4f}")
    print(f"  Training avg return:    {best.user_attrs.get('avg_return', 0):.2f}%")
    print(f"  Training trades:        {best.user_attrs.get('total_trades', 0)}")

    # Load OOS data and validate
    print(f"\n{'='*70}")
    print("OUT-OF-SAMPLE VALIDATION")
    print(f"{'='*70}")

    best_config = build_config(
        best_params["volume_ratio_threshold"],
        best_params["stop_loss_pct"],
        best_params["take_profit_pct"],
    )

    oos_returns = []
    for asset in args.assets:
        df_oos = load_data(asset, args.timeframe, args.oos_start, args.oos_end)
        if df_oos.empty:
            print(f"  {asset}: No OOS data")
            continue
        _, symbol = ASSET_DB[asset]
        m = run_backtest(df_oos, symbol, best_config, args.capital)
        oos_returns.append(m["total_return"])
        print(
            f"  {asset}: Return={m['total_return']:+.2f}%, "
            f"Trades={m['total_trades']}, "
            f"WinRate={m['win_rate']*100:.1f}%, "
            f"Sharpe={m['sharpe']:.3f}, "
            f"MDD={m['mdd']:.2f}%"
        )

    if oos_returns:
        print(f"\n  OOS Average Return: {np.mean(oos_returns):+.2f}%")

    # Save best config
    output = {
        "strategy": "bear_short",
        "optimized_params": {
            "volume_ratio_threshold": best_params["volume_ratio_threshold"],
            "stop_loss_pct": best_params["stop_loss_pct"],
            "take_profit_pct": best_params["take_profit_pct"],
        },
        "training": {
            "period": f"{args.train_start} to {args.train_end}",
            "score": best.value,
            "avg_return": best.user_attrs.get("avg_return", 0),
            "total_trades": best.user_attrs.get("total_trades", 0),
        },
    }

    out_path = PROJECT_ROOT / "config" / "strategies" / "bear_short_optimized.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved optimized params to: {out_path}")


if __name__ == "__main__":
    main()
