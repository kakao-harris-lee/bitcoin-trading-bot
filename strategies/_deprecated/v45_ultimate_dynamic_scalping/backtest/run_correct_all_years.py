#!/usr/bin/env python3
"""
올바른 복리 - 전체 연도 백테스트 (2020-2025)
"""

import json
from pathlib import Path
from correct_compound_backtest import CorrectCompoundBacktest


def main():
    """전체 연도 백테스트"""

    years = [
        ('2020', '2020-01-01', '2020-12-31'),
        ('2021', '2021-01-01', '2021-12-31'),
        ('2022', '2022-01-01', '2022-12-31'),
        ('2023', '2023-01-01', '2023-12-31'),
        ('2024', '2024-01-01', '2024-12-31'),
        ('2025', '2025-01-01', '2025-12-31'),
    ]

    all_results = {}

    print("\n" + "=" * 80)
    print("올바른 복리 - 전체 연도 백테스트 (2020-2025)")
    print("=" * 80)

    for year, start, end in years:
        print(f"\n{'='*80}")
        print(f"Testing: {year}")
        print(f"{'='*80}")

        backtest = CorrectCompoundBacktest()

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

        # 개별 저장
        output_path = Path(__file__).parent.parent / 'results' / f'correct_compound_day_{year}.json'
        backtest.save_results(result, str(output_path))

    # 종합 저장
    summary_path = Path(__file__).parent.parent / 'results' / 'correct_compound_all_years.json'
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    # 종합 출력
    print(f"\n\n{'='*80}")
    print("올바른 복리 - 전체 연도 요약")
    print(f"{'='*80}\n")

    print(f"{'연도':<6} {'수익률':>10} {'거래':>7} {'승률':>6} {'Sharpe':>7} {'MDD':>8}")
    print("-" * 80)

    for year, res in all_results.items():
        print(f"{year:<6} {res['total_return_pct']:>9.2f}% "
              f"{res['total_trades']:>7} "
              f"{res['win_rate']:>5.1f}% "
              f"{res['sharpe_ratio']:>7.2f} "
              f"{res['max_drawdown']:>7.2f}%")

    # 평균 계산
    avg_return = sum(r['total_return_pct'] for r in all_results.values()) / len(all_results)
    avg_trades = sum(r['total_trades'] for r in all_results.values()) / len(all_results)
    avg_sharpe = sum(r['sharpe_ratio'] for r in all_results.values()) / len(all_results)

    print("-" * 80)
    print(f"{'평균':<6} {avg_return:>9.2f}% {avg_trades:>7.1f} {'':>6} {avg_sharpe:>7.2f}")

    print(f"\n{'='*80}")
    print("비교: v43 (버그) vs 올바른 복리")
    print(f"{'='*80}\n")

    v43_results = {
        '2020': 218.46,
        '2021': 471.20,
        '2022': 110.41,
        '2023': 465.60,
        '2024': 1276.99,
        '2025': 1595.62
    }

    print(f"{'연도':<6} {'v43 (버그)':>12} {'올바른 복리':>12} {'차이':>10}")
    print("-" * 80)

    for year in all_results.keys():
        v43 = v43_results.get(year, 0)
        correct = all_results[year]['total_return_pct']
        diff = v43 / correct if correct != 0 else 0

        print(f"{year:<6} {v43:>11.2f}% {correct:>11.2f}% {diff:>9.1f}x")

    v43_avg = sum(v43_results.values()) / len(v43_results)
    diff_avg = v43_avg / avg_return if avg_return != 0 else 0

    print("-" * 80)
    print(f"{'평균':<6} {v43_avg:>11.2f}% {avg_return:>11.2f}% {diff_avg:>9.1f}x")

    print(f"\n{'='*80}")
    print(f"결과 저장: {summary_path}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
