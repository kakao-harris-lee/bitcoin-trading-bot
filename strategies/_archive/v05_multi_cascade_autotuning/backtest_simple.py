#!/usr/bin/env python3
"""
backtest_simple.py
v05 Simplified: DAY (95%) + minute240 (5%)
"""

import sys
sys.path.append('../..')

import json
from core.data_loader import DataLoader
from core.evaluator import Evaluator
from core.market_analyzer import MarketAnalyzer
from multi_timeframe_backtester import MultiTimeframeBacktester
from strategy_cascade import CascadeStrategy, cascade_strategy_wrapper


def main():
    print("=" * 80)
    print("v05 Simplified: DAY (95%) + minute240 (5%)")
    print("=" * 80)

    # 설정 로드
    with open('config_simple.json', 'r') as f:
        config = json.load(f)

    # 데이터 로드
    print("\n[1/4] Loading data...")
    dataframes = {}

    with DataLoader('../../upbit_bitcoin.db') as loader:
        for layer in config['layers'].keys():
            tf = config['layers'][layer]['timeframe']
            print(f"  Loading {tf}...", end=' ')
            df = loader.load_timeframe(tf, start_date='2024-01-01', end_date='2024-12-31')
            df = MarketAnalyzer.add_indicators(df, indicators=['ema'])
            dataframes[tf] = df
            print(f"{len(df)} candles")

    # 전략 생성
    print("\n[2/4] Creating strategy...")
    strategy = CascadeStrategy(config)

    # 백테스팅
    print("\n[3/4] Running backtest...")
    backtest_config = config['backtest_settings']
    backtester = MultiTimeframeBacktester(
        config=config,
        initial_capital=backtest_config['initial_capital'],
        fee_rate=backtest_config['fee_rate'],
        slippage=backtest_config['slippage']
    )

    results = backtester.run(
        dataframes=dataframes,
        strategy_func=cascade_strategy_wrapper,
        strategy_params={'strategy_instance': strategy}
    )

    # 지표 계산
    print("\n[4/4] Calculating metrics...")
    metrics = Evaluator.calculate_all_metrics(results)

    # 결과 출력
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)

    baseline = config['baseline']
    print(f"\n=== v04 Baseline ===")
    print(f"Return: {baseline['v04_return_2024']:.2f}%")
    print(f"Sharpe: {baseline['v04_sharpe']:.2f}")
    print(f"MDD: {baseline['v04_mdd']:.2f}%")
    print(f"Trades: {baseline['v04_trades']}")

    print(f"\n=== v05 Performance ===")
    print(f"Initial: {results['initial_capital']:,.0f} KRW")
    print(f"Final: {results['final_capital']:,.0f} KRW")
    print(f"Return: {results['total_return']:.2f}%")
    print(f"  vs v04: {results['total_return'] - baseline['v04_return_2024']:+.2f}pp")
    print(f"Sharpe: {metrics['sharpe_ratio']:.2f}")
    print(f"MDD: {metrics['max_drawdown']:.2f}%")

    print(f"\n=== Trading Stats ===")
    print(f"Total Trades: {results['total_trades']}")
    print(f"Win Rate: {results['win_rate']:.1%}")
    print(f"Profit Factor: {results['profit_factor']:.2f}")

    # 레이어별
    print(f"\n=== Layer Breakdown ===")
    for layer, stats in results.get('layer_stats', {}).items():
        print(f"{layer.upper()}: {stats['total_trades']} trades, "
              f"{stats['win_rate']:.1%} win rate, "
              f"{stats['total_pnl']:,.0f} KRW")

    # 목표 달성
    target = baseline['v05_target']
    achieved = results['total_return'] >= target
    print(f"\n=== Goal ===")
    print(f"Target: {target:.2f}%")
    print(f"Status: {'✅ ACHIEVED' if achieved else '❌ NOT MET'}")

    print("=" * 80 + "\n")

    # 저장
    with open('results_simple.json', 'w') as f:
        json.dump({
            'config': 'config_simple.json',
            'return': results['total_return'],
            'sharpe': metrics['sharpe_ratio'],
            'mdd': metrics['max_drawdown'],
            'trades': results['total_trades'],
            'win_rate': results['win_rate'],
            'layer_stats': results.get('layer_stats', {})
        }, f, indent=2)

    print("✅ Results saved to results_simple.json\n")


if __name__ == "__main__":
    main()
