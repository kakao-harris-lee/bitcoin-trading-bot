#!/usr/bin/env python3
"""
backtest_2025.py
v05 최적 파라미터로 2025년 검증
"""

import sys
sys.path.append('../..')
sys.path.append('../v04_adaptive_trend_rider')

import json
from core.data_loader import DataLoader
from core.backtester import Backtester
from core.evaluator import Evaluator
from core.market_analyzer import MarketAnalyzer
from strategy_simple import SimpleTrendFollowing, simple_strategy_wrapper


def main():
    print("=" * 80)
    print("v05 Optimized DAY Strategy - 2025 Validation")
    print("=" * 80)

    # 최적 파라미터 로드
    with open('optimized_day_params.json', 'r') as f:
        data = json.load(f)
        params = data['best_params']

    print(f"\nOptimized Parameters:")
    print(f"  position_fraction: {params['position_fraction']:.2f}")
    print(f"  trailing_stop_pct: {params['trailing_stop_pct']:.2f}")
    print(f"  stop_loss_pct: {params['stop_loss_pct']:.2f}")

    # 2025년 데이터 로드
    print(f"\nLoading 2025 data...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2025-01-01', end_date='2025-12-31')

    df = MarketAnalyzer.add_indicators(df, indicators=['ema'])
    print(f"  Loaded {len(df)} candles")

    # 백테스팅
    print(f"\nRunning backtest...")
    strategy = SimpleTrendFollowing(params)
    backtester = Backtester()

    results = backtester.run(
        df=df,
        strategy_func=simple_strategy_wrapper,
        strategy_params={'strategy_instance': strategy, 'backtester': backtester}
    )

    metrics = Evaluator.calculate_all_metrics(results)

    # 결과
    print("\n" + "=" * 80)
    print("2025 VALIDATION RESULTS")
    print("=" * 80)

    print(f"\n=== 2024 Performance (Training) ===")
    print(f"Return: {data['return']:.2f}%")
    print(f"Sharpe: {data['sharpe']:.2f}")
    print(f"MDD: {data['mdd']:.2f}%")

    print(f"\n=== 2025 Performance (Validation) ===")
    print(f"Return: {results['total_return']:.2f}%")
    print(f"Sharpe: {metrics['sharpe_ratio']:.2f}")
    print(f"MDD: {metrics['max_drawdown']:.2f}%")
    print(f"Trades: {results['total_trades']}")
    print(f"Win Rate: {results['win_rate']:.1%}")

    # Buy&Hold 계산
    buyhold_return = ((df.iloc[-1]['close'] - df.iloc[0]['close']) / df.iloc[0]['close']) * 100
    print(f"\n=== vs Buy&Hold (2025) ===")
    print(f"Buy&Hold: {buyhold_return:.2f}%")
    print(f"Strategy: {results['total_return']:.2f}%")
    print(f"Difference: {results['total_return'] - buyhold_return:+.2f}pp")

    # 일관성 평가
    performance_drop = data['return'] - results['total_return']
    consistent = performance_drop < 50  # 50%p 이상 하락하지 않으면 일관적

    print(f"\n=== Consistency ===")
    print(f"2024 → 2025 Drop: {performance_drop:.2f}pp")
    print(f"Status: {'✅ Consistent' if consistent else '⚠️  Degraded'}")

    print("=" * 80 + "\n")

    # 저장
    with open('results_2025_validation.json', 'w') as f:
        json.dump({
            'params': params,
            '2024_return': data['return'],
            '2025_return': results['total_return'],
            '2025_sharpe': metrics['sharpe_ratio'],
            '2025_mdd': metrics['max_drawdown'],
            '2025_trades': results['total_trades'],
            '2025_win_rate': results['win_rate'],
            'buyhold_2025': buyhold_return,
            'consistent': bool(consistent)
        }, f, indent=2)

    print("✅ Saved to: results_2025_validation.json\n")


if __name__ == "__main__":
    main()
