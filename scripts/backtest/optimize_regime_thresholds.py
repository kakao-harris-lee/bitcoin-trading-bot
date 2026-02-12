#!/usr/bin/env python3
"""
Optimize regime classification thresholds via Optuna.

Runs Optuna directly (no Quant Lab worker needed) to find optimal
MFI/ADX thresholds for the 7-level regime classification per asset.

Usage:
    python scripts/backtest/optimize_regime_thresholds.py --symbol BTC --n-trials 200
    python scripts/backtest/optimize_regime_thresholds.py --symbol ETH --n-trials 100 --strategy mlp_direction
    python scripts/backtest/optimize_regime_thresholds.py --symbol BTC --apply  # apply best to allocation.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import optuna

from scripts.backtest._common import load_data, compute_metrics, get_db_path
from scripts.backtest.backtest_mlp import (
    load_strategy_config,
    MLPDirectionBacktester,
)

# Regime threshold search space (matches search_space.py)
REGIME_THRESHOLD_SPACE = {
    "mfi_bull_strong": (50.0, 60.0),
    "mfi_bull_moderate": (50.0, 60.0),
    "mfi_sideways_up": (45.0, 55.0),
    "mfi_bear_moderate": (35.0, 48.0),
    "mfi_bear_strong": (28.0, 42.0),
    "adx_strong_trend": (18.0, 32.0),
    "adx_moderate_trend": (12.0, 25.0),
}


def create_objective(
    symbol: str,
    config_path: str,
    start_date: str,
    end_date: str,
):
    """Create Optuna objective that optimises regime thresholds for MLP strategy."""

    # Load base config once
    allocation, strategy_id, strategy_config = load_strategy_config(
        config_path=config_path, symbol=symbol, mode="paper",
    )

    # Resolve data path
    db_path = get_db_path(symbol)
    df_raw = load_data(db_path, "minute240", start_date, end_date, exchange="binance")
    if df_raw.empty:
        raise ValueError(f"No data for {symbol} ({start_date} to {end_date})")

    # Prepare data once (indicators + MLP features)
    backtester_template = MLPDirectionBacktester(
        symbol=symbol,
        config=strategy_config,
    )
    df = backtester_template.prepare_data(df_raw)

    def objective(trial: optuna.Trial) -> float:
        """Maximise Sharpe ratio by tuning regime thresholds."""
        # Sample thresholds
        regime_thresholds = {}
        for name, (lo, hi) in REGIME_THRESHOLD_SPACE.items():
            regime_thresholds[name] = trial.suggest_float(name, lo, hi)

        # Inject thresholds into strategy config copy
        trial_config = dict(strategy_config)
        trial_config["regime_thresholds"] = regime_thresholds

        bt = MLPDirectionBacktester(
            symbol=symbol,
            config=trial_config,
        )

        from core.component_adapter import ComponentStrategyAdapter
        from trading.strategies.components.strategy_factory import StrategyFactory

        factory = StrategyFactory(redis=None)
        adapter = ComponentStrategyAdapter(
            factory=factory,
            strategy_name="mlp_direction",
            config=trial_config,
        )
        adapter.symbol = symbol
        adapter.precompute_mlp_predictions(df)

        from core.backtester import Backtester

        backtester = Backtester(
            initial_capital=10_000,
            fee_rate=0.001,
            slippage=0.0005,
        )

        try:
            results = backtester.run(df, adapter)
        except Exception as e:
            print(f"  Trial {trial.number} failed: {e}")
            return -999.0

        total_return = results.get("total_return", 0.0)
        sharpe = results.get("sharpe_ratio", 0.0)
        n_trades = results.get("trade_count", 0)

        # Report intermediate values for pruning
        trial.set_user_attr("total_return", total_return)
        trial.set_user_attr("sharpe", sharpe)
        trial.set_user_attr("n_trades", n_trades)
        trial.set_user_attr("max_drawdown", results.get("max_drawdown_pct", 0.0))

        # Penalise too few trades (< 10 trades in 6 years is suspicious)
        if n_trades < 10:
            return sharpe * 0.5

        return sharpe

    return objective


def apply_best_to_allocation(best_params: dict, config_path: str) -> None:
    """Write best regime thresholds to allocation.json defaults."""
    with open(config_path) as f:
        allocation = json.load(f)

    # Filter to only regime threshold keys
    thresholds = {
        k: round(v, 2) for k, v in best_params.items()
        if k in REGIME_THRESHOLD_SPACE
    }

    allocation.setdefault("defaults", {})["regime_thresholds"] = thresholds

    with open(config_path, "w") as f:
        json.dump(allocation, f, indent=2)
        f.write("\n")

    print(f"\nApplied thresholds to {config_path}:")
    for k, v in sorted(thresholds.items()):
        print(f"  {k}: {v}")


def main():
    parser = argparse.ArgumentParser(description="Optimize regime thresholds via Optuna")
    parser.add_argument("--symbol", default="BTC", help="Asset symbol (BTC/ETH/SOL)")
    parser.add_argument("--n-trials", type=int, default=200, help="Number of Optuna trials")
    parser.add_argument("--start-date", default="2020-01-01", help="Backtest start date")
    parser.add_argument("--end-date", default="2026-02-01", help="Backtest end date")
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "config" / "strategies" / "allocation.json"),
        help="Path to allocation.json",
    )
    parser.add_argument("--apply", action="store_true", help="Apply best params to allocation.json")
    parser.add_argument("--study-name", default=None, help="Optuna study name (for persistence)")
    parser.add_argument("--db", default=None, help="Optuna storage URL (sqlite:///study.db)")
    args = parser.parse_args()

    print(f"=== Regime Threshold Optimization: {args.symbol} ===")
    print(f"Period: {args.start_date} to {args.end_date}")
    print(f"Trials: {args.n_trials}")

    objective = create_objective(
        symbol=args.symbol,
        config_path=args.config,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    study_name = args.study_name or f"regime_thresholds_{args.symbol.lower()}"
    storage = args.db

    study = optuna.create_study(
        study_name=study_name,
        storage=storage,
        direction="maximize",
        load_if_exists=True,
    )

    study.optimize(objective, n_trials=args.n_trials, show_progress_bar=True)

    # Print results
    best = study.best_trial
    print(f"\n{'='*60}")
    print(f"Best trial #{best.number}: Sharpe = {best.value:.4f}")
    print(f"  Total return: {best.user_attrs.get('total_return', 'N/A'):.1f}%")
    print(f"  Max drawdown: {best.user_attrs.get('max_drawdown', 'N/A'):.1f}%")
    print(f"  Trades: {best.user_attrs.get('n_trades', 'N/A')}")
    print(f"\nBest thresholds:")
    for k in sorted(REGIME_THRESHOLD_SPACE.keys()):
        default = {
            "mfi_bull_strong": 54.0, "mfi_bull_moderate": 54.0,
            "mfi_sideways_up": 49.0, "mfi_bear_moderate": 41.0,
            "mfi_bear_strong": 34.0, "adx_strong_trend": 25.0,
            "adx_moderate_trend": 18.0,
        }
        v = best.params.get(k, default[k])
        d = default[k]
        delta = v - d
        print(f"  {k}: {v:.2f} (default: {d:.1f}, delta: {delta:+.2f})")

    if args.apply:
        apply_best_to_allocation(best.params, args.config)


if __name__ == "__main__":
    main()
