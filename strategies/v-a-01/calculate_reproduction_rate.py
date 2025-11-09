#!/usr/bin/env python3
"""
v-a-01 재현율 계산
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
sys.path.insert(0, str(Path(__file__).parent / 'utils'))
from reproduction_calculator import ReproductionCalculator
from perfect_signal_loader import PerfectSignalLoader

def main():
    print("=" * 70)
    print("v-a-01 재현율 계산")
    print("=" * 70)
    print()

    # 1. 완벽한 시그널 로드
    print("📈 Loading perfect signals...")
    loader = PerfectSignalLoader()
    perfect_signals = loader.load_perfect_signals('day', 2024)
    perfect_stats = loader.analyze_perfect_signals(perfect_signals)

    print(f"   Perfect signals: {len(perfect_signals)}개")
    print(f"   Perfect avg return: {perfect_stats['avg_return']:.2%}")
    print()

    # 2. v-a-01 시그널 로드
    print("📊 Loading v-a-01 signals...")
    with open('signals/day_2024_signals.json', 'r') as f:
        strategy_data = json.load(f)

    strategy_signals_count = strategy_data['total_signals']
    print(f"   Strategy signals: {strategy_signals_count}개")
    print()

    # 3. v-a-01 백테스팅 결과 로드
    print("💰 Loading backtest results...")
    with open('results/universal_evaluation/evaluation_report.json', 'r') as f:
        backtest_report = json.load(f)

    best_period = backtest_report['optimization']['best_period']
    best_result = backtest_report['full_matrix'][f'2024_{best_period}']
    strategy_return_pct = best_result['total_return_pct'] / 100  # % → decimal

    print(f"   Best holding period: {best_period}")
    print(f"   Strategy return: {strategy_return_pct:.2%}")
    print()

    # 4. 시그널 매칭 (분석 파일에서 가져옴)
    print("🔍 Loading signal matching results...")
    with open('analysis/day_2024_analysis.json', 'r') as f:
        analysis = json.load(f)

    signal_reproduction_rate = analysis['strategy_signals']['signal_reproduction_rate']
    matched_count = analysis['strategy_signals']['matched_count']

    print(f"   Matched signals: {matched_count}/{len(perfect_signals)}")
    print(f"   Signal reproduction: {signal_reproduction_rate:.2%}")
    print()

    # 5. 재현율 계산
    print("📊 Calculating reproduction rate...")
    calc = ReproductionCalculator(tolerance_days=1)

    # 수익 재현율
    perfect_return = perfect_stats['avg_return']
    if perfect_return > 0:
        return_reproduction_rate = min(strategy_return_pct / perfect_return, 1.0)
    else:
        return_reproduction_rate = 0.0

    # 종합 재현율
    total_reproduction_rate = (signal_reproduction_rate * 0.4) + (return_reproduction_rate * 0.6)

    # Tier 분류
    tier = calc._classify_tier(total_reproduction_rate)

    print(f"   Signal reproduction: {signal_reproduction_rate:.2%} (가중 {signal_reproduction_rate * 0.4:.2%})")
    print(f"   Return reproduction: {return_reproduction_rate:.2%} (가중 {return_reproduction_rate * 0.6:.2%})")
    print(f"   Total reproduction: {total_reproduction_rate:.2%}")
    print(f"   Tier: {tier}")
    print()

    # 6. 상세 분석
    print("=" * 70)
    print("📊 Detailed Analysis")
    print("=" * 70)
    print()

    print("[Perfect Signals]")
    print(f"  Total: {len(perfect_signals)}개")
    print(f"  Avg Return: {perfect_return:.2%}")
    print(f"  Avg Hold: {perfect_stats['avg_hold_days']:.1f}일")
    print()

    print("[v-a-01 Strategy]")
    print(f"  Generated Signals: {strategy_signals_count}개")
    print(f"  Matched Signals: {matched_count}개 ({signal_reproduction_rate:.2%})")
    print(f"  Actual Return: {strategy_return_pct:.2%}")
    print(f"  Best Period: {best_period}")
    print(f"  Win Rate: {best_result['win_rate']:.1f}%")
    print(f"  Sharpe Ratio: {best_result['sharpe_ratio']:.2f}")
    print()

    print("[Reproduction Metrics]")
    print(f"  Signal Reproduction: {signal_reproduction_rate:.2%}")
    print(f"  Return Reproduction: {return_reproduction_rate:.2%}")
    print(f"  Total Reproduction: {total_reproduction_rate:.2%}")
    print(f"  Tier: {tier}")
    print()

    # Tier 해석
    tier_description = {
        'S': '✅ 배포 가능 (70%+)',
        'A': '⚠️  최적화 필요 (50-70%)',
        'B': '⚠️  재설계 필요 (30-50%)',
        'C': '❌ 폐기 (<30%)'
    }

    print(f"[{tier}-Tier] {tier_description.get(tier, 'Unknown')}")
    print()

    # 7. 결과 저장
    result = {
        'strategy': 'v-a-01',
        'timeframe': 'day',
        'year': 2024,
        'perfect_signals': {
            'total': len(perfect_signals),
            'avg_return': float(perfect_return),
            'avg_hold_days': float(perfect_stats['avg_hold_days'])
        },
        'strategy_signals': {
            'total': strategy_signals_count,
            'matched': matched_count,
            'signal_reproduction_rate': float(signal_reproduction_rate)
        },
        'strategy_performance': {
            'best_period': best_period,
            'return_pct': float(strategy_return_pct),
            'win_rate': best_result['win_rate'],
            'sharpe_ratio': best_result['sharpe_ratio'],
            'total_trades': best_result['total_trades']
        },
        'reproduction_metrics': {
            'signal_reproduction_rate': float(signal_reproduction_rate),
            'return_reproduction_rate': float(return_reproduction_rate),
            'total_reproduction_rate': float(total_reproduction_rate),
            'tier': tier,
            'tier_description': tier_description.get(tier, 'Unknown')
        }
    }

    output_file = 'results/reproduction_rate.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"💾 Reproduction rate saved: {output_file}")
    print()

    return result

if __name__ == '__main__':
    main()
