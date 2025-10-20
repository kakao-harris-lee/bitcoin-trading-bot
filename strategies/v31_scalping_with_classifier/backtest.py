#!/usr/bin/env python3
"""
v31 Backtest - Scalping with Market Classifier
Minute5 scalping filtered by day-level market state
Target: 300-400% in 2024
"""

import sys
sys.path.append('../..')

import sqlite3
import pandas as pd
import numpy as np
import talib
import json
from datetime import datetime
from market_classifier import MarketClassifier
from strategy import v31_strategy

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

DB_PATH = '../../upbit_bitcoin.db'

# ========================
# Data Loading
# ========================

def load_timeframe_data(db_path, timeframe, start_date, end_date):
    """Load data for any timeframe"""
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

def add_indicators(df, config):
    """Add technical indicators to minute5 data"""
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values

    # RSI
    df['rsi_14'] = talib.RSI(close, timeperiod=config['indicators']['rsi_period'])

    # Bollinger Bands
    upper, middle, lower = talib.BBANDS(close,
                                         timeperiod=config['indicators']['bb_period'],
                                         nbdevup=config['indicators']['bb_std'],
                                         nbdevdn=config['indicators']['bb_std'])
    df['bb_upper'] = upper
    df['bb_middle'] = middle
    df['bb_lower'] = lower
    df['bb_position'] = (close - lower) / (upper - lower + 1e-10)

    # Volume ratio
    volume_sma = talib.SMA(volume, timeperiod=config['indicators']['volume_sma_period'])
    df['volume_ratio'] = volume / (volume_sma + 1e-10)

    # ATR (for position sizing)
    df['atr'] = talib.ATR(high, low, close, timeperiod=config['indicators']['atr_period'])

    return df

# ========================
# Backtesting Engine
# ========================

def run_backtest(df_minute5, classifier, config):
    """Run backtest with market classifier"""

    initial_capital = config['backtest_settings']['initial_capital']
    fee_rate = config['backtest_settings']['fee_rate']
    slippage = config['backtest_settings']['slippage']

    cash = initial_capital
    position = None
    trades = []
    equity_curve = []

    daily_stats = {}  # Track daily performance
    current_day_trades = []
    current_day = None

    for i in range(len(df_minute5)):
        row = df_minute5.iloc[i]
        timestamp = row['timestamp']
        price = row['close']
        date_str = timestamp.date()

        # Daily risk management reset
        if current_day != date_str:
            if current_day is not None:
                # Calculate daily stats
                daily_return = 0
                if len(current_day_trades) > 0:
                    daily_pnl = sum([t['profit_pct'] for t in current_day_trades])
                    daily_return = daily_pnl / len(current_day_trades)

                daily_stats[str(current_day)] = {
                    'trades': len(current_day_trades),
                    'daily_return': daily_return,
                    'wins': sum([1 for t in current_day_trades if t['profit_pct'] > 0]),
                    'losses': sum([1 for t in current_day_trades if t['profit_pct'] <= 0])
                }

            current_day = date_str
            current_day_trades = []

        # Get market classification
        market_state = classifier.classify_market_at_date(timestamp)

        # Calculate equity
        position_value = position['quantity'] * price if position else 0
        total_equity = cash + position_value

        equity_curve.append({
            'timestamp': timestamp,
            'cash': cash,
            'position_value': position_value,
            'total_equity': total_equity,
            'market_state': market_state
        })

        # Strategy decision
        position_info = None
        if position:
            position_info = {
                'entry_price': position['entry_price'],
                'entry_time': position['entry_time'],
                'quantity': position['quantity'],
                'hold_candles': i - position['entry_index']
            }

        decision = v31_strategy(df_minute5, i, config, position_info, market_state)

        # Daily loss limit check
        if current_day_trades:
            daily_loss = sum([t['profit_pct'] for t in current_day_trades if t['profit_pct'] < 0])
            if abs(daily_loss) >= config['risk_management']['max_daily_loss_pct'] * 100:
                # Stop trading for today
                if decision['action'] == 'buy':
                    decision = {'action': 'hold', 'reason': 'DAILY_LOSS_LIMIT_REACHED'}

        # Execute
        if decision['action'] == 'buy' and position is None:
            fraction = decision.get('fraction', 0.3)
            invest_amount = cash * fraction
            effective_price = price * (1 + slippage)
            quantity = invest_amount / (effective_price * (1 + fee_rate))

            position = {
                'entry_time': timestamp,
                'entry_price': price,
                'quantity': quantity,
                'entry_index': i,
                'reason': decision.get('reason', 'BUY')
            }

            cash -= invest_amount

        elif decision['action'] == 'sell' and position is not None:
            effective_price = price * (1 - slippage)
            sell_amount = position['quantity'] * effective_price * (1 - fee_rate)

            profit_pct = (price / position['entry_price'] - 1) * 100
            hold_candles = i - position['entry_index']
            hold_minutes = hold_candles * 5

            trade_record = {
                'entry_time': position['entry_time'],
                'entry_price': position['entry_price'],
                'exit_time': timestamp,
                'exit_price': price,
                'quantity': position['quantity'],
                'profit_pct': profit_pct,
                'hold_candles': hold_candles,
                'hold_minutes': hold_minutes,
                'reason': decision.get('reason', 'SELL'),
                'market_state': market_state
            }

            trades.append(trade_record)
            current_day_trades.append(trade_record)

            cash += sell_amount
            position = None

    # Final equity
    final_equity = cash + (position['quantity'] * df_minute5.iloc[-1]['close'] if position else 0)

    return {
        'initial_capital': initial_capital,
        'final_capital': final_equity,
        'trades': trades,
        'equity_curve': equity_curve,
        'daily_stats': daily_stats
    }

