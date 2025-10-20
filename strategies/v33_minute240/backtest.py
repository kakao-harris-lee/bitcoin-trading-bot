#!/usr/bin/env python3
"""
v33_minute240 Backtesting Engine

Features:
- Minute240 + Day multi-timeframe
- Partial profit taking (1/3 exits)
- Kelly Criterion position sizing
"""

import sys
sys.path.append('../..')

import json
import sqlite3
import pandas as pd
import numpy as np
import talib
from datetime import datetime
from typing import Dict, Optional

from strategy import v33_strategy


def load_config():
    """Load config.json"""
    with open('config.json', 'r', encoding='utf-8') as f:
        return json.load(f)


def load_timeframe_data(db_path: str, timeframe: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Load data for a specific timeframe"""
    conn = sqlite3.connect(db_path)

    table_map = {
        'minute240': 'bitcoin_minute240',
        'day': 'bitcoin_day'
    }
    table_name = table_map.get(timeframe, f'bitcoin_{timeframe}')

    query = f"""
        SELECT
            timestamp,
            opening_price as open,
            high_price as high,
            low_price as low,
            trade_price as close,
            candle_acc_trade_volume as volume
        FROM {table_name}
        WHERE timestamp >= '{start_date}' AND timestamp <= '{end_date}'
        ORDER BY timestamp
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)

    return df


def add_indicators(df: pd.DataFrame, config: Dict) -> pd.DataFrame:
    """Add technical indicators"""
    ind = config['indicators']

    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values

    df['rsi_14'] = talib.RSI(close, timeperiod=ind['rsi_period'])

    macd, signal, hist = talib.MACD(
        close,
        fastperiod=ind['macd_fast'],
        slowperiod=ind['macd_slow'],
        signalperiod=ind['macd_signal']
    )
    df['macd'] = macd
    df['macd_signal'] = signal
    df['macd_hist'] = hist

    df['adx'] = talib.ADX(high, low, close, timeperiod=ind['adx_period'])
    df['volume_sma_20'] = talib.SMA(volume, timeperiod=ind['volume_sma_period'])
    df['mfi'] = talib.MFI(high, low, close, volume, timeperiod=ind['mfi_period'])

    return df


def get_day_data(timestamp: pd.Timestamp, day_dict: Dict) -> Optional[pd.Series]:
    """Get day-level data"""
    date_key = timestamp.date()
    return day_dict.get(date_key, None)


