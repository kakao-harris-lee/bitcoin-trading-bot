#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-Year Results Analyzer
result_2022~2025.json 통합 분석
"""

import sys
import json
import argparse
from pathlib import Path
import statistics

def load_year_result(strategy_path, year):
    """특정 연도 결과 로드"""
    result_file = strategy_path / f"result_{year}.json"

    if not result_file.exists():
        return None

    with open(result_file, 'r') as f:
        return json.load(f)


def calculate_buyhold(year):
    """Buy&Hold 기준선 (알려진 값)"""
    buyhold_data = {
        2024: 137.49,
        2025: 19.26,  # ~10월까지
        # 2022, 2023은 자동 계산 필요
    }
    return buyhold_data.get(year, None)


def analyze_multi_year(strategy_path, years=[2022, 2023, 2024, 2025]):
    """4년 통합 분석"""
    results = {}
    returns = []
    win_rates = []
    trade_counts = []
    buyhold_returns = []

    print(f"\n{'='*80}")
    print("연도별 성과")
    print(f"{'='*80}\n")

    for year in years:
        data = load_year_result(strategy_path, year)

        if not data:
            print(f"⚠️  {year}년 데이터 없음 (result_{year}.json)")
            continue

        total_return = data.get('total_return_pct', 0)
        win_rate = data.get('win_rate', 0)
        total_trades = data.get('total_trades', 0)
        buyhold = calculate_buyhold(year)

        results[year] = {
            'total_return': total_return,
            'win_rate': win_rate,
            'total_trades': total_trades,
            'buyhold': buyhold,
            'diff': total_return - buyhold if buyhold else None
        }

        returns.append(total_return)
        win_rates.append(win_rate)
        trade_counts.append(total_trades)

        if buyhold:
            buyhold_returns.append(buyhold)

        print(f"{year}년:")
        print(f"  수익률: {total_return:+.2f}%")
        print(f"  승률: {win_rate:.1f}%")
        print(f"  거래: {total_trades}회")

        if buyhold:
            print(f"  Buy&Hold: {buyhold:+.2f}%")
            print(f"  차이: {total_return - buyhold:+.2f}%p")
        else:
            print(f"  Buy&Hold: (계산 필요)")

        print()

    # 4년 통합 통계
    print(f"{'='*80}")
    print("4년 통합 통계")
    print(f"{'='*80}\n")

    avg_return = statistics.mean(returns)
    std_return = statistics.stdev(returns) if len(returns) > 1 else 0
    min_return = min(returns)
    max_return = max(returns)

    avg_win_rate = statistics.mean(win_rates)
    avg_trades = statistics.mean(trade_counts)

    print(f"평균 수익률: {avg_return:.2f}%")
    print(f"표준편차: {std_return:.2f}%")
    print(f"최고의 해: {max_return:+.2f}% ({years[returns.index(max_return)]})")
    print(f"최악의 해: {min_return:+.2f}% ({years[returns.index(min_return)]})")
    print(f"평균 승률: {avg_win_rate:.1f}%")
    print(f"평균 거래: {avg_trades:.1f}회/년")

    if buyhold_returns:
        avg_buyhold = statistics.mean(buyhold_returns)
        diff = avg_return - avg_buyhold
        print(f"\n평균 Buy&Hold: {avg_buyhold:.2f}%")
        print(f"차이: {diff:+.2f}%p")

    # Out-of-Sample 검증 (2025 vs 2022-2024)
    print(f"\n{'='*80}")
    print("Out-of-Sample 검증 (2025 vs 2022-2024)")
    print(f"{'='*80}\n")

    if 2025 in results and len([y for y in years if y < 2025 and y in results]) >= 2:
        train_years = [y for y in years if y < 2025 and y in results]
        train_returns = [results[y]['total_return'] for y in train_years]
        train_win_rates = [results[y]['win_rate'] for y in train_years]

        avg_train_return = statistics.mean(train_returns)
        avg_train_win_rate = statistics.mean(train_win_rates)

        test_return = results[2025]['total_return']
        test_win_rate = results[2025]['win_rate']

        threshold_return = avg_train_return * 0.8
        threshold_win_rate = avg_train_win_rate - 15

        print(f"학습 기간 ({', '.join(map(str, train_years))}):")
        print(f"  평균 수익률: {avg_train_return:.2f}%")
        print(f"  평균 승률: {avg_train_win_rate:.1f}%")

        print(f"\n검증 기간 (2025):")
        print(f"  수익률: {test_return:+.2f}%")
        print(f"  승률: {test_win_rate:.1f}%")

        print(f"\n검증 기준:")
        print(f"  수익률 >= {threshold_return:.2f}%? ", end="")
        if test_return >= threshold_return:
            print("✅ 통과")
        else:
            print(f"❌ 실패 ({test_return - threshold_return:+.2f}%p 부족)")

        print(f"  승률 >= {threshold_win_rate:.1f}%? ", end="")
        if test_win_rate >= threshold_win_rate:
            print("✅ 통과")
        else:
            print(f"❌ 실패 ({test_win_rate - threshold_win_rate:+.1f}%p 부족)")

        overfitting = test_return < threshold_return or test_win_rate < threshold_win_rate

        print(f"\n최종 판정: ", end="")
        if overfitting:
            print("❌ 오버피팅 의심, 전략 폐기 권장")
        else:
            print("✅ Out-of-Sample 검증 통과")

    # 목표 달성 여부
    print(f"\n{'='*80}")
    print("목표 달성 여부")
    print(f"{'='*80}\n")

    if buyhold_returns:
        avg_buyhold = statistics.mean(buyhold_returns)
        target = avg_buyhold + 15
        achieved = avg_return >= target

        print(f"4년 평균 수익률: {avg_return:.2f}%")
        print(f"평균 Buy&Hold: {avg_buyhold:.2f}%")
        print(f"목표 (BH + 15%p): {target:.2f}%")
        print(f"차이: {avg_return - target:+.2f}%p")
        print(f"\n최종: ", end="")
        if achieved:
            print("✅ 목표 달성!")
        else:
            print(f"❌ 목표 미달 ({target - avg_return:.2f}%p 부족)")

    # 마크다운 리포트 생성
    report_path = strategy_path / "multi_year_analysis.md"
    generate_markdown_report(report_path, results, years, avg_return, std_return, avg_buyhold if buyhold_returns else None)

    print(f"\n📄 리포트 생성: {report_path}")


def generate_markdown_report(path, results, years, avg_return, std_return, avg_buyhold):
    """마크다운 리포트 생성"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write("# Multi-Year Analysis Report\n\n")

        f.write("## 📊 연도별 성과\n\n")
        f.write("| 연도 | 수익률 | 승률 | 거래 | Buy&Hold | 차이 |\n")
        f.write("|------|--------|------|------|----------|------|\n")

        for year in years:
            if year not in results:
                continue

            r = results[year]
            buyhold_str = f"{r['buyhold']:+.2f}%" if r['buyhold'] else "N/A"
            diff_str = f"{r['diff']:+.2f}%p" if r['diff'] else "N/A"

            f.write(f"| {year} | {r['total_return']:+.2f}% | {r['win_rate']:.1f}% | {r['total_trades']}회 | {buyhold_str} | {diff_str} |\n")

        f.write(f"\n## 📈 4년 통합 통계\n\n")
        f.write(f"- **평균 수익률**: {avg_return:.2f}%\n")
        f.write(f"- **표준편차**: {std_return:.2f}%\n")

        if avg_buyhold:
            f.write(f"- **평균 Buy&Hold**: {avg_buyhold:.2f}%\n")
            f.write(f"- **차이**: {avg_return - avg_buyhold:+.2f}%p\n")

        f.write(f"\n## ✅ 목표 달성 여부\n\n")

        if avg_buyhold:
            target = avg_buyhold + 15
            achieved = avg_return >= target
            status = "✅ 달성" if achieved else "❌ 미달"
            f.write(f"- **목표**: {target:.2f}% (평균 BH + 15%p)\n")
            f.write(f"- **실제**: {avg_return:.2f}%\n")
            f.write(f"- **상태**: {status}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Multi-Year Results Analyzer"
    )
    parser.add_argument(
        "--strategy",
        type=str,
        help="전략 이름 (예: v17_vwap_breakout)"
    )
    parser.add_argument(
        "--strategy-path",
        type=str,
        help="전략 경로 (예: strategies/v17_vwap_breakout)"
    )

    args = parser.parse_args()

    if args.strategy_path:
        strategy_path = Path(args.strategy_path)
    elif args.strategy:
        strategy_path = Path(f"strategies/{args.strategy}")
    else:
        print("❌ --strategy 또는 --strategy-path 필요")
        sys.exit(1)

    if not strategy_path.exists():
        print(f"❌ 전략 폴더를 찾을 수 없습니다: {strategy_path}")
        sys.exit(1)

    analyze_multi_year(strategy_path)


if __name__ == "__main__":
    main()
