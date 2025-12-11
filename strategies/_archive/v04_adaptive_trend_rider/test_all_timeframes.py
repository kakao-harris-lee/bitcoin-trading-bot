#!/usr/bin/env python3
"""
test_all_timeframes.py
v04 Simple 전략을 모든 타임프레임에서 테스트
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
from datetime import datetime

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from core.backtester import Backtester
from core.evaluator import Evaluator

from strategy_simple import SimpleTrendFollowing, simple_strategy_wrapper


def test_timeframe(timeframe: str, config: dict):
    """특정 타임프레임 테스트"""

    print(f"\n{'='*80}")
    print(f"Testing {timeframe.upper()}")
    print(f"{'='*80}")

    # 데이터 로드
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(
            timeframe,
            start_date='2024-01-01',
            end_date='2024-12-30'
        )

    print(f"Loaded {len(df):,} candles")

    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, indicators=['ema'])

    # Buy&Hold 계산
    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    buyhold_return = ((end_price - start_price) / start_price) * 100

    # 백테스팅
    strategy = SimpleTrendFollowing(config)
    backtester = Backtester(
        initial_capital=config['initial_capital'],
        fee_rate=config['fee_rate'],
        slippage=config['slippage']
    )

    strategy_params = {
        'strategy_instance': strategy,
        'backtester': backtester
    }

    results = backtester.run(df, simple_strategy_wrapper, strategy_params)
    metrics = Evaluator.calculate_all_metrics(results)

    # 결과 출력
    print(f"\n=== Results ===")
    print(f"Buy&Hold:     {buyhold_return:7.2f}%")
    print(f"Strategy:     {metrics['total_return']:7.2f}% (vs BH: {metrics['total_return'] - buyhold_return:+.2f}%p)")
    print(f"Sharpe:       {metrics['sharpe_ratio']:7.2f}")
    print(f"MDD:          {metrics['max_drawdown']:7.2f}%")
    print(f"Trades:       {metrics['total_trades']:7d} (Win rate: {metrics['win_rate']:.1%})")
    print(f"Profit Factor:{metrics.get('profit_factor', 0):7.2f}")

    # 170% 달성 여부
    achieved = "✅" if metrics['total_return'] >= 170.0 else "❌"
    print(f"170% Target:  {achieved} ({metrics['total_return']:.2f}% vs 170%)")

    return {
        'timeframe': timeframe,
        'buyhold_return': buyhold_return,
        'strategy_return': metrics['total_return'],
        'sharpe_ratio': metrics['sharpe_ratio'],
        'max_drawdown': metrics['max_drawdown'],
        'total_trades': metrics['total_trades'],
        'win_rate': metrics['win_rate'],
        'profit_factor': metrics.get('profit_factor', 0),
        'metrics': metrics
    }


def main():
    """모든 타임프레임 테스트"""

    print("="*80)
    print("v04 Simple Strategy - All Timeframes Test")
    print("="*80)

    # 최적화된 config 로드
    with open('config_optimized.json', 'r') as f:
        config = json.load(f)

    print(f"\nOptimized Parameters:")
    print(f"  - position_fraction: {config['position_fraction']:.2f}")
    print(f"  - trailing_stop_pct: {config['trailing_stop_pct']:.2f}")
    print(f"  - stop_loss_pct: {config['stop_loss_pct']:.2f}")

    # 테스트할 타임프레임
    timeframes = [
        'minute5',
        'minute15',
        'minute30',
        'minute60',
        'minute240',
        'day'
    ]

    results = []

    # 각 타임프레임 테스트
    for tf in timeframes:
        try:
            result = test_timeframe(tf, config)
            results.append(result)
        except Exception as e:
            print(f"\n❌ Error testing {tf}: {e}")
            continue

    # 종합 결과 테이블
    print("\n" + "="*80)
    print("SUMMARY - ALL TIMEFRAMES")
    print("="*80)
    print()
    print(f"{'Timeframe':<12} {'Buy&Hold':>10} {'Strategy':>10} {'Gap':>8} "
          f"{'Sharpe':>8} {'MDD':>8} {'Trades':>8} {'Win%':>8} {'PF':>8} {'170%':>6}")
    print("-" * 110)

    for r in results:
        gap = r['strategy_return'] - r['buyhold_return']
        achieved = "✅" if r['strategy_return'] >= 170.0 else "❌"

        print(f"{r['timeframe']:<12} {r['buyhold_return']:>9.2f}% {r['strategy_return']:>9.2f}% "
              f"{gap:>7.2f}p {r['sharpe_ratio']:>8.2f} {r['max_drawdown']:>7.2f}% "
              f"{r['total_trades']:>8d} {r['win_rate']:>7.1%} {r['profit_factor']:>8.2f} {achieved:>6}")

    print()

    # 최고 성과 타임프레임
    best = max(results, key=lambda x: x['strategy_return'])
    print(f"\n🏆 Best Timeframe: {best['timeframe'].upper()} with {best['strategy_return']:.2f}% return")

    # 170% 달성 타임프레임
    achieved_170 = [r for r in results if r['strategy_return'] >= 170.0]
    if achieved_170:
        print(f"\n✅ 170% Target Achieved:")
        for r in achieved_170:
            print(f"   - {r['timeframe']}: {r['strategy_return']:.2f}%")
    else:
        print(f"\n❌ No timeframe achieved 170% target")
        print(f"   Best: {best['timeframe']} with {best['strategy_return']:.2f}% (Gap: {170 - best['strategy_return']:.2f}%p)")

    # 결과 저장
    summary = {
        'timestamp': datetime.now().isoformat(),
        'config': config,
        'results': results,
        'best_timeframe': best['timeframe'],
        'best_return': best['strategy_return']
    }

    with open('all_timeframes_results.json', 'w') as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n\nResults saved to: all_timeframes_results.json")
    print("="*80)


if __name__ == '__main__':
    main()
