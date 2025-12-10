#!/usr/bin/env python3
"""
v09 Walk-Forward 분석

연도별 성과를 측정하여 전략의 일관성 확인
"""

import sys
sys.path.append('../..')

import json
from backtest_simple import run_backtest


def walk_forward_analysis():
    """Walk-Forward 분석 실행"""
    print("="*80)
    print("v09 Walk-Forward 분석")
    print("="*80)

    # 최적 파라미터
    with open('optuna_results.json', 'r') as f:
        data = json.load(f)

    params = data['best_params']

    print(f"\n최적 파라미터:")
    print(f"  Trailing Stop: {params['trailing_stop_pct']:.2%}")
    print(f"  Stop Loss: {params['stop_loss_pct']:.2%}\n")

    # 연도별 백테스팅
    years = [
        ('2019', '2019-01-01', '2019-12-31'),
        ('2020', '2020-01-01', '2020-12-31'),
        ('2021', '2021-01-01', '2021-12-31'),
        ('2022', '2022-01-01', '2022-12-31'),
        ('2023', '2023-01-01', '2023-12-31'),
        ('2024', '2024-01-01', '2024-12-31'),
        ('2025', '2025-01-01', '2025-10-17')
    ]

    results_by_year = []

    for year, start, end in years:
        print(f"[{year}] 백테스팅 중...")
        results = run_backtest(start, end, params)

        results_by_year.append({
            'year': year,
            'return': results['total_return'],
            'sharpe': results['sharpe_ratio'],
            'mdd': results['max_drawdown'],
            'trades': results['total_trades'],
            'win_rate': results['win_rate']
        })

        print(f"  수익률: {results['total_return']:>7.2f}%, "
              f"Sharpe: {results['sharpe_ratio']:>5.2f}, "
              f"MDD: {results['max_drawdown']:>5.2f}%, "
              f"거래: {results['total_trades']:>2}회\n")

    # 통계
    returns = [r['return'] for r in results_by_year]
    import numpy as np

    mean_return = np.mean(returns)
    std_return = np.std(returns)
    min_return = np.min(returns)
    max_return = np.max(returns)

    print(f"{'='*80}")
    print("통계 요약")
    print(f"{'='*80}")
    print(f"평균 수익률: {mean_return:.2f}%")
    print(f"표준편차: {std_return:.2f}%")
    print(f"최대 수익률: {max_return:.2f}% ({results_by_year[returns.index(max_return)]['year']})")
    print(f"최소 수익률: {min_return:.2f}% ({results_by_year[returns.index(min_return)]['year']})")
    print(f"일관성: {'✅ 높음' if std_return < 100 else '❌ 낮음'} (표준편차 {std_return:.1f}%)\n")

    # 저장
    walk_forward_data = {
        'params': params,
        'results_by_year': results_by_year,
        'statistics': {
            'mean_return': float(mean_return),
            'std_return': float(std_return),
            'min_return': float(min_return),
            'max_return': float(max_return)
        }
    }

    with open('walk_forward_results.json', 'w') as f:
        json.dump(walk_forward_data, f, indent=2)

    print("결과 저장: walk_forward_results.json\n")


if __name__ == '__main__':
    walk_forward_analysis()
