#!/usr/bin/env python3
"""
v44 Supreme Hybrid Scalping Backtest Runner
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../core'))

from ensemble_coordinator import EnsembleCoordinator
import json


def run_single_backtest(year):
    """단일 연도 백테스트"""
    coordinator = EnsembleCoordinator('../config/base_config.json')

    start_date = f'{year}-01-01'
    end_date = f'{year+1}-01-01' if year < 2025 else '2025-10-20'

    results = coordinator.run_backtest(start_date, end_date)
    coordinator.print_results(results)

    return results, coordinator.all_trades


def run_multi_year_backtest(years):
    """다중 연도 백테스트"""
    all_results = {}

    for year in years:
        print(f"\n\n{'#'*80}")
        print(f"# {year}년 백테스트")
        print(f"{'#'*80}\n")

        results, trades = run_single_backtest(year)
        all_results[year] = results

        # 간단 요약
        print(f"\n{year}년 요약:")
        print(f"  수익률: {results['total_return_pct']:.2f}%")
        print(f"  거래수: {results['total_trades']}회")
        print(f"  승률: {results['win_rate']*100:.1f}%")
        print(f"  Sharpe: {results['sharpe_ratio']:.2f}\n")

    # 전체 요약
    print(f"\n\n{'='*80}")
    print("전체 요약")
    print(f"{'='*80}\n")

    returns = [all_results[y]['total_return_pct'] for y in years]
    avg_return = sum(returns) / len(returns)

    print(f"{'연도':<8} | {'수익률':<10} | {'거래수':<8} | {'승률':<8} | {'Sharpe':<8}")
    print("-" * 80)

    for year in years:
        r = all_results[year]
        print(f"{year:<8} | {r['total_return_pct']:>8.2f}% | {r['total_trades']:>8} | {r['win_rate']*100:>6.1f}% | {r['sharpe_ratio']:>8.2f}")

    print("-" * 80)
    print(f"{'평균':<8} | {avg_return:>8.2f}%")

    # 결과 저장
    with open('../results/multi_year_results.json', 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    print(f"\n결과 저장: ../results/multi_year_results.json\n")

    return all_results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='v44 백테스트')
    parser.add_argument('--year', type=int, help='단일 연도 (예: 2024)')
    parser.add_argument('--all', action='store_true', help='전체 연도 (2020-2025)')

    args = parser.parse_args()

    if args.year:
        # 단일 연도
        results, trades = run_single_backtest(args.year)

        # 결과 저장
        with open(f'../results/result_{args.year}.json', 'w') as f:
            json.dump(results, f, indent=2, default=str)

        print(f"\n결과 저장: ../results/result_{args.year}.json\n")

    elif args.all:
        # 전체 연도
        years = [2020, 2021, 2022, 2023, 2024, 2025]
        run_multi_year_backtest(years)

    else:
        # 기본: 2024년
        print("기본 실행: 2024년 백테스트")
        print("다른 연도: --year 2023")
        print("전체 연도: --all\n")

        results, trades = run_single_backtest(2024)

        with open('../results/result_2024.json', 'w') as f:
            json.dump(results, f, indent=2, default=str)

        print(f"\n결과 저장: ../results/result_2024.json\n")
