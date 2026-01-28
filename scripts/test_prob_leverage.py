#!/usr/bin/env python3
"""Test probability-based leverage with proper backtest_runner logic.

This script tests v35_long_v2 with prob_leverage_enabled to see
if MFI-based leverage adjustment differentiates from buy & hold.
"""

import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
import pandas as pd
import numpy as np
from typing import Dict, List

from core.data_loader import DataLoader
from trading.indicators import add_all_indicators
from trading.strategies.components.strategy_factory import StrategyFactory
from core.component_adapter import ComponentStrategyAdapter


def run_backtest(
    strategy_id: str,
    config: Dict,
    df: pd.DataFrame,
    initial_capital: float,
    leverage: float,
    fee_rate: float = 0.0004,
    slippage: float = 0.0002,
) -> Dict:
    """Run backtest with proper leverage handling from signal."""

    factory = StrategyFactory(redis=None)
    adapter = ComponentStrategyAdapter(factory, strategy_id, config)
    adapter.symbol = "BTC"

    capital = initial_capital
    position_size = 0.0
    entry_price = 0.0
    position_leverage = leverage
    trades: List[Dict] = []
    equity_curve: List[float] = []
    leverage_used: List[Dict] = []  # Track leverage for analysis

    for i in range(len(df)):
        signal = adapter(df, i)
        row = df.iloc[i]

        action = signal.get('action', 'hold')
        reason = signal.get('reason', '')
        timestamp = str(row.get('timestamp', row.name))

        # Current equity calculation
        current_equity = capital
        if position_size > 0:
            current_price = row['close']
            if adapter.current_position and adapter.current_position.side == 'short':
                pnl_ratio = (entry_price - current_price) / entry_price
                unrealized_pnl = position_size * pnl_ratio
                current_equity += (position_size / position_leverage) + unrealized_pnl
            else:
                pnl_ratio = (current_price - entry_price) / entry_price
                unrealized_pnl = position_size * pnl_ratio
                current_equity += (position_size / position_leverage) + unrealized_pnl

        equity_curve.append({'date': timestamp[:10], 'equity': current_equity})

        # OPEN LONG
        if action == 'buy' and position_size == 0:
            fraction = signal.get('fraction', 1.0)
            # Use dynamic leverage from signal
            effective_leverage = signal.get('leverage', leverage)
            max_margin = capital * fraction / (1 + effective_leverage * fee_rate)
            margin = max_margin
            effective_pos_size = margin * effective_leverage
            fee = effective_pos_size * fee_rate

            if capital >= (margin + fee):
                capital -= (margin + fee)
                position_size = effective_pos_size
                position_leverage = effective_leverage
                entry_price = row['close'] * (1 + slippage)

                # Track leverage used
                mfi = row.get('mfi', 50.0)
                leverage_used.append({
                    'date': timestamp,
                    'mfi': mfi,
                    'leverage': effective_leverage,
                    'reason': reason
                })

                trades.append({
                    'type': 'buy',
                    'time': timestamp,
                    'price': entry_price,
                    'size': position_size,
                    'leverage': effective_leverage,
                    'mfi': mfi,
                    'reason': reason
                })

        # OPEN SHORT
        elif action == 'open_short' and position_size == 0:
            fraction = signal.get('fraction', 1.0)
            effective_leverage = signal.get('leverage', leverage)
            max_margin = capital * fraction / (1 + effective_leverage * fee_rate)
            margin = max_margin
            effective_pos_size = margin * effective_leverage
            fee = effective_pos_size * fee_rate

            if capital >= (margin + fee):
                capital -= (margin + fee)
                position_size = effective_pos_size
                position_leverage = effective_leverage
                entry_price = row['close'] * (1 - slippage)

                trades.append({
                    'type': 'short',
                    'time': timestamp,
                    'price': entry_price,
                    'size': position_size,
                    'leverage': effective_leverage,
                    'reason': reason
                })

        # CLOSE LONG (SELL)
        elif action == 'sell' and position_size > 0:
            exit_price = row['close'] * (1 - slippage)
            if adapter.current_position and adapter.current_position.side == 'short':
                pnl_ratio = (entry_price - exit_price) / entry_price
            else:
                pnl_ratio = (exit_price - entry_price) / entry_price

            pnl = position_size * pnl_ratio
            margin_return = position_size / position_leverage
            fee = position_size * fee_rate
            capital += margin_return + pnl - fee

            trades.append({
                'type': 'sell',
                'time': timestamp,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'size': position_size,
                'leverage': position_leverage,
                'pnl': pnl,
                'pnl_pct': pnl_ratio * 100 * position_leverage,
                'reason': reason
            })

            position_size = 0.0
            entry_price = 0.0

        # CLOSE SHORT
        elif action == 'close_short' and position_size > 0:
            exit_price = row['close'] * (1 + slippage)
            pnl_ratio = (entry_price - exit_price) / entry_price
            pnl = position_size * pnl_ratio
            margin_return = position_size / position_leverage
            fee = position_size * fee_rate
            capital += margin_return + pnl - fee

            trades.append({
                'type': 'cover',
                'time': timestamp,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'size': position_size,
                'leverage': position_leverage,
                'pnl': pnl,
                'pnl_pct': pnl_ratio * 100 * position_leverage,
                'reason': reason
            })

            position_size = 0.0
            entry_price = 0.0

    # Force close at end
    if position_size > 0:
        last_price = df.iloc[-1]['close']
        if adapter.current_position and adapter.current_position.side == 'short':
            pnl_ratio = (entry_price - last_price) / entry_price
        else:
            pnl_ratio = (last_price - entry_price) / entry_price
        pnl = position_size * pnl_ratio
        capital += (position_size / position_leverage) + pnl

    # Calculate metrics
    final_capital = capital
    total_return_pct = (final_capital - initial_capital) / initial_capital * 100

    close_trades = [t for t in trades if t['type'] in ('sell', 'cover')]
    profits = [t['pnl'] for t in close_trades]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]

    win_rate = len(wins) / len(close_trades) * 100 if close_trades else 0
    profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0

    equity_values = [e['equity'] for e in equity_curve]
    equity_series = pd.Series(equity_values)

    peak = equity_series.cummax()
    drawdown = (equity_series - peak) / peak * 100
    mdd = float(drawdown.min())

    # Leverage analysis
    if leverage_used:
        lev_df = pd.DataFrame(leverage_used)
        avg_leverage = lev_df['leverage'].mean()
        leverage_distribution = lev_df['leverage'].value_counts().to_dict()
    else:
        avg_leverage = 0
        leverage_distribution = {}

    return {
        'initial_capital': initial_capital,
        'final_capital': final_capital,
        'total_return_pct': total_return_pct,
        'mdd': mdd,
        'total_trades': len(close_trades),
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'avg_leverage': avg_leverage,
        'leverage_distribution': leverage_distribution,
        'trades': trades,
        'equity_curve': equity_curve,
    }


