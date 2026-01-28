#!/usr/bin/env python3
"""Backtest v35_long_v2 with parameter improvements for H2 2023.

Compares current config vs improved parameters targeting the sideways-bull
recovery market of H2 2023 where the strategy underperformed.

Key changes tested:
1. Disable EMA200 filter (cash_below_ema200: false)
2. Wider ATR-based stop loss
3. Higher SIDEWAYS leverage (1.5x vs 1.0x)
4. Relaxed consecutive loss pause (4 losses, 24h pause)
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np

from core.data_loader import DataLoader
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.indicators import add_all_indicators


def run_backtest(
    config: Dict[str, Any],
    df: pd.DataFrame,
    initial_capital: float = 10000,
    leverage: float = 3.0,
    fee_rate: float = 0.0005,
    slippage: float = 0.0004,
    label: str = "Strategy"
) -> Dict[str, Any]:
    """Run backtest with given config."""

    factory = StrategyFactory()
    adapter = ComponentStrategyAdapter(factory, "v35_long_v2", config)
    adapter.symbol = "BTC"

    capital = initial_capital
    position_size = 0.0
    entry_price = 0.0
    position_leverage = leverage
    trades: List[Dict] = []
    equity_curve: List[Dict] = []

    for i in range(len(df)):
        signal = adapter(df, i)
        row = df.iloc[i]

        action = signal.get('action', 'hold')
        timestamp = row.name if hasattr(row.name, 'strftime') else str(row.get('timestamp', ''))

        # Calculate current equity
        current_equity = capital
        if position_size > 0:
            current_price = row['close']
            pnl_ratio = (current_price - entry_price) / entry_price
            unrealized_pnl = position_size * pnl_ratio
            current_equity += (position_size / position_leverage) + unrealized_pnl

        equity_curve.append({'date': str(timestamp)[:10], 'equity': current_equity})

        # OPEN LONG
        if action == 'buy' and position_size == 0:
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
                entry_price = row['close'] * (1 + slippage)
                trades.append({
                    'type': 'entry',
                    'date': str(timestamp),
                    'price': entry_price,
                    'size': position_size,
                    'leverage': position_leverage,
                    'reason': signal.get('reason', ''),
                })

        # CLOSE LONG
        elif action == 'sell' and position_size > 0:
            exit_price = row['close'] * (1 - slippage)
            pnl_ratio = (exit_price - entry_price) / entry_price
            pnl = position_size * pnl_ratio
            fee = position_size * fee_rate

            margin_return = position_size / position_leverage
            capital += margin_return + pnl - fee

            trades.append({
                'type': 'exit',
                'date': str(timestamp),
                'price': exit_price,
                'pnl': pnl,
                'pnl_pct': pnl_ratio * 100,
                'reason': signal.get('reason', ''),
            })

            position_size = 0.0
            entry_price = 0.0

    # Final equity
    final_equity = capital
    if position_size > 0:
        final_price = df.iloc[-1]['close']
        pnl_ratio = (final_price - entry_price) / entry_price
        unrealized_pnl = position_size * pnl_ratio
        final_equity += (position_size / position_leverage) + unrealized_pnl

    # Calculate metrics
    total_return = ((final_equity - initial_capital) / initial_capital) * 100

    # Win rate
    exits = [t for t in trades if t['type'] == 'exit']
    wins = [t for t in exits if t['pnl'] > 0]
    win_rate = (len(wins) / len(exits) * 100) if exits else 0

    # Max drawdown
    equity_values = [e['equity'] for e in equity_curve]
    peak = equity_values[0]
    max_dd = 0
    for eq in equity_values:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    return {
        'label': label,
        'final_equity': final_equity,
        'total_return': total_return,
        'total_trades': len(exits),
        'win_rate': win_rate,
        'max_drawdown': max_dd,
        'avg_pnl': np.mean([t['pnl_pct'] for t in exits]) if exits else 0,
        'equity_curve': equity_curve,
        'trades': trades,
    }


def main():
    print("=" * 70)
    print("v35_long_v2 Parameter Optimization Backtest")
    print("Focus: H2 2023 Sideways-Bull Recovery Market")
    print("=" * 70)

    # Load data
    print("\nLoading BTC data (2023-01-01 to 2023-12-31)...")
    with DataLoader() as loader:
        df = loader.load_timeframe('minute60', '2023-01-01', '2023-12-31')

    # Convert timestamp and add indicators
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.index = df['timestamp']  # Set index but keep column
    add_all_indicators(df)

    print(f"Total candles: {len(df)}")

    # Filter to H2 2023 only for focused analysis
    df_h2 = df[df.index >= '2023-07-01'].copy()
    print(f"H2 2023 candles: {len(df_h2)}")

    # === Configuration 1: Current v35_long_v2 ===
    current_config = {
        'regime_version': 'v2',
        'bbw_block_threshold': 25,
        'bbw_confirm_threshold': 50,
        'volume_block_ratio': 0.8,
        'volume_boost_ratio': 1.2,
        'mtf_enabled': True,
        'stop_loss_cooldown': 6,
        'trailing_enabled': True,
        'trailing_activation': 1.5,
        'trailing_distance': 1.0,
        'atr_stop_enabled': True,
        'atr_stop_multiplier': 3.0,
        'atr_stop_min_pct': 2.0,
        'atr_stop_max_pct': 6.0,
        'dynamic_leverage': True,
        'leverage_bull_strong': 3.0,
        'leverage_bull_moderate': 2.0,
        'leverage_sideways': 1.0,
        'leverage_bear': 0.0,
        'cash_in_bear': True,
        'cash_below_ema200': True,  # <-- Key issue
        'max_consecutive_losses': 3,
        'loss_pause_candles': 48,
        'drawdown_warning_pct': 8.0,
        'drawdown_reduce_pct': 10.0,
        'drawdown_exit_pct': 12.0,
        'v2_exit_on_filter': False,
        'bull_prob_threshold': 0.6,
        'panic_sell_below_ma120': False,
        'use_rf_probability': False,
    }

    # === Configuration 2: No EMA200 filter ===
    no_ema200_config = current_config.copy()
    no_ema200_config['cash_below_ema200'] = False
    no_ema200_config['label'] = 'No EMA200 Filter'

    # === Configuration 3: Improved for recovery markets ===
    improved_config = current_config.copy()
    improved_config.update({
        'cash_below_ema200': False,      # Don't block below EMA200
        'cash_in_bear': False,           # Allow entries in BEAR (with low leverage)
        'leverage_sideways': 1.5,        # Higher SIDEWAYS leverage
        'leverage_bear': 0.5,            # Small exposure even in BEAR
        'atr_stop_multiplier': 3.5,      # Wider ATR stop
        'atr_stop_min_pct': 2.5,         # Higher minimum stop
        'atr_stop_max_pct': 7.0,         # Higher maximum stop
        'max_consecutive_losses': 4,     # More tolerance for losses
        'loss_pause_candles': 24,        # Shorter pause
        'trailing_activation': 2.0,      # Later trailing activation
        'trailing_distance': 1.5,        # Wider trailing distance
        'bull_prob_threshold': 0.5,      # Lower bull probability requirement
    })

    # === Configuration 4: Aggressive recovery ===
    aggressive_config = improved_config.copy()
    aggressive_config.update({
        'leverage_sideways': 2.0,        # Even higher SIDEWAYS leverage
        'leverage_bear': 1.0,            # Higher BEAR exposure
        'atr_stop_multiplier': 4.0,      # Even wider stop
        'bull_prob_threshold': 0.4,      # Even lower threshold
    })

    configs = [
        (current_config, "Current v35_long_v2"),
        (no_ema200_config, "No EMA200 Filter"),
        (improved_config, "Improved (Recovery)"),
        (aggressive_config, "Aggressive Recovery"),
    ]

    # Run backtests
    print("\n" + "=" * 70)
    print("Running backtests on H2 2023 (Jul-Dec)...")
    print("=" * 70)

    results = []
    for config, label in configs:
        print(f"\n>>> {label}...")
        result = run_backtest(config, df_h2, label=label)
        results.append(result)
        print(f"    Return: {result['total_return']:+.1f}%")
        print(f"    Trades: {result['total_trades']}")
        print(f"    Win Rate: {result['win_rate']:.1f}%")
        print(f"    Max DD: {result['max_drawdown']:.1f}%")

    # Summary table
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY - H2 2023 (BTC +38.3%)")
    print("=" * 70)
    print(f"{'Config':<25} {'Return':>10} {'Trades':>8} {'Win%':>8} {'MaxDD':>8} {'AvgPnL':>8}")
    print("-" * 70)
    for r in results:
        print(f"{r['label']:<25} {r['total_return']:>+9.1f}% {r['total_trades']:>8} {r['win_rate']:>7.1f}% {r['max_drawdown']:>7.1f}% {r['avg_pnl']:>+7.2f}%")

    # Buy & Hold comparison
    bh_return = ((df_h2.iloc[-1]['close'] / df_h2.iloc[0]['close']) - 1) * 100
    print("-" * 70)
    print(f"{'Buy & Hold (BTC)':<25} {bh_return:>+9.1f}%")

    # Run full year backtest with best config
    print("\n" + "=" * 70)
    print("Full Year 2023 Backtest (Best Config)")
    print("=" * 70)

    for config, label in [(current_config, "Current"), (improved_config, "Improved")]:
        result = run_backtest(config, df, label=label)
        print(f"\n{label}:")
        print(f"  Return: {result['total_return']:+.1f}%")
        print(f"  Trades: {result['total_trades']}")
        print(f"  Win Rate: {result['win_rate']:.1f}%")
        print(f"  Max DD: {result['max_drawdown']:.1f}%")

    bh_full = ((df.iloc[-1]['close'] / df.iloc[0]['close']) - 1) * 100
    print(f"\nBuy & Hold (Full 2023): {bh_full:+.1f}%")


if __name__ == "__main__":
    main()
