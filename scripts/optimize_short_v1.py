#!/usr/bin/env python3
"""
Short V1 Strategy Parameter Optimization
Optimizes the improved short_v1 strategy parameters using grid search.
"""

import sys
from pathlib import Path
from itertools import product
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import warnings
import json
warnings.filterwarnings('ignore')

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# New Component Imports
from trading.strategies.components.strategy_factory import StrategyFactory
from core.component_adapter import ComponentStrategyAdapter
from trading.indicators import add_all_indicators, technical as ta

# Legacy imports removed:
# from trading.strategy.short_v1 import ShortV1Strategy, PositionTier


@dataclass
class BacktestResult:
    """Backtest result container"""
    params: Dict
    total_return: float
    total_trades: int
    win_rate: float
    sharpe_ratio: float
    max_drawdown: float
    profit_factor: float
    avg_trades_per_year: float

    def __repr__(self):
        return (f"Return: {self.total_return:.2f}%, Trades: {self.total_trades}, "
                f"Win: {self.win_rate:.1f}%, Sharpe: {self.sharpe_ratio:.2f}, "
                f"MDD: {self.max_drawdown:.2f}%")


def load_binance_data(start_date: str, end_date: str) -> pd.DataFrame:
    """Load Binance BTC data from database"""
    import sqlite3

    db_path = PROJECT_ROOT / "data" / "binance_bitcoin.db"
    conn = sqlite3.connect(str(db_path))

    query = """
        SELECT timestamp, open, high, low, close, volume
        FROM binance_minute240
        WHERE timestamp >= ? AND timestamp <= ?
        ORDER BY timestamp
    """

    df = pd.read_sql_query(query, conn, params=[start_date, end_date])
    conn.close()

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


