#!/usr/bin/env python3
"""Optuna optimization for v35_long_v2 global adapter parameters.

Optimizes parameters like:
- cash_below_ema200, cash_in_bear (entry filters)
- leverage_sideways, leverage_bear (dynamic leverage)
- atr_stop_multiplier, atr_stop_min_pct, atr_stop_max_pct (stop loss)
- max_consecutive_losses, loss_pause_candles (pause settings)
- bull_prob_threshold, trailing_activation, trailing_distance (entry/exit)

Uses Optuna for Bayesian optimization and MLflow for experiment tracking.

Usage:
    python scripts/optimize_v35_global_params.py --trials 100
    python scripts/optimize_v35_global_params.py --trials 50 --period 2023-H2
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any, Tuple

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import optuna
from optuna.samplers import TPESampler
import pandas as pd

from core.data_loader import DataLoader
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.indicators import add_all_indicators

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Pre-defined test periods
PERIODS = {
    "2020-2024": ("2020-01-01", "2024-12-31", "Full 5 Years (2020-2024)"),
    "2022": ("2022-01-01", "2022-12-31", "2022 Bear Market"),
    "2023-H1": ("2023-01-01", "2023-06-30", "2023 H1 Bull"),
    "2023-H2": ("2023-07-01", "2023-12-31", "2023 H2 Recovery"),
    "2023": ("2023-01-01", "2023-12-31", "2023 Full Year"),
    "2024": ("2024-01-01", "2024-12-31", "2024 Bull Market"),
    "full": ("2022-01-01", "2024-12-31", "Full History (2022-2024)"),
}


def run_backtest(
    config: Dict[str, Any],
    df: pd.DataFrame,
    initial_capital: float = 10000,
    leverage: float = 3.0,
    fee_rate: float = 0.0005,
    slippage: float = 0.0004,
) -> Dict[str, float]:
    """Run backtest with given config and return metrics."""

    factory = StrategyFactory()
    adapter = ComponentStrategyAdapter(factory, "v35_long_v2", config)
    adapter.symbol = "BTC"

    capital = initial_capital
    position_size = 0.0
    entry_price = 0.0
    position_leverage = leverage
    equity_curve = []
    exit_trades = []

    for i in range(len(df)):
        row = df.iloc[i]

        # Calculate equity BEFORE calling adapter (enables drawdown protection)
        current_equity = capital
        if position_size > 0:
            pnl_ratio = (row["close"] - entry_price) / entry_price
            unrealized_pnl = position_size * pnl_ratio
            current_equity += (position_size / position_leverage) + unrealized_pnl

        # Update adapter with current equity for drawdown protection
        adapter.update_equity(current_equity)

        signal = adapter(df, i)
        action = signal.get("action", "hold")
        equity_curve.append(current_equity)

        if action == "buy" and position_size == 0:
            effective_leverage = signal.get("leverage", leverage)
            margin = capital * 0.95 / (1 + effective_leverage * fee_rate)
            effective_pos_size = margin * effective_leverage
            fee = effective_pos_size * fee_rate
            if capital >= (margin + fee):
                capital -= margin + fee
                position_size = effective_pos_size
                position_leverage = effective_leverage
                entry_price = row["close"] * (1 + slippage)

        elif action == "sell" and position_size > 0:
            exit_fraction = signal.get("fraction", 1.0)
            exit_size = position_size * exit_fraction

            exit_price = row["close"] * (1 - slippage)
            pnl_ratio = (exit_price - entry_price) / entry_price
            pnl = exit_size * pnl_ratio
            fee = exit_size * fee_rate
            capital += (exit_size / position_leverage) + pnl - fee
            exit_trades.append({"pnl": pnl, "pnl_pct": pnl_ratio * 100})

            # Handle partial vs full exit
            if exit_fraction >= 1.0:
                position_size = 0.0
            else:
                position_size -= exit_size

    # Final equity
    final_equity = capital
    if position_size > 0:
        final_price = df.iloc[-1]["close"]
        pnl_ratio = (final_price - entry_price) / entry_price
        final_equity += (position_size / position_leverage) + position_size * pnl_ratio

    # Metrics
    total_return = ((final_equity - initial_capital) / initial_capital) * 100
    wins = [t for t in exit_trades if t["pnl"] > 0]
    win_rate = (len(wins) / len(exit_trades) * 100) if exit_trades else 0

    # Max drawdown
    peak = equity_curve[0]
    max_dd = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Sharpe-like ratio (simplified)
    if exit_trades:
        returns = [t["pnl_pct"] for t in exit_trades]
        avg_return = sum(returns) / len(returns)
        std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5
        sharpe = avg_return / std_return if std_return > 0 else 0
    else:
        sharpe = 0

    return {
        "total_return": total_return,
        "win_rate": win_rate,
        "max_drawdown": max_dd,
        "sharpe": sharpe,
        "trades": len(exit_trades),
    }


def create_objective(df: pd.DataFrame, base_config: Dict[str, Any]):
    """Create Optuna objective function."""

    def objective(trial: optuna.Trial) -> Tuple[float, float, float]:
        """Multi-objective: maximize return, maximize win rate, minimize drawdown."""

        # Sample global parameters
        config = base_config.copy()

        # Entry filters (categorical)
        config["cash_below_ema200"] = trial.suggest_categorical(
            "cash_below_ema200", [True, False]
        )
        config["cash_in_bear"] = trial.suggest_categorical("cash_in_bear", [True, False])

        # Dynamic leverage
        config["leverage_sideways"] = trial.suggest_float(
            "leverage_sideways", 0.5, 2.0, step=0.25
        )
        config["leverage_bear"] = trial.suggest_float(
            "leverage_bear", 0.0, 1.0, step=0.25
        )

        # ATR stop loss parameters
        config["atr_stop_multiplier"] = trial.suggest_float(
            "atr_stop_multiplier", 2.0, 5.0, step=0.5
        )
        config["atr_stop_min_pct"] = trial.suggest_float(
            "atr_stop_min_pct", 1.5, 3.5, step=0.5
        )
        config["atr_stop_max_pct"] = trial.suggest_float(
            "atr_stop_max_pct", 5.0, 10.0, step=1.0
        )

        # Consecutive loss settings
        config["max_consecutive_losses"] = trial.suggest_int(
            "max_consecutive_losses", 2, 5
        )
        config["loss_pause_candles"] = trial.suggest_int(
            "loss_pause_candles", 12, 72, step=12
        )

        # Entry/exit thresholds
        config["bull_prob_threshold"] = trial.suggest_float(
            "bull_prob_threshold", 0.4, 0.7, step=0.05
        )
        config["trailing_activation"] = trial.suggest_float(
            "trailing_activation", 1.0, 3.0, step=0.5
        )
        config["trailing_distance"] = trial.suggest_float(
            "trailing_distance", 0.5, 2.5, step=0.5
        )

        # Run backtest
        try:
            metrics = run_backtest(config, df)

            # Log intermediate values for tracking
            trial.set_user_attr("trades", metrics["trades"])
            trial.set_user_attr("sharpe", metrics["sharpe"])

            # Multi-objective: return, win_rate, -drawdown
            return (
                metrics["total_return"],
                metrics["win_rate"],
                -metrics["max_drawdown"],  # Minimize drawdown
            )
        except Exception as e:
            logger.warning(f"Trial failed: {e}")
            return float("-inf"), 0.0, float("-inf")

    return objective


def main():
    parser = argparse.ArgumentParser(
        description="Optimize v35_long_v2 global parameters with Optuna"
    )
    parser.add_argument(
        "--trials", type=int, default=100, help="Number of optimization trials"
    )
    parser.add_argument(
        "--period",
        type=str,
        default="2023-H2",
        choices=list(PERIODS.keys()),
        help="Test period",
    )
    parser.add_argument(
        "--study-name",
        type=str,
        default="v35_global_params",
        help="Optuna study name",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="web/quant_lab_studies.db",
        help="SQLite database for study storage",
    )
    args = parser.parse_args()

    # Get period dates
    start_date, end_date, period_name = PERIODS[args.period]
    logger.info(f"Optimizing for period: {period_name} ({start_date} to {end_date})")

    # Load data
    logger.info("Loading data...")
    with DataLoader() as loader:
        df = loader.load_timeframe("minute60", start_date, end_date)

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.index = df["timestamp"]
    add_all_indicators(df)
    logger.info(f"Loaded {len(df)} candles")

    # Base config (fixed parameters)
    base_config = {
        "regime_version": "v2",
        "dynamic_leverage": True,
        "leverage_bull_strong": 3.0,
        "leverage_bull_moderate": 2.0,
        "atr_stop_enabled": True,
        "trailing_enabled": True,
        "drawdown_warning_pct": 8.0,
        "drawdown_reduce_pct": 10.0,
        "drawdown_exit_pct": 12.0,
        "v2_exit_on_filter": False,
        "panic_sell_below_ma120": False,
        "use_rf_probability": False,  # Disabled for faster backtesting
    }

    # Create or load study
    storage = f"sqlite:///{args.db_path}"
    study = optuna.create_study(
        study_name=f"{args.study_name}_{args.period}",
        storage=storage,
        directions=["maximize", "maximize", "maximize"],  # return, win_rate, -drawdown
        sampler=TPESampler(seed=42),
        load_if_exists=True,
    )

    # Create objective
    objective = create_objective(df, base_config)

    # Run optimization
    logger.info(f"Starting optimization with {args.trials} trials...")
    study.optimize(objective, n_trials=args.trials, show_progress_bar=True)

    # Get Pareto front
    logger.info("\n" + "=" * 70)
    logger.info("PARETO-OPTIMAL SOLUTIONS")
    logger.info("=" * 70)

    pareto_trials = study.best_trials
    for i, trial in enumerate(pareto_trials[:5]):
        logger.info(f"\nSolution {i+1}:")
        logger.info(f"  Return: {trial.values[0]:+.1f}%")
        logger.info(f"  Win Rate: {trial.values[1]:.1f}%")
        logger.info(f"  Max DD: {-trial.values[2]:.1f}%")
        logger.info(f"  Trades: {trial.user_attrs.get('trades', 'N/A')}")
        logger.info("  Parameters:")
        for k, v in trial.params.items():
            logger.info(f"    {k}: {v}")

    # Export best config
    if pareto_trials:
        best = pareto_trials[0]
        best_config = {**base_config, **best.params}

        output_path = PROJECT_ROOT / f"config/tuned/v35_global_{args.period}.json"
        output_path.parent.mkdir(exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(best_config, f, indent=2)

        logger.info(f"\nBest config saved to: {output_path}")

        # Print allocation.json-ready format
        logger.info("\n" + "=" * 70)
        logger.info("RECOMMENDED allocation.json CHANGES:")
        logger.info("=" * 70)
        for k, v in best.params.items():
            logger.info(f'      "{k}": {json.dumps(v)},')


if __name__ == "__main__":
    main()