def run_backtest(config: Dict) -> Dict:
    """Run backtesting"""
    bt_config = config['backtest_settings']
    db_path = '../../upbit_bitcoin.db'

    print("\n" + "="*70)
    print("v33_minute240 Backtesting - Mid-term Trading on 4h Candles")
    print("="*70)

    # Load data
    print("\n[1/5] Loading data...")
    m240_raw = load_timeframe_data(db_path, 'minute240', bt_config['start_date'], bt_config['end_date'])
    day_raw = load_timeframe_data(db_path, 'day', bt_config['start_date'], bt_config['end_date'])

    print(f"  - Minute240: {len(m240_raw)} candles")
    print(f"  - Day: {len(day_raw)} candles")

    # Add indicators
    print("\n[2/5] Adding indicators...")
    m240 = add_indicators(m240_raw.copy(), config)
    day = add_indicators(day_raw.copy(), config)

    # Create day dict
    print("\n[3/5] Aligning timeframes...")
    day_dict = {}
    for ts, row in day.iterrows():
        date_key = ts.date()
        day_dict[date_key] = row

    # Initialize backtest
    print("\n[4/5] Running backtest...")
    initial_capital = bt_config['initial_capital']
    cash = initial_capital
    position = None
    trades = []
    equity_curve = []
    consecutive_losses = 0

    fee_rate = bt_config['fee_rate']
    slippage = bt_config['slippage']

    for i in range(len(m240)):
        current = m240.iloc[i]
        timestamp = current.name
        close = current['close']

        day_data = get_day_data(timestamp, day_dict)

        # Strategy decision
        decision = v33_strategy(
            m240, i, config,
            position_info=position,
            day_data=day_data,
            consecutive_losses=consecutive_losses
        )

        action = decision['action']
        reason = decision.get('reason', '')

        # Execute
        if action == 'buy' and position is None:
            fraction = decision['fraction']
            buy_amount = cash * fraction
            buy_price = close * (1 + slippage)
            fee = buy_amount * fee_rate
            total_cost = buy_amount + fee

            if total_cost <= cash:
                position = {
                    'entry_price': buy_price,
                    'entry_time': timestamp,
                    'amount': buy_amount / buy_price,
                    'peak_price': buy_price,
                    'fraction': fraction,
                    'remaining_fraction': 1.0
                }
                cash -= total_cost

        elif action == 'sell' and position is not None:
            # Partial or full sell
            sell_fraction = decision.get('fraction', 1.0)
            sell_amount_btc = position['amount'] * sell_fraction
            sell_price = close * (1 - slippage)
            sell_amount_krw = sell_amount_btc * sell_price
            fee = sell_amount_krw * fee_rate
            proceeds = sell_amount_krw - fee

            profit_pct = (sell_price / position['entry_price'] - 1) * 100

            trades.append({
                'entry_time': position['entry_time'],
                'entry_price': position['entry_price'],
                'exit_time': timestamp,
                'exit_price': sell_price,
                'pnl_pct': profit_pct,
                'reason': reason,
                'fraction': position['fraction'],
                'sell_fraction': sell_fraction
            })

            cash += proceeds

            # Update position
            if sell_fraction >= 0.99:
                # Full exit
                if profit_pct < 0:
                    consecutive_losses += 1
                    if consecutive_losses > config['risk_management']['max_consecutive_losses']:
                        consecutive_losses = config['risk_management']['max_consecutive_losses']
                else:
                    consecutive_losses = 0

                position = None
            else:
                # Partial exit
                position['amount'] -= sell_amount_btc
                position['remaining_fraction'] = decision.get('remaining_fraction', position['remaining_fraction'])

        elif action == 'hold' and position is not None:
            # Update peak and remaining fraction
            if 'peak_price' in decision:
                position['peak_price'] = decision['peak_price']
            if 'remaining_fraction' in decision:
                position['remaining_fraction'] = decision['remaining_fraction']

        # Equity curve
        if position is None:
            total_equity = cash
        else:
            total_equity = cash + position['amount'] * close

        equity_curve.append({
            'timestamp': timestamp,
            'equity': total_equity,
            'cash': cash,
            'position_value': total_equity - cash
        })

    # Force close
    if position is not None:
        last_close = m240.iloc[-1]['close']
        sell_price = last_close * (1 - slippage)
        sell_amount = position['amount'] * sell_price
        fee = sell_amount * fee_rate
        proceeds = sell_amount - fee

        profit_pct = (sell_price / position['entry_price'] - 1) * 100

        trades.append({
            'entry_time': position['entry_time'],
            'entry_price': position['entry_price'],
            'exit_time': m240.index[-1],
            'exit_price': sell_price,
            'pnl_pct': profit_pct,
            'reason': 'FORCE_CLOSE_END'
        })

        cash += proceeds
        position = None

    final_capital = cash

    # Calculate metrics
    print("\n[5/5] Calculating metrics...")

    total_return = (final_capital / initial_capital - 1) * 100
    total_trades = len(trades)

    if total_trades > 0:
        wins = [t for t in trades if t['pnl_pct'] > 0]
        losses = [t for t in trades if t['pnl_pct'] < 0]

        win_rate = len(wins) / total_trades * 100
        avg_profit = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
        max_win = max([t['pnl_pct'] for t in trades])
        max_loss = min([t['pnl_pct'] for t in trades])

        returns = [t['pnl_pct'] for t in trades]
        if len(returns) > 1:
            sharpe = np.mean(returns) / (np.std(returns) + 1e-10) * np.sqrt(252)
        else:
            sharpe = 0

        equity_series = pd.Series([e['equity'] for e in equity_curve])
        running_max = equity_series.cummax()
        drawdown = (equity_series - running_max) / running_max * 100
        max_drawdown = drawdown.min()

    else:
        win_rate = avg_profit = avg_loss = max_win = max_loss = sharpe = max_drawdown = 0

    # Buy & Hold
    bh_start = m240_raw.iloc[0]['close']
    bh_end = m240_raw.iloc[-1]['close']
    bh_return = (bh_end / bh_start - 1) * 100

    # Display
    print("\n" + "="*70)
    print("BACKTEST RESULTS")
    print("="*70)
    print(f"\n기간: {bt_config['start_date']} ~ {bt_config['end_date']}")
    print(f"타임프레임: {config['primary_timeframe']}")
    print(f"\n초기 자본: {initial_capital:,}원")
    print(f"최종 자본: {final_capital:,.0f}원")
    print(f"총 수익: {final_capital - initial_capital:+,.0f}원")
    print(f"수익률: {total_return:+.2f}%")
    print(f"\nBuy&Hold 수익률: {bh_return:+.2f}%")
    print(f"vs Buy&Hold: {total_return - bh_return:+.2f}%p")
    print(f"\n총 거래: {total_trades}회")
    print(f"승률: {win_rate:.1f}%")
    print(f"평균 수익: {avg_profit:+.2f}%")
    print(f"평균 손실: {avg_loss:+.2f}%")
    print(f"최대 수익: {max_win:+.2f}%")
    print(f"최대 손실: {max_loss:+.2f}%")
    print(f"\nSharpe Ratio: {sharpe:.2f}")
    print(f"Max Drawdown: {max_drawdown:.2f}%")
    print("="*70)

    # Save
    results = {
        'version': 'v33',
        'config': config,
        'backtest_period': {
            'start': bt_config['start_date'],
            'end': bt_config['end_date'],
            'timeframe': config['primary_timeframe']
        },
        'performance': {
            'initial_capital': initial_capital,
            'final_capital': final_capital,
            'total_return_pct': total_return,
            'buy_hold_return_pct': bh_return,
            'excess_return_pct': total_return - bh_return,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'avg_profit_pct': avg_profit,
            'avg_loss_pct': avg_loss,
            'max_win_pct': max_win,
            'max_loss_pct': max_loss,
            'sharpe_ratio': sharpe,
            'max_drawdown_pct': max_drawdown
        },
        'trades': trades,
        'equity_curve': [{'timestamp': str(e['timestamp']), 'equity': e['equity']} for e in equity_curve]
    }

    with open('results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n결과 저장: results.json")

    return results


if __name__ == '__main__':
    config = load_config()
    results = run_backtest(config)
