#!/usr/bin/env python3
"""
v30 Backtest - Perfect Long-term Strategy
Day timeframe, MFI + MACD + ADX
Target: 150-200% in 2024
"""

import sys
sys.path.append('../..')

import sqlite3
import pandas as pd
import numpy as np
import talib
import json
from datetime import datetime
from strategy import v30_strategy

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

DB_PATH = '../../upbit_bitcoin.db'

# ========================
# Data Loading
# ========================

def load_data(db_path, timeframe, start_date, end_date):
    """Load data from database"""
    conn = sqlite3.connect(db_path)
    query = f"""
        SELECT timestamp, opening_price as open, high_price as high,
               low_price as low, trade_price as close,
               candle_acc_trade_volume as volume
        FROM bitcoin_{timeframe}
        WHERE timestamp >= '{start_date}' AND timestamp <= '{end_date}'
        ORDER BY timestamp ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df

# ========================
# Indicators
# ========================

def add_indicators(df, config):
    """Add technical indicators"""
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values

    # MFI (Money Flow Index) - Most predictive!
    df['mfi'] = talib.MFI(high, low, close, volume, timeperiod=config['indicators']['mfi_period'])

    # MACD
    macd, macd_signal, macd_hist = talib.MACD(close,
                                               fastperiod=config['indicators']['macd_fast'],
                                               slowperiod=config['indicators']['macd_slow'],
                                               signalperiod=config['indicators']['macd_signal'])
    df['macd'] = macd
    df['macd_signal'] = macd_signal
    df['macd_hist'] = macd_hist

    # ADX
    df['adx'] = talib.ADX(high, low, close, timeperiod=config['indicators']['adx_period'])

    # Volume ratio
    volume_sma = talib.SMA(volume, timeperiod=config['indicators']['volume_sma_period'])
    df['volume_ratio'] = volume / (volume_sma + 1e-10)

    # RSI (filter)
    df['rsi_14'] = talib.RSI(close, timeperiod=14)

    # Bollinger Bands (filter)
    upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
    df['bb_position'] = (close - lower) / (upper - lower + 1e-10)

    return df

# ========================
# Backtesting Engine
# ========================

def run_backtest(df, strategy_func, config):
    """Run backtest"""

    initial_capital = config['backtest_settings']['initial_capital']
    fee_rate = config['backtest_settings']['fee_rate']
    slippage = config['backtest_settings']['slippage']

    cash = initial_capital
    position = None
    trades = []
    equity_curve = []

    for i in range(len(df)):
        row = df.iloc[i]
        timestamp = row['timestamp']
        price = row['close']

        # Calculate equity
        position_value = position['quantity'] * price if position else 0
        total_equity = cash + position_value

        equity_curve.append({
            'timestamp': timestamp,
            'cash': cash,
            'position_value': position_value,
            'total_equity': total_equity
        })

        # Strategy decision
        position_info = None
        if position:
            position_info = {
                'entry_price': position['entry_price'],
                'entry_time': position['entry_time'],
                'quantity': position['quantity'],
                'hold_days': (timestamp - position['entry_time']).days
            }

        decision = strategy_func(df, i, config, position_info)

        # Execute
        if decision['action'] == 'buy' and position is None:
            fraction = decision.get('fraction', 1.0)
            invest_amount = cash * fraction
            effective_price = price * (1 + slippage)
            quantity = invest_amount / (effective_price * (1 + fee_rate))

            position = {
                'entry_time': timestamp,
                'entry_price': price,
                'quantity': quantity,
                'reason': decision.get('reason', 'BUY')
            }

            cash -= invest_amount
            print(f"[BUY] {timestamp.date()} | Price: {price:,.0f} | Amount: {invest_amount:,.0f} | {decision.get('reason', '')}")

        elif decision['action'] == 'sell' and position is not None:
            effective_price = price * (1 - slippage)
            sell_amount = position['quantity'] * effective_price * (1 - fee_rate)

            profit_pct = (price / position['entry_price'] - 1) * 100
            hold_days = (timestamp - position['entry_time']).days

            trades.append({
                'entry_time': position['entry_time'],
                'entry_price': position['entry_price'],
                'exit_time': timestamp,
                'exit_price': price,
                'quantity': position['quantity'],
                'profit_pct': profit_pct,
                'hold_days': hold_days,
                'reason': decision.get('reason', 'SELL')
            })

            cash += sell_amount
            print(f"[SELL] {timestamp.date()} | Price: {price:,.0f} | Profit: {profit_pct:+.2f}% | Hold: {hold_days}d | {decision.get('reason', '')}")

            position = None

    # Final equity
    final_equity = cash + (position['quantity'] * df.iloc[-1]['close'] if position else 0)

    return {
        'initial_capital': initial_capital,
        'final_capital': final_equity,
        'trades': trades,
        'equity_curve': equity_curve
    }

# ========================
# Metrics Calculation
# ========================

def calculate_metrics(results, config):
    """Calculate performance metrics"""

    initial = results['initial_capital']
    final = results['final_capital']
    trades = results['trades']

    total_return = (final / initial - 1) * 100

    # Trades analysis
    if len(trades) == 0:
        return {
            'total_return': total_return,
            'total_trades': 0,
            'sharpe_ratio': 0,
            'max_drawdown': 0,
            'win_rate': 0
        }

    winning_trades = [t for t in trades if t['profit_pct'] > 0]
    losing_trades = [t for t in trades if t['profit_pct'] <= 0]

    win_rate = len(winning_trades) / len(trades)
    avg_profit = np.mean([t['profit_pct'] for t in winning_trades]) if winning_trades else 0
    avg_loss = np.mean([t['profit_pct'] for t in losing_trades]) if losing_trades else 0

    # Sharpe Ratio
    trade_returns = [t['profit_pct'] / 100 for t in trades]
    sharpe_ratio = np.mean(trade_returns) / (np.std(trade_returns) + 1e-10) * np.sqrt(len(trades))

    # Max Drawdown
    equity_curve = results['equity_curve']
    equities = [e['total_equity'] for e in equity_curve]
    running_max = np.maximum.accumulate(equities)
    drawdowns = (equities - running_max) / running_max * 100
    max_drawdown = abs(np.min(drawdowns))

    return {
        'total_return': total_return,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown,
        'total_trades': len(trades),
        'winning_trades': len(winning_trades),
        'losing_trades': len(losing_trades),
        'win_rate': win_rate * 100,
        'avg_profit': avg_profit,
        'avg_loss': avg_loss,
        'profit_factor': abs(avg_profit * len(winning_trades) / (avg_loss * len(losing_trades) + 1e-10)) if losing_trades else 999
    }

# ========================
# Main
# ========================

def main():
    print("="*70)
    print("v30 Backtest - Perfect Long-term Strategy")
    print("="*70)

    # Load data
    print(f"\nLoading {config['timeframe']} data...")
    df = load_data(DB_PATH,
                  config['timeframe'],
                  config['backtest_settings']['start_date'],
                  config['backtest_settings']['end_date'])

    print(f"✅ Loaded {len(df):,} records from {df['timestamp'].min()} to {df['timestamp'].max()}")

    # Add indicators
    print("Calculating indicators (MFI, MACD, ADX, etc.)...")
    df = add_indicators(df, config)

    # Buy&Hold baseline
    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    buy_hold_return = (end_price / start_price - 1) * 100

    print(f"\n📊 Buy&Hold Baseline: {buy_hold_return:.2f}%")
    print(f"🎯 Target: {config['target_metrics']['total_return_target']:.2f}% (+{config['target_metrics']['total_return_target'] - buy_hold_return:.2f}%p)\n")

    # Run backtest
    print("="*70)
    print("Running backtest...")
    print("="*70)

    results = run_backtest(df, v30_strategy, config)

    print("\n" + "="*70)
    print("Calculating metrics...")
    print("="*70)

    metrics = calculate_metrics(results, config)

    # Display results
    print(f"\n{'='*70}")
    print("📈 RESULTS")
    print(f"{'='*70}")
    print(f"Initial Capital:    {results['initial_capital']:>15,.0f} KRW")
    print(f"Final Capital:      {results['final_capital']:>15,.0f} KRW")
    print(f"Total Return:       {metrics['total_return']:>15.2f}%")
    print(f"Buy&Hold:           {buy_hold_return:>15.2f}%")
    print(f"Outperformance:     {metrics['total_return'] - buy_hold_return:>15.2f}%p")
    print(f"\n{'='*70}")
    print(f"Sharpe Ratio:       {metrics['sharpe_ratio']:>15.2f}")
    print(f"Max Drawdown:       {metrics['max_drawdown']:>15.2f}%")
    print(f"Total Trades:       {metrics['total_trades']:>15}")
    print(f"Win Rate:           {metrics['win_rate']:>15.2f}%")
    print(f"Avg Profit:         {metrics['avg_profit']:>15.2f}%")
    print(f"Avg Loss:           {metrics['avg_loss']:>15.2f}%")
    print(f"Profit Factor:      {metrics['profit_factor']:>15.2f}")
    print(f"{'='*70}\n")

    # Check targets
    print(f"{'='*70}")
    print("🎯 TARGET ACHIEVEMENT")
    print(f"{'='*70}")

    target_return = config['target_metrics']['total_return_target']
    target_sharpe = config['target_metrics']['sharpe_ratio_target']
    target_mdd = config['target_metrics']['max_drawdown_target']
    target_wr = config['target_metrics']['min_win_rate'] * 100

    return_ok = "✅" if metrics['total_return'] >= target_return else "❌"
    sharpe_ok = "✅" if metrics['sharpe_ratio'] >= target_sharpe else "❌"
    mdd_ok = "✅" if metrics['max_drawdown'] <= target_mdd else "❌"
    wr_ok = "✅" if metrics['win_rate'] >= target_wr else "❌"

    print(f"{return_ok} Total Return:  {metrics['total_return']:.2f}% (Target: >= {target_return}%)")
    print(f"{sharpe_ok} Sharpe Ratio:  {metrics['sharpe_ratio']:.2f} (Target: >= {target_sharpe})")
    print(f"{mdd_ok} Max Drawdown:  {metrics['max_drawdown']:.2f}% (Target: <= {target_mdd}%)")
    print(f"{wr_ok} Win Rate:      {metrics['win_rate']:.2f}% (Target: >= {target_wr}%)")
    print(f"{'='*70}\n")

    # Save results
    output = {
        'version': 'v30',
        'strategy_name': config['strategy_name'],
        'timeframe': config['timeframe'],
        'backtest_period': {
            'start': config['backtest_settings']['start_date'],
            'end': config['backtest_settings']['end_date']
        },
        'metrics': metrics,
        'buy_hold': buy_hold_return,
        'trades': results['trades'],
        'config': config
    }

    with open('results.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"💾 Results saved to results.json\n")

if __name__ == '__main__':
    main()
