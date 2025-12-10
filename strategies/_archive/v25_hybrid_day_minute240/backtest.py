#!/usr/bin/env python3
"""v25 하이브리드 백테스팅"""

import sys, json
from pathlib import Path
import sqlite3, pandas as pd, talib

def load_data(db_path, timeframe, start, end=None):
    conn = sqlite3.connect(db_path)
    query = f"""SELECT timestamp, opening_price as open, high_price as high,
                low_price as low, trade_price as close, candle_acc_trade_volume as volume
                FROM bitcoin_{timeframe}
                WHERE timestamp >= '{start}' {'AND timestamp < ' + chr(39) + end + chr(39) if end else ''}
                ORDER BY timestamp ASC"""
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def add_indicators(df):
    close, high, low, volume = df['close'].values, df['high'].values, df['low'].values, df['volume'].values
    df['rsi'] = talib.RSI(close, 14)
    upper, middle, lower = talib.BBANDS(close, 20, 2, 2)
    df['bb_upper'], df['bb_middle'], df['bb_lower'] = upper, middle, lower
    df['bb_position'] = (close - lower) / (upper - lower)
    df['volume_sma'] = talib.SMA(volume, 20)
    df['volume_ratio'] = volume / df['volume_sma']
    return df

def run_single_backtest(df, config, initial_capital):
    capital, position, entry_price, trades = initial_capital, 0, 0, []
    entry_cfg, exit_cfg, risk_cfg = config['entry'], config['exit'], config['risk']
    fee_rate = 0.0005
    
    for i in range(26, len(df)):
        row = df.iloc[i]
        if pd.isna(row['rsi']) or pd.isna(row['bb_position']) or pd.isna(row['volume_ratio']):
            continue
            
        # 손절/익절
        if position > 0:
            profit_pct = (row['close'] - entry_price) / entry_price
            if profit_pct <= risk_cfg['stop_loss']:
                capital = position * row['close'] * (1 - fee_rate)
                trades.append({'type': 'sell', 'price': row['close'], 'profit': profit_pct * 100})
                position, entry_price = 0, 0
                continue
            if profit_pct >= risk_cfg['take_profit']:
                capital = position * row['close'] * (1 - fee_rate)
                trades.append({'type': 'sell', 'price': row['close'], 'profit': profit_pct * 100})
                position, entry_price = 0, 0
                continue
        
        # 진입
        if position == 0 and row['rsi'] < entry_cfg['rsi_threshold'] and \
           row['bb_position'] < entry_cfg['bb_threshold'] and \
           row['volume_ratio'] > entry_cfg['volume_threshold']:
            position = (capital * (1 - fee_rate)) / row['close']
            entry_price, capital = row['close'], 0
            trades.append({'type': 'buy', 'price': row['close']})
        
        # 청산
        elif position > 0 and (row['rsi'] > exit_cfg['rsi_threshold'] or \
                                row['bb_position'] > exit_cfg['bb_threshold']):
            capital = position * row['close'] * (1 - fee_rate)
            profit_pct = (row['close'] - entry_price) / entry_price
            trades.append({'type': 'sell', 'price': row['close'], 'profit': profit_pct * 100})
            position, entry_price = 0, 0
    
    if position > 0:
        capital = position * df.iloc[-1]['close'] * (1 - fee_rate)
        trades.append({'type': 'sell', 'price': df.iloc[-1]['close'], 
                      'profit': ((df.iloc[-1]['close'] - entry_price) / entry_price) * 100})
    
    total_return = ((capital - initial_capital) / initial_capital) * 100
    num_trades = len([t for t in trades if t['type'] == 'buy'])
    winning = [t for t in trades if t['type'] == 'sell' and t.get('profit', 0) > 0]
    win_rate = len(winning) / num_trades if num_trades > 0 else 0
    
    return {
        'final_capital': capital,
        'total_return': total_return,
        'num_trades': num_trades,
        'win_rate': win_rate,
        'trades': trades
    }

def main():
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path) as f:
        config = json.load(f)
    
    db_path = Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'
    initial_capital = config['risk_management']['initial_capital']
    
    print(f"\n{'='*80}")
    print(f"v25 백테스팅: {config['description']}")
    print(f"{'='*80}")
    
    # 훈련 기간
    print(f"\n📊 훈련 기간: {config['backtest_period']['train_start']} ~ {config['backtest_period']['train_end']}")
    
    # Day 전략
    df_day = load_data(db_path, 'day', config['backtest_period']['train_start'], 
                       config['backtest_period']['test_start'])
    df_day = add_indicators(df_day)
    day_capital = initial_capital * config['allocation']['day']
    day_result = run_single_backtest(df_day, config['day_strategy'], day_capital)
    
    # Minute240 전략
    df_m240 = load_data(db_path, 'minute240', config['backtest_period']['train_start'],
                        config['backtest_period']['test_start'])
    df_m240 = add_indicators(df_m240)
    m240_capital = initial_capital * config['allocation']['minute240']
    m240_result = run_single_backtest(df_m240, config['minute240_strategy'], m240_capital)
    
    # 통합
    total_final = day_result['final_capital'] + m240_result['final_capital']
    total_return = ((total_final - initial_capital) / initial_capital) * 100
    
    print(f"\nDay (70%):")
    print(f"  수익률: {day_result['total_return']:.2f}%")
    print(f"  거래: {day_result['num_trades']}회, 승률: {day_result['win_rate']*100:.1f}%")
    
    print(f"\nMinute240 (30%):")
    print(f"  수익률: {m240_result['total_return']:.2f}%")
    print(f"  거래: {m240_result['num_trades']}회, 승률: {m240_result['win_rate']*100:.1f}%")
    
    print(f"\n통합 결과:")
    print(f"  초기: {initial_capital:,.0f}원")
    print(f"  최종: {total_final:,.0f}원")
    print(f"  총 수익률: {total_return:.2f}%")
    
    # 테스트 기간
    print(f"\n📊 테스트 기간: {config['backtest_period']['test_start']} ~ {config['backtest_period']['test_end']}")
    
    df_day_test = load_data(db_path, 'day', config['backtest_period']['test_start'],
                            config['backtest_period']['test_end'])
    if len(df_day_test) > 0:
        df_day_test = add_indicators(df_day_test)
        day_test = run_single_backtest(df_day_test, config['day_strategy'], day_capital)
        
        df_m240_test = load_data(db_path, 'minute240', config['backtest_period']['test_start'],
                                 config['backtest_period']['test_end'])
        df_m240_test = add_indicators(df_m240_test)
        m240_test = run_single_backtest(df_m240_test, config['minute240_strategy'], m240_capital)
        
        test_final = day_test['final_capital'] + m240_test['final_capital']
        test_return = ((test_final - initial_capital) / initial_capital) * 100
        
        print(f"\n통합 결과:")
        print(f"  총 수익률: {test_return:.2f}%")
    
    print(f"\n{'='*80}")
    print("목표 달성 여부")
    print(f"{'='*80}")
    avg_return = total_return / 3
    print(f"\n연평균 수익률: {avg_return:.2f}%")
    print(f"목표 (79.75%): {'✅ 달성' if avg_return >= 79.75 else '❌ 미달성'}")

if __name__ == '__main__':
    main()
