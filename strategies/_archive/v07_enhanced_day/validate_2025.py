#!/usr/bin/env python3
"""
Out-of-Sample Validation on 2025 Data

최적화된 파라미터를 2025년 데이터로 검증
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
from datetime import datetime
from core.data_loader import DataLoader
from core.evaluator import Evaluator
from simple_backtester import SimpleBacktester
from strategy import v07_strategy


def main():
    print("="*80)
    print("v07 Out-of-Sample Validation (2025)")
    print("="*80)

    # Load optimized params
    with open('optuna_results.json', 'r') as f:
        optuna_results = json.load(f)

    best_params = optuna_results['best_params']

    print("\n최적 파라미터:")
    for key, value in best_params.items():
        print(f"  {key}: {value}")

    # Load 2025 data
    print("\n[1/4] 2025년 데이터 로드...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2025-01-01', end_date='2025-10-17')

    print(f"  {len(df)}개 캔들 (2025-01-01 ~ 2025-10-17)")

    if len(df) < 30:
        print("\n경고: 2025년 데이터가 부족합니다")
        return

    # Add indicators
    print("\n[2/4] 지표 추가...")
    df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['prev_ema12'] = df['ema12'].shift(1)
    df['prev_ema26'] = df['ema26'].shift(1)

    macd_fast = best_params['macd_fast']
    macd_slow = best_params['macd_slow']
    macd_signal = best_params['macd_signal']

    exp1 = df['close'].ewm(span=macd_fast, adjust=False).mean()
    exp2 = df['close'].ewm(span=macd_slow, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=macd_signal, adjust=False).mean()
    df['prev_macd'] = df['macd'].shift(1)
    df['prev_macd_signal'] = df['macd_signal'].shift(1)

    # Backtest
    print("\n[3/4] 백테스팅...")

    v07_strategy.in_position = False
    v07_strategy.entry_price = None
    v07_strategy.highest_price = None

    backtester = SimpleBacktester(10_000_000, 0.0005, 0.0002)

    params = {
        'trailing_stop_pct': best_params['trailing_stop_pct'],
        'stop_loss_pct': best_params['stop_loss_pct'],
        'position_fraction': 0.95
    }

    for i in range(len(df)):
        row = df.iloc[i]
        timestamp = row['timestamp']
        price = row['close']

        decision = v07_strategy(df, i, params)
        if decision['action'] == 'buy':
            backtester.execute_buy(timestamp, price, decision['fraction'])
            print(f"  BUY: {timestamp.date()} @ {price:,.0f}원")
        elif decision['action'] == 'sell':
            backtester.execute_sell(timestamp, price, decision['fraction'])
            print(f"  SELL: {timestamp.date()} @ {price:,.0f}원")

        backtester.record_equity(timestamp, price)

    if backtester.position > 0:
        final_time = df.iloc[-1]['timestamp']
        final_price = df.iloc[-1]['close']
        backtester.execute_sell(final_time, final_price, 1.0)
        backtester.record_equity(final_time, final_price)
        print(f"  [최종 청산]: {final_time.date()} @ {final_price:,.0f}원")

    # Evaluate
    print("\n[4/4] 결과 평가...")
    results = backtester.get_results()
    metrics = Evaluator.calculate_all_metrics(results)

    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    buy_hold = ((end_price - start_price) / start_price) * 100

    print("\n" + "="*80)
    print("Out-of-Sample 검증 결과 (2025년)")
    print("="*80)

    print(f"\n수익률:         {metrics['total_return']:>14.2f}%")
    print(f"Buy&Hold:       {buy_hold:>14.2f}%")
    print(f"차이:           {metrics['total_return'] - buy_hold:>14.2f}%p")

    print(f"\nSharpe Ratio:   {metrics['sharpe_ratio']:>14.2f}")
    print(f"Max Drawdown:   {metrics['max_drawdown']:>14.2f}%")

    print(f"\n총 거래:        {metrics['total_trades']:>15}회")
    print(f"승률:           {metrics['win_rate']:>14.1%}")
    print(f"Profit Factor:  {metrics.get('profit_factor', 0):>14.2f}")

    print("\n="*80)

    # Overfitting check
    train_return = 148.63  # 2024년 최적화 결과
    test_return = metrics['total_return']
    degradation = ((train_return - test_return) / train_return) * 100

    print("\n오버피팅 검사:")
    print(f"  Train (2024): {train_return:.2f}%")
    print(f"  Test (2025):  {test_return:.2f}%")
    print(f"  성능 저하:     {degradation:.2f}%")

    if degradation < 20:
        print("  ✅ 양호: 오버피팅 없음")
    elif degradation < 40:
        print("  ⚠️  주의: 약간의 오버피팅")
    else:
        print("  ❌ 심각: 심각한 오버피팅")

    # Save
    output = {
        'timestamp': datetime.now().isoformat(),
        'period': '2025-01-01 ~ 2025-10-17',
        'metrics': metrics,
        'buy_hold_return': buy_hold,
        'train_return': train_return,
        'test_return': test_return,
        'degradation_pct': degradation
    }

    with open('validation_2025.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print("\n결과 저장: validation_2025.json")


if __name__ == '__main__':
    main()
