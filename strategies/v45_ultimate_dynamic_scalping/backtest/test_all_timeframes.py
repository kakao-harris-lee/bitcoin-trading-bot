#!/usr/bin/env python3
"""
v45 - All Timeframes Test
Day, Minute240, Minute60 모든 타임프레임 테스트
"""

import sys
from pathlib import Path
from v43_replica_backtest import V45V43ReplicaBacktest
import json

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


def main():
    """모든 타임프레임 테스트 (2024년)"""

    results = {}

    # 테스트 설정
    configs = [
        {'timeframe': 'day', 'min_score': 40},
        {'timeframe': 'minute240', 'min_score': 35},
        {'timeframe': 'minute60', 'min_score': 30}
    ]

    for config in configs:
        tf = config['timeframe']
        score = config['min_score']

        print(f"\n{'='*80}")
        print(f"Testing: {tf} (Score >= {score})")
        print(f"{'='*80}\n")

        backtest = V45V43ReplicaBacktest()

        result = backtest.run_backtest(
            timeframe=tf,
            min_score=score,
            start_date='2024-01-01',
            end_date='2024-12-31'
        )

        results[tf] = {
            'min_score': score,
            'total_return_pct': result['total_return_pct'],
            'final_capital': result['final_capital'],
            'total_trades': result['total_trades'],
            'win_rate': result['win_rate'],
            'sharpe_ratio': result['sharpe_ratio'],
            'max_drawdown': result['max_drawdown'],
            'profit_factor': result['profit_factor'],
            'avg_hold_hours': result['avg_hold_hours']
        }

        # 개별 저장
        output_path = Path(__file__).parent.parent / 'results' / f'v45_{tf}_2024.json'
        backtest.save_results(result, str(output_path))

    # 종합 결과 저장
    summary_path = Path(__file__).parent.parent / 'results' / 'v45_all_timeframes_2024.json'
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # 비교 출력
    print(f"\n{'='*80}")
    print("v45 All Timeframes Comparison (2024)")
    print(f"{'='*80}\n")

    print(f"{'Timeframe':<12} {'Score':>5} {'Return':>10} {'Trades':>7} {'Win%':>6} {'Sharpe':>7}")
    print("-" * 80)

    for tf, res in results.items():
        print(f"{tf:<12} {res['min_score']:>5} {res['total_return_pct']:>9.2f}% "
              f"{res['total_trades']:>7} {res['win_rate']:>5.1f}% {res['sharpe_ratio']:>7.2f}")

    print(f"\n{'='*80}")
    print("v43 Comparison (2024):")
    print(f"  day Score 40: +1,345.97%")
    print(f"{'='*80}\n")

    # 최고 성과 타임프레임
    best_tf = max(results.items(), key=lambda x: x[1]['total_return_pct'])
    print(f"Best Timeframe: {best_tf[0]} (+{best_tf[1]['total_return_pct']:.2f}%)\n")


if __name__ == "__main__":
    main()
