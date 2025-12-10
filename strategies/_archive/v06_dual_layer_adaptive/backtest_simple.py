#!/usr/bin/env python3
"""
backtest_simple.py
v06 간단 백테스팅: Layer 1 (DAY) only 먼저 검증
"""

import sys
sys.path.append('../..')

import json
from core.data_loader import DataLoader
from core.backtester import Backtester
from core.evaluator import Evaluator
from core.market_analyzer import MarketAnalyzer
from layer1_day import DayStrategy


def simple_wrapper(df, i, params):
    """Backtester 호환 래퍼"""
    strategy = params['strategy']
    backtester = params['backtester']

    current_capital = backtester.cash + backtester.position_value
    signal = strategy.generate_signal(df, i, current_capital)

    if signal['action'] == 'buy':
        strategy.on_buy(df.iloc[i]['timestamp'], df.iloc[i]['close'])
    elif signal['action'] == 'sell':
        strategy.on_sell()

    return signal


def main():
    print("="*80)
    print("v06 Layer 1 (DAY) Verification")
    print("="*80)

    # Config 로드
    with open('config.json', 'r') as f:
        config = json.load(f)

    # DAY 데이터 로드
    print("\n[1/4] Loading DAY data...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    df = MarketAnalyzer.add_indicators(df, indicators=['ema'])
    print(f"  Loaded {len(df)} candles")

    # 전략 생성
    print("\n[2/4] Creating DAY strategy...")
    day_strategy = DayStrategy(config['layer1_day'])

    # 백테스팅
    print("\n[3/4] Running backtest...")
    backtester = Backtester()

    results = backtester.run(
        df=df,
        strategy_func=simple_wrapper,
        strategy_params={'strategy': day_strategy, 'backtester': backtester}
    )

    # 평가
    print("\n[4/4] Evaluating...")
    metrics = Evaluator.calculate_all_metrics(results)

    # 결과 출력
    print("\n" + "="*80)
    print("RESULTS")
    print("="*80)

    print(f"\nInitial: {results['initial_capital']:,.0f} KRW")
    print(f"Final: {results['final_capital']:,.0f} KRW")
    print(f"Return: {results['total_return']:.2f}%")
    print(f"Sharpe: {metrics['sharpe_ratio']:.2f}")
    print(f"MDD: {metrics['max_drawdown']:.2f}%")
    print(f"Trades: {results['total_trades']}")
    print(f"Win Rate: {results['win_rate']:.1%}")

    # v05 비교
    v05_return = 293.38
    diff = results['total_return'] - v05_return

    print(f"\nvs v05: {diff:+.2f}pp")

    if abs(diff) < 1.0:
        print("✅ DAY strategy correctly implemented (matches v05)")
    else:
        print("⚠️  DAY strategy differs from v05 - check implementation")

    print("="*80 + "\n")


if __name__ == "__main__":
    main()
