#!/usr/bin/env python3
"""
Optimize regime classification thresholds via Optuna.

Runs Optuna directly (no Quant Lab worker needed) to find optimal
MFI/ADX thresholds for the 7-level regime classification per asset.

Usage:
    python scripts/backtest/optimize_regime_thresholds.py --symbol BTC --n-trials 200
    python scripts/backtest/optimize_regime_thresholds.py --symbol ETH --n-trials 100
    python scripts/backtest/optimize_regime_thresholds.py --symbol BTC --apply  # apply best to allocation.json
"""
# pylint: disable=broad-exception-caught

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import optuna
import pandas as pd

from scripts.backtest._common import load_data, compute_metrics, compute_trade_stats
from scripts.backtest.backtest_mlp import MLPDirectionBacktester
from scripts.backtest.regime_ablation import (
    _load_allocation,
    _get_mlp_config,
    ASSET_DB,
)
from core.backtester import Backtester
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory

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

DEFAULTS = {
    "mfi_bull_strong": 54.0,
    "mfi_bull_moderate": 54.0,
    "mfi_sideways_up": 49.0,
    "mfi_bear_moderate": 41.0,
    "mfi_bear_strong": 34.0,
    "adx_strong_trend": 25.0,
    "adx_moderate_trend": 18.0,
}


def create_objective(
    symbol: str,
    start_date: str,
    end_date: str,
):
    """Create Optuna objective that optimises regime thresholds for MLP strategy."""

    # Load base config from allocation.json (same as regime_ablation)
    alloc = _load_allocation()
    base_config = _get_mlp_config(symbol, alloc)
    if not base_config:
        raise ValueError(f"No MLP config found for {symbol} in allocation.json")

    # Resolve data path
    if symbol not in ASSET_DB:
        raise ValueError(f"Unknown symbol: {symbol}. Must be one of {list(ASSET_DB)}")
    db_path = str(PROJECT_ROOT / ASSET_DB[symbol])

    # Load data with warmup
    warmup_start = str(pd.Timestamp(start_date) - pd.DateOffset(months=3))
    df_raw = load_data(db_path, "minute240", warmup_start, end_date, exchange="binance")
    if df_raw.empty:
        raise ValueError(f"No data for {symbol} ({start_date} to {end_date})")

    # Prepare data once (indicators + MLP features)
    mlp_bt = MLPDirectionBacktester(symbol=symbol, config=base_config)
    df_prepared = mlp_bt.prepare_data(df_raw)

    # Find warmup trim point
    eval_start = 0
    if "timestamp" in df_prepared.columns:
        start_ts = pd.Timestamp(start_date)
        mask = pd.to_datetime(df_prepared["timestamp"]) >= start_ts
        if mask.any():
            eval_start = mask.idxmax()

    print(f"Data: {len(df_prepared):,} rows ({len(df_prepared) - eval_start:,} eval)")

    def objective(trial: optuna.Trial) -> float:
        """Maximise Sharpe ratio by tuning regime thresholds."""
        # Sample thresholds
        regime_thresholds = {}
        for name, (lo, hi) in REGIME_THRESHOLD_SPACE.items():
            regime_thresholds[name] = trial.suggest_float(name, lo, hi)

        # Inject thresholds into strategy config copy
        trial_config = copy.deepcopy(base_config)
        trial_config["regime_thresholds"] = regime_thresholds

        factory = StrategyFactory(redis=None)
        adapter = ComponentStrategyAdapter(
            factory=factory,
            strategy_name="mlp_direction",
            config=trial_config,
        )
        adapter.symbol = symbol
        adapter.precompute_mlp_predictions(df_prepared)

        # Trim warmup + remap MLP cache
        df_eval = df_prepared
        if eval_start > 0:
            mlp_cache = getattr(adapter, "_mlp_cache", None)
            if mlp_cache:
                remapped = {}
                for old_idx, val in mlp_cache.items():
                    new_idx = old_idx - eval_start
                    if new_idx >= 0:
                        remapped[new_idx] = val
                setattr(adapter, "_mlp_cache", remapped)
            df_eval = df_prepared.iloc[eval_start:].reset_index(drop=True)

        bt = Backtester(initial_capital=10_000, fee_rate=0.001, slippage=0.0002)

        try:
            results = bt.run(df_eval, adapter, {})
        except Exception as e:
            print(f"  Trial {trial.number} failed: {e}")
            return -999.0

        metrics = compute_metrics(results.get("equity_curve"), timeframe="minute240")
        trade_stats = compute_trade_stats(results)

        total_return = metrics.get("total_return", 0.0)
        sharpe = metrics.get("sharpe", 0.0)
        n_trades = trade_stats.get("total_trades", 0)
        mdd = metrics.get("mdd", 0.0)

        trial.set_user_attr("total_return", total_return)
        trial.set_user_attr("sharpe", sharpe)
        trial.set_user_attr("n_trades", n_trades)
        trial.set_user_attr("max_drawdown", mdd)

        # Penalise too few trades (< 10 trades in 6 years is suspicious)
        if n_trades < 10:
            return sharpe * 0.5

        return sharpe

    return objective


def apply_best_to_allocation(best_params: dict, config_path: str) -> None:
    """Write best regime thresholds to allocation.json defaults."""
    with open(config_path, encoding="utf-8") as f:
        allocation = json.load(f)

    # Filter to only regime threshold keys
    thresholds = {
        k: round(v, 2) for k, v in best_params.items()
        if k in REGIME_THRESHOLD_SPACE
    }

    allocation.setdefault("defaults", {})["regime_thresholds"] = thresholds

    with open(config_path, "w", encoding="utf-8") as f:
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
    print(f"  Total return: {best.user_attrs.get('total_return', 0):.1f}%")
    print(f"  Max drawdown: {best.user_attrs.get('max_drawdown', 0):.1f}%")
    print(f"  Trades: {best.user_attrs.get('n_trades', 0)}")
    print("\nBest thresholds vs defaults:")
    for k in sorted(REGIME_THRESHOLD_SPACE.keys()):
        v = best.params.get(k, DEFAULTS[k])
        d = DEFAULTS[k]
        delta = v - d
        print(f"  {k}: {v:.2f} (default: {d:.1f}, delta: {delta:+.2f})")

    if args.apply:
        apply_best_to_allocation(best.params, args.config)


if __name__ == "__main__":
    main()