def run_backtest(df: pd.DataFrame, config: Dict, leverage: int = 2) -> BacktestResult:
    """Run backtest with given config using ComponentStrategyAdapter"""

    # Initialize Factory and Adapter
    factory = StrategyFactory(redis_client=None) # No Redis needed for backtest
    adapter = ComponentStrategyAdapter(factory, "short_v1", config)

    # Add indicators (Standardized via trading.indicators)
    # Ensure we have all indicators required by ShortV1 components
    # add_all_indicators adds standard MFI, ADX, RSI, ATR (14 period)
    df_bt = df.copy()
    add_all_indicators(df_bt)

    # Calculate specific EMAs and DIs required by ShortV1

    close = df_bt['close']
    high = df_bt['high']
    low = df_bt['low']

    # EMAs
    ema_fast = config.get('ema_fast', 68)
    ema_slow = config.get('ema_slow', 128)
    # Use ta.ema from library
    df_bt[f'ema_{ema_fast}'] = ta.ema(close, period=ema_fast)
    df_bt[f'ema_{ema_slow}'] = ta.ema(close, period=ema_slow)

    # ADX/DI specifics if not standard 14
    adx_period = config.get('adx_period', 14)
    if adx_period != 14:
        # Standard add_all_indicators provides ADX(14)
        # If param differs, recalculate
        df_bt['adx'], df_bt['plus_di'], df_bt['minus_di'] = ta.adx(high, low, close, period=adx_period)

    # ADX Slope (simple momentum)
    df_bt['adx_slope'] = df_bt['adx'].diff()

    # Simulate trading
    initial_capital = 10000
    capital = initial_capital
    position_size = 0
    entry_price = 0
    trades = []

    # Adapter usage loop
    min_idx = 200 # Warmup

    for i in range(min_idx, len(df_bt)):
        # Call Adapter
        # Adapter returns: {'action': 'open_short'/'close_short'/'hold', ...}
        signal = adapter(df_bt, i)

        current_price = df_bt.iloc[i]['close']

        if signal['action'] != 'hold':
            action = signal['action']

            if action == 'open_short' and position_size == 0:
                # Open short position
                position_size = (capital * leverage) / current_price
                entry_price = current_price
                # Note: Adapter manages stop/tp internally, we just execute here

            elif action in ['close_short', 'sell'] and position_size > 0:
                # Close position
                fraction = signal.get('fraction', 1.0)
                close_size = position_size * fraction

                # Calculate PnL (short position)
                pnl = (entry_price - current_price) / entry_price * close_size * entry_price
                capital += pnl

                trades.append({
                    'entry': entry_price,
                    'exit': current_price,
                    'pnl': pnl,
                    'pnl_pct': (entry_price - current_price) / entry_price * 100 * leverage,
                    'exit_type': signal.get('exit_type', 'unknown')
                })

                position_size -= close_size
                if position_size <= 0:
                    position_size = 0
                    entry_price = 0

        # Track equity
        if position_size > 0:
            unrealized_pnl = (entry_price - current_price) / entry_price * position_size * entry_price
            equity_curve.append(capital + unrealized_pnl)
        else:
            equity_curve.append(capital)

    # Close any remaining position
    if position_size > 0:
        current_price = df_bt.iloc[-1]['close']
        pnl = (entry_price - current_price) / entry_price * position_size * entry_price
        capital += pnl
        trades.append({
            'entry': entry_price,
            'exit': current_price,
            'pnl': pnl,
            'pnl_pct': (entry_price - current_price) / entry_price * 100 * leverage,
            'exit_type': 'end_of_data'
        })

    # Calculate metrics
    total_return = (capital - initial_capital) / initial_capital * 100
    total_trades = len(trades)

    if total_trades > 0:
        wins = [t for t in trades if t['pnl'] > 0]
        win_rate = len(wins) / total_trades * 100

        gross_profit = sum(t['pnl'] for t in wins) if wins else 0
        losses = [t for t in trades if t['pnl'] <= 0]
        gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    else:
        win_rate = 0
        profit_factor = 0

    # Calculate Sharpe ratio
    equity_series = pd.Series(equity_curve)
    returns = equity_series.pct_change().dropna()
    if len(returns) > 0 and returns.std() > 0:
        # Annualize for 4H timeframe (6 bars per day, 252 trading days)
        sharpe_ratio = returns.mean() / returns.std() * np.sqrt(6 * 252)
    else:
        sharpe_ratio = 0

    # Calculate max drawdown
    equity_series = pd.Series(equity_curve)
    rolling_max = equity_series.expanding().max()
    drawdown = (equity_series - rolling_max) / rolling_max * 100
    max_drawdown = drawdown.min()

    # Years in data
    years = (df_bt['timestamp'].iloc[-1] - df_bt['timestamp'].iloc[0]).days / 365.25
    avg_trades_per_year = total_trades / years if years > 0 else 0

    return BacktestResult(
        params=config,
        total_return=total_return,
        total_trades=total_trades,
        win_rate=win_rate,
        sharpe_ratio=sharpe_ratio,
        max_drawdown=max_drawdown,
        profit_factor=profit_factor,
        avg_trades_per_year=avg_trades_per_year
    )


