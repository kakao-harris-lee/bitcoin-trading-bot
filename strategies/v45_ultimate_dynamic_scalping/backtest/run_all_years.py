#!/usr/bin/env python3
"""
v45 전체 연도 백테스트 (2020-2025)
"""

import sys
from pathlib import Path
from v43_replica_backtest import V45V43ReplicaBacktest
import json

# MCP Time을 사용하여 현재 시간 가져오기
from datetime import datetime


def main():
    print("\n" + "=" * 100)
    print("v45 - 전체 연도 백테스트 (2020-2025)")
    print("=" * 100)

    years = [
        ('2020', '2020-01-01', '2020-12-31'),
        ('2021', '2021-01-01', '2021-12-31'),
        ('2022', '2022-01-01', '2022-12-31'),
        ('2023', '2023-01-01', '2023-12-31'),
        ('2024', '2024-01-01', '2024-12-31'),
        ('2025', '2025-01-01', '2025-10-20')  # Out-of-Sample
    ]

    all_results = {}

    for year, start, end in years:
        print(f"\n{'=' * 100}")
        print(f"{year}년 백테스트")
        print(f"{'=' * 100}")

        backtest = V45V43ReplicaBacktest()
        result = backtest.run_backtest(
            timeframe='day',
            min_score=40,
            start_date=start,
            end_date=end
        )

        all_results[year] = {
            'total_return_pct': result['total_return_pct'],
            'final_capital': result['final_capital'],
            'total_trades': result['total_trades'],
            'win_rate': result['win_rate'],
            'sharpe_ratio': result['sharpe_ratio'],
            'max_drawdown': result['max_drawdown'],
            'profit_factor': result['profit_factor']
        }

        # 개별 결과 저장
        output_path = Path(__file__).parent.parent / 'results' / f'v45_day_score40_{year}.json'
        backtest.save_results(result, str(output_path))

    # 종합 결과 출력
    print("\n" + "=" * 100)
    print("전체 연도 결과 요약")
    print("=" * 100)
    print(f"\n{'연도':^10} {'수익률':^15} {'거래':^10} {'승률':^10} {'Sharpe':^10} {'MDD':^10}")
    print("-" * 100)

    for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
        res = all_results[year]
        print(f"{year:^10} {res['total_return_pct']:>+13.2f}% {res['total_trades']:>9}회 "
              f"{res['win_rate']:>9.1f}% {res['sharpe_ratio']:>9.2f} {res['max_drawdown']:>9.2f}%")

    # 평균 계산 (2020-2024)
    learning_years = ['2020', '2021', '2022', '2023', '2024']
    avg_return = sum(all_results[y]['total_return_pct'] for y in learning_years) / len(learning_years)
    avg_trades = sum(all_results[y]['total_trades'] for y in learning_years) / len(learning_years)
    avg_win_rate = sum(all_results[y]['win_rate'] for y in learning_years) / len(learning_years)
    avg_sharpe = sum(all_results[y]['sharpe_ratio'] for y in learning_years) / len(learning_years)

    print("-" * 100)
    print(f"{'평균':^10} {avg_return:>+13.2f}% {avg_trades:>9.1f}회 "
          f"{avg_win_rate:>9.1f}% {avg_sharpe:>9.2f}")
    print()

    # 2025 강조
    print("=" * 100)
    print(f"2025 Out-of-Sample 검증 결과: {all_results['2025']['total_return_pct']:+.2f}%")
    print("=" * 100)

    # 전체 결과 저장
    summary_path = Path(__file__).parent.parent / 'results' / 'v45_all_years_summary.json'
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    print(f"\n종합 결과 저장: {summary_path}")
    print("\n" + "=" * 100)
    print("전체 백테스트 완료")
    print("=" * 100 + "\n")


if __name__ == "__main__":
    main()
