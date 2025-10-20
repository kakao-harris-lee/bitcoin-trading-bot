#!/usr/bin/env python3
"""
v43 - Comprehensive Backtest
모든 타임프레임 × 모든 연도 × 모든 Score 조합 테스트
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from v41_replica_backtest import V41ReplicaBacktest
import json
import pandas as pd
from datetime import datetime


def run_all_combinations():
    """모든 조합 백테스트"""

    # 테스트 조합
    timeframes = ['day', 'minute240', 'minute60', 'minute15']
    years = [
        ('2020', '2020-01-01', '2021-01-01'),
        ('2021', '2021-01-01', '2022-01-01'),
        ('2022', '2022-01-01', '2023-01-01'),
        ('2023', '2023-01-01', '2024-01-01'),
        ('2024', '2024-01-01', '2025-01-01'),
    ]
    scores = [20, 25, 30, 35, 40]

    engine = V41ReplicaBacktest()

    all_results = []
    total_tests = len(timeframes) * len(years) * len(scores)
    current = 0

    print(f"\n{'='*80}")
    print(f"v43 Comprehensive Backtest")
    print(f"총 {total_tests}개 테스트 ({len(timeframes)} TF × {len(years)} years × {len(scores)} scores)")
    print(f"{'='*80}\n")

    for timeframe in timeframes:
        for year_name, start_date, end_date in years:
            for min_score in scores:
                current += 1

                print(f"\n[{current}/{total_tests}] {timeframe} {year_name} Score>={min_score}")

                try:
                    stats, trades = engine.run(
                        timeframe=timeframe,
                        start_date=start_date,
                        end_date=end_date,
                        min_score=min_score
                    )

                    if stats:
                        result = {
                            'timeframe': timeframe,
                            'year': year_name,
                            'min_score': min_score,
                            'total_return_pct': stats['total_return'] * 100,
                            'total_trades': stats['total_trades'],
                            'win_rate': stats['win_rate'] * 100,
                            'profit_factor': stats['profit_factor'],
                            'sharpe_ratio': stats['sharpe_ratio'],
                            'avg_hold_hours': stats['avg_hold_hours']
                        }

                        all_results.append(result)

                        print(f"  → 수익률: {result['total_return_pct']:.1f}%, "
                              f"거래: {result['total_trades']}회, "
                              f"승률: {result['win_rate']:.1f}%")

                except Exception as e:
                    print(f"  → 오류: {e}")
                    continue

    # 결과 저장
    output_file = '../results/comprehensive_results.json'
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"\n결과 저장: {output_file}")
    print(f"총 {len(all_results)}개 결과\n")

    return all_results


def analyze_top_strategies(results):
    """TOP 전략 분석 (2020-2024 평균)"""

    print(f"\n{'='*80}")
    print(f"2020-2024 평균 수익률 기준 TOP 10 분석")
    print(f"{'='*80}\n")

    # DataFrame 변환
    df = pd.DataFrame(results)

    # 연도별 그룹화
    grouped = df.groupby(['timeframe', 'min_score'])

    top_strategies = []

    for (timeframe, score), group in grouped:
        # 2020-2024만
        group_2024 = group[group['year'].isin(['2020', '2021', '2022', '2023', '2024'])]

        if len(group_2024) < 5:
            continue

        # 평균 계산
        avg_return = group_2024['total_return_pct'].mean()
        avg_trades = group_2024['total_trades'].mean()
        avg_win_rate = group_2024['win_rate'].mean()
        avg_pf = group_2024['profit_factor'].mean()
        avg_sharpe = group_2024['sharpe_ratio'].mean()

        # 연도별 수익률
        year_returns = {}
        for _, row in group_2024.iterrows():
            year_returns[row['year']] = row['total_return_pct']

        top_strategies.append({
            'name': f"{timeframe}_score{score}",
            'timeframe': timeframe,
            'min_score': score,
            'avg_return_2020_2024': avg_return,
            'avg_trades': avg_trades,
            'avg_win_rate': avg_win_rate,
            'avg_pf': avg_pf,
            'avg_sharpe': avg_sharpe,
            **year_returns
        })

    # 평균 수익률 순 정렬
    top_strategies.sort(key=lambda x: x['avg_return_2020_2024'], reverse=True)

    # TOP 10 출력
    print(f"{'순위':<5} {'전략':<25} {'평균수익':>10} {'2020':>8} {'2021':>8} {'2022':>8} {'2023':>8} {'2024':>8}")
    print("-"*80)

    for i, s in enumerate(top_strategies[:10], 1):
        print(f"{i:<5} {s['name']:<25} {s['avg_return_2020_2024']:>9.1f}% "
              f"{s.get('2020', 0):>7.0f}% "
              f"{s.get('2021', 0):>7.0f}% "
              f"{s.get('2022', 0):>7.0f}% "
              f"{s.get('2023', 0):>7.0f}% "
              f"{s.get('2024', 0):>7.0f}%")

    # 상세 통계
    print(f"\n{'='*80}")
    print(f"TOP 10 상세 통계")
    print(f"{'='*80}\n")

    for i, s in enumerate(top_strategies[:10], 1):
        print(f"\n{i}. {s['name']}")
        print(f"   평균 수익률: {s['avg_return_2020_2024']:.2f}%")
        print(f"   평균 거래: {s['avg_trades']:.0f}회")
        print(f"   평균 승률: {s['avg_win_rate']:.1f}%")
        print(f"   평균 PF: {s['avg_pf']:.2f}")
        print(f"   평균 Sharpe: {s['avg_sharpe']:.2f}")

    # 저장
    output_file = '../results/top10_strategies_2020_2024.json'
    with open(output_file, 'w') as f:
        json.dump(top_strategies[:10], f, indent=2, ensure_ascii=False)

    print(f"\n\nTOP 10 저장: {output_file}\n")

    return top_strategies[:10]


def main():
    """메인"""

    # 1. 전체 백테스트 실행
    results = run_all_combinations()

    # 2. TOP 10 분석
    top10 = analyze_top_strategies(results)


if __name__ == '__main__':
    main()