def main():
    print("=" * 60)
    print("Testing Probability-based Leverage")
    print("=" * 60)

    # Load allocation config
    allocation_path = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
    with open(allocation_path) as f:
        allocation = json.load(f)

    # Test parameters
    start_date = "2024-01-01"
    end_date = "2024-12-31"
    initial_capital = 10000.0

    # Load data
    print(f"\nLoading data from {start_date} to {end_date}...")
    with DataLoader(exchange="binance") as loader:
        df = loader.load_timeframe("minute60", start_date, end_date)

    if df.empty:
        print("ERROR: No data loaded")
        return

    print(f"Loaded {len(df)} candles")

    # Add indicators
    print("Calculating indicators...")
    add_all_indicators(df)

    # Get v35_long_v2 config
    strategy_config = allocation['strategies']['v35_long_v2']

    # Test 1: Baseline (prob_leverage disabled)
    print("\n" + "=" * 60)
    print("Test 1: BASELINE (prob_leverage_enabled=False)")
    print("=" * 60)

    baseline_config = {
        'regime_version': strategy_config.get('regime_version', 'v1'),
        'stop_loss_cooldown': strategy_config.get('stop_loss_cooldown', 24),
        'trailing_enabled': strategy_config.get('trailing_enabled', False),
        'trailing_activation': strategy_config.get('trailing_activation', 3.0),
        'trailing_distance': strategy_config.get('trailing_distance', 2.0),
        'atr_stop_enabled': strategy_config.get('atr_stop_enabled', False),
        'atr_stop_multiplier': strategy_config.get('atr_stop_multiplier', 2.0),
        'atr_stop_min_pct': strategy_config.get('atr_stop_min_pct', 1.5),
        'atr_stop_max_pct': strategy_config.get('atr_stop_max_pct', 4.0),
        # Keep dynamic_leverage disabled for baseline
        'dynamic_leverage': False,
        'cash_in_bear': strategy_config.get('cash_in_bear', False),
        'cash_below_ema200': strategy_config.get('cash_below_ema200', False),
        'bull_prob_threshold': strategy_config.get('bull_prob_threshold', 0.0),
        'panic_sell_below_ma120': False,
        # Disable prob_leverage for baseline
        'prob_leverage_enabled': False,
    }

    baseline_results = run_backtest(
        'v35_long',
        baseline_config,
        df.copy(),
        initial_capital,
        leverage=3.0
    )

    print(f"Return: {baseline_results['total_return_pct']:.2f}%")
    print(f"MDD: {baseline_results['mdd']:.2f}%")
    print(f"Trades: {baseline_results['total_trades']}")
    print(f"Win Rate: {baseline_results['win_rate']:.1f}%")
    print(f"Profit Factor: {baseline_results['profit_factor']:.2f}")
    print(f"Avg Leverage: {baseline_results['avg_leverage']:.2f}x")

    # Test 2: Prob Leverage enabled
    print("\n" + "=" * 60)
    print("Test 2: PROB_LEVERAGE (MFI-based leverage)")
    print("=" * 60)

    prob_config = baseline_config.copy()
    prob_config.update({
        'prob_leverage_enabled': True,
        'prob_leverage_max': 3.0,   # MFI >= 70
        'prob_leverage_high': 2.0,  # MFI 60-70
        'prob_leverage_mid': 1.5,   # MFI 50-60
        'prob_leverage_low': 1.0,   # MFI 40-50
        'prob_leverage_min': 0.5,   # MFI 30-40
        # MFI < 30 = no entry
    })

    prob_results = run_backtest(
        'v35_long',
        prob_config,
        df.copy(),
        initial_capital,
        leverage=3.0
    )

    print(f"Return: {prob_results['total_return_pct']:.2f}%")
    print(f"MDD: {prob_results['mdd']:.2f}%")
    print(f"Trades: {prob_results['total_trades']}")
    print(f"Win Rate: {prob_results['win_rate']:.1f}%")
    print(f"Profit Factor: {prob_results['profit_factor']:.2f}")
    print(f"Avg Leverage: {prob_results['avg_leverage']:.2f}x")
    print(f"Leverage Distribution: {prob_results['leverage_distribution']}")

    # Test 3: Full v35_long_v2 config
    print("\n" + "=" * 60)
    print("Test 3: FULL v35_long_v2 config (all MDD defenses)")
    print("=" * 60)

    full_config = {
        'regime_version': strategy_config.get('regime_version', 'v1'),
        'stop_loss_cooldown': strategy_config.get('stop_loss_cooldown', 6),
        'trailing_enabled': strategy_config.get('trailing_enabled', True),
        'trailing_activation': strategy_config.get('trailing_activation', 1.5),
        'trailing_distance': strategy_config.get('trailing_distance', 1.0),
        'atr_stop_enabled': strategy_config.get('atr_stop_enabled', True),
        'atr_stop_multiplier': strategy_config.get('atr_stop_multiplier', 3.0),
        'atr_stop_min_pct': strategy_config.get('atr_stop_min_pct', 2.0),
        'atr_stop_max_pct': strategy_config.get('atr_stop_max_pct', 6.0),
        'dynamic_leverage': strategy_config.get('dynamic_leverage', True),
        'leverage_bull_strong': strategy_config.get('leverage_bull_strong', 3.0),
        'leverage_bull_moderate': strategy_config.get('leverage_bull_moderate', 2.0),
        'leverage_sideways': strategy_config.get('leverage_sideways', 1.0),
        'leverage_bear': strategy_config.get('leverage_bear', 0.0),
        'cash_in_bear': strategy_config.get('cash_in_bear', True),
        'cash_below_ema200': strategy_config.get('cash_below_ema200', True),
        'max_consecutive_losses': strategy_config.get('max_consecutive_losses', 3),
        'loss_pause_candles': strategy_config.get('loss_pause_candles', 48),
        'bull_prob_threshold': strategy_config.get('bull_prob_threshold', 0.55),
        'panic_sell_below_ma120': strategy_config.get('panic_sell_below_ma120', False),
        'prob_leverage_enabled': strategy_config.get('prob_leverage_enabled', True),
        'prob_leverage_max': strategy_config.get('prob_leverage_max', 3.0),
        'prob_leverage_high': strategy_config.get('prob_leverage_high', 2.0),
        'prob_leverage_mid': strategy_config.get('prob_leverage_mid', 1.5),
        'prob_leverage_low': strategy_config.get('prob_leverage_low', 1.0),
        'prob_leverage_min': strategy_config.get('prob_leverage_min', 0.5),
    }

    full_results = run_backtest(
        'v35_long',
        full_config,
        df.copy(),
        initial_capital,
        leverage=3.0
    )

    print(f"Return: {full_results['total_return_pct']:.2f}%")
    print(f"MDD: {full_results['mdd']:.2f}%")
    print(f"Trades: {full_results['total_trades']}")
    print(f"Win Rate: {full_results['win_rate']:.1f}%")
    print(f"Profit Factor: {full_results['profit_factor']:.2f}")
    print(f"Avg Leverage: {full_results['avg_leverage']:.2f}x")
    print(f"Leverage Distribution: {full_results['leverage_distribution']}")

    # Calculate Buy & Hold for comparison
    print("\n" + "=" * 60)
    print("Benchmark: BUY & HOLD")
    print("=" * 60)

    start_price = df.iloc[200]['close']  # After warmup
    end_price = df.iloc[-1]['close']
    bh_return = (end_price - start_price) / start_price * 100
    bh_leveraged = bh_return * 3.0  # 3x leverage

    print(f"Return (1x): {bh_return:.2f}%")
    print(f"Return (3x): {bh_leveraged:.2f}%")

    # Summary comparison
    print("\n" + "=" * 60)
    print("SUMMARY COMPARISON")
    print("=" * 60)
    print(f"{'Strategy':<30} {'Return':>10} {'MDD':>10} {'Trades':>8} {'Avg Lev':>8}")
    print("-" * 60)
    print(f"{'Baseline (fixed 3x)':<30} {baseline_results['total_return_pct']:>9.1f}% {baseline_results['mdd']:>9.1f}% {baseline_results['total_trades']:>8} {baseline_results['avg_leverage']:>7.2f}x")
    print(f"{'Prob Leverage (MFI-based)':<30} {prob_results['total_return_pct']:>9.1f}% {prob_results['mdd']:>9.1f}% {prob_results['total_trades']:>8} {prob_results['avg_leverage']:>7.2f}x")
    print(f"{'Full v35_long_v2':<30} {full_results['total_return_pct']:>9.1f}% {full_results['mdd']:>9.1f}% {full_results['total_trades']:>8} {full_results['avg_leverage']:>7.2f}x")
    print(f"{'Buy & Hold (3x)':<30} {bh_leveraged:>9.1f}% {'-':>10} {'-':>8} {'3.00':>7}x")

    # Show leverage improvement
    print("\n" + "=" * 60)
    print("LEVERAGE DISTRIBUTION (Full v35_long_v2)")
    print("=" * 60)
    if full_results['leverage_distribution']:
        total = sum(full_results['leverage_distribution'].values())
        for lev, count in sorted(full_results['leverage_distribution'].items(), reverse=True):
            pct = count / total * 100
            print(f"  {lev}x leverage: {count} trades ({pct:.1f}%)")


if __name__ == "__main__":
    main()