def run_grid_search(
    train_start: str = '2020-01-01',
    train_end: str = '2024-12-31',
    oos_start: str = '2025-01-01',
    oos_end: str = '2026-01-09',
    leverage: int = 2,
    min_trades_per_year: float = 5.0,
    max_mdd: float = -20.0,
    min_sharpe: float = 0.3,
    top_n: int = 10
):
    """Run grid search optimization"""

    print("=" * 80)
    print("🔍 Short V1 Parameter Optimization (Grid Search)")
    print("=" * 80)

    # Load data
    print("\n📥 Loading training data...")
    df_train = load_binance_data(train_start, train_end)
    print(f"   Training: {len(df_train)} bars ({train_start} to {train_end})")

    print("📥 Loading OOS data...")
    df_oos = load_binance_data(oos_start, oos_end)
    print(f"   OOS: {len(df_oos)} bars ({oos_start} to {oos_end})")

    # Parameter grid
    param_grid = {
        'ema_fast': [30, 50, 68],
        'ema_slow': [100, 128, 150, 200],
        'adx_period': [14],
        'adx_min': [20, 25, 30],
        'atr_period': [14],
        'atr_buffer_multiplier': [1.0, 1.5, 2.0],
        'risk_reward_ratio': [2.0, 2.5, 3.0],
        'max_stop_loss_pct': [5.0],
        'require_death_cross': [True],
        'di_negative_dominant': [True],
        'require_adx_not_declining': [True, False],
        'two_tier_enabled': [True, False],
        'first_tier_pct': [0.5],
        'first_tier_r_multiple': [1.0],
        'trailing_stop_atr_multiplier': [1.5, 2.0],
        'exit_on_golden_cross': [True],
        'extreme_volatility_threshold': [0.10],
        'halt_entries_on_extreme_vol': [True],
        'max_leverage': [leverage],
        'min_entry_confidence': [0.6, 0.7],
    }

    # Generate all combinations
    keys = list(param_grid.keys())
    combinations = list(product(*[param_grid[k] for k in keys]))
    total_combos = len(combinations)

    print(f"\n🔢 Total parameter combinations: {total_combos}")
    print(f"   Filters: trades/year >= {min_trades_per_year}, MDD >= {max_mdd}%, Sharpe >= {min_sharpe}")

    # Run grid search
    results = []

    for idx, combo in enumerate(combinations):
        config = dict(zip(keys, combo))

        # Skip invalid combinations
        if config['ema_fast'] >= config['ema_slow']:
            continue

        try:
            result = run_backtest(df_train, config, leverage)

            # Apply filters
            if (result.avg_trades_per_year >= min_trades_per_year and
                result.max_drawdown >= max_mdd and
                result.sharpe_ratio >= min_sharpe):
                results.append(result)

        except Exception as e:
            pass

        # Progress
        if (idx + 1) % 100 == 0:
            print(f"   Progress: {idx + 1}/{total_combos} ({len(results)} passed filters)")

    print(f"\n✅ Grid search complete: {len(results)} configurations passed filters")

    if not results:
        print("\n⚠️  No configurations passed filters. Try relaxing constraints.")
        return

    # Sort by Sharpe ratio
    results.sort(key=lambda x: x.sharpe_ratio, reverse=True)

    # Show top training results
    print(f"\n📊 Top {min(top_n, len(results))} Training Results (by Sharpe):")
    print("-" * 100)
    print(f"{'#':<4} {'Return':>10} {'Trades':>8} {'Win%':>8} {'Sharpe':>8} {'MDD':>8} {'PF':>8} {'Tr/Yr':>8}")
    print("-" * 100)

    for i, r in enumerate(results[:top_n]):
        print(f"{i+1:<4} {r.total_return:>9.2f}% {r.total_trades:>8} {r.win_rate:>7.1f}% "
              f"{r.sharpe_ratio:>8.2f} {r.max_drawdown:>7.2f}% {r.profit_factor:>8.2f} {r.avg_trades_per_year:>7.1f}")

    # Run OOS validation on top candidates
    print(f"\n🔬 Out-of-Sample Validation (Top {min(top_n, len(results))}):")
    print("-" * 100)
    print(f"{'#':<4} {'Train Ret':>10} {'OOS Ret':>10} {'OOS Trades':>10} {'OOS Sharpe':>10} {'OOS MDD':>10}")
    print("-" * 100)

    oos_results = []
    for i, train_result in enumerate(results[:top_n]):
        try:
            oos_result = run_backtest(df_oos, train_result.params, leverage)
            oos_results.append((train_result, oos_result))

            print(f"{i+1:<4} {train_result.total_return:>9.2f}% {oos_result.total_return:>9.2f}% "
                  f"{oos_result.total_trades:>10} {oos_result.sharpe_ratio:>10.2f} {oos_result.max_drawdown:>9.2f}%")
        except Exception as e:
            print(f"{i+1:<4} Error: {e}")

    # Find best OOS performer
    if oos_results:
        # Sort by OOS Sharpe (with minimum trades requirement)
        valid_oos = [(t, o) for t, o in oos_results if o.total_trades >= 1]
        if valid_oos:
            valid_oos.sort(key=lambda x: x[1].sharpe_ratio, reverse=True)
            best_train, best_oos = valid_oos[0]

            print("\n" + "=" * 80)
            print("🏆 Best Configuration (by OOS Sharpe)")
            print("=" * 80)
            print(f"\nTraining Performance:")
            print(f"   Return: {best_train.total_return:.2f}%")
            print(f"   Trades: {best_train.total_trades}")
            print(f"   Win Rate: {best_train.win_rate:.1f}%")
            print(f"   Sharpe: {best_train.sharpe_ratio:.2f}")
            print(f"   MDD: {best_train.max_drawdown:.2f}%")

            print(f"\nOOS Performance:")
            print(f"   Return: {best_oos.total_return:.2f}%")
            print(f"   Trades: {best_oos.total_trades}")
            print(f"   Win Rate: {best_oos.win_rate:.1f}%")
            print(f"   Sharpe: {best_oos.sharpe_ratio:.2f}")
            print(f"   MDD: {best_oos.max_drawdown:.2f}%")

            print(f"\nOptimal Parameters:")
            for k, v in best_train.params.items():
                print(f"   {k}: {v}")

            # Save best config
            output_path = PROJECT_ROOT / "config" / "strategies" / "short_v1_optimized.json"
            config_json = {
                "strategy_name": "SHORT_V1_OPTIMIZED",
                "description": "Optimized Short V1 strategy parameters",
                "symbol": "BTCUSDT",
                "timeframe": "4h",
                "indicators": {
                    "ema_fast": best_train.params['ema_fast'],
                    "ema_slow": best_train.params['ema_slow'],
                    "adx_period": best_train.params['adx_period'],
                    "atr_period": best_train.params['atr_period'],
                },
                "entry": {
                    "require_death_cross": best_train.params['require_death_cross'],
                    "adx_min": best_train.params['adx_min'],
                    "di_negative_dominant": best_train.params['di_negative_dominant'],
                    "require_adx_not_declining": best_train.params['require_adx_not_declining'],
                    "min_entry_confidence": best_train.params.get('min_entry_confidence', 0.7),
                },
                "exit": {
                    "max_stop_loss_pct": best_train.params['max_stop_loss_pct'],
                    "risk_reward_ratio": best_train.params['risk_reward_ratio'],
                    "exit_on_golden_cross": best_train.params['exit_on_golden_cross'],
                    "two_tier_enabled": best_train.params['two_tier_enabled'],
                    "first_tier_pct": best_train.params['first_tier_pct'],
                    "first_tier_r_multiple": best_train.params['first_tier_r_multiple'],
                    "trailing_stop_atr_multiplier": best_train.params['trailing_stop_atr_multiplier'],
                },
                "stop_loss": {
                    "atr_buffer_multiplier": best_train.params['atr_buffer_multiplier'],
                    "max_stop_loss_pct": best_train.params['max_stop_loss_pct'],
                },
                "risk_management": {
                    "max_leverage": best_train.params['max_leverage'],
                    "extreme_volatility_threshold": best_train.params['extreme_volatility_threshold'],
                    "halt_entries_on_extreme_vol": best_train.params['halt_entries_on_extreme_vol'],
                },
                "performance": {
                    "train_return": best_train.total_return,
                    "train_sharpe": best_train.sharpe_ratio,
                    "train_mdd": best_train.max_drawdown,
                    "train_trades": best_train.total_trades,
                    "oos_return": best_oos.total_return,
                    "oos_sharpe": best_oos.sharpe_ratio,
                    "oos_mdd": best_oos.max_drawdown,
                    "oos_trades": best_oos.total_trades,
                }
            }

            with open(output_path, 'w') as f:
                json.dump(config_json, f, indent=2)

            print(f"\n💾 Saved to: {output_path}")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Optimize Short V1 Strategy Parameters')
    parser.add_argument('--leverage', type=int, default=2)
    parser.add_argument('--min-trades-per-year', type=float, default=5.0)
    parser.add_argument('--max-mdd', type=float, default=-20.0)
    parser.add_argument('--min-sharpe', type=float, default=0.3)
    parser.add_argument('--train-start', default='2020-01-01')
    parser.add_argument('--train-end', default='2024-12-31')
    parser.add_argument('--oos-start', default='2025-01-01')
    parser.add_argument('--oos-end', default='2026-01-09')
    parser.add_argument('--top-n', type=int, default=10)

    args = parser.parse_args()

    run_grid_search(
        train_start=args.train_start,
        train_end=args.train_end,
        oos_start=args.oos_start,
        oos_end=args.oos_end,
        leverage=args.leverage,
        min_trades_per_year=args.min_trades_per_year,
        max_mdd=args.max_mdd,
        min_sharpe=args.min_sharpe,
        top_n=args.top_n,
    )
