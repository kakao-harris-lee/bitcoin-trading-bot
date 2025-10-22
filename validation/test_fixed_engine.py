#!/usr/bin/env python3
"""
수정된 엔진 테스트 스크립트
"""

import sys
import json
from pathlib import Path

# 엔진 임포트
from universal_evaluation_engine import UniversalEvaluationEngine

def test_strategy(strategy_name):
    """단일 전략 테스트"""

    strategy_dir = Path(f"strategies/validation/{strategy_name}")

    # Config 로드
    config_file = strategy_dir / "evaluation" / "config.json"
    with open(config_file, 'r') as f:
        config = json.load(f)

    print(f"\n{'='*80}")
    print(f"Testing: {strategy_name}")
    print(f"{'='*80}\n")

    # 엔진 초기화
    engine = UniversalEvaluationEngine(
        initial_capital=10_000_000,
        fee_rate=0.0005,
        slippage=0.0004
    )

    # 평가 실행
    signals_dir = strategy_dir / "signals"

    results = engine.evaluate_all_combinations(
        signals_dir=signals_dir,
        evaluation_config=config,
        parallel=False
    )

    # 결과 출력
    print(f"\n✅ Evaluation complete!")
    print(f"\nBest period: {results['optimization']['best_period']}")
    print(f"Training avg:")
    print(f"  - Sharpe: {results['optimization']['training_avg']['avg_sharpe']:.2f}")
    print(f"  - Return: {results['optimization']['training_avg']['avg_return_pct']:.2f}%")
    print(f"  - Trades: {results['optimization']['training_avg']['avg_trades']:.0f}")

    # 최적 period 상세 정보
    best_period = results['optimization']['best_period']
    best_key = f"2024_{best_period}"

    if best_key in results['full_matrix']:
        best_stats = results['full_matrix'][best_key]
        print(f"\nBest period stats ({best_period}):")
        print(f"  - Win rate: {best_stats['win_rate']:.2f}%")
        print(f"  - Avg return: {best_stats['avg_return']:.2f}%")
        print(f"  - Winning trades: {best_stats['winning_trades']}")
        print(f"  - Losing trades: {best_stats['losing_trades']}")
        print(f"  - Total return: {best_stats['total_return_pct']:.2f}%")
        print(f"  - Sharpe: {best_stats['sharpe_ratio']:.2f}")

    # 결과 저장
    output_file = strategy_dir / "evaluation" / "full_matrix_fixed.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n📄 Results saved: {output_file}")

    return results

if __name__ == '__main__':
    # 3개 전략 테스트
    strategies = ['v_simple_rsi', 'v_momentum', 'v_volume_spike']

    all_results = {}

    for strategy in strategies:
        try:
            results = test_strategy(strategy)
            all_results[strategy] = results
        except Exception as e:
            print(f"\n❌ Error testing {strategy}: {e}")
            import traceback
            traceback.print_exc()

    # 비교 요약
    print(f"\n\n{'='*80}")
    print("COMPARISON SUMMARY")
    print(f"{'='*80}\n")

    print(f"{'Strategy':<20} {'Win Rate':<12} {'Avg Return':<12} {'Total Return':<12} {'Sharpe':<10}")
    print(f"{'-'*80}")

    for strategy, results in all_results.items():
        best_period = results['optimization']['best_period']
        best_key = f"2024_{best_period}"

        if best_key in results['full_matrix']:
            stats = results['full_matrix'][best_key]
            print(f"{strategy:<20} {stats['win_rate']:>10.2f}% {stats['avg_return']:>10.2f}% {stats['total_return_pct']:>10.2f}% {stats['sharpe_ratio']:>10.2f}")