# ========================
# Metrics Calculation
# ========================

def calculate_metrics(results):
    """Calculate performance metrics"""

    initial = results['initial_capital']
    final = results['final_capital']
    trades = results['trades']

    total_return = (final / initial - 1) * 100

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

    # Profit factor
    total_profit = sum([t['profit_pct'] for t in winning_trades])
    total_loss = abs(sum([t['profit_pct'] for t in losing_trades]))
    profit_factor = total_profit / (total_loss + 1e-10) if total_loss > 0 else 999

    # Avg hold time
    avg_hold_minutes = np.mean([t['hold_minutes'] for t in trades])

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
        'profit_factor': profit_factor,
        'avg_hold_minutes': avg_hold_minutes
    }

# ========================
# Main
# ========================

def main():
    print("="*70)
    print("v31 Backtest - Scalping with Market Classifier")
    print("="*70)

    # Initialize market classifier
    print("\n시장 분류기 초기화 중...")
    classifier = MarketClassifier(DB_PATH, config)

    # Load day data for classifier (need wider range for indicators)
    classifier_start = "2023-01-01"  # Earlier for indicator calculation
    classifier.load_day_data(classifier_start, config['backtest_settings']['end_date'])
    print(f"✅ Day 데이터 로드 완료: {len(classifier.day_data)} 레코드")

    # Load primary timeframe data
    timeframe = config['primary_timeframe']
    print(f"\n{timeframe} 데이터 로드 중...")
    df = load_timeframe_data(DB_PATH,
                            timeframe,
                            config['backtest_settings']['start_date'],
                            config['backtest_settings']['end_date'])

    print(f"✅ Loaded {len(df):,} {timeframe} 레코드 from {df['timestamp'].min()} to {df['timestamp'].max()}")

    # Add indicators
    print("지표 계산 중 (RSI, BB, Volume)...")
    df = add_indicators(df, config)

    # Buy&Hold baseline
    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    buy_hold_return = (end_price / start_price - 1) * 100

    print(f"\n📊 Buy&Hold Baseline: {buy_hold_return:.2f}%")
    print(f"🎯 Target: {config['target_metrics']['total_return_target']:.2f}%\n")

    # Run backtest
    print("="*70)
    print("백테스팅 실행 중...")
    print("="*70 + "\n")

    results = run_backtest(df, classifier, config)

    print("="*70)
    print("메트릭 계산 중...")
    print("="*70)

    metrics = calculate_metrics(results)

    # Display results
    print(f"\n{'='*70}")
    print("📈 결과")
    print(f"{'='*70}")
    print(f"초기 자본:         {results['initial_capital']:>15,.0f} KRW")
    print(f"최종 자본:         {results['final_capital']:>15,.0f} KRW")
    print(f"총 수익률:         {metrics['total_return']:>15.2f}%")
    print(f"Buy&Hold:          {buy_hold_return:>15.2f}%")
    print(f"초과 수익:         {metrics['total_return'] - buy_hold_return:>15.2f}%p")
    print(f"\n{'='*70}")
    print(f"Sharpe Ratio:      {metrics['sharpe_ratio']:>15.2f}")
    print(f"Max Drawdown:      {metrics['max_drawdown']:>15.2f}%")
    print(f"총 거래:           {metrics['total_trades']:>15}")
    print(f"승률:              {metrics['win_rate']:>15.2f}%")
    print(f"평균 수익:         {metrics['avg_profit']:>15.2f}%")
    print(f"평균 손실:         {metrics['avg_loss']:>15.2f}%")
    print(f"Profit Factor:     {metrics['profit_factor']:>15.2f}")
    print(f"평균 보유 시간:    {metrics['avg_hold_minutes']:>15.1f} 분")
    print(f"{'='*70}\n")

    # Target check
    print(f"{'='*70}")
    print("🎯 목표 달성도")
    print(f"{'='*70}")

    target_return = config['target_metrics']['total_return_target']
    target_sharpe = config['target_metrics']['sharpe_ratio_target']
    target_mdd = config['target_metrics']['max_drawdown_target']
    target_wr = config['target_metrics']['min_win_rate'] * 100

    return_ok = "✅" if metrics['total_return'] >= target_return else "❌"
    sharpe_ok = "✅" if metrics['sharpe_ratio'] >= target_sharpe else "❌"
    mdd_ok = "✅" if metrics['max_drawdown'] <= target_mdd else "❌"
    wr_ok = "✅" if metrics['win_rate'] >= target_wr else "❌"

    print(f"{return_ok} 총 수익률:  {metrics['total_return']:.2f}% (목표: >= {target_return}%)")
    print(f"{sharpe_ok} Sharpe:     {metrics['sharpe_ratio']:.2f} (목표: >= {target_sharpe})")
    print(f"{mdd_ok} Max DD:     {metrics['max_drawdown']:.2f}% (목표: <= {target_mdd}%)")
    print(f"{wr_ok} 승률:       {metrics['win_rate']:.2f}% (목표: >= {target_wr}%)")
    print(f"{'='*70}\n")

    # Save results
    output = {
        'version': 'v31',
        'strategy_name': config['strategy_name'],
        'primary_timeframe': config['primary_timeframe'],
        'classifier_timeframe': config['classifier_timeframe'],
        'backtest_period': {
            'start': config['backtest_settings']['start_date'],
            'end': config['backtest_settings']['end_date']
        },
        'metrics': metrics,
        'buy_hold': buy_hold_return,
        'trades': results['trades'][:100],  # First 100 trades
        'total_trades': len(results['trades']),
        'config': config
    }

    with open('results.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"💾 결과 저장 완료: results.json\n")

if __name__ == '__main__':
    main()
